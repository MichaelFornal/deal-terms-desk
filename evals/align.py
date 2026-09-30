import re
from bisect import bisect_left
from dataclasses import dataclass

PAGE_MARKER = re.compile(r"\(Pages?\s*[\d\-–, ]+\)")
WHITESPACE = re.compile(r"\s+")
MIN_PIECE = 40
ANCHOR = 40
MAX_ANCHOR_TRIES = 4
# An anchored span shorter than this share of the text its anchors bracket is a truncation.
MIN_ANCHORED_SHARE = 0.7


@dataclass(frozen=True)
class Aligned:
    """One excerpt piece placed in the contract; start/end are canonical offsets, -1 if unaligned."""
    status: str  # "exact" | "anchored" | "none"
    start: int
    end: int
    n_candidates: int = 0  # places it could go, after table-of-contents exclusion
    toc_rescued: bool = False  # a table-of-contents match was passed over for the body
    toc_only: bool = False  # it matched only inside the table of contents, so it is unaligned


def _squash(s: str) -> str:
    return WHITESPACE.sub("", s)


def _parts(excerpt: str) -> list[str]:
    return [p.strip() for p in PAGE_MARKER.sub("", excerpt).split("<omitted>")]


def pieces_of(excerpt: str) -> list[str]:
    return [p for p in _parts(excerpt) if len(_squash(p)) >= MIN_PIECE]


def short_pieces(excerpt: str) -> int:
    """Non-empty pieces too short to align; they are left out of the gold, so they are counted."""
    return sum(1 for p in _parts(excerpt) if 0 < len(_squash(p)) < MIN_PIECE)


def _occurrences(needle: str, hay: str, start: int = 0, stop: int | None = None) -> list[int]:
    stop = len(hay) if stop is None else stop
    out = []
    i = hay.find(needle, start, stop)
    while i >= 0:
        out.append(i)
        i = hay.find(needle, i + 1, stop)
    return out


def _squashed_spans(spans, index: list[int]) -> list[tuple[int, int]]:
    """Canonical spans to squashed ones, with overlapping or touching spans merged."""
    merged: list[list[int]] = []
    for a, b in sorted(spans):
        if merged and a <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(bisect_left(index, a), bisect_left(index, b)) for a, b in merged]


def _inside(span: tuple[int, int], excluded: list[tuple[int, int]]) -> bool:
    return any(a <= span[0] and span[1] <= b for a, b in excluded)


def _candidates(p: str, squashed: str, excluded: list[tuple[int, int]]) -> tuple[str, list[tuple[int, int]], bool]:
    """Every squashed span the piece could occupy outside the excluded spans, and whether any
    match was thrown away for lying inside one."""
    dropped = False
    n = len(p)
    exact = [(i, i + n) for i in _occurrences(p, squashed)]
    kept = [c for c in exact if not _inside(c, excluded)]
    dropped |= len(kept) < len(exact)
    if kept:
        return "exact", kept, dropped
    limit = 2 * n + 200
    for head_at in range(0, min(n - ANCHOR, MAX_ANCHOR_TRIES * ANCHOR) + 1, ANCHOR):
        heads = _occurrences(p[head_at:head_at + ANCHOR], squashed)
        if not heads:
            continue
        for tail_end in range(n, max(head_at + 2 * ANCHOR, n - MAX_ANCHOR_TRIES * ANCHOR) - 1, -ANCHOR):
            # The tail anchor starts at or after the head anchor's end, so it brackets something.
            tail = p[tail_end - ANCHOR:tail_end]
            bracketed = tail_end - head_at
            found = []
            for h in heads:
                ends = [t + ANCHOR for t in _occurrences(tail, squashed, h, h + limit)]
                if not ends:
                    continue
                # The tail can recur inside the clause; take the one ending where the piece would.
                end = min(ends, key=lambda e: abs(e - (h + bracketed)))
                if end - h >= MIN_ANCHORED_SHARE * bracketed:
                    found.append((h, end))
            kept = [c for c in found if not _inside(c, excluded)]
            dropped |= len(kept) < len(found)
            if kept:
                return "anchored", kept, dropped
    return "none", [], dropped


def _gap(a: tuple[int, int], b: tuple[int, int]) -> int:
    return max(0, a[0] - b[1], b[0] - a[1])


def align_excerpt(excerpt: str, squashed: str, index: list[int], exclude=()) -> list[Aligned]:
    """Align each piece of one excerpt. `exclude` holds canonical spans (the table of contents)
    that gold may not sit in. A piece that fits several places takes the one nearest the
    excerpt's pieces that fit only one; with none of those it takes the first."""
    excluded = _squashed_spans(exclude, index)
    found = [_candidates(_squash(p), squashed, excluded) for p in pieces_of(excerpt)]
    fixed = [cands[0] for _, cands, _ in found if len(cands) == 1]
    out = []
    for status, cands, dropped in found:
        if not cands:
            out.append(Aligned("none", -1, -1, 0, False, dropped))
            continue
        s, e = cands[0]
        if len(cands) > 1 and fixed:
            s, e = min(cands, key=lambda c: min(_gap(c, f) for f in fixed))
        out.append(Aligned(status, index[s], index[e - 1] + 1, len(cands), dropped, False))
    return out


def align_piece(piece: str, squashed: str, index: list[int], exclude=()) -> tuple[str, int, int]:
    status, cands, _ = _candidates(_squash(piece), squashed, _squashed_spans(exclude, index))
    if not cands:
        return "none", -1, -1
    s, e = cands[0]
    return status, index[s], index[e - 1] + 1
