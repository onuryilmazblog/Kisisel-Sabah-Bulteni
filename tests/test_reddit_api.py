"""Reddit Data API adaptörü: elle hazırlanmış Listing JSON'u, OAuth token, hız sınırı, eksik kimlik bilgileri.

Canlı Reddit'e karşı çalıştırılmadı; yanıtlar Reddit API belgelerindeki Listing/t3 yapısına göre elle
hazırlandı (bkz. helpers.reddit_listing).
"""
from __future__ import annotations

import json

import pytest
from helpers import (
    REDDIT_TOKEN, FakeFetcher, enable_reddit_api, freeze, make_db, only_sources, reddit_listing, rss_feed,
)

from bulten.net.fetcher import FetchError
from bulten.pipeline.evidence import effective_trust, evidence_for_observation
from bulten.settings_store import get_settings
from bulten.sources import reddit_api
from bulten.sources.base import AdapterContext, SourceRow
from bulten.sources.registry import seed_sources
from bulten.sources.rss import parse_feed

SYSADMIN = reddit_api.listing_url("sysadmin")

POSTS = [
    {"title": "KB5999100 broke RDP on Server 2025", "link": "https://www.reddit.com/r/sysadmin/comments/abc1/kb5999100/",
     "desc": "Remote desktop fails after the update on our Windows Server 2025 session hosts.", "author": "u/admin1",
     "date": "Thu, 24 Sep 2026 09:00:00 GMT", "flair": "General Windows"},
    {"title": "Which monitor should I buy?", "link": "https://www.reddit.com/r/sysadmin/comments/abc2/monitor/",
     "desc": "Advice please", "author": "u/b", "date": "Thu, 24 Sep 2026 08:00:00 GMT"},
    {"title": "Windows 11 tips thread", "link": "https://www.reddit.com/r/sysadmin/comments/abc3/tips/",
     "desc": "Share your tips", "author": "u/c", "date": "Thu, 24 Sep 2026 07:00:00 GMT"},
    {"title": "Intune compliance policy broken after KB5999100", "link": "https://www.reddit.com/r/sysadmin/comments/abc4/x/",
     "desc": "[removed]", "author": "u/d", "date": "Thu, 24 Sep 2026 06:00:00 GMT", "removed": "moderator"},
    {"title": "KB5990001 broke printing on Windows 11", "link": "https://www.reddit.com/r/sysadmin/comments/old1/x/",
     "desc": "Old report.", "author": "u/e", "date": "Mon, 14 Sep 2026 06:00:00 GMT"},
]


def _source(conn, slug="reddit-sysadmin") -> SourceRow:
    return SourceRow.from_row(conn.execute("SELECT * FROM sources WHERE slug = ?", (slug,)).fetchone())


def _ctx(conn, ff) -> AdapterContext:
    return AdapterContext(conn=conn, fetcher=ff, settings=get_settings(conn))


