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
    stripped = re.sub(r"0\.5|R6n|R7n|M[0-9]|@5|\bp(?:50|95)\b|sha256", "", text)
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


def test_every_machine_section_is_labelled_and_costs_name_dollars():
    text = render_m5(Every())
    for heading in ("The same path the evals measured", "API calibration", "Cost and budget", "Server",
                    "The cap trips"):
        sec = text.split(f"## {heading}", 1)[1].split("\n## ", 1)[0]
        assert "machine-built" in sec, heading
    assert "US$0.5 on average" in text and "daily ceiling of US$0.5" in text
    assert "a share of" in text and "(n 0.5)" in text


def test_samples_left_out_of_the_timings_are_named():
    f = Every(m5_server_errors=4, m5_server_fresh_served_from_cache=1, m5_server_cached_answered_live=2)
    text = render_m5(f)
    assert "served other than meant, during the measurement: 4." in text
    assert "new questions the cache served: 1;" in text and "cached examples answered live, and billed: 2." in text
