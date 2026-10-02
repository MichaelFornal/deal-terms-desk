import re

from facts.report_m0 import render_m0

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


ALLOWED = re.compile(r"\bM\d\b|§\d+(?:\.\d+)?|EX-2\.1|EX-99\.1|\b8-K\b")


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m0(Every()).replace(str(SENTINEL), "")
    lines = [l for l in text.splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_the_report_states_the_gate_and_its_labels():
    text = render_m0(Every())
    assert "machine-built" in text and "Gate" in text and "This is not legal advice." in text
