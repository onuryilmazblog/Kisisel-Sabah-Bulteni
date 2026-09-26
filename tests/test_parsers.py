"""Ayrıştırıcı birim testleri. memdocs örnekleri gerçek Microsoft belgeleridir; ms/ örnekleri elle hazırlanmıştır."""
from __future__ import annotations

from helpers import FIXTURES, freeze

from bulten.daily.calendar_ics import parse_ics_today
from bulten.daily.markets import parse_tr_number
from bulten.sources.base import SourceRow
from bulten.sources.configmgr import (
    classify_hotfix, parse_cm_release_notes_md, parse_cm_tp_md, parse_cm_versions_md, parse_hotfix_detail_md,
    parse_hotfix_toc,
)
from bulten.sources.intune import parse_intune_html, parse_intune_markdown
from bulten.sources.ms_support import classify_release, parse_kb_article, parse_update_history
from bulten.sources.rss import parse_feed
from bulten.sources.wrh import normalize_status, parse_wrh_page
from bulten.timeutil import parse_loose_date
from helpers import rss_feed

MS = FIXTURES / "ms"
MD = FIXTURES / "memdocs"


def test_wrh_status_page():
    r = parse_wrh_page((MS / "wrh-status-25h2.html").read_text(), page_url="u", page_products=["win11-25h2"], section="active")
    assert r.structure_ok and not r.warnings
    by = {o.external_key: o for o in r.observations}
    rds, cg, audio = by["wrh:9101"], by["wrh:9102"], by["wrh:9050"]
    assert rds.fields["status"] == "mitigated" and rds.fields["kir"] and "Known Issue Rollback" in rds.fields["workaround"]
    assert set(rds.fields["products"]) == {"win11-25h2", "win11-24h2", "ws2025"}
    assert "rds" in rds.fields["tags"] and rds.fields["originating_kbs"] == ["5999008"]
    assert cg.fields["status"] == "confirmed" and cg.fields["workaround"] == "" and "dc" in cg.fields["tags"]
    assert cg.fields["resolution"] == "", "'a resolution' cümlesi Resolution etiketi sayılmamalı"
    assert audio.fields["status"] == "resolved" and audio.fields["resolving_kbs"] == ["5999020"]
    assert rds.published_at.startswith("2026-09-10") and audio.source_updated_at.startswith("2026-09-14")


def test_wrh_variant_structure_and_unknown_page():
    r = parse_wrh_page((MS / "wrh-status-ws2025-variant.html").read_text(), page_url="u", page_products=["ws2025"], section="active")
    (o,) = r.observations
    assert o.external_key == "wrh:9101" and o.fields["kir"] and o.fields["affected_platforms"] == {"server": "Windows Server 2025"}
    r2 = parse_wrh_page("<html><body><main><h1>Hata</h1></main></body></html>", page_url="u", page_products=[], section="active")
    assert not r2.structure_ok and r2.warnings


def test_status_normalization():
    assert normalize_status("Resolved KB5999020") == "resolved"
    assert normalize_status("Mitigated External") == "mitigated_external"
    assert normalize_status("Investigating") == "investigating"


def test_update_history_release_types():
    freeze(2026, 9, 26, 5)
    r = parse_update_history((MS / "update-history-25h2.html").read_text(), page_url="https://support.microsoft.com/x",
                             page_products=["win11-25h2"])
    types = {o.fields["kb"]: o.fields["release_type"] for o in r.observations}
    assert types == {"5999030": "preview", "5999020": "oob", "5999008": "security", "5999001": "preview",
                     "5998990": "security"}, "4 aydan eski KB'ler alınmaz"
    assert classify_release("August 11, 2026—Hotpatch KB5120228 (OS Build 26100.33222)", True,
                            parse_loose_date("August 11, 2026")) == "hotpatch"


def test_kb_article_known_issues():
    r = parse_kb_article((MS / "kb5999008.html").read_text(), kb="5999008", page_url="u", page_products=["win11-25h2"])
    assert len(r.observations) == 2
    assert all(o.fields["originating_kbs"] == ["5999008"] for o in r.observations)
    r2 = parse_kb_article((MS / "kb5999030-noissues.html").read_text(), kb="5999030", page_url="u", page_products=[])
    assert r2.structure_ok and r2.observations == []


def test_intune_real_markdown():
    r = parse_intune_markdown((MD / "intune-whats-new.md").read_text(), page="whats_new", page_url="https://learn/x")
    assert len(r.observations) > 20
    first = r.observations[0]
    assert first.external_key == "intune:wi:9052232" and first.fields["service_release"] == "2608"
    assert first.fields["week"] == "August 25, 2026" and first.fields["stage"] == "ga"
    assert "windows" in first.fields["platforms"]
    dev = parse_intune_markdown((MD / "intune-in-development.md").read_text(), page="in_development", page_url="u")
    assert dev.observations and all(o.fields["stage"] == "in_development" for o in dev.observations)
    notes = parse_intune_markdown((MD / "intune-notices.md").read_text(), page="notices", page_url="u")
    assert notes.observations[0].fields["admin_action"].startswith("Check your Intune reporting")
    md = "## Week of September 1, 2026\n\n### Device security\n\n#### New thing (preview)<!-- 123456 -->\n\nNow in public preview.\n"
    (o,) = parse_intune_markdown(md, page="whats_new", page_url="u").observations
    assert o.fields["stage"] == "public_preview"


