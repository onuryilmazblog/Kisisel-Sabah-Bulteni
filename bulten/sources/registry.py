"""Adaptör eşlemesi ve yerleşik (varsayılan) kaynak listesi.

Kaynak adresleri veri tabanında saklanır ve arayüzden değiştirilebilir. Yerleşik
kaynaklar her başlangıçta slug'a göre eklenir; kullanıcının açma/kapama tercihi ve
adres değişiklikleri korunur (yalnızca `builtin_rev` artarsa adres güncellenir).
"""
from __future__ import annotations

import sqlite3
from typing import Any

from ..catalog import PRODUCTS, wrh_url
from ..db import jdump, jload
from ..timeutil import now_iso
from . import configmgr, intune, ms_support, rss, websearch, wrh
from .base import AdapterFn

ADAPTERS: dict[str, AdapterFn] = {
    "wrh_status": wrh.run_wrh,
    "wrh_resolved": wrh.run_wrh,
    "wrh_messages": wrh.run_message_center,
    "ms_update_history": ms_support.run_update_history,
    "ms_kb": ms_support.run_kb_articles,
    "intune": intune.run_intune,
    "cm_versions": configmgr.run_cm_versions,
    "cm_hotfix": configmgr.run_cm_hotfix,
    "cm_release_notes": configmgr.run_cm_release_notes,
    "cm_tp": configmgr.run_cm_tp,
    "rss": rss.run_rss,
    "web_search": websearch.run_web_search,
}

ADAPTER_LABELS = {
    "wrh_status": "Release health – bilinen sorunlar",
    "wrh_resolved": "Release health – çözülen sorunlar",
    "wrh_messages": "Windows message center",
    "ms_update_history": "Güncelleme geçmişi (KB listesi)",
    "ms_kb": "KB makaleleri – Known issues bölümü",
    "intune": "Intune belgeleri",
    "cm_versions": "ConfigMgr desteklenen sürümler",
    "cm_hotfix": "ConfigMgr hotfix/rollup",
    "cm_release_notes": "ConfigMgr sürüm notları",
    "cm_tp": "ConfigMgr Technical Preview",
    "rss": "RSS/Atom beslemesi",
    "web_search": "Web araması",
}

RAW_MEMDOCS = "https://raw.githubusercontent.com/MicrosoftDocs/memdocs/main/"
SEARCH_VALIDATED = "Arama dizininde doğrulandı (2026-09-26); canlı HTTP kontrolü yapılmadı."
UNVALIDATED = "Doğrulanmadı: 'Kaynağı test et' ile kontrol edin."
MEMDOCS_VALIDATED = "Markdown kaynağı GitHub'dan okunarak doğrulandı (2026-09-26); Learn adresi arama dizininde doğrulandı."


def _src(slug: str, name: str, module: str, adapter: str, url: str, trust: str, *, fetch_url: str | None = None,
         fallback_url: str | None = None, category: str | None = None, products: list[str] | None = None,
         enabled: bool = True, critical: bool = False, config: dict[str, Any] | None = None,
         note: str = SEARCH_VALIDATED) -> dict[str, Any]:
    return {
        "slug": slug, "name": name, "module": module, "adapter": adapter, "url": url, "fetch_url": fetch_url,
        "fallback_url": fallback_url, "trust": trust, "category": category, "product_ids": products or [],
        "enabled": enabled, "critical": critical, "config": config or {}, "validation_note": note,
    }


