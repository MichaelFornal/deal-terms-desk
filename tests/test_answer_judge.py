import json

from evals.answer_judge import JUDGE_MODEL, judge_all, refute_all
from evals.answer_sets import AnswerItem
from tests.fakes import fake_claude

ITEM = AnswerItem("edgar_1|termination_fee", "tmachine", "termination_fee", "report", None, "How much…?", (),
                  "edgar_1", {"a": "A $5m fee.", "b": "Five million dollars.", "gold": []})


def rec(state, claims=()):
    return {"answer": {"state": state, "claims": [{"text": t, "quote": q} for t, q in claims]}, "error": None}


def test_judge_asks_once_per_answered_item_and_declines_without_a_call(tmp_path):
    run = fake_claude(json.dumps({"verdict": "agree", "reason": "same amount"}))
    other = AnswerItem("edgar_2|termination_fee", "tmachine", "termination_fee", "report", None, "q", (), "edgar_2",
                       {"a": "x", "b": "y", "gold": []})
    errored = AnswerItem("edgar_3|termination_fee", "tmachine", "termination_fee", "report", None, "q", (), "edgar_3",
                         {"a": "x", "b": "y", "gold": []})
    answers = {ITEM.item_id: rec("answered", [("The fee is $5m.", "$5,000,000")]),
               other.item_id: rec("not_stated"), errored.item_id: {"answer": None, "error": "parse: x"}}
    got = judge_all([ITEM, other, errored], answers, run, tmp_path / "j.jsonl")
    assert got[ITEM.item_id]["verdict"] == "agree" and got[other.item_id]["verdict"] == "declined"
    assert errored.item_id not in got and len(run.calls) == 1 and run.calls[0][1] == JUDGE_MODEL
    assert "A $5m fee." in run.calls[0][0] and "The fee is $5m." in run.calls[0][0]
    judge_all([ITEM, other], answers, run, tmp_path / "j.jsonl")
    assert len(run.calls) == 1  # ledgered


def test_unparseable_verdict_is_none(tmp_path):
    got = judge_all([ITEM], {ITEM.item_id: rec("answered", [("t", "q")])}, fake_claude("hmm"), tmp_path / "j.jsonl")
    assert got[ITEM.item_id]["verdict"] is None


def test_refute_one_call_per_surviving_claim(tmp_path):
    run = fake_claude(json.dumps({"refuted": False, "reason": "quote supports it"}))
    answers = {"a": rec("answered", [("c1", "q1"), ("c2", "q2")]), "b": rec("not_stated")}
    got = refute_all(answers, run, tmp_path / "r.jsonl")
    assert set(got) == {"a#0", "a#1"} and got["a#0"]["refuted"] is False and len(run.calls) == 2
    assert "q1" in run.calls[0][0] and "c1" in run.calls[0][0]
