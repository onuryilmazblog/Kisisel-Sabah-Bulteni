"""Demo verisi: API anahtarları/erişim olmadan arayüzü denemek için.

Tüm demo kayıtları `is_demo = 1` ile işaretlenir, arayüzde ve bildirimlerde "Demo" etiketiyle görünür,
gerçek olay hafızasıyla eşleştirilmez ve `bulten demo-sil` ile tamamen kaldırılır.
KB numaraları ve içerikler KURGUSALDIR.
"""
from __future__ import annotations

import copy
import json
import sqlite3

from .db import jdump, tx
from .pipeline.analyze import analyze_events
from .pipeline.bulletin import compose_bulletin
from .pipeline.collect import upsert_observations
from .pipeline.match import match_pending
from .pipeline.summarize import summarize_pending
from .settings_store import get_settings
from .sources.base import Observation, SourceRow
from .timeutil import now_iso

DEMO_SOURCES = [
    ("demo-official", "Demo: resmî kaynak (Windows)", "windows", "official", None),
    ("demo-intune", "Demo: resmî kaynak (Intune)", "intune", "official", None),
    ("demo-cm", "Demo: resmî kaynak (ConfigMgr)", "configmgr", "official", None),
    ("demo-community", "Demo: topluluk", "community", "community", None),
    ("demo-press", "Demo: teknoloji basını", "community", "press", None),
    ("demo-news-tr", "Demo: haber (Türkiye)", "news", "press", "turkiye"),
    ("demo-news-tr2", "Demo: haber 2 (Türkiye)", "news", "press", "turkiye"),
    ("demo-news-dunya", "Demo: haber (Dünya)", "news", "press", "dunya"),
]


def _ensure_sources(conn: sqlite3.Connection) -> dict[str, SourceRow]:
    out = {}
    for slug, name, module, trust, cat in DEMO_SOURCES:
        row = conn.execute("SELECT * FROM sources WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sources(slug, name, module, adapter, url, trust, category, enabled, builtin, critical, "
                "config_json, validation_note, created_at, updated_at) VALUES (?, ?, ?, 'rss', 'https://demo.invalid/', ?, ?, "
                "0, 0, 0, '{}', 'Demo verisi (kurgusal)', ?, ?)", (slug, name, module, trust, cat, now_iso(), now_iso()))
            row = conn.execute("SELECT * FROM sources WHERE slug = ?", (slug,)).fetchone()
        out[slug] = SourceRow.from_row(row)
    return out


def _obs(**kw) -> Observation:
    return Observation(**kw)


