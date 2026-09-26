"""Hava durumu: Open-Meteo (anahtarsız). Resmî uyarılar için MGM bağlantısı / isteğe bağlı CAP-Atom beslemesi.

Konum tahmin edilmez: kullanıcı şehir/ilçeyi arar ve listeden seçer (koordinatlar kaydedilir).
MGM MeteoUyarı için belgelenmiş bir API bulunamadığından resmî uyarılar otomatik okunmaz;
bülten bunu açıkça belirtir. Kullanıcı bir CAP/Atom/RSS uyarı beslemesi adresi verirse okunur.
"""
from __future__ import annotations

import json
from urllib.parse import urlencode

import feedparser

from datetime import datetime

from ..config import load_config
from ..net.fetcher import Fetcher, FetchError
from ..timeutil import now_iso, tz

WMO_TR = {
    0: "Açık", 1: "Çoğunlukla açık", 2: "Parçalı bulutlu", 3: "Kapalı", 45: "Sisli", 48: "Kırağılı sis",
    51: "Hafif çisenti", 53: "Çisenti", 55: "Yoğun çisenti", 56: "Donan çisenti", 57: "Yoğun donan çisenti",
    61: "Hafif yağmur", 63: "Yağmur", 65: "Kuvvetli yağmur", 66: "Donan yağmur", 67: "Kuvvetli donan yağmur",
    71: "Hafif kar", 73: "Kar", 75: "Yoğun kar", 77: "Kar taneleri", 80: "Hafif sağanak", 81: "Sağanak",
    82: "Şiddetli sağanak", 85: "Kar sağanağı", 86: "Yoğun kar sağanağı", 95: "Gök gürültülü fırtına",
    96: "Dolu ile fırtına", 99: "Şiddetli dolu ile fırtına",
}

MGM_URL = "https://www.mgm.gov.tr/meteouyari/"


def geocode(fetcher: Fetcher, query: str, count: int = 8) -> list[dict]:
    cfg = load_config()
    url = f"{cfg.open_meteo_geocoding_base}/v1/search?" + urlencode(
        {"name": query, "count": count, "language": "tr", "format": "json"})
    # Etkileşimli arama: kullanıcı beklemesin diye tek deneme.
    res = fetcher.get(url, trusted=True, use_cache=False, accept="application/json", retries=0)
    data = json.loads(res.text)
    out = []
    for r in data.get("results") or []:
        out.append({"name": r.get("name"), "admin1": r.get("admin1"), "admin2": r.get("admin2"),
                    "country": r.get("country"), "country_code": r.get("country_code"),
                    "lat": r.get("latitude"), "lon": r.get("longitude"), "timezone": r.get("timezone")})
    return out


def fetch_weather(fetcher: Fetcher, location: dict, tzname: str) -> dict:
    cfg = load_config()
    params = {
        "latitude": location["lat"], "longitude": location["lon"],
        "current": "temperature_2m,apparent_temperature,precipitation,weather_code,wind_speed_10m",
        "daily": "temperature_2m_max,temperature_2m_min,apparent_temperature_max,apparent_temperature_min,"
                 "precipitation_sum,precipitation_probability_max,weather_code",
        "timezone": tzname, "forecast_days": 1,
    }
    url = f"{cfg.open_meteo_base}/v1/forecast?" + urlencode(params)
    res = fetcher.get(url, trusted=True, use_cache=False, accept="application/json")
    return parse_open_meteo(json.loads(res.text), location, tzname)


