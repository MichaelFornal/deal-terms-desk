import json

import pytest

from evals.items import Item
from evals.run_rung import Context, evaluate
from facts.m4 import build_m4, present_m4
from retrieval.bm25 import Hit
from retrieval.result import Retrieved

H = "claude-haiku-4-5-20251001"
CI = {"mean": 0.5, "lo": 0.4, "hi": 0.6, "n_items": 10, "n_clusters": 5}


def _evaluate_all(tmp_path):
    ctx = Context([Item(f"{c}|f", c, "termination_fee", "termination_fee", "q", ((0, 10),)) for c in ("edgar_a", "edgar_d")],
                  {}, {}, {"edgar_a": [(0, 10)], "edgar_d": [(0, 10)]})

    def r(q, c, k):
        return Retrieved([Hit(1, c or "edgar_a", 0, 10, 1.0)], 1.0, [])
    out, m4 = tmp_path / "out", tmp_path / "out" / "m4"
    for name, d in (("R6", out), ("T-R6", out / "m3"), ("R6n", m4), ("T-R6n", m4), ("T-R7-corpus", m4),
                    ("T-R7n-corpus", m4)):
        evaluate(ctx, name, r, d, n_boot=20)
    return out, m4


def _scores(**over):
    s = {"thuman": {H: {"report": {"accuracy": CI, "accuracy_cited": {**CI, "mean": 0.45}, "baseline": CI,
                                   "vs_baseline": {**CI, "mean": 0.1, "lo": 0.02, "hi": 0.2}, "n": 10, "items": 12,
                                   "missing": 2, "errors": 0, "out_of_list": 1,
                                   "by_category": {"Deal Structure": {"accuracy": CI, "accuracy_cited": CI,
                                                                      "baseline": CI}}},
                       "tune": {"accuracy": CI, "baseline": CI, "n": 4, "errors": 0, "out_of_list": 0,
                                "by_category": {}}}},
         "tmachine": {H: {"report": {"agree": CI, "agree_or_partial": CI, "declined": 1, "wrong_deal": 0,
                                     "judge_unparsed": 0, "not_judged": 2, "missing": 1, "items": 13, "errors": 0,
                                     "n": 10,
                                     "by_family": {"termination_fee": {"agree": CI, "agree_or_partial": CI}}},
                          "tune": {"agree": CI, "agree_or_partial": CI, "declined": 0, "wrong_deal": 0,
                                   "judge_unparsed": 0, "errors": 0, "n": 3, "by_family": {}}}},
         "abstain": {"earnout": {"n": 30, "items": 32, "missing": 2, "correct": 27, "false_answer": 2, "other": 1,
                                 "errors": 0, "correct_rate": 0.9, "false_answer_rate": 0.0667}},
         "gate": {"thuman": {"returned": 10, "kept": 9, "pass_rate": 0.9, "by_reason": {}}},
         "refute": {"claims": 9, "not_refuted": 8, "unparsed": 0, "survival_rate": 0.8889},
         "tokens": {H: {"thuman": {"in_mean": 3000.0, "out_mean": 200.0, "n": 14}}}}
    s.update(over)
    return s


def _setup(tmp_path, scores):
    out, m4 = _evaluate_all(tmp_path)
    (m4 / "scores.json").write_text(json.dumps(scores))
    data = tmp_path / "data_m4"
    data.mkdir()
    (data / "sets_summary.json").write_text(json.dumps({"thuman": 14, "tmachine": 13, "abstain": {"earnout": 30},
        "thuman_excluded": {"disputed": 2, "too_many_options": 5, "questions_too_many_options": 2, "not_indexed": 0}}))
    return out, m4, data