def demo_observations() -> dict[str, list[Observation]]:
    wrh = "https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-25h2"
    return {
        "demo-official": [
            _obs(external_key="wrh:demo-9101", kind="known_issue", title="Remote Desktop Services might become unstable",
                 url=wrh + "#demo", published_at="2026-09-10T16:12:00+00:00",
                 body="After installing the September 2026 security update (KB5999908), some organizations might experience "
                      "issues with Remote Desktop Services (RDS). RDP connections might fail after several minutes.\n"
                      "Workaround: This issue is mitigated using a Known Issue Rollback (KIR) Group Policy.",
                 fields={"status": "mitigated", "status_raw": "Mitigated", "originating_kbs": ["5999908"],
                         "workaround": "This issue is mitigated using a Known Issue Rollback (KIR) Group Policy.",
                         "kir": True, "products": ["win11-25h2", "win11-24h2", "ws2025"], "tags": ["rds", "auth"]}),
            _obs(external_key="wrh:demo-9102", kind="known_issue",
                 title="Credential Guard protected machine accounts might lose secure channel", url=wrh + "#demo2",
                 published_at="2026-09-09T23:40:00+00:00",
                 body="After installing KB5999908, some Credential Guard protected machine accounts might lose their secure "
                      "channel with an on-premises Active Directory domain. Users might be unable to sign in.",
                 fields={"status": "confirmed", "originating_kbs": ["5999908"], "products": ["win11-25h2", "win11-24h2"],
                         "tags": ["dc", "auth"]}),
            _obs(external_key="kb:5999908", kind="kb_release",
                 title="September 8, 2026—KB5999908 (OS Builds 26200.9445 and 26100.9445)",
                 url="https://support.microsoft.com/", published_at="2026-09-08T00:00:00+00:00",
                 fields={"kb": "5999908", "release_type": "security", "builds": ["26100.9445", "26200.9445"],
                         "products": ["win11-25h2", "win11-24h2"]}),
            _obs(external_key="kb:5999920", kind="kb_release",
                 title="September 14, 2026—KB5999920 (OS Builds 26200.9457 and 26100.9457) Out-of-band",
                 url="https://support.microsoft.com/", published_at="2026-09-14T00:00:00+00:00",
                 fields={"kb": "5999920", "release_type": "oob", "builds": ["26100.9457", "26200.9457"],
                         "products": ["win11-25h2", "win11-24h2"]}),
        ],
        "demo-intune": [
            _obs(external_key="intune:wi:demo-1", kind="feature", title="Operating system version property in assignment filters is generally available",
                 url="https://learn.microsoft.com/en-us/intune/whats-new/", published_at="2026-08-25T00:00:00+00:00",
                 body="The operating system version property in assignment filters is now generally available for Windows devices.",
                 fields={"stage": "ga", "change_kind": "feature", "platforms": ["windows"], "week": "August 25, 2026",
                         "service_release": "2608"}),
            _obs(external_key="intune:t:demo-notice", kind="notice", title="Plan for change: Update to the latest Intune Company Portal",
                 url="https://learn.microsoft.com/en-us/intune/whats-new/#notices",
                 body="Starting January 2027, older Company Portal versions will be blocked. How can you prepare? Update the "
                      "Company Portal to the latest version.",
                 fields={"stage": "notice", "change_kind": "change", "platforms": ["android"],
                         "admin_action": "Update the Company Portal to the latest version before January 2027."}),
        ],
        "demo-cm": [
            _obs(external_key="cm:version:demo-2503", kind="cm_version", title="Configuration Manager 2503 (Current Branch)",
                 url="https://learn.microsoft.com/en-us/intune/configmgr/core/servers/manage/updates",
                 body="Demo: destek sonu yaklaşan sürüm.",
                 fields={"version": "2503", "track": "current", "supported": True, "support_days_left": 4,
                         "support_end": "2026-09-30T00:00:00+00:00", "availability": "2025-03-31T00:00:00+00:00",
                         "build": "5.00.9135"}),
        ],
        "demo-community": [
            _obs(external_key="rss:demo-r1", kind="field_report", title="KB5999911 broke Always On VPN on our Server 2025 RRAS boxes",
                 url="https://www.reddit.com/r/sysadmin/comments/demo1/", published_at="2026-09-21T01:00:00+00:00",
                 body="After installing KB5999911 on Windows Server 2025 RRAS servers, IKEv2 VPN connections fail.",
                 fields={"kbs": ["5999911"], "products": ["ws2025"], "tags": ["vpn"], "author": "u/demo1",
                         "source_name": "r/sysadmin (demo)", "canonical_url": "https://www.reddit.com/r/sysadmin/comments/demo1/"}),
        ],
        "demo-press": [
            _obs(external_key="rss:demo-p1", kind="field_report", title="Windows Server 2025: VPN problems after KB5999911",
                 url="https://borncity.com/win/demo/", published_at="2026-09-21T02:00:00+00:00",
                 body="Administrators report RRAS VPN connections failing after update KB5999911 on Windows Server 2025.",
                 fields={"kbs": ["5999911"], "products": ["ws2025"], "tags": ["vpn"], "source_name": "Born's Tech (demo)",
                         "canonical_url": "https://borncity.com/win/demo/"}),
        ],
        "demo-news-tr": [
            _obs(external_key="rss:demo-n1", kind="article", title="İstanbul'da 5,2 büyüklüğünde deprem: AFAD açıklama yaptı",
                 url="https://demo.invalid/n1", lang="tr", published_at=now_iso(),
                 body="Marmara Denizi'nde meydana gelen deprem İstanbul'da da hissedildi. Can kaybı bildirilmedi.",
                 fields={"news_category": "turkiye", "source_name": "Demo haber", "canonical_url": "https://demo.invalid/n1"}),
        ],
        "demo-news-tr2": [
            _obs(external_key="rss:demo-n2", kind="article", title="İstanbul'da 5,2 büyüklüğünde deprem meydana geldi",
                 url="https://demo.invalid/n2", lang="tr", published_at=now_iso(),
                 body="Marmara Denizi'nde meydana gelen deprem İstanbul'da da hissedildi.",
                 fields={"news_category": "turkiye", "source_name": "Demo haber 2", "canonical_url": "https://demo.invalid/n2"}),
        ],
        "demo-news-dunya": [
            _obs(external_key="rss:demo-n3", kind="article", title="AB liderleri enerji fiyatları için ortak adım üzerinde uzlaştı",
                 url="https://demo.invalid/n3", lang="tr", published_at=now_iso(),
                 body="Brüksel'deki zirvede ortak alım mekanizmasının kapsamı genişletildi.",
                 fields={"news_category": "dunya", "source_name": "Demo haber", "canonical_url": "https://demo.invalid/n3"}),
        ],
    }


