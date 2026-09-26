"""Piyasa verileri: USD/TRY, EUR/TRY, 24 ayar gram altın, 22 ayar bilezik gram.

Kurallar:
- TCMB gösterge kuru (REFERANS) ile piyasa kuru ayrı kaynaklardan ve ayrı etiketle gösterilir; karıştırılmaz.
- Her değer için kaynak, veri zamanı, birim ve varsa alış/satış ayrı yazılır.
- 22 ayar bilezik fiyatı 24 ayar fiyatından ORANLANARAK ÜRETİLMEZ. Doğrudan veri yoksa "doğrudan veri yok" denir.
- Bilezikte işçilik dahil/hariç bilgisi yalnızca kaynak belirtiyorsa yazılır; aksi halde "kaynak belirtmiyor".
- Önceki bültene göre değişim yalnızca aynı sağlayıcı + aynı kalem + aynı fiyat türü için hesaplanır.
"""
from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from typing import Any

from ..config import load_config
from ..net.fetcher import Fetcher, FetchError
from ..timeutil import to_iso, tz

ITEM_LABELS = {"USDTRY": "USD/TRY", "EURTRY": "EUR/TRY", "GRAM24": "Gram altın (24 ayar)",
               "BILEZIK22": "22 ayar bilezik (gram)"}
ITEM_UNITS = {"USDTRY": "TRY / 1 USD", "EURTRY": "TRY / 1 EUR", "GRAM24": "TRY / gram", "BILEZIK22": "TRY / gram"}


