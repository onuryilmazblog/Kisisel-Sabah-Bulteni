"""support.microsoft.com: güncelleme geçmişi sayfaları ve KB makalelerinin "Known issues" bölümü.

Güncelleme geçmişi sayfasındaki bağlantı metinleri tutarlı bir kalıp izler:
  "September 8, 2026—KB5124008 (OS Builds 26200.9445 and 26100.9445)"
  "August 27, 2026—KB5120998 (OS Builds 26200.9278 and 26100.9278) Preview"
  "September 14, 2026—KB5129195 (OS Builds 26200.9457 and 26100.9457) Out-of-band"
  "August 11, 2026—Hotpatch KB5120228 (OS Build 26100.33222)"
Tür etiketi bu metinden çıkarılır; etiket yoksa ayın ikinci salısı "aylık güvenlik
güncellemesi" (B sürümü) kabul edilir, değilse "diğer".
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta
from urllib.parse import urljoin

from bs4 import Tag

from ..db import jload
from ..net.fetcher import FetchError
from ..textutil import (
    PARTIAL_FIX_RE, extract_builds, extract_kbs, extract_products, norm_space, split_fix_kbs, strip_registry_warning,
    symptom_tags,
)
from ..timeutil import now_utc, parse_loose_date, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, short_hash
from .htmlutil import main_content, soup_of, text_of

TITLE_RE = re.compile(
    r"(?P<date>[A-Z][a-z]+\.? \d{1,2},? \d{4})\s*[—–\-]+\s*(?P<hot>Hotpatch\s+)?KB\s?(?P<kb>\d{6,8})\s*"
    # Bazı satırlarda KB ile build arasında ürün adı geçer: "KB5071959 Windows 10, version 22H2 (OS Build …)"
    r"(?:[^()—–]{0,80}?\s*)?\((?P<builds>OS Builds?[^)]*)\)\s*(?P<suffix>[^|]*)",
    re.I,
)

RELEASE_TYPE_TR = {
    "security": "Aylık güvenlik güncellemesi",
    "preview": "Preview (isteğe bağlı, güvenlik dışı)",
    "oob": "OOB (plan dışı)",
    "hotpatch": "Hotpatch güvenlik güncellemesi",
    "other": "Diğer güncelleme",
}


def is_patch_tuesday(dt: datetime) -> bool:
    return dt.weekday() == 1 and 8 <= dt.day <= 14


def classify_release(title: str, hot: bool, date: datetime | None) -> str:
    t = title.lower()
    if "out-of-band" in t or "out of band" in t:
        return "oob"
    if hot:
        return "hotpatch"
    if re.search(r"\bpreview\b", t):
        return "preview"
    if date is not None and is_patch_tuesday(date):
        return "security"
    return "other"


def _nav_candidates(soup, nav_category: str | None) -> tuple[list[tuple[str, str | None]] | None, str | None]:
    """Güncelleme geçmişi sayfasının sol menüsünden sayfanın ürününe ait bağlantılar.

    Gerçek sayfalarda KB listesi ana içerikte değil, tüm ürün ailesini içeren sol menüdedir
    (ör. 25H2 sayfasının menüsünde 26H1 ve 23H2 KB'leri de vardır). Bu yüzden yalnızca ürünün
    kategorisi okunur: yapılandırılan kategori başlığı, yoksa sayfanın etkin kategorisi.
    Menü yoksa None döner (ana içerik taranır).
    """
    cats = soup.select("div.learnRenderLeftNavCategory")
    if not cats:
        return None, None
    chosen = None
    if nav_category:
        want = norm_space(nav_category).lower()
        for cat in cats:
            head = cat.select_one(".learnRenderLeftNavCategoryTitle")
            title = norm_space(head.get_text(" ", strip=True)).lower() if head else ""
            if title == want or title.startswith(want):
                chosen = cat
                break
        if chosen is None:
            return [], f"Menüde '{nav_category}' kategorisi bulunamadı (sayfa yapısı değişmiş olabilir)."
    else:
        chosen = soup.select_one("div.learnRenderLeftNavActiveCategory")
        if chosen is None:
            return [], "Menüde sayfanın etkin kategorisi bulunamadı."
    return [(norm_space(a.get_text(" ", strip=True)), a.get("href")) for a in chosen.select("li a")], None


def parse_update_history(html: str, *, page_url: str, page_products: list[str],
                         months_back: int = 4, nav_category: str | None = None) -> AdapterResult:
    soup = soup_of(html)
    root = main_content(soup)
    cutoff = now_utc() - timedelta(days=31 * months_back)
    seen: dict[str, Observation] = {}
    warnings: list[str] = []
    candidates, nav_warning = _nav_candidates(soup, nav_category)
    if nav_warning:
        return AdapterResult(observations=[], warnings=[nav_warning], structure_ok=False, fetched_url=page_url)
    if candidates is None:
        candidates = [(norm_space(a.get_text(" ", strip=True)), a.get("href")) for a in root.find_all("a")]
        if not candidates:
            candidates = [(norm_space(line), None) for line in text_of(root).split("\n")]
    matched_any = False
    for text, href in candidates:
        m = TITLE_RE.search(text)
        if not m:
            continue
        matched_any = True
        kb = m.group("kb")
        date = parse_loose_date(m.group("date").replace(".", ""))
        if date is None or date < cutoff:
            continue
        builds = extract_builds(m.group("builds"))
        title = norm_space(m.group(0))
        rtype = classify_release(title, bool(m.group("hot")), date)
        products = set(page_products)
        products.update(extract_products(" ".join(builds)) if not page_products else [])
        if kb not in seen:
            seen[kb] = Observation(
                external_key=f"kb:{kb}", kind="kb_release", title=title,
                url=urljoin(page_url, href) if href else page_url, published_at=to_iso(date),
                body=title,
                fields={"kb": kb, "builds": builds, "release_type": rtype, "products": sorted(products),
                        "expired": "expired" in title.lower()},
            )
    obs = list(seen.values())
    if not matched_any:
        warnings.append("Bu sayfada KB bağlantısı bulunamadı (yapı değişmiş olabilir).")
    elif not obs:
        warnings.append(f"Son {months_back} ayda yayımlanmış KB bağlantısı yok.")
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=matched_any, fetched_url=page_url)


def run_update_history(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, _ = fetch_with_fallback(source, ctx)
    # Göreli bağlantılar (../../2026/09/kb…) yönlendirme sonrası adrese göre çözülmeli.
    out = parse_update_history(res.text, page_url=res.url or source.url, page_products=source.product_ids,
                               months_back=int(source.config.get("months_back", 4)),
                               nav_category=source.config.get("nav_category"))
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out


# --- KB makalesi: "Known issues in this update" --------------------------------

NO_ISSUES_RE = re.compile(r"(not currently aware of any issues|no known issues)", re.I)
SECTION_LABELS = {
    "symptom": "symptoms", "symptoms": "symptoms", "workaround": "workaround", "workarounds": "workaround",
    "mitigation": "workaround", "resolution": "resolution", "resolutions": "resolution", "next steps": "next_steps",
    "next step": "next_steps", "cause": "symptoms",
}
FULL_FIX_RE = re.compile(r"\b(?:is|was|has been|have been|are)\s+(?:now\s+)?(?:fully\s+)?(?:resolved|fixed|addressed)\b",
                         re.I)


def _known_issues_block(root: Tag) -> tuple[Tag | None, list[Tag]]:
    for h in root.find_all(["h2", "h3"]):
        if re.search(r"known issues", h.get_text(" ", strip=True), re.I):
            level = int(h.name[1])
            nodes: list[Tag] = []
            for sib in h.find_next_siblings():
                if isinstance(sib, Tag) and sib.name in ("h1", "h2") or (
                        isinstance(sib, Tag) and sib.name == "h3" and level == 3):
                    break
                nodes.append(sib)
            return h, nodes
    return None, []


def _section_label(node: Tag) -> str | None:
    """"<p><strong>Symptoms</strong></p>" veya "<h3>Workaround</h3>" gibi bölüm etiketleri."""
    text = norm_space(node.get_text(" ", strip=True)).rstrip(":").lower()
    if text not in SECTION_LABELS:
        return None
    if node.name in ("h3", "h4", "h5", "h6"):
        return SECTION_LABELS[text]
    strong = node.find(["b", "strong"])
    if node.name == "p" and strong is not None and norm_space(strong.get_text(" ", strip=True)).rstrip(":").lower() == text:
        return SECTION_LABELS[text]
    return None


def _details_issues(nodes: list[Tag]) -> list[dict[str, str]]:
    """Gerçek KB makalelerinde her sorun bir <details> bloğudur: <summary> başlık, ardından
    "Symptoms", "Workaround", "Resolution" bölümleri."""
    out = []
    blocks: list[Tag] = []
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        blocks.extend([n] if n.name == "details" else n.find_all("details"))
    for d in blocks:
        summary = d.find("summary")
        title = norm_space(text_of(summary)) if summary else ""
        sections: dict[str, list[str]] = {"symptoms": []}
        current = "symptoms"
        for child in d.children:
            if not isinstance(child, Tag) or child is summary:
                continue
            label = _section_label(child)
            if label:
                current = label
                sections.setdefault(current, [])
                continue
            t = text_of(child)
            if t:
                sections.setdefault(current, []).append(t)
        if title:
            out.append({k: "\n".join(v) for k, v in sections.items()} | {"title": title})
    return out


def _table_issues(nodes: list[Tag]) -> list[dict[str, str]]:
    out = []
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        for table in [n] if n.name == "table" else n.find_all("table"):
            headers = [norm_space(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
            if not headers:
                continue
            si = next((i for i, h in enumerate(headers) if "symptom" in h), 0)
            wi = next((i for i, h in enumerate(headers) if "workaround" in h or "resolution" in h), None)
            for tr in table.find_all("tr"):
                tds = tr.find_all("td")
                if not tds:
                    continue
                symptom = text_of(tds[si]) if si < len(tds) else ""
                workaround = text_of(tds[wi]) if wi is not None and wi < len(tds) else ""
                head = tds[si].find(["b", "strong"]) if si < len(tds) else None
                title = norm_space(head.get_text(" ", strip=True)) if head else symptom.split(".")[0]
                out.append({"title": title, "symptoms": symptom, "workaround": workaround})
    return out


def _heading_issues(nodes: list[Tag]) -> list[dict[str, str]]:
    """Tablo/details yoksa alt başlık veya yalnızca kalın metinden oluşan paragraf bazlı bölme."""
    out = []
    current: list[str] = []
    title = ""
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        is_head = n.name in ("h3", "h4", "h5") or (
            n.name == "p" and n.find(["b", "strong"]) is not None
            and norm_space(n.get_text()) == norm_space(n.find(["b", "strong"]).get_text()))
        if is_head and not _section_label(n):
            if title and current:
                out.append({"title": title, "symptoms": "\n".join(current)})
            title, current = norm_space(n.get_text(" ", strip=True)), []
        else:
            t = text_of(n)
            if t:
                current.append(t)
    if title and current:
        out.append({"title": title, "symptoms": "\n".join(current)})
    return out


def parse_kb_article(html: str, *, kb: str, page_url: str, page_products: list[str]) -> AdapterResult:
    soup = soup_of(html)
    root = main_content(soup)
    heading, nodes = _known_issues_block(root)
    obs: list[Observation] = []
    if heading is None:
        return AdapterResult(observations=[], warnings=["'Known issues' bölümü bulunamadı."],
                             structure_ok=False, fetched_url=page_url)
    block_text = "\n".join(text_of(n) for n in nodes if isinstance(n, Tag))
    if NO_ISSUES_RE.search(block_text) and len(block_text) < 400:
        return AdapterResult(observations=[], structure_ok=True, fetched_url=page_url, warnings=[])
    issues = _details_issues(nodes) or _table_issues(nodes) or _heading_issues(nodes)
    warnings: list[str] = []
    if not issues and block_text.strip():
        issues = [{"title": f"KB{kb} bilinen sorun", "symptoms": block_text}]
        warnings.append("Bilinen sorunlar tek tek ayrılamadı; bölüm tek kayıt olarak alındı.")
    anchor = heading.get("id") or "known-issues"
    for it in issues:
        title = norm_space(it["title"])
        symptom = it.get("symptoms", "")
        workaround = it.get("workaround", "")
        resolution = "\n".join(x for x in (it.get("resolution", ""), it.get("next_steps", "")) if x)
        # Microsoft'un standart kayıt defteri uyarısı geçici çözümün kendisi değildir.
        workaround = strip_registry_warning(workaround)
        if not (workaround or resolution):
            # Tablo/başlık biçiminde bölümler metnin içinde "Workaround:" gibi etiketlerle gelebilir.
            m = re.search(r"(?<![A-Za-z])(?:Workaround|Mitigation)\s*:\s*(.+)", symptom, re.I | re.S)
            workaround = norm_space(m.group(1)) if m else ""
            m = re.search(r"(?<![A-Za-z])Resolution\s*:\s*(.+)", symptom, re.I | re.S)
            resolution = norm_space(m.group(1)) if m else ""
        body = symptom
        if workaround:
            body += "\n\nWorkaround: " + workaround
        if resolution:
            body += "\n\nResolution: " + resolution
        # Kaynak KB: belirtide adı geçen güncelleme ("After installing KB5124008 or later updates");
        # yoksa makalenin KB'si. Sorun sonraki KB'lerin makalelerinde de listelenir; bu KB'ler kaynak sayılmaz.
        origin = extract_kbs(symptom) or [kb]
        fix_text = resolution or symptom
        full_kbs, partial_kbs = split_fix_kbs(fix_text)
        fully = any(FULL_FIX_RE.search(sn) and not PARTIAL_FIX_RE.search(sn)
                    for sn in re.split(r"(?<=[.!?])\s+|\n+", fix_text))
        resolving = sorted(set(full_kbs) - set(origin)) if fully else []
        partial = sorted(set(partial_kbs) - set(origin) - set(resolving))
        status = "resolved" if fully else "mitigated" if partial else "confirmed"
        obs.append(Observation(
            external_key=f"kbki:{kb}:{short_hash(title.lower()[:90])}", kind="known_issue",
            title=title[:300], url=f"{page_url}#{anchor}", body=body[:8000],
            fields={
                "kb": kb, "originating_kbs": origin, "workaround": norm_space(workaround)[:2000],
                "resolution": norm_space(resolution)[:2000],
                "status": status, "status_raw": "KB Known issues",
                "resolving_kbs": resolving, "partial_fix_kbs": partial,
                "products": sorted(set(page_products) | set(extract_products(body))),
                "tags": symptom_tags(title + " " + symptom), "kir": "known issue rollback" in body.lower(),
                "from": "kb_article",
            },
        ))
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=True, fetched_url=page_url)


def run_kb_articles(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    """Son yayımlanan KB'lerin (update history'den) makalelerini okur ve bilinen sorunları çıkarır.

    Yalnızca son 24 saatte yayımlananlar değil, `days_back` içindeki tüm KB'ler her
    çalıştırmada yeniden kontrol edilir (bilinen sorunlar sonradan eklenir/çözülür).
    """
    days_back = int(source.config.get("days_back", 60))
    max_pages = int(source.config.get("max_pages", 15))
    targets: dict[str, tuple[str, list[str]]] = {}
    if ctx.kb_targets is not None:
        targets = {kb: (url, prods) for kb, url, prods in ctx.kb_targets}
    else:
        cutoff = to_iso(now_utc() - timedelta(days=days_back))
        selected = set(ctx.settings.get("products") or [])
        rows = ctx.conn.execute(
            "SELECT o.url, o.fields_json, o.published_at FROM observations o JOIN sources s ON s.id = o.source_id "
            "WHERE o.kind = 'kb_release' AND s.enabled = 1 AND o.published_at >= ? AND o.is_demo = 0 "
            "ORDER BY o.published_at DESC", (cutoff,),
        ).fetchall()
        for r in rows:
            f = jload(r["fields_json"], {})
            prods = f.get("products") or []
            if selected and not (set(prods) & selected):
                continue
            kb = f.get("kb")
            if kb and r["url"] and kb not in targets and "support.microsoft.com" in r["url"]:
                targets[kb] = (r["url"], prods)
    all_obs: list[Observation] = []
    warnings: list[str] = []
    ok_pages = 0
    for kb, (url, prods) in list(targets.items())[:max_pages]:
        try:
            res = ctx.fetcher.get(url)
        except FetchError as exc:
            warnings.append(f"KB{kb}: {exc}")
            continue
        part = parse_kb_article(res.text, kb=kb, page_url=url, page_products=prods)
        ok_pages += 1 if part.structure_ok else 0
        all_obs.extend(part.observations)
        warnings.extend(f"KB{kb}: {w}" for w in part.warnings)
    if len(targets) > max_pages:
        warnings.append(f"{len(targets) - max_pages} KB sayfası bu çalıştırmada sınır nedeniyle atlandı.")
    if not targets:
        # "Bilinen sorun yok" değil: okunacak KB makalesi henüz yok.
        warnings.append(f"Son {days_back} güne ait KB kaydı yok; KB makaleleri güncelleme geçmişi kaynakları "
                        "toplandıktan sonra okunur.")
    structure_ok = ok_pages > 0 or not targets
    return AdapterResult(observations=all_obs, warnings=warnings, structure_ok=structure_ok,
                         fetched_url=f"{len(targets)} KB sayfası")
