"""Adım 3: Olay eşleştirme.

Yalnızca URL veya başlığa göre eleme yapılmaz. Sıra:
1. Güçlü anahtar (alias): Release health sorun kimliği, KB numarası, Intune iş öğesi kimliği,
   ConfigMgr KB'si, kanonik URL.
2. Türüne göre bulanık eşleştirme:
   - Resmî bilinen sorun ↔ mevcut sorun olayı (saha kaynaklı olanlar dahil): ortak KB/ürün +
     başlık benzerliği + belirti etiketlerinin uyumu. Aynı KB'de belirtileri farklı iki sorun
     BİRLEŞTİRİLMEZ (özgül belirti etiketleri ayrışıyorsa eşleşme reddedilir).
   - Saha raporu ↔ sorun olayı: KB + belirti etiketi, ya da güçlü başlık benzerliği. KB'yi anıp
     belirti belirtmeyen raporlar, hangi soruna ait olduğu bilinemediği için KB sürüm olayına iliştirilir.
   - Haber ↔ haber: 48 saat penceresinde başlık/metin benzerliği (dil bağımsız kökleme; LLM varsa
     İngilizce kanonik başlık da kullanılır). Aynı olay ikinci bir kategoride tekrar oluşturulmaz.
3. Eşleşme yoksa yeni olay.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import timedelta

from ..db import jdump, jload, tx
from ..sources.base import short_hash
from ..textutil import DOMAIN_NOISE, near_duplicate_text, specific_tags, title_similarity, token_set, tokens
from ..timeutil import now_iso, now_utc, parse_iso, to_iso
from .evidence import effective_trust

# İşleme önceliği: resmî kayıtlar önce eşleşsin ki saha raporları onlara bağlanabilsin.
KIND_PRIORITY = {
    "known_issue": 0, "cm_known_issue": 0, "kb_release": 1, "cm_version": 1, "cm_hotfix": 1, "feature": 2,
    "notice": 2, "announcement": 3, "field_report": 4, "article": 5, "content": 6,
}

EVENT_KIND = {
    "known_issue": "issue", "cm_known_issue": "issue", "field_report": "issue", "kb_release": "release",
    "cm_version": "version", "cm_hotfix": "hotfix", "feature": "feature", "notice": "notice",
    "announcement": "notice", "article": "news", "content": "content",
}


@dataclass
class ObsRow:
    id: int
    source_id: int
    source_module: str
    source_trust: str
    source_category: str | None
    external_key: str
    kind: str
    url: str | None
    title: str
    body: str
    published_at: str | None
    fields: dict
    is_demo: int

    @property
    def trust(self) -> str:
        return effective_trust(self.source_trust, self.url, self.fields)

    @property
    def kbs(self) -> set[str]:
        f = self.fields
        return set(f.get("originating_kbs") or []) | set(f.get("kbs") or []) | ({f["kb"]} if f.get("kb") else set())

    @property
    def tags(self) -> set[str]:
        return set(self.fields.get("tags") or [])

    @property
    def products(self) -> set[str]:
        return set(self.fields.get("products") or [])


def aliases_for(o: ObsRow) -> list[str]:
    f = o.fields
    out = [f"{o.kind}:{o.external_key}"]
    if o.external_key.startswith("wrh:"):
        out.append(o.external_key)
    if o.kind == "kb_release" and f.get("kb"):
        out.append(f"kb:{f['kb']}")
    if o.kind in ("feature", "notice") and o.external_key.startswith("intune:"):
        for wi in f.get("work_items") or []:
            out.append(f"intune:wi:{wi}")
        if f.get("title_slug"):
            out.append(f"intune:t:{f['title_slug']}")
    if o.kind in ("cm_version", "cm_hotfix", "cm_known_issue", "announcement"):
        out.append(o.external_key)
    if o.kind in ("field_report", "article", "content") and (f.get("canonical_url") or o.url):
        out.append("url:" + (f.get("canonical_url") or o.url))
    return list(dict.fromkeys(out))


def _load_pending(conn: sqlite3.Connection) -> list[ObsRow]:
    rows = conn.execute(
        "SELECT o.*, s.module AS s_module, s.trust AS s_trust, s.category AS s_category "
        "FROM observations o JOIN sources s ON s.id = o.source_id WHERE o.event_id IS NULL"
    ).fetchall()
    out = [ObsRow(id=r["id"], source_id=r["source_id"], source_module=r["s_module"], source_trust=r["s_trust"],
                  source_category=r["s_category"], external_key=r["external_key"], kind=r["kind"], url=r["url"],
                  title=r["title"], body=r["body"] or "", published_at=r["published_at"],
                  fields=jload(r["fields_json"], {}), is_demo=r["is_demo"]) for r in rows]
    out.sort(key=lambda o: (KIND_PRIORITY.get(o.kind, 9), 0 if o.trust == "official" else 1, o.id))
    return out


def _lookup_alias(conn: sqlite3.Connection, aliases: list[str]) -> int | None:
    for a in aliases:
        row = conn.execute("SELECT event_id FROM event_aliases WHERE alias = ?", (a,)).fetchone()
        if row:
            return row["event_id"]
    return None


def _event_profile(conn: sqlite3.Connection, ev: sqlite3.Row) -> dict:
    return {
        "id": ev["id"], "title": ev["title"], "kind": ev["kind"], "module": ev["module"],
        "kbs": set(jload(ev["kbs_json"], [])), "tags": set(jload(ev["tags_json"], [])),
        "products": set(jload(ev["products_json"], [])), "signature": ev["signature"] or "",
        "evidence": ev["evidence_level"], "category": ev["category"], "first_seen": ev["first_seen_at"],
    }


def _tags_compatible(a: set[str], b: set[str]) -> bool:
    sa, sb = specific_tags(a), specific_tags(b)
    if not sa or not sb:
        return True
    return bool(sa & sb)


def _issue_candidates(conn: sqlite3.Connection, o: ObsRow, days: int) -> list[dict]:
    cutoff = to_iso(now_utc() - timedelta(days=days))
    rows = conn.execute(
        "SELECT * FROM events WHERE kind = 'issue' AND first_seen_at >= ? AND is_demo = ?",
        (cutoff, o.is_demo),
    ).fetchall()
    return [_event_profile(conn, r) for r in rows]


def match_issue(conn: sqlite3.Connection, o: ObsRow) -> tuple[int | None, str, float]:
    """Bilinen sorun veya saha raporunu mevcut bir sorun olayıyla eşleştirir."""
    official = o.trust == "official" and o.kind in ("known_issue", "cm_known_issue")
    cands = _issue_candidates(conn, o, 120 if official else 45)
    text = o.title + " " + o.fields.get("summary", "")[:300]
    best: tuple[int | None, str, float] = (None, "", 0.0)
    for c in cands:
        kb_overlap = bool(o.kbs & c["kbs"])
        both_wrh = (official and o.external_key.startswith("wrh:")
                    and any(k.startswith("wrh:") for k in _aliases_of_event(conn, c["id"])))
        if both_wrh:
            # İki farklı Release health kimliği normalde iki ayrı sorundur. Yalnızca başlık neredeyse
            # aynıysa ve KB ortaksa (sayfaya özgü kimlik ihtimali) aynı olay sayılır.
            if kb_overlap and title_similarity(o.title, c["title"], technical=True) >= 0.9:
                return c["id"], "wrh-same-title", 0.95
            continue
        prod_overlap = bool(o.products & c["products"]) or not o.products or not c["products"]
        if not _tags_compatible(o.tags, c["tags"]):
            continue
        tag_overlap = bool(specific_tags(o.tags) & specific_tags(c["tags"]))
        sim = title_similarity(text, c["title"] + " " + c["signature"], technical=True)
        score = 0.0
        if kb_overlap and tag_overlap:
            score = 0.6 + 0.4 * sim
        elif kb_overlap and sim >= 0.45:
            score = 0.5 + 0.4 * sim
        elif tag_overlap and prod_overlap and sim >= 0.35:
            score = 0.45 + 0.5 * sim
        elif sim >= 0.6 and prod_overlap:
            score = 0.4 + 0.5 * sim
        if score > best[2]:
            best = (c["id"], "kb+tag" if kb_overlap and tag_overlap else "similarity", score)
    if best[0] is not None and best[2] >= 0.55:
        return best
    return None, "", 0.0


def _aliases_of_event(conn: sqlite3.Connection, event_id: int) -> list[str]:
    return [r["alias"] for r in conn.execute("SELECT alias FROM event_aliases WHERE event_id = ?", (event_id,))]


def key_tokens(title: str) -> set[str]:
    """Başlıktaki özel adlar (büyük harfle başlayan kelimeler) ve sayılar: farklı olayları ayırmak için."""
    keys: set[str] = set()
    for m in re.finditer(r"\d+(?:[.,]\d+)?", title or ""):
        keys.add(m.group(0).replace(",", "."))
    for w in re.findall(r"[A-ZÇĞİÖŞÜ][\wçğıöşüÇĞİÖŞÜ'’]*", title or ""):
        base = re.split(r"['’]", w)[0]
        toks = tokens(base)
        if toks:
            keys.add(toks[0])
    return keys


def match_news(conn: sqlite3.Connection, o: ObsRow) -> tuple[int | None, str, float]:
    """Haber kümeleme: aday olaydaki TÜM başlıklarla karşılaştırılır (tekli bağlantı).

    Başlıklardaki özel adlar/sayılar tamamen ayrışıyorsa (ör. "Van'da deprem" / "İstanbul'da deprem")
    yüksek benzerlik olmadıkça aynı olay sayılmaz.
    """
    pub = parse_iso(o.published_at) or now_utc()
    lo, hi = to_iso(pub - timedelta(hours=48)), to_iso(pub + timedelta(hours=48))
    rows = conn.execute(
        "SELECT * FROM events WHERE kind = 'news' AND COALESCE(published_at, first_seen_at) BETWEEN ? AND ? "
        "AND is_demo = ?", (lo, hi, o.is_demo),
    ).fetchall()
    text = o.title + " " + (o.body or "")[:280]
    alt = o.fields.get("canonical_title_en") or ""
    okeys = key_tokens(o.title)
    best: tuple[int | None, str, float] = (None, "", 0.0)
    for r in rows:
        members = conn.execute("SELECT title, body, fields_json FROM observations WHERE event_id = ? LIMIT 12",
                               (r["id"],)).fetchall()
        score = 0.0
        for mem in members or [{"title": r["title"], "body": "", "fields_json": "{}"}]:
            mtitle = mem["title"]
            mtext = mtitle + " " + (mem["body"] or "")[:280]
            mkeys = key_tokens(mtitle)
            sim = max(title_similarity(o.title, mtitle), 0.95 * title_similarity(text, mtext))
            malt = jload(mem["fields_json"], {}).get("canonical_title_en") or ""
            if alt and malt:
                sim = max(sim, title_similarity(alt, malt))
            if near_duplicate_text(text, mtext):
                sim = max(sim, 0.9)
            if okeys and mkeys and not (okeys & mkeys) and sim < 0.8:
                sim = 0.0
            score = max(score, sim)
        if score > best[2]:
            best = (r["id"], "news-similarity", score)
    if best[0] is not None and best[2] >= 0.5:
        return best
    return None, "", 0.0


def match_feature(conn: sqlite3.Connection, o: ObsRow) -> tuple[int | None, str, float]:
    rows = conn.execute(
        "SELECT * FROM events WHERE module = ? AND kind IN ('feature', 'notice') AND is_demo = ?",
        (o.source_module, o.is_demo),
    ).fetchall()
    best: tuple[int | None, str, float] = (None, "", 0.0)
    for r in rows:
        sim = title_similarity(o.title, r["title"], technical=True)
        if sim > best[2]:
            best = (r["id"], "title-similarity", sim)
    if best[0] is not None and best[2] >= 0.8:
        return best
    return None, "", 0.0


def _field_module(o: ObsRow) -> str:
    tags = o.tags
    if "configmgr" in tags:
        return "configmgr"
    if "intune" in tags:
        return "intune"
    return "windows"


def create_event(conn: sqlite3.Connection, o: ObsRow) -> int:
    kind = EVENT_KIND.get(o.kind, "news")
    if o.kind in ("field_report",):
        module = _field_module(o)
        key = "field:" + short_hash(o.url or o.external_key, 14)
    elif o.kind == "article":
        module = "news" if o.source_module == "news" else o.source_module
        key = "news:" + short_hash(o.url or o.external_key, 14)
    elif o.kind == "content":
        module = "content"
        key = "content:" + short_hash(o.url or o.external_key, 14)
    else:
        module = o.source_module if o.source_module in ("windows", "intune", "configmgr") else "windows"
        key = o.external_key if ":" in o.external_key else f"{o.kind}:{o.external_key}"
    # Aynı anahtar başka bir olayda varsa (ör. yeniden oluşturma) benzersizleştir.
    if conn.execute("SELECT 1 FROM events WHERE event_key = ?", (key,)).fetchone():
        key = f"{key}:{o.id}"
    signature = " ".join(sorted(token_set(o.title + " " + o.fields.get("summary", "")[:300], noise=DOMAIN_NOISE)))
    ts = now_iso()
    cur = conn.execute(
        "INSERT INTO events(event_key, module, category, kind, title, first_seen_at, published_at, "
        "products_json, kbs_json, tags_json, signature, needs_analysis, is_demo) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
        (key, module, o.source_category if kind == "news" else None, kind, o.title, ts, o.published_at,
         jdump(sorted(o.products)), jdump(sorted(o.kbs)), jdump(sorted(o.tags)), signature, o.is_demo),
    )
    return cur.lastrowid


def _attach_kb_release(conn: sqlite3.Connection, o: ObsRow) -> int | None:
    """Belirti belirtmeyen ama KB anan saha raporu → ilgili KB sürüm olayı."""
    if specific_tags(o.tags):
        return None
    for kb in sorted(o.kbs):
        row = conn.execute("SELECT event_id FROM event_aliases WHERE alias = ?", (f"kb:{kb}",)).fetchone()
        if row:
            return row["event_id"]
    return None


def match_pending(conn: sqlite3.Connection) -> list[int]:
    touched: set[int] = set()
    pending = _load_pending(conn)
    for o in pending:
        with tx(conn):
            aliases = aliases_for(o)
            event_id = _lookup_alias(conn, aliases)
            method, score = ("key", 1.0) if event_id else ("", 0.0)
            if event_id is None:
                if o.kind in ("known_issue", "cm_known_issue", "field_report"):
                    event_id, method, score = match_issue(conn, o)
                    if event_id is None and o.kind == "field_report":
                        kb_event = _attach_kb_release(conn, o)
                        if kb_event:
                            event_id, method, score = kb_event, "kb-only", 0.5
                elif o.kind == "article":
                    event_id, method, score = match_news(conn, o)
                elif o.kind in ("feature", "notice"):
                    event_id, method, score = match_feature(conn, o)
            if event_id is None:
                event_id = create_event(conn, o)
                method, score = "new", 1.0
            conn.execute("UPDATE observations SET event_id = ?, match_method = ?, match_score = ? WHERE id = ?",
                         (event_id, method, round(score, 3), o.id))
            for a in aliases:
                conn.execute("INSERT OR IGNORE INTO event_aliases(alias, event_id) VALUES (?, ?)", (a, event_id))
            conn.execute("UPDATE events SET needs_analysis = 1 WHERE id = ?", (event_id,))
            touched.add(event_id)
    return sorted(touched)

