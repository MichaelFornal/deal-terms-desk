import json

import pytest
from pathlib import Path

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
    monkeypatch.setattr(cli, "DATA", tmp_path / "data")
    monkeypatch.setattr(cli, "REPORT_M0", tmp_path / "docs" / "m0" / "REPORT.md")
    monkeypatch.setattr(cli, "REPORT_M2", tmp_path / "docs" / "m2" / "REPORT.md")
    monkeypatch.setattr(cli, "REPORT_M3", tmp_path / "docs" / "m3" / "REPORT.md")
    from tests.fakes import FakeEmbedder, FakeReranker
    monkeypatch.setattr(cli, "INDEX_FIXED", tmp_path / "index" / "maud_fixed.db")
    monkeypatch.setattr(cli, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(cli, "EDGAR", tmp_path / "raw" / "edgar")
    monkeypatch.setattr(cli, "DEALS_INDEX", tmp_path / "index" / "deals.db")
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


def test_the_cli_chain_does_not_touch_the_real_m0_report_or_data(data):
    root = Path(__file__).resolve().parent.parent
    real, real_m3 = root / "docs" / "m0" / "REPORT.md", root / "docs" / "m3" / "REPORT.md"
    before = real.stat().st_mtime_ns if real.exists() else None
    before_m3 = real_m3.stat().st_mtime_ns if real_m3.exists() else None
    for cmd in (["build"], ["eval"], ["facts"], ["report"]):
        assert cli.entry(cmd) == 0
    assert (real.stat().st_mtime_ns if real.exists() else None) == before
    assert (real_m3.stat().st_mtime_ns if real_m3.exists() else None) == before_m3
    facts = json.loads((data / "facts.json").read_text())
    assert not [k for k in facts if k.startswith("m0_") or k.startswith("m3_")]
    assert not (data / "docs" / "m3").exists()
    assert not (data / "docs" / "m0").exists()


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


def test_r5_llm_append_appends_the_cached_rewrite_and_makes_no_call(data, monkeypatch):
    from tests.fakes import fake_claude
    monkeypatch.setattr(cli, "run_claude", fake_claude("Type of Consideration cash"))
    cli.entry(["build"]); cli.entry(["embed"])
    assert cli.entry(["rewrite"]) == 0
    monkeypatch.setattr(cli, "run_claude", lambda *a, **k: pytest.fail("no model call allowed"))
    seen = []
    real_run = cli.Ladder.run
    monkeypatch.setattr(cli.Ladder, "run", lambda self, rung, q, c=None, k=10, rewritten=None:
                        seen.append((q, rewritten)) or real_run(self, rung, q, c, k, rewritten))
    assert cli.entry(["eval", "--rung", "R5-llm-append"]) == 0
    assert seen and all(r.startswith(q + " ") and len(r) > len(q) + 1 for q, r in seen)
    assert (data / "out" / "r5_llm_append.json").exists()
    assert (data / "out" / "r5_llm_append_items.jsonl").exists()


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


def _m2_chain(data, monkeypatch):
    from pathlib import Path

    from evals.bootstrap import split_of
    from tests.fakes import fake_claude
    raw = data / "raw" / "maud"
    part = DOC.split(chr(10) * 2)[1].strip()
    extra = ""
    for i, cid in enumerate([c for c in (f"contract_t{i}" for i in range(40)) if split_of(c) == "tune"][:2]):
        (raw / "contracts" / f"{cid}.txt").write_text(DOC, encoding="utf-8")
        extra += (f'main,{cid},"{part} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,'
                  f'Type of Consideration,{50 + i},General Information\n')
    with open(raw / "MAUD_dev.csv", "a", encoding="utf-8") as fh:
        fh.write(extra)
    monkeypatch.setattr(cli, "run_claude", fake_claude('{"answers": true, "quote": "Closing"}'))
    monkeypatch.setattr(cli, "EXTERNAL", Path("facts/external.json").resolve())
    monkeypatch.setattr(cli, "REPORT_M2", data / "docs" / "m2" / "REPORT.md")
    steps = [["build"], ["embed"], ["lexicon"], ["tune"]]
    steps += [["eval", "--rung", r] for r in ("R1", "R2", "R3", "R4", "R5", "R6")]
    steps += [["rewrite"], ["eval", "--rung", "R5-llm"], ["build", "--fixed"], ["embed", "--fixed"],
              ["eval", "--rung", "R3-fixed"], ["eval", "--rung", "corpus"], ["failures"], ["disputes"],
              ["facts"], ["facts", "--check"], ["report"]]
    for step in steps:
        assert cli.entry(step) == 0, step
    return json.loads((data / "facts.json").read_text())


def test_full_m2_chain_produces_facts_and_both_reports(data, monkeypatch):
    facts = _m2_chain(data, monkeypatch)
    assert facts["m2_r1_report_recall_at_5"] == facts["r1_report_recall_at_5"]
    assert "machine-built" in (data / "docs" / "m2" / "REPORT.md").read_text()


def test_latency_tokens_and_gold_spans_are_on_the_report_split(data, monkeypatch):
    from evals.run_rung import _percentile
    facts = _m2_chain(data, monkeypatch)
    for rung in ("r1", "r4", "r5_llm"):
        rows = [json.loads(l) for l in (data / "out" / f"{rung}_items.jsonl").read_text().splitlines()]
        report = [r for r in rows if r["split"] == "report"]
        assert report and len(report) < len(rows)
        lat = sorted(r["latency_ms"] for r in report)
        assert facts[f"m2_{rung}_latency_ms_p50"] == round(_percentile(lat, 0.50), 2)
        assert facts[f"m2_{rung}_latency_ms_p95"] == round(_percentile(lat, 0.95), 2)
        tokens = [r["context_tokens"] for r in report]
        assert facts[f"m2_{rung}_context_tokens_mean"] == round(sum(tokens) / len(tokens), 1)
        if rung == "r1":
            assert facts["m2_report_gold_spans"] == sum(len(r["gold"]) for r in report)


def test_r5_llm_model_comes_from_the_rewrite_records(data, monkeypatch):
    from evals.llm_rewrite import REWRITE_MODEL
    facts = _m2_chain(data, monkeypatch)
    assert facts["m2_llm_rewrite_model"] == REWRITE_MODEL
    with pytest.raises(ValueError, match="model"):
        cli._rewrite_model({"a": {"model": "x"}, "b": {"model": "y"}})
    assert cli._rewrite_model({"a": {"model": "x"}, "b": {"model": "x"}}) == "x"


def test_facts_with_an_unreadable_index_table_exits_2(data, monkeypatch, capsys):
    import sqlite3

    def boom(*a, **kw):
        raise sqlite3.OperationalError("no such table: chunking")
    cli.entry(["build"]); cli.entry(["eval"])
    monkeypatch.setattr(cli, "m2_present", lambda out: True)
    monkeypatch.setattr(cli, "build_m2", boom)
    capsys.readouterr()
    assert cli.entry(["facts"]) == 2
    err = capsys.readouterr().err
    assert "no such table: chunking" in err and "dtd build --fixed" in err


def test_atomic_write_keeps_the_old_file_when_the_write_fails(tmp_path, monkeypatch):
    from pathlib import Path
    target = tmp_path / "x.json"
    target.write_text("old", encoding="utf-8")
    real = Path.write_text

    def torn(self, text, **kw):
        real(self, text[:2], **kw)
        raise OSError("disk full")
    monkeypatch.setattr(Path, "write_text", torn)
    with pytest.raises(OSError):
        cli._write_atomic(target, "new content")
    monkeypatch.setattr(Path, "write_text", real)
    assert target.read_text(encoding="utf-8") == "old"
    cli._write_atomic(target, "new content")
    assert target.read_text(encoding="utf-8") == "new content"
    assert [p.name for p in tmp_path.iterdir()] == ["x.json"]


def test_disputes_and_failures_are_written_atomically(data, monkeypatch):
    from tests.fakes import fake_claude
    written = []
    real = cli._write_atomic
    monkeypatch.setattr(cli, "_write_atomic", lambda path, text: (written.append(path.name), real(path, text)))
    monkeypatch.setattr(cli, "run_claude", fake_claude('{"answers": true, "quote": "closing shall occur"}'))
    cli.entry(["build"]); cli.entry(["embed"]); cli.entry(["eval", "--rung", "R3"])
    assert cli.entry(["failures"]) == 0 and cli.entry(["disputes"]) == 0
    assert {"failures_r3.json", "disputes.json"} <= set(written)


def test_facts_with_partial_m2_results_name_what_is_missing(data, capsys):
    cli.entry(["build"]); cli.entry(["embed"]); cli.entry(["eval"]); cli.entry(["eval", "--rung", "R2"])
    assert cli.entry(["facts"]) == 2
    assert "r3.json" in capsys.readouterr().err


def test_facts_with_rungs_scored_on_different_items_fail_clearly(data, capsys, monkeypatch):
    from pathlib import Path

    from evals.bootstrap import split_of
    from tests.fakes import fake_claude
    raw = data / "raw" / "maud"
    part = DOC.split(chr(10) * 2)[1].strip()
    extra = ""
    for i, cid in enumerate([c for c in (f"contract_t{i}" for i in range(40)) if split_of(c) == "tune"][:2]):
        (raw / "contracts" / f"{cid}.txt").write_text(DOC, encoding="utf-8")
        extra += (f'main,{cid},"{part} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,'
                  f'Type of Consideration,{50 + i},General Information\n')
    with open(raw / "MAUD_dev.csv", "a", encoding="utf-8") as fh:
        fh.write(extra)
    monkeypatch.setattr(cli, "run_claude", fake_claude('{"answers": true, "quote": "Closing"}'))
    monkeypatch.setattr(cli, "EXTERNAL", Path("facts/external.json").resolve())
    cli.entry(["build"]); cli.entry(["embed"]); cli.entry(["lexicon"]); cli.entry(["tune"])
    for r in ("R1", "R2", "R3", "R4", "R5", "R6"):
        cli.entry(["eval", "--rung", r])
    cli.entry(["rewrite"]); cli.entry(["eval", "--rung", "R5-llm"]); cli.entry(["build", "--fixed"])
    cli.entry(["embed", "--fixed"]); cli.entry(["eval", "--rung", "R3-fixed"]); cli.entry(["eval", "--rung", "corpus"])
    cli.entry(["failures"]); cli.entry(["disputes"])
    path = data / "out" / "r3_items.jsonl"
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[1:]) + "\n")
    capsys.readouterr()
    assert cli.entry(["facts"]) == 2
    assert "different items" in capsys.readouterr().err


