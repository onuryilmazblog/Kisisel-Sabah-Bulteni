"""Adım 1-2: Toplama ve normalleştirme.

Her kaynak için adaptör çalıştırılır, sonuçlar `observations` tablosuna yazılır.
İçerik değiştiyse kanıt anlık görüntüsü (`observation_snapshots`) eklenir.
Kaynağa erişilemezse bu "yeni sorun yok" anlamına gelmez: kontrol kaydı hata olarak tutulur
ve arayüzde/bültende kapsam uyarısı olarak gösterilir.
"""
from __future__ import annotations

import hashlib
import json
import logging
import sqlite3
import time
import traceback
import uuid
from dataclasses import dataclass, field

from ..db import jdump, tx
from ..net.fetcher import Fetcher, FetchError
from ..settings_store import get_settings
from ..sources.base import AdapterContext, Observation, SourceRow
from ..sources.registry import ADAPTERS, module_enabled
from ..timeutil import now_iso

log = logging.getLogger(__name__)

# Bağımlılık sırası: güncelleme geçmişi → KB makaleleri → web araması (KB listesini kullanır)
ADAPTER_ORDER = {
    "ms_update_history": 0, "wrh_status": 1, "wrh_resolved": 1, "wrh_messages": 2, "intune": 2,
    "cm_versions": 2, "cm_hotfix": 2, "cm_release_notes": 2, "cm_tp": 3, "ms_kb": 4, "rss": 5, "web_search": 6,
}

# Anlamsal özet: yalnızca anlamlı alanlar (yazım/tarih/düzen değişikliğini dışarıda bırakmak için).
SEMANTIC_FIELDS = ("status", "originating_kbs", "resolving_kbs", "partial_fix_kbs", "products", "tags", "kir",
                   "stage", "change_kind", "platforms", "release_type", "builds", "versions", "support_end",
                   "hotfix_type", "admin_action")


def semantic_hash(ob: Observation) -> str:
    f = ob.fields or {}
    payload = {k: f.get(k) for k in SEMANTIC_FIELDS if k in f}
    payload["_wa"] = bool(f.get("workaround"))
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


@dataclass
class CollectReport:
    run_id: str
    sources_total: int = 0
    sources_ok: int = 0
    sources_error: int = 0
    sources_warning: int = 0
    observations_changed: int = 0
    errors: list[str] = field(default_factory=list)


def _source_had_success(conn: sqlite3.Connection, source_id: int) -> bool:
    row = conn.execute(
        "SELECT 1 FROM source_checks WHERE source_id = ? AND status IN ('ok', 'not_modified') LIMIT 1", (source_id,)
    ).fetchone()
    return row is not None


def upsert_observations(conn: sqlite3.Connection, source: SourceRow, observations: list[Observation], *,
                        first_run: bool, is_demo: bool = False) -> int:
    ts = now_iso()
    changed = 0
    seen: set[str] = set()
    with tx(conn):
        for ob in observations:
            if ob.external_key in seen:
                continue
            seen.add(ob.external_key)
            ch = ob.content_hash()
            sh = semantic_hash(ob)
            row = conn.execute(
                "SELECT id, content_hash FROM observations WHERE source_id = ? AND external_key = ?",
                (source.id, ob.external_key),
            ).fetchone()
            if row is None:
                cur = conn.execute(
                    "INSERT INTO observations(source_id, external_key, kind, url, title, body, lang, published_at, "
                    "source_updated_at, first_seen_at, last_seen_at, fields_json, content_hash, semantic_hash, "
                    "needs_analysis, from_first_run, is_demo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
                    (source.id, ob.external_key, ob.kind, ob.url, ob.title, ob.body, ob.lang, ob.published_at,
                     ob.source_updated_at, ts, ts, jdump(ob.fields), ch, sh, 1 if first_run else 0,
                     1 if is_demo else 0),
                )
                obs_id = cur.lastrowid
                changed += 1
            else:
                obs_id = row["id"]
                if row["content_hash"] == ch:
                    conn.execute("UPDATE observations SET last_seen_at = ? WHERE id = ?", (ts, obs_id))
                    continue
                conn.execute(
                    "UPDATE observations SET kind = ?, url = ?, title = ?, body = ?, lang = ?, "
                    "published_at = COALESCE(?, published_at), source_updated_at = ?, last_seen_at = ?, "
                    "fields_json = ?, content_hash = ?, semantic_hash = ?, needs_analysis = 1 WHERE id = ?",
                    (ob.kind, ob.url, ob.title, ob.body, ob.lang, ob.published_at, ob.source_updated_at, ts,
                     jdump(ob.fields), ch, sh, obs_id),
                )
                changed += 1
            conn.execute(
                "INSERT INTO observation_snapshots(observation_id, captured_at, content_hash, title, body, fields_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (obs_id, ts, ch, ob.title, ob.body, jdump(ob.fields)),
            )
            ev = conn.execute("SELECT event_id FROM observations WHERE id = ?", (obs_id,)).fetchone()
            if ev and ev["event_id"]:
                conn.execute("UPDATE events SET needs_analysis = 1 WHERE id = ?", (ev["event_id"],))
    return changed


