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
from ..textutil import extract_builds, extract_kbs, extract_products, norm_space, symptom_tags
from ..timeutil import now_utc, parse_loose_date, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, short_hash
from .htmlutil import main_content, soup_of, text_of

TITLE_RE = re.compile(
    r"(?P<date>[A-Z][a-z]+\.? \d{1,2},? \d{4})\s*[—–\-]+\s*(?P<hot>Hotpatch\s+)?KB\s?(?P<kb>\d{6,8})\s*"
    r"\((?P<builds>OS Builds?[^)]*)\)\s*(?P<suffix>[^|]*)",
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


def parse_update_history(html: str, *, page_url: str, page_products: list[str],
                         months_back: int = 4) -> AdapterResult:
    soup = soup_of(html)
    root = main_content(soup)
    cutoff = now_utc() - timedelta(days=31 * months_back)
    seen: dict[str, Observation] = {}
    candidates: list[tuple[str, str | None]] = []
    for a in root.find_all("a"):
        candidates.append((norm_space(a.get_text(" ", strip=True)), a.get("href")))
    if not candidates:
        for line in text_of(root).split("\n"):
            candidates.append((norm_space(line), None))
    for text, href in candidates:
        m = TITLE_RE.search(text)
        if not m:
            continue
        kb = m.group("kb")
        date = parse_loose_date(m.group("date").replace(".", ""))
        if date is None or date < cutoff:
            continue
        builds = extract_builds(m.group("builds"))
        title = norm_space(m.group(0))
        rtype = classify_release(title, bool(m.group("hot")), date)
        products = set(page_products)
        products.update(extract_products(" ".join(builds)) if not page_products else [])
        ob = seen.get(kb)
        if ob is None:
            seen[kb] = Observation(
                external_key=f"kb:{kb}", kind="kb_release", title=title,
                url=urljoin(page_url, href) if href else page_url, published_at=to_iso(date),
                body=title,
                fields={"kb": kb, "builds": builds, "release_type": rtype, "products": sorted(products),
                        "expired": "expired" in title.lower()},
            )
    obs = list(seen.values())
    warnings = [] if obs else ["Bu sayfada son aylara ait KB bağlantısı bulunamadı (yapı değişmiş olabilir)."]
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=bool(obs), fetched_url=page_url)


def run_update_history(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, _ = fetch_with_fallback(source, ctx)
    out = parse_update_history(res.text, page_url=source.url, page_products=source.product_ids,
                               months_back=int(source.config.get("months_back", 4)))
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out


# --- KB makalesi: "Known issues in this update" --------------------------------

NO_ISSUES_RE = re.compile(r"(not currently aware of any issues|no known issues)", re.I)


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


def parse_kb_article(html: str, *, kb: str, page_url: str, page_products: list[str]) -> AdapterResult:
    soup = soup_of(html)
    root = main_content(soup)
    heading, nodes = _known_issues_block(root)
    obs: list[Observation] = []
    if heading is None:
        return AdapterResult(observations=[], warnings=["'Known issues' bölümü bulunamadı."],
                             structure_ok=False, fetched_url=page_url)
    block_text = "\n".join(text_of(n) for n in nodes)
    if NO_ISSUES_RE.search(block_text) and len(block_text) < 400:
        return AdapterResult(observations=[], structure_ok=True, fetched_url=page_url,
                             warnings=[], http_status=200)
    issues: list[tuple[str, str, str]] = []  # (başlık, belirti, geçici çözüm)
    for n in nodes:
        if not isinstance(n, Tag):
            continue
        tables = [n] if n.name == "table" else n.find_all("table")
        for table in tables:
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
                issues.append((title, symptom, workaround))
    if not issues:
        # Tablo yoksa alt başlık / kalın paragraf bazlı bölme
        current: list[str] = []
        title = ""
        for n in nodes:
            if not isinstance(n, Tag):
                continue
            is_head = n.name in ("h3", "h4", "h5") or (
                n.name == "p" and n.find(["b", "strong"]) is not None
                and norm_space(n.get_text()) == norm_space(n.find(["b", "strong"]).get_text()))
            if is_head:
                if title and current:
                    issues.append((title, "\n".join(current), ""))
                title, current = norm_space(n.get_text(" ", strip=True)), []
            else:
                t = text_of(n)
                if t:
                    current.append(t)
        if title and current:
            issues.append((title, "\n".join(current), ""))
        if not issues and block_text.strip():
            issues.append((f"KB{kb} bilinen sorun", block_text, ""))
    for title, symptom, workaround in issues:
        body = symptom + ("\n\nWorkaround: " + workaround if workaround else "")
        wa = workaround
        if not wa:
            m = re.search(r"(?:Workaround|Resolution|Mitigation)\s*:?\s*(.+)", symptom, re.I | re.S)
            wa = norm_space(m.group(1)) if m else ""
        resolved = bool(re.search(r"(this issue (?:is|was) (?:now )?resolved|resolved in KB|has been resolved)", body, re.I))
        obs.append(Observation(
            external_key=f"kbki:{kb}:{short_hash(norm_space(title).lower()[:90])}", kind="known_issue",
            title=norm_space(title)[:300], url=page_url + "#known-issues", body=body[:8000],
            fields={
                "kb": kb, "originating_kbs": [kb], "workaround": norm_space(wa)[:2000],
                "status": "resolved" if resolved else "confirmed", "status_raw": "KB Known issues",
                "resolving_kbs": sorted(set(extract_kbs(body)) - {kb}) if resolved else [],
                "products": sorted(set(page_products) | set(extract_products(body))),
                "tags": symptom_tags(title + " " + body), "kir": "known issue rollback" in body.lower(),
                "from": "kb_article",
            },
        ))
    return AdapterResult(observations=obs, structure_ok=True, fetched_url=page_url)


def run_kb_articles(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    """Son yayımlanan KB'lerin (update history'den) makalelerini okur ve bilinen sorunları çıkarır.

    Yalnızca son 24 saatte yayımlananlar değil, `days_back` içindeki tüm KB'ler her
    çalıştırmada yeniden kontrol edilir (bilinen sorunlar sonradan eklenir/çözülür).
    """
    days_back = int(source.config.get("days_back", 60))
    max_pages = int(source.config.get("max_pages", 15))
    cutoff = to_iso(now_utc() - timedelta(days=days_back))
    selected = set(ctx.settings.get("products") or [])
    rows = ctx.conn.execute(
        "SELECT o.url, o.fields_json, o.published_at FROM observations o JOIN sources s ON s.id = o.source_id "
        "WHERE o.kind = 'kb_release' AND s.enabled = 1 AND o.published_at >= ? AND o.is_demo = 0 "
        "ORDER BY o.published_at DESC", (cutoff,),
    ).fetchall()
    targets: dict[str, tuple[str, list[str]]] = {}
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
    structure_ok = ok_pages > 0 or not targets
    return AdapterResult(observations=all_obs, warnings=warnings, structure_ok=structure_ok,
                         fetched_url=f"{len(targets)} KB sayfası")
