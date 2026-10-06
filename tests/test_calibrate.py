import json
import os
import signal
import subprocess
import sys
import time

import pytest

from evals.answer_sets import AnswerItem, write_items
from evals.calibrate import calibration_sample, ledger_path, run_calibration, summarise
from evals.run_answers import load_answers
from pipeline import cli
from service.prices import Prices
from tests.test_run_answers import FakeAnswerer, runner

P = Prices("m", 1.0, 5.0, 1.25, 0.1, "s", "2026-10-05")


def item(iid, s="thuman", split="tune", expected="", choices=()):
    return AnswerItem(iid, s, "g", split, "c", f"q {iid}", choices, expected)


def ans(state="answered", choice=None, kept=1, dropped=0, tin=1000, tout=100):
    return {"state": state, "choice": choice, "claims": [{"quote": "q"}] * kept,
            "dropped": [{"reason": "quote_not_found"}] * dropped, "tokens_in": tin, "tokens_out": tout,
            "usage": {"input_tokens": tin, "output_tokens": tout}}


def rec(answer=None, error=None):
    return {"answer": answer, "error": error}


TH1 = item("th1", expected="Yes", choices=("No", "Yes"))
TH2 = item("th2", expected="No", choices=("No", "Yes"))
TH3 = item("th3", expected="No", choices=("No", "Yes"))
TM1, TM2 = item("tm1", "tmachine"), item("tm2", "tmachine")
ITEMS = [TH1, TH2, TH3, TM1, TM2]
CHARS = {"th1": 9000, "th2": 9000, "tm1": 12000, "tm2": 12000}


def test_sample_takes_tune_items_from_both_sets_stably():
    pool = ([item(f"h{k}") for k in range(10)] + [item(f"r{k}", split="report") for k in range(10)]
            + [item(f"m{k}", "tmachine") for k in range(10)])
    got = calibration_sample(pool, 6)
    assert [i.set for i in got] == ["thuman"] * 3 + ["tmachine"] * 3
    assert all(i.split == "tune" for i in got)
    assert [i.item_id for i in calibration_sample(list(reversed(pool)), 6)] == [i.item_id for i in got]
    assert len(calibration_sample(pool, 40)) == 20  # never more than the tune split holds


def test_ledger_name_carries_the_model_and_the_output_cap(tmp_path):
    a, b = ledger_path(tmp_path, "m", 1024), ledger_path(tmp_path, "m", 2048)
    assert a != b and a.name == "calibration_m_mt1024.jsonl" and a.parent == tmp_path


def test_ledger_name_carries_the_thinking_budget_only_when_there_is_one(tmp_path):
    assert ledger_path(tmp_path, "m", 6144, 4096).name == "calibration_m_mt6144_tb4096.jsonl"
    assert ledger_path(tmp_path, "m", 1024, 0) == ledger_path(tmp_path, "m", 1024)
    assert ledger_path(tmp_path, "m", 6144, 4096) != ledger_path(tmp_path, "m", 6144, 2048)


def test_the_summary_records_the_thinking_budget():
    assert summarise(ITEMS, {}, {}, CHARS, P, 6144, 4096)["thinking_budget"] == 4096
    assert summarise(ITEMS, {}, {}, CHARS, P, 1024)["thinking_budget"] == 0


def test_calibrate_defaults_and_flags_reach_the_stage(monkeypatch):
    seen = []
    monkeypatch.setitem(cli.M5_STAGES, "calibrate", lambda a: seen.append(a) or 0)
    assert cli.entry(["m5", "calibrate"]) == 0
    assert cli.entry(["m5", "calibrate", "--thinking-budget", "0", "--max-tokens", "900"]) == 0
    assert (seen[0].thinking_budget, seen[0].max_tokens) == (4096, 6144)
    assert (seen[1].thinking_budget, seen[1].max_tokens) == (0, 900)


