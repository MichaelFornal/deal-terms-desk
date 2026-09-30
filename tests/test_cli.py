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
