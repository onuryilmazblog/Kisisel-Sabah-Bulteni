"""Adaptör eşlemesi ve yerleşik (varsayılan) kaynak listesi.

Kaynaklar veri tabanında saklanır. Yerleşik kaynaklar her başlangıçta slug'a göre eklenir.
Arayüzden yerleşik kaynakların yalnızca açık/kapalı durumu değiştirilebilir; bu tercih korunur.
`BUILTIN_REV` artırıldığında mevcut yerleşik kaynakların tanımı (adres, yapılandırma, not)
koddaki listeyle yenilenir.
"""
from __future__ import annotations

import sqlite3
from typing import Any

from ..catalog import PRODUCTS, wrh_url
from ..db import jdump, jload, kv_get, kv_set
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

# Yerleşik kaynak tanımları değiştiğinde artırılır (mevcut kurulumlarda adres/yapılandırma yenilenir).
# 2: support.microsoft.com kanonik /servicing/os/ adresleri, güncelleme geçmişi menü kategorisi,
#    canlı doğrulama notları, robots.txt'nin engellediği kaynakların kapatılması, NTV adresi.
BUILTIN_REV = 2

RAW_MEMDOCS = "https://raw.githubusercontent.com/MicrosoftDocs/memdocs/main/"
LIVE_VALIDATED = "Canlı doğrulandı (2026-09-26, bulten kaynak-dogrula --hepsi)."
UNVALIDATED = "Doğrulanmadı: 'Kaynağı test et' ile kontrol edin."
ROBOTS_BLOCKED = ("robots.txt otomatik erişime izin vermiyor (2026-09-26'da kontrol edildi); uygulama robots.txt'ye "
                  "uyduğu için varsayılan olarak kapalı.")
MEMDOCS_VALIDATED = "Markdown kaynağı GitHub'dan canlı okunarak doğrulandı (2026-09-26)."


def _src(slug: str, name: str, module: str, adapter: str, url: str, trust: str, *, fetch_url: str | None = None,
         fallback_url: str | None = None, category: str | None = None, products: list[str] | None = None,
         enabled: bool = True, critical: bool = False, config: dict[str, Any] | None = None,
         note: str = UNVALIDATED, blocked: bool = False) -> dict[str, Any]:
    # blocked: kaynak kalıcı olarak okunamıyor (ör. robots.txt); tanım yenilenirken de kapatılır.
    return {
        "slug": slug, "name": name, "module": module, "adapter": adapter, "url": url, "fetch_url": fetch_url,
        "fallback_url": fallback_url, "trust": trust, "category": category, "product_ids": products or [],
        "enabled": enabled and not blocked, "critical": critical, "config": config or {}, "validation_note": note,
        "blocked": blocked,
    }


