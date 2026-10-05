import collections
import json
import re
from pathlib import Path

from facts.labels import HUMAN, MACHINE, is_machine_built, tier_label
from facts.m5 import build_m5
from facts.report_m5 import render_m5
from tests.test_facts_m5 import every_input

NUM = re.compile(r"[-+]?\d+\.\d+")
# Realistic M5 values that no committed fact holds, so the check below can tell which fact a printed number is.
M5_CALIBRATION = {"api_tokens_in_mean": 4183.6, "api_tokens_out_mean": 312.4, "cost_usd_total": 0.2731,
                  "cost_per_answer_mean": 0.0071, "cost_per_answer_p95": 0.0094, "state_agreement": 0.9211,
                  "gate_pass_rate": {"api": 0.8714, "cli": 0.8633},
                  "thuman_accuracy": {"api": 0.6316, "cli": 0.5789, "diff": 0.0527, "n": 19}}
M5_SERVER = {"search": {"e2e": {"n": 50, "p50": 131.2, "p95": 208.7}, "server": {"n": 50, "p50": 23.4, "p95": 41.9}},
             "ask_cached": {"e2e": {"n": 6, "p50": 118.3, "p95": 162.5}, "server": {"n": 6, "p50": 3.1, "p95": 4.6},
                            "states": {}},
             "ask_fresh": {"e2e": {"n": 3, "p50": 4310.2, "p95": 5120.8}, "server": {"n": 3, "p50": 4204.5,
                                                                                     "p95": 5003.3}, "states": {}},
             "rss_mb": 912.4}


def machine_line_check(facts: dict, reports) -> tuple[list[str], list[tuple[str, str]]]:
    """Take every number on a report line that says machine-built, or under a heading ending "(machine-built)".
    When it is a float held by exactly one fact, that fact must be machine-built. "machine-built lexicon" describes
    R5's method, not the number beside it. `reports`: (name, text) pairs. -> (facts checked, (report, fact) pairs
    printed as machine-built that are not)."""
    by_value = collections.defaultdict(list)
    for k, v in facts.items():
        if isinstance(v, float):
            by_value[v].append(k)
    unique = {v: ks[0] for v, ks in by_value.items() if len(ks) == 1}
    checked, wrong = [], []
    for name, text in reports:
        for section in re.split(r"\n(?=## )", text):
            whole = "(machine-built)" in section.splitlines()[0]
            for line in section.splitlines():
                line = line.replace("machine-built lexicon", "")
                if not (whole or "machine-built" in line):
                    continue
                for n in NUM.findall(line):
                    key = unique.get(float(n))
                    if key is not None and n.lstrip("+") == str(facts[key]):
                        checked.append(key)
                        if not is_machine_built(key):
                            wrong.append((name, key))
    return checked, wrong


def test_known_keys_are_classified():
    assert is_machine_built("m3_t_r6_report_recall_at_5") and is_machine_built("m3_tier_r1_machine_recall_at_5")
    assert is_machine_built("m2_r5_llm_report_recall_at_5") and is_machine_built("m4_cmp_model_haiku_tmachine_tune_agree")
    assert not is_machine_built("m3_tier_r1_human_recall_at_5") and not is_machine_built("m4_tokens_haiku_report_in_mean")
    assert tier_label("m2_r5_report_recall_at_5") == HUMAN and tier_label("m4_thuman_haiku_report_accuracy") == HUMAN
    assert tier_label("m4_refute_survival_rate") == MACHINE and tier_label("m4_gate_thuman_report_pass_rate") is None


def test_m5_labels_follow_where_the_judgement_comes_from(tmp_path):
    """machine-built: a model judges correctness (here, API-vs-CLI answer-state agreement). human-labelled (MAUD):
    scored against MAUD's key. No label: plain measurements (tokens, money, caps, hosting, latency, memory, bytes,
    sha, sample counts, the deterministic parity counts, the citation gate's pass rate, the cap-trip results)."""
    m5 = build_m5(*every_input(tmp_path))
    by_label = collections.defaultdict(set)
    for k in m5:
        by_label[tier_label(k)].add(k)
    assert by_label[MACHINE] == {"m5_calibration_state_agreement"}
    assert by_label[HUMAN] == {"m5_bundle_r6n_report_recall_at_5", "m5_bundle_r6n_report_recall_at_5_lo",
                               "m5_bundle_r6n_report_recall_at_5_hi", "m5_calibration_accuracy_api",
                               "m5_calibration_accuracy_cli"}
    for k in ("m5_api_tokens_in_mean", "m5_cost_per_answer_mean", "m5_model_cap_usd", "m5_server_rss_mb",
              "m5_prompt_parity_same", "m5_bundle_parity_same", "m5_server_embed_parity", "m5_calibration_n",
              "m5_calibration_gate_pass_api", "m5_cap_trip_budget_reached", "m5_bundle_bytes"):
        assert k in by_label[None], k


def test_every_number_the_reports_print_as_machine_built_is_classified_so():
    """Cross-check against every committed report, docs/m*/REPORT.md: M0 to M4, and M5 once its report is
    committed (the next test simulates that)."""
    f = json.loads(Path("facts.json").read_text())
    reports = [(r.parent.name, r.read_text()) for r in sorted(Path("docs").glob("m*/REPORT.md"))]
    checked, wrong = machine_line_check(f, reports)
    assert len(checked) > 100 and wrong == []  # planning measured 159 checks, 0 wrong


def test_a_committed_m5_report_passes_the_same_check(tmp_path):
    """docs/m5/REPORT.md lands late in M5, and the check above then reads it. Render it now, from the committed
    facts plus every M5 fact at a realistic value, and run the same check."""
    f = json.loads(Path("facts.json").read_text()) | build_m5(*every_input(tmp_path, M5_CALIBRATION, M5_SERVER))
    checked, wrong = machine_line_check(f, [("m5", render_m5(f))])
    assert wrong == [] and "m5_calibration_state_agreement" in checked
