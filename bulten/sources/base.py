"""Kaynak adaptörleri için ortak tipler."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Callable

from ..net.fetcher import Fetcher, FetchError, FetchResult


@dataclass
class Observation:
    external_key: str
    kind: str
    title: str
    url: str | None = None
    body: str = ""
    lang: str = "en"
    published_at: str | None = None
    source_updated_at: str | None = None
    fields: dict[str, Any] = field(default_factory=dict)

    def content_hash(self) -> str:
        payload = json.dumps(
            {"t": self.title, "b": self.body, "f": self.fields, "u": self.url}, sort_keys=True,
            ensure_ascii=False, default=str,
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass
class AdapterResult:
    observations: list[Observation]
    fetched_url: str | None = None
    http_status: int | None = None
    not_modified: bool = False
    warnings: list[str] = field(default_factory=list)
    # Sayfa beklenen yapıda ayrıştırılabildi mi? False ise "sorun yok" diye yorumlanmaz.
    structure_ok: bool = True


@dataclass
class SourceRow:
    id: int
    slug: str
    name: str
    module: str
    adapter: str
    url: str
    fetch_url: str | None
    fallback_url: str | None
    trust: str
    category: str | None
    product_ids: list[str]
    config: dict[str, Any]
    critical: bool = False

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "SourceRow":
        return cls(
            id=row["id"], slug=row["slug"], name=row["name"], module=row["module"],
            adapter=row["adapter"], url=row["url"], fetch_url=row["fetch_url"],
            fallback_url=row["fallback_url"], trust=row["trust"], category=row["category"],
            product_ids=json.loads(row["product_ids"] or "[]"),
            config=json.loads(row["config_json"] or "{}"), critical=bool(row["critical"]),
        )

    @property
    def trusted_fetch(self) -> bool:
        """Yerleşik resmî kaynaklar genel internettedir; yine de SSRF kontrolünden geçer.

        Yalnızca operatörün .env'de tanımladığı uç noktalar güvenilir sayılır (config.trusted_hosts).
        """
        return False


@dataclass
class AdapterContext:
    conn: sqlite3.Connection
    fetcher: Fetcher
    settings: dict[str, Any]


AdapterFn = Callable[[SourceRow, AdapterContext], AdapterResult]


def fetch_with_fallback(source: SourceRow, ctx: AdapterContext, *, accept: str | None = None
                        ) -> tuple[FetchResult, str]:
    """Birincil adresi, olmazsa yedeği dener. (sonuç, 'primary'|'fallback') döner."""
    primary = source.fetch_url or source.url
    try:
        return ctx.fetcher.get(primary, accept=accept), "primary"
    except FetchError as exc:
        if not source.fallback_url:
            raise
        try:
            return ctx.fetcher.get(source.fallback_url, accept=accept), "fallback"
        except FetchError as exc2:
            raise FetchError(f"Birincil: {exc}; yedek: {exc2}", kind=exc2.kind, status=exc2.status,
                             retryable=exc.retryable or exc2.retryable, url=source.fallback_url) from exc2


def slugify(text: str, maxlen: int = 80) -> str:
    import re
    import unicodedata

    t = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii").lower()
    t = re.sub(r"[^a-z0-9]+", "-", t).strip("-")
    return t[:maxlen].rstrip("-")


def short_hash(text: str, n: int = 10) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:n]