def test_build_m4_reads_scores_sets_and_recall(tmp_path):
    out, m4, data = _setup(tmp_path, _scores())
    assert present_m4(m4)
    f = build_m4(m4, out, data, n_boot=20)
    assert f["m4_thuman_haiku_report_accuracy"] == 0.5 and f["m4_thuman_haiku_report_accuracy_lo"] == 0.4
    assert f["m4_tmachine_haiku_termination_fee_agree"] == 0.5 and f["m4_abstain_earnout_correct_rate"] == 0.9
    assert f["m4_gate_thuman_pass_rate"] == 0.9 and f["m4_refute_survival_rate"] == 0.8889
    assert f["m4_r6n_report_recall_at_5"] == 1.0 and "m4_cmp_t_r7n_vs_t_r7_corpus_recall_at_5_delta" in f
    assert f["m4_cmp_model_haiku_tokens_in_mean"] == 3000.0 and f["m4_cmp_model_sonnet_tokens_in_mean"] is None
    assert f["m4_thuman_questions_too_many_options"] == 2 and f["m4_abstain_earnout_n"] == 30
    assert all(k.startswith("m4_") for k in f)


def test_build_m4_carries_items_missing_cited_and_baseline_difference(tmp_path):
    out, m4, data = _setup(tmp_path, _scores())
    f = build_m4(m4, out, data, n_boot=20)
    assert (f["m4_thuman_haiku_report_items"], f["m4_thuman_haiku_report_missing"]) == (12, 2)
    assert f["m4_thuman_haiku_report_accuracy_cited"] == 0.45 and f["m4_thuman_haiku_report_accuracy_cited_lo"] == 0.4
    assert (f["m4_thuman_haiku_report_vs_baseline"], f["m4_thuman_haiku_report_vs_baseline_lo"],
            f["m4_thuman_haiku_report_vs_baseline_hi"]) == (0.1, 0.02, 0.2)
    assert f["m4_thuman_haiku_deal_structure_accuracy_cited"] == 0.5
    assert (f["m4_tmachine_haiku_report_items"], f["m4_tmachine_haiku_report_missing"],
            f["m4_tmachine_haiku_report_not_judged"]) == (13, 1, 2)
    assert (f["m4_abstain_earnout_items"], f["m4_abstain_earnout_missing"]) == (32, 2)


def test_missing_blocks_and_absent_groups_become_none_or_absent(tmp_path):
    s = _scores()
    for k in ("accuracy_cited", "vs_baseline"):
        del s["thuman"][H]["report"][k]
    out, m4, data = _setup(tmp_path, s)
    f = build_m4(m4, out, data, n_boot=20)
    for k in ("accuracy_cited", "vs_baseline"):
        assert [f[f"m4_thuman_haiku_report_{k}{x}"] for x in ("", "_lo", "_hi")] == [None] * 3
    assert "m4_abstain_unknown_deal_correct_rate" not in f


def test_build_m4_names_every_missing_input(tmp_path):
    with pytest.raises(FileNotFoundError, match="scores.json"):
        build_m4(tmp_path / "m4", tmp_path, tmp_path / "d")


def test_absent_not_filed_answered_rate_and_judge_counts(tmp_path):
    ab = {"absent": {"n": 8, "items": 10, "missing": 0, "correct": 6, "false_answer": 1, "other": 1, "errors": 0,
                     "not_judged": 1, "judge_unparsed": 1, "correct_rate": 0.75, "false_answer_rate": 0.125},
          "absent_not_filed": {"n": 4, "items": 4, "missing": 0, "correct": 1, "false_answer": 3, "other": 0,
                               "errors": 0, "not_judged": 0, "judge_unparsed": 0, "correct_rate": 0.25,
                               "false_answer_rate": 0.75}}
    out, m4, data = _setup(tmp_path, _scores(abstain=ab))
    f = build_m4(m4, out, data, n_boot=20)
    assert f["m4_abstain_absent_not_filed_answered_rate"] == 0.75
    assert (f["m4_abstain_absent_not_judged"], f["m4_abstain_absent_judge_unparsed"]) == (1, 1)
    out2, m42, data2 = _setup(tmp_path / "b", _scores())
    assert build_m4(m42, out2, data2, n_boot=20)["m4_abstain_absent_not_filed_answered_rate"] is None