def test_listing_maps_posts_like_rss_adapter(tmp_path):
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path)
    cfg = enable_reddit_api(conn)
    ff = FakeFetcher(pages={SYSADMIN: reddit_listing(POSTS), **REDDIT_TOKEN})
    src = _source(conn)
    res = reddit_api.run_reddit_api(src, _ctx(conn, ff))

    assert res.structure_ok and res.fetched_url == SYSADMIN
    (o,) = res.observations  # kapsam dışı, sorun bildirimi olmayan, kaldırılmış ve 4 günden eski gönderiler alınmaz
    assert o.external_key == "reddit:t3_abc1" and o.kind == "field_report"
    assert o.url == "https://www.reddit.com/r/sysadmin/comments/abc1/kb5999100/"
    assert o.published_at.startswith("2026-09-24T09:00")
    f = o.fields
    assert f["author"] == "u/admin1" and f["trust"] == "community" and f["kbs"] == ["5999100"]
    assert "rds" in f["tags"] and "ws2025" in f["products"]
    assert f["categories"] == ["r/sysadmin", "General Windows"]

    # Aynı gönderiler RSS adaptöründen geçseydi aynı alanlar üretilirdi (kategoriler hariç: RSS'te yok).
    rss_obs = parse_feed(rss_feed(POSTS[:3]), source=src, max_age_days=4).observations
    assert len(rss_obs) == 1
    rf = rss_obs[0].fields
    assert set(rf) == set(f)
    assert {k: f[k] for k in f if k != "categories"} == {k: rf[k] for k in rf if k != "categories"}
    assert (o.kind, o.title, o.url, o.body) == (rss_obs[0].kind, rss_obs[0].title, rss_obs[0].url, rss_obs[0].body)

    # OAuth: client credentials + HTTP Basic token isteği; listing isteği bearer token ve Reddit User-Agent'ı taşır.
    (m1, u1, k1), (m2, u2, k2) = ff.requests
    assert (m1, u1) == ("POST", reddit_api.TOKEN_URL)
    assert k1["data"] == {"grant_type": "client_credentials"} and k1["auth"] == (cfg.reddit_client_id,
                                                                                 cfg.reddit_client_secret)
    assert k1["extra_headers"]["User-Agent"] == cfg.reddit_user_agent
    assert (m2, u2) == ("GET", SYSADMIN) and k2["api"] is True and k2["use_cache"] is False
    assert k2["extra_headers"] == {"User-Agent": cfg.reddit_user_agent, "Authorization": "bearer test-token"}

    # Topluluk gönderisi asla resmî kanıt olmaz (kaynak satırı "official" olarak değiştirilmiş olsa bile).
    assert effective_trust("official", o.url) == "community"
    assert evidence_for_observation(o.kind, effective_trust(src.trust, o.url)) == "field"


def test_token_is_reused_and_refreshed_once_on_401(tmp_path):
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path)
    enable_reddit_api(conn)

    class ExpiringFetcher(FakeFetcher):
        fail_next_get = False

        def get(self, url, **kwargs):
            if self.fail_next_get:
                self.fail_next_get = False
                self.requests.append(("GET", url, kwargs))
                raise FetchError("HTTP 401", kind="http", status=401, retryable=False, url=url)
            return super().get(url, **kwargs)

    ff = ExpiringFetcher(pages={SYSADMIN: reddit_listing(POSTS[:1]), **REDDIT_TOKEN})
    src = _source(conn)
    reddit_api.run_reddit_api(src, _ctx(conn, ff))
    reddit_api.run_reddit_api(src, _ctx(conn, ff))
    assert [m for m, _, _ in ff.requests] == ["POST", "GET", "GET"], "token her istekte yeniden alınmamalı"
    ff.fail_next_get = True
    res = reddit_api.run_reddit_api(src, _ctx(conn, ff))
    assert len(res.observations) == 1
    assert [m for m, _, _ in ff.requests][3:] == ["GET", "POST", "GET"], "401 sonrası token bir kez yenilenir"


def test_bad_credentials_report_clear_error_without_secret(tmp_path):
    conn = make_db(tmp_path)
    cfg = enable_reddit_api(conn)

    class Rejecting(FakeFetcher):
        def post(self, url, **kwargs):
            raise FetchError("HTTP 401", kind="http", status=401, retryable=False, url=url)

    with pytest.raises(FetchError) as exc:
        reddit_api.run_reddit_api(_source(conn), _ctx(conn, Rejecting()))
    assert exc.value.status == 401 and "REDDIT_CLIENT_SECRET" in str(exc.value)
    assert cfg.reddit_client_secret not in str(exc.value)


def test_rate_limit_headers_are_respected(tmp_path):
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path)
    enable_reddit_api(conn, ["reddit-sysadmin", "reddit-intune"])
    intune = reddit_api.listing_url("Intune")
    ff = FakeFetcher(pages={SYSADMIN: reddit_listing([]), intune: reddit_listing([], "Intune"), **REDDIT_TOKEN},
                     headers={SYSADMIN: {"x-ratelimit-used": "99", "x-ratelimit-remaining": "1.0",
                                         "x-ratelimit-reset": "120"}})
    reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff))
    with pytest.raises(FetchError) as exc:
        reddit_api.run_reddit_api(_source(conn, "reddit-intune"), _ctx(conn, ff))
    assert exc.value.status == 429 and "hız sınırı" in str(exc.value) and not exc.value.retryable
    assert intune not in ff.calls, "sınır dolmak üzereyken istek gönderilmemeli"


