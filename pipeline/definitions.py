import re

from pipeline.terms import _QUOTED, Term

MAX_DEF_CHARS = 800
MAX_DEFS = 6
UBIQUITY = 0.2
MEANS_END = re.compile(r"\n\s*\n|\n\s*[“\"][A-Z]")
NEXT_DEF = re.compile(_QUOTED + r"\s+(?:means|shall mean|has the meaning|shall have the meaning)\b")
SENTENCE_END = re.compile(r"(?<=[.;])\s|\n\s*\n")


def _means_span(text: str, t: Term) -> tuple[int, int]:
    ends = [len(text)]
    for pat in (MEANS_END, NEXT_DEF):
        m = pat.search(text, t.end)
        if m:
            ends.append(m.start())
    end = min(ends)
    while end > t.end and text[end - 1].isspace():
        end -= 1
    return t.start, min(end, t.start + MAX_DEF_CHARS)


def _paren_span(text: str, t: Term) -> tuple[int, int]:
    lo = max(0, t.start - MAX_DEF_CHARS)
    starts = [m.end() for m in SENTENCE_END.finditer(text, lo, t.start)]
    s = starts[-1] if starts else lo
    m = SENTENCE_END.search(text, t.end)
    e = m.start() if m else len(text)
    if e - s > MAX_DEF_CHARS:
        s = max(s, t.end - MAX_DEF_CHARS // 2)
        e = min(e, s + MAX_DEF_CHARS)
    return s, e


def definition_spans(text: str, terms: list[Term]) -> dict[str, tuple[int, int]]:
    out: dict[str, tuple[int, int]] = {}
    for style, span in (("means", _means_span), ("paren", _paren_span)):
        for t in sorted(terms, key=lambda t: t.start):
            if t.style == style and t.term not in out:
                out[t.term] = span(text, t)
    return out


def term_pattern(names: list[str]) -> re.Pattern | None:
    if not names:
        return None
    alts = "|".join(re.escape(n) for n in sorted(set(names), key=lambda n: (-len(n), n)))
    return re.compile(r"(?<![A-Za-z0-9])(" + alts + r")(?![A-Za-z0-9])")


def terms_used(passage_text: str, pattern: re.Pattern | None) -> list[str]:
    if pattern is None:
        return []
    return list(dict.fromkeys(m.group(1) for m in pattern.finditer(passage_text)))
