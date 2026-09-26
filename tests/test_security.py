"""Güvenlik: SSRF, güven sınıflandırması, Telegram yetkilendirmesi, kaynak ekleme kısıtları."""
from __future__ import annotations

import socket

import pytest
from helpers import freeze, make_db

from bulten.net.fetcher import Fetcher, FetchError
from bulten.net.ssrf import UnsafeURL, ip_is_public, resolve_public, validate_url_syntax
from bulten.pipeline.evidence import classify_url, count_independent, effective_trust
from bulten.web.forms import FormError, add_user_source


@pytest.mark.parametrize("url", [
    "http://127.0.0.1/", "http://localhost/feed", "http://10.0.0.5/rss", "http://192.168.1.1/", "http://172.16.3.4/",
    "http://169.254.169.254/latest/meta-data/", "http://[::1]/", "http://[fd00::1]/", "http://100.64.1.1/",
    "ftp://example.com/feed", "file:///etc/passwd", "http://user:pass@example.com/", "http://example.com:8080/",
    "http://intranet/", "http://printer.local/", "http://0.0.0.0/", "gopher://example.com/",
])
def test_ssrf_rejects_private_and_odd_urls(url):
    with pytest.raises(UnsafeURL):
        validate_url_syntax(url)


def test_ssrf_dns_resolution_checked(monkeypatch):
    def fake_getaddrinfo(host, port, type=0):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.1.2.3", port))]
    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(UnsafeURL):
        resolve_public("rebinding.example.com", 443)
    assert ip_is_public("8.8.8.8") and not ip_is_public("::ffff:127.0.0.1")