DEMO_DAILY = {
    "weather": ("Demo", {"provider": "Demo (Open-Meteo biçiminde kurgusal veri)", "location": "Demo İlçe", "admin1": "Demo İl",
                         "current": {"temperature": 19.5, "apparent": 18.0, "precipitation": 0.0, "code": 2,
                                     "description": "Parçalı bulutlu", "wind": 12.0,
                                     "units": {"temperature": "°C", "precipitation": "mm", "wind": "km/h"}},
                         "today": {"max": 23.0, "min": 15.0, "precipitation_sum": 0.4, "precipitation_probability": 20,
                                   "description": "Parçalı bulutlu", "units": {"temperature": "°C", "precipitation": "mm"}},
                         "warnings": {"items": [], "note": "Demo: resmî uyarı verisi yok."}}),
    "market": ("Demo", {"blocks": [
        {"provider": "tcmb", "provider_label": "DEMO – TCMB gösterge kuru (referans) biçimi", "data_time": None,
         "items": {"USDTRY": {"label": "USD/TRY", "unit": "TRY / 1 USD", "prices": {"Döviz alış": 41.5, "Döviz satış": 41.58}}},
         "note": ""},
        {"provider": "demo", "provider_label": "DEMO – piyasa verisi (kurgusal)", "data_time": None,
         "items": {"GRAM24": {"label": "Gram altın (24 ayar)", "unit": "TRY / gram", "prices": {"Alış": 4600.0, "Satış": 4615.0}}},
         "note": ""}], "missing": ["22 ayar bilezik (gram)"], "errors": []}),
    "calendar": ("Demo", {"events": [{"summary": "Değişiklik danışma kurulu (demo)", "location": "Teams", "all_day": False,
                                      "start": now_iso(), "end": None, "start_local": "10:00"}], "count": 1}),
}


def load_demo(conn: sqlite3.Connection) -> int:
    """Demo verisini yükler ve bir demo bülteni oluşturur. Demo bülten kimliğini döndürür."""
    remove_demo(conn)
    with tx(conn):
        sources = _ensure_sources(conn)
    for slug, obs in demo_observations().items():
        upsert_observations(conn, sources[slug], obs, first_run=False, is_demo=True)
    match_pending(conn)
    analyze_events(conn)
    # İkinci sürüm örneği: Credential Guard sorununa geçici çözüm eklendi → "Ne değişti?"
    cg = demo_observations()["demo-official"][1]
    cg.fields["workaround"] = "Temporarily disable machine account password rotation for affected devices (see KB)."
    cg.body += "\nWorkaround: Temporarily disable machine account password rotation for affected devices (see KB)."
    upsert_observations(conn, sources["demo-official"], [cg], first_run=False, is_demo=True)
    analyze_events(conn)
    summarize_pending(conn, max_llm_calls=0)
    ids = {}
    for module, (provider, payload) in DEMO_DAILY.items():
        ids[module] = conn.execute(
            "INSERT INTO daily_data(module, provider, fetched_at, data_time, status, payload_json, is_demo) "
            "VALUES (?, ?, ?, ?, 'ok', ?, 1)", (module, provider, now_iso(), now_iso(), jdump(payload))).lastrowid
    demo_settings = copy.deepcopy(get_settings(conn))
    demo_settings["modules"] = {k: True for k in demo_settings["modules"]}
    demo_settings["news_categories"] = ["turkiye", "dunya", "genel", "teknoloji"]
    bid = compose_bulletin(conn, kind="daily", is_demo=1, settings=demo_settings)
    with tx(conn):
        row = conn.execute("SELECT content_json FROM bulletins WHERE id = ?", (bid,)).fetchone()
        content = json.loads(row["content_json"])
        content["daily"] = ids
        conn.execute("UPDATE bulletins SET content_json = ? WHERE id = ?", (jdump(content), bid))
    return bid


def remove_demo(conn: sqlite3.Connection) -> None:
    with tx(conn):
        conn.execute("DELETE FROM bulletins WHERE is_demo = 1")
        conn.execute("DELETE FROM events WHERE is_demo = 1")
        conn.execute("DELETE FROM observations WHERE is_demo = 1")
        conn.execute("DELETE FROM daily_data WHERE is_demo = 1")
        conn.execute("DELETE FROM sources WHERE slug LIKE 'demo-%' AND builtin = 0")


def demo_loaded(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM events WHERE is_demo = 1 LIMIT 1").fetchone() is not None
