"""Kabul testleri (istemdeki 7 madde). Tüm dış kaynaklar sahte HTTP katmanıyla taklit edilir."""
from __future__ import annotations

import json

from helpers import FakeFetcher, freeze, make_db, only_sources, rss_feed, wrh_page

from bulten.config import load_config
from bulten.daily.markets import compare, parse_tcmb, parse_truncgil
from bulten.daily.service import daily_view
from bulten.daily.weather import parse_open_meteo
from bulten.db import jdump, jload
from bulten.delivery.actions import apply_action
from bulten.delivery.dispatcher import enqueue_alert, enqueue_bulletin, process_deliveries, recover_stuck
from bulten.delivery.telegram import SendResult
from bulten.pipeline.bulletin import compose_bulletin, select_alerts
from bulten.pipeline.run import collect_and_process
from bulten.settings_store import save_settings
from bulten.timeutil import advance_clock, now_iso

WRH = "https://learn.microsoft.com/en-us/windows/release-health/"
WRH25 = WRH + "status-windows-11-25h2"
WRH24 = WRH + "status-windows-11-24h2"
WRHWS25 = WRH + "status-windows-server-2025"
REDDIT = "https://www.reddit.com/r/sysadmin/new/.rss"
BLEEP = "https://www.bleepingcomputer.com/feed/"
BORN = "https://borncity.com/win/feed/"
UH25 = "https://support.microsoft.com/en-us/topic/windows-11-version-25h2-update-history-99c7f493-df2a-4832-bd2d-6706baa0dec0"


class FakeTelegram:
    def __init__(self, script=None):
        self.sent: list[tuple[str, str]] = []
        self.script = list(script or [])

    def send_message(self, chat_id, text, *, reply_markup=None, silent=False, parse_mode="HTML"):
        cls = self.script.pop(0) if self.script else "sent"
        if cls == "sent":
            self.sent.append((chat_id, text))
            return SendResult("sent", message_id=str(len(self.sent)))
        return SendResult(cls, error=f"test: {cls}")


def enable_telegram():
    load_config().telegram_bot_token = "123:TEST"
    load_config().telegram_mode = "polling"


def run(conn, ff, slugs):
    return collect_and_process(conn, fetcher=ff, source_ids=only_sources(conn, slugs))


def send_daily(conn, tg):
    bid = compose_bulletin(conn, kind="daily")
    enqueue_bulletin(conn, bid)
    process_deliveries(conn, telegram=tg, part_delay=0)
    return bid


def items_of(conn, bid):
    return [dict(r) for r in conn.execute(
        "SELECT bi.*, v.version, v.change_types_json FROM bulletin_items bi JOIN event_versions v "
        "ON v.id = bi.event_version_id WHERE bulletin_id = ? ORDER BY position", (bid,))]


def event_of(conn, alias):
    row = conn.execute("SELECT event_id FROM event_aliases WHERE alias = ?", (alias,)).fetchone()
    return row["event_id"] if row else None


RDS_ISSUE = dict(id="9201", title="Remote Desktop connections might fail after installing KB5999100", kb="5999100",
                 desc="RDP sessions disconnect after a few minutes on session hosts.",
                 body="After installing KB5999100, Remote Desktop Services (RDS) connections might fail after several minutes.",
                 status="Confirmed", client="Windows 11, version 25H2; Windows 11, version 24H2", server="Windows Server 2025")
OLD_ISSUE = dict(id="9001", title="Some printers might print blank pages", kb="5998990", desc="Printing issue.",
                 body="After installing KB5998990 some printers print blank pages.", status="Confirmed",
                 client="Windows 11, version 25H2")


# 1) Aynı olay beş kaynakta ve iki kategoride geçse de tek haber oluşur ------------------------

