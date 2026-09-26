"""Gerçek Microsoft sayfalarına karşı ayrıştırıcı testleri.

`fixtures/ms-real/` altındaki dosyalar learn.microsoft.com ve support.microsoft.com'dan 2026-09-26'da
indirilip yalnızca ana içerik bırakılarak küçültülmüş gerçek sayfalardır (bkz. fixtures/README.md).
"""
from __future__ import annotations

import json

from helpers import FIXTURES, FakeFetcher, freeze, make_db, only_sources

from bulten.catalog import PRODUCT_BY_ID
from bulten.pipeline.run import collect_and_process
from bulten.sources.ms_support import parse_kb_article, parse_update_history
from bulten.sources.wrh import parse_message_center, parse_wrh_page

REAL = FIXTURES / "ms-real"
WRH = "https://learn.microsoft.com/en-us/windows/release-health"


def _wrh(name: str, products: list[str], section: str = "active"):
    r = parse_wrh_page((REAL / f"wrh-{name}.html").read_text(), page_url=f"{WRH}/{name}",
                       page_products=products, section=section)
    assert r.structure_ok and not r.warnings
    return r, {o.external_key: o for o in r.observations}


def test_real_wrh_status_windows_11_25h2():
    r, by = _wrh("status-windows-11-25h2", ["win11-25h2"])
    assert len(r.observations) == 10
    for o in r.observations:
        # Her sorunun ayrıntı bölümü ve "Affected platforms" kuyruğu okunmalı.
        assert o.fields["affected_platforms"], o.external_key
        assert o.fields.get("opened"), o.external_key
        assert o.url.startswith(f"{WRH}/status-windows-11-25h2#") and o.url.endswith("msgdesc")

    rds = by["wrh:4981"]
    assert rds.title.startswith("Remote Desktop Services might stop responding")
    assert rds.fields["status"] == "resolved" and rds.fields["status_raw"] == "Resolved KB5129195"
    assert rds.fields["originating_kbs"] == ["5124008"] and rds.fields["resolving_kbs"] == ["5129195"]
    assert "rds" in rds.fields["tags"]
    assert {"win11-25h2", "ws2025", "ws2022"} <= set(rds.fields["products"])
    assert rds.published_at == "2026-09-11T18:19:00+00:00"  # "Opened: 2026-09-11, 11:19 PT"
    assert rds.fields["resolved"] == "2026-09-14T17:00:00+00:00"

    # İç içe div'lerde kalan kuyruk (KIR notu, etkilenen platformlar) kesilmemeli.
    black = by["wrh:5006"]
    assert black.fields["status"] == "mitigated" and black.fields["kir"]
    assert black.fields["originating_kbs"] == ["5120998"] and black.fields["resolving_kbs"] == []
    assert "Windows 11, version 25H2" in black.fields["affected_platforms"]["client"]
    assert black.fields["affected_platforms"].get("server") is None  # "Server: None"
    assert "avd" in black.fields["tags"]

    # "partially resolved in … (KB5129195)" tam düzeltme sayılmaz.
    audio = by["wrh:4984"]
    assert audio.fields["status"] == "mitigated"
    assert audio.fields["resolving_kbs"] == [] and audio.fields["partial_fix_kbs"] == ["5129195"]

    trust = by["wrh:4990"]
    assert trust.fields["workaround"].startswith("To work around this issue"), "kayıt defteri uyarısı atlanmalı"

    # "Originating update: N/A" → kaynak KB yok; çözüm KB'si durum hücresinden gelmez.
    defender = by["wrh:4956"]
    assert defender.fields["originating_kbs"] == [] and defender.fields["status"] == "resolved"

    # Olumsuz cümle ("does not affect …") etiket üretmez; yalnızca Hyper-V/paylaşım etiketleri.
    share = by["wrh:4983"]
    assert {"hyperv", "storage"} <= set(share.fields["tags"])


def test_real_wrh_same_issue_has_product_specific_kbs():
    _, s25 = _wrh("status-windows-11-25h2", ["win11-25h2"])
    _, ws = _wrh("status-windows-server-2025", ["ws2025"])
    a, b = s25["wrh:4981"], ws["wrh:4981"]
    # Aynı sorun kimliği iki sayfada, ürüne özgü farklı KB'lerle yayımlanır (anahtar aynı → tek olay).
    assert a.external_key == b.external_key
    assert b.fields["originating_kbs"] == ["5122871"] and b.fields["resolving_kbs"] == ["5129235"]
    assert a.fields["resolving_kbs"] != b.fields["resolving_kbs"]


