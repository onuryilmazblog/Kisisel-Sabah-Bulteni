"""Reddit Data API adaptörü (OAuth, yalnızca uygulama erişimi / client credentials).

Reddit'in robots.txt dosyası tüm otomatik erişimi yasaklıyor (`User-agent: *` / `Disallow: /`); uygulama
robots.txt'ye uyduğu için RSS beslemeleri okunmaz. Bunun yerine kullanıcının Reddit'te kaydettiği bir
"script" uygulamasının kimlik bilgileriyle resmî Data API kullanılır:

1. https://www.reddit.com/api/v1/access_token adresinden `grant_type=client_credentials` ile token alınır
   (HTTP Basic: client id + secret). Token yalnızca bellekte tutulur, veri tabanına yazılmaz.
2. https://oauth.reddit.com/r/<alt forum>/new okunur (`Authorization: bearer <token>`).

Reddit API kuralları uygulanır: her istekte `<platform>:<uygulama kimliği>:<sürüm> (by /u/<kullanıcı adı>)`
biçiminde açıklayıcı bir User-Agent gönderilir; OAuth istemcisi başına dakikada 100 istek sınırı için
X-Ratelimit-Remaining / X-Ratelimit-Reset başlıkları izlenir. Sınır dolmak üzereyse istek yapılmaz, 429
yanıtında yeniden denenmez; kaynak "hata" olarak kaydedilir ("yeni sorun yok" anlamına gelmez).

Gönderiler topluluk içeriğidir: güven düzeyi her zaman "community"dir ve resmî kanıt sayılmaz (bkz.
pipeline/evidence.py). Kapsam filtresi ve alanlar RSS adaptörüyle aynıdır (bkz. rss.py). Kimlik bilgileri
tanımlı değilse adaptör boş sonuç döndürmez, "yapılandırılmadı" hatası verir.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit

from ..config import Config, load_config
from ..net.fetcher import FetchError, FetchResult
from ..textutil import norm_space
from ..timeutil import now_utc, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow
from .rss import canonical_url, community_kind, guess_lang, text_fields

TOKEN_URL = "https://www.reddit.com/api/v1/access_token"
API_BASE = "https://oauth.reddit.com"
WEB_BASE = "https://www.reddit.com"
SUBREDDIT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]{1,20}$")
PAGE_LIMIT = 100
# Kalan istek hakkı bunun altına düştüyse sıfırlanma zamanına kadar istek yapılmaz.
MIN_REMAINING = 5
RETRY_DELAY = 2.0

# Süreç içi durum; worker ve web ayrı süreçlerdir ve her biri kendi token'ını alır.
_tokens: dict[str, tuple[str, float]] = {}   # client_id → (access_token, geçerlilik sonu; epoch)
_rate: dict[str, tuple[float, float]] = {}   # client_id → (kalan istek, sıfırlanma zamanı; epoch)


def reset_state() -> None:
    """Token ve hız sınırı durumunu sıfırlar (testler için)."""
    _tokens.clear()
    _rate.clear()


def listing_url(subreddit: str, *, after: str | None = None, limit: int = PAGE_LIMIT) -> str:
    params: dict[str, str | int] = {"limit": limit, "raw_json": 1}
    if after:
        params["after"] = after
    return f"{API_BASE}/r/{subreddit}/new?{urlencode(params)}"


def not_configured_message(cfg: Config) -> str:
    return ("Reddit Data API yapılandırılmadı: " + ", ".join(cfg.reddit_missing) + " tanımlı değil (.env). "
            "Reddit'in robots.txt dosyası RSS okumaya izin vermediği için bu kaynak API olmadan okunamaz.")


# -- OAuth ve hız sınırı -----------------------------------------------------------------

def _token(ctx: AdapterContext, cfg: Config) -> str:
    cached = _tokens.get(cfg.reddit_client_id)
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    try:
        res = ctx.fetcher.post(TOKEN_URL, data={"grant_type": "client_credentials"},
                               auth=(cfg.reddit_client_id, cfg.reddit_client_secret), accept="application/json",
                               extra_headers={"User-Agent": cfg.reddit_user_agent})
    except FetchError as exc:
        if exc.status in (400, 401, 403):
            raise FetchError(f"Reddit token alınamadı (HTTP {exc.status}): REDDIT_CLIENT_ID / REDDIT_CLIENT_SECRET "
                             "değerlerini ve uygulama türünün 'script' olduğunu kontrol edin.", kind="http",
                             status=exc.status, retryable=False, url=TOKEN_URL) from exc
        raise
    try:
        data = json.loads(res.text)
    except ValueError as exc:
        raise FetchError("Reddit token yanıtı JSON değil.", kind="http", status=res.status, retryable=False,
                         url=TOKEN_URL) from exc
    token = data.get("access_token") if isinstance(data, dict) else None
    if not token:
        err = data.get("error") if isinstance(data, dict) else None
        raise FetchError(f"Reddit token yanıtında access_token yok ({err or 'beklenmeyen yanıt'}).", kind="http",
                         status=res.status, retryable=False, url=TOKEN_URL)
    try:
        ttl = float(data.get("expires_in") or 3600)
    except (TypeError, ValueError):
        ttl = 3600.0
    _tokens[cfg.reddit_client_id] = (token, time.time() + ttl)
    return token


def _header_float(headers: dict, key: str) -> float | None:
    try:
        return float(headers[key])
    except (KeyError, TypeError, ValueError):
        return None


def _note_rate(cfg: Config, headers: dict) -> None:
    remaining = _header_float(headers, "x-ratelimit-remaining")
    if remaining is None:
        return
    reset = _header_float(headers, "x-ratelimit-reset") or 0.0
    _rate[cfg.reddit_client_id] = (remaining, time.time() + reset)


def _check_rate(cfg: Config) -> None:
    state = _rate.get(cfg.reddit_client_id)
    if state and state[0] < MIN_REMAINING:
        wait = state[1] - time.time()
        if wait > 0:
            raise FetchError(f"Reddit API hız sınırı doldu (kalan {state[0]:.0f} istek); {int(wait) + 1} sn "
                             "sonra yeniden denenecek.", kind="http", status=429, retryable=False, url=API_BASE)


def _api_get(ctx: AdapterContext, cfg: Config, url: str) -> FetchResult:
    refreshed = retried = False
    while True:
        _check_rate(cfg)
        headers = {"User-Agent": cfg.reddit_user_agent, "Authorization": "bearer " + _token(ctx, cfg)}
        try:
            # Belgelenmiş API: robots.txt değil Reddit'in API koşulları geçerli (api=True).
            res = ctx.fetcher.get(url, api=True, use_cache=False, retries=0, accept="application/json",
                                  extra_headers=headers)
        except FetchError as exc:
            _note_rate(cfg, exc.headers)
            if exc.status == 429:
                wait = (_header_float(exc.headers, "x-ratelimit-reset")
                        or _header_float(exc.headers, "retry-after") or 60.0)
                _rate[cfg.reddit_client_id] = (0.0, time.time() + wait)
                raise FetchError(f"Reddit API hız sınırı aşıldı (HTTP 429); {int(wait)} sn sonra yeniden "
                                 "denenecek.", kind="http", status=429, retryable=False, url=exc.url) from exc
            if exc.status == 401 and not refreshed:
                # Token süresi dolmuş veya iptal edilmiş olabilir: bir kez yenile.
                _tokens.pop(cfg.reddit_client_id, None)
                refreshed = True
                continue
            if exc.retryable and not retried:
                retried = True
                time.sleep(RETRY_DELAY)
                continue
            raise
        _note_rate(cfg, res.headers)
        if _norm_path(res.url) != _norm_path(url):
            # Ör. var olmayan alt forum için arama sayfasına yönlendirme: boş liste gibi yorumlanmamalı.
            raise FetchError(f"Reddit isteği başka bir adrese yönlendirdi ({urlsplit(res.url).path}); alt forum "
                             "bulunamadı veya erişilemiyor olabilir.", kind="http", status=res.status,
                             retryable=False, url=res.url)
        return res


def _norm_path(url: str) -> str:
    return urlsplit(url).path.rstrip("/").lower()


# -- Listing ayrıştırma ------------------------------------------------------------------

@dataclass
class ListingPage:
    observations: list[Observation] = field(default_factory=list)
    after: str | None = None
    reached_cutoff: bool = False
    structure_ok: bool = True
    warning: str | None = None


def _epoch(value) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return datetime.fromtimestamp(float(value), tz=timezone.utc)


def parse_listing(text: str, *, source: SourceRow, cutoff: datetime) -> ListingPage:
    """/r/<alt>/new yanıtı → saha raporları. RSS adaptörüyle aynı kapsam filtresi ve alanlar."""
    try:
        data = json.loads(text)
        children = data["data"]["children"] if data.get("kind") == "Listing" else None
    except (ValueError, KeyError, TypeError, AttributeError):
        children = None
    if not isinstance(children, list):
        return ListingPage(structure_ok=False, warning="Beklenen Reddit Listing yapısı bulunamadı.")
    page = ListingPage(after=data["data"].get("after"))
    for child in children:
        if not isinstance(child, dict) or child.get("kind") != "t3" or not isinstance(child.get("data"), dict):
            continue
        d = child["data"]
        ts = _epoch(d.get("created_utc"))
        if ts is not None and ts < cutoff:
            page.reached_cutoff = True
            continue
        # Silinen veya moderatörce kaldırılan gönderiler alınmaz.
        if d.get("removed_by_category") or d.get("selftext") in ("[deleted]", "[removed]"):
            continue
        title = norm_space(d.get("title") or "")
        permalink = d.get("permalink") or ""
        if not title or not permalink.startswith("/r/"):
            continue
        link = canonical_url(WEB_BASE + permalink)
        body = norm_space(d.get("selftext") or "")[:4000]
        full = f"{title}\n{body}"
        kind = community_kind(full, source)
        if kind is None:
            continue
        author = d.get("author")
        categories = [f"r/{d['subreddit']}"] if d.get("subreddit") else []
        if d.get("link_flair_text"):
            categories.append(norm_space(str(d["link_flair_text"])))
        fields = {
            "source_name": source.name, "author": f"u/{author}" if author and author != "[deleted]" else None,
            # Reddit gönderisi her zaman topluluk içeriğidir; kaynak satırından bağımsız olarak resmî sayılmaz.
            "trust": "community", "categories": categories[:10], **text_fields(full), "canonical_url": link,
            "summary": body[:1500],
        }
        post_id = d.get("name") or f"t3_{d.get('id')}"
        page.observations.append(Observation(
            external_key=f"reddit:{post_id}", kind=kind, title=title, url=link, body=body,
            lang=guess_lang(full, source.config.get("lang")), published_at=to_iso(ts),
            source_updated_at=to_iso(_epoch(d.get("edited")) or ts), fields=fields,
        ))
    return page


def run_reddit_api(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    cfg = load_config()
    if not cfg.reddit_configured:
        raise FetchError(not_configured_message(cfg), kind="config", retryable=False, url=TOKEN_URL)
    sub = str(source.config.get("subreddit") or "")
    if not SUBREDDIT_RE.match(sub):
        raise FetchError(f"Geçersiz alt forum adı: {sub!r}", kind="config", retryable=False)
    cutoff = now_utc() - timedelta(days=int(source.config.get("max_age_days", 4)))
    max_items = int(source.config.get("max_items", 60))
    max_pages = max(1, int(source.config.get("max_pages", 2)))
    out = AdapterResult(observations=[])
    after = None
    for _ in range(max_pages):
        res = _api_get(ctx, cfg, listing_url(sub, after=after))
        if out.fetched_url is None:
            out.fetched_url, out.http_status = res.url, res.status
        page = parse_listing(res.text, source=source, cutoff=cutoff)
        if not page.structure_ok:
            out.structure_ok = False
            out.warnings.append(page.warning or "Reddit yanıtı ayrıştırılamadı.")
            break
        out.observations += page.observations
        if page.reached_cutoff or not page.after or len(out.observations) >= max_items:
            break
        after = page.after
    out.observations = out.observations[:max_items]
    return out