def test_fetcher_blocks_user_url_to_private_network(tmp_path, monkeypatch):
    for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"):
        monkeypatch.delenv(k, raising=False)
    conn = make_db(tmp_path)
    monkeypatch.setattr(socket, "getaddrinfo",
                        lambda host, port, type=0: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.10", port))])
    f = Fetcher(conn, respect_robots=False)
    with pytest.raises(FetchError) as exc:
        f.get("https://looks-public.example.com/feed")
    assert exc.value.kind == "blocked"


def test_robots_applies_to_pages_but_not_documented_apis(tmp_path):
    """api.open-meteo.com tarayıcılara "Disallow: /" döndürür; belgelenmiş API çağrısı engellenmemeli,
    sayfa/besleme okuması ise robots.txt'ye uymalı (Reddit, Webrazzi /feed/ gibi)."""
    import httpx

    conn = make_db(tmp_path)
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /\n")
        return httpx.Response(200, json={"ok": True})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    f = Fetcher(conn, client=client, min_host_interval=0)
    res = f.get("https://api.example.com/v1/forecast?latitude=1", trusted=True, api=True, use_cache=False)
    assert res.status == 200 and "/robots.txt" not in seen
    with pytest.raises(FetchError) as exc:
        f.get("https://api.example.com/feed/", trusted=True)
    assert exc.value.kind == "robots" and seen.count("/v1/forecast") == 1 and "/feed/" not in seen


def test_credentials_not_forwarded_on_cross_origin_redirect_and_post_does_not_follow(tmp_path):
    """Bearer token (ör. Reddit API) başka bir ana bilgisayara yönlendirmede gönderilmemeli; OAuth token
    isteği (POST) yönlendirme izlememeli ve robots.txt'ye bakmamalı; 429 yanıt başlıkları korunmalı."""
    import httpx

    conn = make_db(tmp_path)
    seen: list[tuple[str, str, str | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, f"{request.url.host}{request.url.path}", request.headers.get("authorization")))
        if request.url.path == "/same":
            return httpx.Response(302, headers={"location": "/final"})
        if request.url.path == "/cross":
            return httpx.Response(302, headers={"location": "https://other.example/final"})
        if request.url.path == "/token":
            return httpx.Response(307, headers={"location": "https://other.example/token"})
        if request.url.path == "/limited":
            return httpx.Response(429, headers={"x-ratelimit-remaining": "0", "x-ratelimit-reset": "42"})
        return httpx.Response(200, json={"ok": True})

    f = Fetcher(conn, client=httpx.Client(transport=httpx.MockTransport(handler)), min_host_interval=0)
    auth = {"Authorization": "bearer secret-token"}
    f.get("https://api.example/same", trusted=True, api=True, use_cache=False, extra_headers=auth)
    assert seen[-1] == ("GET", "api.example/final", "bearer secret-token")
    f.get("https://api.example/cross", trusted=True, api=True, use_cache=False, extra_headers=auth)
    assert seen[-1] == ("GET", "other.example/final", None)

    with pytest.raises(FetchError) as exc:
        f.post("https://api.example/token", data={"grant_type": "client_credentials"}, auth=("id", "secret"),
               trusted=True)
    assert exc.value.status == 307 and seen[-1][:2] == ("POST", "api.example/token")
    assert seen[-1][2].startswith("Basic ") and not any(h.startswith("other.example/token") for _, h, _ in seen)
    assert not any(h.endswith("/robots.txt") for _, h, _ in seen)

    with pytest.raises(FetchError) as exc:
        f.get("https://api.example/limited", trusted=True, api=True, use_cache=False, retries=0)
    assert exc.value.status == 429 and exc.value.headers["x-ratelimit-reset"] == "42"


def test_microsoft_community_pages_are_not_official():
    assert classify_url("https://learn.microsoft.com/en-us/answers/questions/123/kb-issue") == "community"
    assert classify_url("https://answers.microsoft.com/en-us/windows/forum/x") == "community"
    assert classify_url("https://techcommunity.microsoft.com/discussions/windows/x/123") == "community"
    assert classify_url("https://techcommunity.microsoft.com/t5/windows-10/some-post/m-p/12345") == "community"
    assert classify_url("https://techcommunity.microsoft.com/blog/intunecustomersuccess/known-issue/4400000") == "official"
    assert classify_url("https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-25h2") == "official"
    assert classify_url("https://www.bleepingcomputer.com/news/x") == "press"
    # Resmî bir besleme bile topluluk URL'sine işaret ediyorsa resmî sayılmaz.
    assert effective_trust("official", "https://learn.microsoft.com/en-us/answers/questions/1/x") == "community"


def test_syndicated_copies_are_not_independent():
    base = ("Microsoft confirmed that the September update KB5999100 causes Remote Desktop connections to drop on "
            "Windows Server 2025 session hosts after several minutes of use.")
    items = [
        {"url": "https://a.example/1", "title": "RDP drops after KB5999100", "body": base, "trust": "press"},
        {"url": "https://b.example/2", "title": "KB5999100 RDP issue", "body": base + " Via a.example.", "trust": "press"},
        {"url": "https://www.reddit.com/r/sysadmin/1", "title": "RDP dies every 5 min since last night",
         "body": "Our RDS farm is dropping sessions, anyone else?", "trust": "community", "author": "u/a"},
        {"url": "https://www.reddit.com/r/sysadmin/2", "title": "Session hosts disconnecting",
         "body": "Users kicked out of Remote Desktop constantly.", "trust": "community", "author": "u/b"},
    ]
    assert count_independent(items) == 3


def test_user_source_cannot_claim_official_or_private(tmp_path):
    conn = make_db(tmp_path)
    sid = add_user_source(conn, name="Blog", url="https://example.org/feed", module="content", category=None,
                          trust="official")
    assert conn.execute("SELECT trust FROM sources WHERE id = ?", (sid,)).fetchone()[0] == "user"
    with pytest.raises(FormError):
        add_user_source(conn, name="x", url="http://10.0.0.1/feed", module="community", category=None, trust="user")


def test_telegram_callbacks_only_from_configured_chat(tmp_path):
    from bulten.delivery.telegram import handle_update
    freeze(2026, 9, 24, 5)
    conn = make_db(tmp_path)
    conn.execute("INSERT INTO events(event_key, module, kind, title, first_seen_at, current_version) "
                 "VALUES ('x', 'windows', 'issue', 't', '2026-09-24T00:00:00+00:00', 1)")
    eid = conn.execute("SELECT id FROM events WHERE event_key = 'x'").fetchone()[0]

    class FakeClient:
        def __init__(self):
            self.answers = []

        def answer_callback(self, cid, text):
            self.answers.append(text)

        def send_message(self, *a, **k):
            pass

    c = FakeClient()
    bad = {"update_id": 1, "callback_query": {"id": "q1", "data": f"r:{eid}:1", "message": {"chat": {"id": 999}}}}
    assert handle_update(conn, c, bad) == "unauthorized"
    assert conn.execute("SELECT COUNT(*) FROM user_event_state").fetchone()[0] == 0
    good = {"update_id": 2, "callback_query": {"id": "q2", "data": f"r:{eid}:1", "message": {"chat": {"id": 1001}}}}
    assert handle_update(conn, c, good) == "r"
    assert conn.execute("SELECT read_version FROM user_event_state WHERE event_id = ?", (eid,)).fetchone()[0] == 1
    weird = {"update_id": 3, "callback_query": {"id": "q3", "data": "r:abc", "message": {"chat": {"id": 1001}}}}
    assert handle_update(conn, c, weird) == "invalid"


def test_cards_only_link_http_urls_and_news_have_sources(tmp_path):
    from bulten.pipeline.cards import build_card
    from bulten.pipeline.collect import upsert_observations
    from bulten.pipeline.run import process
    from bulten.sources.base import Observation, SourceRow
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path)
    conn.execute("INSERT INTO sources(slug, name, module, adapter, url, trust, category, enabled, builtin, critical, "
                 "config_json, created_at, updated_at) VALUES ('n1', 'Haber A', 'news', 'rss', 'https://a.example', "
                 "'press', 'genel', 1, 0, 0, '{}', 't', 't')")
    src = SourceRow.from_row(conn.execute("SELECT * FROM sources WHERE slug = 'n1'").fetchone())
    upsert_observations(conn, src, [
        Observation(external_key="rss:1", kind="article", title="Merkez Bankası faiz kararını açıkladı",
                    url="javascript:alert(1)", body="x"),
        Observation(external_key="rss:2", kind="article", title="Merkez Bankası faiz kararını açıkladı (güncellendi)",
                    url="https://a.example/faiz", body="Politika faizi sabit."),
    ], first_run=False)
    process(conn)
    vid = conn.execute("SELECT v.id FROM event_versions v JOIN events e ON e.id = v.event_id WHERE e.module = 'news'").fetchone()[0]
    card = build_card(conn, vid)
    assert card["primary_url"] == "https://a.example/faiz"
    assert all(ln["url"].startswith("http") for ln in card["links"])


