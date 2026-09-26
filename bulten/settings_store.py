"""Kullanıcı tercihleri (tek kullanıcı). Varsayılanlar + DB'de saklanan değişiklikler.

Konum, ürün sürümleri ve ConfigMgr sürümü tahmin edilmez: varsayılanları boştur
ve kurulum sihirbazında kullanıcı tarafından seçilir.
"""
from __future__ import annotations

import copy
import sqlite3
from typing import Any

from .config import load_config
from .db import jdump, jload
from .timeutil import now_iso

RISK_ORDER = ["low", "medium", "high", "critical"]
EVIDENCE_ORDER = ["field", "ms_official", "ms_known_issue"]

LENGTH_PRESETS = {
    # yaklaşık okuma süresi 3-5 dk: kart sayısı üst sınırları
    "kisa": {"total_items": 10},
    "orta": {"total_items": 16},
    "uzun": {"total_items": 24},
}

DEFAULTS: dict[str, Any] = {
    "onboarding_done": False,
    "timezone": None,                       # None → config.default_timezone (Europe/Istanbul)
    "location": None,                       # {"name","admin1","country","lat","lon","district"}
    "mgm_warning_url": "",                  # kullanıcı isterse MGM MeteoUyarı il sayfası
    "modules": {
        "windows": True,
        "intune": True,
        "configmgr": True,
        "community": True,
        "weather": False,
        "markets": False,
        "news": False,
        "content": False,                   # blog/RSS + YouTube
        "calendar": False,
    },
    "products": [],                         # catalog.PRODUCTS id listesi
    "configmgr_version": None,              # "2509" gibi; None = belirtilmedi
    "configmgr_tracks": ["current", "early_ring", "hotfix", "tp"],
    "intune_platforms": ["windows"],
    "roles": [],                            # catalog.ROLES anahtarları
    "bulletin": {
        "time": "08:00",
        "weekend": False,
        "length": "orta",
        "catch_up_until": "12:00",          # worker kapalıysa bu saate kadar telafi edilir
    },
    "channels": {"telegram": True, "email": False},
    "telegram_chat_id": "",
    "email_to": "",
    "quiet_hours": {"enabled": True, "start": "22:30", "end": "07:30"},
    "category_limits": {
        "windows": 6, "intune": 4, "configmgr": 3, "community": 3,
        "news_turkiye": 3, "news_dunya": 3, "news_genel": 2, "news_teknoloji": 3,
        "content": 3,
    },
    "critical": {
        "enabled": False,
        "interval_min": 60,
        "min_risk": "high",
        "min_evidence": "ms_official",
        "allow_field": True,                # teyitsiz ama yüksek etkili sinyaller (işaretli)
        "field_min_sources": 2,             # bağımsız kaynak sayısı
        "quiet_exception": "none",          # none|ms_critical|all_critical
        "morning_reference": True,          # sabah bülteninde kısa referans ver
    },
    "resurface": {
        "read": "notify",                   # notify|bulletin_only|silent
        "muted": "silent",                  # silent|critical_only|notify
    },
    "keywords": [],
    "exclude_keywords": [],
    "topics": [],
    "news_categories": ["turkiye", "dunya", "teknoloji"],
    "markets": {
        "items": ["USDTRY", "EURTRY", "GRAM24", "BILEZIK22"],
        "provider": "truncgil",             # truncgil|json|none (piyasa); TCMB referans ayrı
        "show_tcmb": True,
    },
    "calendar_ics_url": "",
    "youtube_channels": [],                 # [{"id": "UC...", "name": "..."}]
    "baseline_max_items": 8,
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def get_settings(conn: sqlite3.Connection) -> dict[str, Any]:
    stored: dict[str, Any] = {}
    for row in conn.execute("SELECT key, value_json FROM settings"):
        stored[row["key"]] = jload(row["value_json"])
    merged = _deep_merge(DEFAULTS, stored)
    if not merged.get("timezone"):
        merged["timezone"] = load_config().default_timezone
    return merged


def save_settings(conn: sqlite3.Connection, updates: dict[str, Any]) -> dict[str, Any]:
    ts = now_iso()
    for key, value in updates.items():
        if key not in DEFAULTS:
            raise KeyError(f"Bilinmeyen ayar: {key}")
        conn.execute(
            "INSERT INTO settings(key, value_json, updated_at) VALUES (?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, updated_at = excluded.updated_at",
            (key, jdump(value), ts),
        )
    return get_settings(conn)


def risk_at_least(level: str | None, minimum: str) -> bool:
    if level not in RISK_ORDER:
        return False
    return RISK_ORDER.index(level) >= RISK_ORDER.index(minimum if minimum in RISK_ORDER else "high")


def evidence_at_least(level: str | None, minimum: str) -> bool:
    if level not in EVIDENCE_ORDER:
        return False
    return EVIDENCE_ORDER.index(level) >= EVIDENCE_ORDER.index(
        minimum if minimum in EVIDENCE_ORDER else "ms_official"
    )
