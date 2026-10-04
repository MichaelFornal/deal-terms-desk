import json
import os
import signal
import subprocess
import sys
import time

import pytest

from answer.answerer import Answer, ParseError, Prepared
from answer.prompt import TEMPLATE_SHA
from evals.answer_sets import AnswerItem, write_items
from evals.run_answers import answer_all, load_answers


class FakeAnswerer:
    """prepare/finish without retrieval: item questions starting 'nodeal' need no call."""
    def __init__(self, runner, model="m", fail_parse=()):
        self.runner, self.model, self.fail_parse = runner, model, set(fail_parse)

    def prepare(self, question, contract_id=None, choices=()):
        if question.startswith("nodeal"):
            return Answer("which_deal")
        return Prepared(question, contract_id or "c", [], f"PROMPT {question}", "sha", tuple(choices))

    def finish(self, p, reply, ms):
        if p.question in self.fail_parse:
            raise ParseError("parse: nope")
        return Answer("not_stated", contract_id=p.contract_id, tokens_in=10, ms=ms)


def runner(prompt, model):
    runner.calls.append(prompt)
    return {"result": "{}", "usage": {"input_tokens": 10, "output_tokens": 2}}


def items(n, prefix="q"):
    return [AnswerItem(f"i{k}", "thuman", "g", "report", "c", f"{prefix}{k}") for k in range(n)]


def test_ledger_skip_and_no_call_states(tmp_path):
    runner.calls = []
    its = items(5) + [AnswerItem("nd", "abstain", "unknown_deal", "report", None, "nodeal x", (), "which_deal")]
    s = answer_all(its, FakeAnswerer(runner), tmp_path / "l.jsonl", workers=2)
    assert s == {"items": 6, "done": 6, "new_calls": 5, "errors": 0}
    got = load_answers(tmp_path / "l.jsonl", "m")
    assert got["nd"]["answer"]["state"] == "which_deal" and got["i0"]["template_sha"] == TEMPLATE_SHA
    runner.calls = []
    assert answer_all(its, FakeAnswerer(runner), tmp_path / "l.jsonl")["new_calls"] == 0 and runner.calls == []


def test_changed_template_is_a_miss(tmp_path, monkeypatch):
    runner.calls = []
    answer_all(items(2), FakeAnswerer(runner), tmp_path / "l.jsonl")
    import evals.run_answers as ra
    monkeypatch.setattr(ra, "TEMPLATE_SHA", "000000000000")
    runner.calls = []
    assert answer_all(items(2), FakeAnswerer(runner), tmp_path / "l.jsonl")["new_calls"] == 2
    assert set(load_answers(tmp_path / "l.jsonl", "m")) == {"i0", "i1"}


def test_parse_and_runner_errors_are_recorded_and_threshold_stops(tmp_path):
    runner.calls = []
    s = answer_all(items(40), FakeAnswerer(runner, fail_parse={"q3"}), tmp_path / "l.jsonl", max_error_rate=0.05)
    assert s["errors"] == 1 and load_answers(tmp_path / "l.jsonl", "m")["i3"]["error"].startswith("parse")

    def down(prompt, model):
        raise RuntimeError("claude down")
    with pytest.raises(RuntimeError, match="error rate"):
        answer_all(items(40, "z"), FakeAnswerer(down), tmp_path / "l2.jsonl", max_error_rate=0.05)


def test_max_new_bounds_the_run(tmp_path):
    runner.calls = []
    assert answer_all(items(10), FakeAnswerer(runner), tmp_path / "l.jsonl", max_new=3)["new_calls"] == 3


SCRIPT = """
import sys, time
sys.path.insert(0, {root!r})
from evals.answer_sets import read_items
from evals.run_answers import answer_all
from tests.test_run_answers import FakeAnswerer
def slow(prompt, model):
    time.sleep(0.05)
    return {{"result": "{{}}", "usage": {{}}}}
answer_all(read_items({items!r}), FakeAnswerer(slow), {ledger!r}, workers=2)
"""


def test_sigkill_mid_run_then_resume(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    write_items(tmp_path / "items.jsonl", items(60))
    ledger = tmp_path / "l.jsonl"
    p = subprocess.Popen([sys.executable, "-c", SCRIPT.format(root=root, items=str(tmp_path / "items.jsonl"),
                                                             ledger=str(ledger))], cwd=root)
    deadline = time.time() + 30
    while time.time() < deadline and (not ledger.exists() or len(ledger.read_text().splitlines()) < 10):
        time.sleep(0.02)
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    before = len(load_answers(ledger, "m"))
    assert 10 <= before < 60
    with open(ledger, "a") as f:
        f.write('{"key": "torn')  # a kill mid-write leaves a torn last line
    runner.calls = []
    s = answer_all(items(60), FakeAnswerer(runner), ledger)
    assert s["new_calls"] == 60 - before and len(load_answers(ledger, "m")) == 60
    keys = [json.loads(l)["key"] for l in ledger.read_text().splitlines() if l.strip()]
    assert len(keys) == len(set(keys)) == 60
