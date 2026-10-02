from retrieval.bm25 import Hit
from retrieval.hybrid import rrf


def h(pid):
    return Hit(pid, "c", pid * 10, pid * 10 + 5, 0.0)


def test_rrf_rewards_agreement_between_lists():
    fused = rrf([[h(1), h(2), h(3)], [h(3), h(1), h(4)]], k0=60, k=10)
    assert [x.passage_id for x in fused][:2] == [1, 3]
    assert fused[0].score == 1 / 61 + 1 / 62


def test_rrf_breaks_ties_by_passage_id_and_truncates():
    fused = rrf([[h(5)], [h(2)]], k0=60, k=1)
    assert [x.passage_id for x in fused] == [2]


def test_rrf_of_nothing_is_nothing():
    assert rrf([[], []]) == []