def parse_tr_number(value: Any) -> float | None:
    """'4.123,45' / '4123,45' / '41.5' / '%0,12' → float."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip().replace("%", "").replace("₺", "").replace("TL", "").strip()
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".") if s.rfind(",") > s.rfind(".") else s.replace(",", "")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


# --- TCMB (referans) -------------------------------------------------------------------

def parse_tcmb(xml_text: str) -> dict:
    root = ET.fromstring(xml_text.encode("utf-8") if isinstance(xml_text, str) else xml_text)
    date_attr = root.attrib.get("Tarih") or root.attrib.get("Date")
    data_time = None
    if date_attr:
        m = re.match(r"(\d{2})\.(\d{2})\.(\d{4})", date_attr) or None
        if m:
            d, mo, y = int(m.group(1)), int(m.group(2)), int(m.group(3))
        else:
            m2 = re.match(r"(\d{2})/(\d{2})/(\d{4})", date_attr)
            mo, d, y = (int(m2.group(1)), int(m2.group(2)), int(m2.group(3))) if m2 else (None, None, None)
        if y:
            # TCMB gösterge kurları iş günlerinde 15:30'da belirlenir.
            data_time = to_iso(datetime(y, mo, d, 15, 30, tzinfo=tz("Europe/Istanbul")))
    items = {}
    for cur in root.findall("Currency"):
        code = cur.attrib.get("CurrencyCode") or cur.attrib.get("Kod")
        key = {"USD": "USDTRY", "EUR": "EURTRY"}.get(code or "")
        if not key:
            continue
        unit = parse_tr_number(cur.findtext("Unit")) or 1

        def val(tag):
            v = parse_tr_number(cur.findtext(tag))
            return v / unit if v is not None else None

        items[key] = {
            "label": ITEM_LABELS[key], "unit": ITEM_UNITS[key],
            "prices": {"Döviz alış": val("ForexBuying"), "Döviz satış": val("ForexSelling"),
                       "Efektif alış": val("BanknoteBuying"), "Efektif satış": val("BanknoteSelling")},
        }
    return {"provider": "tcmb", "provider_label": "TCMB gösterge kuru (referans, piyasa kuru değildir)",
            "data_time": data_time, "bulletin_no": root.attrib.get("Bulten_No"), "items": items,
            "note": "TCMB kurları iş günlerinde 15:30'da belirlenen gösterge niteliğindeki referans kurlardır."}


# --- Truncgil Finans (piyasa) -------------------------------------------------------------

TRUNCGIL_KEYS = {
    "USDTRY": ["USD", "usd", "ABD DOLARI"],
    "EURTRY": ["EUR", "eur", "EURO"],
    "GRAM24": ["gram-altin", "GRA", "gram_altin", "Gram Altın"],
    "BILEZIK22": ["22-ayar-bilezik", "YIA", "22_ayar_bilezik", "22 Ayar Bilezik"],
}


def parse_truncgil(json_text: str, tzname: str) -> dict:
    data = json.loads(json_text)
    update = data.get("Update_Date") or data.get("Update_Date_Time") or (data.get("Meta_Data") or {}).get("Update_Date")
    data_time = None
    if update:
        try:
            data_time = to_iso(datetime.strptime(str(update)[:19], "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz("Europe/Istanbul")))
        except ValueError:
            data_time = None
    items: dict[str, Any] = {}
    for key, names in TRUNCGIL_KEYS.items():
        entry = None
        for n in names:
            if isinstance(data.get(n), dict):
                entry = data[n]
                break
        if entry is None:
            for v in data.values():
                if isinstance(v, dict) and str(v.get("Name") or v.get("İsim") or "").lower() == names[-1].lower():
                    entry = v
                    break
        if entry is None:
            continue
        buy = parse_tr_number(entry.get("Alış") if "Alış" in entry else entry.get("Buying"))
        sell = parse_tr_number(entry.get("Satış") if "Satış" in entry else entry.get("Selling"))
        items[key] = {"label": ITEM_LABELS[key], "unit": ITEM_UNITS[key], "prices": {"Alış": buy, "Satış": sell}}
        if key == "BILEZIK22":
            items[key]["workmanship"] = "Kaynak belirtmiyor"
    return {"provider": "truncgil", "provider_label": "Piyasa (Truncgil Finans, serbest piyasa verisi)",
            "data_time": data_time, "items": items,
            "note": "Serbest piyasa fiyatlarıdır; kuyumcu ve bankalarda farklılık gösterebilir."}


# --- Kullanıcı tanımlı JSON kaynağı ---------------------------------------------------------

def _dig(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if isinstance(obj, list):
            try:
                obj = obj[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(obj, dict):
            obj = obj.get(part)
        else:
            return None
    return obj


def parse_mapped_json(json_text: str, mapping: dict, label: str) -> dict:
    """mapping: {"time": "yol", "items": {"USDTRY": {"buy": "yol", "sell": "yol"}, "BILEZIK22": {..., "workmanship": "dahil"}}}"""
    data = json.loads(json_text)
    items = {}
    for key, spec in (mapping.get("items") or {}).items():
        if key not in ITEM_LABELS:
            continue
        buy = parse_tr_number(_dig(data, spec["buy"])) if spec.get("buy") else None
        sell = parse_tr_number(_dig(data, spec["sell"])) if spec.get("sell") else None
        if buy is None and sell is None:
            continue
        items[key] = {"label": ITEM_LABELS[key], "unit": ITEM_UNITS[key], "prices": {"Alış": buy, "Satış": sell}}
        if key == "BILEZIK22":
            items[key]["workmanship"] = {"dahil": "İşçilik dahil (kaynağa göre)", "hariç": "İşçilik hariç (kaynağa göre)"}.get(
                spec.get("workmanship", ""), "Kaynak belirtmiyor")
    t = _dig(data, mapping["time"]) if mapping.get("time") else None
    return {"provider": "json", "provider_label": label, "data_time": str(t) if t else None, "items": items, "note": ""}


def refresh_markets(fetcher: Fetcher, settings: dict) -> tuple[str, dict, str | None, str | None]:
    cfg = load_config()
    mset = settings.get("markets") or {}
    wanted = mset.get("items") or list(ITEM_LABELS)
    blocks: list[dict] = []
    errors: list[str] = []
    if mset.get("show_tcmb", True) and any(k in wanted for k in ("USDTRY", "EURTRY")):
        try:
            res = fetcher.get(cfg.tcmb_url, trusted=True, api=True, use_cache=False, accept="application/xml")
            blocks.append(parse_tcmb(res.text))
        except (FetchError, ET.ParseError) as exc:
            errors.append(f"TCMB: {exc}")
    provider = mset.get("provider", "truncgil")
    try:
        if provider == "truncgil":
            res = fetcher.get(cfg.truncgil_url, trusted=True, api=True, use_cache=False, accept="application/json")
            blocks.append(parse_truncgil(res.text, settings.get("timezone")))
        elif provider == "json" and cfg.market_json_url and cfg.market_json_mapping:
            res = fetcher.get(cfg.market_json_url, trusted=True, api=True, use_cache=False, accept="application/json")
            blocks.append(parse_mapped_json(res.text, json.loads(cfg.market_json_mapping), "Kullanıcı tanımlı kaynak"))
        elif provider == "json":
            errors.append("JSON piyasa kaynağı seçili ama MARKET_JSON_URL / MARKET_JSON_MAPPING tanımlı değil.")
    except (FetchError, ValueError, KeyError) as exc:
        errors.append(f"Piyasa ({provider}): {exc}")
    for b in blocks:
        b["items"] = {k: v for k, v in b["items"].items() if k in wanted}
    missing = []
    market_block = next((b for b in blocks if b["provider"] != "tcmb"), None)
    for k in wanted:
        if k in ("GRAM24", "BILEZIK22") and (market_block is None or k not in market_block["items"]):
            missing.append(ITEM_LABELS[k])
    payload = {"blocks": blocks, "missing": missing, "errors": errors}
    status = "ok" if blocks and not errors else ("partial" if blocks else "error")
    data_time = max((b.get("data_time") or "" for b in blocks), default="") or None
    return status, payload, data_time, "; ".join(errors) or None


def compare(prev: dict | None, cur: dict) -> dict:
    """Önceki bülten verisine göre değişim: {provider: {item: {fiyat_türü: fark}}} (karşılaştırılabilir olanlar)."""
    out: dict = {}
    if not prev:
        return out
    prev_blocks = {b["provider"]: b for b in prev.get("blocks", [])}
    for b in cur.get("blocks", []):
        pb = prev_blocks.get(b["provider"])
        if not pb or pb.get("data_time") == b.get("data_time"):
            continue
        for key, item in b["items"].items():
            pitem = pb["items"].get(key)
            if not pitem:
                continue
            for ptype, val in item["prices"].items():
                pval = pitem["prices"].get(ptype)
                if val is not None and pval:
                    out.setdefault(b["provider"], {}).setdefault(key, {})[ptype] = {
                        "diff": round(val - pval, 4), "pct": round((val - pval) / pval * 100, 2),
                        "prev_time": pb.get("data_time")}
    return out
