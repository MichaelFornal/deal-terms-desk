import json
import re
from pathlib import Path

import pytest

from facts.report_m5 import render_m5


class Every(dict):
    """Any fact renders as a placeholder number unless overridden, so the template is checked, not the data."""
    def __missing__(self, key):
        return 0.5

    def get(self, key, default=None):
        return self[key]


def test_report_has_every_section_and_its_labels():
    text = render_m5(Every())
    for heading in ("## Live index", "## The same path the evals measured", "## API calibration",
                    "## Cost and budget", "## Server", "## The cap trips"):
        assert heading in text
    assert "human-labelled (MAUD)" in text and "This is not legal advice." in text


def test_missing_facts_render_pending():
    text = render_m5({})
    assert "pending" in text and "None" not in text


def test_report_copy_has_no_hard_coded_digits():
    text = render_m5(Every())
    stripped = re.sub(r"0\.5|R6n|R7n|M[0-9]|@5|\bp(?:50|95)\b|sha256|docs/m5/kill-test\.log", "", text)
    assert not re.search(r"\d", stripped), re.findall(r".{20}\d.{20}", stripped)[:3]


def test_committed_m5_report_is_rendered_from_committed_facts():
    f = json.loads(Path("facts.json").read_text())
    if "m5_bundle_sha" not in f:
        pytest.skip("M5 facts not yet committed")
    assert Path("docs/m5/REPORT.md").read_text() == render_m5(f)


def test_dtd_report_writes_the_m5_report_when_its_facts_exist(tmp_path, monkeypatch):
    from pipeline import cli
    f = json.loads(Path("facts.json").read_text()) | {"m5_bundle_sha": "ab", "m5_bundle_bytes": 1}
    (tmp_path / "facts.json").write_text(json.dumps(f))
    monkeypatch.setattr(cli, "FACTS", tmp_path / "facts.json")
    for name in ("REPORT", "REPORT_M0", "REPORT_M2", "REPORT_M3", "REPORT_M4", "REPORT_M5"):
        monkeypatch.setattr(cli, name, tmp_path / name / "REPORT.md")
    assert cli.entry(["report"]) == 0
    assert (tmp_path / "REPORT_M5" / "REPORT.md").read_text() == render_m5(f)


def test_only_the_model_judged_fact_says_machine_built_and_costs_name_dollars():
    """Tier labels follow where the judgement comes from: the API-vs-CLI state agreement is model against model;
    parity, tokens, money, times and the cap trip are plain measurements."""
    text = render_m5(Every())
    for heading in ("The same path the evals measured", "Cost and budget", "Server", "The cap trips"):
        sec = text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
        assert "machine-built" not in sec, heading
    sec = text.split("## API calibration\n", 1)[1].split("\n## ", 1)[0]
    assert [line for line in sec.splitlines() if "machine-built" in line] == [
        "| Answer state matches the other run (machine-built) | 0.5 | — |"]
    assert "US$0.5 on average" in text and "daily ceiling of US$0.5" in text
    assert "a share of" in text and "(n 0.5)" in text


def test_samples_left_out_of_the_timings_are_named():
    f = Every(m5_server_errors=4, m5_server_fresh_served_from_cache=1, m5_server_cached_answered_live=2)
    text = render_m5(f)
    assert "served other than meant, during the measurement: 4." in text
    assert "new questions the cache served: 1;" in text and "cached examples answered live, and billed: 2." in text


