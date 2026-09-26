"""İşlem hattını uçtan uca çalıştıran yardımcılar (worker ve CLI tarafından kullanılır)."""
from __future__ import annotations

import logging
import sqlite3
from dataclasses import asdict

from ..db import kv_get, kv_set
from ..timeutil import now_iso
from .analyze import analyze_events
from .canonical import canonicalize_pending
from .collect import CollectReport, run_collection
from .match import match_pending
from .summarize import summarize_pending

log = logging.getLogger(__name__)


def process(conn: sqlite3.Connection, *, max_llm_calls: int = 25) -> dict:
    """(Kanonik başlık) → eşleştir → analiz et → özetle (tekrar çalıştırılması güvenlidir)."""
    canonicalize_pending(conn)
    touched = match_pending(conn)
    versions = analyze_events(conn)
    stats = summarize_pending(conn, max_llm_calls=max_llm_calls)
    if kv_get(conn, "baseline_at") is None and _has_official_success(conn):
        # İlk başarılı resmî tarama tamamlandı: bundan önceki kayıtlar "başlangıç arşivi"dir.
        kv_set(conn, "baseline_at", now_iso())
    return {"events_touched": len(touched), "versions_created": len(versions), "summaries": stats}


def _has_official_success(conn: sqlite3.Connection) -> bool:
    row = conn.execute(
        "SELECT 1 FROM source_checks c JOIN sources s ON s.id = c.source_id WHERE s.trust = 'official' "
        "AND c.status IN ('ok', 'not_modified') LIMIT 1"
    ).fetchone()
    return row is not None


def collect_and_process(conn: sqlite3.Connection, *, only_critical: bool = False, modules: list[str] | None = None,
                        source_ids: list[int] | None = None, fetcher=None, max_llm_calls: int = 25) -> dict:
    report: CollectReport = run_collection(conn, only_critical=only_critical, modules=modules, source_ids=source_ids,
                                           fetcher=fetcher)
    result = process(conn, max_llm_calls=max_llm_calls)
    kv_set(conn, "last_check_at", now_iso())
    if report.sources_ok:
        kv_set(conn, "last_success_check_at", now_iso())
    return {"collect": asdict(report), **result}
