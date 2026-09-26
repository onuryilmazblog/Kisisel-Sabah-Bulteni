"""Bülten derleme ve kritik alarm seçimi.

Kurallar:
- Önce kritik ve kullanıcının ortamıyla ilgili gelişmeler, sonra seçilen diğer modüller.
- Daha önce bir bültende yer almış (gönderilmiş) değişmeyen içerik tekrar eklenmez; okunmamış olsa da
  arşivde okunmamış olarak kalır. Aynı olayın YENİ bir sürümü (maddi değişiklik) yeniden gelir.
- Kritik alarmla bildirilmiş değişmeyen içerik sabah tam haber olarak gelmez; ayara göre kısa referans verilir.
- Okunan/susturulan olayların yeni sürümleri için davranış ayarlanabilir (settings.resurface).
- İlk bültende eski arşiv toplu gönderilmez; yalnızca açık kritik sorunlardan "başlangıç özeti" oluşturulur.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from ..db import jdump, kv_get, tx
from ..settings_store import LENGTH_PRESETS, evidence_at_least, get_settings, risk_at_least
from ..sources.registry import module_enabled
from ..timeutil import in_quiet_hours, local_date_str, local_now, now_iso, now_utc, to_iso
from .analyze import RESOLVED

SECTION_TITLES = {
    "baslangic": "Başlangıç özeti: açık kritik sorunlar",
    "kritik": "Kritik ve ortamınızla ilgili",
    "windows": "Windows istemci/sunucu",
    "intune": "Intune",
    "configmgr": "Configuration Manager",
    "saha": "Saha sinyalleri (Microsoft teyidi yok)",
    "gece": "Gece kritik alarm olarak bildirilenler",
    "news_turkiye": "Türkiye", "news_dunya": "Dünya", "news_genel": "Genel", "news_teknoloji": "Teknoloji",
    "content": "Bloglar ve videolar",
}

RISK_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}


def _candidates(conn: sqlite3.Connection, since: str, is_demo: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT v.id AS vid, v.version, v.created_at AS v_created, v.change_types_json, e.*, "
        " u.read_at, u.read_version, u.muted_at, u.muted_version, COALESCE(u.followed, 0) AS followed "
        "FROM event_versions v JOIN events e ON e.id = v.event_id LEFT JOIN user_event_state u ON u.event_id = e.id "
        "WHERE v.is_major = 1 AND v.created_at > ? AND e.is_demo = ? AND NOT (e.is_baseline = 1 AND v.version = 1) "
        "ORDER BY v.created_at DESC", (since, is_demo),
    ).fetchall()


def resurface_allowed(row: sqlite3.Row, settings: dict, purpose: str) -> bool:
    """Okunan/susturulan olayın bu sürümü gösterilsin mi? purpose: bulletin|alert."""
    policy = settings.get("resurface") or {}
    if row["muted_at"]:
        if (row["muted_version"] or 0) >= row["version"]:
            return False
        mode = policy.get("muted", "silent")
        if mode == "silent":
            return False
        if mode == "critical_only" and row["risk_level"] != "critical":
            return False
    if row["read_at"]:
        if (row["read_version"] or 0) >= row["version"]:
            return False
        mode = policy.get("read", "notify")
        if mode == "silent":
            return False
        if mode == "bulletin_only" and purpose == "alert":
            return False
    return True


def _already_in_bulletin(conn: sqlite3.Connection, vid: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM bulletin_items bi JOIN bulletins b ON b.id = bi.bulletin_id "
        "WHERE bi.event_version_id = ? AND b.kind IN ('daily', 'baseline', 'manual') AND b.slot NOT LIKE 'demo:%' LIMIT 1", (vid,),
    ).fetchone() is not None


def _already_alerted(conn: sqlite3.Connection, vid: int) -> bool:
    return conn.execute(
        "SELECT 1 FROM delivery_items di JOIN deliveries d ON d.id = di.delivery_id "
        "WHERE di.event_version_id = ? AND d.kind = 'alert' AND di.render_mode = 'full' "
        "AND d.status IN ('sent', 'partial', 'uncertain', 'pending', 'sending') LIMIT 1", (vid,),
    ).fetchone() is not None


def _relevant(row: sqlite3.Row, settings: dict) -> bool:
    if row["relevance"] is not None and row["relevance"] < -10:
        return False  # hariç tutulan anahtar kelime
    if row["module"] in ("news", "content"):
        return True
    if row["followed"]:
        return True
    user_products = settings.get("products") or []
    if row["module"] == "windows" and user_products:
        return (row["relevance"] or 0) > 0
    return (row["relevance"] or 0) > 0 or row["module"] in ("intune", "configmgr")


def _module_ok(row: sqlite3.Row, settings: dict) -> bool:
    mods = settings.get("modules") or {}
    if row["module"] in ("news", "content"):
        return bool(mods.get(row["module"]))
    if not mods.get(row["module"]):
        return False
    if row["kind"] == "issue" and row["evidence_level"] == "field":
        return bool(mods.get("community"))
    return True


def _section_for(row: sqlite3.Row) -> str:
    if row["module"] == "news":
        return f"news_{row['category'] or 'genel'}"
    if row["module"] == "content":
        return "content"
    if row["kind"] == "issue" and row["evidence_level"] == "field":
        return "saha"
    return row["module"] if row["module"] in ("windows", "intune", "configmgr") else "windows"


def _is_critical_for_user(row: sqlite3.Row) -> bool:
    if row["followed"] and row["kind"] == "issue" and row["status"] not in RESOLVED:
        return True
    return row["risk_level"] in ("high", "critical") and (row["relevance"] or 0) >= 1.5 and \
        not (row["kind"] == "issue" and row["evidence_level"] == "field")


def select_items(conn: sqlite3.Connection, settings: dict, *, is_demo: int = 0, current_bulletin_id: int | None = None
                 ) -> tuple[list[dict], int, list[int]]:
    """(öğeler, taşan sayısı, gece alarmı referansları)."""
    baseline_at = kv_get(conn, "baseline_at") or "1970-01-01T00:00:00+00:00"
    week_ago = to_iso(now_utc() - timedelta(days=7))
    since = max(baseline_at, week_ago) if not is_demo else week_ago
    news_since = to_iso(now_utc() - timedelta(hours=30))
    rows = _candidates(conn, since, is_demo)
    seen_events: set[int] = set()
    buckets: dict[str, list[sqlite3.Row]] = {}
    alert_refs: list[int] = []
    news_cats = set(settings.get("news_categories") or [])
    for r in rows:
        if r["id"] in seen_events:
            continue  # aynı olayın yalnızca en yeni sürümü
        seen_events.add(r["id"])
        if not _module_ok(r, settings):
            continue
        if r["module"] == "news" and (r["category"] not in news_cats or r["v_created"] < news_since):
            continue
        if not _relevant(r, settings) or not resurface_allowed(r, settings, "bulletin"):
            continue
        if _already_in_bulletin(conn, r["vid"]):
            continue
        if _already_alerted(conn, r["vid"]):
            if (settings.get("critical") or {}).get("morning_reference", True):
                alert_refs.append(r["vid"])
            continue
        sec = "kritik" if _is_critical_for_user(r) else _section_for(r)
        buckets.setdefault(sec, []).append(r)
    limits = settings.get("category_limits") or {}
    total_cap = LENGTH_PRESETS.get((settings.get("bulletin") or {}).get("length", "orta"), LENGTH_PRESETS["orta"])["total_items"]
    order = ["kritik", "windows", "intune", "configmgr", "saha", "news_turkiye", "news_dunya", "news_genel",
             "news_teknoloji", "content"]
    items: list[dict] = []
    overflow = 0
    for sec in order:
        lst = sorted(buckets.get(sec, []), key=lambda r: (RISK_RANK.get(r["risk_level"], 4), -(r["relevance"] or 0),
                                                           r["v_created"]), reverse=False)
        if sec != "kritik":
            lst = sorted(lst, key=lambda r: (RISK_RANK.get(r["risk_level"], 4), -(r["relevance"] or 0)))
        cap = 6 if sec == "kritik" else int(limits.get("community" if sec == "saha" else sec, 3))
        for i, r in enumerate(lst):
            if i >= cap or (len(items) >= total_cap and sec != "kritik"):
                overflow += 1
                continue
            items.append({"version_id": r["vid"], "event_id": r["id"], "section": sec, "mode": "full"})
    return items, overflow, alert_refs


def baseline_items(conn: sqlite3.Connection, settings: dict) -> list[dict]:
    rows = conn.execute(
        "SELECT v.id AS vid, e.* FROM events e JOIN event_versions v ON v.event_id = e.id AND v.version = e.current_version "
        "WHERE e.is_baseline = 1 AND e.is_demo = 0 AND ((e.kind = 'issue' AND e.status NOT IN ('resolved', 'resolved_external') "
        "AND e.evidence_level != 'field') OR (e.kind = 'version' AND e.relevance >= 3)) "
        "AND e.risk_level IN ('high', 'critical') AND e.relevance > 0 "
        "ORDER BY CASE e.risk_level WHEN 'critical' THEN 0 ELSE 1 END, e.relevance DESC LIMIT ?",
        (int(settings.get("baseline_max_items") or 8),),
    ).fetchall()
    return [{"version_id": r["vid"], "event_id": r["id"], "section": "baslangic", "mode": "full"} for r in rows]


def tracking_summary(conn: sqlite3.Connection, settings: dict, is_demo: int = 0) -> dict:
    rows = conn.execute(
        "SELECT e.id, e.title, e.risk_level, e.status, COALESCE(u.followed, 0) AS followed FROM events e "
        "LEFT JOIN user_event_state u ON u.event_id = e.id WHERE e.kind = 'issue' AND e.is_demo = ? AND "
        "e.status NOT IN ('resolved', 'resolved_external') AND (u.followed = 1 OR (e.risk_level IN ('high','critical') "
        "AND e.relevance > 0)) AND (u.muted_at IS NULL) ORDER BY u.followed DESC, "
        "CASE e.risk_level WHEN 'critical' THEN 0 WHEN 'high' THEN 1 ELSE 2 END", (is_demo,),
    ).fetchall()
    return {"open_count": len(rows), "top": [{"event_id": r["id"], "title": r["title"], "risk": r["risk_level"]}
                                              for r in rows[:5]]}


def coverage(conn: sqlite3.Connection, hours: int = 26) -> dict:
    since = to_iso(now_utc() - timedelta(hours=hours))
    rows = conn.execute(
        "SELECT s.id, s.name, s.module, "
        " (SELECT status FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_status, "
        " (SELECT MAX(finished_at) FROM source_checks c WHERE c.source_id = s.id AND c.status IN ('ok','not_modified')) AS last_ok "
        "FROM sources s WHERE s.enabled = 1").fetchall()
    ok = [r for r in rows if r["last_status"] in ("ok", "not_modified") and (r["last_ok"] or "") >= since]
    failing = [r for r in rows if r["last_status"] in ("error", "parse_warning")]
    never = [r for r in rows if r["last_status"] is None]
    return {
        "enabled": len(rows), "ok": len(ok), "failing": [{"name": r["name"], "status": r["last_status"],
                                                          "last_ok": r["last_ok"]} for r in failing],
        "never_checked": len(never),
        "scope_note": "Yalnızca yapılandırılmış kaynaklar ve (etkinse) web araması tarandı; internetin tamamı taranmaz.",
    }


def latest_daily(conn: sqlite3.Connection, module: str, max_age_hours: int = 6) -> int | None:
    row = conn.execute("SELECT id, fetched_at FROM daily_data WHERE module = ? ORDER BY id DESC LIMIT 1",
                       (module,)).fetchone()
    if not row:
        return None
    return row["id"]


def compose_bulletin(conn: sqlite3.Connection, *, kind: str = "daily", is_demo: int = 0) -> int:
    """Bülteni oluşturur ve kaydeder. Günlük bülten gün başına bir kez oluşturulur (idempotent)."""
    settings = get_settings(conn)
    tzname = settings.get("timezone")
    local_day = local_date_str(tzname)
    slot = f"{kind}:{local_day}" if kind == "daily" else f"{kind}:{now_iso()}"
    if is_demo:
        slot = "demo:" + slot
    existing = conn.execute("SELECT id FROM bulletins WHERE slot = ?", (slot,)).fetchone()
    if existing:
        return existing["id"]
    with tx(conn):
        items, overflow, alert_refs = select_items(conn, settings, is_demo=is_demo)
        first_daily = kind == "daily" and not is_demo and conn.execute(
            "SELECT 1 FROM bulletins WHERE kind = 'daily' AND slot NOT LIKE 'demo:%' LIMIT 1").fetchone() is None
        base = baseline_items(conn, settings) if first_daily and kv_get(conn, "baseline_at") else []
        existing_ids = {i["version_id"] for i in items}
        items = [b for b in base if b["version_id"] not in existing_ids] + items
        sections: dict[str, list[dict]] = {}
        for it in items:
            sections.setdefault(it["section"], []).append({"version_id": it["version_id"], "event_id": it["event_id"],
                                                          "mode": it["mode"]})
        if alert_refs:
            sections["gece"] = [{"version_id": v, "event_id": None, "mode": "reference"} for v in alert_refs]
        order = ["baslangic", "kritik", "gece", "windows", "intune", "configmgr", "saha", "news_turkiye", "news_dunya",
                 "news_genel", "news_teknoloji", "content"]
        last_daily = conn.execute("SELECT MAX(created_at) AS t FROM bulletins WHERE kind = 'daily' AND slot NOT LIKE 'demo:%'"
                                  ).fetchone()["t"]
        content = {
            "date": local_day, "kind": kind, "generated_at": now_iso(), "window_start": last_daily,
            "sections": [{"key": k, "title": SECTION_TITLES[k], "items": sections[k]} for k in order if k in sections],
            "baseline": bool(base), "tracking": tracking_summary(conn, settings, is_demo),
            "daily": {m: latest_daily(conn, m) for m in ("weather", "market", "calendar")
                      if module_enabled(settings, {"market": "markets"}.get(m, m))},
            "coverage": coverage(conn), "overflow": overflow,
            "modules": {k: v for k, v in (settings.get("modules") or {}).items()},
        }
        bid = conn.execute(
            "INSERT INTO bulletins(bulletin_date, kind, slot, created_at, window_start, window_end, content_json, is_demo) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (local_day, kind, slot, now_iso(), last_daily, now_iso(), jdump(content), is_demo),
        ).lastrowid
        pos = 0
        for sec in content["sections"]:
            for it in sec["items"]:
                ev_id = it["event_id"] or conn.execute("SELECT event_id FROM event_versions WHERE id = ?",
                                                       (it["version_id"],)).fetchone()["event_id"]
                conn.execute("INSERT OR IGNORE INTO bulletin_items(bulletin_id, event_version_id, event_id, section, "
                             "position, render_mode) VALUES (?, ?, ?, ?, ?, ?)",
                             (bid, it["version_id"], ev_id, sec["key"], pos, it["mode"]))
                pos += 1
    return bid


# --- Kritik alarm -------------------------------------------------------------------

def select_alerts(conn: sqlite3.Connection, settings: dict | None = None, *, is_demo: int = 0) -> tuple[list[int], str]:
    """Kritik alarm olarak gönderilecek sürümler ve açıklama (ör. sessiz saat nedeniyle ertelendi)."""
    settings = settings or get_settings(conn)
    crit = settings.get("critical") or {}
    if not crit.get("enabled"):
        return [], "Kritik alarm modu kapalı."
    baseline_at = kv_get(conn, "baseline_at")
    if not baseline_at and not is_demo:
        return [], "Başlangıç taraması tamamlanmadı."
    since = max(baseline_at or "", to_iso(now_utc() - timedelta(days=3)))
    rows = _candidates(conn, since, is_demo)
    local = local_now(settings.get("timezone"))
    qh = settings.get("quiet_hours") or {}
    quiet = bool(qh.get("enabled")) and in_quiet_hours(local, qh.get("start", "22:30"), qh.get("end", "07:30"))
    chosen: list[int] = []
    deferred = 0
    seen: set[int] = set()
    for r in rows:
        if r["id"] in seen:
            continue
        seen.add(r["id"])
        if r["module"] not in ("windows", "intune", "configmgr"):
            continue
        if not _relevant(r, settings) or not resurface_allowed(r, settings, "alert"):
            continue
        if _already_alerted(conn, r["vid"]) or _already_in_bulletin(conn, r["vid"]):
            continue
        if not alert_threshold_met(r, crit):
            continue
        if quiet:
            exc = crit.get("quiet_exception", "none")
            allowed = (exc == "all_critical" and r["risk_level"] == "critical") or (
                exc == "ms_critical" and r["risk_level"] == "critical" and r["evidence_level"] in ("ms_known_issue", "ms_official"))
            if not allowed:
                deferred += 1
                continue
        chosen.append(r["vid"])
    note = f"{deferred} alarm sessiz saat nedeniyle sabah bültenine bırakıldı." if deferred else ""
    return chosen, note


def alert_threshold_met(row: sqlite3.Row, crit: dict) -> bool:
    min_risk = crit.get("min_risk", "high")
    if not risk_at_least(row["risk_level"], min_risk):
        return False
    if row["kind"] != "issue":
        return True
    if evidence_at_least(row["evidence_level"], crit.get("min_evidence", "ms_official")):
        return True
    # Teyitsiz ama yüksek etkili saha sinyali: yalnızca izin verildiyse ve yeterli bağımsız kaynak varsa.
    return (bool(crit.get("allow_field")) and row["evidence_level"] == "field" and row["risk_level"] == "critical"
            and (row["field_sources"] or 0) >= int(crit.get("field_min_sources", 2)))


def is_due_bulletin_day(settings: dict) -> bool:
    local = local_now(settings.get("timezone"))
    if local.weekday() >= 5 and not (settings.get("bulletin") or {}).get("weekend", False):
        return False
    return True