def builtin_sources() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in PRODUCTS:
        if p.wrh_status:
            out.append(_src(f"wrh-status-{p.id}", f"Release health: {p.label}", "windows", "wrh_status",
                            wrh_url(p.wrh_status), "official", products=[p.id], enabled=False, critical=True))
        if p.wrh_resolved:
            out.append(_src(f"wrh-resolved-{p.id}", f"Çözülen sorunlar: {p.label}", "windows", "wrh_resolved",
                            wrh_url(p.wrh_resolved), "official", products=[p.id], enabled=False))
        if p.update_history:
            out.append(_src(f"ms-uh-{p.id}", f"Güncelleme geçmişi: {p.label}", "windows", "ms_update_history",
                            p.update_history, "official", products=[p.id], enabled=False, critical=True,
                            config={"months_back": 4}))
    out += [
        _src("ms-kb-articles", "KB makaleleri (Known issues bölümleri)", "windows", "ms_kb",
             "https://support.microsoft.com/", "official", critical=True, config={"days_back": 60, "max_pages": 15},
             note="Adresler güncelleme geçmişi sayfalarından dinamik alınır."),
        _src("wrh-message-center", "Windows message center", "windows", "wrh_messages",
             "https://learn.microsoft.com/en-us/windows/release-health/windows-message-center", "official"),
        _src("intune-whatsnew", "Intune: What's new", "intune", "intune",
             "https://learn.microsoft.com/en-us/intune/whats-new/", "official",
             fetch_url=RAW_MEMDOCS + "intune/whats-new/index.md",
             fallback_url="https://learn.microsoft.com/en-us/intune/whats-new/", critical=True,
             config={"page": "whats_new", "max_weeks": 6}, note=MEMDOCS_VALIDATED),
        _src("intune-indev", "Intune: In development", "intune", "intune",
             "https://learn.microsoft.com/en-us/intune/whats-new/in-development", "official",
             fetch_url=RAW_MEMDOCS + "intune/whats-new/in-development.md",
             fallback_url="https://learn.microsoft.com/en-us/intune/whats-new/in-development",
             config={"page": "in_development"}, note=MEMDOCS_VALIDATED),
        _src("intune-notices", "Intune: Important notices", "intune", "intune",
             "https://learn.microsoft.com/en-us/intune/whats-new/#notices", "official",
             fetch_url=RAW_MEMDOCS + "intune/whats-new/includes/intune-notices.md",
             fallback_url="https://learn.microsoft.com/en-us/intune/whats-new/", critical=True,
             config={"page": "notices"}, note=MEMDOCS_VALIDATED),
        _src("cm-versions", "ConfigMgr: desteklenen sürümler", "configmgr", "cm_versions",
             "https://learn.microsoft.com/en-us/intune/configmgr/core/servers/manage/updates", "official",
             fetch_url=RAW_MEMDOCS + "intune/configmgr/core/servers/manage/updates.md",
             fallback_url="https://learn.microsoft.com/en-us/intune/configmgr/core/servers/manage/updates",
             critical=True,
             note=MEMDOCS_VALIDATED + " (whats-new-incremental-versions sayfası sürüm listesi için bu sayfaya yönlendirir.)"),
        _src("cm-hotfix", "ConfigMgr: hotfix ve update rollup'lar", "configmgr", "cm_hotfix",
             "https://learn.microsoft.com/en-us/intune/configmgr/hotfix/", "official",
             fetch_url=RAW_MEMDOCS + "intune/configmgr/hotfix/TOC.yml",
             fallback_url="https://learn.microsoft.com/en-us/intune/configmgr/hotfix/", critical=True,
             config={"max_details": 6}, note=MEMDOCS_VALIDATED),
        _src("cm-release-notes", "ConfigMgr: sürüm notları (bilinen sorunlar)", "configmgr", "cm_release_notes",
             "https://learn.microsoft.com/en-us/intune/configmgr/core/servers/deploy/install/release-notes", "official",
             fetch_url=RAW_MEMDOCS + "intune/configmgr/core/servers/deploy/install/release-notes.md",
             fallback_url="https://learn.microsoft.com/en-us/intune/configmgr/core/servers/deploy/install/release-notes",
             note=MEMDOCS_VALIDATED),
        _src("cm-tp", "ConfigMgr: Technical Preview", "configmgr", "cm_tp",
             "https://learn.microsoft.com/en-us/intune/configmgr/core/get-started/technical-preview", "official",
             fetch_url=RAW_MEMDOCS + "intune/configmgr/core/get-started/technical-preview.md",
             fallback_url="https://learn.microsoft.com/en-us/intune/configmgr/core/get-started/technical-preview",
             note=MEMDOCS_VALIDATED + " Son TP sürümü 2411 (Kasım 2024)."),
        # Resmî Microsoft blogları (Tech Community blog panoları resmîdir; tartışma panoları değildir)
        _src("tc-intune-cs", "Intune Customer Success blogu", "intune", "rss",
             "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=IntuneCustomerSuccess",
             "official", enabled=False, config={"max_age_days": 21, "official_blog": True}, note=UNVALIDATED),
        _src("tc-windows-itpro", "Windows IT Pro blogu", "windows", "rss",
             "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=Windows-ITPro-blog",
             "official", enabled=False, config={"max_age_days": 21, "official_blog": True}, note=UNVALIDATED),
        _src("tc-configmgr", "Configuration Manager blogu", "configmgr", "rss",
             "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=ConfigurationManagerBlog",
             "official", enabled=False, config={"max_age_days": 30, "official_blog": True}, note=UNVALIDATED),
        # Saha sinyalleri: topluluklar ve teknoloji yayınları
        _src("reddit-sysadmin", "r/sysadmin", "community", "rss", "https://www.reddit.com/r/sysadmin/new/.rss",
             "community", critical=True, config={"max_age_days": 4}, note=UNVALIDATED),
        _src("reddit-intune", "r/Intune", "community", "rss", "https://www.reddit.com/r/Intune/new/.rss",
             "community", critical=True, config={"max_age_days": 4}, note=UNVALIDATED),
        _src("reddit-sccm", "r/SCCM", "community", "rss", "https://www.reddit.com/r/SCCM/new/.rss",
             "community", config={"max_age_days": 5}, note=UNVALIDATED),
        _src("bleepingcomputer", "BleepingComputer", "community", "rss", "https://www.bleepingcomputer.com/feed/",
             "press", critical=True, config={"max_age_days": 5}, note=UNVALIDATED),
        _src("borncity", "Born's Tech and Windows World", "community", "rss", "https://borncity.com/win/feed/",
             "press", critical=True, config={"max_age_days": 5}, note=UNVALIDATED),
        _src("windowslatest", "Windows Latest", "community", "rss", "https://www.windowslatest.com/feed/",
             "press", config={"max_age_days": 5}, note=UNVALIDATED),
        _src("askwoody", "AskWoody", "community", "rss", "https://www.askwoody.com/feed/", "press",
             config={"max_age_days": 7}, note=UNVALIDATED),
        _src("web-search", "Web araması (yeni raporları keşif)", "community", "web_search", "(yapılandırılabilir)",
             "unknown", critical=False, config={"max_queries": 6},
             note="SEARCH_PROVIDER ile Brave veya SearXNG seçilir."),
        # Haberler (Aşama 2)
        _src("news-aa", "Anadolu Ajansı – Güncel", "news", "rss", "https://www.aa.com.tr/tr/rss/default?cat=guncel",
             "press", category="turkiye", config={"max_age_days": 2, "lang": "tr"}, note=UNVALIDATED),
        _src("news-ntv", "NTV – Gündem", "news", "rss", "https://www.ntv.com.tr/gundem.rss", "press",
             category="turkiye", config={"max_age_days": 2, "lang": "tr"}, note=UNVALIDATED),
        _src("news-bbc-turkce", "BBC Türkçe", "news", "rss", "https://feeds.bbci.co.uk/turkce/rss.xml", "press",
             category="dunya", config={"max_age_days": 2, "lang": "tr"}, note=UNVALIDATED),
        _src("news-dw-turkce", "DW Türkçe", "news", "rss", "https://rss.dw.com/rdf/rss-tur-all", "press",
             category="dunya", config={"max_age_days": 2, "lang": "tr"}, note=UNVALIDATED),
        _src("news-bbc-world", "BBC News – World", "news", "rss", "https://feeds.bbci.co.uk/news/world/rss.xml",
             "press", category="dunya", config={"max_age_days": 2, "lang": "en"}, note=UNVALIDATED),
        _src("news-euronews-tr", "Euronews Türkçe", "news", "rss", "https://tr.euronews.com/rss", "press",
             category="genel", config={"max_age_days": 2, "lang": "tr"}, note=UNVALIDATED),
        _src("news-webrazzi", "Webrazzi", "news", "rss", "https://webrazzi.com/feed/", "press",
             category="teknoloji", config={"max_age_days": 2, "lang": "tr"}, note=UNVALIDATED),
        _src("news-theverge", "The Verge", "news", "rss", "https://www.theverge.com/rss/index.xml", "press",
             category="teknoloji", config={"max_age_days": 2, "lang": "en"}, note=UNVALIDATED),
        _src("news-arstechnica", "Ars Technica", "news", "rss", "https://feeds.arstechnica.com/arstechnica/index",
             "press", category="teknoloji", config={"max_age_days": 2, "lang": "en"}, note=UNVALIDATED),
    ]
    return out