def test_m0_without_a_contact_refuses_before_any_request(data, monkeypatch, capsys):
    monkeypatch.delenv("SEC_CONTACT", raising=False)
    monkeypatch.chdir(data)
    assert cli.entry(["m0", "search"]) == 2
    assert "SEC_CONTACT" in capsys.readouterr().err


def test_m0_stops_with_exit_3_when_blocked(data, monkeypatch, capsys):
    from pipeline.sec_client import Blocked
    monkeypatch.setenv("SEC_CONTACT", "tester@example.com")
    monkeypatch.setattr(cli, "DATA", data)

    def blocked(client, out, today=None):
        raise Blocked("sec.gov answered 403; stopped, no retry")
    monkeypatch.setattr(cli.m0, "stage_search", blocked)
    assert cli.entry(["m0", "search"]) == 3
    assert "403" in capsys.readouterr().err


class _FakeSec:
    made = []

    def __init__(self, root, contact):
        self.root, self.contact, self.closed = root, contact, False
        _FakeSec.made.append(self)

    def close(self):
        self.closed = True


def _m0_fakes(monkeypatch, tmp_path, blocked_at=None):
    from pipeline.sec_client import Blocked
    _FakeSec.made = []
    ran = []
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(cli, "SecClient", _FakeSec)
    monkeypatch.setattr(cli, "sec_contact", lambda: "tester@example.com")
    for stage in cli.M0_STAGES:
        def fn(*args, _stage=stage, **kw):
            ran.append((_stage, args, kw))
            if _stage == blocked_at:
                raise Blocked("sec.gov answered 403; stopped, no retry")
            return {}
        monkeypatch.setattr(cli.m0, f"stage_{stage}", fn)
    return ran


