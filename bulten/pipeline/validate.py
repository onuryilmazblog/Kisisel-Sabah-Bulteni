"""Kaynak doğrulama (kuru çalıştırma): adaptörü gerçek ağ üzerinden çalıştırır, sonuçları kaydetmez."""
from __future__ import annotations

import json
import sqlite3
import time
import xml.etree.ElementTree as ET
from typing import Any, Callable

from ..config import load_config
from ..daily.markets import parse_mapped_json, parse_tcmb, parse_truncgil
from ..daily.weather import fetch_weather, geocode
from ..net.fetcher import Fetcher, FetchError
from ..settings_store import get_settings
from ..sources.base import AdapterContext, SourceRow
from ..sources.registry import ADAPTERS


def validate_source(conn: sqlite3.Connection, src: SourceRow, fetcher: Fetcher | None = None) -> dict:
    own = fetcher is None
    fetcher = fetcher or Fetcher(conn, respect_robots=True)
    started = time.time()
    out = {"slug": src.slug, "name": src.name, "url": src.fetch_url or src.url, "ok": False, "items": 0,
           "warnings": [], "error": None, "sample": [], "not_configured": False}
    try:
        adapter = ADAPTERS[src.adapter]
        # Kuru çalıştırma: DB'ye yazmayan bir bağlam (ms_kb/websearch okuma yapar, yazmaz).
        ctx = AdapterContext(conn=conn, fetcher=fetcher, settings=get_settings(conn))
        if src.adapter == "ms_kb":
            ctx.kb_targets = _recent_kb_targets(conn, fetcher, ctx.settings)
        res = adapter(src, ctx)
        out["ok"] = bool(res.structure_ok)
        out["items"] = len(res.observations)
        out["warnings"] = res.warnings
        out["http_status"] = res.http_status
        out["fetched_url"] = res.fetched_url
        out["sample"] = [o.title for o in res.observations[:3]]
    except FetchError as exc:
        out["error"] = str(exc)
        # Gerekli .env yapılandırması (ör. Reddit API kimlik bilgileri) yok: "başarılı" sayılmaz.
        out["not_configured"] = exc.kind == "config"
    except Exception as exc:  # noqa: BLE001
        out["error"] = f"{exc.__class__.__name__}: {exc}"
    finally:
        if own:
            fetcher.close()
    out["duration_ms"] = int((time.time() - started) * 1000)
    return out


def _recent_kb_targets(conn: sqlite3.Connection, fetcher: Fetcher, settings: dict,
                       per_page: int = 2) -> list[tuple[str, str, list[str]]]:
    """KB makalesi doğrulaması için hedefler: seçili ürünlerin (yoksa ilk üç ürünün) güncelleme
    geçmişi sayfalarından en yeni KB'ler. Veri tabanına yazılmaz."""
    rows = [SourceRow.from_row(r) for r in conn.execute(
        "SELECT * FROM sources WHERE adapter = 'ms_update_history' ORDER BY enabled DESC, id").fetchall()]
    selected = set(settings.get("products") or [])
    chosen = [r for r in rows if set(r.product_ids) & selected] or rows[:3]
    ctx = AdapterContext(conn=conn, fetcher=fetcher, settings=settings)
    out: dict[str, tuple[str, str, list[str]]] = {}
    for src in chosen:
        try:
            res = ADAPTERS[src.adapter](src, ctx)
        except FetchError:
            continue
        for ob in res.observations[:per_page]:
            kb = ob.fields.get("kb")
            if kb and kb not in out:
                out[kb] = (kb, ob.url, ob.fields.get("products") or [])
    return list(out.values())


def validate_sources(conn: sqlite3.Connection, slugs: list[str] | None = None, include_disabled: bool = False) -> list[dict]:
    """Etkin kaynakları doğrular. Slug ile açıkça istenen kaynaklar kapalı olsalar da denenir."""
    q = "SELECT * FROM sources" + ("" if include_disabled or slugs else " WHERE enabled = 1")
    rows = [SourceRow.from_row(r) for r in conn.execute(q).fetchall()]
    if slugs:
        rows = [r for r in rows if r.slug in slugs]
    with Fetcher(conn) as fetcher:
        return [validate_source(conn, r, fetcher) for r in rows]