def test_the_calibration_runner_sends_the_thinking_budget(monkeypatch):
    from types import SimpleNamespace
    calls = []

    class Client:
        messages = SimpleNamespace(create=lambda **kw: calls.append(kw) or SimpleNamespace(
            content=[SimpleNamespace(type="text", text="{}")], stop_reason="end_turn",
            usage=SimpleNamespace(input_tokens=1, output_tokens=1)))
    monkeypatch.setattr(cli, "_api_client", lambda key: Client())
    cli._calibration_runner(SimpleNamespace(max_tokens=6144, thinking_budget=4096), "k")("p", "m")
    cli._calibration_runner(SimpleNamespace(max_tokens=1024, thinking_budget=0), "k")("p", "m")
    assert calls[0]["thinking"] == {"type": "enabled", "budget_tokens": 4096} and "thinking" not in calls[1]


def test_the_calibration_client_waits_long_enough_for_thinking(monkeypatch):
    import anthropic
    seen = {}
    monkeypatch.setattr(anthropic, "Anthropic", lambda **kw: seen.update(kw))
    cli._api_client("k")
    assert seen["timeout"] == 90.0 and seen["max_retries"] == 0


def test_summary_counts_tokens_cost_parity_and_stops_on_disagreement():
    api = {"th1": rec(ans(choice="Yes", kept=2, tin=1000, tout=100)),
           "th2": rec(ans("not_stated", choice="Yes", kept=0, dropped=1, tin=2000, tout=200)),
           "tm1": rec(ans(kept=1, dropped=1, tin=3000, tout=300)),
           "tm2": rec(error="runner: truncated: reply stopped at max_tokens (max_tokens=1024)")}
    cli_recs = {"th1": rec(ans(choice="Yes", kept=1, dropped=1)), "th2": rec(ans("not_stated", choice="No", kept=0)),
                "tm1": rec(ans("not_stated", kept=0)), "tm2": rec(ans())}
    s = summarise(ITEMS, api, cli_recs, CHARS, P, 1024)
    assert (s["n"], s["called"], s["errors"], s["missing"], s["truncated"], s["refused"]) == (5, 3, 1, 1, 1, 0)
    assert (s["api_tokens_in_mean"], s["api_tokens_in_p95"]) == (2000.0, 3000)
    assert (s["api_tokens_out_mean"], s["api_tokens_out_p95"], s["api_tokens_out_p99"]) == (200.0, 300, 300)
    # three answered calls at their actual cost, the truncated one at its worst case (12,000 chars, 1,024 out)
    assert s["cost_usd_total"] == pytest.approx(0.0015 + 0.003 + 0.0045 + 0.00912)
    assert s["cost_per_answer_mean"] == pytest.approx(0.003)
    assert s["cost_per_answer_p95"] == pytest.approx(0.0045)
    assert s["worst_case_ok"] is True and s["worst_case_min_margin_usd"] == pytest.approx(0.00462)
    assert s["paired"] == 3
    assert s["gate_pass_rate"] == {"api": 0.6, "cli": 0.5}
    assert s["state_agreement"] == 0.6667
    assert s["thuman_accuracy"] == {"api": 0.5, "cli": 1.0, "diff": -0.5, "n": 2}
    assert s["stop_rule"]["verdict"] == "stop" and len(s["stop_rule"]["reasons"]) == 2


def test_summary_goes_when_api_and_cli_agree():
    same = {"th1": rec(ans(choice="Yes")), "th2": rec(ans("not_stated", choice="No", kept=0)), "tm1": rec(ans())}
    s = summarise(ITEMS, same, same, CHARS, P, 1024)
    assert s["state_agreement"] == 1.0 and s["thuman_accuracy"]["diff"] == 0.0
    assert s["stop_rule"] == {"state_agreement_min": 0.8, "accuracy_diff_max": 0.15, "verdict": "go", "reasons": []}