def test_m0_all_runs_every_stage_in_order_with_one_client(tmp_path, monkeypatch):
    ran = _m0_fakes(monkeypatch, tmp_path)
    assert cli.entry(["m0", "all"]) == 0
    assert [s for s, _, _ in ran] == ["search", "candidates", "fetch", "deals", "sample", "press", "measure"]
    assert len(_FakeSec.made) == 1 and _FakeSec.made[0].closed
    client = _FakeSec.made[0]
    for stage, args, _ in ran:
        assert (args[0] is client) == (stage not in ("sample", "measure"))


@pytest.mark.parametrize("stage", ["search", "fetch", "press"])
def test_m0_all_stops_at_the_first_block_and_closes_the_client(tmp_path, monkeypatch, capsys, stage):
    ran = _m0_fakes(monkeypatch, tmp_path, blocked_at=stage)
    assert cli.entry(["m0", "all"]) == 3
    order = list(cli.M0_STAGES)
    assert [s for s, _, _ in ran] == order[:order.index(stage) + 1]
    assert len(_FakeSec.made) == 1 and _FakeSec.made[0].closed
    assert "403" in capsys.readouterr().err


def test_m0_closes_the_client_on_any_error(tmp_path, monkeypatch):
    _m0_fakes(monkeypatch, tmp_path)

    def boom(*a, **kw):
        raise KeyError("x")
    monkeypatch.setattr(cli.m0, "stage_candidates", boom)
    with pytest.raises(KeyError):
        cli.entry(["m0", "all"])
    assert len(_FakeSec.made) == 1 and _FakeSec.made[0].closed