def test_real_wrh_resolved_issues_edge_cases():
    r, by = _wrh("resolved-issues-windows-11-23h2", ["win11-23h2"], section="resolved")
    assert len(r.observations) == 12
    assert all(o.fields["status"] == "resolved" for o in r.observations)
    assert all(o.fields["affected_platforms"] for o in r.observations)

    # Gövdede "limited to the affected platforms listed below" geçiyor; asıl blok sonda.
    shut = by["wrh:3764"]
    assert shut.fields["affected_platforms"]["server"] == "Windows Server 2022; Windows Server 2019"
    assert "Windows 11, version 23H2" in shut.fields["affected_platforms"]["client"]
    assert shut.fields["originating_kbs"] == ["5073455"]
    # Tam çözüm KB5075941; "an initial solution that resolved some devices" OOB'leri kısmi düzeltmedir.
    assert shut.fields["resolving_kbs"] == ["5075941"]
    assert shut.fields["partial_fix_kbs"] == ["5077797", "5078132"]
    assert {"ws2022", "ws2019"} <= set(shut.fields["products"])

    # Üç haneli gerçek kimlik ve "N/A" kaynak güncelleme
    parental = by["wrh:350"]
    assert parental.fields["originating_kbs"] == [] and parental.fields["resolving_kbs"] == ["5062663"]

    rollback = by["wrh:4875"]
    assert rollback.fields["kir"] and rollback.fields["originating_kbs"] == ["5093998"]


def test_real_wrh_message_center():
    r = parse_message_center((REAL / "wrh-windows-message-center.html").read_text(),
                             page_url=f"{WRH}/windows-message-center")
    assert r.structure_ok and not r.warnings
    assert len(r.observations) == 12  # örnek dosya ilk 12 duyuruyla sınırlı
    by = {o.external_key: o for o in r.observations}
    tz = by["wmc:5008"]
    assert tz.title == "Interim time zone guidance for Alberta, British Columbia, and Morocco"
    assert tz.published_at == "2026-09-25T20:00:00+00:00"  # "2026-09-25 13:00 PT"
    assert tz.url == f"{WRH}/windows-message-center#5008"
    oob = by["wmc:4986"]
    assert oob.title.startswith("Take Action: Out-of-band update")
    assert "5129195" in oob.fields["kbs"]


# --- support.microsoft.com -------------------------------------------------------

SUP = "https://support.microsoft.com/en-us/servicing/os"
UH25 = f"{SUP}/windows-11/2025/07/windows-11-version-25h2-update-history"


def test_real_update_history_reads_only_the_products_nav_category():
    freeze(2026, 9, 26)
    html = (REAL / "uh-windows-11-version-25h2.html").read_text()
    r = parse_update_history(html, page_url=UH25, page_products=["win11-25h2"], nav_category="Windows 11, version 25H2")
    assert r.structure_ok and not r.warnings
    by = {o.fields["kb"]: o for o in r.observations}
    # Menüde 26H1 (KB5124006, KB5129194, KB5124012) ve 23H2 (KB5129242) KB'leri de var; alınmamalı.
    assert not {"5124006", "5129194", "5124012", "5129242"} & set(by)
    assert [o.fields["kb"] for o in r.observations][:5] == ["5124010", "5129195", "5124008", "5120998", "5121003"]
    assert by["5124010"].fields["release_type"] == "preview"
    assert by["5129195"].fields["release_type"] == "oob"
    assert by["5124008"].fields["release_type"] == "security"  # etiketsiz + ayın 2. salısı
    assert by["5124008"].fields["builds"] == ["26100.9445", "26200.9445"]
    # Göreli bağlantı (../../2026/09/…) sayfa adresine göre mutlak adrese çevrilir.
    assert by["5124008"].url == f"{SUP}/windows-11/2026/09/kb5124008-windows-11-24h2-25h2-security-update"
    assert by["5124008"].published_at.startswith("2026-09-08")
    # 4 aylık pencere: 26 Mayıs dahil, 12 Mayıs hariç
    assert "5089573" in by and "5089549" not in by

    # Kategori verilmezse sayfanın etkin kategorisi kullanılır.
    same = parse_update_history(html, page_url=UH25, page_products=["win11-25h2"])
    assert [o.external_key for o in same.observations] == [o.external_key for o in r.observations]
    # Kategori bulunamazsa tahmin edilmez: yapı uyarısı verilir.
    bad = parse_update_history(html, page_url=UH25, page_products=["win11-25h2"], nav_category="Windows 11, version 27H2")
    assert not bad.structure_ok and not bad.observations and "bulunamadı" in bad.warnings[0]


