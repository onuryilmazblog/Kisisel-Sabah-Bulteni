"""Web ekranları için sorgular ve görünüm modelleri."""
from __future__ import annotations

import sqlite3
from datetime import timedelta
from typing import Any

from ..catalog import PRODUCT_BY_ID
from ..config import load_config
from ..db import jload, kv_get
from ..delivery.dispatcher import channel_problems, delivery_overview
from ..pipeline.bulletin import SECTION_TITLES, coverage, latest_daily, select_items, tracking_summary
from ..pipeline.cards import build_card
from ..pipeline.evidence import EVIDENCE_LABELS, effective_trust
from ..sources.registry import ADAPTER_LABELS
from ..daily.service import daily_view
from ..timeutil import local_date_str, now_utc, parse_iso, to_iso
from ..usage import today_totals, usage_summary


def _sections_from_items(conn: sqlite3.Connection, items: list[dict]) -> list[dict]:
    order = ["baslangic", "kritik", "gece", "windows", "intune", "configmgr", "saha", "news_turkiye", "news_dunya",
             "news_genel", "news_teknoloji", "content"]
    by: dict[str, list[dict]] = {}
    for it in items:
        card = build_card(conn, it["version_id"], mode=it.get("mode", "full"))
        if card:
            by.setdefault(it["section"], []).append(card)
    return [{"key": k, "title": SECTION_TITLES.get(k, k), "cards": by[k]} for k in order if k in by]


def bulletin_view(conn: sqlite3.Connection, settings: dict, bulletin_id: int | None = None) -> dict[str, Any]:
    """Bugünün bülteni. Bugün için kayıtlı bülten yoksa canlı önizleme (kaydedilmez, gönderilmiş sayılmaz)."""
    tzname = settings.get("timezone")
    today = local_date_str(tzname)
    if bulletin_id:
        row = conn.execute("SELECT * FROM bulletins WHERE id = ?", (bulletin_id,)).fetchone()
    else:
        row = conn.execute("SELECT * FROM bulletins WHERE is_demo = 0 AND kind IN ('daily', 'manual') "
                           "AND bulletin_date = ? ORDER BY id DESC LIMIT 1", (today,)).fetchone()
    demo_row = None
    if row is None and not bulletin_id:
        has_real = conn.execute("SELECT 1 FROM events WHERE is_demo = 0 LIMIT 1").fetchone()
        if not has_real:
            demo_row = conn.execute("SELECT * FROM bulletins WHERE is_demo = 1 ORDER BY id DESC LIMIT 1").fetchone()
            row = demo_row
    if row is not None:
        content = jload(row["content_json"], {})
        items = []
        for sec in content.get("sections", []):
            for it in sec["items"]:
                items.append({**it, "section": sec["key"]})
        daily_ids = content.get("daily") or {}
        return {"row": dict(row), "content": content, "sections": _sections_from_items(conn, items),
                "is_preview": False, "is_demo": bool(row["is_demo"]),
                "daily": {m: daily_view(conn, daily_ids.get(m), m, tzname) for m in daily_ids},
                "tracking": content.get("tracking") or {}, "coverage": content.get("coverage") or {}}
    items, overflow, alert_refs = select_items(conn, settings)
    items += [{"version_id": v, "event_id": None, "section": "gece", "mode": "reference"} for v in alert_refs]
    daily = {}
    for m, key in (("weather", "weather"), ("market", "markets"), ("calendar", "calendar")):
        if (settings.get("modules") or {}).get(key):
            daily[m] = daily_view(conn, latest_daily(conn, m), m, tzname)
    return {"row": None, "content": {"date": today, "overflow": overflow}, "sections": _sections_from_items(conn, items),
            "is_preview": True, "is_demo": False, "daily": daily, "tracking": tracking_summary(conn, settings),
            "coverage": coverage(conn)}


