import re

from facts.report_m3 import render_m3

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


ALLOWED = re.compile(r"\bM\d\b|\bR\d\b|@\d+|\bp95\b|§\d+(?:\.\d+)?")


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m3(Every()).replace(str(SENTINEL), "")
    lines = [l for l in text.splitlines() if re.search(r"\d", ALLOWED.sub("", l))]
    assert lines == []


def test_machine_built_numbers_are_labelled_and_the_disclaimer_is_there():
    text = render_m3(Every())
    for heading in ("## T-machine labels", "## The ladder on T-machine", "## Tier agreement"):
        section = text.split(heading, 1)[1].split("\n## ", 1)[0]
        assert "machine-built" in section, heading
    assert "This is not legal advice." in text


def test_missing_values_print_as_na():
    text = render_m3(Every(m3_tm_equity_awards_agreement_rate=None, m3_tier_tau=None))
    assert "n/a" in text
