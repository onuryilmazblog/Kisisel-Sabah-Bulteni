"""Takvim: kullanıcının verdiği salt okunur ICS adresi (ör. Google Takvim "gizli iCal adresi",
Outlook "takvim yayımlama" ICS bağlantısı). OAuth veya yazma izni kullanılmaz.
Adres kullanıcıdan geldiği için SSRF kontrolünden geçer.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta

import icalendar
import recurring_ical_events

from ..net.fetcher import Fetcher, FetchError
from ..timeutil import local_now, to_iso, tz


def parse_ics_today(ics_text: str, tzname: str, day: datetime | None = None) -> list[dict]:
    zone = tz(tzname)
    day = (day or local_now(tzname)).astimezone(zone)
    start = datetime.combine(day.date(), time.min, tzinfo=zone)
    end = start + timedelta(days=1)
    cal = icalendar.Calendar.from_ical(ics_text)
    events = []
    for ev in recurring_ical_events.of(cal).between(start, end):
        dtstart = ev.get("DTSTART").dt if ev.get("DTSTART") else None
        dtend = ev.get("DTEND").dt if ev.get("DTEND") else None
        all_day = not isinstance(dtstart, datetime)
        if isinstance(dtstart, datetime):
            dtstart = dtstart if dtstart.tzinfo else dtstart.replace(tzinfo=zone)
        if isinstance(dtend, datetime):
            dtend = dtend if dtend.tzinfo else dtend.replace(tzinfo=zone)
        events.append({
            "summary": str(ev.get("SUMMARY") or "(başlıksız)"),
            "location": str(ev.get("LOCATION") or ""),
            "all_day": all_day,
            "start": to_iso(dtstart) if isinstance(dtstart, datetime) else str(dtstart),
            "end": to_iso(dtend) if isinstance(dtend, datetime) else (str(dtend) if dtend else None),
            "start_local": dtstart.astimezone(zone).strftime("%H:%M") if isinstance(dtstart, datetime) else "Tüm gün",
        })
    events.sort(key=lambda e: (not e["all_day"], e["start"]))
    return events


def refresh_calendar(fetcher: Fetcher, settings: dict) -> tuple[str, dict, str | None, str | None]:
    url = (settings.get("calendar_ics_url") or "").strip()
    if not url:
        return "error", {"missing": "ics"}, None, "Takvim bağlantısı yapılandırılmadı."
    try:
        res = fetcher.get(url, use_cache=False, accept="text/calendar, text/plain")
        events = parse_ics_today(res.text, settings.get("timezone"))
    except FetchError as exc:
        return "error", {}, None, f"Takvim okunamadı: {exc}"
    except (ValueError, KeyError) as exc:
        return "error", {}, None, f"ICS ayrıştırılamadı: {exc}"
    return "ok", {"events": events[:15], "count": len(events)}, res.fetched_at, None
