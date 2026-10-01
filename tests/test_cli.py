import json

import pytest

from pipeline import cli

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"
DOC = (
    "Section 1.1 Closing. The closing shall occur at the offices of counsel on the Closing Date.\n\n"
    "Section 2.6 Type of Consideration. Each Company Share shall be converted into the right to receive cash.\n"
)


@pytest.fixture
def data(tmp_path, monkeypatch):
    raw = tmp_path / "raw" / "maud"
    (raw / "contracts").mkdir(parents=True)
    for i in range(3):
        (raw / "contracts" / f"contract_{i}.txt").write_text(DOC, encoding="utf-8")
    body = "".join(
        f'main,contract_{i},"{DOC.split(chr(10) * 2)[1].strip()} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,{i},General Information\n'
        for i in range(3))
    (raw / "MAUD_dev.csv").write_text(HEADER + body, encoding="utf-8")
    monkeypatch.setattr(cli, "RAW", raw)
    monkeypatch.setattr(cli, "INDEX", tmp_path / "index" / "maud.db")
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "FACTS", tmp_path / "facts.json")
    monkeypatch.setattr(cli, "REPORT", tmp_path / "docs" / "REPORT.md")
    monkeypatch.setattr(cli, "CSV_NAMES", ("MAUD_dev.csv",))
    from tests.fakes import FakeEmbedder, FakeReranker
    monkeypatch.setattr(cli, "INDEX_FIXED", tmp_path / "index" / "maud_fixed.db")
    monkeypatch.setattr(cli, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cli, "SETTINGS_PATH", tmp_path / "settings.json")
    monkeypatch.setattr(cli, "LEXICON_PATH", tmp_path / "lexicon.json")
    monkeypatch.setattr(cli, "_models", lambda: (FakeEmbedder(), lambda name: FakeReranker()))
    return tmp_path


def test_build_eval_facts_report_chain(data, capsys):
    assert cli.entry(["build"]) == 0
    assert cli.entry(["eval"]) == 0
    assert cli.entry(["facts"]) == 0
    assert cli.entry(["facts", "--check"]) == 0
    assert cli.entry(["report"]) == 0
    facts = json.loads((data / "facts.json").read_text())
    assert facts["maud_contracts"] == 3 and facts["eval_items_scored"] == 3
    assert str(facts["maud_contracts"]) in (data / "docs" / "REPORT.md").read_text()


def test_facts_check_fails_when_facts_are_stale(data):
    cli.entry(["build"]); cli.entry(["eval"]); cli.entry(["facts"])
    stale = json.loads((data / "facts.json").read_text())
    stale["maud_contracts"] = 0
    (data / "facts.json").write_text(json.dumps(stale))
    assert cli.entry(["facts", "--check"]) == 1


def test_build_without_fetched_contracts_fails_clearly(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(cli, "RAW", tmp_path / "nothing")
    monkeypatch.setattr(cli, "INDEX", tmp_path / "maud.db")
    assert cli.entry(["build"]) == 2
    assert "dtd fetch" in capsys.readouterr().err


def test_facts_include_the_label_recount_and_per_category_results(data):
    cli.entry(["build"]); cli.entry(["eval"])
    assert cli.entry(["facts"]) == 0
    facts = json.loads((data / "facts.json").read_text())
    assert facts["maud_label_rows_all"] == 3 and facts["maud_label_contracts"] == 3
    assert facts["r1_cat_general_items"] == 3


def test_facts_without_label_csvs_fails_clearly(data, capsys):
    cli.entry(["build"]); cli.entry(["eval"])
    for p in (data / "raw" / "maud").glob("*.csv"):
        p.unlink()
    assert cli.entry(["facts"]) == 2
    assert "label CSVs" in capsys.readouterr().err


def test_embed_then_every_ladder_rung_evaluates(data):
    assert cli.entry(["build"]) == 0
    assert cli.entry(["embed"]) == 0
    for rung in ("R1", "R2", "R3", "R4"):
        assert cli.entry(["eval", "--rung", rung]) == 0
        result = json.loads((data / "out" / f"{rung.lower()}.json").read_text())
        assert result["rung"] == rung and result["context_tokens"]["mean"] > 0


def test_eval_of_a_dense_rung_before_embed_fails_clearly(data, capsys):
    cli.entry(["build"])
    assert cli.entry(["eval", "--rung", "R2"]) == 2
    assert "dtd embed" in capsys.readouterr().err


def test_embed_twice_embeds_nothing_the_second_time(data, capsys):
    cli.entry(["build"])
    cli.entry(["embed"])
    capsys.readouterr()
    assert cli.entry(["embed"]) == 0
    assert json.loads(capsys.readouterr().out)["embedded"] == 0


def test_r1_through_the_ladder_matches_the_direct_m1_path(data):
    from evals.run_r1 import run as run_r1
    assert cli.entry(["build"]) == 0
    assert cli.entry(["eval", "--rung", "R1"]) == 0
    direct = run_r1(cli.INDEX, cli._csv_paths(), cli.RAW / "contracts", data / "direct")
    via = json.loads((data / "out" / "r1.json").read_text())
    assert via["overall"] == direct["overall"]

    def rows(d):
        path = next(d.glob("*_items.jsonl"))
        drop = {"latency_ms", "context_tokens", "load", "extra"}
        return [{k: v for k, v in json.loads(line).items() if k not in drop}
                for line in path.read_text().splitlines()]
    assert rows(data / "out") == rows(data / "direct") and rows(data / "out")


def test_embed_before_build_fails_clearly(data, capsys):
    assert cli.entry(["embed"]) == 2
    assert "dtd build" in capsys.readouterr().err


def test_unknown_rung_fails(data):
    cli.entry(["build"])
    assert cli.entry(["eval", "--rung", "R9"]) == 2
