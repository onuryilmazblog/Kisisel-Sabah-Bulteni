"""Windows release health (learn.microsoft.com/windows/release-health) ayrıştırıcıları.

Durum sayfası ("known issues and notifications") ve çözülen sorunlar sayfası aynı
kalıbı kullanır: bir özet tablosu (Summary | Originating update | Status | Last updated)
ve her sorun için "…msgdesc" çapasıyla işaretlenmiş ayrıntı bölümü.

Microsoft için resmî RSS bulunmadığından HTML ayrıştırılır. Ayrıştırıcı yapıya karşı
toleranslıdır; beklenen yapı hiç bulunamazsa `structure_ok=False` döner ve kaynak
"ayrıştırma uyarısı" olarak işaretlenir ("yeni sorun yok" diye yorumlanmaz).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from ..textutil import (
    extract_builds, extract_kbs, extract_products, norm_space, split_fix_kbs, strip_registry_warning, symptom_tags,
)
from ..timeutil import parse_loose_date, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, slugify
from .htmlutil import BLOCK_TAGS, main_content, normalize_text, soup_of, text_of

ANCHOR_RE = re.compile(r"(\d{3,9})msgdesc", re.I)


def normalize_status(raw: str | None) -> str:
    r = (raw or "").lower()
    if "resolved external" in r:
        return "resolved_external"
    if "resolved" in r:
        return "resolved"
    if "mitigated external" in r:
        return "mitigated_external"
    if "mitigated" in r:
        return "mitigated"
    if "confirmed" in r:
        return "confirmed"
    if "investigating" in r or "reported" in r:
        return "investigating"
    return "unknown"


def _find_summary_tables(root: Tag) -> list[tuple[Tag, dict[str, int]]]:
    found = []
    for table in root.find_all("table"):
        header_cells = table.find_all("th")
        if not header_cells:
            first = table.find("tr")
            header_cells = first.find_all("td") if first else []
        names = [norm_space(c.get_text(" ", strip=True)).lower() for c in header_cells]
        if any("summary" in n for n in names) and any("status" in n for n in names):
            colmap: dict[str, int] = {}
            for i, n in enumerate(names):
                if "summary" in n:
                    colmap["summary"] = i
                elif "originating" in n:
                    colmap["originating"] = i
                elif "status" in n:
                    colmap["status"] = i
                elif "updated" in n or "resolved" in n or "date" in n:
                    colmap["updated"] = i
            found.append((table, colmap))
    return found


def _anchor_of(cell: Tag) -> str | None:
    for a in cell.find_all("a", href=True):
        href = a["href"]
        if href.startswith("#") and len(href) > 1:
            return href[1:]
    return None


def _issue_id(anchor: str | None, title: str) -> str:
    if anchor:
        m = ANCHOR_RE.search(anchor)
        return m.group(1) if m else slugify(anchor, 40)
    return "t-" + slugify(title, 60)


def _section_after(label: str, text: str, stops: list[str]) -> str:
    # Etiket iki nokta ile bitmeli ("Resolution:"); cümle içindeki "a resolution" eşleşmesin.
    pat = re.compile(rf"(?<![A-Za-z]){label}\s*:\s*(.+?)(?=(?:{'|'.join(stops)})\s*:|\Z)", re.I | re.S)
    m = pat.search(text)
    if not m:
        return ""
    return norm_space(m.group(1)).strip(" ·")


STOP_LABELS = ["Workaround", "Resolution", "Next steps", "Affected platforms", "Status", "Originating update",
               "History", "Back to top", "Note", "Important"]


def _is_anchor(node: Tag) -> bool:
    ident = node.get("id") or (node.get("name") if node.name == "a" else None) or ""
    return bool(ident) and bool(ANCHOR_RE.search(ident))


def _detail_text(soup: BeautifulSoup, anchor: str) -> str | None:
    """Çapadan bir sonraki sorun çapasına (veya h2 başlığına) kadar olan metni belge sırasıyla toplar.

    Gerçek Learn sayfalarında bir sorunun kuyruğu (ör. "Affected platforms") bir sonraki sorunun
    çapasını da içeren iç içe bir div'de olabilir; kardeş öğe yürüyüşü bu kısmı kaçırır. Belge sırası
    (next_elements) iç içe yapıdan bağımsızdır.
    """
    el = soup.find(id=anchor) or soup.find("a", attrs={"name": anchor})
    if el is None:
        return None
    parts: list[str] = []
    for node in el.next_elements:
        if isinstance(node, Tag):
            if node is not el and _is_anchor(node):
                break
            if node.name in ("h1", "h2"):
                break
            if node.name == "br":
                parts.append("\n")
            elif node.name == "li":
                parts.append("\n• ")
            elif node.name in ("td", "th"):
                parts.append(" · ")
            elif node.name in BLOCK_TAGS:
                parts.append("\n")
        elif isinstance(node, NavigableString):
            if isinstance(node, Comment) or (node.parent is not None and node.parent.name in (
                    "script", "style", "noscript", "template")):
                continue
            parts.append(str(node))
    return normalize_text("".join(parts))


def _detail_meta(soup: BeautifulSoup, anchor: str) -> dict[str, str]:
    """Ayrıntı bölümündeki küçük tablo (Status | Originating update | History), hücre bazında.

    Serbest metinde "Originating update" etiketinden sonrası durum hücresindeki çözüm KB'sini de
    içerebildiği için kaynak KB hücreden okunur.
    """
    el = soup.find(id=anchor) or soup.find("a", attrs={"name": anchor})
    if el is None:
        return {}
    table = None
    for node in el.next_elements:
        if isinstance(node, Tag):
            if node is not el and _is_anchor(node):
                return {}
            if node.name == "table":
                table = node
                break
    if table is None:
        return {}
    heads = [norm_space(c.get_text(" ", strip=True)).lower() for c in table.find_all("th")]
    row = next((tr.find_all("td") for tr in table.find_all("tr") if tr.find_all("td")), [])
    out: dict[str, str] = {}
    for head, cell in zip(heads, row):
        key = ("status" if "status" in head else "originating" if "originating" in head
               else "history" if "history" in head else None)
        if key:
            out[key] = text_of(cell)
    return out


def _symptom_text(detail: str) -> str:
    """Ayrıntı metninden yalnızca belirti kısmı (geçici çözüm/çözüm metni etiketlemeyi yanıltmasın)."""
    m = re.search(r"(?<![A-Za-z])(Workaround|Resolution|Affected platforms?|Next steps)\s*:", detail, re.I)
    return detail[: m.start()] if m else detail


def _affected(text: str) -> dict[str, str]:
    out = {}
    # Etiket iki nokta ile gelmeli: gerçek sayfalarda gövdede "limited to the affected platforms listed
    # below" gibi cümleler de geçiyor. Birden çok eşleşmede sonuncusu (sorunun kuyruğundaki blok) alınır.
    blocks = re.findall(r"Affected platforms?\s*:(.+?)(?=Workaround\s*:|Resolution\s*:|Next steps\s*:|\Z)",
                        text, re.I | re.S)
    block = blocks[-1] if blocks else text
    for kind in ("Client", "Server"):
        mm = re.search(rf"{kind}\s*:\s*(.+)", block)
        if mm:
            value = norm_space(mm.group(1)).strip(" ·;")
            if value.lower() not in ("none", "n/a", "-"):
                out[kind.lower()] = value
    return out


def _history_dates(text: str) -> dict[str, str | None]:
    res: dict[str, str | None] = {}
    for label, key in (("Opened", "opened"), ("Resolved", "resolved"), ("Last updated", "last_updated"),
                       ("Mitigated", "mitigated")):
        m = re.search(rf"{label}\s*:?\s*(\d{{4}}-\d{{2}}-\d{{2}}(?:,?\s*\d{{1,2}}:\d{{2}}\s*(?:PT|UTC)?)?|[A-Z][a-z]+ \d{{1,2}}, \d{{4}})",
                      text)
        if m:
            res[key] = to_iso(parse_loose_date(m.group(1).replace(",", " ")))
    return res


def parse_wrh_page(html: str, *, page_url: str, page_products: list[str], section: str) -> AdapterResult:
    soup = soup_of(html)
    root = main_content(soup)
    obs: dict[str, Observation] = {}
    warnings: list[str] = []
    tables = _find_summary_tables(root)
    rows_seen = 0

    for table, colmap in tables:
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2 or "summary" not in colmap:
                continue
            si = colmap.get("summary", 0)
            if si >= len(cells):
                continue
            summary_cell = cells[si]
            anchor = _anchor_of(summary_cell)
            strong = summary_cell.find(["b", "strong", "a"])
            title = norm_space(strong.get_text(" ", strip=True)) if strong else ""
            full = text_of(summary_cell)
            if not title:
                title = norm_space(full.split("\n")[0])
            if not title:
                continue
            rows_seen += 1
            short = norm_space(full.replace(title, "", 1))
            status_raw = text_of(cells[colmap["status"]]) if "status" in colmap and colmap["status"] < len(cells) else ""
            orig_raw = text_of(cells[colmap["originating"]]) if "originating" in colmap and colmap["originating"] < len(cells) else ""
            upd_raw = text_of(cells[colmap["updated"]]) if "updated" in colmap and colmap["updated"] < len(cells) else ""
            iid = _issue_id(anchor, title)
            obs[iid] = Observation(
                external_key=f"wrh:{iid}", kind="known_issue", title=title,
                url=f"{page_url}#{anchor}" if anchor else page_url, body=short,
                fields={
                    "issue_id": iid, "anchor": anchor, "section": section,
                    "status_raw": norm_space(status_raw), "status": normalize_status(status_raw),
                    "originating_raw": norm_space(orig_raw),
                    "originating_kbs": extract_kbs(orig_raw), "originating_builds": extract_builds(orig_raw),
                    "last_updated_raw": norm_space(upd_raw),
                },
                source_updated_at=to_iso(parse_loose_date(upd_raw)),
            )

    # Ayrıntı bölümleri
    anchors = []
    for el in root.find_all(id=ANCHOR_RE):
        anchors.append(el.get("id"))
    for el in root.find_all("a", attrs={"name": ANCHOR_RE}):
        anchors.append(el.get("name"))
    for ob in obs.values():
        if ob.fields.get("anchor") and ob.fields["anchor"] not in anchors:
            anchors.append(ob.fields["anchor"])

    for anchor in dict.fromkeys(anchors):
        detail = _detail_text(soup, anchor)
        if not detail:
            continue
        iid = _issue_id(anchor, "")
        ob = obs.get(iid)
        dtitle = norm_space(detail.split("\n")[0])
        if ob is None:
            ob = Observation(external_key=f"wrh:{iid}", kind="known_issue", title=dtitle or iid,
                             url=f"{page_url}#{anchor}", fields={"issue_id": iid, "anchor": anchor, "section": section})
            obs[iid] = ob
        ob.body = detail[:8000]
        f = ob.fields
        meta = _detail_meta(soup, anchor)
        if not f.get("status_raw"):
            if meta.get("status"):
                f["status_raw"] = norm_space(meta["status"])
            else:
                m = re.search(r"\b(Resolved External|Resolved(?: KB\d+)?|Mitigated External|Mitigated|Confirmed|Investigating)\b", detail)
                f["status_raw"] = m.group(1) if m else ""
            f["status"] = normalize_status(f["status_raw"])
        if not f.get("originating_kbs"):
            if "originating" in meta:
                seg = meta["originating"]
            else:
                m = re.search(r"Originating update\s*:(.{0,160})", detail, re.S)
                seg = m.group(1) if m else ""
            f["originating_kbs"] = extract_kbs(seg)
            f["originating_builds"] = extract_builds(seg)
            if seg and not f.get("originating_raw"):
                f["originating_raw"] = norm_space(seg)
        f["workaround"] = strip_registry_warning(_section_after("Workaround", detail, STOP_LABELS))
        f["resolution"] = _section_after("Resolution", detail, STOP_LABELS)
        f["next_steps"] = _section_after("Next steps", detail, STOP_LABELS)
        f["affected_platforms"] = _affected(detail)
        f.update({k: v for k, v in _history_dates(detail).items() if v})
        if f.get("opened"):
            ob.published_at = f["opened"]
        if f.get("last_updated") or f.get("resolved"):
            ob.source_updated_at = f.get("last_updated") or f.get("resolved")

    for ob in obs.values():
        f = ob.fields
        text_all = " ".join([ob.title, ob.body, f.get("status_raw", ""), f.get("resolution", "")])
        full_kbs, partial_kbs = split_fix_kbs(f.get("resolution", ""))
        origin = set(f.get("originating_kbs") or [])
        res_kbs = (set(extract_kbs(f.get("status_raw", ""))) | set(full_kbs)) - origin
        f["resolving_kbs"] = sorted(res_kbs)
        f["partial_fix_kbs"] = sorted(set(partial_kbs) - res_kbs - origin)
        f["kir"] = bool(re.search(r"known issue rollback|\bKIR\b", text_all, re.I))
        aff = " ; ".join((f.get("affected_platforms") or {}).values())
        products = set(page_products) | set(extract_products(aff))
        f["products"] = sorted(products)
        f["tags"] = symptom_tags(ob.title + " " + _symptom_text(ob.body))
        f["page_products"] = page_products

    structure_ok = bool(tables) or bool(obs)
    if not tables:
        warnings.append("Özet tablosu bulunamadı (sayfa yapısı değişmiş olabilir).")
    if tables and rows_seen == 0 and not obs:
        # Tablo var ama boş: gerçekten açık sorun olmayabilir; yine de işaretle.
        warnings.append("Özet tablosu boş.")
    return AdapterResult(observations=list(obs.values()), warnings=warnings, structure_ok=structure_ok,
                         fetched_url=page_url)


def run_wrh(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, which = fetch_with_fallback(source, ctx)
    section = "resolved" if source.adapter == "wrh_resolved" else "active"
    out = parse_wrh_page(res.text, page_url=source.url, page_products=source.product_ids, section=section)
    out.fetched_url = res.url
    out.http_status = res.status
    out.not_modified = res.not_modified
    if which == "fallback":
        out.warnings.append("Birincil adres başarısız; yedek adres kullanıldı.")
    return out


def parse_message_center(html: str, *, page_url: str) -> AdapterResult:
    """Windows message center: duyurular (özet tablo satırları veya başlıklar)."""
    soup = soup_of(html)
    root = main_content(soup)
    obs: list[Observation] = []
    for table in root.find_all("table"):
        for tr in table.find_all("tr"):
            cells = tr.find_all("td")
            if len(cells) < 2:
                continue
            first = cells[0]
            strong = first.find(["b", "strong", "a"])
            title = norm_space(strong.get_text(" ", strip=True)) if strong else ""
            if not title:
                continue
            body = text_of(first)
            date_txt = text_of(cells[-1])
            dt = to_iso(parse_loose_date(date_txt))
            anchor = _anchor_of(first)
            key = "wmc:" + (_issue_id(anchor, title) if anchor else slugify(title, 70))
            obs.append(Observation(
                external_key=key, kind="announcement", title=title, url=f"{page_url}#{anchor}" if anchor else page_url,
                body=body[:6000], published_at=dt, source_updated_at=dt,
                fields={"products": extract_products(body), "kbs": extract_kbs(body), "tags": symptom_tags(body)},
            ))
    structure_ok = bool(obs)
    warnings = [] if obs else ["Duyuru tablosu bulunamadı."]
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=structure_ok, fetched_url=page_url)


def run_message_center(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, _ = fetch_with_fallback(source, ctx)
    out = parse_message_center(res.text, page_url=source.url)
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out