def test_intune_html_fallback():
    html = ("<html><body><main><h2>Week of August 25, 2026 (Service release 2608)</h2><h3>App management</h3>"
            "<h4>Newly available protected apps</h4><p>The following apps are available.</p>"
            "<div class='checklist'><ul><li>iOS/iPadOS</li></ul></div><h2>Notices</h2><h3>Plan for change: X</h3>"
            "<p>How can you prepare? Update apps.</p></main></body></html>")
    r = parse_intune_html(html, page="whats_new", page_url="u")
    assert [o.title for o in r.observations] == ["Newly available protected apps"]
    assert r.observations[0].external_key.startswith("intune:t:")
    n = parse_intune_html(html, page="notices", page_url="u")
    assert [o.title for o in n.observations] == ["Plan for change: X"]


def test_configmgr_real_docs():
    freeze(2026, 9, 26, 5)
    v = parse_cm_versions_md((MD / "cm-updates.md").read_text(), page_url="u")
    vers = {o.fields["version"]: o.fields for o in v.observations}
    assert set(vers) == {"2603", "2509", "2503"}
    assert vers["2503"]["support_end"].startswith("2026-09-30") and vers["2503"]["support_days_left"] == 3
    toc = parse_hotfix_toc((MD / "cm-hotfix-toc.yml").read_text())
    kb = {e["kb"]: e for e in toc}
    assert kb["37864969"]["versions"] == ["2509"] and set(kb["33247081"]["versions"]) >= {"2603", "2509"}
    assert classify_hotfix("KB 32480179 Configuration Manager 2503 early update ring") == "early_ring"
    assert classify_hotfix("KB 37864969 Second update rollup for Configuration Manager version 2509") == "rollup"
    d = parse_hotfix_detail_md((MD / "cm-hotfix-37864969.md").read_text())
    assert len(d["fixed_issues"]) >= 5 and d["date"].startswith("2026-05-27")
    rn = parse_cm_release_notes_md((MD / "cm-release-notes.md").read_text(), page_url="u")
    assert rn.observations and rn.observations[0].fields["versions"] == ["2403"]
    tp = parse_cm_tp_md((MD / "cm-technical-preview.md").read_text(), page_url="u")
    assert tp.observations[0].external_key == "cm:tp:2411" and tp.observations[0].fields["track"] == "tp"


def _src(module="community", trust="community"):
    return SourceRow(id=1, slug="s", name="Src", module=module, adapter="rss", url="u", fetch_url=None,
                     fallback_url=None, trust=trust, category="teknoloji" if module == "news" else None,
                     product_ids=[], config={})


def test_rss_community_filters_to_tracked_issue_reports():
    freeze(2026, 9, 24, 12)
    feed = rss_feed([
        {"title": "KB5999100 broke RDP on Server 2025", "link": "https://www.reddit.com/r/sysadmin/1",
         "desc": "Remote desktop fails after update."},
        {"title": "Which monitor should I buy?", "link": "https://www.reddit.com/r/sysadmin/2", "desc": "Advice please"},
        {"title": "Windows 11 tips thread", "link": "https://www.reddit.com/r/sysadmin/3", "desc": "Share your tips"},
    ])
    r = parse_feed(feed, source=_src())
    assert [o.title for o in r.observations] == ["KB5999100 broke RDP on Server 2025"]
    o = r.observations[0]
    assert o.kind == "field_report" and o.fields["kbs"] == ["5999100"] and "rds" in o.fields["tags"]
    news = parse_feed(feed, source=_src("news", "press"))
    assert len(news.observations) == 3 and all(o.kind == "article" for o in news.observations)


def test_turkish_numbers_and_ics():
    assert parse_tr_number("4.615,10") == 4615.10
    assert parse_tr_number("41,6500") == 41.65
    assert parse_tr_number("%0,12") == 0.12
    freeze(2026, 9, 24, 5)
    ics = ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:test\r\nBEGIN:VEVENT\r\nUID:1\r\nDTSTART:20260924T070000Z\r\n"
           "DTEND:20260924T080000Z\r\nSUMMARY:CAB toplantısı\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:2\r\n"
           "DTSTART;VALUE=DATE:20260924\r\nSUMMARY:Bakım günü\r\nEND:VEVENT\r\nBEGIN:VEVENT\r\nUID:3\r\n"
           "DTSTART:20260925T070000Z\r\nSUMMARY:Yarın\r\nEND:VEVENT\r\nEND:VCALENDAR\r\n")
    evs = parse_ics_today(ics, "Europe/Istanbul")
    assert [e["summary"] for e in evs] == ["Bakım günü", "CAB toplantısı"]
    assert evs[1]["start_local"] == "10:00"


def test_geocode_ranking_real_response():
    """Gerçek Open-Meteo yanıtı: "Kadıköy" aramasında İstanbul Kadıköy API sırasında 10. sıradan sonra gelir."""
    import json

    from bulten.daily.weather import rank_places

    data = json.loads((FIXTURES / "geocode-kadikoy.json").read_text())
    api_top10 = [(r["name"], r["admin1"]) for r in data["results"][:10]]
    assert ("Kadıköy", "İstanbul") not in api_top10
    ranked = rank_places(data["results"], "Kadıköy")
    assert (ranked[0]["name"], ranked[0]["admin2"], ranked[0]["admin1"]) == ("Kadıköy", "Kadıköy", "İstanbul")
    assert all(p["name"] == "Kadıköy" for p in ranked[:5]), "adı eşleşmeyen yer (Babadağ) öne geçmemeli"
    only_ist = rank_places(data["results"], "Kadıköy", "istanbul")
    assert {p["admin1"] for p in only_ist} == {"İstanbul"} and len(only_ist) == 2
