"""Ayarlar formunun doğrulanması ve kullanıcı tanımlı kaynakların yönetimi."""
from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..catalog import CONFIGMGR_VERSIONS, INTUNE_PLATFORMS, NEWS_CATEGORIES, PRODUCT_BY_ID, ROLES
from ..db import jdump
from ..net.ssrf import UnsafeURL, validate_url_syntax
from ..pipeline.evidence import classify_url
from ..settings_store import EVIDENCE_ORDER, LENGTH_PRESETS, RISK_ORDER
from ..sources.base import slugify
from ..timeutil import now_iso, parse_hhmm, tz

TIME_RE = re.compile(r"^\d{1,2}[:.]\d{2}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class FormError(ValueError):
    pass


def _lines(value: str) -> list[str]:
    parts = re.split(r"[\n,;]+", value or "")
    return [p.strip() for p in parts if p.strip()][:50]


def _time(value: str, default: str) -> str:
    value = (value or "").strip()
    if not value:
        return default
    if not TIME_RE.match(value):
        raise FormError(f"Geçersiz saat: {value} (SS:DD biçiminde olmalı)")
    h, m = parse_hhmm(value, (-1, -1))
    if h < 0:
        raise FormError(f"Geçersiz saat: {value}")
    return f"{h:02d}:{m:02d}"


def _int(value: str, lo: int, hi: int, default: int) -> int:
    try:
        v = int(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def parse_settings_form(form: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Form alanlarını doğrulanmış ayar sözlüğüne çevirir. Yalnızca formda bulunan bölümler güncellenir."""
    get = form.get
    getlist = form.getlist if hasattr(form, "getlist") else (lambda k: form.get(k) or [])
    sections = set(getlist("_sections"))
    out: dict[str, Any] = {}
    if "genel" in sections:
        tzname = (get("timezone") or "Europe/Istanbul").strip()
        if tz(tzname).key != tzname:
            raise FormError(f"Bilinmeyen saat dilimi: {tzname}")
        out["timezone"] = tzname
        b = dict(current.get("bulletin") or {})
        b["time"] = _time(get("bulletin_time"), "08:00")
        b["weekend"] = get("bulletin_weekend") == "on"
        b["length"] = get("bulletin_length") if get("bulletin_length") in LENGTH_PRESETS else "orta"
        b["catch_up_until"] = _time(get("catch_up_until"), b.get("catch_up_until", "12:00"))
        out["bulletin"] = b
        out["quiet_hours"] = {"enabled": get("quiet_enabled") == "on", "start": _time(get("quiet_start"), "22:30"),
                              "end": _time(get("quiet_end"), "07:30")}
    if "moduller" in sections:
        mods = {k: get(f"mod_{k}") == "on" for k in (current.get("modules") or {})}
        out["modules"] = mods
    if "ortam" in sections:
        out["products"] = [p for p in getlist("products") if p in PRODUCT_BY_ID]
        out["roles"] = [r for r in getlist("roles") if r in ROLES]
        cm = get("configmgr_version") or ""
        out["configmgr_version"] = cm if cm in CONFIGMGR_VERSIONS else None
        out["configmgr_tracks"] = [t for t in getlist("configmgr_tracks") if t in ("current", "early_ring", "hotfix", "tp")]
        out["intune_platforms"] = [p for p in getlist("intune_platforms") if p in INTUNE_PLATFORMS]
    if "konum" in sections:
        raw = get("location_json") or ""
        if raw:
            try:
                loc = json.loads(raw)
                out["location"] = {k: loc.get(k) for k in ("name", "admin1", "admin2", "country", "lat", "lon", "district")}
                if out["location"]["lat"] is None or out["location"]["lon"] is None:
                    raise FormError("Konum koordinatları eksik.")
                out["location"]["district"] = (get("district") or "").strip()[:80] or out["location"].get("district")
            except (ValueError, AttributeError) as exc:
                raise FormError("Konum verisi okunamadı; listeden yeniden seçin.") from exc
        elif get("location_clear") == "on":
            out["location"] = None
        mgm = (get("mgm_warning_url") or "").strip()
        if mgm:
            _check_url(mgm)
        out["mgm_warning_url"] = mgm
    if "bildirim" in sections:
        out["channels"] = {"telegram": get("ch_telegram") == "on", "email": get("ch_email") == "on"}
        chat = (get("telegram_chat_id") or "").strip()
        if chat and not re.fullmatch(r"-?\d{3,20}", chat):
            raise FormError("Telegram sohbet kimliği yalnızca rakamlardan oluşmalı (grup için başında '-' olabilir).")
        out["telegram_chat_id"] = chat
        email = (get("email_to") or "").strip()
        if email and not EMAIL_RE.match(email):
            raise FormError("E-posta adresi geçersiz.")
        out["email_to"] = email
        crit = dict(current.get("critical") or {})
        crit["enabled"] = get("crit_enabled") == "on"
        crit["interval_min"] = _int(get("crit_interval"), 15, 1440, 60)
        crit["min_risk"] = get("crit_min_risk") if get("crit_min_risk") in RISK_ORDER else "high"
        crit["min_evidence"] = get("crit_min_evidence") if get("crit_min_evidence") in EVIDENCE_ORDER else "ms_official"
        crit["allow_field"] = get("crit_allow_field") == "on"
        crit["field_min_sources"] = _int(get("crit_field_min_sources"), 1, 10, 2)
        crit["quiet_exception"] = get("crit_quiet_exception") if get("crit_quiet_exception") in (
            "none", "ms_critical", "all_critical") else "none"
        crit["morning_reference"] = get("crit_morning_reference") == "on"
        out["critical"] = crit
        out["resurface"] = {
            "read": get("resurface_read") if get("resurface_read") in ("notify", "bulletin_only", "silent") else "notify",
            "muted": get("resurface_muted") if get("resurface_muted") in ("silent", "critical_only", "notify") else "silent",
        }
    if "icerik" in sections:
        limits = dict(current.get("category_limits") or {})
        for k in list(limits):
            limits[k] = _int(get(f"limit_{k}"), 0, 20, limits[k])
        out["category_limits"] = limits
        out["keywords"] = _lines(get("keywords"))
        out["exclude_keywords"] = _lines(get("exclude_keywords"))
        out["topics"] = _lines(get("topics"))
        out["news_categories"] = [c for c in getlist("news_categories") if c in NEWS_CATEGORIES]
        m = dict(current.get("markets") or {})
        m["items"] = [i for i in getlist("market_items") if i in ("USDTRY", "EURTRY", "GRAM24", "BILEZIK22")]
        m["provider"] = get("market_provider") if get("market_provider") in ("truncgil", "json", "none") else "truncgil"
        m["show_tcmb"] = get("show_tcmb") == "on"
        out["markets"] = m
        ics = (get("calendar_ics_url") or "").strip()
        if ics:
            _check_url(ics.replace("webcal://", "https://", 1))
            ics = ics.replace("webcal://", "https://", 1)
        out["calendar_ics_url"] = ics
        channels = []
        for line in (get("youtube_channels") or "").splitlines():
            line = line.strip()
            if not line:
                continue
            cid, _, name = line.partition("|")
            cid = cid.strip()
            if not re.fullmatch(r"UC[\w-]{20,30}", cid):
                raise FormError(f"YouTube kanal kimliği 'UC' ile başlamalı: {cid}")
            channels.append({"id": cid, "name": name.strip() or cid})
        out["youtube_channels"] = channels[:30]
        out["baseline_max_items"] = _int(get("baseline_max_items"), 0, 30, 8)
    return out


def _check_url(url: str) -> None:
    try:
        validate_url_syntax(url)
    except UnsafeURL as exc:
        raise FormError(f"Adres kabul edilmedi: {exc}") from exc


def add_user_source(conn: sqlite3.Connection, *, name: str, url: str, module: str, category: str | None,
                    trust: str) -> int:
    """Kullanıcı kaynağı ekler. Özel ağ adresleri reddedilir; 'resmî' yalnızca URL kuralları doğrularsa verilir."""
    name = (name or "").strip()[:120]
    url = (url or "").strip()
    if not name or not url:
        raise FormError("Ad ve adres gerekli.")
    _check_url(url)
    if module not in ("community", "news", "content", "windows", "intune", "configmgr"):
        raise FormError("Geçersiz modül.")
    if module == "news" and category not in NEWS_CATEGORIES:
        raise FormError("Haber kaynağı için kategori seçin.")
    by_url = classify_url(url)
    if trust == "official" and by_url != "official":
        trust = "user"  # resmî etiket yalnızca Microsoft resmî alan/yol kurallarıyla
    if trust not in ("official", "press", "community", "user"):
        trust = "user"
    slug = "user-" + slugify(name, 40)
    base, i = slug, 2
    while conn.execute("SELECT 1 FROM sources WHERE slug = ?", (slug,)).fetchone():
        slug, i = f"{base}-{i}", i + 1
    cfg = {"max_age_days": 3 if module == "news" else 7}
    return conn.execute(
        "INSERT INTO sources(slug, name, module, adapter, url, trust, category, enabled, builtin, critical, config_json, "
        "validation_note, created_at, updated_at) VALUES (?, ?, ?, 'rss', ?, ?, ?, 1, 0, 0, ?, 'Kullanıcı ekledi', ?, ?)",
        (slug, name, module, url, trust, category if module == "news" else None, jdump(cfg), now_iso(), now_iso()),
    ).lastrowid


def sync_youtube_sources(conn: sqlite3.Connection, settings: dict) -> None:
    wanted = {c["id"]: c for c in settings.get("youtube_channels") or []}
    existing = {r["slug"]: r for r in conn.execute("SELECT * FROM sources WHERE slug LIKE 'yt-%'")}
    for cid, ch in wanted.items():
        slug = f"yt-{cid}"
        if slug not in existing:
            conn.execute(
                "INSERT INTO sources(slug, name, module, adapter, url, trust, enabled, builtin, critical, config_json, "
                "validation_note, created_at, updated_at) VALUES (?, ?, 'content', 'rss', ?, 'user', 1, 0, 0, ?, "
                "'YouTube kanal RSS', ?, ?)",
                (slug, f"YouTube: {ch['name']}", f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
                 jdump({"max_age_days": 7}), now_iso(), now_iso()))
    for slug in existing:
        if slug[3:] not in wanted:
            conn.execute("UPDATE sources SET enabled = 0 WHERE slug = ?", (slug,))
