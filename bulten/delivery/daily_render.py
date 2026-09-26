"""Hava/piyasa/takvim bloklarının Telegram ve e-posta biçimleri."""
from __future__ import annotations

import html
import sqlite3

from ..daily.service import daily_view


def esc(t) -> str:
    return html.escape(str(t if t is not None else ""), quote=False)


def fmt_num(v, digits: int = 2) -> str:
    if v is None:
        return "—"
    s = f"{v:,.{digits}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


def weather_lines(view: dict) -> list[str]:
    if view is None:
        return []
    p = view["payload"]
    if view["status"] == "error":
        return [f"🌤 Hava durumu: {view['error'] or 'alınamadı'}"]
    c, t = p.get("current") or {}, p.get("today") or {}
    u = c.get("units") or {}
    place = ", ".join(x for x in (p.get("location"), p.get("admin1")) if x)
    lines = [f"🌤 {place}: {c.get('description')}, {fmt_num(c.get('temperature'), 1)}{u.get('temperature', '°C')} "
             f"(hissedilen {fmt_num(c.get('apparent'), 1)}{u.get('temperature', '°C')}); bugün "
             f"{fmt_num(t.get('min'), 0)}–{fmt_num(t.get('max'), 0)}°, yağış {fmt_num(t.get('precipitation_sum'), 1)} "
             f"{(t.get('units') or {}).get('precipitation', 'mm')}"
             + (f" (olasılık %{t.get('precipitation_probability')})" if t.get("precipitation_probability") is not None else "")]
    lines.append(f"Veri zamanı: {view['data_time_label']} · {p.get('provider') or 'Open-Meteo'}"
                 + (" · ⚠️ güncel değil" if view["stale"] else ""))
    w = p.get("warnings") or {}
    if w.get("items"):
        for it in w["items"][:3]:
            lines.append(f"⚠️ Uyarı: {it.get('title')}")
    else:
        lines.append(w.get("note") or "Resmî uyarı bilgisi yok.")
    return lines


def market_lines(view: dict) -> list[str]:
    if view is None:
        return []
    p = view["payload"]
    lines = []
    if not p.get("blocks"):
        return [f"💱 Piyasalar: {view['error'] or 'veri alınamadı'}"]
    changes = view.get("changes") or {}
    for b in p["blocks"]:
        lines.append(f"💱 {b['provider_label']} — veri zamanı: {b.get('data_time_label')}"
                     + (" · ⚠️ güncel değil" if b.get("stale") else ""))
        for key, item in b["items"].items():
            prices = " / ".join(f"{k} {fmt_num(v, 4 if key in ('USDTRY', 'EURTRY') else 2)}"
                                for k, v in item["prices"].items() if v is not None)
            ch = (changes.get(b["provider"]) or {}).get(key) or {}
            ch_txt = ""
            if ch:
                ptype, cval = next(iter(ch.items()))
                sign = "+" if cval["diff"] >= 0 else ""
                ch_txt = f" ({ptype}: {sign}{fmt_num(cval['pct'], 2)}% önceki bültene göre)"
            extra = f" · {item['workmanship']}" if item.get("workmanship") else ""
            lines.append(f"  {item['label']}: {prices} [{item['unit']}]{extra}{ch_txt}")
    for m in p.get("missing") or []:
        lines.append(f"  {m}: doğrudan veri yok (başka bir değerden hesaplanmadı)")
    for e in p.get("errors") or []:
        lines.append(f"  ⚠️ {e}")
    return lines


def calendar_lines(view: dict) -> list[str]:
    if view is None:
        return []
    if view["status"] == "error":
        return [f"📅 Takvim: {view['error']}"]
    evs = view["payload"].get("events") or []
    if not evs:
        return ["📅 Bugün takviminizde etkinlik yok."]
    return ["📅 Bugün:"] + [f"  {e['start_local']} {e['summary']}" + (f" ({e['location']})" if e.get("location") else "")
                           for e in evs[:8]]


def telegram_blocks(conn: sqlite3.Connection, daily: dict, tzname: str) -> list[str]:
    blocks = []
    for module, fn in (("weather", weather_lines), ("market", market_lines), ("calendar", calendar_lines)):
        if module not in daily:
            continue
        view = daily_view(conn, daily.get(module), module, tzname)
        if view is None:
            label = {"weather": "Hava durumu", "market": "Piyasalar", "calendar": "Takvim"}[module]
            blocks.append(f"{label}: veri henüz alınmadı.")
            continue
        blocks.append(esc("\n".join(fn(view))))
    return blocks


def email_html(conn: sqlite3.Connection, daily: dict, tzname: str) -> str:
    parts = []
    for module, fn, title in (("weather", weather_lines, "Hava durumu"), ("market", market_lines, "Piyasalar"),
                              ("calendar", calendar_lines, "Takvim")):
        if module not in daily:
            continue
        view = daily_view(conn, daily.get(module), module, tzname)
        lines = fn(view) if view else ["Veri henüz alınmadı."]
        parts.append(f"<h2>{title}</h2><div class='card'>" + "".join(f"<p>{esc(ln)}</p>" for ln in lines) + "</div>")
    return "".join(parts)

