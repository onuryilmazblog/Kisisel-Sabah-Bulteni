"""Günlük verilerin (hava, piyasa, takvim) yenilenmesi ve görünüm modeli.

Bu veriler haber tekrarı filtresinden ve olay hafızasından ayrı işlenir: her bültende o günün
güncel değeri gösterilir. Eski veriye "güncel" etiketi verilmez; eksik veri açıkça belirtilir.
"""
from __future__ import annotations

import sqlite3
from datetime import timedelta

from ..db import jdump, jload
from ..net.fetcher import Fetcher
from ..settings_store import get_settings
from ..timeutil import fmt_tr, now_iso, now_utc, parse_iso
from .calendar_ics import refresh_calendar
from .markets import compare, refresh_markets
from .weather import refresh_weather

REFRESHERS = {"weather": ("weather", refresh_weather), "market": ("markets", refresh_markets),
              "calendar": ("calendar", refresh_calendar)}
STALE_HOURS = {"weather": 3, "market": 8, "calendar": 12}


def refresh_daily(conn: sqlite3.Connection, fetcher: Fetcher | None = None, modules: list[str] | None = None) -> dict:
    settings = get_settings(conn)
    own = fetcher is None
    fetcher = fetcher or Fetcher(conn)
    out = {}
    try:
        for module, (setting_key, fn) in REFRESHERS.items():
            if modules and module not in modules:
                continue
            if not (settings.get("modules") or {}).get(setting_key):
                continue
            status, payload, data_time, error = fn(fetcher, settings)
            conn.execute("INSERT INTO daily_data(module, provider, fetched_at, data_time, status, payload_json, error) "
                         "VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (module, payload.get("provider") or module, now_iso(), data_time, status, jdump(payload), error))
            out[module] = status
    finally:
        if own:
            fetcher.close()
    return out


def daily_view(conn: sqlite3.Connection, row_id: int | None, module: str, tzname: str) -> dict | None:
    if row_id is None:
        return None
    row = conn.execute("SELECT * FROM daily_data WHERE id = ?", (row_id,)).fetchone()
    if row is None:
        return None
    payload = jload(row["payload_json"], {})
    fetched = parse_iso(row["fetched_at"])
    dtime = parse_iso(row["data_time"]) if row["data_time"] else None
    ref = dtime or fetched
    stale = ref is None or (now_utc() - ref) > timedelta(hours=STALE_HOURS.get(module, 6))
    view = {"id": row["id"], "module": module, "status": row["status"], "error": row["error"], "payload": payload,
            "fetched_at": row["fetched_at"], "data_time": row["data_time"], "stale": stale,
            "fetched_label": fmt_tr(row["fetched_at"], tzname), "data_time_label": fmt_tr(row["data_time"], tzname)
            if row["data_time"] else "kaynak belirtmiyor"}
    if module == "market":
        prev = conn.execute("SELECT payload_json FROM daily_data WHERE module = 'market' AND id < ? AND status != 'error' "
                            "AND id IN (SELECT json_extract(content_json, '$.daily.market') FROM bulletins) "
                            "ORDER BY id DESC LIMIT 1", (row_id,)).fetchone()
        view["changes"] = compare(jload(prev["payload_json"], {}) if prev else None, payload)
        for b in payload.get("blocks", []):
            bt = parse_iso(b.get("data_time"))
            b["data_time_label"] = fmt_tr(b.get("data_time"), tzname) if b.get("data_time") else "kaynak belirtmiyor"
            b["stale"] = bt is None or (now_utc() - bt) > timedelta(hours=30 if b["provider"] == "tcmb" else 8)
    return view