def test_each_label_covers_exactly_the_facts_it_names(tmp_path):
    """Render every fact as its own name. A line or section marked machine-built holds only machine-built facts,
    every machine-built fact sits on one, and every human-labelled fact sits on a line, or under a table header,
    marked human-labelled (MAUD). Plain measurements carry no label."""
    from facts.labels import HUMAN, MACHINE, tier_label
    from facts.m5 import build_m5
    from tests.test_facts_m5 import every_input
    keys = set(build_m5(*every_input(tmp_path))) | {"m4_r6n_report_recall_at_5", "m4_r6n_report_recall_at_5_lo",
                                                    "m4_r6n_report_recall_at_5_hi"}
    text = render_m5({k: f"<{k}>" for k in keys})
    seen = set()
    for section in re.split(r"\n(?=## )", text):
        whole, header, in_table = "(machine-built)" in section.splitlines()[0], "", False
        for line in section.splitlines():
            row = line.startswith("|")
            header = line if row and not in_table else header
            in_table = row
            machine = whole or "machine-built" in line
            human = HUMAN in line or (row and HUMAN in header)
            for key in re.findall(r"\(n <(m\d_\w+)>\)", line):  # a sample size: plain, whatever it counts
                seen.add(key)
                assert tier_label(key) is None, (key, line)
            line = re.sub(r"\(n <m\d_\w+>\)", "", line)
            for key in re.findall(r"<(m\d_\w+)>", line):
                seen.add(key)
                want = tier_label(key)
                assert machine == (want == MACHINE), (key, want, line)
                assert human == (want == HUMAN), (key, want, line)
    assert {"m5_calibration_state_agreement", "m5_calibration_accuracy_api", "m5_bundle_r6n_report_recall_at_5",
            "m5_api_tokens_in_mean", "m5_server_rss_mb", "m5_cap_trip_budget_reached", "m5_calibration_thuman_n",
            "m5_calibration_called", "m5_server_embed_parity_same"} <= seen


def test_the_report_says_the_model_answers_with_extended_thinking():
    sentence = ("The live model answers with extended thinking, as the evaluation runs did, "
                "with up to {} tokens of thinking per answer; the evaluation runs used the command-line tool's own "
                "thinking default.")
    assert sentence.format("<m5_thinking_budget_tokens>") in render_m5({"m5_thinking_budget_tokens": "<m5_thinking_budget_tokens>"})
    assert sentence.format("pending") in render_m5({})


def _named(*keys) -> dict:
    return {k: f"<{k}>" for k in keys}


def test_the_accuracy_row_and_the_intro_show_their_counts():
    text = render_m5(_named("m5_calibration_thuman_n", "m5_calibration_called", "m5_calibration_n",
                            "m5_calibration_accuracy_api", "m5_calibration_accuracy_cli"))
    row = next(line for line in text.splitlines() if line.startswith("| MAUD answer accuracy"))
    assert "(n <m5_calibration_thuman_n>)" in row and "human-labelled (MAUD)" in row
    assert row.endswith("| <m5_calibration_accuracy_api> | <m5_calibration_accuracy_cli> |")
    assert "<m5_calibration_n> tune-split questions (<m5_calibration_called> model calls) were answered" in text
    assert ("with the live model settings; retrieval ran over the evaluation indexes, which the parity section "
            "above shows serve the same passages") in text
    assert "with the live settings" not in text


def test_the_server_parity_sentence_counts_the_matches():
    text = render_m5(_named("m5_server_embed_parity_same", "m5_server_embed_parity_n", "m5_server_embed_parity"))
    assert ("The server's searches returned the same top passages as the development machine's for "
            "<m5_server_embed_parity_same> of <m5_server_embed_parity_n> questions (a share of "
            "<m5_server_embed_parity>); query embeddings are computed on each machine.") in text


def test_output_tokens_say_they_include_thinking():
    text = render_m5(Every())
    rows = [line for line in text.splitlines() if "Output tokens per answer" in line]
    assert rows and all("Output tokens per answer (including thinking)" in r for r in rows)


def test_report_booleans_read_yes_or_no():
    f = Every(m5_calibration_estimator_ok=True, m5_cap_trip_budget_reached=True, m5_cap_trip_budget_cached=False,
              m5_cap_trip_ledger_unchanged=True)
    text = render_m5(f)
    assert "True" not in text and "False" not in text
    assert "covered every calibrated call: yes." in text and 'a new question got "budget reached": yes;' in text
    assert 'showing a cached answer": no;' in text and "the month's spend did not move: yes." in text


def test_the_report_points_to_the_committed_kill_test_log():
    """The live kill test's log is committed verbatim from the run; it holds ledger sums, row counts, HTTP codes and
    a clock time, never a key, an address or the host."""
    text = render_m5({})
    assert text.count("`docs/m5/kill-test.log`") == 1
    line = next(s for s in text.splitlines() if "docs/m5/kill-test.log" in s)
    assert "kill test" in line
    log = Path("docs/m5/kill-test.log").read_text()
    assert "== before" in log and "== after stale window + restart" in log
    assert "sk-ant" not in log and "@" not in log and "forn.al" not in log and "ANTHROPIC" not in log
    assert not re.search(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", log)  # no IPv4 address