def parse_open_meteo(data: dict, location: dict, tzname: str) -> dict:
    cur = data.get("current") or {}
    cu = data.get("current_units") or {}
    daily = data.get("daily") or {}
    du = data.get("daily_units") or {}

    def d0(key):
        vals = daily.get(key) or []
        return vals[0] if vals else None

    data_time = None
    if cur.get("time"):
        try:
            data_time = datetime.fromisoformat(cur["time"]).replace(tzinfo=tz(tzname)).isoformat()
        except ValueError:
            data_time = None
    return {
        "provider": "Open-Meteo", "location": location.get("name"), "admin1": location.get("admin1"),
        "district": location.get("district"), "data_time": data_time,
        "current": {
            "temperature": cur.get("temperature_2m"), "apparent": cur.get("apparent_temperature"),
            "precipitation": cur.get("precipitation"), "code": cur.get("weather_code"),
            "description": WMO_TR.get(cur.get("weather_code"), "Bilinmiyor"), "wind": cur.get("wind_speed_10m"),
            "units": {"temperature": cu.get("temperature_2m", "°C"), "precipitation": cu.get("precipitation", "mm"),
                      "wind": cu.get("wind_speed_10m", "km/h")},
        },
        "today": {
            "max": d0("temperature_2m_max"), "min": d0("temperature_2m_min"),
            "apparent_max": d0("apparent_temperature_max"), "apparent_min": d0("apparent_temperature_min"),
            "precipitation_sum": d0("precipitation_sum"), "precipitation_probability": d0("precipitation_probability_max"),
            "code": d0("weather_code"), "description": WMO_TR.get(d0("weather_code"), "Bilinmiyor"),
            "units": {"temperature": du.get("temperature_2m_max", "°C"), "precipitation": du.get("precipitation_sum", "mm")},
        },
    }


def fetch_warnings(fetcher: Fetcher, feed_url: str, location: dict) -> dict:
    """Kullanıcının verdiği CAP/Atom/RSS uyarı beslemesi (kullanıcı adresi → SSRF kontrolünden geçer)."""
    res = fetcher.get(feed_url, accept="application/atom+xml, application/rss+xml, application/xml")
    parsed = feedparser.parse(res.text)
    needle = (location.get("admin1") or location.get("name") or "").lower()
    items = []
    for e in parsed.entries[:40]:
        text = f"{e.get('title', '')} {e.get('summary', '')}"
        if needle and needle not in text.lower():
            continue
        items.append({"title": e.get("title"), "link": e.get("link"), "summary": (e.get("summary") or "")[:300],
                      "updated": e.get("updated") or e.get("published")})
    return {"source": feed_url, "items": items[:5], "checked_at": now_iso()}


def refresh_weather(fetcher: Fetcher, settings: dict) -> tuple[str, dict, str | None, str | None]:
    """(durum, payload, veri zamanı, hata)"""
    loc = settings.get("location")
    tzname = settings.get("timezone")
    if not loc or loc.get("lat") is None:
        return "error", {"missing": "location"}, None, "Konum seçilmedi (Ayarlar → Konum)."
    try:
        payload = fetch_weather(fetcher, loc, tzname)
    except (FetchError, ValueError, KeyError) as exc:
        return "error", {"location": loc.get("name")}, None, f"Hava durumu alınamadı: {exc}"
    warn_url = settings.get("mgm_warning_url") or ""
    payload["warnings"] = {"source": None, "items": [], "note": (
        "Resmî (MGM) uyarılar otomatik okunmuyor: belgelenmiş bir API bulunamadı. Güncel uyarılar için MGM MeteoUyarı sayfasına bakın.")}
    payload["warnings_link"] = MGM_URL
    status = "ok"
    if warn_url.lower().endswith((".xml", ".atom", ".rss")) or "cap" in warn_url.lower():
        try:
            payload["warnings"] = fetch_warnings(fetcher, warn_url, loc)
            payload["warnings"]["note"] = "Uyarılar kullanıcı tarafından yapılandırılan beslemeden okundu."
        except FetchError as exc:
            payload["warnings"]["note"] = f"Uyarı beslemesi okunamadı: {exc}"
            status = "partial"
    elif warn_url:
        payload["warnings_link"] = warn_url
    return status, payload, payload.get("data_time"), None
