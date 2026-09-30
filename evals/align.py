import re

PAGE_MARKER = re.compile(r"\(Pages?\s*[\d\-–, ]+\)")
WHITESPACE = re.compile(r"\s+")
MIN_PIECE = 40
ANCHOR = 40
MAX_ANCHOR_TRIES = 4


def _squash(s: str) -> str:
    return WHITESPACE.sub("", s)


def pieces_of(excerpt: str) -> list[str]:
    parts = PAGE_MARKER.sub("", excerpt).split("<omitted>")
    return [p.strip() for p in parts if len(_squash(p)) >= MIN_PIECE]


def _locate(p: str, squashed: str) -> tuple[str, int, int]:
    i = squashed.find(p)
    if i >= 0:
        return "exact", i, i + len(p)
    n = len(p)
    limit = 2 * n + 200
    for head_at in range(0, min(n - ANCHOR, MAX_ANCHOR_TRIES * ANCHOR) + 1, ANCHOR):
        h = squashed.find(p[head_at:head_at + ANCHOR])
        if h < 0:
            continue
        for tail_end in range(n, max(ANCHOR, n - MAX_ANCHOR_TRIES * ANCHOR) - 1, -ANCHOR):
            t = squashed.find(p[tail_end - ANCHOR:tail_end], h)
            if t >= 0 and t + ANCHOR - h <= limit:
                return "anchored", h, t + ANCHOR
    return "none", -1, -1


def align_piece(piece: str, squashed: str, index: list[int]) -> tuple[str, int, int]:
    status, s, e = _locate(_squash(piece), squashed)
    if status == "none":
        return "none", -1, -1
    return status, index[s], index[e - 1] + 1