def _daily_check(slug: str, name: str, url: str, fn: Callable[[], tuple[int, list[str], list[str]]]) -> dict:
    started = time.time()
    out: dict[str, Any] = {"slug": slug, "name": name, "url": url, "ok": False, "items": 0, "warnings": [],
                           "error": None, "sample": []}
    try:
        out["items"], out["sample"], out["warnings"] = fn()
        out["ok"] = out["items"] > 0
        if not out["ok"] and not out["warnings"]:
            out["warnings"] = ["Yanıt geldi ama beklenen veri bulunamadı."]
    except (FetchError, ValueError, KeyError, ET.ParseError) as exc:
        out["error"] = f"{exc.__class__.__name__}: {exc}" if not isinstance(exc, FetchError) else str(exc)
    out["duration_ms"] = int((time.time() - started) * 1000)
    return out


def validate_daily(conn: sqlite3.Connection, include_disabled: bool = False) -> list[dict]:
    """Hava ve piyasa sağlayıcılarını canlı dener (kayıt yazmaz).

    Konum seçilmemişse hava tahmini, arama API'sinden dönen ilk "Ankara" sonucu ile yalnızca bağlantı
    testi olarak denenir; bu, kullanıcının konumu olarak kaydedilmez veya gösterilmez.
    """
    cfg = load_config()
    settings = get_settings(conn)
    mods = settings.get("modules") or {}
    results: list[dict] = []
    with Fetcher(conn) as f:
        if include_disabled or mods.get("weather"):
            loc = settings.get("location") or {}
            tzname = settings.get("timezone") or cfg.default_timezone

            def weather_check():
                target, note = loc, "kayıtlı konum"
                if not loc or loc.get("lat") is None:
                    found = geocode(f, "Ankara", count=1)
                    if not found:
                        return 0, [], ["Konum arama API'si sonuç döndürmedi."]
                    target, note = found[0], "bağlantı testi, kullanıcı konumu değil"
                w = fetch_weather(f, target, tzname)
                cur, today = w["current"], w["today"]
                ok = cur.get("temperature") is not None and today.get("max") is not None
                sample = [f"{target.get('name')} ({note}): {cur.get('temperature')} {cur['units']['temperature']}, "
                          f"{cur.get('description')}; bugün {today.get('min')}–{today.get('max')}; veri zamanı "
                          f"{w.get('data_time')}"]
                return (1 if ok else 0), sample, []

            results.append(_daily_check("gunluk-hava", "Hava durumu (Open-Meteo)", cfg.open_meteo_base, weather_check))
        if include_disabled or mods.get("markets"):
            def tcmb_check():
                res = f.get(cfg.tcmb_url, trusted=True, api=True, use_cache=False, accept="application/xml")
                block = parse_tcmb(res.text)
                return len(block["items"]), _market_sample(block), []

            def market_check():
                provider = (settings.get("markets") or {}).get("provider", "truncgil")
                if provider == "json":
                    if not (cfg.market_json_url and cfg.market_json_mapping):
                        return 0, [], ["MARKET_JSON_URL / MARKET_JSON_MAPPING tanımlı değil."]
                    res = f.get(cfg.market_json_url, trusted=True, api=True, use_cache=False, accept="application/json")
                    block = parse_mapped_json(res.text, json.loads(cfg.market_json_mapping), "Kullanıcı tanımlı")
                else:
                    res = f.get(cfg.truncgil_url, trusted=True, api=True, use_cache=False, accept="application/json")
                    block = parse_truncgil(res.text, settings.get("timezone") or cfg.default_timezone)
                missing = [k for k in ("GRAM24", "BILEZIK22") if k not in block["items"]]
                warn = [f"Kaynakta doğrudan veri yok: {', '.join(missing)}"] if missing else []
                return len(block["items"]), _market_sample(block), warn

            results.append(_daily_check("gunluk-piyasa-tcmb", "TCMB gösterge kurları (referans)", cfg.tcmb_url,
                                        tcmb_check))
            results.append(_daily_check("gunluk-piyasa", "Piyasa verisi (döviz, gram altın, bilezik)",
                                        cfg.market_json_url or cfg.truncgil_url, market_check))
    return results


def _market_sample(block: dict) -> list[str]:
    out = []
    for item in block["items"].values():
        prices = ", ".join(f"{k} {v}" for k, v in item["prices"].items() if v is not None)
        extra = f" [işçilik: {item['workmanship']}]" if item.get("workmanship") else ""
        out.append(f"{item['label']}: {prices}{extra}")
    return [f"veri zamanı {block.get('data_time')}"] + out[:4]
