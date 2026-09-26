"""Olay sürümlerinden kanal bağımsız "kart" görünüm modeli (web, Telegram, e-posta aynı modeli kullanır)."""
from __future__ import annotations

import sqlite3
from typing import Any

from ..catalog import PRODUCT_BY_ID
from ..db import jload
from ..sources.configmgr import HOTFIX_TYPE_TR
from ..sources.ms_support import RELEASE_TYPE_TR
from .analyze import CHANGE_TR, RISK_TR, STAGE_TR, STATUS_TR
from .evidence import EVIDENCE_LABELS
from .summarize import BASIS_LABELS

MODULE_TR = {"windows": "Windows", "intune": "Intune", "configmgr": "ConfigMgr", "community": "Saha",
             "news": "Haber", "content": "İçerik"}
KIND_TR = {"issue": "Sorun", "release": "Güncelleme", "feature": "Özellik", "notice": "Duyuru",
           "version": "Sürüm", "hotfix": "Hotfix", "news": "Haber", "content": "İçerik"}


def product_short(pid: str) -> str:
    p = PRODUCT_BY_ID.get(pid)
    if not p:
        return pid
    return (p.label.replace("Windows Server", "WS").replace("Windows 11, sürüm", "Win11")
            .replace("Windows 10, sürüm", "Win10").replace(" / Windows 10 1809", "").replace(" / Windows 10 1607", ""))


def build_card(conn: sqlite3.Connection, version_id: int, *, mode: str = "full") -> dict[str, Any] | None:
    row = conn.execute(
        "SELECT v.*, e.module, e.kind, e.category, e.title AS e_title, e.published_at, e.meaningful_update_at, "
        "e.last_checked_at, e.status AS e_status, e.evidence_level AS e_evidence, e.risk_level AS e_risk, "
        "e.current_version, e.is_demo, e.is_baseline, e.field_sources, e.state_json AS e_state, e.kbs_json, "
        "u.read_at, u.read_version, u.muted_at, u.followed, u.viewed_at "
        "FROM event_versions v JOIN events e ON e.id = v.event_id LEFT JOIN user_event_state u ON u.event_id = e.id "
        "WHERE v.id = ?", (version_id,),
    ).fetchone()
    if row is None:
        return None
    vstate = jload(row["state_json"], {})
    cur_state = jload(row["e_state"], {}) or vstate
    meta = cur_state.get("meta") or {}
    badges: list[dict[str, str]] = []
    if row["kind"] == "issue":
        ev = cur_state.get("evidence")
        badges.append({"kind": f"ev-{ev}", "text": EVIDENCE_LABELS.get(ev, "?")})
        badges.append({"kind": "status", "text": STATUS_TR.get(cur_state.get("status"), cur_state.get("status") or "?")})
    if cur_state.get("risk"):
        badges.append({"kind": f"risk-{cur_state['risk']}", "text": f"Risk: {RISK_TR[cur_state['risk']]}"})
    if cur_state.get("release_type"):
        badges.append({"kind": f"rt-{cur_state['release_type']}", "text": RELEASE_TYPE_TR.get(cur_state["release_type"], "")})
    if cur_state.get("stage"):
        badges.append({"kind": f"stage-{cur_state['stage']}", "text": STAGE_TR.get(cur_state["stage"], cur_state["stage"])})
    if cur_state.get("hotfix_type"):
        badges.append({"kind": "hotfix", "text": HOTFIX_TYPE_TR.get(cur_state["hotfix_type"], "")})
    if cur_state.get("track") == "tp":
        badges.append({"kind": "tp", "text": "Technical Preview"})
    if row["kind"] == "issue" and cur_state.get("evidence") == "field":
        n = meta.get("field_sources", 0)
        badges.append({"kind": "sources", "text": "Tek kaynak" if n <= 1 else f"{n} bağımsız kaynak"})
    if row["is_demo"]:
        badges.insert(0, {"kind": "demo", "text": "Demo"})
    kbs = sorted(set(cur_state.get("originating_kbs") or []) | ({cur_state["kb"]} if cur_state.get("kb") else set()))
    actions = jload(row["actions_json"], []) or []
    for a in actions:
        a["basis_label"] = BASIS_LABELS.get(a.get("basis"), a.get("basis"))
    changes = [c for c in jload(row["change_types_json"], []) if c != "new"]
    links = list(meta.get("official_refs") or []) + list(meta.get("field_refs") or [])
    return {
        "version_id": row["id"], "event_id": row["event_id"], "version": row["version"],
        "current_version": row["current_version"], "module": row["module"],
        "module_label": MODULE_TR.get(row["module"], row["module"]), "kind": row["kind"],
        "kind_label": KIND_TR.get(row["kind"], row["kind"]), "category": row["category"],
        "title": row["title_tr"] or row["e_title"], "source_title": row["e_title"],
        "summary": row["summary_tr"] or "", "why": row["why_tr"] or "",
        "what_changed": (row["what_changed_tr"] or row["change_note"] or "") if row["version"] > 1 else "",
        "change_labels": [CHANGE_TR.get(c, c) for c in changes], "change_types": changes,
        "details": row["details_tr"] or "", "actions": actions, "badges": badges,
        "kbs": kbs, "products": [product_short(p) for p in cur_state.get("products") or []],
        "risk": cur_state.get("risk"), "evidence": cur_state.get("evidence"), "status": cur_state.get("status"),
        "published_at": row["published_at"], "meaningful_update_at": row["created_at"],
        "last_checked_at": row["last_checked_at"], "links": links[:8],
        "primary_url": (links[0]["url"] if links else None),
        "summary_source": row["summary_source"] or "", "summary_note": row["summary_note"] or "",
        "ai": (row["summary_source"] or "").startswith("llm:"),
        "is_read": bool(row["read_at"]) and (row["read_version"] or 0) >= row["version"],
        "is_muted": bool(row["muted_at"]), "is_followed": bool(row["followed"]), "is_viewed": bool(row["viewed_at"]),
        "is_demo": bool(row["is_demo"]), "is_stale_version": row["version"] < row["current_version"],
        "mode": mode, "field_sources": meta.get("field_sources", 0),
        "workaround_text": meta.get("workaround_text", ""),
    }
