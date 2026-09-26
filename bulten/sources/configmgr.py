"""Configuration Manager (SCCM/MECM): sürümler, hotfix/rollup'lar, sürüm notları, Technical Preview.

Kaynak: MicrosoftDocs/memdocs (Learn sayfalarının kaynağı) — yedek: Learn HTML.
Ayrım:
  current     → Current Branch sürümü (genel kullanım)
  early_ring  → "early update ring" (erken halka)
  rollup      → update rollup
  security    → güvenlik güncellemesi
  hotfix      → diğer hotfix
  summary     → "Summary of changes" (sürüm özeti)
  tp          → Technical Preview (laboratuvar; üretim dışı)
"""
from __future__ import annotations

import re

from ..db import jload
from ..net.fetcher import FetchError
from ..textutil import norm_space, symptom_tags
from ..timeutil import now_utc, parse_loose_date, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, slugify
from .htmlutil import main_content, soup_of, text_of
from .mdparse import full_body_md, md_to_text, parse_front_matter, parse_md_table, parse_sections

LEARN_CM = "https://learn.microsoft.com/en-us/intune/configmgr/"
RAW_CM = "https://raw.githubusercontent.com/MicrosoftDocs/memdocs/main/intune/configmgr/"


def classify_hotfix(title: str) -> str:
    t = title.lower()
    if "summary of changes" in t:
        return "summary"
    if "early update ring" in t:
        return "early_ring"
    if "rollup" in t:
        return "rollup"
    if "security update" in t or "security" in t:
        return "security"
    return "hotfix"


HOTFIX_TYPE_TR = {
    "summary": "Sürüm özeti (Current Branch)", "early_ring": "Early update ring", "rollup": "Update rollup",
    "security": "Güvenlik güncellemesi", "hotfix": "Hotfix", "current": "Current Branch", "tp": "Technical Preview",
}


# --- Sürümler -------------------------------------------------------------------

def _supported_section(body: str) -> str:
    """'Supported versions' başlığından sonraki ilk tabloyu içeren bölüm (yoksa tüm metin)."""
    m = re.search(r"^#{2,5}\s+Supported versions\s*$", body, re.M | re.I)
    if not m:
        return body
    rest = body[m.end():]
    nxt = re.search(r"^#{2,5}\s+", rest, re.M)
    return rest[: nxt.start()] if nxt else rest


def _keep_version(ob: Observation) -> bool:
    end = parse_loose_date(ob.fields.get("support_end"))
    # Desteği 120 günden uzun süre önce bitmiş sürümler gürültüdür.
    return end is None or (end - now_utc()).days > -120


def parse_cm_versions_md(md: str, *, page_url: str) -> AdapterResult:
    _, body = parse_front_matter(md)
    obs: dict[str, Observation] = {}
    for row in parse_md_table(_supported_section(body)):
        if len(row) < 3:
            continue
        m = re.search(r"\*\*(\d{4})\*\*", row[0]) or re.search(r"\b(2\d{3}|1\d{3})\b", row[0])
        if not m or row[0].lower().startswith("version"):
            continue
        ver = m.group(1)
        build = (re.search(r"\((5\.\d{2}\.\d{4}(?:\.\d+)?)\)", row[0]) or [None, None])[1]
        avail = parse_loose_date(md_to_text(row[1]))
        end = parse_loose_date(md_to_text(row[2]))
        ob = _version_obs(ver, build, avail, end, row[3:] if len(row) > 3 else [], page_url)
        if _keep_version(ob) and ob.external_key not in obs:
            obs[ob.external_key] = ob
    obs = list(obs.values())
    return AdapterResult(observations=obs, structure_ok=bool(obs),
                         warnings=[] if obs else ["Desteklenen sürümler tablosu bulunamadı."], fetched_url=page_url)