def test_http_429_is_not_retried(tmp_path):
    conn = make_db(tmp_path)
    enable_reddit_api(conn)

    class Limited(FakeFetcher):
        def get(self, url, **kwargs):
            self.requests.append(("GET", url, kwargs))
            raise FetchError("HTTP 429", kind="http", status=429, url=url,
                             headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "300"})

    ff = Limited(pages=dict(REDDIT_TOKEN))
    with pytest.raises(FetchError) as exc:
        reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff))
    assert exc.value.status == 429 and "300 sn" in str(exc.value)
    assert [m for m, _, _ in ff.requests] == ["POST", "GET"], "429 yanıtı hemen yeniden denenmemeli"
    with pytest.raises(FetchError):
        reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff))
    assert len(ff.requests) == 2, "sıfırlanma zamanına kadar yeni istek yok"


def test_unexpected_structure_is_not_no_news(tmp_path):
    conn = make_db(tmp_path)
    enable_reddit_api(conn)
    ff = FakeFetcher(pages={SYSADMIN: json.dumps({"error": 500, "message": "oops"}), **REDDIT_TOKEN})
    res = reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff))
    assert not res.structure_ok and res.warnings and res.observations == []


def test_pagination_stops_at_cutoff(tmp_path):
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path)
    enable_reddit_api(conn)
    page2 = reddit_api.listing_url("sysadmin", after="t3_abc3")
    ff = FakeFetcher(pages={SYSADMIN: reddit_listing(POSTS[:3], after="t3_abc3"),
                            page2: reddit_listing(POSTS[3:], after="t3_old1"), **REDDIT_TOKEN})
    res = reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff))
    assert [o.external_key for o in res.observations] == ["reddit:t3_abc1"]
    assert ff.calls.count(page2) == 1 and len([u for u in ff.calls if "oauth" in u]) == 2


def test_missing_credentials_never_mean_no_new_issues(tmp_path, capsys):
    """Kimlik bilgisi yoksa Reddit kaynakları kapalıdır; açılırsa her kontrol "hata" olarak kaydedilir,
    bültende kapsam uyarısı çıkar ve `kaynak-dogrula` "yapılandırılmadı" der (asla "başarılı" değil)."""
    from bulten.cli import main
    from bulten.delivery.render import telegram_bulletin_messages
    from bulten.pipeline.bulletin import compose_bulletin, coverage
    from bulten.pipeline.run import collect_and_process
    from bulten.pipeline.validate import validate_source

    freeze(2026, 9, 24, 5)
    conn = make_db(tmp_path)
    rows = {r["slug"]: r for r in conn.execute("SELECT * FROM sources WHERE adapter = 'reddit_api'")}
    assert set(rows) == {"reddit-sysadmin", "reddit-intune", "reddit-sccm"}
    assert all(r["enabled"] == 0 and "yapılandırılmadı" in r["validation_note"] for r in rows.values())

    ff = FakeFetcher()
    v = validate_source(conn, _source(conn), fetcher=ff)
    assert not v["ok"] and v["not_configured"] and "yapılandırılmadı" in v["error"]
    assert "REDDIT_CLIENT_ID" in v["error"] and ff.calls == [], "kimlik bilgisi yokken ağa çıkılmaz"

    # Kullanıcı kaynağı arayüzden açsa bile sonuç "0 kayıt, başarılı" olmamalı.
    conn.execute("UPDATE sources SET enabled = 1 WHERE slug = 'reddit-sysadmin'")
    collect_and_process(conn, fetcher=ff, source_ids=only_sources(conn, ["reddit-sysadmin"]))
    check = conn.execute("SELECT * FROM source_checks WHERE source_id = ? ORDER BY id DESC",
                         (rows["reddit-sysadmin"]["id"],)).fetchone()
    assert check["status"] == "error" and "yapılandırılmadı" in check["error"]
    assert "r/sysadmin" in [f["name"] for f in coverage(conn)["failing"]]
    bid = compose_bulletin(conn, kind="manual")
    head = telegram_bulletin_messages(conn, bid)[0]["text"]
    assert "r/sysadmin" in head and "yeni sorun olmadığı anlamına gelmez" in head

    capsys.readouterr()
    with pytest.raises(SystemExit) as exc:
        main(["kaynak-dogrula", "--slug", "reddit-intune"])  # kapalı kaynak da slug ile istenince denenir
    out = capsys.readouterr().out
    assert exc.value.code == 1
    assert "[YAPILANDIRILMADI] reddit-intune" in out and "0/1 kaynak doğrulandı" in out and "[OK" not in out


