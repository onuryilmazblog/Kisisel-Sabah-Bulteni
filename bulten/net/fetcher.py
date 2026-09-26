"""Güvenli HTTP okuyucu: SSRF koruması, robots.txt, koşullu GET önbelleği, yeniden deneme.

Tüm kaynak okumaları buradan geçer. Operatörün .env ile tanımladığı uç noktalar
(`trusted=True`) özel ağ kontrolünden muaftır; arayüzden eklenen kaynaklar asla muaf değildir.
"""
from __future__ import annotations

import hashlib
import logging
import os
import socket
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from urllib import robotparser
from urllib.parse import urljoin, urlsplit

import httpx

from ..config import Config, load_config
from ..timeutil import now_iso
from .ssrf import UnsafeURL, ip_is_public, resolve_public, validate_url_syntax

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


class FetchError(Exception):
    def __init__(self, message: str, *, kind: str = "network", status: int | None = None,
                 retryable: bool = True, url: str | None = None):
        super().__init__(message)
        self.kind = kind            # network|http|blocked|robots|too_large|timeout
        self.status = status
        self.retryable = retryable
        self.url = url


@dataclass
class FetchResult:
    url: str
    status: int
    text: str
    content_type: str
    fetched_at: str
    not_modified: bool = False
    from_cache: bool = False
    headers: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8", "replace")).hexdigest()


