from answer.answerer import Answerer
from evals.answer_sets import AnswerItem
from evals.live_parity import prompt_parity, r7n_parity
from tests.fakes import fake_claude
from tests.test_ladder import deals_ladder  # noqa: F401


def item(i, question, cid=None):
    return AnswerItem(f"i{i}", "tmachine", "termination_fee", "test", cid, question)


def test_prompt_parity_compares_recorded_hashes_and_skips_failed_calls(deals_ladder):
    run = fake_claude("")
    ans = Answerer(deals_ladder, run, "m")
    items = [item(1, "What is the Acme Software outside date?"), item(2, "termination fee", "edgar_0001"),
             item(3, "outside date", "edgar_0001"), item(4, "What is the outside date for Zeta Labs?"),
             item(5, "closing", "contract_1")]
    sha = {i.item_id: ans.prepare(i.question, i.contract_id).prompt_sha for i in items}
    records = {"i1": {"answer": {"prompt_sha": sha["i1"]}},
               "i2": {"answer": {"prompt_sha": "stale0000000"}},
               "i3": {"answer": None, "error": "runner: timeout"},  # a failed call has no answer: skipped
               "i4": {"answer": {"prompt_sha": None}}}               # which_deal: no prompt, as recorded
    assert prompt_parity(items, ans, records) == {"checked": 3, "same": 2, "differ": ["i2"]}
    assert run.calls == []


def test_r7n_parity_names_the_questions_that_differ():
    from retrieval.bm25 import Hit
    from retrieval.result import Retrieved

    class L:
        def __init__(self, ids):
            self.ids = ids

        def run(self, rung, q, cid, k):
            assert rung == "R7n"
            return Retrieved([Hit(i, "c", 0, 1, 1.0) for i in self.ids[q]], 1.0, [], ())
    a, b = L({"x": [1, 2], "y": [3]}), L({"x": [1, 2], "y": [4]})
    assert r7n_parity([("x", None), ("y", "c")], a, b) == {
        "checked": 2, "same": 1, "differ": [{"question": "y", "contract_id": "c"}]}
