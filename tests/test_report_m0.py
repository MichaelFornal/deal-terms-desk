import json
import re
from pathlib import Path

import pytest

from facts.report_m0 import render_m0

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


ALLOWED = re.compile(r"\bM\d\b|§\d+(?:\.\d+)?|EX-2(?:\.1)?\b|EX-99\b|\b8-K\b")


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m0(Every()).replace(str(SENTINEL), "")
    lines = [l for l in text.splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_the_report_states_the_gate_and_its_labels():
    text = render_m0(Every())
    assert "machine-built" in text and "Gate" in text and "This is not legal advice." in text


class EveryWithAccess(Every):
    def __init__(self):
        super().__init__(m0_sec_requests=SENTINEL, m0_min_request_gap_s=SENTINEL, m0_blocked_events=SENTINEL,
                         m0_server_errors=SENTINEL, m0_server_errors_recorded_later=SENTINEL)


def test_the_access_sentence_is_built_from_facts():
    text = render_m0(EveryWithAccess())
    assert "Every request followed" not in text
    line = text[text.index("Requests made to sec.gov"):].splitlines()[0]
    assert line.count(str(SENTINEL)) == 5 and "smallest gap between request starts" in line
    assert "server errors" in line and "retried up to twice after a wait" in line
    assert "recorded after the fact" in line
    lines = [l for l in text.replace(str(SENTINEL), "").splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_the_gate_is_labelled_machine_built_and_shows_targets():
    text = render_m0(Every())
    gate = text.split("## Gate")[1].split("\n## ")[0]
    family = next(l for l in gate.splitlines() if "lead family" in l)
    assert "(machine-built)" in family
    assert "machine-built sample" in gate
    tech = next(l for l in gate.splitlines() if "Tech agreements" in l)
    assert "distinct target" in tech
    assert "an EX-99 exhibit (usually the press release)" in text and "EX-99.1" not in text


def test_no_access_log_says_so_without_numbers():
    text = render_m0(Every())
    assert "Every request followed" not in text and "No sec.gov request log" in text


class EveryWithCandidates(Every):
    def __init__(self, ok=True):
        super().__init__(m0_candidate_sample=SENTINEL, m0_adopted_family="employee_benefits", m0_gate_pass_adopted=ok)


def test_candidate_section_absent_without_candidate_facts():
    assert "Replacement lead family" not in render_m0(Every())


def test_candidate_section_is_labelled_and_has_no_stray_digits():
    text = render_m0(EveryWithCandidates())
    assert text.index("## Gate") < text.index("## Replacement lead family (decided 7777.0)") < text.index("## How the corpus")
    sec = text.split("## Replacement lead family")[1].split("\n## ")[0]
    assert "machine-built" in sec and "verbatim" in sec and "earn-out" in sec
    assert "Gate with the adopted family: PASS" in sec
    for label in ("Employees' pay and benefits", "Buyer financing", "Go-shop period"):
        row = next(l for l in sec.splitlines() if l.startswith("| " + label))
        assert row.count(str(SENTINEL)) == 4
    gate = text.split("## Gate")[1].split("\n## ")[0]
    assert "recorded a replacement family" in gate and "fallback applies" not in gate
    assert "fallback applies" in render_m0(Every())
    assert "bare buyer termination-fee" in sec
    assert "Gate with the adopted family: FAIL" in render_m0(EveryWithCandidates(False))
    lines = [l for l in text.replace(str(SENTINEL), "").splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_the_index_size_estimate_names_the_current_index():
    text = render_m0(Every(m0_estimate_index_bytes=SENTINEL))
    assert "Estimated index size from the current section-aware index's bytes per passage" in text
    assert "M2's bytes per passage" not in text


def test_committed_m0_report_is_rendered_from_committed_facts():
    root = Path(__file__).resolve().parent.parent
    f = json.loads((root / "facts.json").read_text(encoding="utf-8"))
    if "m0_gate_pass" not in f:
        pytest.skip("M0 facts not committed")
    assert (root / "docs" / "m0" / "REPORT.md").read_text(encoding="utf-8") == render_m0(f)
