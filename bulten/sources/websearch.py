"""Yapılandırılabilir web araması: yalnızca RSS'e bağlı kalmadan yeni saha raporlarını keşfetmek için.

Sağlayıcılar: Brave Search API (anahtar gerekir) veya kendi SearXNG örneğiniz (JSON çıktısı açık olmalı).
Sonuçlar yalnızca başlık+özet içerir; bu kayıtlar "yalnızca arama özeti" olarak işaretlenir.
Tüm internetin tarandığı iddia edilmez: sorgu listesi ve sağlayıcı kapsam ekranında gösterilir.
"""
from __future__ import annotations

import json
from datetime import timedelta
from urllib.parse import urlencode

from ..config import load_config
from ..db import jload
from ..net.fetcher import FetchError
from ..textutil import extract_kbs, extract_products, looks_like_issue_report, norm_space, symptom_tags
from ..timeutil import now_utc, parse_loose_date, to_iso
from ..usage import record, search_budget_left
from .base import AdapterContext, AdapterResult, Observation, SourceRow, short_hash
from .rss import canonical_url


def build_queries(ctx: AdapterContext, max_queries: int = 6) -> list[str]:
    settings = ctx.settings
    selected = set(settings.get("products") or [])
    cutoff = to_iso(now_utc() - timedelta(days=21))
    rows = ctx.conn.execute(
        "SELECT fields_json FROM observations WHERE kind = 'kb_release' AND published_at >= ? AND is_demo = 0 "
        "ORDER BY published_at DESC LIMIT 40", (cutoff,),
    ).fetchall()
    kbs: list[str] = []
    for r in rows:
        f = jload(r["fields_json"], {})
        if f.get("release_type") in ("security", "oob", "preview") and (not selected or set(f.get("products") or []) & selected):
            if f.get("kb") and f["kb"] not in kbs:
                kbs.append(f["kb"])
    queries = []
    for kb in kbs[:3]:
        queries.append(f"KB{kb} issue OR problem OR broken")
    if settings.get("modules", {}).get("intune"):
        queries.append("Intune issue this week admins reporting")
    if settings.get("modules", {}).get("configmgr"):
        queries.append("ConfigMgr SCCM update problem")
    for topic in settings.get("topics") or []:
        queries.append(str(topic))
    return queries[:max_queries]


def _search_brave(ctx: AdapterContext, q: str) -> list[dict]:
    cfg = load_config()
    url = "https://api.search.brave.com/res/v1/web/search?" + urlencode({"q": q, "freshness": "pw", "count": 10})
    res = ctx.fetcher.get(url, trusted=True, use_cache=False, accept="application/json",
                          extra_headers={"X-Subscription-Token": cfg.brave_api_key})
    data = json.loads(res.text)
    out = []
    for item in (data.get("web") or {}).get("results", []):
        out.append({"title": item.get("title"), "url": item.get("url"), "snippet": item.get("description"),
                    "date": item.get("page_age") or item.get("age")})
    return out


def _search_searxng(ctx: AdapterContext, q: str) -> list[dict]:
    cfg = load_config()
    url = f"{cfg.searxng_url}/search?" + urlencode({"q": q, "format": "json", "time_range": "week"})
    res = ctx.fetcher.get(url, trusted=True, use_cache=False, accept="application/json")
    data = json.loads(res.text)
    return [{"title": i.get("title"), "url": i.get("url"), "snippet": i.get("content"),
             "date": i.get("publishedDate")} for i in data.get("results", [])[:10]]


def run_web_search(source: SourceRow, ctx: AdapterContext) -> AdapterResult:
    cfg = load_config()
    if not cfg.search_configured:
        return AdapterResult(observations=[], structure_ok=True,
                             warnings=["Web arama sağlayıcısı yapılandırılmadı (SEARCH_PROVIDER)."],
                             fetched_url="(kapalı)")
    queries = build_queries(ctx, int(source.config.get("max_queries", 6)))
    obs: list[Observation] = []
    warnings: list[str] = []
    done = 0
    for q in queries:
        ok, why = search_budget_left(ctx.conn, cfg)
        if not ok:
            warnings.append(why)
            break
        try:
            results = _search_brave(ctx, q) if cfg.search_provider == "brave" else _search_searxng(ctx, q)
            record(ctx.conn, provider=cfg.search_provider, kind="search", note=q[:120])
            done += 1
        except (FetchError, ValueError) as exc:
            record(ctx.conn, provider=cfg.search_provider, kind="search", ok=False, note=str(exc)[:200])
            warnings.append(f"'{q}': {exc}")
            continue
        for r in results:
            title, url = norm_space(r.get("title") or ""), canonical_url(r.get("url"))
            snippet = norm_space(r.get("snippet") or "")
            if not title or not url:
                continue
            full = title + "\n" + snippet
            if not looks_like_issue_report(full):
                continue
            obs.append(Observation(
                external_key="ws:" + short_hash(url, 16), kind="field_report", title=title, url=url, body=snippet,
                published_at=to_iso(parse_loose_date(r.get("date"))),
                fields={"query": q, "snippet_only": True, "kbs": extract_kbs(full), "products": extract_products(full),
                        "tags": symptom_tags(full), "canonical_url": url, "source_name": "Web araması",
                        "trust": "unknown"},
            ))
    return AdapterResult(observations=obs, warnings=warnings, structure_ok=True,
                         fetched_url=f"{cfg.search_provider}: {done}/{len(queries)} sorgu")
