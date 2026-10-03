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


def test_a_missing_comparison_prints_na_and_no_verdict():
    text = render_m3(Every(m3_cmp_t_r2_vs_t_r1_recall_at_5_delta=None, m3_cmp_t_r2_vs_t_r1_recall_at_5_lo=None,
                           m3_cmp_t_r2_vs_t_r1_recall_at_5_hi=None))
    row = next(l for l in text.splitlines() if l.startswith("| R2 dense |"))
    assert "n/a (n/a to n/a)" in row and "helps" not in row and "hurts" not in row and "no measurable" not in row


def test_empty_tier_orders_print_na():
    text = render_m3(Every(m3_tier_human_order="", m3_tier_machine_order=""))
    tier = text.split("## Tier agreement", 1)[1]
    assert "lawyers' key n/a; machine-built key n/a" in tier


def test_the_fix_wave_sentences_and_tables():
    text = render_m3(Every())
    ladder = text.split("## The ladder on T-machine", 1)[1].split("\n## ", 1)[0]
    assert "Same questions without the company name" in ladder and "tokens" in ladder
    assert "company's name" in ladder and "keyword search" in ladder
    bare = ladder.split("Same questions without the company name", 1)[1]
    assert bare.count("| R") >= 6 and "vs the question naming the company" in bare
    r7 = text.split("## R7", 1)[1].split("\n## ", 1)[0]
    assert "drops the company's name" in r7
    tm = text.split("## T-machine labels", 1)[1].split("\n## ", 1)[0]
    assert "ledgered model replies" in tm and "model calls" not in tm and "asked one at a time" in tm
    corpus = text.split("## Corpus", 1)[1].split("\n## ", 1)[0]
    assert "both in MAUD and among the tech deals" in corpus


def test_committed_m3_report_is_rendered_from_committed_facts():
    import json
    from pathlib import Path
    import pytest
    root = Path(__file__).resolve().parent.parent
    facts, report = root / "facts.json", root / "docs" / "m3" / "REPORT.md"
    if not (facts.exists() and report.exists()):
        pytest.skip("no committed M3 facts or report")
    f = json.loads(facts.read_text(encoding="utf-8"))
    if "m3_t_bare_r1_report_recall_at_5" not in f:
        pytest.skip("committed facts predate the fix-wave rerun (no bare-question facts yet)")
    assert render_m3(f) == report.read_text(encoding="utf-8")
