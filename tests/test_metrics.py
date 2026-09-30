import math

import pytest

from evals.metrics import is_relevant, mrr, ndcg_at_k, recall_at_k
from retrieval.bm25 import Hit


def hit(start, end, pid=1):
    return Hit(pid, "c", start, end, 1.0)


GOLD = ((100, 200), (500, 510))


def test_relevance_needs_twenty_characters_of_overlap():
    assert is_relevant(180, 300, GOLD)
    assert not is_relevant(190, 300, GOLD)
    assert not is_relevant(200, 300, GOLD)


def test_a_span_shorter_than_twenty_needs_full_overlap():
    assert is_relevant(495, 520, GOLD)
    assert not is_relevant(505, 520, GOLD)


def test_recall_counts_gold_spans_touched_in_top_k():
    hits = [hit(0, 50), hit(90, 210), hit(480, 520)]
    assert recall_at_k(hits, GOLD, 1) == 0.0
    assert recall_at_k(hits, GOLD, 2) == 0.5
    assert recall_at_k(hits, GOLD, 3) == 1.0


def test_recall_with_no_hits_is_zero():
    assert recall_at_k([], GOLD, 5) == 0.0


def test_mrr_is_reciprocal_rank_of_first_relevant_hit():
    assert mrr([hit(0, 50), hit(90, 210)], GOLD) == 0.5
    assert mrr([hit(0, 50)], GOLD) == 0.0


def test_mrr_ignores_hits_beyond_k():
    hits = [hit(0, 50)] * 10 + [hit(90, 210)]
    assert mrr(hits, GOLD, k=10) == 0.0


def test_ndcg_is_one_for_an_ideal_ranking():
    assert ndcg_at_k([hit(90, 210), hit(480, 520), hit(0, 50)], GOLD, n_relevant=2) == pytest.approx(1.0)


def test_ndcg_discounts_a_late_relevant_hit():
    got = ndcg_at_k([hit(0, 50), hit(90, 210)], GOLD, n_relevant=1)
    assert got == pytest.approx((1 / math.log2(3)) / 1.0)


def test_ndcg_is_zero_when_nothing_is_relevant_in_the_corpus():
    assert ndcg_at_k([hit(0, 50)], GOLD, n_relevant=0) == 0.0
