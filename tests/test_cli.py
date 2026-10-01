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


def _add_tune_contract(data):
    # contract_3 falls in the tune split and defines a term, so the vocabulary is non-empty
    (data / "raw" / "maud" / "contracts" / "contract_3.txt").write_text(
        DOC + "\nSection 1.2 Terms. \u201cType of Consideration\u201d means cash.\n", encoding="utf-8")


def test_lexicon_command_writes_the_lexicon_and_r5_then_runs(data, monkeypatch):
    from tests.fakes import fake_claude
    _add_tune_contract(data)
    runner = fake_claude('{"cash deal": ["Type of Consideration"]}')
    monkeypatch.setattr(cli, "run_claude", runner)
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["lexicon"]) == 0
    assert len(runner.calls) == 1
    doc = json.loads((data / "lexicon.json").read_text())
    assert doc["_meta"]["built_by"] == "machine"
    assert doc["entries"] == {"cash deal": ["Type of Consideration"]}
    assert cli.entry(["eval", "--rung", "R5"]) == 0


def test_lexicon_command_exits_2_when_the_runner_fails(data, monkeypatch, capsys):
    _add_tune_contract(data)

    def boom(prompt, model):
        raise RuntimeError("claude exited 1: nope")
    monkeypatch.setattr(cli, "run_claude", boom)
    cli.entry(["build"])
    capsys.readouterr()
    assert cli.entry(["lexicon"]) == 2
    assert "claude exited 1" in capsys.readouterr().err
    assert not (data / "lexicon.json").exists()


@pytest.mark.parametrize("rung", ["R5", "R6"])
def test_eval_r5_r6_without_a_lexicon_exit_2(data, capsys, rung):
    cli.entry(["build"]); cli.entry(["embed"])
    capsys.readouterr()
    assert cli.entry(["eval", "--rung", rung]) == 2
    assert "run `dtd lexicon` first" in capsys.readouterr().err


def test_r5_llm_runs_after_rewrite(data, monkeypatch):
    from tests.fakes import fake_claude
    monkeypatch.setattr(cli, "run_claude", fake_claude("Type of Consideration cash"))
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["eval", "--rung", "R5-llm"]) == 2
    assert cli.entry(["rewrite"]) == 0
    assert cli.entry(["eval", "--rung", "R5-llm"]) == 0
    result = json.loads((data / "out" / "r5_llm.json").read_text())
    assert result["extra"]["input_tokens_mean"] == 100 and result["latency_ms"]["p50"] >= 50


def test_rewrite_command_exits_2_when_the_runner_fails(data, monkeypatch, capsys):
    def boom(prompt, model):
        raise RuntimeError("claude exited 1: nope")
    monkeypatch.setattr(cli, "run_claude", boom)
    cli.entry(["build"])
    capsys.readouterr()
    assert cli.entry(["rewrite"]) == 2
    assert "claude exited 1" in capsys.readouterr().err


def test_fixed_index_is_evaluated_on_the_same_items(data):
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["build", "--fixed"]) == 0
    assert cli.entry(["embed", "--fixed"]) == 0
    assert cli.entry(["eval", "--rung", "R3"]) == 0
    assert cli.entry(["eval", "--rung", "R3-fixed"]) == 0
    a = [json.loads(l)["item_id"] for l in (data / "out" / "r3_items.jsonl").read_text().splitlines()]
    b = [json.loads(l)["item_id"] for l in (data / "out" / "r3_fixed_items.jsonl").read_text().splitlines()]
    assert a == b


def test_fixed_build_needs_the_section_index_first(data, capsys):
    assert cli.entry(["build", "--fixed"]) == 2
    assert "dtd build" in capsys.readouterr().err


def test_failures_with_a_bad_passage_id_exits_2(data, capsys):
    assert cli.entry(["build"]) == 0
    cli.OUT.mkdir(parents=True, exist_ok=True)
    row = {"item_id": "x|1", "contract_id": "contract_0", "category": "C", "split": "report",
           "gold": [[0, 5]], "top_passage_ids": [10**9]}
    (cli.OUT / "r1_items.jsonl").write_text(json.dumps(row) + "\n")
    assert cli.entry(["failures"]) == 2
    assert "x|1" in capsys.readouterr().err


def test_disputes_without_rung_results_exits_2(data, capsys):
    cli.entry(["build"])
    capsys.readouterr()
    assert cli.entry(["disputes"]) == 2
    assert "dtd eval" in capsys.readouterr().err


def test_disputes_command_writes_a_machine_built_estimate(data, monkeypatch):
    from tests.fakes import fake_claude
    runner = fake_claude('{"answers": true, "quote": "closing shall occur"}')
    monkeypatch.setattr(cli, "run_claude", runner)
    monkeypatch.setattr(cli, "sample_misses", lambda rows: [sorted(rows.values(), key=lambda r: r["item_id"])[0]])
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["eval", "--rung", "R3"]) == 0
    assert cli.entry(["disputes"]) == 0
    doc = json.loads((data / "out" / "disputes.json").read_text())
    assert doc["rung"] == "R3" and doc["machine_built"] is True
    assert doc["sample"] == 1 and len(runner.calls) == 1 and doc["share"]["n_items"] == 1


def test_disputes_with_missing_items_file_exits_2(data, capsys):
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["eval", "--rung", "R3"]) == 0
    (data / "out" / "r3_items.jsonl").unlink()
    capsys.readouterr()
    assert cli.entry(["disputes"]) == 2
    assert "r3_items.jsonl" in capsys.readouterr().err


def test_disputes_command_exits_2_when_the_runner_fails(data, monkeypatch, capsys):
    def boom(prompt, model):
        raise RuntimeError("claude exited 1: nope")
    monkeypatch.setattr(cli, "run_claude", boom)
    # force a non-empty sample so the runner is reached
    monkeypatch.setattr(cli, "sample_misses", lambda rows: [
        {"item_id": "x", "contract_id": "contract_0", "category": "c", "query": "q", "gold": [[0, 5]],
         "top_passage_ids": [1], "split": "report", "mrr@10": 0.0}])
    cli.entry(["build"]); cli.entry(["embed"]); cli.entry(["eval", "--rung", "R3"])
    capsys.readouterr()
    assert cli.entry(["disputes"]) == 2
    assert "claude exited 1" in capsys.readouterr().err


def test_corpus_wide_runs_r1_and_the_best_rung(data):
    cli.entry(["build"]); cli.entry(["embed"])
    for rung in ("R1", "R2"):
        cli.entry(["eval", "--rung", rung])
    assert cli.entry(["eval", "--rung", "corpus"]) == 0
    r1 = json.loads((data / "out" / "r1_corpus.json").read_text())
    best = json.loads((data / "out" / "best_corpus.json").read_text())
    assert r1["scope"] == "corpus-wide" and "char_recall@64" in r1["overall"]
    assert best["extra"]["rung"] in ("R1", "R2")
