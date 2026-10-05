from answer.answerer import Answerer
from evals.answer_sets import AnswerItem
from evals.live_parity import prompt_parity
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
