"""Kanıt gücü sınıflandırması ve bağımsız kaynak sayımı.

Teyit etiketleri (risk seviyesinden ayrıdır):
  ms_known_issue → "Microsoft doğruladı — Known issues" (Microsoft'un Known issues kaydında açıkça var)
  ms_official    → "Microsoft resmî açıklaması" (başka resmî Microsoft kaynağında açık teyit; Known issues ayrıca kontrol edildi)
  field          → "Saha bildirimi — Microsoft teyidi bulunamadı"

Microsoft alan adındaki topluluk içerikleri (Q&A, Tech Community tartışmaları, answers.microsoft.com)
resmî sayılmaz. Teyit bulunamaması Microsoft'un sorunu reddettiği anlamına gelmez.
"""
from __future__ import annotations

import re
from urllib.parse import urlsplit

from ..textutil import near_duplicate_text

EVIDENCE_LABELS = {
    "ms_known_issue": "Microsoft doğruladı — Known issues",
    "ms_official": "Microsoft resmî açıklaması",
    "field": "Saha bildirimi — Microsoft teyidi bulunamadı",
    "official_doc": "Resmî Microsoft belgesi",
    "press": "Basın",
}

OFFICIAL_BLOG_BOARDS = {
    "intunecustomersuccess", "windows-itpro-blog", "windowsitpro", "configurationmanagerblog",
    "windowsservernewsandbestpractices", "microsoftintuneblog", "windows-servicing", "msrc",
    "coreinfrastructureandsecurityblog", "askds", "networkingblog", "itopstalkblog",
}

COMMUNITY_PATTERNS = [
    re.compile(r"^https?://(?:[a-z-]+\.)?learn\.microsoft\.com/[^/]+/answers/", re.I),
    re.compile(r"^https?://answers\.microsoft\.com/", re.I),
    re.compile(r"^https?://social\.(?:technet|msdn)\.microsoft\.com/", re.I),
    re.compile(r"^https?://techcommunity\.microsoft\.com/(?:discussions|t5/[^/]+/(?:[^/]+/)?(?:m-p|td-p|qaq-p)/)", re.I),
    re.compile(r"^https?://feedbackportal\.microsoft\.com/", re.I),
    re.compile(r"^https?://github\.com/", re.I),
    re.compile(r"^https?://(?:www\.|old\.)?reddit\.com/", re.I),
]

OFFICIAL_PATTERNS = [
    re.compile(r"^https?://learn\.microsoft\.com/(?!.*/answers/)(?!.*/archive/)", re.I),
    re.compile(r"^https?://support\.microsoft\.com/", re.I),
    re.compile(r"^https?://msrc\.microsoft\.com/", re.I),
    re.compile(r"^https?://blogs\.windows\.com/", re.I),
    re.compile(r"^https?://www\.microsoft\.com/[^/]+/security/blog/", re.I),
]

PRESS_DOMAINS = {
    "bleepingcomputer.com", "borncity.com", "windowslatest.com", "theregister.com", "neowin.net",
    "windowscentral.com", "askwoody.com", "theverge.com", "arstechnica.com", "zdnet.com", "computerworld.com",
    "petri.com", "windowsforum.com", "securityweek.com", "helpnetsecurity.com", "techradar.com", "webrazzi.com",
    "shiftdelete.net", "donanimhaber.com", "chip.com.tr",
}


def classify_url(url: str | None) -> str:
    """URL'ye göre güven düzeyi: official|community|press|unknown."""
    if not url:
        return "unknown"
    for pat in COMMUNITY_PATTERNS:
        if pat.search(url):
            return "community"
    m = re.match(r"^https?://techcommunity\.microsoft\.com/(?:blog|category/[^/]+/blog|t5/[^/]+/bg-p|t5/([^/]+)/ba-p)/?([^/?#]*)",
                 url, re.I)
    if m:
        board = (m.group(2) or m.group(1) or "").lower()
        return "official" if board in OFFICIAL_BLOG_BOARDS else "community"
    for pat in OFFICIAL_PATTERNS:
        if pat.search(url):
            return "official"
    dom = registrable_domain(url)
    if dom in PRESS_DOMAINS:
        return "press"
    return "unknown"


def effective_trust(source_trust: str, url: str | None, fields: dict | None = None) -> str:
    """Kaynağın güven düzeyi ile URL kurallarını birleştirir (topluluk URL'si asla resmî olamaz)."""
    by_url = classify_url(url)
    if by_url == "community":
        return "community"
    if source_trust == "official":
        # Resmî blog beslemesi bile olsa tartışma sayfalarına işaret eden kayıtlar resmî değildir.
        return "official" if by_url in ("official", "unknown") else by_url
    if source_trust in ("unknown", "user"):
        return by_url
    return source_trust


def registrable_domain(url: str | None) -> str:
    host = (urlsplit(url or "").hostname or "").lower()
    parts = host.split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:]) if len(parts) >= 2 else host


def evidence_for_observation(kind: str, trust: str) -> str | None:
    if trust == "official":
        if kind in ("known_issue", "cm_known_issue"):
            return "ms_known_issue"
        return "ms_official"
    return "field"


def count_independent(items: list[dict]) -> int:
    """Bağımsız saha kaynağı sayısı.

    Aynı metni kopyalayan (sendikasyon) yayınlar ve birbirine atıf yapanlar tek kaynak sayılır.
    Aynı alan adındaki farklı yazarların gönderileri (ör. Reddit) ayrı raporlardır; aynı alan
    adındaki basın makaleleri tek kaynak sayılır.
    items: {"url", "title", "body", "trust", "author"}
    """
    n = len(items)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i: int, j: int) -> None:
        pi, pj = find(i), find(j)
        if pi != pj:
            parent[pj] = pi

    doms = [registrable_domain(it.get("url")) for it in items]
    for i in range(n):
        for j in range(i + 1, n):
            a, b = items[i], items[j]
            text_a = f"{a.get('title', '')}\n{a.get('body', '')}"
            text_b = f"{b.get('title', '')}\n{b.get('body', '')}"
            if near_duplicate_text(text_a, text_b):
                union(i, j)
                continue
            if doms[i] == doms[j] and a.get("trust") == "press":
                union(i, j)
                continue
            if doms[i] == doms[j] and a.get("author") and a.get("author") == b.get("author"):
                union(i, j)
                continue
            # atıf: bir metin diğerinin alan adını kaynak olarak anıyor ("via bleepingcomputer")
            if doms[j] and re.search(rf"(?:via|according to|reported by|kaynak:?)\s+\S*{re.escape(doms[j].split('.')[0])}",
                                     text_a, re.I):
                union(i, j)
            elif doms[i] and re.search(rf"(?:via|according to|reported by|kaynak:?)\s+\S*{re.escape(doms[i].split('.')[0])}",
                                       text_b, re.I):
                union(i, j)
    return len({find(i) for i in range(n)})
