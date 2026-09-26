"""Zaman yardımcıları. Saklama her zaman UTC ISO-8601; gösterim kullanıcı saat diliminde."""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

_frozen: datetime | None = None

TR_MONTHS = [
    "Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran",
    "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık",
]
TR_DAYS = ["Pazartesi", "Salı", "Çarşamba", "Perşembe", "Cuma", "Cumartesi", "Pazar"]

EN_MONTHS = {
    m: i + 1
    for i, m in enumerate(
        ["january", "february", "march", "april", "may", "june", "july",
         "august", "september", "october", "november", "december"]
    )
}
EN_MONTHS.update({k[:3]: v for k, v in list(EN_MONTHS.items())})
EN_MONTHS["sept"] = 9


def set_clock(dt: datetime | None) -> None:
    """Testler için saati sabitle (None: gerçek saat)."""
    global _frozen
    _frozen = dt.astimezone(timezone.utc) if dt is not None else None


def advance_clock(**kwargs) -> datetime:
    global _frozen
    base = _frozen or datetime.now(timezone.utc)
    _frozen = base + timedelta(**kwargs)
    return _frozen


def now_utc() -> datetime:
    return _frozen if _frozen is not None else datetime.now(timezone.utc)


def now_iso() -> str:
    return to_iso(now_utc())


def to_iso(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def tz(name: str | None) -> ZoneInfo:
    try:
        return ZoneInfo(name or "Europe/Istanbul")
    except Exception:  # noqa: BLE001 - geçersiz saat dilimi adı
        return ZoneInfo("Europe/Istanbul")


def local_now(tzname: str | None) -> datetime:
    return now_utc().astimezone(tz(tzname))


def local_date_str(tzname: str | None, dt: datetime | None = None) -> str:
    dt = dt or now_utc()
    return dt.astimezone(tz(tzname)).date().isoformat()


_PT = ZoneInfo("America/Los_Angeles")


def parse_loose_date(text: str | None, default_tz: ZoneInfo | None = None) -> datetime | None:
    """Kaynaklardaki tarih biçimlerini ayrıştırır.

    Desteklenenler: ISO (2026-09-08, 2026-09-08T10:00:00Z), "September 8, 2026",
    "Sept 8, 2026", "8 September 2026", "2026-09-14 10:00 PT", "09/01/2026" (ABD).
    Saat yoksa gün başı (UTC) kabul edilir. Ayrıştırılamazsa None.
    """
    if not text:
        return None
    s = " ".join(str(text).replace(" ", " ").split())
    iso = parse_iso(s)
    if iso:
        return iso
    zone = default_tz or timezone.utc
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})(?:[ T](\d{1,2}):(\d{2}))?\s*(PT|PST|PDT|UTC|GMT)?", s)
    if m:
        y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
        hh, mm = int(m.group(4) or 0), int(m.group(5) or 0)
        z = _PT if (m.group(6) or "").startswith("P") else zone
        try:
            return datetime(y, mo, d, hh, mm, tzinfo=z).astimezone(timezone.utc)
        except ValueError:
            return None
    m = re.search(r"([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})", s)
    if m and m.group(1).lower() in EN_MONTHS:
        try:
            return datetime(int(m.group(3)), EN_MONTHS[m.group(1).lower()], int(m.group(2)), tzinfo=zone).astimezone(timezone.utc)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})\s+([A-Za-z]{3,9})\.?,?\s+(\d{4})", s)
    if m and m.group(2).lower() in EN_MONTHS:
        try:
            return datetime(int(m.group(3)), EN_MONTHS[m.group(2).lower()], int(m.group(1)), tzinfo=zone).astimezone(timezone.utc)
        except ValueError:
            return None
    m = re.search(r"(\d{1,2})/(\d{1,2})/(\d{4})", s)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(1)), int(m.group(2)), tzinfo=zone).astimezone(timezone.utc)
        except ValueError:
            return None
    return None


def fmt_tr(value: str | datetime | None, tzname: str | None = None, with_time: bool = True) -> str:
    """'26 Eylül 2026 08:00' biçimi (kullanıcı saat diliminde)."""
    dt = parse_iso(value) if isinstance(value, str) else value
    if dt is None:
        return "—"
    local = dt.astimezone(tz(tzname))
    s = f"{local.day} {TR_MONTHS[local.month - 1]} {local.year}"
    if with_time:
        s += f" {local:%H:%M}"
    return s


def fmt_tr_date(d: date | str) -> str:
    if isinstance(d, str):
        d = date.fromisoformat(d)
    return f"{d.day} {TR_MONTHS[d.month - 1]} {d.year}, {TR_DAYS[d.weekday()]}"


def age_text(value: str | datetime | None) -> str:
    dt = parse_iso(value) if isinstance(value, str) else value
    if dt is None:
        return "bilinmiyor"
    delta = now_utc() - dt
    secs = int(delta.total_seconds())
    if secs < 0:
        return "az önce"
    if secs < 90:
        return "az önce"
    if secs < 3600:
        return f"{secs // 60} dk önce"
    if secs < 86400:
        return f"{secs // 3600} sa önce"
    return f"{secs // 86400} gün önce"


def parse_hhmm(value: str, default: tuple[int, int] = (8, 0)) -> tuple[int, int]:
    m = re.fullmatch(r"\s*(\d{1,2})[:.](\d{2})\s*", value or "")
    if not m:
        return default
    h, mi = int(m.group(1)), int(m.group(2))
    if not (0 <= h < 24 and 0 <= mi < 60):
        return default
    return h, mi


def in_quiet_hours(local: datetime, start: str, end: str) -> bool:
    sh, sm = parse_hhmm(start, (22, 30))
    eh, em = parse_hhmm(end, (7, 30))
    cur = local.hour * 60 + local.minute
    s, e = sh * 60 + sm, eh * 60 + em
    if s == e:
        return False
    if s < e:
        return s <= cur < e
    return cur >= s or cur < e
