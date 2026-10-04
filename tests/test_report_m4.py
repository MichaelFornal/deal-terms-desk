import json
import re
from pathlib import Path

import pytest

from facts.report_m4 import render_m4


class Every(dict):
    """Any fact name renders as a placeholder number unless overridden, so the template is checked, not the data."""
    def __missing__(self, key):
        return 0.5

    def get(self, key, default=None):  # report_m4 reads with .get so absent groups render n/a
        return self[key]


def test_report_has_every_section_and_labels_machine_built():
    text = render_m4(Every())
    for heading in ("## Answer path", "## T-human answers", "## T-machine answers (machine-built)", "## Abstention",
                    "## Citation accuracy", "## Model comparison"):
        assert heading in text
    assert text.count("machine-built") >= 3 and "This is not legal advice." in text


def test_none_renders_as_na():
    assert "n/a" in render_m4(Every(m4_thuman_haiku_report_accuracy=None))


def test_thuman_section_shows_three_rows_difference_and_coverage():
    text = render_m4(Every(m4_thuman_haiku_report_vs_baseline=0.1, m4_thuman_haiku_report_vs_baseline_lo=0.02,
                           m4_thuman_haiku_report_vs_baseline_hi=0.2, m4_thuman_haiku_report_n=7,
                           m4_thuman_haiku_report_items=9, m4_thuman_haiku_report_missing=2))
    sec = text.split("## T-human answers", 1)[1].split("\n## ", 1)[0]
    assert "counting only picks whose citations survived the gate" in sec and "Majority-answer baseline" in sec
    assert "Difference from the baseline: 0.1 (0.02 to 0.2; helps)" in sec
    assert "Scored 7 of 9 items" in sec and "2 have no answer yet" in sec and "Answered 7" not in sec
    assert "cited answers" not in text
    hurts = render_m4(Every(m4_thuman_haiku_report_vs_baseline_lo=-0.3, m4_thuman_haiku_report_vs_baseline_hi=-0.1))
    assert "hurts" in hurts
    assert "no measurable change" in render_m4(Every(m4_thuman_haiku_report_vs_baseline_lo=-0.1))


def test_tmachine_and_abstention_show_not_judged_and_missing():
    text = render_m4(Every(m4_tmachine_haiku_report_not_judged=11, m4_tmachine_haiku_report_missing=22))
    assert "not yet judged: 11" in text and "no answer yet: 22" in text
    assert "| Group | Items | Missing |" in text
    assert "A company name that matches no deal's aliases" in text and "not in the corpus" not in text


def test_absent_abstain_group_renders_na():
    class NoGroup(Every):
        def __missing__(self, key):
            return None if key.startswith("m4_abstain_schedule") else 0.5
    row = [l for l in render_m4(NoGroup()).splitlines() if l.startswith("| Answer sits")][0]
    assert row.count("n/a") == 4


def test_report_copy_has_no_hard_coded_digits():
    text = render_m4(Every())
    stripped = re.sub(r"0\.5|R6n|R7n|R6|R7|M[0-9]|@5|§[0-9.]+", "", text)
    assert not re.search(r"\d", stripped), re.findall(r".{20}\d.{20}", stripped)[:3]


def test_committed_m4_report_is_rendered_from_committed_facts():
    f = json.loads(Path("facts.json").read_text())
    if "m4_thuman_haiku_report_accuracy" not in f:
        pytest.skip("M4 facts not yet committed")
    assert Path("docs/m4/REPORT.md").read_text() == render_m4(f)


def test_absent_not_filed_is_reported_apart_with_its_answered_share():
    text = render_m4(Every(m4_abstain_absent_not_filed_answered_rate=0.75, m4_abstain_absent_not_filed_items=4,
                           m4_abstain_absent_not_judged=3, m4_abstain_absent_judge_unparsed=2))
    sec = text.split("## Abstention", 1)[1].split("\n## ", 1)[0]
    main, apart = sec.split("Machine key contradicted by retrieval", 1)
    assert "section's text was not filed" not in main and "section's title" not in main
    row = [line for line in apart.splitlines() if line.startswith("| ") and "section's title" in line][0]
    assert "the answerer found the clause text" in row and "| 4 |" in row and "0.75" in row
    assert "answered but not yet judged: 3" in main and "judge reply unreadable: 2" in main


def test_model_comparison_has_report_split_tokens_line():
    text = render_m4(Every(m4_tokens_haiku_report_in_mean=3100.5, m4_tokens_haiku_report_out_mean=210.25))
    sec = text.split("## Model comparison", 1)[1]
    assert "Mean tokens per answer on the report split (answer model): in 3100.5, out 210.25" in sec


def test_one_verdict_helper_serves_deltas_and_the_baseline_line():
    from facts.report_m4 import _change
    assert _change(0.1, 0.02, 0.2) == "0.1 (0.02 to 0.2; helps)"
    assert _change(-0.2, -0.3, -0.1) == "-0.2 (-0.3 to -0.1; hurts)"
    assert _change(0.0, -0.1, 0.1) == "0.0 (-0.1 to 0.1; no measurable change)"
    assert _change(None, -0.1, 0.1) == "n/a (-0.1 to 0.1)"