def test_real_update_history_shared_page_and_product_name_in_title():
    freeze(2026, 9, 26)
    html = (REAL / "uh-windows-10.html").read_text()
    url = f"{SUP}/windows-10/2022/09/windows-10-update-history"
    # Aynı sayfa hem 22H2 hem LTSC 2021 (21H2) için kullanılır; kategori ürüne göre seçilir.
    ltsc = parse_update_history(html, page_url=url, page_products=["win10-ltsc2021"],
                                nav_category="Windows 10, version 21H2", months_back=12)
    assert ltsc.structure_ok and ltsc.observations[0].fields["kb"] == "5129236"
    assert all(o.fields["products"] == ["win10-ltsc2021"] for o in ltsc.observations)
    w22 = parse_update_history(html, page_url=url, page_products=["win10-22h2"],
                               nav_category="Windows 10, version 22H2", months_back=12)
    by = {o.fields["kb"]: o for o in w22.observations}
    # "November 11, 2025—KB5071959 Windows 10, version 22H2 (OS Build 19045.6466) Out-of-band"
    assert by["5071959"].fields["release_type"] == "oob" and by["5071959"].fields["builds"] == ["19045.6466"]
    # Tarihli olmayan menü öğeleri (ESU lisans paketi, hizmet sonu bildirimi) KB sürümü sayılmaz.
    assert all(o.title[0].isalpha() and "—KB" in o.title for o in w22.observations)


def test_real_kb_article_known_issues_split_per_issue():
    url = f"{SUP}/windows-11/2026/09/kb5124008-windows-11-24h2-25h2-security-update"
    r = parse_kb_article((REAL / "kb5124008.html").read_text(), kb="5124008", page_url=url,
                         page_products=["win11-24h2", "win11-25h2"])
    assert r.structure_ok and not r.warnings
    assert [o.title for o in r.observations] == [
        "Domain-joined devices might lose their secure trust relationship with the domain",
        "USB audio devices might fail to start or produce no sound",
        "Host folder shares might be unavailable in Hyper-V-based Linux VMs",
        "Remote Desktop Services might stop responding after September 2026 security update",
        "File History might stop working after installing September 2026 Windows update",
    ]
    trust, audio, share, rds, history = r.observations
    assert trust.fields["status"] == "confirmed" and "Machine Identity Isolation" in trust.fields["workaround"]
    # Microsoft'un standart kayıt defteri uyarısı geçici çözüm metnine alınmaz.
    assert trust.fields["workaround"].startswith("To work around this issue")
    assert {"dc", "auth"} <= set(trust.fields["tags"])
    # "partially resolved in … (KB5129195)" → tam düzeltme değil
    assert audio.fields["status"] == "mitigated"
    assert audio.fields["resolving_kbs"] == [] and audio.fields["partial_fix_kbs"] == ["5129195"]
    assert share.fields["status"] == "resolved" and share.fields["resolving_kbs"] == ["5129195"]
    assert rds.fields["status"] == "resolved" and "rds" in rds.fields["tags"]
    # "does not affect Windows 365 or Azure Virtual Desktop" → AVD etiketi yok
    assert "avd" not in rds.fields["tags"]
    assert history.fields["resolving_kbs"] == ["5124010"]
    assert all(o.url == url + "#known-issues-in-this-update" for o in r.observations)
    # Kaynak KB belirtide adı geçen güncellemedir; yoksa makalenin KB'si. (USB ses sorununda Microsoft
    # metni KB5124012'yi anıyor; kaynağa sadık kalınır, olay düzeyinde Release health'in KB'siyle birleşir.)
    assert [o.fields["originating_kbs"] for o in r.observations] == [
        ["5124008"], ["5124012"], ["5124008"], ["5124008"], ["5124008"]]
    later = parse_kb_article((REAL / "kb5124010.html").read_text(), kb="5124010", page_url="u", page_products=[])
    # "After installing KB5124008 or later updates": KB5124010 sorunu listeler ama kaynağı değildir.
    assert later.observations[0].fields["originating_kbs"] == ["5124008"]
    assert later.observations[0].fields["kb"] == "5124010"


def test_real_kb_article_server_and_no_issues():
    r = parse_kb_article((REAL / "kb5122871.html").read_text(), kb="5122871", page_url="u", page_products=["ws2025"])
    wsus, rds = r.observations
    # "After installing KB5070881 or later updates" → kaynak KB olarak eklenir
    assert wsus.fields["originating_kbs"] == ["5070881"] and wsus.fields["status"] == "confirmed"
    assert rds.fields["resolving_kbs"] == ["5129235"]
    none = parse_kb_article((REAL / "kb5101650.html").read_text(), kb="5101650", page_url="u", page_products=[])
    assert none.structure_ok and none.observations == [] and none.warnings == []


