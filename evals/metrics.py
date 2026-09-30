import math

MIN_OVERLAP = 20


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def _touches(start: int, end: int, g0: int, g1: int) -> bool:
    return _overlap(start, end, g0, g1) >= min(MIN_OVERLAP, g1 - g0)


def is_relevant(start: int, end: int, gold) -> bool:
    return any(_touches(start, end, g0, g1) for g0, g1 in gold)


def recall_at_k(hits, gold, k: int) -> float:
    top = hits[:k]
    found = sum(1 for g0, g1 in gold if any(_touches(h.start, h.end, g0, g1) for h in top))
    return found / len(gold)


def mrr(hits, gold, k: int = 10) -> float:
    for rank, h in enumerate(hits[:k], start=1):
        if is_relevant(h.start, h.end, gold):
            return 1.0 / rank
    return 0.0


def ndcg_at_k(hits, gold, n_relevant: int, k: int = 10) -> float:
    ideal = sum(1.0 / math.log2(rank + 1) for rank in range(1, min(k, n_relevant) + 1))
    if ideal == 0:
        return 0.0
    dcg = sum(
        1.0 / math.log2(rank + 1)
        for rank, h in enumerate(hits[:k], start=1)
        if is_relevant(h.start, h.end, gold)
    )
    return dcg / ideal
