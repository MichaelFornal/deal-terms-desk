import re
from dataclasses import dataclass

HEAD = re.compile(
    r"(?:(?<=\n)|(?<=\s\s)|\A)(?:Section\s+|SECTION\s+)?(\d{1,2}\.\d{1,2})\.?[ \t\xa0]+(?=[A-Z])"
)
SECTION_NUMBER = re.compile(r"\b\d{1,2}\.\d{1,2}\b")
TITLE = re.compile(r"([^.\n]{2,100})\.")
# Tried in order: blank line, sub-clause marker, sentence end.
BREAKS = (
    re.compile(r"\n\s*\n"),
    re.compile(r"\s(?=\((?:[a-z]|[ivx]{1,4}|[A-Z])\)\s)"),
    re.compile(r"(?<=[.;:])\s"),
)
TOC_MIN_SECTION_NUMBERS = 5
ARTICLE = re.compile(r"(?m)^[ \t]*(?:ARTICLE|Article)[ \t]+([IVXLC]+|\d{1,2})\b")
CLAUSE = re.compile(r"\s*\(([a-z]|[ivx]{1,4}|[A-Z])\)\s")
ROMAN = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100}
PATH_SEP = " › "


@dataclass(frozen=True)
class Passage:
    contract_id: str
    ordinal: int
    start: int
    end: int
    section_id: str
    section_title: str
    kind: str
    section_path: str = ""


def _numeral(s: str) -> int:
    if s.isdigit():
        return int(s)
    total = 0
    for i, ch in enumerate(s):
        v = ROMAN[ch]
        total += -v if i + 1 < len(s) and ROMAN[s[i + 1]] > v else v
    return total


def _article(articles: list[tuple[int, str]], pos: int, section_id: str) -> str:
    """The numeral of the last article heading before pos that matches the section's major number."""
    major = int(section_id.split(".")[0])
    found = ""
    for apos, numeral in articles:
        if apos >= pos:
            break
        if _numeral(numeral) == major:
            found = numeral
    return found


def _title(text: str, pos: int) -> str:
    m = TITLE.match(text[pos:pos + 110])
    return m.group(1).strip() if m else ""


def _cut(text: str, start: int, end: int, max_chars: int) -> list[tuple[int, int]]:
    out = []
    while end - start > max_chars:
        window = text[start:start + max_chars]
        cut = None
        for rx in BREAKS:
            ends = [m.end() for m in rx.finditer(window) if m.end() >= max_chars // 4]
            if ends:
                cut = ends[-1]
                break
        if cut is None:
            cut = max_chars
        out.append((start, start + cut))
        start += cut
    out.append((start, end))
    return out


def segment(contract_id: str, text: str, max_chars: int = 2400) -> list[Passage]:
    if not text:
        return []
    cands = [(m.start(), m.group(1), m.end()) for m in HEAD.finditer(text)]
    heads = []
    if cands:
        first_id = cands[0][1]
        occurrences = [i for i, c in enumerate(cands) if c[1] == first_id]
        heads = cands[occurrences[1] if len(occurrences) > 1 else occurrences[0]:]
    pieces = []
    body_start = heads[0][0] if heads else len(text)
    if body_start > 0:
        pieces.append((0, body_start, "", "", "front"))
    for i, (pos, section_id, title_pos) in enumerate(heads):
        nxt = heads[i + 1][0] if i + 1 < len(heads) else len(text)
        pieces.append((pos, nxt, section_id, _title(text, title_pos), "section"))
    articles = [(m.start(), m.group(1)) for m in ARTICLE.finditer(text)]
    out: list[Passage] = []
    for s, e, section_id, title, kind in pieces:
        article = _article(articles, s, section_id) if kind == "section" else ""
        for a, b in _cut(text, s, e, max_chars):
            k = kind
            if kind == "front" and len(SECTION_NUMBER.findall(text[a:b])) >= TOC_MIN_SECTION_NUMBERS:
                k = "toc"
            path = ""
            if kind == "section":
                parts = ([f"Article {article}"] if article else []) + [section_id]
                clause = CLAUSE.match(text, a) if a > s else None
                if clause:
                    parts.append(f"({clause.group(1)})")
                path = PATH_SEP.join(parts)
            out.append(Passage(contract_id, len(out), a, b, section_id, title, k, path))
    return out
