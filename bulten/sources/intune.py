"""Microsoft Intune: What's new, In development ve Important notices.

Birincil okuma, Learn sayfalarının kaynağı olan MicrosoftDocs/memdocs deposundaki
markdown'dır (iş öğesi kimlikleri korunur). Yedek olarak Learn HTML'i ayrıştırılır.
Kullanıcıya gösterilen bağlantı her zaman learn.microsoft.com adresidir.

Aşama ayrımı:
  in_development  → "In development" sayfası (henüz yayınlanmadı)
  public_preview  → What's new'da başlık/metinde "(preview)" / "public preview"
  ga              → What's new'daki diğer kayıtlar (genel kullanıma açıldı / yayınlandı)
  notice          → Important notices ("Plan for change" vb.)
Kademeli dağıtım notu sayfa geneli için geçerlidir; özelliğin kullanıcının tenant'ında
açık olduğu varsayılmaz.
"""
from __future__ import annotations

import re

from ..textutil import norm_space, symptom_tags
from ..timeutil import parse_loose_date, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, slugify
from .htmlutil import main_content, soup_of, text_of
from .mdparse import applies_to, full_body_md, md_to_text, parse_front_matter, parse_sections

WEEK_RE = re.compile(r"Week of ([A-Z][a-z]+ \d{1,2}, \d{4})(?:\s*\(Service release (\d{4})\))?", re.I)

PLATFORM_MAP = [
    ("windows", ["windows"]),
    ("ios", ["ios", "ipados"]),
    ("macos", ["macos"]),
    ("android", ["android"]),
    ("linux", ["linux"]),
]

LICENSE_RE = re.compile(
    r"[^.\n]*(licen[cs]e|Intune Suite|Intune Plan 2|add-on|E3|E5|premium|requires? (?:a |an )?subscription)[^.\n]*\.",
    re.I,
)
ROLLOUT_RE = re.compile(r"[^.\n]*(gradual|rolling out|rolls out|rollout|over the coming weeks|phased)[^.\n]*\.", re.I)
ACTION_RE = re.compile(r"How can you prepare\??(.+?)(?=\n#{2,4} |\Z)", re.I | re.S)


def detect_platforms(text_items: list[str], body: str) -> list[str]:
    hay = " ".join(text_items).lower() or body.lower()
    found = [pid for pid, keys in PLATFORM_MAP if any(k in hay for k in keys)]
    return found


def detect_stage(title: str, body: str, page: str) -> str:
    if page == "in_development":
        return "in_development"
    if page == "notices":
        return "notice"
    t = (title + " " + body[:600]).lower()
    if re.search(r"\(preview\)|public preview|is (?:now )?in preview|now available in preview", t):
        return "public_preview"
    return "ga"


def detect_change_kind(title: str, body: str, page: str) -> str:
    t = (title + " " + body[:800]).lower()
    if re.search(r"deprecat|retire|end of support|no longer support|will be removed|removal|sunset|kaldırıl", t):
        return "deprecation"
    if page == "notices" or re.search(
            r"plan for change|action required|(?:you|admins?) (?:need|must|should) to take action|take action before", t):
        return "change"
    return "feature"


def _first_match(rx: re.Pattern, text: str) -> str:
    m = rx.search(text)
    return norm_space(m.group(0)) if m else ""


def _make_obs(*, title: str, ids: list[str], body_md: str, page: str, category: str, week: str | None,
              service_release: str | None, url: str) -> Observation:
    body_text = md_to_text(body_md)
    platforms_list = applies_to(body_md)
    stage = detect_stage(title, body_text, page)
    kind = detect_change_kind(title, body_text, page)
    action = ""
    m = ACTION_RE.search(body_md)
    if m:
        action = norm_space(md_to_text(m.group(1)))[:1200]
    key = f"intune:wi:{ids[0]}" if ids else f"intune:t:{slugify(title, 70)}"
    return Observation(
        external_key=key, kind="notice" if page == "notices" else "feature", title=title,
        url=url, body=body_text[:8000], published_at=to_iso(parse_loose_date(week)) if week else None,
        fields={
            "work_items": ids, "title_slug": slugify(title, 70), "stage": stage, "change_kind": kind,
            "category": category, "week": week, "service_release": service_release, "page": page,
            "platforms_raw": platforms_list, "platforms": detect_platforms(platforms_list, body_text),
            "license_note": _first_match(LICENSE_RE, body_text)[:400],
            "rollout_note": _first_match(ROLLOUT_RE, body_text)[:400],
            "admin_action": action, "tags": symptom_tags(title + " " + body_text),
        },
    )