def builtin_sources() -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for p in PRODUCTS:
        if p.wrh_status:
            out.append(_src(f"wrh-status-{p.id}", f"Release health: {p.label}", "windows", "wrh_status",
                            wrh_url(p.wrh_status), "official", products=[p.id], enabled=False, critical=True,
                            note=LIVE_VALIDATED))
        if p.wrh_resolved:
            out.append(_src(f"wrh-resolved-{p.id}", f"Çözülen sorunlar: {p.label}", "windows", "wrh_resolved",
                            wrh_url(p.wrh_resolved), "official", products=[p.id], enabled=False,
                            note=LIVE_VALIDATED))
        if p.update_history:
            out.append(_src(f"ms-uh-{p.id}", f"Güncelleme geçmişi: {p.label}", "windows", "ms_update_history",
                            p.update_history, "official", products=[p.id], enabled=False, critical=True,
                            config={"months_back": 4, "nav_category": p.uh_nav},
                            note=LIVE_VALIDATED + (" " + p.note if p.note else "")))
    out += [
        _src("ms-kb-articles", "KB makaleleri (Known issues bölümleri)", "windows", "ms_kb",
             "https://support.microsoft.com/", "official", critical=True, config={"days_back": 60, "max_pages": 15},
             note="Adresler güncelleme geçmişi sayfalarından dinamik alınır. KB makalesi ayrıştırıcısı gerçek "
                  "sayfalarla doğrulandı (2026-09-26)."),
        _src("wrh-message-center", "Windows message center", "windows", "wrh_messages",
             "https://learn.microsoft.com/en-us/windows/release-health/windows-message-center", "official",
             note=LIVE_VALIDATED),
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
             "official", config={"max_age_days": 21, "official_blog": True}, note=LIVE_VALIDATED),
        _src("tc-windows-itpro", "Windows IT Pro blogu", "windows", "rss",
             "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=Windows-ITPro-blog",
             "official", config={"max_age_days": 21, "official_blog": True}, note=LIVE_VALIDATED),
        _src("tc-configmgr", "Configuration Manager blogu", "configmgr", "rss",
             "https://techcommunity.microsoft.com/t5/s/gxcuf89792/rss/board?board.id=ConfigurationManagerBlog",
             "official", config={"max_age_days": 30, "official_blog": True}, note=LIVE_VALIDATED),
        # Saha sinyalleri: topluluklar ve teknoloji yayınları
        _src("reddit-sysadmin", "r/sysadmin", "community", "rss", "https://www.reddit.com/r/sysadmin/new/.rss",
             "community", critical=True, config={"max_age_days": 4}, note=ROBOTS_BLOCKED, blocked=True),
        _src("reddit-intune", "r/Intune", "community", "rss", "https://www.reddit.com/r/Intune/new/.rss",
             "community", critical=True, config={"max_age_days": 4}, note=ROBOTS_BLOCKED, blocked=True),
        _src("reddit-sccm", "r/SCCM", "community", "rss", "https://www.reddit.com/r/SCCM/new/.rss",
             "community", config={"max_age_days": 5}, note=ROBOTS_BLOCKED, blocked=True),
        _src("bleepingcomputer", "BleepingComputer", "community", "rss", "https://www.bleepingcomputer.com/feed/",
             "press", critical=True, config={"max_age_days": 5}, note=LIVE_VALIDATED),
        _src("borncity", "Born's Tech and Windows World", "community", "rss", "https://borncity.com/win/feed/",
             "press", critical=True, config={"max_age_days": 5}, note=LIVE_VALIDATED),
        _src("windowslatest", "Windows Latest", "community", "rss", "https://www.windowslatest.com/feed/",
             "press", config={"max_age_days": 5}, note=LIVE_VALIDATED),
        _src("askwoody", "AskWoody", "community", "rss", "https://www.askwoody.com/feed/", "press",
             config={"max_age_days": 7}, note=LIVE_VALIDATED),
        _src("web-search", "Web araması (yeni raporları keşif)", "community", "web_search", "(yapılandırılabilir)",
             "unknown", critical=False, config={"max_queries": 6},
             note="SEARCH_PROVIDER ile Brave veya SearXNG seçilir."),
        # Haberler (Aşama 2)
        _src("news-aa", "Anadolu Ajansı – Güncel", "news", "rss", "https://www.aa.com.tr/tr/rss/default?cat=guncel",
             "press", category="turkiye", config={"max_age_days": 2, "lang": "tr"}, note=LIVE_VALIDATED),
        _src("news-ntv", "NTV – Türkiye", "news", "rss", "https://www.ntv.com.tr/turkiye.rss", "press",
             category="turkiye", config={"max_age_days": 2, "lang": "tr"},
             note=LIVE_VALIDATED + " (gundem.rss bu adrese kalıcı yönlendiriliyor.)"),
        _src("news-bbc-turkce", "BBC Türkçe", "news", "rss", "https://feeds.bbci.co.uk/turkce/rss.xml", "press",
             category="dunya", config={"max_age_days": 2, "lang": "tr"}, note=LIVE_VALIDATED),
        _src("news-dw-turkce", "DW Türkçe", "news", "rss", "https://rss.dw.com/rdf/rss-tur-all", "press",
             category="dunya", config={"max_age_days": 2, "lang": "tr"}, note=LIVE_VALIDATED),
        _src("news-bbc-world", "BBC News – World", "news", "rss", "https://feeds.bbci.co.uk/news/world/rss.xml",
             "press", category="dunya", config={"max_age_days": 2, "lang": "en"}, note=LIVE_VALIDATED),
        _src("news-euronews-tr", "Euronews Türkçe", "news", "rss", "https://tr.euronews.com/rss", "press",
             category="genel", config={"max_age_days": 2, "lang": "tr"}, note=LIVE_VALIDATED),
        _src("news-webrazzi", "Webrazzi", "news", "rss", "https://webrazzi.com/feed/", "press",
             category="teknoloji", config={"max_age_days": 2, "lang": "tr"}, note=ROBOTS_BLOCKED,
             blocked=True),
        _src("news-theverge", "The Verge", "news", "rss", "https://www.theverge.com/rss/index.xml", "press",
             category="teknoloji", config={"max_age_days": 2, "lang": "en"}, note=LIVE_VALIDATED),
        _src("news-arstechnica", "Ars Technica", "news", "rss", "https://feeds.arstechnica.com/arstechnica/index",
             "press", category="teknoloji", config={"max_age_days": 2, "lang": "en"}, note=LIVE_VALIDATED),
    ]
    return out


def seed_sources(conn: sqlite3.Connection) -> int:
    """Yerleşik kaynakları ekler; `BUILTIN_REV` arttıysa mevcutların tanımını yeniler.

    Açık/kapalı tercihi korunur; tek istisna kalıcı olarak okunamayan (`blocked`, ör. robots.txt)
    kaynakların kapatılmasıdır. Eklenen kaynak sayısını döndürür.
    """
    added = 0
    ts = now_iso()
    refresh = int(kv_get(conn, "builtin_sources_rev", "0") or 0) < BUILTIN_REV
    for s in builtin_sources():
        exists = conn.execute("SELECT id FROM sources WHERE slug = ?", (s["slug"],)).fetchone()
        if exists:
            if refresh:
                conn.execute(
                    "UPDATE sources SET name = ?, module = ?, adapter = ?, url = ?, fetch_url = ?, fallback_url = ?, "
                    "trust = ?, category = ?, product_ids = ?, critical = ?, config_json = ?, validation_note = ?, "
                    "enabled = CASE WHEN ? = 1 THEN 0 ELSE enabled END, updated_at = ? WHERE id = ? AND builtin = 1",
                    (s["name"], s["module"], s["adapter"], s["url"], s["fetch_url"], s["fallback_url"], s["trust"],
                     s["category"], jdump(s["product_ids"]), 1 if s["critical"] else 0, jdump(s["config"]),
                     s["validation_note"], 1 if s["blocked"] else 0, ts, exists["id"]),
                )
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
    if refresh:
        kv_set(conn, "builtin_sources_rev", str(BUILTIN_REV))
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
