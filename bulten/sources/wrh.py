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

from bs4 import BeautifulSoup, Tag

from ..textutil import extract_builds, extract_kbs, extract_products, norm_space, symptom_tags
from ..timeutil import parse_loose_date, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, slugify
from .htmlutil import main_content, soup_of, text_of

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


def _detail_container(soup: BeautifulSoup, anchor: str) -> Tag | None:
    el = soup.find(id=anchor) or soup.find("a", attrs={"name": anchor})
    if el is None:
        return None
    for parent in el.parents:
        if parent.name in ("tr", "section", "details", "article") and parent.name != "body":
            # tablo satırı birden çok soruna yayılmıyorsa kullan
            if len(parent.find_all(id=ANCHOR_RE)) <= 1:
                return parent
            break
    # Kardeşleri bir sonraki çapaya veya başlığa kadar topla.
    wrapper = soup.new_tag("div")
    node = el
    collected = [el] if el.get_text(strip=True) else []
    while node is not None:
        node = node.next_sibling
        if node is None:
            break
        if isinstance(node, Tag):
            if node.name in ("h1", "h2") or (node.get("id") and ANCHOR_RE.search(node.get("id", ""))):
                break
            if node.find(id=ANCHOR_RE) is not None:
                break
            if node.name == "h3" and collected:
                break
        collected.append(node)
    for c in collected:
        wrapper.append(c.__copy__() if isinstance(c, Tag) else str(c))
    return wrapper


def _symptom_text(detail: str) -> str:
    """Ayrıntı metninden yalnızca belirti kısmı (geçici çözüm/çözüm metni etiketlemeyi yanıltmasın)."""
    m = re.search(r"(?<![A-Za-z])(Workaround|Resolution|Affected platforms?|Next steps)\s*:", detail, re.I)
    return detail[: m.start()] if m else detail


def _affected(text: str) -> dict[str, str]:
    out = {}
    m = re.search(r"Affected platforms?\s*:?(.+?)(?:Workaround\s*:|Resolution\s*:|Next steps\s*:|\Z)", text, re.I | re.S)
    block = m.group(1) if m else text
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
        container = _detail_container(soup, anchor)
        if container is None:
            continue
        detail = text_of(container)
        if not detail:
            continue
        iid = _issue_id(anchor, "")
        ob = obs.get(iid)
        head = container.find(["b", "strong", "h3", "h4"])
        dtitle = norm_space(head.get_text(" ", strip=True)) if head else norm_space(detail.split("\n")[0])
        if ob is None:
            ob = Observation(external_key=f"wrh:{iid}", kind="known_issue", title=dtitle or iid,
                             url=f"{page_url}#{anchor}", fields={"issue_id": iid, "anchor": anchor, "section": section})
            obs[iid] = ob
        ob.body = detail[:8000]
        f = ob.fields
        if not f.get("status_raw"):
            m = re.search(r"\b(Resolved External|Resolved(?: KB\d+)?|Mitigated External|Mitigated|Confirmed|Investigating)\b", detail)
            f["status_raw"] = m.group(1) if m else ""
            f["status"] = normalize_status(f["status_raw"])
        if not f.get("originating_kbs"):
            m = re.search(r"Originating update\s*:?(.{0,160})", detail, re.S)
            seg = m.group(1) if m else detail[:600]
            f["originating_kbs"] = extract_kbs(seg)
            f["originating_builds"] = extract_builds(seg)
        f["workaround"] = _section_after("Workaround", detail, STOP_LABELS)
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
        res_kbs = set(extract_kbs(f.get("status_raw", "")) + extract_kbs(f.get("resolution", "")))
        res_kbs -= set(f.get("originating_kbs") or [])
        f["resolving_kbs"] = sorted(res_kbs)
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
