import re

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
        super().__init__(m0_sec_requests=SENTINEL, m0_min_request_gap_s=SENTINEL, m0_blocked_events=SENTINEL)


def test_the_access_sentence_is_built_from_facts():
    text = render_m0(EveryWithAccess())
    assert "Every request followed" not in text
    line = text[text.index("Requests made to sec.gov"):].splitlines()[0]
    assert line.count(str(SENTINEL)) == 3 and "smallest gap between request starts" in line
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
