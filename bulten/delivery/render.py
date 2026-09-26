"""Bülten → kanal biçimleri (Telegram HTML mesajları ve e-posta HTML/metin)."""
from __future__ import annotations

import html
import sqlite3
from typing import Any

from ..config import load_config
from ..db import jload
from ..pipeline.cards import build_card
from ..settings_store import get_settings
from ..timeutil import fmt_tr, fmt_tr_date
from . import daily_render
from .actions import action_url

RISK_ICON = {"critical": "🟥", "high": "🟧", "medium": "🟨", "low": "🟩"}
EV_ICON = {"ms_known_issue": "✅", "ms_official": "Ⓜ️", "field": "⚠️"}
TG_LIMIT = 4000


def esc(text: Any) -> str:
    return html.escape(str(text or ""), quote=False)


def load_bulletin_cards(conn: sqlite3.Connection, bulletin_id: int) -> tuple[dict, list[dict]]:
    b = conn.execute("SELECT * FROM bulletins WHERE id = ?", (bulletin_id,)).fetchone()
    content = jload(b["content_json"], {})
    sections = []
    for sec in content.get("sections", []):
        cards = []
        for it in sec["items"]:
            card = build_card(conn, it["version_id"], mode=it.get("mode", "full"))
            if card:
                cards.append(card)
        if cards:
            sections.append({"key": sec["key"], "title": sec["title"], "cards": cards})
    return {"row": dict(b), "content": content}, sections


def _times_line(card: dict, tzname: str) -> str:
    parts = []
    if card.get("published_at"):
        parts.append(f"Yayın: {fmt_tr(card['published_at'], tzname)}")
    if card.get("meaningful_update_at"):
        parts.append(f"Anlamlı güncelleme: {fmt_tr(card['meaningful_update_at'], tzname)}")
    if card.get("last_checked_at"):
        parts.append(f"Son kontrol: {fmt_tr(card['last_checked_at'], tzname)}")
    return " · ".join(parts)


# --- Telegram ----------------------------------------------------------------------

def telegram_card(card: dict, tzname: str) -> str:
    lines = []
    icon = RISK_ICON.get(card.get("risk"), "▫️")
    title = esc(card["title"])
    if card["is_demo"]:
        title = "[DEMO] " + title
    lines.append(f"{icon} <b>{title}</b>")
    meta = [card["module_label"], card["kind_label"]] + [b["text"] for b in card["badges"] if b["kind"] != "demo"]
    lines.append("<i>" + esc(" · ".join(meta)) + "</i>")
    scope = []
    if card["kbs"]:
        scope.append(", ".join("KB" + k for k in card["kbs"][:4]))
    if card["products"]:
        scope.append(", ".join(card["products"][:4]))
    if scope:
        lines.append(esc(" · ".join(scope)))
    if card.get("what_changed"):
        lines.append(f"🔄 <b>Ne değişti?</b> {esc(card['what_changed'])}")
    if card.get("summary"):
        lines.append(esc(card["summary"]))
    if card.get("why"):
        lines.append(f"<b>Beni neden ilgilendiriyor?</b> {esc(card['why'])}")
    for a in card.get("actions", [])[:2]:
        lines.append(f"<b>Aksiyon</b> [{esc(a['basis_label'])}]: {esc(a['text'])}")
    link_parts = []
    for ln in card.get("links", [])[:3]:
        if ln.get("url"):
            link_parts.append(f'<a href="{html.escape(ln["url"])}">{esc(ln.get("source") or "Kaynak")}</a>')
    if link_parts:
        lines.append("🔗 " + " · ".join(link_parts))
    t = _times_line(card, tzname)
    if t:
        lines.append(f"🕒 {esc(t)}")
    if not card.get("ai"):
        lines.append("<i>AI özeti yok — şablon özet.</i>")
    text = "\n".join(lines)
    return text[:TG_LIMIT]


