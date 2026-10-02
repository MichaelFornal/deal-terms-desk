from collections import defaultdict
from dataclasses import replace

from retrieval.bm25 import Hit


def rrf(rankings: list[list[Hit]], k0: int = 60, k: int = 10) -> list[Hit]:
    score: dict[int, float] = defaultdict(float)
    first: dict[int, Hit] = {}
    for ranking in rankings:
        for rank, h in enumerate(ranking, start=1):
            score[h.passage_id] += 1.0 / (k0 + rank)
            first.setdefault(h.passage_id, h)
    order = sorted(score, key=lambda pid: (-score[pid], pid))
    return [replace(first[pid], score=score[pid]) for pid in order[:k]]
