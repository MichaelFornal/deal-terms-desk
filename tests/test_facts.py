import json
from pathlib import Path

import pytest

from evals.bootstrap import CI_HIGH, CI_LOW
from facts.build import build, check
from facts.queries import CATEGORIES, QUERIES
from facts.report import render
from retrieval.index import build_index

METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")
R1 = {
    "alignment": {"rows": 10, "items": 6, "items_scored": 5, "items_no_gold": 1, "items_missing_contract": 0,
                  "pieces": 8, "pieces_exact": 5, "pieces_anchored": 2, "pieces_unaligned": 1, "pieces_short": 3,
                  "pieces_ambiguous": 2, "pieces_toc_rescued": 1, "pieces_toc_only": 1},
    "overall": {m: {"mean": 0.123456, "lo": 0.1, "hi": 0.2, "n_items": 5, "n_clusters": 2} for m in METRICS},
    "by_split": {"report": {m: {"mean": 0.5, "lo": 0.4, "hi": 0.6, "n_items": 3, "n_clusters": 1}
                            for m in METRICS}},
    "by_category": {
        "Knowledge": {m: {"mean": 0.31234, "lo": 0.21, "hi": 0.41, "n_items": 40, "n_clusters": 12} for m in METRICS},
        "Remedies": {m: {"mean": 0.9, "lo": 0.8, "hi": 0.97, "n_items": 5, "n_clusters": 3} for m in METRICS},
    },
    "latency_ms": {"p50": 1.23456, "p95": 4.56789},
}
DOC = ("Section 1.1 Closing. “Closing Date” means the date of closing, and the closing occurs then "
       "(the “Closing Date”). “Merger Sub” has the meaning set forth in Section 9.1.\n\n"
       "Section 1.2 Merger. The merger occurs.\n")
HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
CSV = HEADER + (
    "main,contract_a,x,Yes,0,Fee-Answer,<NONE>,Fee,0,Remedies\n"
    "abridged,contract_a,x,Yes,0,Fee-Answer (Y/N),<NONE>,Fee,1,Remedies\n"
    "main,contract_c,x,No,1,Knowledge Definition-Answer,<NONE>,Knowledge,2,Knowledge\n"
    "rare_answers,<RARE_ANSWERS>,x,No,1,Fee-Answer,<NONE>,Fee,3,Remedies\n"
)


def make(tmp_path, r1_obj=R1):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_a": DOC, "contract_b": "no headings here at all"})
    r1 = tmp_path / "r1.json"
    r1.write_text(json.dumps(r1_obj))
    csv_path = tmp_path / "MAUD_dev.csv"
    csv_path.write_text(CSV, encoding="utf-8")
    return db, r1, [csv_path]


def test_build_runs_every_named_query(tmp_path):
    facts = build(*make(tmp_path))
    assert set(facts) == set(QUERIES)
    assert facts["maud_contracts"] == 2
    assert facts["eval_items_scored"] == 5
    assert facts["align_piece_rate"] == 0.875
    assert facts["r1_recall_at_5"] == 0.1235
    assert facts["r1_report_recall_at_5"] == 0.5
    assert 0 < facts["maud_passages_with_section_share"] < 1
    assert 0 <= facts["maud_passages_with_article_share"] <= 1


def test_defined_terms_are_distinct_real_definitions_and_cross_references_are_separate(tmp_path):
    facts = build(*make(tmp_path))
    assert facts["maud_terms_defined"] == 1
    assert facts["maud_terms_xref"] == 1
    assert "maud_terms" not in facts


def test_label_csvs_are_recounted(tmp_path):
    facts = build(*make(tmp_path))
    assert facts["maud_label_rows_all"] == 4
    assert facts["maud_label_contracts"] == 2
    assert facts["maud_label_contracts_with_text"] == 1
    assert facts["maud_question_types"] == 3


def test_alignment_counts_are_published(tmp_path):
    facts = build(*make(tmp_path))
    assert (facts["align_pieces_short"], facts["align_pieces_ambiguous"],
            facts["align_pieces_toc_rescued"], facts["align_pieces_toc_only"]) == (3, 2, 1, 1)