def test_real_pages_end_to_end_one_event_per_issue(tmp_path):
    """Gerçek sayfalarla toplama → eşleştirme → analiz: aynı sorun tek olay.

    Canlı çalıştırmada görülen tekrarların regresyon testi: Microsoft aynı sorunu her ürün için farklı
    KB numarasıyla ama aynı başlıkla yayımlar; açık sorunu sonraki KB makalelerinde de listeler.
    """
    freeze(2026, 9, 26, 5)
    conn = make_db(tmp_path, products=("win11-25h2", "ws2025", "ws2022"))
    w11, ws = f"{SUP}/windows-11/2026/09", f"{SUP}/windows-server/2026/09"
    ff = FakeFetcher(pages={
        PRODUCT_BY_ID["win11-25h2"].update_history: (REAL / "uh-windows-11-version-25h2.html").read_text(),
        PRODUCT_BY_ID["ws2025"].update_history: (REAL / "uh-windows-server-2025.html").read_text(),
        PRODUCT_BY_ID["ws2022"].update_history: (REAL / "uh-windows-server-2022.html").read_text(),
        f"{WRH}/status-windows-11-25h2": (REAL / "wrh-status-windows-11-25h2.html").read_text(),
        f"{WRH}/status-windows-server-2025": (REAL / "wrh-status-windows-server-2025.html").read_text(),
        f"{w11}/kb5124008-windows-11-24h2-25h2-security-update": (REAL / "kb5124008.html").read_text(),
        f"{w11}/kb5124010-windows-11-24h2-25h2-update": (REAL / "kb5124010.html").read_text(),
        f"{w11}/kb5129195-windows-11-24h2-25h2-security-update": (REAL / "kb5129195.html").read_text(),
        f"{ws}/kb5122871-windows-server-2025-security-update": (REAL / "kb5122871.html").read_text(),
        f"{ws}/kb5122882-windows-server-2022-security-update": (REAL / "kb5122882.html").read_text(),
    })
    slugs = ["ms-uh-win11-25h2", "ms-uh-ws2025", "ms-uh-ws2022", "wrh-status-win11-25h2", "wrh-status-ws2025",
             "ms-kb-articles"]
    collect_and_process(conn, fetcher=ff, source_ids=only_sources(conn, slugs))

    def ev(alias):
        return conn.execute("SELECT event_id FROM event_aliases WHERE alias = ?", (alias,)).fetchone()["event_id"]

    def kb_article_titles(event_id):
        return {(r["kb"], r["title"]) for r in conn.execute(
            "SELECT json_extract(fields_json, '$.kb') AS kb, title FROM observations "
            "WHERE event_id = ? AND external_key LIKE 'kbki:%'", (event_id,))}

    dups = conn.execute("SELECT title, COUNT(*) FROM events WHERE kind = 'issue' GROUP BY title HAVING COUNT(*) > 1").fetchall()
    assert not dups, [tuple(r) for r in dups]
    assert conn.execute("SELECT COUNT(*) FROM observations WHERE event_id IS NULL").fetchone()[0] == 0

    # RDS: Release health + Windows 11, Server 2025 ve Server 2022 KB makaleleri (üç farklı KB) → tek olay
    rds = kb_article_titles(ev("wrh:4981"))
    assert {kb for kb, _ in rds} == {"5124008", "5122871", "5122882"}
    # WSUS sorunu Release health'te yok; Server 2025 ve 2022 makalelerinde aynı başlıkla → tek olay
    wsus = {r["event_id"] for r in conn.execute(
        "SELECT event_id FROM observations WHERE title LIKE 'Windows Server Update Services (WSUS)%'")}
    assert len(wsus) == 1
    # USB ses: KB5129195 "kısmen düzeltir" (Release health); sonraki makaleler kalan belirtiyi farklı başlıkla
    # listeler ("USB Audio Class 1.0 devices with error Code 10 or no output") → Release health olayına katılır.
    usb_id = ev("wrh:4984")
    assert {kb for kb, _ in kb_article_titles(usb_id)} == {"5124008", "5124010", "5129195"}
    state = json.loads(conn.execute("SELECT state_json FROM events WHERE id = ?", (usb_id,)).fetchone()[0])
    assert state["status"] == "mitigated" and not state["fix"]
    assert "5129195" in state["partial_fix_kbs"] and "5129195" not in state["resolving_kbs"]
    # Etki alanı güven ilişkisi: KB5124008, KB5124010 ve KB5129195 makaleleri → Release health 4990
    assert {kb for kb, _ in kb_article_titles(ev("wrh:4990"))} == {"5124008", "5124010", "5129195"}
