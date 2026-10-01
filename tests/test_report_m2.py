import re

from facts.report_m2 import render_m2
from retrieval.models import RERANKERS

SENTINEL = 7777.0


class Every(dict):
    def __missing__(self, key):
        return SENTINEL


# Identifiers, not figures: the BM25 algorithm name and the reranker model names.
NAMES = "|".join(re.escape(n) for n in ("BM25",) + RERANKERS)
ALLOWED = re.compile(
    NAMES + r"|recall@\d+|precision@\d+|MRR@\d+|nDCG@\d+|\bR\d\b|\bM\d\b|\bk0\b|p50|p95|95%|bge-small-en-v1\.5|"
    r"^\| \d+ \|", re.M)


def test_every_digit_in_the_report_comes_from_facts():
    text = render_m2(Every()).replace(str(SENTINEL), "")
    stray = re.findall(r"\d", ALLOWED.sub("", text))
    assert stray == [], [line for line in text.splitlines() if re.search(r"\d", ALLOWED.sub("", line))]


def test_the_report_carries_the_required_statements():
    text = render_m2(Every())
    assert "machine-built" in text
    assert "not directly comparable" in text
    assert "label names" in text
    assert "This is not legal advice." in text


def test_no_sampled_misses_is_not_printed_as_a_measured_share():
    f = Every()
    f["m2_machine_disputed_n"] = 0
    text = render_m2(f)
    assert "no sampled misses" in text
    assert "judged that the first result also answers" not in text


def test_sampled_misses_print_the_share():
    f = Every()
    f["m2_machine_disputed_n"] = 12
    assert "judged that the first result also answers" in render_m2(f)