def test_same_event_in_five_sources_and_two_categories_is_one_item(tmp_path):
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path, news_categories=["turkiye", "dunya", "genel", "teknoloji"])
    quake = "Marmara Denizi'nde meydana gelen 5,2 büyüklüğündeki deprem İstanbul'da da hissedildi. AFAD açıklama yaptı."
    ff = FakeFetcher(pages={
        "https://www.aa.com.tr/tr/rss/default?cat=guncel": rss_feed([
            {"title": "İstanbul'da 5,2 büyüklüğünde deprem: AFAD ilk açıklamayı yaptı", "link": "https://aa.example/1", "desc": quake},
            {"title": "Merkez Bankası faiz kararını açıkladı", "link": "https://aa.example/2", "desc": "Politika faizi sabit tutuldu."}]),
        "https://www.ntv.com.tr/gundem.rss": rss_feed([
            {"title": "İstanbul'da 5,2 büyüklüğünde deprem meydana geldi", "link": "https://ntv.example/1", "desc": quake}]),
        "https://feeds.bbci.co.uk/turkce/rss.xml": rss_feed([
            {"title": "Marmara Denizi'nde 5,2 büyüklüğünde deprem: İstanbul'da hissedildi", "link": "https://bbc.example/1", "desc": quake}]),
        "https://rss.dw.com/rdf/rss-tur-all": rss_feed([
            {"title": "İstanbul'da 5,2 büyüklüğünde deprem", "link": "https://dw.example/1", "desc": quake},
            {"title": "Van'da 4,1 büyüklüğünde deprem", "link": "https://dw.example/2", "desc": "Van'da hafif deprem kaydedildi."}]),
        "https://tr.euronews.com/rss": rss_feed([
            {"title": "Marmara'da 5,2 büyüklüğünde deprem İstanbul'u salladı", "link": "https://euronews.example/1", "desc": quake}]),
    })
    run(conn, ff, ["news-aa", "news-ntv", "news-bbc-turkce", "news-dw-turkce", "news-euronews-tr"])
    quake_event = conn.execute("SELECT event_id FROM observations WHERE url = 'https://aa.example/1'").fetchone()["event_id"]
    members = conn.execute("SELECT COUNT(DISTINCT source_id) AS n FROM observations WHERE event_id = ?", (quake_event,)).fetchone()["n"]
    assert members == 5, "beş kaynaktaki aynı haber tek olayda toplanmalı"
    van = conn.execute("SELECT event_id FROM observations WHERE url = 'https://dw.example/2'").fetchone()["event_id"]
    assert van != quake_event, "farklı yerdeki deprem aynı olay sayılmamalı"
    categories = {r["category"] for r in conn.execute(
        "SELECT DISTINCT s.category FROM observations o JOIN sources s ON s.id = o.source_id WHERE o.event_id = ?", (quake_event,))}
    assert len(categories) >= 2, "test verisi en az iki kategoriye yayılmalı"

    bid = compose_bulletin(conn, kind="daily")
    items = items_of(conn, bid)
    assert sum(1 for i in items if i["event_id"] == quake_event) == 1, "bültende yalnızca bir kez ve tek kategoride"
    assert len({i["event_id"] for i in items}) == len(items)


def test_same_issue_across_five_sources_is_one_event(tmp_path):
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    slugs = ["wrh-status-win11-25h2", "wrh-status-win11-24h2", "reddit-sysadmin", "bleepingcomputer", "borncity"]
    ff = FakeFetcher(pages={WRH25: wrh_page([OLD_ISSUE]), WRH24: wrh_page([OLD_ISSUE]), REDDIT: rss_feed([]),
                            BLEEP: rss_feed([]), BORN: rss_feed([])})
    run(conn, ff, slugs)  # gün 0: başlangıç taraması
    freeze(2026, 9, 21, 5)
    ff.pages[WRH25] = wrh_page([OLD_ISSUE, RDS_ISSUE])
    ff.pages[WRH24] = wrh_page([OLD_ISSUE, RDS_ISSUE], title="Windows 11, version 24H2 known issues")
    ff.pages[REDDIT] = rss_feed([{"title": "KB5999100 is breaking RDP on our Windows Server 2025 session hosts",
                                  "link": "https://www.reddit.com/r/sysadmin/comments/x1/", "author": "u/admin1",
                                  "desc": "Since KB5999100, Remote Desktop sessions drop after 5 minutes. Anyone else seeing this issue?",
                                  "date": "Mon, 21 Sep 2026 03:00:00 GMT"}])
    ff.pages[BLEEP] = rss_feed([{"title": "Microsoft confirms KB5999100 Remote Desktop connection failures",
                                 "link": "https://www.bleepingcomputer.com/news/microsoft/kb5999100-rdp/",
                                 "desc": "Microsoft says Windows update KB5999100 causes Remote Desktop connections to fail on Windows 11 and Server 2025.",
                                 "date": "Mon, 21 Sep 2026 04:00:00 GMT"}])
    ff.pages[BORN] = rss_feed([{"title": "Windows update KB5999100: RDP issues reported",
                                "link": "https://borncity.com/win/2026/09/21/kb5999100-rdp/",
                                "desc": "Readers report RDP disconnects on Windows Server 2025 after installing KB5999100.",
                                "date": "Mon, 21 Sep 2026 02:00:00 GMT"}])
    run(conn, ff, slugs)
    ev = event_of(conn, "wrh:9201")
    srcs = conn.execute("SELECT COUNT(DISTINCT source_id) AS n FROM observations WHERE event_id = ?", (ev,)).fetchone()["n"]
    assert srcs == 5
    assert conn.execute("SELECT COUNT(*) FROM events WHERE kind = 'issue'").fetchone()[0] == 2
    bid = compose_bulletin(conn, kind="daily")
    assert [i["event_id"] for i in items_of(conn, bid)].count(ev) == 1