def telegram_keyboard(card: dict) -> dict:
    eid, ver = card["event_id"], card["version"]
    row = [{"text": "✅ Okudum", "callback_data": f"r:{eid}:{ver}"},
           {"text": "📌 Takip et" if not card["is_followed"] else "📌 Takipte", "callback_data": f"f:{eid}"},
           {"text": "🔕 Sustur", "callback_data": f"m:{eid}:{ver}"}]
    kb = [row]
    base = load_config().app_base_url
    if base.startswith("https://"):
        kb.append([{"text": "↗ Uygulamada aç", "url": f"{base}/olay/{eid}"}])
    return {"inline_keyboard": kb}


def telegram_bulletin_messages(conn: sqlite3.Connection, bulletin_id: int) -> list[dict]:
    settings = get_settings(conn)
    tzname = settings.get("timezone")
    meta, sections = load_bulletin_cards(conn, bulletin_id)
    content = meta["content"]
    is_demo = bool(meta["row"]["is_demo"])
    head = [f"☀️ <b>{'[DEMO] ' if is_demo else ''}Sabah Bülteni — {esc(fmt_tr_date(content['date']))}</b>"]
    counts = [f"{s['title']}: {len(s['cards'])}" for s in sections]
    if counts:
        head.append(esc(" · ".join(counts)))
    else:
        head.append("Son bültenden bu yana seçili modüllerde yeni gelişme yok.")
    if content.get("baseline"):
        head.append("ℹ️ İlk bülten: eski arşiv gönderilmedi; yalnızca açık kritik sorunlardan başlangıç özeti var.")
    cov = content.get("coverage") or {}
    if cov.get("failing"):
        names = ", ".join(f["name"] for f in cov["failing"][:4])
        more = f" (+{len(cov['failing']) - 4})" if len(cov["failing"]) > 4 else ""
        head.append(f"⚠️ Erişilemeyen/okunamayan kaynaklar: {esc(names)}{more}. Bu kaynaklarda yeni sorun olmadığı anlamına gelmez.")
    if content.get("overflow"):
        head.append(f"📦 {content['overflow']} gelişme bülten sınırına sığmadı; arşivde okunmamış duruyor.")
    trk = content.get("tracking") or {}
    if trk.get("open_count"):
        head.append(f"📌 Takipteki çözülmemiş riskler: {trk['open_count']}")
    for block in daily_render.telegram_blocks(conn, content.get("daily") or {}, tzname):
        head.append(block)
    base = load_config().app_base_url
    if base.startswith("https://"):
        head.append(f'<a href="{html.escape(base)}/">Uygulamada aç</a>')
    msgs = [{"text": "\n\n".join(head)[:TG_LIMIT], "reply_markup": None, "silent": False}]
    for sec in sections:
        if sec["key"] == "gece":
            lines = [f"🌙 <b>{esc(sec['title'])}</b> (değişmediği için tekrar edilmedi)"]
            for c in sec["cards"]:
                lines.append(f"• {esc(c['title'])}")
            msgs.append({"text": "\n".join(lines)[:TG_LIMIT], "reply_markup": None, "silent": True})
            continue
        if sec["key"].startswith("news_") or sec["key"] == "content":
            lines = [f"📰 <b>{esc(sec['title'])}</b>"]
            for i, c in enumerate(sec["cards"], 1):
                link = c.get("primary_url")
                t = f'<a href="{html.escape(link)}">{esc(c["title"])}</a>' if link else esc(c["title"])
                src = ", ".join(sorted({ln.get("source") for ln in c.get("links", []) if ln.get("source")}))
                lines.append(f"{i}. {t}\n{esc(c['summary'][:260])}" + (f"\n<i>{esc(src)}</i>" if src else ""))
            kb = {"inline_keyboard": [[{"text": "✅ Hepsini okudum", "callback_data": f"rb:{bulletin_id}:{sec['key']}"}]]}
            msgs.append({"text": "\n\n".join(lines)[:TG_LIMIT], "reply_markup": kb, "silent": True})
            continue
        msgs.append({"text": f"— <b>{esc(sec['title'])}</b> —", "reply_markup": None, "silent": True})
        for c in sec["cards"]:
            msgs.append({"text": telegram_card(c, tzname), "reply_markup": telegram_keyboard(c), "silent": True,
                         "event_id": c["event_id"], "version_id": c["version_id"]})
    return msgs