def test_credentials_switch_builtin_sources_on_and_off(tmp_path):
    from bulten.db import kv_set

    conn = make_db(tmp_path)

    def state():
        return {r["slug"]: (r["adapter"], r["enabled"], r["validation_note"]) for r in conn.execute(
            "SELECT slug, adapter, enabled, validation_note FROM sources WHERE slug LIKE 'reddit-%'")}

    # Eski kurulum (BUILTIN_REV 2): RSS tanımı, robots.txt nedeniyle kapalı.
    conn.execute("UPDATE sources SET adapter = 'rss', url = 'https://www.reddit.com/r/sysadmin/new/.rss', enabled = 0 "
                 "WHERE slug LIKE 'reddit-%'")
    conn.execute("DELETE FROM kv WHERE key = 'builtin_sources_requirements'")
    kv_set(conn, "builtin_sources_rev", "2")
    seed_sources(conn)
    assert all(a == "reddit_api" and e == 0 and "yapılandırılmadı" in n for a, e, n in state().values())

    # Kimlik bilgileri tanımlandı: kaynaklar açılır, not güncellenir.
    enable_reddit_api()
    seed_sources(conn)
    assert all(a == "reddit_api" and e == 1 and "Data API" in n and "yapılandırılmadı" not in n
               for a, e, n in state().values())
    url = conn.execute("SELECT url FROM sources WHERE slug = 'reddit-sccm'").fetchone()[0]
    assert url == "https://www.reddit.com/r/SCCM/new/"

    # Kullanıcının kapattığı kaynak, yapılandırma değişmedikçe kapalı kalır.
    conn.execute("UPDATE sources SET enabled = 0 WHERE slug = 'reddit-sccm'")
    seed_sources(conn)
    assert state()["reddit-sccm"][1] == 0 and state()["reddit-sysadmin"][1] == 1

    # Kimlik bilgileri kaldırıldı: kaynaklar kapanır ve not "yapılandırılmadı" olur.
    enable_reddit_api().reddit_client_secret = ""
    seed_sources(conn)
    assert all(e == 0 and "REDDIT_CLIENT_SECRET" in n for _, e, n in state().values())


def test_redirect_to_other_page_is_an_error_not_empty_listing(tmp_path):
    from bulten.net.fetcher import FetchResult
    from bulten.timeutil import now_iso

    conn = make_db(tmp_path)
    enable_reddit_api(conn)

    class Redirecting(FakeFetcher):
        def get(self, url, **kwargs):
            self.requests.append(("GET", url, kwargs))
            final = self.target
            return FetchResult(url=final, status=200, text=reddit_listing([]), content_type="application/json",
                               fetched_at=now_iso())

    ff = Redirecting(pages=dict(REDDIT_TOKEN))
    ff.target = "https://oauth.reddit.com/r/Sysadmin/new/?limit=100&raw_json=1"  # yalnızca yazım farkı: sorun değil
    assert reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff)).structure_ok
    ff.target = "https://oauth.reddit.com/subreddits/search?q=sysadmin"
    with pytest.raises(FetchError) as exc:
        reddit_api.run_reddit_api(_source(conn), _ctx(conn, ff))
    assert "yönlendirdi" in str(exc.value)
