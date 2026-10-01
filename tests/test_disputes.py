import sqlite3

from evals.disputes import judge, sample_misses, summarise, verdict
from retrieval.index import build_index
from tests.fakes import fake_claude

DOC = "Section 1.1 Fees. The Company shall pay the Termination Fee.\n\nSection 1.2 Other. The Parent shall pay the Reverse Termination Fee.\n"


def rows():
    base = {"contract_id": "c", "category": "Remedies", "query": "Termination Fee", "gold": [[0, 40]]}
    return {
        "c|a": {**base, "item_id": "c|a", "split": "report", "mrr@10": 0.5, "top_passage_ids": [2, 1]},
        "c|b": {**base, "item_id": "c|b", "split": "report", "mrr@10": 1.0, "top_passage_ids": [1]},
        "c|t": {**base, "item_id": "c|t", "split": "tune", "mrr@10": 0.0, "top_passage_ids": [2]},
    }


def test_sample_takes_report_items_whose_first_result_is_not_gold():
    assert [r["item_id"] for r in sample_misses(rows(), n=10)] == ["c|a"]


def test_verdict_needs_true_and_a_verbatim_quote():
    retrieved = "The Parent shall pay the\nReverse Termination Fee."
    assert verdict('{"answers": true, "quote": "shall pay the Reverse Termination Fee"}', retrieved)
    assert not verdict('{"answers": true, "quote": "shall pay a fee"}', retrieved)
    assert not verdict('{"answers": false, "quote": "shall pay the"}', retrieved)
    assert not verdict("not json", retrieved)
    assert not verdict('{"answers": true, "quote": "a"}', "a fee")


def test_judge_asks_once_per_item_and_resumes(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    conn = sqlite3.connect(db)
    runner = fake_claude('{"answers": true, "quote": "Reverse Termination Fee"}')
    sample = sample_misses(rows(), n=10)
    first = judge(sample, {"c": DOC}, conn, tmp_path / "d.jsonl", runner=runner, model="m")
    assert [r["disputed"] for r in first] == [True] and len(runner.calls) == 1
    assert "Reverse Termination Fee" in runner.calls[0][0] and "Termination Fee" in runner.calls[0][0]
    again = fake_claude("unused")
    assert judge(sample, {"c": DOC}, conn, tmp_path / "d.jsonl", runner=again, model="m") == first
    assert again.calls == []
    assert summarise(first, n_boot=50)["mean"] == 1.0


def test_cache_is_keyed_on_passage_and_model(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    conn = sqlite3.connect(db)
    ok = '{"answers": true, "quote": "Reverse Termination Fee"}'
    sample = sample_misses(rows(), n=10)
    path = tmp_path / "d.jsonl"
    runner = fake_claude(ok)
    judge(sample, {"c": DOC}, conn, path, runner=runner, model="m")
    judge(sample, {"c": DOC}, conn, path, runner=runner, model="m")
    assert len(runner.calls) == 1
    judge(sample, {"c": DOC}, conn, path, runner=runner, model="other")
    assert len(runner.calls) == 2
    moved = [{**sample[0], "top_passage_ids": [1, 2]}]
    out = judge(moved, {"c": DOC}, conn, path, runner=runner, model="m")
    assert len(runner.calls) == 3 and out[0]["passage_id"] == 1


def test_judged_records_keep_the_usage(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    runner = fake_claude('{"answers": true, "quote": "Reverse Termination Fee"}', input_tokens=7, output_tokens=3)
    out = judge(sample_misses(rows(), n=10), {"c": DOC}, sqlite3.connect(db), tmp_path / "d.jsonl",
                runner=runner, model="m")
    assert out[0]["usage"] == {"input_tokens": 7, "output_tokens": 3}