@pytest.mark.parametrize("stage", ["sample", "measure"])
def test_m0_sample_and_measure_never_open_a_client(tmp_path, monkeypatch, stage):
    ran = _m0_fakes(monkeypatch, tmp_path)
    assert cli.entry(["m0", stage]) == 0
    assert _FakeSec.made == [] and [s for s, _, _ in ran] == [stage]


def test_m0_search_reuses_the_recorded_end_date(tmp_path, monkeypatch):
    from datetime import date
    ran = _m0_fakes(monkeypatch, tmp_path)
    assert cli.entry(["m0", "search"]) == 0
    assert ran[-1][2].get("today") is None
    (tmp_path / "m0").mkdir()
    (tmp_path / "m0" / "search_meta.json").write_text(json.dumps({"end": "2026-09-30"}))
    assert cli.entry(["m0", "search"]) == 0
    assert ran[-1][2]["today"] == date(2026, 9, 30)


def test_m0_facts_read_the_sec_logs(tmp_path, monkeypatch):
    seen = {}

    def fake_build(m0_dir, facts=None, sec_dir=None):
        seen["sec_dir"] = sec_dir
        return {}
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(cli, "build_facts", lambda *a: {})
    monkeypatch.setattr(cli, "OUT", tmp_path / "out")
    monkeypatch.setattr(cli, "m2_present", lambda out: False)
    monkeypatch.setattr(cli, "present_m3", lambda out: False)
    monkeypatch.setattr(cli, "build_m0", fake_build)
    (tmp_path / "m0").mkdir()
    (tmp_path / "m0" / "measure.json").write_text("{}")
    cli._all_facts()
    assert seen["sec_dir"] == tmp_path / "sec"


def test_m0_candidate_sample_makes_no_sec_client(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "DATA", tmp_path)
    monkeypatch.setattr(cli, "SecClient", lambda *a, **k: pytest.fail("SecClient constructed"))
    monkeypatch.setattr(cli.m0, "stage_candidates_sample", lambda out: calls.append(out) or {"sample": 0})
    assert cli.entry(["m0", "candidate-sample"]) == 0
    assert calls == [tmp_path / "m0"]


def test_m3_corpus_writes_the_summary_under_the_patched_edgar(data, capsys):
    from tests.test_tech_corpus import make_m0
    make_m0(data / "data")  # builds <DATA>/m0
    assert cli.entry(["m3", "corpus"]) == 0
    summary = json.loads((data / "raw" / "edgar" / "summary.json").read_text())
    assert summary["kept"] == 2 and json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == summary


