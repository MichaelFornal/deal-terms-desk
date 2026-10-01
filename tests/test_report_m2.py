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
    NAMES + r"|recall@\d+|precision@\d+|MRR@\d+|nDCG@\d+|\bR\d\b|\bM\d\b|\bk0\b|p50|p95|95%|"
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


def test_rewriting_section_is_labelled_machine_built():
    text = render_m2(Every())
    section = text.split("## Query rewriting")[1].split("\n## ")[0]
    assert section.count("machine-built") >= 3


def test_no_python_literals_are_printed():
    f = Every()
    f["m2_r1_context_tokens_mean"] = None
    f["m2_tuned_live_path_ok"] = False
    text = render_m2(f)
    assert "None" not in text and "True" not in text and "False" not in text
    assert "not measured" in text and "Live path within the limit: no." in text


def test_rung_two_names_the_model_from_the_facts():
    f = Every()
    f["m2_vec_model"] = "some-model"
    assert "Dense only (some-model in sqlite-vec)" in render_m2(f)


def test_rewriting_section_caveats_the_token_measurement():
    section = render_m2(Every()).split("## Query rewriting")[1].split("\n## ")[0]
    assert "measured through `claude -p` (includes the CLI's own prompt and any thinking); a direct API call would cost less" in section


def _tuning_section(f):
    text = render_m2(f)
    return text.split("## Tuning", 1)[1].split("\n## ", 1)[0]


def test_tuning_shows_r3_and_the_chosen_reranker_by_depth():
    from evals.tune import GRID_RERANK_DEPTH
    f = Every()
    f["m2_tune_r3_recall_at_5"] = 0.1234
    f["m2_tune_r3_p95_ms"] = 55.5
    for d in GRID_RERANK_DEPTH:
        f[f"m2_tune_depth_{d}_recall_at_5"] = 0.2000 + d / 1000
        f[f"m2_tune_depth_{d}_p95_ms"] = 900.5 + d
    section = _tuning_section(f)
    assert "Chosen reranker by rerank depth" in section
    assert "hybrid without a reranker (R3) scored 0.1234" in section
    assert "(p95 55.5 ms)" in section
    for d in GRID_RERANK_DEPTH:
        assert f"| {d} | {0.2 + d / 1000} | {900.5 + d} |" in section


def test_probe_clause_only_when_the_probe_did_not_qualify():
    f = Every()
    f["m2_tune_probe_qualified"] = False
    assert "no reranker qualified at the probe depth" in _tuning_section(f)
    f["m2_tune_probe_qualified"] = True
    assert "no reranker qualified" not in _tuning_section(f)


def test_live_path_sentence_names_the_chosen_depth():
    f = Every()
    f["m2_tuned_rerank_depth"] = 10
    f["m2_tuned_live_path_ok"] = True
    assert "Live path within the limit at the chosen depth (10): yes" in _tuning_section(f)
    f["m2_tuned_live_path_ok"] = False
    assert "chosen depth (10): no" in _tuning_section(f)
