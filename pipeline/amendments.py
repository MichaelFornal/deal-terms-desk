import re

AMEND_SPAN_MAX = 4000
AMENDS = re.compile(r"Section\s+(\d{1,2}\.\d{1,2})(?:\([A-Za-z0-9]+\))*\s+of\s+the\s+(?:Merger\s+)?Agreement\s+"
                    r"(?:is|shall\s+be)\s+(?:hereby\s+)?(?:amended|deleted\s+and\s+replaced)", re.I)
ORDINALS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5}
NUMBER = re.compile(r"Amendment\s+No\.?\s*(\d+)|\b(First|Second|Third|Fourth|Fifth)\s+Amendment\b", re.I)


def amended_sections(text: str) -> list[tuple[str, int, int]]:
    hits = list(AMENDS.finditer(text))
    out = []
    for i, m in enumerate(hits):
        end = hits[i + 1].start() if i + 1 < len(hits) else len(text)
        out.append((m.group(1), m.start(), min(end, m.start() + AMEND_SPAN_MAX)))
    return out


def amendment_no(text: str, fallback: int) -> int:
    m = NUMBER.search(text[:2000])
    if not m:
        return fallback
    return int(m.group(1)) if m.group(1) else ORDINALS[m.group(2).lower()]
