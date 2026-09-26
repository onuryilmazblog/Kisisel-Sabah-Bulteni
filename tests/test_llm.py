"""LLM katmanı: kanıt doğrulaması, şablon yedeği, bütçe ve diller arası kanonik başlık (sahte sağlayıcı ile)."""
from __future__ import annotations

from helpers import FakeFetcher, freeze, make_db, only_sources, rss_feed, wrh_page

from bulten.config import load_config
from bulten.db import jload
from bulten.llm.base import LLMResult
from bulten.pipeline import canonical as canonical_mod
from bulten.pipeline import summarize as summarize_mod
from bulten.pipeline.run import collect_and_process
from bulten.pipeline.summarize import validate_llm_output

WRH25 = "https://learn.microsoft.com/en-us/windows/release-health/status-windows-11-25h2"


class FakeProvider:
    name = "fake"
    model = "fake-model"

    def __init__(self, responder):
        self.responder = responder
        self.calls = 0

    def generate_json(self, *, system, user, schema, max_tokens=4000):
        self.calls += 1
        return LLMResult(data=self.responder(user), input_tokens=1000, output_tokens=200, model=self.model)


EVIDENCE = [{"title": "RDS unstable", "text": "After installing KB5999008, RDS might become unstable. Workaround: use the KIR Group Policy.",
             "source": "WRH", "trust": "official", "url": "u", "fields": {}}]


def _out(**kw):
    base = {"title_tr": "RDS kararsız hale gelebilir", "summary_tr": "KB5999008 sonrası RDS sorunları.",
            "why_tr": "RDS kullanıyorsunuz.", "what_changed_tr": "", "details_tr": "…", "canonical_title_en": "RDS unstable",
            "actions": []}
    base.update(kw)
    return base


def test_validation_rejects_hallucinated_kb_and_demotes_fake_quotes():
    state = {"originating_kbs": ["5999008"]}
    clean, notes = validate_llm_output(_out(summary_tr="KB5999777 ile düzeltildi."), EVIDENCE, state)
    assert clean is None and "KB5999777" in notes[0]
    clean, notes = validate_llm_output(_out(actions=[
        {"text": "KIR ilkesini uygulayın", "basis": "kaynak", "evidence_quote": "use the KIR Group Policy"},
        {"text": "Sunucuyu yeniden başlatın", "basis": "kaynak", "evidence_quote": "Restart the server immediately"},
    ]), EVIDENCE, state)
    assert clean["actions"][0]["basis"] == "kaynak"
    assert clean["actions"][1]["basis"] == "ai_cikarim" and clean["actions"][1]["evidence_quote"] == ""


def test_summarize_uses_llm_with_budget_and_falls_back(tmp_path, monkeypatch):
    freeze(2026, 9, 20, 5)
    conn = make_db(tmp_path)
    cfg = load_config()
    cfg.llm_max_calls_per_day = 1
    prov = FakeProvider(lambda user: _out(summary_tr="Özet (LLM)."))
    monkeypatch.setattr(summarize_mod, "get_provider", lambda c: prov)
    monkeypatch.setattr(canonical_mod, "get_provider", lambda c: None)
    titles = ["Remote Desktop sessions disconnect", "Domain controllers might fail Kerberos authentication",
              "Start menu might fail to open"]
    issues = [dict(id=str(9000 + i), title=t, kb="5999008", body=f"After installing KB5999008: {t}.", status="Confirmed",
                   client="Windows 11, version 25H2", server="Windows Server 2025") for i, t in enumerate(titles)]
    ff = FakeFetcher(pages={WRH25: wrh_page(issues)})
    collect_and_process(conn, fetcher=ff, source_ids=only_sources(conn, ["wrh-status-win11-25h2"]))
    rows = conn.execute("SELECT summary_status, summary_note FROM event_versions").fetchall()
    statuses = [r["summary_status"] for r in rows]
    assert statuses.count("llm") == 1, "günlük çağrı sınırı: 1"
    assert statuses.count("template") == len(rows) - 1
    assert any("bütçe" in (r["summary_note"] or "").lower() or "sınır" in (r["summary_note"] or "").lower() for r in rows)
    usage = conn.execute("SELECT COUNT(*), SUM(cost_usd) FROM usage_log WHERE kind = 'llm'").fetchone()
    assert usage[0] == 1 and usage[1] > 0


def test_cross_language_news_clustering_with_canonical_titles(tmp_path, monkeypatch):
    freeze(2026, 9, 24, 12)
    conn = make_db(tmp_path, news_categories=["turkiye", "dunya", "genel", "teknoloji"])
    translations = {"AB, Rusya'ya yönelik 20. yaptırım paketini onayladı": "EU approves 20th sanctions package against Russia"}

    def responder(user):
        import json
        data = json.loads(user)
        return {"items": [{"id": h["id"], "en": translations.get(h["text"], h["text"])} for h in data["headlines"]]}

    prov = FakeProvider(responder)
    monkeypatch.setattr(canonical_mod, "get_provider", lambda c: prov)
    monkeypatch.setattr(summarize_mod, "get_provider", lambda c: None)
    ff = FakeFetcher(pages={
        "https://feeds.bbci.co.uk/turkce/rss.xml": rss_feed([
            {"title": "AB, Rusya'ya yönelik 20. yaptırım paketini onayladı", "link": "https://bbc.example/tr1",
             "desc": "Brüksel'de alınan kararla yeni yaptırımlar yürürlüğe giriyor."}]),
        "https://feeds.bbci.co.uk/news/world/rss.xml": rss_feed([
            {"title": "EU approves 20th package of sanctions on Russia", "link": "https://bbc.example/en1",
             "desc": "New sanctions enter into force after decision in Brussels."}]),
    })
    collect_and_process(conn, fetcher=ff, source_ids=only_sources(conn, ["news-bbc-turkce", "news-bbc-world"]))
    ev_tr = conn.execute("SELECT event_id, fields_json FROM observations WHERE url = 'https://bbc.example/tr1'").fetchone()
    ev_en = conn.execute("SELECT event_id FROM observations WHERE url = 'https://bbc.example/en1'").fetchone()
    assert jload(ev_tr["fields_json"])["canonical_title_en"].startswith("EU approves")
    assert ev_tr["event_id"] == ev_en["event_id"], "Türkçe ve İngilizce aynı haber tek olay olmalı"
    assert prov.calls == 1, "başlıklar toplu çevrilir"