def _version_obs(ver, build, avail, end, extra, page_url) -> Observation:
    baseline = md_to_text(extra[0]) if extra else ""
    in_console = md_to_text(extra[1]) if len(extra) > 1 else ""
    days_left = (end - now_utc()).days if end else None
    supported = days_left is None or days_left >= 0
    return Observation(
        external_key=f"cm:version:{ver}", kind="cm_version",
        title=f"Configuration Manager {ver} (Current Branch)", url=page_url + "#supported-versions",
        body=f"Sürüm {ver}, build {build or '?'}; erişilebilirlik {to_iso(avail) or '?'}; destek sonu {to_iso(end) or '?'}.",
        published_at=to_iso(avail),
        fields={"version": ver, "build": build, "availability": to_iso(avail), "support_end": to_iso(end),
                "baseline": baseline, "in_console": in_console, "track": "current",
                "support_days_left": days_left, "supported": supported},
    )


def parse_cm_versions_html(html: str, *, page_url: str) -> AdapterResult:
    soup = soup_of(html)
    obs = []
    for table in main_content(soup).find_all("table"):
        heads = [norm_space(th.get_text(" ", strip=True)).lower() for th in table.find_all("th")]
        if not heads or "version" not in heads[0] or not any("support end" in h for h in heads):
            continue
        for tr in table.find_all("tr"):
            tds = tr.find_all("td")
            if len(tds) < 3:
                continue
            t0 = text_of(tds[0])
            m = re.search(r"\b(2\d{3})\b", t0)
            if not m:
                continue
            build = (re.search(r"(5\.\d{2}\.\d{4}(?:\.\d+)?)", t0) or [None, None])[1]
            ob = _version_obs(m.group(1), build, parse_loose_date(text_of(tds[1])),
                              parse_loose_date(text_of(tds[2])), [text_of(t) for t in tds[3:]], page_url)
            if _keep_version(ob) and all(o.external_key != ob.external_key for o in obs):
                obs.append(ob)
        if obs:
            break
    return AdapterResult(observations=obs, structure_ok=bool(obs),
                         warnings=[] if obs else ["Desteklenen sürümler tablosu bulunamadı."], fetched_url=page_url)