def _proxy_configured() -> bool:
    return any(os.environ.get(k) for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY"))


class Fetcher:
    """İş parçacığı güvenli değildir; her iş/istek için bir örnek oluşturun."""

    _host_last: dict[str, float] = {}
    _host_lock = threading.Lock()
    _robots_cache: dict[str, tuple[float, robotparser.RobotFileParser | None]] = {}

    def __init__(self, conn: sqlite3.Connection | None = None, cfg: Config | None = None,
                 client: httpx.Client | None = None, min_host_interval: float = 1.0,
                 respect_robots: bool = True):
        self.cfg = cfg or load_config()
        self.conn = conn
        self._own_client = client is None
        self.client = client or httpx.Client(
            timeout=httpx.Timeout(self.cfg.http_timeout, connect=10.0),
            follow_redirects=False,
            headers={"User-Agent": self.cfg.http_user_agent, "Accept-Language": "en-US,en;q=0.8,tr;q=0.6"},
            trust_env=True,
        )
        self.min_host_interval = min_host_interval
        self.respect_robots = respect_robots

    def close(self) -> None:
        if self._own_client:
            self.client.close()

    def __enter__(self) -> "Fetcher":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- güvenlik ------------------------------------------------------------

    def _check_target(self, url: str, trusted: bool) -> None:
        host = (urlsplit(url).hostname or "").lower()
        if trusted or host in self.cfg.trusted_hosts:
            return
        try:
            _, host, port = validate_url_syntax(url)
        except UnsafeURL as exc:
            raise FetchError(str(exc), kind="blocked", retryable=False, url=url) from exc
        try:
            resolve_public(host, port)
        except UnsafeURL as exc:
            raise FetchError(str(exc), kind="blocked", retryable=False, url=url) from exc
        except socket.gaierror as exc:
            if _proxy_configured():
                # Proxy arkasında ad çözümlemesini proxy yapar; sözdizimi kontrolü yine de uygulandı.
                return
            raise FetchError(f"DNS çözümlenemedi: {host}", kind="network", url=url) from exc

    def _check_peer(self, response: httpx.Response, url: str, trusted: bool) -> None:
        if trusted or _proxy_configured():
            return
        stream = response.extensions.get("network_stream")
        if stream is None:
            return
        try:
            addr = stream.get_extra_info("server_addr")
        except Exception:  # noqa: BLE001
            return
        if addr and not ip_is_public(str(addr[0])):
            raise FetchError("Bağlantı özel bir IP adresine yöneldi; engellendi.", kind="blocked",
                             retryable=False, url=url)

    def _robots_allowed(self, url: str, trusted: bool) -> bool:
        if not self.respect_robots:
            return True
        parts = urlsplit(url)
        base = f"{parts.scheme}://{parts.netloc}"
        cached = self._robots_cache.get(base)
        now = time.time()
        if cached is None or now - cached[0] > 86400:
            rp: robotparser.RobotFileParser | None = robotparser.RobotFileParser()
            try:
                res = self._raw_get(base + "/robots.txt", trusted=trusted, headers={}, max_bytes=500_000)
                if res.status >= 400:
                    rp = None  # robots.txt yok → izin var
                else:
                    rp.parse(res.text.splitlines())
            except FetchError:
                rp = None  # erişilemiyorsa engelleme yapmıyoruz; hata asıl istekte görünür
            self._robots_cache[base] = (now, rp)
            cached = self._robots_cache[base]
        rp = cached[1]
        if rp is None:
            return True
        # can_fetch, kullanıcı ajanına özel kural yoksa "*" kuralına düşer.
        return rp.can_fetch(self.cfg.http_user_agent, url)

    # -- HTTP ------------------------------------------------------------------

    def _pace(self, host: str) -> None:
        with self._host_lock:
            last = self._host_last.get(host, 0.0)
            wait = self.min_host_interval - (time.time() - last)
            self._host_last[host] = time.time() + max(wait, 0)
        if wait > 0:
            time.sleep(wait)

    def _raw_get(self, url: str, *, trusted: bool, headers: dict, max_bytes: int) -> FetchResult:
        current = url
        for _hop in range(6):
            self._check_target(current, trusted)
            self._pace(urlsplit(current).netloc)
            try:
                with self.client.stream("GET", current, headers=headers) as resp:
                    self._check_peer(resp, current, trusted)
                    if resp.status_code in (301, 302, 303, 307, 308) and resp.headers.get("location"):
                        current = urljoin(current, resp.headers["location"])
                        continue
                    chunks, total = [], 0
                    for chunk in resp.iter_bytes():
                        total += len(chunk)
                        if total > max_bytes:
                            raise FetchError(f"Yanıt çok büyük (> {max_bytes} bayt).", kind="too_large",
                                             retryable=False, url=current)
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    encoding = resp.charset_encoding or _sniff_encoding(raw) or "utf-8"
                    try:
                        text = raw.decode(encoding, errors="replace")
                    except LookupError:
                        text = raw.decode("utf-8", errors="replace")
                    return FetchResult(
                        url=current, status=resp.status_code, text=text,
                        content_type=resp.headers.get("content-type", ""), fetched_at=now_iso(),
                        headers={k.lower(): v for k, v in resp.headers.items()},
                    )
            except FetchError:
                raise
            except httpx.TimeoutException as exc:
                raise FetchError(f"Zaman aşımı: {exc.__class__.__name__}", kind="timeout", url=current) from exc
            except httpx.HTTPError as exc:
                raise FetchError(f"Ağ hatası: {exc}", kind="network", url=current) from exc
        raise FetchError("Çok fazla yönlendirme.", kind="http", retryable=False, url=url)

    def get(self, url: str, *, trusted: bool = False, use_cache: bool = True, retries: int = 2,
            accept: str | None = None, extra_headers: dict | None = None,
            max_bytes: int | None = None) -> FetchResult:
        if self.respect_robots and not self._robots_allowed(url, trusted):
            raise FetchError("robots.txt bu sayfanın okunmasına izin vermiyor.", kind="robots",
                             retryable=False, url=url)
        headers = dict(extra_headers or {})
        if accept:
            headers["Accept"] = accept
        cached = self._cache_get(url) if use_cache and self.conn is not None else None
        if cached:
            if cached["etag"]:
                headers["If-None-Match"] = cached["etag"]
            if cached["last_modified"]:
                headers["If-Modified-Since"] = cached["last_modified"]
        limit = max_bytes or self.cfg.http_max_bytes
        attempt = 0
        while True:
            try:
                res = self._raw_get(url, trusted=trusted, headers=headers, max_bytes=limit)
                if res.status == 304 and cached:
                    return FetchResult(url=res.url, status=200, text=cached["body"] or "",
                                       content_type=cached["content_type"] or "", fetched_at=res.fetched_at,
                                       not_modified=True, from_cache=True, headers=res.headers)
                if res.status in RETRYABLE_STATUS:
                    raise FetchError(f"HTTP {res.status}", kind="http", status=res.status, url=res.url)
                if res.status >= 400:
                    raise FetchError(f"HTTP {res.status}", kind="http", status=res.status,
                                     retryable=False, url=res.url)
                if use_cache and self.conn is not None:
                    self._cache_put(url, res)
                return res
            except FetchError as exc:
                attempt += 1
                if not exc.retryable or attempt > retries:
                    raise
                time.sleep(min(2 ** attempt, 8))

    # -- önbellek --------------------------------------------------------------

    def _cache_get(self, url: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM http_cache WHERE url = ?", (url,)).fetchone()

    def _cache_put(self, url: str, res: FetchResult) -> None:
        self.conn.execute(
            "INSERT INTO http_cache(url, etag, last_modified, content_hash, content_type, body, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(url) DO UPDATE SET etag=excluded.etag, "
            "last_modified=excluded.last_modified, content_hash=excluded.content_hash, "
            "content_type=excluded.content_type, body=excluded.body, fetched_at=excluded.fetched_at",
            (url, res.headers.get("etag"), res.headers.get("last-modified"), res.content_hash,
             res.content_type, res.text, res.fetched_at),
        )


def _sniff_encoding(raw: bytes) -> str | None:
    head = raw[:2048].decode("ascii", errors="ignore").lower()
    for marker in ('encoding="', "charset="):
        idx = head.find(marker)
        if idx != -1:
            rest = head[idx + len(marker):]
            enc = "".join(ch for ch in rest[:20] if ch.isalnum() or ch in "-_")
            if enc:
                return enc
    return None