def test_summary_stops_when_the_worst_case_estimate_is_below_an_actual_cost():
    a = {"th1": rec(ans(choice="Yes", tin=50_000, tout=100))}  # far more tokens than 9,000 characters / 3
    s = summarise([TH1], a, a, {"th1": 9000}, P, 1024)
    assert s["worst_case_ok"] is False and s["stop_rule"]["verdict"] == "stop"


def test_summary_stops_when_nothing_is_paired():
    s = summarise(ITEMS, {}, {}, CHARS, P, 1024)
    assert s["paired"] == 0 and s["state_agreement"] is None and s["cost_usd_total"] == 0.0
    assert s["stop_rule"]["verdict"] == "stop"


def test_a_few_failed_calls_do_not_stop_calibration(tmp_path):
    runner.calls = []

    def flaky(prompt, model):
        if prompt[-1] in "135":
            raise RuntimeError("overloaded: try later")
        return runner(prompt, model)
    its = [item(f"h{k}") for k in range(20)]  # h1 h3 h5 h11 h13 h15 fail: 30%, over answer_all's default 5%
    got = run_calibration([(its, FakeAnswerer(flaky))], tmp_path / "cal.jsonl", workers=2)
    assert got["errors"] == 6 and got["done"] == 14


SCRIPT = """
import sys, time
sys.path.insert(0, {root!r})
from evals.answer_sets import read_items
from evals.calibrate import run_calibration
from tests.test_run_answers import FakeAnswerer
def slow(prompt, model):
    time.sleep(0.05)
    return {{"result": "{{}}", "usage": {{}}}}
its = read_items({items!r})
jobs = [([i for i in its if i.set == s], FakeAnswerer(slow)) for s in ("thuman", "tmachine")]
run_calibration(jobs, {ledger!r}, workers=2)
"""


def test_sigkill_mid_calibration_then_resume(tmp_path):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    its = [item(f"h{k}") for k in range(30)] + [item(f"m{k}", "tmachine") for k in range(30)]
    write_items(tmp_path / "items.jsonl", its)
    ledger = tmp_path / "cal.jsonl"
    p = subprocess.Popen([sys.executable, "-c", SCRIPT.format(root=root, items=str(tmp_path / "items.jsonl"),
                                                             ledger=str(ledger))], cwd=root)
    deadline = time.time() + 30
    while time.time() < deadline and (not ledger.exists() or len(ledger.read_text().splitlines()) < 10):
        time.sleep(0.02)
    os.kill(p.pid, signal.SIGKILL)
    p.wait()
    before = len(load_answers(ledger, "m", its))
    assert 10 <= before < 60
    runner.calls = []
    jobs = [([i for i in its if i.set == s], FakeAnswerer(runner)) for s in ("thuman", "tmachine")]
    got = run_calibration(jobs, ledger, workers=2)
    assert got["new_calls"] == 60 - before and got["done"] == 60
    keys = [json.loads(l)["key"] for l in ledger.read_text().splitlines() if l.strip()]
    assert len(keys) == len(set(keys)) == 60


def test_calibrate_refuses_without_an_api_key(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(cli, "ENV_FILE", tmp_path / ".env")  # never the real .env, which may hold the dev key
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    monkeypatch.setattr(cli, "make_api_runner", lambda *a, **k: pytest.fail("no runner without a key"))
    assert cli.entry(["m5", "calibrate"]) == 2
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_the_cli_summarises_with_the_calibration_summary():
    import evals.calibrate
    import evals.disputes
    # cli.py also imports evals.disputes.summarise; the calibration one must not be shadowed by it, or vice versa
    assert cli.summarise_calibration is evals.calibrate.summarise and cli.summarise is evals.disputes.summarise


def test_calibrate_refuses_when_m4_inputs_are_missing(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    monkeypatch.setattr(cli, "make_api_runner", lambda *a, **k: pytest.fail("no runner without inputs"))
    assert cli.entry(["m5", "calibrate"]) == 2
    assert "calibration inputs missing" in capsys.readouterr().err
