import inspect
import json
import sqlite3

from evals.bootstrap import split_of
from pipeline.build_lexicon import build, parse, prompt, vocabulary
from retrieval.index import build_index
from tests.fakes import fake_claude

TUNE = [c for c in (f"contract_{i}" for i in range(60)) if split_of(c) == "tune"][:2]
REPORT = [c for c in (f"contract_{i}" for i in range(60)) if split_of(c) == "report"][:1]


def docs():
    d = {c: f"Section 1.1 Fees. “Company Termination Fee” means $1. “Tune Only {i}” means x.\n"
         for i, c in enumerate(TUNE)}
    d[REPORT[0]] = "Section 1.1 Fees. “Report Secret Term” means y.\n"
    return d


def test_vocabulary_comes_from_tune_split_agreements_only(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, docs())
    vocab = vocabulary(sqlite3.connect(db))
    assert vocab[0] == "Company Termination Fee"
    assert "Report Secret Term" not in vocab


def test_prompt_sees_only_the_vocabulary():
    assert list(inspect.signature(prompt).parameters) == ["vocab"]
    assert "Company Termination Fee" in prompt(["Company Termination Fee"])


def test_parse_keeps_only_grounded_expansions_and_tolerates_prose():
    text = 'Here you go:\n{"break-up fee": ["Company Termination Fee", "Invented Phrase"], "x": ["Fee"], "bad": 3}\nDone.'
    assert parse(text, ["The Company Termination Fee is due."]) == {"break-up fee": ["Company Termination Fee"]}


def test_build_writes_a_machine_labelled_lexicon(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, docs())
    runner = fake_claude('{"break-up fee": ["Company Termination Fee"]}')
    out = tmp_path / "lexicon.json"
    doc = build(sqlite3.connect(db), list(docs()[c] for c in TUNE), out, runner=runner, model="m")
    assert json.loads(out.read_text()) == doc
    assert doc["_meta"]["built_by"] == "machine" and doc["_meta"]["saw_eval_queries"] is False
    assert doc["entries"] == {"break-up fee": ["Company Termination Fee"]}
    assert len(runner.calls) == 1 and "Report Secret Term" not in runner.calls[0][0]
