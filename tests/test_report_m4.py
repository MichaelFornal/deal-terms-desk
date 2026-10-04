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
    assert "Answered 7 of 9 items" in sec and "2 have no answer yet" in sec
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
    stripped = re.sub(r"0\.5|R6n|R7n|R6|R7|M[0-9]|claude-[a-z0-9.\-]+|@5|§[0-9.]+", "", text)
    assert not re.search(r"\d", stripped), re.findall(r".{20}\d.{20}", stripped)[:3]


def test_committed_m4_report_is_rendered_from_committed_facts():
    f = json.loads(Path("facts.json").read_text())
    if "m4_thuman_haiku_report_accuracy" not in f:
        pytest.skip("M4 facts not yet committed")
    assert Path("docs/m4/REPORT.md").read_text() == render_m4(f)


def test_absent_not_filed_is_reported_apart_with_its_answered_share():
    text = render_m4(Every(m4_abstain_absent_not_filed_answered_rate=0.75, m4_abstain_absent_not_filed_n=4,
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
