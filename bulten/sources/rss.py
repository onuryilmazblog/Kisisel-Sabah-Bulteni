"""Genel RSS/Atom adaptörü: haberler, teknoloji yayınları, topluluklar (Reddit vb.), bloglar, YouTube.

Topluluk ve basın kaynaklarında yalnızca takip edilen kapsamla (Windows/Intune/ConfigMgr)
ilgili ve sorun bildirimi gibi görünen kayıtlar "saha raporu" (field_report) olarak alınır.
Bir Microsoft alan adındaki topluluk mesajı (Q&A, Tech Community tartışması) resmî sayılmaz:
güven düzeyi kaynağın `trust` alanından ve URL kurallarından gelir (bkz. pipeline/evidence.py).
"""
from __future__ import annotations

import calendar
import re
from datetime import datetime, timedelta, timezone

import feedparser

from ..textutil import (
    extract_cves, extract_kbs, extract_products, looks_like_issue_report, mentions_tracked_scope, norm_space,
    symptom_tags,
)
from ..timeutil import now_utc, to_iso
from .base import AdapterContext, AdapterResult, Observation, SourceRow, fetch_with_fallback, short_hash
from .htmlutil import soup_of, text_of


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        tm = entry.get(key)
        if tm:
            return datetime.fromtimestamp(calendar.timegm(tm), tz=timezone.utc)
    return None


def _clean_html(html: str) -> str:
    if not html:
        return ""
    if "<" not in html:
        return norm_space(html)
    return text_of(soup_of(html))


def canonical_url(url: str | None) -> str | None:
    if not url:
        return url
    u = re.sub(r"[?&](utm_[^=&]+|fbclid|gclid|ref|cmpid|at_[a-z_]+)=[^&#]*", "", url)
    u = u.replace("?&", "?").rstrip("?")
    return u


def parse_feed(text: str, *, source: SourceRow, max_age_days: int = 7, max_items: int = 60) -> AdapterResult:
    parsed = feedparser.parse(text)
    if parsed.bozo and not parsed.entries:
        return AdapterResult(observations=[], structure_ok=False,
                             warnings=[f"Besleme ayrıştırılamadı: {parsed.get('bozo_exception')}"])
    cutoff = now_utc() - timedelta(days=max_age_days)
    module = source.module
    feed_lang = (parsed.feed.get("language") or source.config.get("lang") or "").split("-")[0].lower() or None
    obs: list[Observation] = []
    for entry in parsed.entries[: max_items * 2]:
        title = norm_space(entry.get("title", ""))
        link = canonical_url(entry.get("link"))
        if not title or not link:
            continue
        ts = _entry_time(entry)
        if ts is not None and ts < cutoff:
            continue
        summary_html = entry.get("summary") or ""
        if not summary_html and entry.get("content"):
            summary_html = entry["content"][0].get("value", "")
        if not summary_html and entry.get("media_description"):
            summary_html = entry.get("media_description")
        summary = _clean_html(summary_html)[:4000]
        full = f"{title}\n{summary}"
        guid = entry.get("id") or entry.get("guid") or link
        fields = {
            "source_name": source.name, "author": entry.get("author"), "trust": source.trust,
            "categories": [t.get("term") for t in entry.get("tags", []) if t.get("term")][:10],
            "kbs": extract_kbs(full), "products": extract_products(full), "tags": symptom_tags(full),
            "cves": extract_cves(full), "canonical_url": link, "summary": summary[:1500],
        }
        if module in ("community", "press"):
            if not mentions_tracked_scope(full):
                continue
            kind = "field_report" if looks_like_issue_report(full) else "article"
            if kind == "article" and not source.config.get("keep_articles", False):
                continue
        elif module == "news":
            kind = "article"
            fields["news_category"] = source.category
        else:
            kind = "content"
            if entry.get("yt_videoid"):
                fields["youtube_id"] = entry.get("yt_videoid")
                fields["transcript"] = None
        obs.append(Observation(
            external_key="rss:" + short_hash(str(guid), 16), kind=kind, title=title, url=link, body=summary,
            lang=feed_lang or ("tr" if re.search(r"[çğıöşüİ]", full) else "en"),
            published_at=to_iso(ts), source_updated_at=to_iso(ts), fields=fields,
        ))
        if len(obs) >= max_items:
            break
    return AdapterResult(observations=obs, structure_ok=True)


def run_rss(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    res, _ = fetch_with_fallback(
        source, ctx, accept="application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.5")
    out = parse_feed(res.text, source=source, max_age_days=int(source.config.get("max_age_days", 7)),
                     max_items=int(source.config.get("max_items", 60)))
    out.fetched_url, out.http_status, out.not_modified = res.url, res.status, res.not_modified
    return out