def test_every_report_split_metric_has_an_interval(tmp_path):
    facts = build(*make(tmp_path))
    for name in ("recall_at_1", "recall_at_5", "recall_at_10", "mrr_at_10", "ndcg_at_10"):
        assert facts[f"r1_report_{name}_lo"] == 0.4 and facts[f"r1_report_{name}_hi"] == 0.6


def test_every_category_has_recall_at_5_with_interval_and_counts(tmp_path):
    facts = build(*make(tmp_path))
    assert facts["r1_cat_knowledge_recall_at_5"] == 0.3123
    assert facts["r1_cat_knowledge_recall_at_5_lo"] == 0.21
    assert facts["r1_cat_knowledge_recall_at_5_hi"] == 0.41
    assert facts["r1_cat_knowledge_items"] == 40
    assert facts["r1_cat_knowledge_contracts"] == 12
    assert facts["r1_cat_mae_recall_at_5"] is None and facts["r1_cat_mae_items"] == 0


def test_a_category_without_a_named_query_is_refused(tmp_path):
    r1 = json.loads(json.dumps(R1))
    r1["by_category"]["Brand New Family"] = r1["by_category"]["Remedies"]
    with pytest.raises(ValueError, match="Brand New Family"):
        build(*make(tmp_path, r1))


def test_check_reports_stale_facts(tmp_path):
    db, r1, csvs = make(tmp_path)
    path = tmp_path / "facts.json"
    facts = build(db, r1, csvs)
    path.write_text(json.dumps(facts))
    assert check(db, r1, path, csvs) == []
    facts["maud_contracts"] = 999
    path.write_text(json.dumps(facts))
    assert check(db, r1, path, csvs) == ["maud_contracts"]


def test_check_reports_a_missing_facts_file(tmp_path):
    db, r1, csvs = make(tmp_path)
    assert check(db, r1, tmp_path / "absent.json", csvs) == sorted(QUERIES)


def test_report_prints_only_values_from_facts(tmp_path):
    facts = build(*make(tmp_path))
    text = render(facts)
    assert "machine" not in text.lower()
    assert "human-labelled (MAUD)" in text
    for name in ("maud_contracts", "r1_report_recall_at_5", "align_piece_rate", "maud_terms_defined",
                 "maud_terms_xref", "maud_label_rows_all", "maud_question_types", "align_pieces_short",
                 "r1_report_ndcg_at_10_lo", "r1_report_mrr_at_10_hi", "r1_cat_knowledge_recall_at_5_lo"):
        assert str(facts[name]) in text


def test_report_has_a_row_per_category_and_flags_thin_strata(tmp_path):
    text = render(build(*make(tmp_path)))
    rows = {line.split("|")[1].strip(): line for line in text.splitlines() if line.startswith("| ")}
    for category in CATEGORIES.values():
        assert category in rows
    assert "few agreements, interval unreliable" in rows["Remedies"]
    assert "few agreements" not in rows["Knowledge"]
    assert "no scored items" in rows["Material Adverse Effect"]


def test_bootstrap_quantiles_match_the_reports_95_percent():
    assert (CI_LOW, CI_HIGH) == (0.025, 0.975)
    assert "Intervals are 95%" in render({name: 0 for name in QUERIES})


ROOT = Path(__file__).resolve().parent.parent


def test_committed_facts_file_has_exactly_the_named_queries():
    path = ROOT / "facts.json"
    if path.exists():
        keys = set(json.loads(path.read_text()))
        assert {k for k in keys if not k.startswith(("m2_", "m0_", "m3_"))} == set(QUERIES)
        m2 = {k for k in keys if k.startswith("m2_")}
        if m2:
            assert {"m2_r1_report_recall_at_5", "m2_r6_report_recall_at_5"} <= m2
        m3 = {k for k in keys if k.startswith("m3_")}
        if m3:
            assert {"m3_t_r1_report_recall_at_5", "m3_t_r7_corpus_report_recall_at_5",
                    "m3_tier_tau"} <= m3


def test_committed_report_is_rendered_from_committed_facts():
    facts, report = ROOT / "facts.json", ROOT / "docs" / "m1" / "REPORT.md"
    if facts.exists() and report.exists():
        assert render(json.loads(facts.read_text(encoding="utf-8"))) == report.read_text(encoding="utf-8")