def telegram_alert_messages(conn: sqlite3.Connection, version_ids: list[int]) -> list[dict]:
    settings = get_settings(conn)
    tzname = settings.get("timezone")
    msgs = []
    for vid in version_ids:
        c = build_card(conn, vid)
        if not c:
            continue
        text = "🚨 <b>Kritik alarm</b>\n" + telegram_card(c, tzname)
        msgs.append({"text": text[:TG_LIMIT], "reply_markup": telegram_keyboard(c), "silent": False,
                     "event_id": c["event_id"], "version_id": vid})
    return msgs


# --- E-posta -------------------------------------------------------------------------

EMAIL_CSS = """
body{margin:0;background:#f4f5f7;font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#1d2330}
.wrap{max-width:680px;margin:0 auto;padding:16px}
h1{font-size:20px;margin:8px 0 4px} h2{font-size:15px;margin:22px 0 8px;color:#39465c;text-transform:uppercase;letter-spacing:.03em}
.card{background:#fff;border-radius:10px;padding:14px 16px;margin:0 0 12px;border:1px solid #e2e5ea}
.card h3{font-size:16px;margin:0 0 6px}
.meta{font-size:12px;color:#5b6475;margin:0 0 8px}
.badge{display:inline-block;font-size:11px;padding:2px 7px;border-radius:9px;background:#eef1f5;margin:0 4px 4px 0}
.risk-critical{background:#fde2e1;color:#8a1c16}.risk-high{background:#ffe8d1;color:#8a4a00}
.ev-field{background:#fff4cc;color:#6b5200}.ev-ms_known_issue{background:#dff3e4;color:#11622b}.demo{background:#333;color:#fff}
p{margin:6px 0;font-size:14px;line-height:1.45}.small{font-size:12px;color:#5b6475}
a.btn{display:inline-block;font-size:12px;padding:5px 10px;border:1px solid #c6ccd6;border-radius:6px;color:#1d2330;text-decoration:none;margin:6px 6px 0 0}
.note{background:#fff8e1;border-radius:8px;padding:8px 12px;font-size:13px}
"""


def email_card_html(card: dict, tzname: str) -> str:
    badges = "".join(f'<span class="badge {esc(b["kind"])}">{esc(b["text"])}</span>' for b in card["badges"])
    parts = [f'<div class="card"><h3>{esc(card["title"])}</h3>',
             f'<div class="meta">{esc(card["module_label"])} · {esc(card["kind_label"])}'
             + (f' · {esc(", ".join("KB" + k for k in card["kbs"][:4]))}' if card["kbs"] else "")
             + (f' · {esc(", ".join(card["products"][:4]))}' if card["products"] else "") + "</div>", badges]
    if card.get("what_changed"):
        parts.append(f"<p><b>Ne değişti?</b> {esc(card['what_changed'])}</p>")
    parts.append(f"<p>{esc(card['summary'])}</p>")
    if card.get("why"):
        parts.append(f"<p><b>Beni neden ilgilendiriyor?</b> {esc(card['why'])}</p>")
    for a in card.get("actions", [])[:3]:
        parts.append(f"<p><b>Aksiyon</b> <span class='badge'>{esc(a['basis_label'])}</span> {esc(a['text'])}</p>")
    links = " · ".join(f'<a href="{html.escape(ln["url"])}">{esc(ln.get("source") or "Kaynak")}</a>'
                       for ln in card.get("links", [])[:4] if ln.get("url"))
    if links:
        parts.append(f'<p class="small">Kaynak: {links}</p>')
    parts.append(f'<p class="small">{esc(_times_line(card, tzname))}'
                 + ("" if card.get("ai") else " · AI özeti yok (şablon)") + "</p>")
    eid, ver = card["event_id"], card["version"]
    parts.append(f'<a class="btn" href="{action_url(eid, ver, "read")}">Okudum</a>'
                 f'<a class="btn" href="{action_url(eid, ver, "follow")}">Takip et</a>'
                 f'<a class="btn" href="{action_url(eid, ver, "mute")}">Sustur</a>')
    parts.append("</div>")
    return "".join(parts)