def event_cards(conn: sqlite3.Connection, where: str, params: tuple, limit: int = 50, offset: int = 0,
                order: str = "COALESCE(e.meaningful_update_at, e.first_seen_at) DESC") -> list[dict]:
    rows = conn.execute(
        f"SELECT v.id AS vid FROM events e JOIN event_versions v ON v.event_id = e.id AND v.version = e.current_version "
        f"LEFT JOIN user_event_state u ON u.event_id = e.id WHERE {where} ORDER BY {order} LIMIT ? OFFSET ?",
        (*params, limit, offset)).fetchall()
    return [c for c in (build_card(conn, r["vid"]) for r in rows) if c]


def critical_view(conn: sqlite3.Connection, settings: dict) -> dict:
    since = to_iso(now_utc() - timedelta(days=21))
    cards = event_cards(conn, "e.is_demo = 0 AND e.risk_level IN ('high', 'critical') AND e.relevance > 0 AND "
                              "COALESCE(e.meaningful_update_at, e.first_seen_at) >= ?", (since,),
                        order="CASE e.risk_level WHEN 'critical' THEN 0 ELSE 1 END, e.meaningful_update_at DESC")
    alerts = conn.execute("SELECT d.*, (SELECT COUNT(*) FROM delivery_items di WHERE di.delivery_id = d.id) AS n "
                          "FROM deliveries d WHERE d.kind = 'alert' ORDER BY d.id DESC LIMIT 20").fetchall()
    return {"cards": cards, "alerts": [dict(a) for a in alerts], "critical": settings.get("critical") or {}}


def tracking_view(conn: sqlite3.Connection, settings: dict) -> dict:
    followed = event_cards(conn, "e.is_demo = 0 AND u.followed = 1", (), order="e.meaningful_update_at DESC")
    open_risks = event_cards(
        conn, "e.is_demo = 0 AND e.kind = 'issue' AND e.status NOT IN ('resolved', 'resolved_external') AND "
              "e.risk_level IN ('high', 'critical') AND e.relevance > 0 AND COALESCE(u.followed, 0) = 0 AND u.muted_at IS NULL",
        (), order="CASE e.risk_level WHEN 'critical' THEN 0 ELSE 1 END, e.meaningful_update_at DESC")
    return {"followed": followed, "open_risks": open_risks, "summary": tracking_summary(conn, settings)}


ARCHIVE_FILTERS = ("q", "module", "kind", "product", "kb", "evidence", "status", "read", "demo")