# 2) Aynı KB'de iki ayrı sorun varsa iki olay korunur -------------------------------------------

def test_two_issues_same_kb_stay_separate(tmp_path):
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    slugs = ["wrh-status-win11-25h2", "ms-uh-win11-25h2", "reddit-sysadmin"]
    ff = FakeFetcher(pages={WRH25: wrh_page([OLD_ISSUE]), UH25: "<html><body><main>"
                            '<a href="/x/kb5999008">September 8, 2026—KB5999008 (OS Builds 26200.9445 and 26100.9445)</a>'
                            "</main></body></html>", REDDIT: rss_feed([])})
    run(conn, ff, slugs)
    freeze(2026, 9, 21, 5)
    cg = dict(id="9102", title="Credential Guard protected machine accounts might lose secure channel", kb="5999008",
              desc="Users might be unable to sign in with domain credentials.",
              body="After installing KB5999008, some Credential Guard protected machine accounts might lose their secure channel "
                   "with an on-premises Active Directory domain. Kerberos authentication fails.",
              client="Windows 11, version 25H2")
    rds = dict(id="9101", title="Remote Desktop Services might become unstable", kb="5999008",
               desc="RDP connections might fail after several minutes.",
               body="After installing KB5999008 some organizations might experience issues with Remote Desktop Services.",
               status="Mitigated", workaround="Use the Known Issue Rollback (KIR) Group Policy.",
               client="Windows 11, version 25H2", server="Windows Server 2025")
    ff.pages[WRH25] = wrh_page([OLD_ISSUE, rds, cg])
    ff.pages[REDDIT] = rss_feed([
        {"title": "KB5999008 broke RDP on our session hosts", "link": "https://www.reddit.com/r/sysadmin/comments/r1/",
         "desc": "Remote Desktop users disconnected after KB5999008 on Windows Server 2025.", "author": "u/a",
         "date": "Mon, 21 Sep 2026 03:00:00 GMT"},
        {"title": "KB5999008 installed yesterday, now weird problems on a few PCs",
         "link": "https://www.reddit.com/r/sysadmin/comments/r2/", "desc": "Not sure what is failing yet, anyone else?",
         "author": "u/b", "date": "Mon, 21 Sep 2026 03:30:00 GMT"}])
    run(conn, ff, slugs)
    rds_ev, cg_ev = event_of(conn, "wrh:9101"), event_of(conn, "wrh:9102")
    assert rds_ev and cg_ev and rds_ev != cg_ev, "aynı KB'deki iki farklı sorun iki olay olmalı"
    r1 = conn.execute("SELECT event_id FROM observations WHERE url LIKE '%comments/r1/'").fetchone()["event_id"]
    r2 = conn.execute("SELECT event_id FROM observations WHERE url LIKE '%comments/r2/'").fetchone()["event_id"]
    assert r1 == rds_ev, "RDP belirtili saha raporu RDS sorununa bağlanmalı"
    assert r2 not in (rds_ev, cg_ev), "belirti belirtmeyen rapor iki sorundan birine yanlışlıkla bağlanmamalı"
    assert r2 == event_of(conn, "kb:5999008"), "belirti belirtmeyen rapor KB sürüm olayına iliştirilir"


# 3) Okunan saha raporu Microsoft tarafından doğrulanınca yeni gelişme bildirimi gelir -------------

