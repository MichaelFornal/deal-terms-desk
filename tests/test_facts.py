import json
import sqlite3

from facts.build import build, check
from facts.queries import QUERIES
from facts.report import render
from retrieval.index import build_index

R1 = {
    "alignment": {"rows": 10, "items": 6, "items_scored": 5, "items_no_gold": 1, "items_missing_contract": 0,
                  "pieces": 8, "pieces_exact": 5, "pieces_anchored": 2, "pieces_unaligned": 1},
    "overall": {m: {"mean": 0.123456, "lo": 0.1, "hi": 0.2, "n_items": 5, "n_clusters": 2}
                for m in ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")},
    "by_split": {"report": {m: {"mean": 0.5, "lo": 0.4, "hi": 0.6, "n_items": 3, "n_clusters": 1}
                            for m in ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")}},
    "latency_ms": {"p50": 1.23456, "p95": 4.56789},
}
DOC = "Section 1.1 Closing. “Closing Date” means the date of closing.\n\nSection 1.2 Merger. The merger occurs.\n"


def make(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_a": DOC, "contract_b": "no headings here at all"})
    r1 = tmp_path / "r1.json"
    r1.write_text(json.dumps(R1))
    return db, r1


def test_build_runs_every_named_query(tmp_path):
    db, r1 = make(tmp_path)
    facts = build(db, r1)
    assert set(facts) == set(QUERIES)
    assert facts["maud_contracts"] == 2
    assert facts["maud_terms"] == 1
    assert facts["eval_items_scored"] == 5
    assert facts["align_piece_rate"] == 0.875
    assert facts["r1_recall_at_5"] == 0.1235
    assert facts["r1_report_recall_at_5"] == 0.5
    assert 0 < facts["maud_passages_with_section_share"] < 1


def test_check_reports_stale_facts(tmp_path):
    db, r1 = make(tmp_path)
    path = tmp_path / "facts.json"
    facts = build(db, r1)
    path.write_text(json.dumps(facts))
    assert check(db, r1, path) == []
    facts["maud_contracts"] = 999
    path.write_text(json.dumps(facts))
    assert check(db, r1, path) == ["maud_contracts"]


def test_check_reports_a_missing_facts_file(tmp_path):
    db, r1 = make(tmp_path)
    assert check(db, r1, tmp_path / "absent.json") == sorted(QUERIES)


def test_report_prints_only_values_from_facts(tmp_path):
    db, r1 = make(tmp_path)
    facts = build(db, r1)
    text = render(facts)
    assert "machine" not in text.lower()
    assert "human-labelled (MAUD)" in text
    for name in ("maud_contracts", "r1_report_recall_at_5", "align_piece_rate"):
        assert str(facts[name]) in text


def test_committed_facts_file_has_exactly_the_named_queries():
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "facts.json"
    if path.exists():
        assert set(json.loads(path.read_text())) == set(QUERIES)