def test_eval_out_writes_elsewhere_and_leaves_the_default_untouched(data, tmp_path):
    assert cli.entry(["build"]) == 0
    other = tmp_path / "parity"
    assert cli.entry(["eval", "--rung", "R1", "--out", str(other)]) == 0
    assert (other / "r1.json").exists()
    assert not (cli.OUT / "r1.json").exists()


def test_build_deals_writes_index_and_summary(data, capsys):
    from tests.test_tech_corpus import make_m0
    make_m0(data / "data")
    assert cli.entry(["m3", "corpus"]) == 0
    assert cli.entry(["build", "--deals"]) == 0
    summary = json.loads((data / "data" / "m3" / "deals_summary.json").read_text())
    assert (data / "index" / "deals.db").exists()
    assert summary["deals"] >= 2 and summary["maud_deals"] == 3
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == summary


def test_build_deals_without_corpus_names_the_command(data, capsys):
    assert cli.entry(["build", "--deals"]) == 2
    assert "dtd m3 corpus" in capsys.readouterr().err


def _fake_label_runner(calls):
    def runner(prompt, model):
        calls.append(model)
        if prompt.startswith("Below is the outline"):
            reply = {"equity_awards": [], "termination_fee": [], "employee_benefits": []}
        else:
            reply = {}
        return {"result": json.dumps(reply), "usage": {"input_tokens": 1, "output_tokens": 1}}
    return runner


def test_m3_label_writes_rows_and_summary_and_resumes_from_the_ledger(data, capsys, monkeypatch):
    from tests.test_tech_corpus import make_m0
    make_m0(data / "data")
    assert cli.entry(["m3", "corpus"]) == 0
    assert cli.entry(["build", "--deals"]) == 0
    calls = []
    monkeypatch.setattr(cli, "run_claude", _fake_label_runner(calls))
    assert cli.entry(["m3", "label", "--workers", "2"]) == 0
    out = data / "data" / "m3"
    rows = [json.loads(line) for line in (out / "tmachine.jsonl").read_text().splitlines()]
    summary = json.loads((out / "tmachine_summary.json").read_text())
    assert calls and rows and summary["complete"] == summary["contracts"] and summary["absent"] == len(rows)
    assert (out / "tmachine_ledger.jsonl").exists()
    assert json.loads(capsys.readouterr().out.strip().splitlines()[-1]) == summary

    def boom(prompt, model):
        raise AssertionError("model called on a fully cached run")
    monkeypatch.setattr(cli, "run_claude", boom)
    assert cli.entry(["m3", "label"]) == 0


def test_m3_label_runner_error_exits_2_and_missing_inputs_name_the_step(data, capsys, monkeypatch):
    assert cli.entry(["m3", "label"]) == 2
    assert "dtd build --deals" in capsys.readouterr().err
    from tests.test_tech_corpus import make_m0
    make_m0(data / "data")
    assert cli.entry(["m3", "corpus"]) == 0
    assert cli.entry(["build", "--deals"]) == 0

    def fail(prompt, model):
        raise RuntimeError("claude down")
    monkeypatch.setattr(cli, "run_claude", fail)
    assert cli.entry(["m3", "label"]) == 2
    assert "claude down" in capsys.readouterr().err


def _kept_runner(prompt, model):
    quote = "The parties agree. The parties agree."
    if prompt.startswith("Below is the outline"):
        reply = {t: ["C1"] for t in ("equity_awards", "termination_fee", "employee_benefits")}
    else:
        reply = {t: {"found": True, "quotes": [quote], "answer": "yes"}
                 for t in ("equity_awards", "termination_fee", "employee_benefits")}
    return {"result": json.dumps(reply), "usage": {"input_tokens": 1, "output_tokens": 1}}


def _m3_setup(data, monkeypatch):
    from tests.fakes import fake_claude
    from tests.test_tech_corpus import make_m0
    make_m0(data / "data")
    _add_tune_contract(data)
    assert cli.entry(["m3", "corpus"]) == 0
    assert cli.entry(["build"]) == 0
    assert cli.entry(["build", "--deals"]) == 0
    return fake_claude


