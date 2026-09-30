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


@dataclass(frozen=True)
class Passage:
    contract_id: str
    ordinal: int
    start: int
    end: int
    section_id: str
    section_title: str
    kind: str


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
    out: list[Passage] = []
    for s, e, section_id, title, kind in pieces:
        for a, b in _cut(text, s, e, max_chars):
            k = kind
            if kind == "front" and len(SECTION_NUMBER.findall(text[a:b])) >= TOC_MIN_SECTION_NUMBERS:
                k = "toc"
            out.append(Passage(contract_id, len(out), a, b, section_id, title, k))
    return out