def test_abstention_table_headers_say_machine_built_key():
    sec = render_m4(Every()).split("## Abstention", 1)[1].split("\n## ", 1)[0]
    assert "| Correct decline (machine-built key) | False answer (machine-built key) |" in sec


def _sec(text, heading):
    return text.split(heading, 1)[1].split("\n## ", 1)[0]


def test_which_agreement_groups_are_reported_apart_from_the_rate_table():
    text = render_m4(Every(m4_abstain_unknown_deal_correct=29, m4_abstain_unknown_deal_items=30,
                           m4_abstain_ambiguous_deal_correct=28, m4_abstain_ambiguous_deal_items=31))
    sec = _sec(text, "## Abstention")
    table = [l for l in sec.split("### Which agreement?", 1)[0].splitlines() if l.startswith("| ")]
    assert not any("no deal's aliases" in l or "several deals" in l for l in table)
    apart = sec.split("### Which agreement?", 1)[1].split("###", 1)[0]
    assert "A company name that matches no deal's aliases: \"which agreement?\" returned: 29 of 30" in apart
    assert "A name matching several deals: \"which agreement?\" returned: 28 of 31" in apart
    assert "resolver" in apart and "not the model" in apart


def test_token_lines_say_cli_counts_upper_bound_and_no_same_items():
    text = render_m4(Every())
    sec = _sec(text, "## Model comparison")
    assert "same items" not in text
    assert "the same tune-split questions; each model's mean covers the answers it completed" in sec
    assert "`claude -p` CLI" in sec and "CLI's own system prompt" in sec and "upper bound" in sec
    assert "not an API price" in sec and "M5 measures API tokens" in sec


def test_model_comparison_ids_come_from_facts_and_name_the_self_preference_risk():
    text = render_m4(Every(m4_answer_model="answer-x", m4_compare_model="compare-y", m4_judge_model="judge-z"))
    sec = _sec(text, "## Model comparison")
    assert "| answer-x |" in sec and "| compare-y |" in sec and "claude-" not in text
    assert "same model family as the comparison answerer" in sec and "self-preference" in sec


def test_per_category_thuman_table_with_cis():
    from facts.m2 import slug
    from facts.queries import CATEGORIES
    s = slug(CATEGORIES["mae"])
    text = render_m4(Every(**{f"m4_thuman_haiku_{s}_accuracy": 0.7, f"m4_thuman_haiku_{s}_accuracy_lo": 0.6,
                              f"m4_thuman_haiku_{s}_accuracy_hi": 0.8}))
    sec = _sec(text, "## T-human answers")
    assert "| Category | Accuracy | With surviving citations | Baseline |" in sec
    row = [l for l in sec.splitlines() if l.startswith(f"| {CATEGORIES['mae']} |")][0]
    assert row.startswith(f"| {CATEGORIES['mae']} | 0.7 (0.6 to 0.8) | 0.5 (0.5 to 0.5) | 0.5 (0.5 to 0.5) |")
    assert sum(l.startswith("| ") for l in sec.split("| Category |", 1)[1].split("\n\n", 1)[0].splitlines()) == \
        len(CATEGORIES)  # one data row per category


def test_not_indexed_exclusion_is_counted_and_explained():
    sec = _sec(render_m4(Every(m4_thuman_excluded_not_indexed=4419)), "## T-human answers")
    assert "4419" in sec and "no contract text in the index" in sec and "text files are missing" in sec


def test_not_filed_row_shows_items_scored_and_missing():
    text = render_m4(Every(m4_abstain_absent_not_filed_items=7, m4_abstain_absent_not_filed_scored=6,
                           m4_abstain_absent_not_filed_missing=1))
    apart = _sec(text, "## Abstention").split("Machine key contradicted by retrieval", 1)[1]
    assert "| Group | Items | Scored | Missing | Answered share (machine-built key) |" in apart
    row = [l for l in apart.splitlines() if "section's title" in l][0]
    assert "| 7 | 6 | 1 |" in row


def test_absent_correct_cell_is_footnoted_with_unjudged_count():
    text = render_m4(Every(m4_abstain_absent_not_judged=3, m4_abstain_absent_judge_unparsed=2))
    sec = _sec(text, "## Abstention")
    row = [l for l in sec.splitlines() if l.startswith("| Lead question, both passes")][0]
    assert "*" in row
    assert "Correct (decline, or judged consistent with no such clause)" in sec
    assert "answered but not yet judged: 3" in sec and "judge reply unreadable: 2" in sec and "excluded" in sec


def test_gate_line_names_the_report_split():
    text = render_m4(Every(m4_gate_thuman_report_kept=9, m4_gate_thuman_report_returned=10))
    sec = _sec(text, "## Citation accuracy")
    assert "report split" in sec and "(9 of 10)" in sec