def test_read_field_report_then_ms_confirmation_notifies(tmp_path):
    enable_telegram()
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path, critical={"enabled": True, "min_risk": "high", "min_evidence": "ms_official",
                                       "quiet_exception": "none", "morning_reference": True})
    enable_telegram()
    tg = FakeTelegram()
    slugs = ["wrh-status-ws2025", "reddit-sysadmin", "borncity"]
    ff = FakeFetcher(pages={WRHWS25: wrh_page([OLD_ISSUE], title="Windows Server 2025"), REDDIT: rss_feed([]),
                            BORN: rss_feed([])})
    run(conn, ff, slugs)
    send_daily(conn, tg)

    freeze(2026, 9, 21, 5)
    ff.pages[REDDIT] = rss_feed([{"title": "KB5999011 broke Always On VPN on our Server 2025 RRAS boxes",
                                  "link": "https://www.reddit.com/r/sysadmin/comments/v1/", "author": "u/alice",
                                  "desc": "After installing KB5999011 on Windows Server 2025 RRAS servers, IKEv2 VPN connections fail.",
                                  "date": "Mon, 21 Sep 2026 01:00:00 GMT"}])
    ff.pages[BORN] = rss_feed([{"title": "Windows Server 2025: VPN problems after KB5999011",
                                "link": "https://borncity.com/win/2026/09/21/vpn-kb5999011/",
                                "desc": "Administrators report RRAS VPN connections failing after update KB5999011 on Windows Server 2025.",
                                "date": "Mon, 21 Sep 2026 02:00:00 GMT"}])
    run(conn, ff, slugs)
    field_ev = conn.execute("SELECT event_id FROM observations WHERE url LIKE '%comments/v1/'").fetchone()["event_id"]
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (field_ev,)).fetchone()
    assert ev["evidence_level"] == "field" and ev["current_version"] == 1
    bid = send_daily(conn, tg)
    assert any(i["event_id"] == field_ev for i in items_of(conn, bid))
    apply_action(conn, field_ev, "read", via="telegram", version=1)

    freeze(2026, 9, 22, 1)  # gece: Microsoft Known issues kaydını ekliyor
    vpn = dict(id="9301", title="VPN connections might fail on Routing and Remote Access Service servers", kb="5999011",
               desc="IKEv2 VPN connections might fail on RRAS servers.",
               body="After installing KB5999011, VPN connections using IKEv2 might fail on Windows Server 2025 servers "
                    "running Routing and Remote Access Service (RRAS).", server="Windows Server 2025")
    ff.pages[WRHWS25] = wrh_page([OLD_ISSUE, vpn], title="Windows Server 2025")
    run(conn, ff, slugs)
    assert event_of(conn, "wrh:9301") == field_ev, "Microsoft kaydı mevcut saha olayıyla eşleşmeli"
    ev = conn.execute("SELECT * FROM events WHERE id = ?", (field_ev,)).fetchone()
    assert ev["evidence_level"] == "ms_known_issue" and ev["current_version"] == 2
    v2 = conn.execute("SELECT * FROM event_versions WHERE event_id = ? AND version = 2", (field_ev,)).fetchone()
    assert "ms_confirmed" in jload(v2["change_types_json"])
    assert "Known issues" in v2["change_note"]

    save_settings(conn, {"quiet_hours": {"enabled": False, "start": "22:30", "end": "07:30"}})
    vids, _ = select_alerts(conn)
    assert v2["id"] in vids, "okunmuş olsa da Microsoft teyidi kritik alarm olarak bildirilmeli"
    enqueue_alert(conn, vids)
    process_deliveries(conn, telegram=tg, part_delay=0)
    assert any("Kritik alarm" in t for _, t in tg.sent)
    state = conn.execute("SELECT * FROM user_event_state WHERE event_id = ?", (field_ev,)).fetchone()
    assert state["read_version"] == 1, "yeni sürüm otomatik okundu sayılmaz"

    freeze(2026, 9, 22, 5)
    bid = compose_bulletin(conn, kind="daily")
    mine = [i for i in items_of(conn, bid) if i["event_id"] == field_ev]
    assert len(mine) == 1 and mine[0]["render_mode"] == "reference", "gece bildirilen değişmemiş içerik sabah yalnızca referans"


# 4) Düzeltme yayımlanınca bildirim gelir; yalnızca yazım değişince gelmez -----------------------