def email_bulletin(conn: sqlite3.Connection, bulletin_id: int) -> dict:
    settings = get_settings(conn)
    tzname = settings.get("timezone")
    meta, sections = load_bulletin_cards(conn, bulletin_id)
    content = meta["content"]
    demo = "[DEMO] " if meta["row"]["is_demo"] else ""
    subject = f"{demo}Sabah Bülteni — {fmt_tr_date(content['date'])}"
    crit = next((s for s in sections if s["key"] in ("kritik", "baslangic")), None)
    if crit:
        subject += f" · {len(crit['cards'])} kritik"
    body = [f'<div class="wrap"><h1>{esc(subject)}</h1>']
    if content.get("baseline"):
        body.append('<p class="note">İlk bülten: eski arşiv gönderilmedi; yalnızca açık kritik sorunlardan başlangıç özeti var.</p>')
    cov = content.get("coverage") or {}
    if cov.get("failing"):
        body.append('<p class="note">Erişilemeyen/okunamayan kaynaklar: ' +
                    esc(", ".join(f["name"] for f in cov["failing"])) +
                    ". Bu kaynaklarda yeni sorun olmadığı anlamına gelmez.</p>")
    body.append(daily_render.email_html(conn, content.get("daily") or {}, tzname))
    text_lines = [subject, ""]
    for sec in sections:
        body.append(f"<h2>{esc(sec['title'])}</h2>")
        text_lines.append(f"== {sec['title']} ==")
        for c in sec["cards"]:
            if sec["key"] == "gece":
                body.append(f'<p>• {esc(c["title"])} <span class="small">(gece bildirildi, değişmedi)</span></p>')
            else:
                body.append(email_card_html(c, tzname))
            text_lines.append(f"- {c['title']}\n  {c['summary']}\n  {c.get('primary_url') or ''}")
    if not sections:
        body.append("<p>Son bültenden bu yana seçili modüllerde yeni gelişme yok.</p>")
    base = load_config().app_base_url
    body.append(f'<p class="small">Uygulama: <a href="{html.escape(base)}/">{esc(base)}</a> · '
                f'{esc(cov.get("scope_note", ""))}</p></div>')
    html_doc = f"<!doctype html><html><head><meta charset='utf-8'><style>{EMAIL_CSS}</style></head><body>{''.join(body)}</body></html>"
    return {"subject": subject, "html": html_doc, "text": "\n".join(text_lines)}


def email_alert(conn: sqlite3.Connection, version_ids: list[int]) -> dict:
    settings = get_settings(conn)
    tzname = settings.get("timezone")
    cards = [c for c in (build_card(conn, v) for v in version_ids) if c]
    subject = "Kritik alarm: " + (cards[0]["title"] if len(cards) == 1 else f"{len(cards)} gelişme")
    body = "".join(email_card_html(c, tzname) for c in cards)
    html_doc = (f"<!doctype html><html><head><meta charset='utf-8'><style>{EMAIL_CSS}</style></head><body>"
                f"<div class='wrap'><h1>{esc(subject)}</h1>{body}</div></body></html>")
    text = "\n\n".join(f"{c['title']}\n{c['summary']}\n{c.get('primary_url') or ''}" for c in cards)
    return {"subject": subject[:200], "html": html_doc, "text": text}