def run_cm_versions(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, which = fetch_with_fallback(source, ctx)
    if which == "primary" and (source.fetch_url or "").endswith(".md"):
        out = parse_cm_versions_md(res.text, page_url=source.url)
    else:
        out = parse_cm_versions_html(res.text, page_url=source.url)
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out


# --- Hotfix / rollup --------------------------------------------------------------

def parse_hotfix_toc(yml: str) -> list[dict]:
    """TOC.yml: '- name: Version 2603' grupları altında '- name: KB …' + 'href: 2603/…md'."""
    entries: dict[str, dict] = {}
    version = None
    name = None
    for line in yml.splitlines():
        m = re.match(r"\s*-\s*name:\s*(.+)$", line)
        if m:
            name = m.group(1).strip().strip("'\"")
            vm = re.match(r"Version\s+(\d{4})", name, re.I)
            if vm:
                version, name = vm.group(1), None
            continue
        h = re.match(r"\s*href:\s*(\S+\.md)\s*$", line)
        if h and name:
            km = re.search(r"KB\s?(\d{6,9})", name)
            if km:
                kb = km.group(1)
                e = entries.setdefault(kb, {"kb": kb, "title": name, "href": h.group(1), "versions": []})
                if version and version not in e["versions"]:
                    e["versions"].append(version)
            name = None
    return list(entries.values())


def parse_hotfix_index_html(html: str) -> list[dict]:
    soup = soup_of(html)
    entries: dict[str, dict] = {}
    root = main_content(soup)
    version = None
    for el in root.find_all(["h2", "h3", "a"]):
        if el.name in ("h2", "h3"):
            vm = re.search(r"\b(2\d{3})\b", el.get_text(" ", strip=True))
            version = vm.group(1) if vm else version
            continue
        text = norm_space(el.get_text(" ", strip=True))
        km = re.search(r"KB\s?(\d{6,9})", text)
        if km and el.get("href"):
            kb = km.group(1)
            e = entries.setdefault(kb, {"kb": kb, "title": text, "href": el["href"], "versions": []})
            if version and version not in e["versions"]:
                e["versions"].append(version)
    return list(entries.values())


def parse_hotfix_detail_md(md: str) -> dict:
    meta, body = parse_front_matter(md)
    sections = parse_sections(body)
    fixed: list[str] = []
    summary = ""
    for i, sec in enumerate(sections):
        if sec.level == 2 and "fixed" in sec.title.lower():
            for sub in re.findall(r"^\s*-\s+\*\*(.+?)\*\*", sec.body_md, re.M):
                fixed.append(norm_space(sub))
        if sec.level == 2 and sec.title.lower().startswith("summary"):
            summary = md_to_text(sec.body_md)[:1500]
    text = md_to_text(body)
    return {"fixed_issues": fixed[:40], "summary": summary, "date": to_iso(parse_loose_date(meta.get("ms.date"))),
            "text": text[:8000]}


def run_cm_hotfix(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, which = fetch_with_fallback(source, ctx)
    if which == "primary" and (source.fetch_url or "").endswith(".yml"):
        entries = parse_hotfix_toc(res.text)
    else:
        entries = parse_hotfix_index_html(res.text)
    known = {
        r["external_key"]: (jload(r["fields_json"], {}), r["body"] or "")
        for r in ctx.conn.execute("SELECT external_key, fields_json, body FROM observations WHERE source_id = ?",
                                  (source.id,))
    }
    max_details = int(source.config.get("max_details", 6))
    # Yalnızca son ~2 yılın sürümlerine ait KB'ler (eski arşiv gürültüdür).
    min_version = int(source.config.get("min_version") or f"{(now_utc().year - 2) % 100:02d}00")
    entries = [e for e in entries if not e["versions"] or max(int(v) for v in e["versions"]) >= min_version]
    warnings = []
    obs = []
    details_fetched = 0
    for e in entries:
        key = f"cm:kb:{e['kb']}"
        href = e["href"]
        rel = href[:-3] if href.endswith(".md") else href
        learn_url = rel if rel.startswith("http") else LEARN_CM + "hotfix/" + rel.lstrip("./")
        prev, body = known.get(key) or ({}, "")
        detail = {k: prev.get(k) for k in ("fixed_issues", "summary", "date") if prev.get(k)}
        if not prev.get("fixed_issues") and details_fetched < max_details and href.endswith(".md"):
            try:
                d = ctx.fetcher.get(RAW_CM + "hotfix/" + href.lstrip("./"))
                parsed = parse_hotfix_detail_md(d.text)
                detail = {k: parsed[k] for k in ("fixed_issues", "summary", "date") if parsed.get(k)}
                body = parsed["text"]
                details_fetched += 1
            except FetchError as exc:
                warnings.append(f"KB{e['kb']} ayrıntısı okunamadı: {exc}")
        htype = classify_hotfix(e["title"])
        title = re.sub(r"^KB\s?\d+\s*", "", e["title"]).strip()
        obs.append(Observation(
            external_key=key, kind="cm_hotfix", title=f"ConfigMgr KB{e['kb']}: {title}", url=learn_url,
            body=body or title, published_at=detail.get("date"),
            fields={"kb": e["kb"], "versions": sorted(e["versions"]), "hotfix_type": htype,
                    "track": "early_ring" if htype == "early_ring" else "current",
                    "fixed_issues": detail.get("fixed_issues") or [], "summary": detail.get("summary") or "",
                    "date": detail.get("date"), "tags": symptom_tags(title + " " + (body or ""))},
        ))
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=bool(obs),
                         fetched_url=res.url, http_status=res.status, not_modified=res.not_modified)


# --- Sürüm notları (bilinen sorunlar) ve Technical Preview ---------------------

def parse_cm_release_notes_md(md: str, *, page_url: str) -> AdapterResult:
    meta, body = parse_front_matter(md)
    sections = parse_sections(body)
    obs = []
    category = ""
    for i, sec in enumerate(sections):
        if sec.level == 2:
            category = sec.title
            continue
        if sec.level == 3 and category:
            text_md = full_body_md(sections, i)
            m = re.search(r"Applies to:?\s*version[s]?\s*([\d,\sand]+)", md_to_text(text_md), re.I)
            versions = re.findall(r"\d{4}", m.group(1)) if m else []
            text = md_to_text(text_md)
            obs.append(Observation(
                external_key=f"cm:rn:{slugify(sec.title, 70)}", kind="cm_known_issue", title=sec.title,
                url=f"{page_url}#{slugify(sec.title, 80)}", body=text[:6000],
                source_updated_at=to_iso(parse_loose_date(meta.get("ms.date"))),
                fields={"category": category, "versions": versions, "status": "confirmed",
                        "status_raw": "Release notes", "workaround": _workaround(text),
                        "tags": symptom_tags(sec.title + " " + text), "products": [], "track": "current"},
            ))
    return AdapterResult(observations=obs, structure_ok=bool(obs),
                         warnings=[] if obs else ["Sürüm notu başlıkları bulunamadı."], fetched_url=page_url)


def _workaround(text: str) -> str:
    m = re.search(r"(?:Workaround|To work around this issue|Resolution)\s*:?\s*(.+)", text, re.I | re.S)
    return norm_space(m.group(1))[:1500] if m else ""


def parse_cm_tp_md(md: str, *, page_url: str, max_versions: int = 3) -> AdapterResult:
    meta, body = parse_front_matter(md)
    sections = parse_sections(body)
    obs = []
    for i, sec in enumerate(sections):
        m = re.match(r"Technical preview version (\d{4})", sec.title, re.I)
        if sec.level == 3 and m:
            ver = m.group(1)
            text = md_to_text(full_body_md(sections, i))
            yy, mm = int(ver[:2]), int(ver[2:])
            pub = to_iso(parse_loose_date(f"20{yy:02d}-{mm:02d}-01")) if 1 <= mm <= 12 else None
            obs.append(Observation(
                external_key=f"cm:tp:{ver}", kind="cm_version", title=f"ConfigMgr Technical Preview {ver}",
                url=page_url, body=text[:5000], published_at=pub,
                fields={"version": ver, "track": "tp", "hotfix_type": "tp"},
            ))
            if len(obs) >= max_versions:
                break
    return AdapterResult(observations=obs, structure_ok=bool(obs),
                         warnings=[] if obs else ["Technical Preview sürüm başlıkları bulunamadı."], fetched_url=page_url)


def _html_to_md_headings(html: str) -> str:
    soup = soup_of(html)
    root = main_content(soup)
    parts = []
    for el in root.find_all(["h2", "h3", "h4", "p", "ul", "ol", "table"]):
        if el.name.startswith("h"):
            parts.append("#" * int(el.name[1]) + " " + norm_space(el.get_text(" ", strip=True)))
        elif el.find_parent(["ul", "ol", "table", "p"]) is None:
            parts.append(text_of(el))
    return "\n\n".join(parts)


def run_cm_release_notes(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, which = fetch_with_fallback(source, ctx)
    md = res.text if which == "primary" and (source.fetch_url or "").endswith(".md") else _html_to_md_headings(res.text)
    out = parse_cm_release_notes_md(md, page_url=source.url)
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out


def run_cm_tp(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, which = fetch_with_fallback(source, ctx)
    md = res.text if which == "primary" and (source.fetch_url or "").endswith(".md") else _html_to_md_headings(res.text)
    out = parse_cm_tp_md(md, page_url=source.url)
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out