def archive_view(conn: sqlite3.Connection, f: dict, page: int = 1, per_page: int = 25) -> dict:
    where = ["1 = 1"]
    params: list[Any] = []
    where.append("e.is_demo = ?")
    params.append(1 if f.get("demo") == "1" else 0)
    if f.get("q"):
        q = f"%{f['q'].strip()}%"
        where.append("(e.title LIKE ? OR v.title_tr LIKE ? OR v.summary_tr LIKE ? OR e.kbs_json LIKE ? OR e.event_key LIKE ?)")
        params += [q, q, q, q, q]
    if f.get("module"):
        where.append("e.module = ?")
        params.append(f["module"])
    if f.get("kind"):
        where.append("e.kind = ?")
        params.append(f["kind"])
    if f.get("product"):
        where.append("e.products_json LIKE ?")
        params.append(f'%"{f["product"]}"%')
    if f.get("kb"):
        kb = "".join(ch for ch in f["kb"] if ch.isdigit())
        where.append("e.kbs_json LIKE ?")
        params.append(f'%"{kb}"%')
    if f.get("evidence"):
        where.append("e.evidence_level = ?")
        params.append(f["evidence"])
    if f.get("status") == "open":
        where.append("e.kind = 'issue' AND e.status NOT IN ('resolved', 'resolved_external')")
    elif f.get("status") == "resolved":
        where.append("e.status IN ('resolved', 'resolved_external')")
    if f.get("read") == "unread":
        where.append("(u.read_at IS NULL OR u.read_version < e.current_version)")
    elif f.get("read") == "read":
        where.append("u.read_at IS NOT NULL AND u.read_version >= e.current_version")
    elif f.get("read") == "muted":
        where.append("u.muted_at IS NOT NULL")
    w = " AND ".join(where)
    total = conn.execute(
        f"SELECT COUNT(*) FROM events e JOIN event_versions v ON v.event_id = e.id AND v.version = e.current_version "
        f"LEFT JOIN user_event_state u ON u.event_id = e.id WHERE {w}", params).fetchone()[0]
    cards = event_cards(conn, w, tuple(params), limit=per_page, offset=(page - 1) * per_page)
    return {"cards": cards, "total": total, "page": page, "pages": max(1, (total + per_page - 1) // per_page)}


def event_detail(conn: sqlite3.Connection, event_id: int) -> dict | None:
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if ev is None:
        return None
    versions = conn.execute("SELECT * FROM event_versions WHERE event_id = ? ORDER BY version DESC", (event_id,)).fetchall()
    card = build_card(conn, versions[0]["id"]) if versions else None
    history = [{"version": v["version"], "created_at": v["created_at"], "change_note": v["change_note"],
                "change_types": jload(v["change_types_json"], []), "title": v["title_tr"],
                "what_changed": v["what_changed_tr"], "summary_source": v["summary_source"]} for v in versions]
    obs = conn.execute(
        "SELECT o.*, s.name AS s_name, s.trust AS s_trust, s.adapter AS s_adapter, "
        "(SELECT COUNT(*) FROM observation_snapshots sn WHERE sn.observation_id = o.id) AS snaps "
        "FROM observations o JOIN sources s ON s.id = o.source_id WHERE o.event_id = ? ORDER BY o.first_seen_at", (event_id,)
    ).fetchall()
    evidence = []
    for o in obs:
        fields = jload(o["fields_json"], {})
        trust = effective_trust(o["s_trust"], o["url"], fields)
        evidence.append({"title": o["title"], "url": o["url"], "source": fields.get("source_name") or o["s_name"],
                         "trust": trust, "kind": o["kind"], "first_seen": o["first_seen_at"], "last_seen": o["last_seen_at"],
                         "published": o["published_at"], "updated": o["source_updated_at"], "snaps": o["snaps"],
                         "match": f"{o['match_method']} ({o['match_score']})" if o["match_method"] else "",
                         "excerpt": (o["body"] or "")[:600], "snippet_only": bool(fields.get("snippet_only"))})
    state = conn.execute("SELECT * FROM user_event_state WHERE event_id = ?", (event_id,)).fetchone()
    deliveries = conn.execute(
        "SELECT d.channel, d.kind, d.status, d.created_at, d.sent_at, di.render_mode, v.version FROM delivery_items di "
        "JOIN deliveries d ON d.id = di.delivery_id JOIN event_versions v ON v.id = di.event_version_id "
        "WHERE di.event_id = ? ORDER BY d.id DESC LIMIT 20", (event_id,)).fetchall()
    actions = conn.execute("SELECT * FROM user_actions WHERE event_id = ? ORDER BY id DESC LIMIT 20", (event_id,)).fetchall()
    ki_checked = None
    if ev["kind"] == "issue":
        row = conn.execute("SELECT MAX(c.finished_at) AS t FROM source_checks c JOIN sources s ON s.id = c.source_id "
                           "WHERE s.adapter IN ('wrh_status', 'wrh_resolved', 'ms_kb') AND c.status IN ('ok', 'not_modified')"
                           ).fetchone()
        ki_checked = row["t"] if row else None
    return {"event": dict(ev), "card": card, "history": history, "evidence": evidence,
            "state": dict(state) if state else {}, "deliveries": [dict(d) for d in deliveries],
            "actions": [dict(a) for a in actions], "ki_checked": ki_checked,
            "evidence_label": EVIDENCE_LABELS.get(ev["evidence_level"], "")}


def sources_view(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT s.*, "
        " (SELECT MAX(finished_at) FROM source_checks c WHERE c.source_id = s.id AND c.status IN ('ok','not_modified')) AS last_ok, "
        " (SELECT status FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_status, "
        " (SELECT error FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_error, "
        " (SELECT finished_at FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_check, "
        " (SELECT items_found FROM source_checks c WHERE c.source_id = s.id ORDER BY c.id DESC LIMIT 1) AS last_items "
        "FROM sources s WHERE s.slug NOT LIKE 'demo-%' ORDER BY s.module, s.enabled DESC, s.name").fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["adapter_label"] = ADAPTER_LABELS.get(r["adapter"], r["adapter"])
        d["products"] = [PRODUCT_BY_ID[p].label for p in jload(r["product_ids"], []) if p in PRODUCT_BY_ID]
        out.append(d)
    return out


def system_view(conn: sqlite3.Connection) -> dict:
    cfg = load_config()
    hb = parse_iso(kv_get(conn, "worker_heartbeat"))
    alive = hb is not None and (now_utc() - hb).total_seconds() < 180
    requirements = []
    if not cfg.app_password:
        requirements.append(("warn", "APP_PASSWORD tanımlı değil: uygulama yalnızca bu makineden (localhost) erişilebilir."))
    if cfg.secret_key_is_ephemeral:
        requirements.append(("warn", "APP_SECRET_KEY tanımlı değil: oturumlar ve e-posta aksiyon bağlantıları yeniden başlatmada geçersizleşir."))
    if not cfg.llm_configured:
        requirements.append(("info", "LLM yapılandırılmadı (LLM_PROVIDER/ANTHROPIC_API_KEY): özetler AI'sız şablonla üretiliyor."))
    if not cfg.search_configured:
        requirements.append(("info", "Web araması yapılandırılmadı (SEARCH_PROVIDER): yalnızca listelenen kaynaklar taranıyor."))
    if not cfg.reddit_configured:
        requirements.append(("info", "Reddit Data API tanımlı değil (" + ", ".join(cfg.reddit_missing) + "): "
                                     "r/sysadmin, r/Intune ve r/SCCM okunmuyor."))
    if not cfg.telegram_bot_token:
        requirements.append(("info", "TELEGRAM_BOT_TOKEN tanımlı değil: Telegram bildirimi yapılamaz."))
    if not cfg.email_configured:
        requirements.append(("info", "SMTP ayarları eksik: e-posta bildirimi yapılamaz."))
    if not cfg.app_base_url.startswith("https://"):
        requirements.append(("info", "APP_BASE_URL https değil: Telegram'daki 'Uygulamada aç' düğmesi gösterilmiyor."))
    return {
        "worker_alive": alive, "worker_heartbeat": kv_get(conn, "worker_heartbeat"),
        "worker_started": kv_get(conn, "worker_started_at"), "last_check": kv_get(conn, "last_check_at"),
        "last_success": kv_get(conn, "last_success_check_at"), "baseline_at": kv_get(conn, "baseline_at"),
        "telegram_poll_at": kv_get(conn, "telegram_poll_at"),
        "jobs": [dict(r) for r in conn.execute("SELECT * FROM job_runs ORDER BY id DESC LIMIT 15")],
        "requests": [dict(r) for r in conn.execute("SELECT * FROM job_requests ORDER BY id DESC LIMIT 10")],
        "deliveries": delivery_overview(conn, 20), "usage": usage_summary(conn),
        "llm_today": today_totals(conn, "llm"), "search_today": today_totals(conn, "search"),
        "requirements": requirements, "channel_problems": channel_problems(conn), "coverage": coverage(conn),
        "cfg": {"llm_provider": cfg.llm_provider, "llm_model": cfg.llm_model, "llm_budget": cfg.llm_daily_budget_usd,
                "llm_calls": cfg.llm_max_calls_per_day, "search_provider": cfg.search_provider,
                "search_limit": cfg.search_daily_limit, "telegram_mode": cfg.telegram_mode},
    }


def nav_counts(conn: sqlite3.Connection) -> dict:
    crit = conn.execute("SELECT COUNT(*) FROM events e LEFT JOIN user_event_state u ON u.event_id = e.id WHERE e.is_demo = 0 "
                        "AND e.risk_level IN ('high','critical') AND e.relevance > 0 AND e.kind = 'issue' AND "
                        "e.status NOT IN ('resolved','resolved_external') AND (u.read_at IS NULL OR u.read_version < e.current_version) "
                        "AND u.muted_at IS NULL").fetchone()[0]
    followed = conn.execute("SELECT COUNT(*) FROM user_event_state WHERE followed = 1").fetchone()[0]
    return {"critical": crit, "followed": followed}