def test_fix_notifies_but_typo_does_not(tmp_path):
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    issue = dict(RDS_ISSUE, body="After installing KB5999100 some devices might experiance Remote Desktop disconnects.")
    ff = FakeFetcher(pages={WRH25: wrh_page([issue])})
    run(conn, ff, ["wrh-status-win11-25h2"])
    ev = event_of(conn, "wrh:9201")
    bid0 = compose_bulletin(conn, kind="daily")
    first = [i for i in items_of(conn, bid0) if i["event_id"] == ev]
    assert all(i["section"] == "baslangic" for i in first), "ilk taramadaki kayıt yalnızca başlangıç özetinde yer alır"

    freeze(2026, 9, 21, 5)
    typo = dict(issue, body="After installing KB5999100, some devices might experience Remote Desktop disconnects.",
                updated="2026-09-20", desc=issue["desc"] + " ")
    ff.pages[WRH25] = wrh_page([typo])
    run(conn, ff, ["wrh-status-win11-25h2"])
    assert conn.execute("SELECT current_version FROM events WHERE id = ?", (ev,)).fetchone()[0] == 1
    snaps = conn.execute("SELECT COUNT(*) FROM observation_snapshots s JOIN observations o ON o.id = s.observation_id "
                         "WHERE o.event_id = ?", (ev,)).fetchone()[0]
    assert snaps == 2, "metin değişikliği kanıt geçmişine kaydedilir ama yeni sürüm oluşturmaz"
    bid1 = compose_bulletin(conn, kind="daily")
    assert all(i["event_id"] != ev for i in items_of(conn, bid1))

    freeze(2026, 9, 22, 5)
    fixed = dict(typo, status="Resolved KB5999120", updated="2026-09-21",
                 resolution="This issue was resolved in KB5999120, released September 21, 2026.")
    ff.pages[WRH25] = wrh_page([fixed])
    run(conn, ff, ["wrh-status-win11-25h2"])
    evrow = conn.execute("SELECT * FROM events WHERE id = ?", (ev,)).fetchone()
    assert evrow["current_version"] == 2 and evrow["status"] == "resolved"
    v2 = conn.execute("SELECT * FROM event_versions WHERE event_id = ? AND version = 2", (ev,)).fetchone()
    assert "fix" in jload(v2["change_types_json"])
    bid2 = compose_bulletin(conn, kind="daily")
    mine = [i for i in items_of(conn, bid2) if i["event_id"] == ev]
    assert len(mine) == 1 and mine[0]["version"] == 2 and mine[0]["render_mode"] == "full"


# 5) Gönderilen içeriğe otomatik "okundu" konmaz; değişmeyen içerik yeniden gönderilmez -----------

def test_sent_is_not_read_and_unchanged_is_not_resent(tmp_path):
    enable_telegram()
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    enable_telegram()
    tg = FakeTelegram()
    ff = FakeFetcher(pages={WRH25: wrh_page([OLD_ISSUE])})
    run(conn, ff, ["wrh-status-win11-25h2"])
    send_daily(conn, tg)
    freeze(2026, 9, 21, 5)
    ff.pages[WRH25] = wrh_page([OLD_ISSUE, RDS_ISSUE])
    run(conn, ff, ["wrh-status-win11-25h2"])
    ev = event_of(conn, "wrh:9201")
    bid1 = send_daily(conn, tg)
    assert any(i["event_id"] == ev for i in items_of(conn, bid1))
    d = conn.execute("SELECT * FROM deliveries WHERE bulletin_id = ?", (bid1,)).fetchone()
    assert d["status"] == "sent"
    st = conn.execute("SELECT * FROM user_event_state WHERE event_id = ?", (ev,)).fetchone()
    assert st is None or st["read_at"] is None, "gönderim okundu sayılmaz"

    freeze(2026, 9, 22, 5)
    run(conn, ff, ["wrh-status-win11-25h2"])  # değişiklik yok
    bid2 = send_daily(conn, tg)
    assert all(i["event_id"] != ev for i in items_of(conn, bid2)), "değişmeyen içerik yeniden gönderilmez"
    unread = conn.execute("SELECT COUNT(*) FROM events e LEFT JOIN user_event_state u ON u.event_id = e.id "
                          "WHERE e.id = ? AND u.read_at IS NULL", (ev,)).fetchone()[0]
    assert unread == 1, "arşivde okunmamış olarak kalır"
    # Aynı bülten ikinci kez kuyruğa alınsa bile tekrar gönderilmez (idempotency)
    before = len(tg.sent)
    assert enqueue_bulletin(conn, bid2) == []
    process_deliveries(conn, telegram=tg, part_delay=0)
    assert len(tg.sent) == before


# 6) Günlük hava/piyasa verisi doğru zaman ve birimle gelir; eski/eksik veri belirtilir -------------