def parse_intune_markdown(md: str, *, page: str, page_url: str, max_weeks: int = 6) -> AdapterResult:
    meta, body = parse_front_matter(md)
    sections = parse_sections(body)
    obs: list[Observation] = []
    week = sr = None
    category = ""
    weeks_seen = 0
    start = 0
    if page == "notices":
        # HTML yedeğinde tüm What's new sayfası gelir: yalnızca "Notices" başlığından sonrası alınır.
        for i, sec in enumerate(sections):
            if sec.level == 2 and "notice" in sec.title.lower():
                start = i + 1
                break
    for i, sec in enumerate(sections):
        if i < start:
            continue
        if page == "whats_new":
            if sec.level == 2:
                m = WEEK_RE.search(sec.title)
                if m:
                    weeks_seen += 1
                    week, sr = m.group(1), m.group(2)
                else:
                    week = None  # "Notices" vb.
                category = ""
                continue
            if weeks_seen > max_weeks:
                break
            if sec.level == 3:
                category = sec.title
                continue
            if sec.level == 4 and week:
                anchor = slugify(sec.title, 80)
                obs.append(_make_obs(title=sec.title, ids=sec.ids, body_md=full_body_md(sections, i), page=page,
                                     category=category, week=week, service_release=sr, url=f"{page_url}#{anchor}"))
        elif page == "in_development":
            if sec.level == 2:
                category = sec.title
                continue
            if sec.level == 3 and category and category.lower() != "notices":
                obs.append(_make_obs(title=sec.title, ids=sec.ids, body_md=full_body_md(sections, i), page=page,
                                     category=category, week=None, service_release=None,
                                     url=f"{page_url}#{slugify(sec.title, 80)}"))
        elif page == "notices":
            if sec.level == 3:
                obs.append(_make_obs(title=sec.title, ids=sec.ids, body_md=full_body_md(sections, i), page=page,
                                     category="Notices", week=None, service_release=None,
                                     url=f"{page_url}#{slugify(sec.title, 80)}"))
    page_date = to_iso(parse_loose_date(meta.get("ms.date")))
    for ob in obs:
        ob.source_updated_at = page_date
    warnings = [] if obs else ["Beklenen başlık yapısı bulunamadı."]
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=bool(obs), fetched_url=page_url)


def parse_intune_html(html: str, *, page: str, page_url: str, max_weeks: int = 6) -> AdapterResult:
    """Learn HTML yedeği: h2 (hafta/kategori) → h3 → h4 yapısını markdown'a çevirip aynı ayrıştırıcıyı kullanır."""
    soup = soup_of(html)
    root = main_content(soup)
    lines: list[str] = []
    for el in root.find_all(["h2", "h3", "h4", "p", "ul", "ol", "table", "div", "pre"], recursive=True):
        if el.name in ("h2", "h3", "h4"):
            lines.append("#" * int(el.name[1]) + " " + norm_space(el.get_text(" ", strip=True)))
        elif el.name in ("p", "ul", "ol", "table", "pre") and el.find_parent(["ul", "ol", "table", "p"]) is None:
            lines.append(text_of(el))
        elif el.name == "div" and "checklist" in " ".join(el.get("class", [])):
            items = [norm_space(li.get_text(" ", strip=True)) for li in el.find_all("li")]
            lines.append("Applies to:\n" + "\n".join("- " + i for i in items))
    md = "\n\n".join(lines)
    return parse_intune_markdown(md, page=page, page_url=page_url, max_weeks=max_weeks)


def run_intune(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    page = source.config.get("page", "whats_new")
    max_weeks = int(source.config.get("max_weeks", 6))
    res, which = fetch_with_fallback(source, ctx)
    is_md = which == "primary" and (source.fetch_url or "").endswith(".md")
    if is_md:
        out = parse_intune_markdown(res.text, page=page, page_url=source.url, max_weeks=max_weeks)
    else:
        out = parse_intune_html(res.text, page=page, page_url=source.url, max_weeks=max_weeks)
        if which == "fallback":
            out.warnings.append("Markdown kaynağına erişilemedi; Learn HTML yedeği kullanıldı.")
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out