def select_sources(conn: sqlite3.Connection, settings: dict, *, only_critical: bool = False,
                   source_ids: list[int] | None = None, modules: list[str] | None = None) -> list[SourceRow]:
    rows = conn.execute("SELECT * FROM sources WHERE enabled = 1").fetchall()
    out = []
    for r in rows:
        s = SourceRow.from_row(r)
        if source_ids is not None and s.id not in source_ids:
            continue
        if source_ids is None:
            if not module_enabled(settings, s.module):
                continue
            if modules is not None and s.module not in modules:
                continue
            if only_critical and not s.critical:
                continue
        out.append(s)
    out.sort(key=lambda s: (ADAPTER_ORDER.get(s.adapter, 9), s.id))
    return out


def run_collection(conn: sqlite3.Connection, *, only_critical: bool = False, source_ids: list[int] | None = None,
                   modules: list[str] | None = None, fetcher: Fetcher | None = None) -> CollectReport:
    settings = get_settings(conn)
    run_id = uuid.uuid4().hex[:12]
    report = CollectReport(run_id=run_id)
    sources = select_sources(conn, settings, only_critical=only_critical, source_ids=source_ids, modules=modules)
    own_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(conn)
    ctx = AdapterContext(conn=conn, fetcher=fetcher, settings=settings)
    try:
        for src in sources:
            report.sources_total += 1
            adapter = ADAPTERS.get(src.adapter)
            started = time.time()
            check_id = conn.execute(
                "INSERT INTO source_checks(source_id, run_id, started_at, status) VALUES (?, ?, ?, 'running')",
                (src.id, run_id, now_iso()),
            ).lastrowid
            status, error, http_status, fetched_url, found, changed = "error", None, None, None, 0, 0
            try:
                if adapter is None:
                    raise RuntimeError(f"Bilinmeyen adaptör: {src.adapter}")
                first_run = not _source_had_success(conn, src.id)
                result = adapter(src, ctx)
                found = len(result.observations)
                changed = upsert_observations(conn, src, result.observations, first_run=first_run)
                http_status, fetched_url = result.http_status, result.fetched_url
                if not result.structure_ok:
                    status = "parse_warning"
                elif result.not_modified:
                    status = "not_modified"
                else:
                    status = "ok"
                if result.warnings:
                    error = "; ".join(result.warnings)[:2000]
                report.observations_changed += changed
            except FetchError as exc:
                error = str(exc)
                http_status = exc.status
                fetched_url = exc.url
            except Exception as exc:  # noqa: BLE001 - bir kaynağın hatası diğerlerini durdurmasın
                error = f"{exc.__class__.__name__}: {exc}"
                log.error("Kaynak hatası %s: %s", src.slug, traceback.format_exc())
            if status in ("ok", "not_modified"):
                report.sources_ok += 1
            elif status == "parse_warning":
                report.sources_warning += 1
                report.errors.append(f"{src.name}: {error or 'ayrıştırma uyarısı'}")
            else:
                report.sources_error += 1
                report.errors.append(f"{src.name}: {error}")
            conn.execute(
                "UPDATE source_checks SET finished_at = ?, status = ?, http_status = ?, fetched_url = ?, error = ?, "
                "items_found = ?, items_changed = ?, duration_ms = ? WHERE id = ?",
                (now_iso(), status, http_status, fetched_url, error, found, changed,
                 int((time.time() - started) * 1000), check_id),
            )
    finally:
        if own_fetcher:
            fetcher.close()
    return report


def last_success_by_source(conn: sqlite3.Connection) -> dict[int, dict]:
    rows = conn.execute(
        "SELECT s.id, s.slug, s.name, s.module, s.enabled, "
        " (SELECT MAX(finished_at) FROM source_checks c WHERE c.source_id = s.id AND c.status IN ('ok','not_modified')) AS last_ok, "
        " (SELECT status FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_status, "
        " (SELECT error FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_error, "
        " (SELECT finished_at FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_check "
        "FROM sources s"
    ).fetchall()
    return {r["id"]: dict(r) for r in rows}
