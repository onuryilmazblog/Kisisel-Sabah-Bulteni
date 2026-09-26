"""Kaynak doğrulama (kuru çalıştırma): adaptörü gerçek ağ üzerinden çalıştırır, sonuçları kaydetmez."""
from __future__ import annotations

import sqlite3
import time

from ..net.fetcher import Fetcher, FetchError
from ..settings_store import get_settings
from ..sources.base import AdapterContext, SourceRow
from ..sources.registry import ADAPTERS


def validate_source(conn: sqlite3.Connection, src: SourceRow, fetcher: Fetcher | None = None) -> dict:
    own = fetcher is None
    fetcher = fetcher or Fetcher(conn, respect_robots=True)
    started = time.time()
    out = {"slug": src.slug, "name": src.name, "url": src.fetch_url or src.url, "ok": False, "items": 0,
           "warnings": [], "error": None, "sample": []}
    try:
        adapter = ADAPTERS[src.adapter]
        # Kuru çalıştırma: DB'ye yazmayan bir bağlam (ms_kb/websearch okuma yapar, yazmaz).
        res = adapter(src, AdapterContext(conn=conn, fetcher=fetcher, settings=get_settings(conn)))
        out["ok"] = bool(res.structure_ok)
        out["items"] = len(res.observations)
        out["warnings"] = res.warnings
        out["http_status"] = res.http_status
        out["fetched_url"] = res.fetched_url
        out["sample"] = [o.title for o in res.observations[:3]]
    except FetchError as exc:
        out["error"] = str(exc)
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if own:
            fetcher.close()
    out["duration_ms"] = int((time.time() - started) * 1000)
    return out


def validate_sources(conn: sqlite3.Connection, slugs: list[str] | None = None, include_disabled: bool = False) -> list[dict]:
    q = "SELECT * FROM sources" + ("" if include_disabled else " WHERE enabled = 1")
    rows = [SourceRow.from_row(r) for r in conn.execute(q).fetchall()]
    if slugs:
        rows = [r for r in rows if r.slug in slugs]
    with Fetcher(conn) as fetcher:
        return [validate_source(conn, r, fetcher) for r in rows]