def test_m3_chain_embed_lexicon_label_eval_writes_every_result(data, monkeypatch):
    fake_claude = _m3_setup(data, monkeypatch)
    assert cli.entry(["embed", "--deals"]) == 0
    monkeypatch.setattr(cli, "run_claude", fake_claude('{"cash deal": ["Type of Consideration"]}'))
    assert cli.entry(["embed"]) == 0
    assert cli.entry(["lexicon"]) == 0
    monkeypatch.setattr(cli, "run_claude", _kept_runner)
    assert cli.entry(["m3", "label"]) == 0
    assert cli.entry(["m3", "eval"]) == 0
    out = data / "out" / "m3"
    for name in ([f"t_r{i}.json" for i in range(1, 7)] + [f"t_bare_r{i}.json" for i in range(1, 7)]
                 + ["t_r6_corpus.json", "t_r7_corpus.json", "r7_scope.json"]):
        assert (out / name).exists(), name
    assert json.loads((out / "t_r7_corpus.json").read_text())["scope"] == "corpus-wide"
    assert json.loads((out / "r7_scope.json").read_text())["items"]
    bare = json.loads((out / "t_bare_r1_items.jsonl").read_text().splitlines()[0])
    named = json.loads((out / "t_r1_items.jsonl").read_text().splitlines()[0])
    assert bare["item_id"] == named["item_id"] and bare["query"] != named["query"]


def test_m3_eval_before_embed_deals_exits_2_and_names_it(data, capsys):
    from tests.test_tech_corpus import make_m0
    make_m0(data / "data")
    assert cli.entry(["m3", "corpus"]) == 0
    assert cli.entry(["build", "--deals"]) == 0
    assert cli.entry(["m3", "eval"]) == 2
    assert "dtd embed --deals" in capsys.readouterr().err


def _tier_runner(prompt, model):
    if prompt.startswith("Below is the outline"):
        reply = {"T1": ["C1"]}
    else:
        reply = {"T1": {"found": True, "quotes": ["Each Company Share shall be converted into the right to receive cash"], "answer": "x"}}
    return {"result": json.dumps(reply), "usage": {"input_tokens": 1, "output_tokens": 1}}


def test_m3_tier_writes_the_report_and_names_a_missing_rung(data, monkeypatch, capsys):
    _m2_chain(data, monkeypatch)
    monkeypatch.setattr(cli, "run_claude", _tier_runner)
    assert cli.entry(["m3", "tier", "--workers", "2"]) == 0
    rep = json.loads((data / "out" / "m3" / "tier.json").read_text())
    assert {"match", "tau", "rungs"} <= set(rep) and set(rep["rungs"]) == {f"R{i}" for i in range(1, 7)}
    assert rep["kept"] >= 1 and rep["match"]["mean"] == 1.0
    rows = [json.loads(x) for x in (data / "data" / "m3" / "tier_rows.jsonl").read_text().splitlines()]
    assert rows and (data / "data" / "m3" / "tier_ledger.jsonl").exists()
    assert not (data / "out" / "tier.json").exists()

    def boom(prompt, model):
        raise AssertionError("model called on a fully cached run")
    monkeypatch.setattr(cli, "run_claude", boom)
    assert cli.entry(["m3", "tier"]) == 0
    (data / "out" / "r6_items.jsonl").unlink()
    capsys.readouterr()
    assert cli.entry(["m3", "tier"]) == 2
    assert "dtd eval --rung R6" in capsys.readouterr().err


def test_m3_tier_with_kept_items_missing_from_a_rung_exits_2(data, monkeypatch, capsys):
    _m2_chain(data, monkeypatch)
    f = data / "out" / "r4_items.jsonl"
    f.write_text("".join(l + "\n" for l in f.read_text().splitlines()[:0]), encoding="utf-8")
    monkeypatch.setattr(cli, "run_claude", _tier_runner)
    capsys.readouterr()
    assert cli.entry(["m3", "tier"]) == 2
    err = capsys.readouterr().err
    assert "dtd eval --rung R4" in err and "dtd eval --rung R1" not in err