def seed_sources(conn: sqlite3.Connection) -> int:
    """Yerleşik kaynakları ekler (var olanlara dokunmaz). Eklenen sayısını döndürür."""
    added = 0
    ts = now_iso()
    for s in builtin_sources():
        exists = conn.execute("SELECT id FROM sources WHERE slug = ?", (s["slug"],)).fetchone()
        if exists:
            continue
        conn.execute(
            "INSERT INTO sources(slug, name, module, adapter, url, fetch_url, fallback_url, trust, category, "
            "product_ids, enabled, builtin, critical, config_json, validation_note, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)",
            (s["slug"], s["name"], s["module"], s["adapter"], s["url"], s["fetch_url"], s["fallback_url"],
             s["trust"], s["category"], jdump(s["product_ids"]), 1 if s["enabled"] else 0,
             1 if s["critical"] else 0, jdump(s["config"]), s["validation_note"], ts, ts),
        )
        added += 1
    return added


def sync_product_sources(conn: sqlite3.Connection, settings: dict[str, Any]) -> None:
    """Seçilen ürünlere göre ürün bazlı Windows kaynaklarını aç/kapat."""
    selected = set(settings.get("products") or [])
    for row in conn.execute("SELECT id, product_ids, adapter FROM sources WHERE builtin = 1 AND adapter IN "
                            "('wrh_status', 'wrh_resolved', 'ms_update_history')").fetchall():
        pids = set(jload(row["product_ids"], []))
        conn.execute("UPDATE sources SET enabled = ?, updated_at = ? WHERE id = ?",
                     (1 if pids & selected else 0, now_iso(), row["id"]))


def module_enabled(settings: dict[str, Any], module: str) -> bool:
    mods = settings.get("modules", {})
    if module == "community":
        return bool(mods.get("community")) and any(mods.get(m) for m in ("windows", "intune", "configmgr"))
    return bool(mods.get(module))
