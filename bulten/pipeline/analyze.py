"""Adım 4: Değişiklik analizi, teyit düzeyi ve risk.

Her olay için bağlı tüm kanıtlardan bir "maddi durum" hesaplanır. Yeni bir olay sürümü
(`event_versions`) yalnızca maddi bir değişiklikte oluşturulur:
  Microsoft teyidi geldi, kapsam genişledi/daraldı (düzeltme), risk anlamlı değişti,
  geçici çözüm veya düzeltme yayımlandı, sorun yeniden açıldı, Intune aşaması değişti,
  destek bitişi yaklaştı, güncelleme geri çekildi (EXPIRED)...
Yazım, tarih ve sayfa düzeni değişiklikleri durumu değiştirmez → yeni sürüm oluşmaz.

Risk (sorunun nesnel etkisi) ile kanıt gücü (teyit düzeyi) ayrı hesaplanır. Kullanıcıya
göre değişen "ilgi" (relevance) ise durumdan bağımsız tutulur; ayar değişikliği yeni sürüm üretmez.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..db import jdump, jload, tx
from ..settings_store import EVIDENCE_ORDER, RISK_ORDER, get_settings
from ..sources.configmgr import HOTFIX_TYPE_TR
from ..sources.ms_support import RELEASE_TYPE_TR
from ..textutil import (
    DOMAIN_NOISE, ROLE_TO_TAGS, TAG_LABELS_TR, fold, jaccard, specific_tags, token_set,
)
from ..catalog import PRODUCT_BY_ID
from ..timeutil import now_iso
from .evidence import count_independent, effective_trust, evidence_for_observation

RESOLVED = {"resolved", "resolved_external"}
MITIGATED = {"mitigated", "mitigated_external"}
STATUS_TR = {
    "investigating": "İnceleniyor", "confirmed": "Doğrulandı (açık)", "mitigated": "Hafifletildi",
    "mitigated_external": "Hafifletildi (harici)", "resolved": "Çözüldü", "resolved_external": "Çözüldü (harici)",
    "reported": "Bildirildi (teyitsiz)", "unknown": "Bilinmiyor", "info": "Bilgi",
}
RISK_TR = {"low": "Düşük", "medium": "Orta", "high": "Yüksek", "critical": "Kritik"}
STAGE_TR = {"in_development": "Geliştirme aşamasında", "public_preview": "Public preview",
            "ga": "Genel kullanıma açıldı", "notice": "Önemli duyuru"}
CHANGE_TR = {
    "new": "Yeni", "ms_confirmed": "Microsoft teyidi", "scope_expanded": "Kapsam genişledi",
    "correction": "Düzeltme", "risk_changed": "Risk değişti", "workaround": "Geçici çözüm",
    "workaround_updated": "Geçici çözüm güncellendi", "fix": "Düzeltme yayımlandı", "reopened": "Yeniden açıldı",
    "spread": "Daha fazla saha raporu", "stage_changed": "Aşama değişti", "action_required": "Yönetici aksiyonu",
    "deprecation": "Kaldırma/destek sonu", "support_ending": "Destek bitişi yaklaşıyor", "pulled": "Geri çekildi",
}


# --- Durum hesaplama ------------------------------------------------------------

def _load_obs(conn: sqlite3.Connection, event_id: int) -> list[dict]:
    rows = conn.execute(
        "SELECT o.*, s.trust AS s_trust, s.adapter AS s_adapter, s.name AS s_name, s.config_json AS s_config, "
        " (SELECT id FROM observation_snapshots sn WHERE sn.observation_id = o.id ORDER BY sn.id DESC LIMIT 1) AS snap_id "
        "FROM observations o JOIN sources s ON s.id = o.source_id WHERE o.event_id = ? ORDER BY o.id",
        (event_id,),
    ).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        d["fields"] = jload(r["fields_json"], {})
        d["trust"] = effective_trust(r["s_trust"], r["url"], d["fields"])
        d["evidence"] = evidence_for_observation(r["kind"], d["trust"])
        out.append(d)
    return out


def _bucket_sources(n: int) -> int:
    return 5 if n >= 5 else 2 if n >= 2 else 1 if n >= 1 else 0


def _support_bucket(days_left: int | None) -> str:
    if days_left is None:
        return "unknown"
    if days_left < 0:
        return "ended"
    for limit in (7, 30, 90, 180):
        if days_left <= limit:
            return f"<={limit}"
    return ">180"


def _wa_tokens(text: str) -> list[str]:
    return sorted(token_set(text or "", noise=DOMAIN_NOISE))


def compute_issue_state(obs: list[dict]) -> dict[str, Any]:
    ki = [o for o in obs if o["evidence"] == "ms_known_issue"]
    off = [o for o in obs if o["evidence"] == "ms_official"]
    field = [o for o in obs if o["evidence"] == "field"]
    evidence = "ms_known_issue" if ki else "ms_official" if off else "field"
    primary = ki or off or field
    # Durum: en güncel resmî bilinen sorun kaydı (Release health > KB makalesi)
    status = "reported"
    if ki:
        def _rank(o):
            return (1 if o["external_key"].startswith("wrh:") else 0, o.get("source_updated_at") or "", o["id"])
        best = max(ki, key=_rank)
        status = best["fields"].get("status") or "confirmed"
        if status == "unknown":
            status = "confirmed"
        # Herhangi bir resmî kayıt çözüldü diyorsa ve diğeri daha eskiyse zaten sıralama bunu seçer.
    elif off:
        status = "confirmed"
    products: set[str] = set()
    tags: set[str] = set()
    okbs: set[str] = set()
    rkbs: set[str] = set()
    workaround_texts: list[str] = []
    kir = False
    for o in primary:
        f = o["fields"]
        products.update(f.get("products") or [])
        tags.update(f.get("tags") or [])
        okbs.update(f.get("originating_kbs") or ([f["kb"]] if f.get("kb") and o["kind"] == "known_issue" else []))
        if o["evidence"] != "field":
            rkbs.update(f.get("resolving_kbs") or [])
            if f.get("workaround"):
                workaround_texts.append(f["workaround"])
            kir = kir or bool(f.get("kir"))
    if evidence == "field":
        for o in field:
            okbs.update(o["fields"].get("kbs") or [])
    items = [{"url": o["url"], "title": o["title"], "body": o["body"], "trust": o["trust"],
              "author": o["fields"].get("author")} for o in field]
    n_field = count_independent(items) if items else 0
    wa_text = " ".join(workaround_texts)
    state = {
        "type": "issue", "evidence": evidence, "status": status, "products": sorted(products),
        "tags": sorted(tags), "originating_kbs": sorted(okbs), "resolving_kbs": sorted(rkbs),
        "workaround": bool(wa_text.strip()) or kir, "workaround_tokens": _wa_tokens(wa_text), "kir": kir,
        "fix": status in RESOLVED or bool(rkbs), "field_bucket": _bucket_sources(n_field),
        "meta": {
            "field_sources": n_field,
            "official_refs": [{"url": o["url"], "title": o["title"], "source": o["s_name"], "kind": o["kind"]}
                              for o in (ki + off)][:6],
            "field_refs": [{"url": o["url"], "title": o["title"], "source": o["fields"].get("source_name") or o["s_name"],
                            "trust": o["trust"]} for o in field][:8],
            "workaround_text": wa_text[:1500],
        },
    }
    state["risk"] = compute_risk(state)
    return state


def compute_state(kind: str, obs: list[dict]) -> dict[str, Any]:
    if kind == "issue":
        return compute_issue_state(obs)
    official = [o for o in obs if o["trust"] == "official"] or obs
    main = max(official, key=lambda o: (o.get("source_updated_at") or o.get("published_at") or "", o["id"]))
    f = main["fields"]
    field_obs = [o for o in obs if o["kind"] == "field_report"]
    meta = {"field_sources": len(field_obs),
            "field_refs": [{"url": o["url"], "title": o["title"], "source": o["fields"].get("source_name") or o["s_name"],
                            "trust": o["trust"]} for o in field_obs][:6],
            "official_refs": [{"url": o["url"], "title": o["title"], "source": o["s_name"], "kind": o["kind"]}
                              for o in official if o["trust"] == "official"][:4]}
    if kind == "release":
        prods = sorted({p for o in official for p in (o["fields"].get("products") or [])})
        st = {"type": "release", "kb": f.get("kb"), "release_type": f.get("release_type"), "products": prods,
              "builds": sorted({b for o in official for b in (o["fields"].get("builds") or [])}),
              "expired": any(o["fields"].get("expired") for o in official), "meta": meta}
    elif kind in ("feature", "notice"):
        st = {"type": kind, "stage": f.get("stage"), "change_kind": f.get("change_kind"),
              "platforms": sorted({p for o in official for p in (o["fields"].get("platforms") or [])}),
              "admin_action": any(bool(o["fields"].get("admin_action")) for o in official),
              "license": bool(f.get("license_note")), "meta": {**meta,
                                                              "admin_action_text": f.get("admin_action") or "",
                                                              "license_note": f.get("license_note") or "",
                                                              "rollout_note": f.get("rollout_note") or "",
                                                              "work_items": f.get("work_items") or [],
                                                              "week": f.get("week"),
                                                              "service_release": f.get("service_release")}}
        if main["kind"] == "announcement":
            st = {"type": "notice", "stage": "notice", "change_kind": "announcement", "platforms": [],
                  "admin_action": False, "license": False, "meta": meta}
    elif kind == "version":
        st = {"type": "version", "version": f.get("version"), "track": f.get("track"),
              "supported": f.get("supported", True), "support_bucket": _support_bucket(f.get("support_days_left")),
              "meta": {**meta, "support_end": f.get("support_end"), "availability": f.get("availability"),
                       "build": f.get("build"), "support_days_left": f.get("support_days_left")}}
    elif kind == "hotfix":
        st = {"type": "hotfix", "kb": f.get("kb"), "versions": sorted(f.get("versions") or []),
              "hotfix_type": f.get("hotfix_type"), "meta": {**meta, "fixed_issues": f.get("fixed_issues") or [],
                                                             "summary": f.get("summary") or ""}}
    else:
        st = {"type": kind, "meta": {**meta, "sources": sorted({o["s_name"] for o in obs}),
                                     "source_count": len({o["source_id"] for o in obs})}}
    st["risk"] = compute_risk(st)
    return st


def compute_risk(state: dict[str, Any]) -> str | None:
    t = state.get("type")
    if t == "issue":
        tags = set(state.get("tags") or [])
        if "security" in tags:
            impact = 3.5
        elif tags & {"dc", "auth", "boot", "bitlocker"}:
            impact = 3.0
        elif tags & {"rds", "vpn", "network", "hyperv", "avd"}:
            impact = 2.75
        elif tags & {"update_install", "printing", "storage", "adcs", "gpo", "configmgr", "intune", "iis"}:
            impact = 2.0
        elif tags:
            impact = 1.5
        else:
            impact = 1.25
        if any(PRODUCT_BY_ID.get(p) and PRODUCT_BY_ID[p].family == "server" for p in state.get("products") or []):
            impact += 0.25
        status = state.get("status")
        if status in RESOLVED:
            impact -= 1.5
        elif status in MITIGATED or state.get("workaround"):
            impact -= 0.25
        if impact >= 3.25:
            return "critical"
        if impact >= 2.5:
            return "high"
        if impact >= 1.75:
            return "medium"
        return "low"
    if t == "release":
        if state.get("expired"):
            return "high"
        return {"oob": "high", "security": "medium", "hotpatch": "medium"}.get(state.get("release_type"), "low")
    if t == "version":
        b = state.get("support_bucket")
        if state.get("track") == "tp":
            return "low"
        return {"ended": "high", "<=7": "high", "<=30": "high", "<=90": "medium"}.get(b, "low")
    if t == "hotfix":
        return {"security": "high", "rollup": "medium", "hotfix": "medium"}.get(state.get("hotfix_type"), "low")
    if t in ("feature", "notice"):
        if state.get("change_kind") == "deprecation" or state.get("admin_action"):
            return "medium"
        return "low"
    return None


def state_hash(state: dict[str, Any]) -> str:
    core = {k: v for k, v in state.items() if k != "meta"}
    return hashlib.sha256(json.dumps(core, sort_keys=True, default=str).encode()).hexdigest()


# --- Fark analizi -----------------------------------------------------------------

def _plabels(ids: list[str] | set[str]) -> str:
    return ", ".join(PRODUCT_BY_ID[p].label if p in PRODUCT_BY_ID else p for p in sorted(ids))


def diff_states(prev: dict[str, Any], new: dict[str, Any]) -> tuple[list[str], bool, list[str]]:
    """(değişiklik türleri, maddi mi, Türkçe açıklama satırları)."""
    changes: list[str] = []
    notes: list[str] = []
    major = False
    t = new.get("type")

    def add(kind: str, note: str, is_major: bool = True) -> None:
        nonlocal major
        if kind not in changes:
            changes.append(kind)
        notes.append(note)
        major = major or is_major

    if t == "issue":
        pe, ne = prev.get("evidence"), new.get("evidence")
        if ne in EVIDENCE_ORDER and pe in EVIDENCE_ORDER and EVIDENCE_ORDER.index(ne) > EVIDENCE_ORDER.index(pe):
            if ne == "ms_known_issue":
                add("ms_confirmed", "Microsoft sorunu Known issues kaydına ekledi (resmî teyit).")
            else:
                add("ms_confirmed", "Microsoft sorunu resmî bir kaynakta doğruladı.")
        ps, ns = prev.get("status"), new.get("status")
        if ps != ns:
            if ns in RESOLVED and ps not in RESOLVED:
                add("fix", f"Durum: {STATUS_TR.get(ns, ns)}.")
            elif ps in RESOLVED and ns not in RESOLVED:
                add("reopened", f"Sorun yeniden açık olarak işaretlendi ({STATUS_TR.get(ns, ns)}).")
            elif ns in MITIGATED and ps not in MITIGATED:
                add("workaround", f"Durum: {STATUS_TR.get(ns, ns)}.")
            else:
                add("status", f"Durum: {STATUS_TR.get(ps, ps)} → {STATUS_TR.get(ns, ns)}.", is_major=False)
        added_p = set(new.get("products") or []) - set(prev.get("products") or [])
        removed_p = set(prev.get("products") or []) - set(new.get("products") or [])
        if added_p:
            add("scope_expanded", f"Etkilenen kapsam genişledi: + {_plabels(added_p)}.")
        if removed_p and not added_p:
            add("correction", f"Etkilenen ürün listesi düzeltildi: − {_plabels(removed_p)}.")
        added_t = specific_tags(new.get("tags") or []) - specific_tags(prev.get("tags") or [])
        if added_t and prev.get("tags"):
            add("scope_expanded", "Yeni belirti/etki alanı: " + ", ".join(TAG_LABELS_TR.get(x, x) for x in sorted(added_t)) + ".")
        added_k = set(new.get("originating_kbs") or []) - set(prev.get("originating_kbs") or [])
        if added_k and prev.get("originating_kbs"):
            add("scope_expanded", "Sorunu tetikleyen güncellemeler: + " + ", ".join(f"KB{k}" for k in sorted(added_k)) + ".")
        if new.get("workaround") and not prev.get("workaround"):
            add("workaround", "Geçici çözüm yayımlandı" + (" (Known Issue Rollback)." if new.get("kir") else "."))
        elif new.get("kir") and not prev.get("kir"):
            add("workaround", "Known Issue Rollback (KIR) yayımlandı.")
        elif new.get("workaround") and prev.get("workaround"):
            sim = jaccard(set(prev.get("workaround_tokens") or []), set(new.get("workaround_tokens") or []))
            if sim < 0.5:
                add("workaround_updated", "Geçici çözüm metni önemli ölçüde değişti.")
        added_r = set(new.get("resolving_kbs") or []) - set(prev.get("resolving_kbs") or [])
        if added_r:
            add("fix", "Düzeltme içeren güncelleme: " + ", ".join(f"KB{k}" for k in sorted(added_r)) + ".")
        if ne == "field" and (new.get("field_bucket") or 0) > (prev.get("field_bucket") or 0) and prev.get("field_bucket"):
            add("spread", f"Bağımsız saha raporu sayısı arttı ({new['meta'].get('field_sources')}).")
    elif t == "release":
        if new.get("release_type") != prev.get("release_type"):
            add("correction", f"Güncelleme türü düzeltildi: {RELEASE_TYPE_TR.get(new.get('release_type'), '?')}.")
        if new.get("expired") and not prev.get("expired"):
            add("pulled", "Microsoft bu güncellemeyi geri çekti/süresi doldu (EXPIRED).")
        if set(new.get("products") or []) - set(prev.get("products") or []):
            add("scope", "Ürün listesi genişledi.", is_major=False)
    elif t in ("feature", "notice"):
        if new.get("stage") != prev.get("stage"):
            add("stage_changed", f"Aşama: {STAGE_TR.get(prev.get('stage'), prev.get('stage'))} → "
                                 f"{STAGE_TR.get(new.get('stage'), new.get('stage'))}.")
        if new.get("change_kind") == "deprecation" and prev.get("change_kind") != "deprecation":
            add("deprecation", "Kaldırma / destek sonu bilgisi eklendi.")
        if new.get("admin_action") and not prev.get("admin_action"):
            add("action_required", "Yönetici aksiyonu gerektiren bilgi eklendi.")
        if set(new.get("platforms") or []) - set(prev.get("platforms") or []):
            add("scope", "Platform listesi genişledi.", is_major=False)
    elif t == "version":
        if new.get("support_bucket") != prev.get("support_bucket"):
            b = new.get("support_bucket")
            if b == "ended":
                add("support_ending", "Destek süresi sona erdi.")
            elif b and b.startswith("<="):
                add("support_ending", f"Destek bitişine {new['meta'].get('support_days_left')} gün kaldı.")
    elif t == "hotfix":
        if new.get("hotfix_type") != prev.get("hotfix_type"):
            add("correction", f"Tür düzeltildi: {HOTFIX_TYPE_TR.get(new.get('hotfix_type'), '?')}.")
        if set(new.get("versions") or []) - set(prev.get("versions") or []):
            add("scope", "Geçerli sürüm listesi genişledi.", is_major=False)

    pr, nr = prev.get("risk"), new.get("risk")
    if pr in RISK_ORDER and nr in RISK_ORDER and pr != nr:
        delta = RISK_ORDER.index(nr) - RISK_ORDER.index(pr)
        add("risk_changed", f"Risk {'yükseldi' if delta > 0 else 'düştü'}: {RISK_TR[pr]} → {RISK_TR[nr]}.",
            is_major=abs(delta) >= 1 and (delta > 0 or t == "issue"))
    return changes, major, notes


# --- İlgi (kullanıcıya göre) ------------------------------------------------------

def compute_relevance(event: dict[str, Any], state: dict[str, Any], settings: dict[str, Any],
                      followed: bool = False, text: str = "") -> float:
    rel = 0.0
    user_products = set(settings.get("products") or [])
    prods = set(state.get("products") or event.get("products") or [])
    if user_products and prods & user_products:
        rel += 2.0
    elif not user_products and event.get("module") == "windows":
        rel += 0.5
    role_tags: set[str] = set()
    for role in settings.get("roles") or []:
        role_tags |= ROLE_TO_TAGS.get(role, set())
    if role_tags & set(state.get("tags") or event.get("tags") or []):
        rel += 1.5
    cm_ver = settings.get("configmgr_version")
    if event.get("module") == "configmgr":
        if state.get("type") == "version" and cm_ver and state.get("version") == cm_ver:
            rel += 3.0
        elif state.get("type") == "hotfix" and cm_ver and cm_ver in (state.get("versions") or []):
            rel += 2.0
        elif state.get("type") == "version" and state.get("track") == "tp" and "tp" in (settings.get("configmgr_tracks") or []):
            rel += 0.5
        elif not cm_ver:
            rel += 0.5
    if event.get("module") == "intune":
        plats = set(state.get("platforms") or [])
        if not plats or plats & set(settings.get("intune_platforms") or []):
            rel += 1.0
    if followed:
        rel += 3.0
    ftext = fold(text)
    for kw in settings.get("keywords") or []:
        if kw and fold(kw) in ftext:
            rel += 1.0
    for kw in settings.get("exclude_keywords") or []:
        if kw and fold(kw) in ftext:
            rel -= 100.0
    return rel


# --- Ana döngü --------------------------------------------------------------------

def analyze_events(conn: sqlite3.Connection, event_ids: list[int] | None = None) -> list[int]:
    settings = get_settings(conn)
    if event_ids is None:
        event_ids = [r["id"] for r in conn.execute("SELECT id FROM events WHERE needs_analysis = 1")]
    created: list[int] = []
    for eid in event_ids:
        with tx(conn):
            vid = _analyze_one(conn, eid, settings)
            if vid:
                created.append(vid)
    return created


def _analyze_one(conn: sqlite3.Connection, event_id: int, settings: dict[str, Any]) -> int | None:
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    if ev is None:
        return None
    obs = _load_obs(conn, event_id)
    if not obs:
        conn.execute("UPDATE events SET needs_analysis = 0 WHERE id = ?", (event_id,))
        return None
    state = compute_state(ev["kind"], obs)
    last = conn.execute(
        "SELECT * FROM event_versions WHERE event_id = ? ORDER BY version DESC LIMIT 1", (event_id,)
    ).fetchone()
    ts = now_iso()
    version_id = None
    if last is None:
        changes, major, notes = ["new"], True, ["İlk kez görüldü."]
    else:
        changes, major, notes = diff_states(jload(last["state_json"], {}), state)
    if major:
        new_ver = (last["version"] + 1) if last else 1
        version_id = conn.execute(
            "INSERT INTO event_versions(event_id, version, created_at, state_json, state_hash, change_types_json, "
            "change_note, is_major) VALUES (?, ?, ?, ?, ?, ?, ?, 1)",
            (event_id, new_ver, ts, jdump(state), state_hash(state), jdump(changes), " ".join(notes)),
        ).lastrowid
        for o in obs:
            conn.execute("INSERT OR IGNORE INTO event_version_evidence(event_version_id, observation_id, snapshot_id) "
                         "VALUES (?, ?, ?)", (version_id, o["id"], o["snap_id"]))
        baseline = 0
        if last is None and ev["module"] not in ("news",) and all(o["from_first_run"] for o in obs):
            baseline = 1
        conn.execute("UPDATE events SET current_version = ?, meaningful_update_at = ?, is_baseline = CASE WHEN ? = 1 "
                     "THEN is_baseline ELSE ? END WHERE id = ?",
                     (new_ver, ts, 1 if last else 0, baseline, event_id))
    # Olayın güncel görünümü (sürüm oluşmasa da güncellenir)
    official = [o for o in obs if o["trust"] == "official"]
    title = ev["title"]
    if official:
        pref = [o for o in official if o["external_key"].startswith("wrh:")] or official
        title = pref[0]["title"]
    followed = bool((conn.execute("SELECT followed FROM user_event_state WHERE event_id = ?", (event_id,)).fetchone()
                     or {"followed": 0})["followed"])
    text = " ".join([title] + [o["body"][:500] for o in obs[:5]])
    rel = compute_relevance({"module": ev["module"], "products": jload(ev["products_json"], []),
                             "tags": jload(ev["tags_json"], [])}, state, settings, followed, text)
    kbs = set(state.get("originating_kbs") or []) | ({state["kb"]} if state.get("kb") else set())
    for o in obs:
        kbs.update(o["fields"].get("kbs") or [])
    signature_tokens = set((ev["signature"] or "").split())
    for o in official[:3]:
        signature_tokens |= token_set(o["title"], noise=DOMAIN_NOISE)
    pub = min((o["published_at"] for o in obs if o["published_at"]), default=ev["published_at"])
    conn.execute(
        "UPDATE events SET title = ?, status = ?, evidence_level = ?, risk_level = ?, relevance = ?, "
        "products_json = ?, kbs_json = ?, tags_json = ?, signature = ?, state_json = ?, field_sources = ?, "
        "published_at = ?, last_checked_at = ?, needs_analysis = 0 WHERE id = ?",
        (title, state.get("status") or ("info" if ev["kind"] != "issue" else None),
         state.get("evidence") if ev["kind"] == "issue" else ("ms_official" if official else "field"),
         state.get("risk"), rel, jdump(state.get("products") or jload(ev["products_json"], [])), jdump(sorted(kbs)),
         jdump(state.get("tags") or jload(ev["tags_json"], [])), " ".join(sorted(signature_tokens))[:2000],
         jdump(state), (state.get("meta") or {}).get("field_sources", 0), pub, ts, event_id),
    )
    conn.execute("UPDATE observations SET needs_analysis = 0 WHERE event_id = ?", (event_id,))
    return version_id


def recompute_relevance(conn: sqlite3.Connection) -> None:
    """Ayarlar değişince ilgi puanlarını yeniden hesapla (yeni sürüm oluşturmaz)."""
    settings = get_settings(conn)
    with tx(conn):
        for ev in conn.execute("SELECT e.*, COALESCE(u.followed, 0) AS followed FROM events e "
                               "LEFT JOIN user_event_state u ON u.event_id = e.id").fetchall():
            state = jload(ev["state_json"], {})
            rel = compute_relevance({"module": ev["module"], "products": jload(ev["products_json"], []),
                                     "tags": jload(ev["tags_json"], [])}, state, settings, bool(ev["followed"]),
                                    ev["title"])
            conn.execute("UPDATE events SET relevance = ? WHERE id = ?", (rel, ev["id"]))


def unresolved_is_open(status: str | None) -> bool:
    return status not in RESOLVED and status not in (None, "info")