def test_builtin_refresh_updates_definitions_and_disables_blocked_sources(tmp_path):
    from bulten.db import kv_set
    from bulten.sources.registry import seed_sources

    conn = make_db(tmp_path)
    # Eski sürümden kalma durum: eski adres, robots.txt'nin engellediği kaynak açık, kullanıcı bir kaynağı kapatmış.
    conn.execute("UPDATE sources SET url = 'https://support.microsoft.com/en-us/topic/old', config_json = '{}' "
                 "WHERE slug = 'ms-uh-win11-25h2'")
    conn.execute("UPDATE sources SET enabled = 1 WHERE slug IN ('reddit-sysadmin', 'news-webrazzi')")
    conn.execute("UPDATE sources SET enabled = 0 WHERE slug = 'bleepingcomputer'")
    kv_set(conn, "builtin_sources_rev", "1")
    seed_sources(conn)
    row = conn.execute("SELECT * FROM sources WHERE slug = 'ms-uh-win11-25h2'").fetchone()
    assert row["url"].startswith("https://support.microsoft.com/en-us/servicing/os/windows-11/")
    assert "Windows 11, version 25H2" in row["config_json"] and row["enabled"] == 1
    en = {r["slug"]: r["enabled"] for r in conn.execute("SELECT slug, enabled FROM sources")}
    assert en["reddit-sysadmin"] == 0 and en["news-webrazzi"] == 0
    assert en["bleepingcomputer"] == 0, "kullanıcının kapattığı kaynak kapalı kalmalı"
    # Sürüm kaydedildikten sonra tekrar yenileme yapılmaz (kullanıcı tercihine dokunulmaz).
    conn.execute("UPDATE sources SET enabled = 1 WHERE slug = 'reddit-sysadmin'")
    seed_sources(conn)
    assert conn.execute("SELECT enabled FROM sources WHERE slug = 'reddit-sysadmin'").fetchone()[0] == 1