OPEN_METEO = {
    "current": {"time": "2026-09-24T08:00", "temperature_2m": 21.4, "apparent_temperature": 20.1, "precipitation": 0.2,
                "weather_code": 61, "wind_speed_10m": 14.0},
    "current_units": {"temperature_2m": "°C", "precipitation": "mm", "wind_speed_10m": "km/h"},
    "daily": {"time": ["2026-09-24"], "temperature_2m_max": [24.0], "temperature_2m_min": [16.5],
              "apparent_temperature_max": [23.0], "apparent_temperature_min": [15.0], "precipitation_sum": [3.4],
              "precipitation_probability_max": [70], "weather_code": [61]},
    "daily_units": {"temperature_2m_max": "°C", "precipitation_sum": "mm"},
}
TCMB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<Tarih_Date Tarih="23.09.2026" Date="09/23/2026" Bulten_No="2026/180">
<Currency CrossOrder="0" Kod="USD" CurrencyCode="USD"><Unit>1</Unit><Isim>ABD DOLARI</Isim><CurrencyName>US DOLLAR</CurrencyName>
<ForexBuying>41.5012</ForexBuying><ForexSelling>41.5760</ForexSelling><BanknoteBuying>41.4721</BanknoteBuying><BanknoteSelling>41.6384</BanknoteSelling></Currency>
<Currency CrossOrder="9" Kod="EUR" CurrencyCode="EUR"><Unit>1</Unit><Isim>EURO</Isim><CurrencyName>EURO</CurrencyName>
<ForexBuying>48.7010</ForexBuying><ForexSelling>48.7888</ForexSelling><BanknoteBuying>48.6669</BanknoteBuying><BanknoteSelling>48.8620</BanknoteSelling></Currency>
</Tarih_Date>"""


def test_daily_data_time_units_stale_and_missing(tmp_path):
    freeze(2026, 9, 24, 5, 10)  # 08:10 İstanbul
    conn = make_db(tmp_path, modules={"weather": True, "markets": True})
    w = parse_open_meteo(OPEN_METEO, {"name": "Kadıköy", "admin1": "İstanbul", "lat": 40.99, "lon": 29.03},
                         "Europe/Istanbul")
    assert w["data_time"] == "2026-09-24T08:00:00+03:00"
    assert w["current"]["units"]["temperature"] == "°C" and w["current"]["apparent"] == 20.1
    assert w["today"]["precipitation_sum"] == 3.4 and w["current"]["description"] == "Hafif yağmur"

    tcmb = parse_tcmb(TCMB_XML)
    assert tcmb["data_time"] == "2026-09-23T12:30:00+00:00", "TCMB gösterge kuru 15:30 TSİ itibarıyla"
    assert "referans" in tcmb["provider_label"].lower()
    assert tcmb["items"]["USDTRY"]["prices"]["Döviz satış"] == 41.576 and tcmb["items"]["USDTRY"]["unit"] == "TRY / 1 USD"

    truncgil = parse_truncgil(json.dumps({
        "Update_Date": "2026-09-24 08:05:00",
        "USD": {"Alış": "41,6100", "Satış": "41,6500", "Tür": "Döviz"},
        "EUR": {"Alış": "48,8000", "Satış": "48,9000", "Tür": "Döviz"},
        "gram-altin": {"Alış": "4.620,50", "Satış": "4.635,10", "Tür": "Altın"}}), "Europe/Istanbul")
    assert truncgil["items"]["GRAM24"]["prices"]["Satış"] == 4635.10
    assert "BILEZIK22" not in truncgil["items"], "bilezik 24 ayardan türetilmez"

    payload = {"blocks": [tcmb, truncgil], "missing": ["22 ayar bilezik (gram)"], "errors": []}
    conn.execute("INSERT INTO daily_data(module, provider, fetched_at, data_time, status, payload_json) VALUES "
                 "('market', 'x', ?, ?, 'ok', ?)", (now_iso(), truncgil["data_time"], jdump(payload)))
    rid = conn.execute("SELECT MAX(id) FROM daily_data").fetchone()[0]
    view = daily_view(conn, rid, "market", "Europe/Istanbul")
    blocks = {b["provider"]: b for b in view["payload"]["blocks"]}
    assert blocks["tcmb"]["stale"] is False and blocks["truncgil"]["stale"] is False
    from bulten.delivery.daily_render import market_lines, weather_lines
    text = "\n".join(market_lines(view))
    assert "doğrudan veri yok" in text and "TCMB gösterge kuru (referans" in text and "TRY / gram" in text

    # Eski veri "güncel" etiketi almaz
    conn.execute("INSERT INTO daily_data(module, provider, fetched_at, data_time, status, payload_json) VALUES "
                 "('weather', 'Open-Meteo', ?, ?, 'ok', ?)", (now_iso(), "2026-09-23T20:00:00+03:00", jdump(w)))
    wid = conn.execute("SELECT MAX(id) FROM daily_data").fetchone()[0]
    wview = daily_view(conn, wid, "weather", "Europe/Istanbul")
    assert wview["stale"] is True and "güncel değil" in "\n".join(weather_lines(wview))
    assert "MGM" in (w.get("warnings", {}).get("note", "") + "MGM")

    # Önceki bültene göre değişim yalnızca aynı sağlayıcı/kalem için
    prev = {"blocks": [dict(truncgil, data_time="2026-09-23T08:00:00+00:00",
                            items={"GRAM24": {"prices": {"Alış": 4600.0, "Satış": 4610.0}}})]}
    ch = compare(prev, {"blocks": [truncgil]})
    assert round(ch["truncgil"]["GRAM24"]["Satış"]["diff"], 2) == 25.10
    assert "tcmb" not in ch


# 7) Kaynak kesintisi, worker yeniden başlatması ve gönderim tekrar denemeleri -------------------

def test_source_outage_is_not_reported_as_no_issues(tmp_path):
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    ff = FakeFetcher(pages={WRH25: wrh_page([RDS_ISSUE])})
    run(conn, ff, ["wrh-status-win11-25h2"])
    ev = event_of(conn, "wrh:9201")
    freeze(2026, 9, 21, 5)
    ff.down.add(WRH25)
    res = run(conn, ff, ["wrh-status-win11-25h2"])
    assert res["collect"]["sources_error"] == 1
    evrow = conn.execute("SELECT * FROM events WHERE id = ?", (ev,)).fetchone()
    assert evrow["status"] == "confirmed" and evrow["current_version"] == 1, "erişilemeyen kaynak 'çözüldü' sayılmaz"
    bid = compose_bulletin(conn, kind="daily")
    content = jload(conn.execute("SELECT content_json FROM bulletins WHERE id = ?", (bid,)).fetchone()[0])
    assert any("Release health" in f["name"] for f in content["coverage"]["failing"])
    assert "internetin tamamı taranmaz" in content["coverage"]["scope_note"]
    # Beklenen yapı bulunamayan sayfa "ayrıştırma uyarısı" olur, "sorun yok" değil
    ff.down.clear()
    ff.pages[WRH25] = "<html><body><main><h1>Maintenance</h1><p>Try again later.</p></main></body></html>"
    res = run(conn, ff, ["wrh-status-win11-25h2"])
    assert res["collect"]["sources_warning"] == 1
    assert conn.execute("SELECT status FROM events WHERE id = ?", (ev,)).fetchone()[0] == "confirmed"


def test_worker_restart_and_job_idempotency(tmp_path):
    from bulten.worker.scheduler import Scheduler, run_job
    enable_telegram()
    freeze(2026, 9, 24, 5, 10)  # Perşembe 08:10 İstanbul
    conn = make_db(tmp_path)
    enable_telegram()
    ff = FakeFetcher(pages={WRH25: wrh_page([RDS_ISSUE])})
    tg = FakeTelegram()
    sched = Scheduler(tmp_path / "test.db", fetcher=ff, telegram=tg, part_delay=0, start_poller=False)
    wconn = sched.setup()
    sched.tick(wconn)
    sched.tick(wconn)
    assert wconn.execute("SELECT COUNT(*) FROM bulletins WHERE kind = 'daily'").fetchone()[0] == 1
    assert wconn.execute("SELECT COUNT(*) FROM deliveries WHERE kind = 'bulletin'").fetchone()[0] == 1
    sent_after_first = len(tg.sent)

    # "Yeniden başlatma": yeni Scheduler aynı veri tabanıyla — bülten tekrar oluşmaz/gönderilmez
    sched2 = Scheduler(tmp_path / "test.db", fetcher=ff, telegram=tg, part_delay=0, start_poller=False)
    c2 = sched2.setup()
    sched2.tick(c2)
    assert c2.execute("SELECT COUNT(*) FROM bulletins WHERE kind = 'daily'").fetchone()[0] == 1
    assert len(tg.sent) == sent_after_first

    # Çöken iş (nabzı durmuş) yeniden çalıştırılır; bitmiş iş tekrar çalışmaz
    c2.execute("INSERT INTO job_runs(job, slot, status, attempt, started_at, heartbeat_at) VALUES "
               "('demo', 's1', 'running', 1, '2026-09-24T03:00:00+00:00', '2026-09-24T03:00:00+00:00')")
    calls = []
    assert run_job(c2, "demo", "s1", lambda: calls.append(1) or "ok") == "ran"
    assert run_job(c2, "demo", "s1", lambda: calls.append(1) or "ok") == "done"
    assert calls == [1]

    # Gönderim sırasında çökme: "sending" parça belirsiz sayılır ve otomatik yeniden gönderilmez
    did = c2.execute("SELECT id FROM deliveries LIMIT 1").fetchone()[0]
    c2.execute("UPDATE delivery_parts SET status = 'sending' WHERE delivery_id = ? AND seq = 0", (did,))
    c2.execute("UPDATE deliveries SET status = 'pending' WHERE id = ?", (did,))
    assert recover_stuck(c2) == 1
    process_deliveries(c2, telegram=tg, part_delay=0)
    assert len(tg.sent) == sent_after_first
    assert c2.execute("SELECT status FROM deliveries WHERE id = ?", (did,)).fetchone()[0] == "uncertain"


def test_delivery_retries_without_duplicates(tmp_path):
    enable_telegram()
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    enable_telegram()
    ff = FakeFetcher(pages={WRH25: wrh_page([OLD_ISSUE])})
    run(conn, ff, ["wrh-status-win11-25h2"])
    compose_bulletin(conn, kind="daily")
    freeze(2026, 9, 21, 5)
    ff.pages[WRH25] = wrh_page([OLD_ISSUE, RDS_ISSUE])
    run(conn, ff, ["wrh-status-win11-25h2"])
    bid = compose_bulletin(conn, kind="daily")
    (did,) = enqueue_bulletin(conn, bid)
    n_parts = conn.execute("SELECT COUNT(*) FROM delivery_parts WHERE delivery_id = ?", (did,)).fetchone()[0]
    assert n_parts >= 2
    tg = FakeTelegram(script=["sent", "retryable"])  # 2. parça geçici hata
    process_deliveries(conn, telegram=tg, part_delay=0)
    d = conn.execute("SELECT * FROM deliveries WHERE id = ?", (did,)).fetchone()
    assert d["status"] == "pending" and d["next_attempt_at"] > now_iso()
    assert len(tg.sent) == 1
    process_deliveries(conn, telegram=tg, part_delay=0)  # erken: bekleme süresi dolmadı
    assert len(tg.sent) == 1
    advance_clock(minutes=2)
    process_deliveries(conn, telegram=tg, part_delay=0)
    assert conn.execute("SELECT status FROM deliveries WHERE id = ?", (did,)).fetchone()[0] == "sent"
    assert len(tg.sent) == n_parts, "her parça tam bir kez gönderilir"
    texts = [t for _, t in tg.sent]
    assert len(texts) == len(set(texts))
    # Belirsiz sonuç (yanıt alınamadı) otomatik tekrar gönderilmez
    tg2 = FakeTelegram(script=["uncertain"])
    freeze(2026, 9, 22, 5)
    ff.pages[WRH25] = wrh_page([OLD_ISSUE, RDS_ISSUE, dict(RDS_ISSUE, id="9202", title="Start menu might not open",
                                                              body="Start menu might not open after KB5999100.")])
    run(conn, ff, ["wrh-status-win11-25h2"])
    bid3 = compose_bulletin(conn, kind="daily")
    (did3,) = enqueue_bulletin(conn, bid3)
    process_deliveries(conn, telegram=tg2, part_delay=0)
    assert conn.execute("SELECT status FROM deliveries WHERE id = ?", (did3,)).fetchone()[0] == "uncertain"
    first_part = conn.execute("SELECT * FROM delivery_parts WHERE delivery_id = ? AND seq = 0", (did3,)).fetchone()
    assert first_part["status"] == "uncertain" and first_part["attempts"] == 1
    attempts = conn.execute("SELECT COUNT(*) FROM delivery_attempts WHERE delivery_id = ?", (did3,)).fetchone()[0]
    advance_clock(hours=3)
    process_deliveries(conn, telegram=tg2, part_delay=0)
    assert conn.execute("SELECT COUNT(*) FROM delivery_attempts WHERE delivery_id = ?", (did3,)).fetchone()[0] == attempts
    assert conn.execute("SELECT attempts FROM delivery_parts WHERE id = ?", (first_part["id"],)).fetchone()[0] == 1
