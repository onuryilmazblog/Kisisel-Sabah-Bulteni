"""Microsoft Learn markdown kaynakları (MicrosoftDocs depoları) için küçük ayrıştırıcı."""
from __future__ import annotations

import re
from dataclasses import dataclass, field

_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_COMMENT = re.compile(r"<!--(.*?)-->", re.S)
_FENCE = re.compile(r"^\s*(```|~~~)")


@dataclass
class MdSection:
    level: int
    title: str
    raw_title: str
    ids: list[str]
    body_md: str
    index: int = 0
    tags: list[str] = field(default_factory=list)


def parse_front_matter(md: str) -> tuple[dict[str, str], str]:
    meta: dict[str, str] = {}
    if md.startswith("---"):
        end = md.find("\n---", 3)
        if end != -1:
            block = md[3:end]
            for line in block.splitlines():
                if ":" in line and not line.startswith(" ") and not line.startswith("-"):
                    k, _, v = line.partition(":")
                    meta[k.strip()] = v.strip().strip("'\"")
            md = md[end + 4:]
    return meta, md


def clean_heading(raw: str) -> tuple[str, list[str], list[str]]:
    """Başlıktan HTML yorumlarını/çapaları temizler; yorumdaki iş öğesi kimliklerini döndürür."""
    ids: list[str] = []
    tags: list[str] = []
    for m in _COMMENT.finditer(raw):
        content = m.group(1)
        ids.extend(re.findall(r"\b\d{5,9}\b", content))
        tags.extend(t for t in re.findall(r"[a-z]{4,}", content.lower()))
    text = _COMMENT.sub("", raw)
    text = re.sub(r"<a\s+name=\"?[^>]*>\s*</a>", "", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = text.replace("**", "").replace("__", "").strip()
    return text, ids, tags


def parse_sections(md: str) -> list[MdSection]:
    sections: list[MdSection] = []
    current: MdSection | None = None
    buf: list[str] = []
    in_fence = False
    preamble = MdSection(level=0, title="", raw_title="", ids=[], body_md="")
    for line in md.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
        m = None if in_fence else _HEADING.match(line)
        if m:
            target = current or preamble
            target.body_md = "\n".join(buf).strip("\n")
            buf = []
            title, ids, tags = clean_heading(m.group(2))
            current = MdSection(level=len(m.group(1)), title=title, raw_title=m.group(2), ids=ids,
                                body_md="", index=len(sections), tags=tags)
            sections.append(current)
        else:
            buf.append(line)
    target = current or preamble
    target.body_md = "\n".join(buf).strip("\n")
    return [preamble] + sections if preamble.body_md else sections


def full_body_md(sections: list[MdSection], idx: int) -> str:
    """Bölümün kendi gövdesi + alt başlıkları (bir sonraki eş/üst başlığa kadar)."""
    base = sections[idx]
    parts = [base.body_md]
    for sec in sections[idx + 1:]:
        if sec.level <= base.level:
            break
        parts.append("#" * sec.level + " " + sec.title)
        parts.append(sec.body_md)
    return "\n\n".join(p for p in parts if p)


_ALERT = {
    "NOTE": "Not:", "TIP": "İpucu:", "IMPORTANT": "Önemli:", "WARNING": "Uyarı:", "CAUTION": "Dikkat:",
}


def md_to_text(md: str) -> str:
    text = _COMMENT.sub("", md)
    out_lines: list[str] = []
    in_fence = False
    for line in text.splitlines():
        if _FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            out_lines.append("    " + line)
            continue
        s = line.rstrip()
        s = re.sub(r"^\s*>\s?", "", s)
        s = re.sub(r"^#{1,6}\s+", "", s)  # alt başlıklar düz metin satırı olur
        m = re.match(r"^\s*\[!(\w+)\]\s*$", s)
        if m:
            out_lines.append(_ALERT.get(m.group(1).upper(), ""))
            continue
        if re.match(r"^\s*\[!div[^\]]*\]\s*$", s):
            continue
        if re.match(r"^\s*\|?\s*:?-{3,}", s):
            continue  # tablo ayırıcı satırı
        s = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", s)
        s = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", s)
        s = re.sub(r"\[([^\]]+)\]\[[^\]]*\]", r"\1", s)
        s = re.sub(r"<br\s*/?>", " ", s, flags=re.I)
        s = re.sub(r"<[^>]+>", "", s)
        s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
        s = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"\1", s)
        s = re.sub(r"(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])", r"\1", s)
        s = re.sub(r"`([^`]+)`", r"\1", s)
        s = re.sub(r"^\s*[-*+]\s+", "• ", s)
        s = re.sub(r"^\s*\|\s*|\s*\|\s*$", "", s) if s.strip().startswith("|") else s
        s = s.replace(" | ", " · ") if "|" in s else s
        s = s.replace("&nbsp;", " ").replace("&amp;", "&")
        out_lines.append(s)
    result = "\n".join(out_lines)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.strip()


def parse_md_table(md: str) -> list[list[str]]:
    rows = []
    for line in md.splitlines():
        s = line.strip()
        if not s.startswith("|"):
            continue
        if re.match(r"^\|\s*:?-{3,}", s):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        rows.append(cells)
    return rows


def applies_to(md: str) -> list[str]:
    """'Applies to:' kontrol listesindeki platformları döndürür."""
    m = re.search(r"Applies to:?\s*\n((?:\s*>?\s*(?:-\s+.*|\s*)\n?)+)", md)
    if not m:
        return []
    items = re.findall(r"-\s+(.+)", m.group(1))
    return [md_to_text(i).strip() for i in items if i.strip()]
