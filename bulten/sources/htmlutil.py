"""HTML'den okunabilir düz metin çıkarma yardımcıları."""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, NavigableString, Tag

BLOCK_TAGS = {
    "p", "div", "section", "article", "li", "ul", "ol", "table", "tr", "br", "h1", "h2", "h3", "h4",
    "h5", "h6", "pre", "blockquote", "details", "summary", "dd", "dt", "dl", "header", "footer",
}


def soup_of(html: str) -> BeautifulSoup:
    return BeautifulSoup(html, "lxml")


def text_of(node: Tag | NavigableString | None, *, sep_cells: str = " · ") -> str:
    """Blok öğeleri satır sonuyla ayırarak metin üretir."""
    if node is None:
        return ""
    if isinstance(node, NavigableString):
        return str(node)
    parts: list[str] = []
    _walk(node, parts, sep_cells)
    text = "".join(parts)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t\r\f\v]+", " ", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _walk(node: Tag, parts: list[str], sep_cells: str) -> None:
    for child in node.children:
        if isinstance(child, NavigableString):
            if child.__class__.__name__ in ("Comment", "Doctype", "Declaration", "ProcessingInstruction"):
                continue
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name.lower()
        if name in ("script", "style", "noscript", "template", "svg", "button", "nav"):
            continue
        if name == "br":
            parts.append("\n")
            continue
        if name in ("td", "th"):
            _walk(child, parts, sep_cells)
            parts.append(sep_cells)
            continue
        if name == "li":
            parts.append("\n• ")
            _walk(child, parts, sep_cells)
            parts.append("\n")
            continue
        block = name in BLOCK_TAGS
        if block:
            parts.append("\n")
        _walk(child, parts, sep_cells)
        if block:
            parts.append("\n")


def main_content(soup: BeautifulSoup) -> Tag:
    for sel in ("main#main", "main", "div.content", "article", "#main-column", "body"):
        found = soup.select_one(sel)
        if found is not None:
            return found
    return soup


def page_updated_date(soup: BeautifulSoup) -> str | None:
    """Learn sayfalarının meta verisinden güncelleme tarihi."""
    for attr in ("ms.date", "updated_at", "article:modified_time"):
        meta = soup.find("meta", attrs={"name": attr}) or soup.find("meta", attrs={"property": attr})
        if meta and meta.get("content"):
            return meta["content"]
    t = soup.find("time", attrs={"data-article-date": True}) or soup.find("time")
    if t and (t.get("datetime") or t.get_text(strip=True)):
        return t.get("datetime") or t.get_text(strip=True)
    return None
