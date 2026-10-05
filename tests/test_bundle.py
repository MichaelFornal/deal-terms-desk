import json
import sqlite3

import pytest

from answer.prompt import TEMPLATE_SHA
from pipeline.bundle import MANIFEST, build_bundle, bundle_is_current, maud_url
from pipeline.normalise import load_contract
from retrieval.deals import add_deals
from retrieval.index import build_index
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder
from tests.test_amendments import AMEND
from tests.test_deals import deals_inputs

LEXICON = {"walk-away payment": ["Termination Fee"]}


@pytest.fixture
def src(tmp_path):
    deals, texts, amends = deals_inputs(tmp_path)
    db = tmp_path / "src" / "deals.db"
    build_index(db, texts)
    add_deals(db, deals, texts, amends)
    conn, cache, emb = connect(db), open_cache(tmp_path / "src" / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    conn.close()
    jsonl = tmp_path / "src" / "deals.jsonl"
    jsonl.write_text("".join(json.dumps(d) + "\n" for d in deals), encoding="utf-8")
    settings = tmp_path / "src" / "settings.json"
    settings.write_text(json.dumps({"settings": {"depth": 10, "rrf_k0": 60, "reranker": "fake-reranker",
                                                 "rerank_depth": 3}, "answer_path": "R7n"}))
    lexicon = tmp_path / "src" / "lexicon.json"
    lexicon.write_text(json.dumps({"entries": LEXICON}))
    return {"db": db, "texts": texts, "amendment_texts": amends, "deals_jsonl": jsonl, "settings": settings,
            "lexicon": lexicon}


def bundle(src, out):
    return build_bundle(src["db"], out, texts=src["texts"], amendment_texts=src["amendment_texts"],
                        deals_jsonl=src["deals_jsonl"], settings_path=src["settings"], lexicon_path=src["lexicon"])


def test_the_bundle_holds_the_index_texts_and_links_but_not_terms(src, tmp_path):
    out = tmp_path / "live" / "live.db"
    s = bundle(src, out)
    assert s["rebuilt"] and s["contracts"] == 2 and s["passages"] > 0 and bundle_is_current(out)
    conn = sqlite3.connect(out)
    names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
    assert "terms" not in names
    assert {"passages_fts", "passages_x_fts", "passages_vec", "deals", "aliases", "superseded", "texts",
            "amendment_texts", "links", "meta"} <= names
    assert dict(conn.execute("SELECT contract_id, text FROM texts")) == src["texts"]
    assert dict(conn.execute("SELECT amendment_id, text FROM amendment_texts")) == {"edgar_0002": AMEND}
    assert sorted(conn.execute("SELECT contract_id, kind, amendment_no, url FROM links")) == sorted([
        ("contract_1", "filing", None, maud_url("contract_1")),
        ("edgar_0001", "filing", None, "https://example.test/a"),
        ("edgar_0001", "amendment", 2, "https://example.test/b")])
    meta = dict(conn.execute("SELECT key, value FROM meta"))
    assert meta["template_sha"] == TEMPLATE_SHA and len(meta["deals_db_sha256"]) == 64
    assert json.loads(out.with_name(MANIFEST).read_text())["sha256"] == s["sha256"]


def test_maud_links_are_the_fetched_contract_urls():
    from pipeline.paths import MAUD_BASE
    assert maud_url("contract_7") == f"{MAUD_BASE}/contracts/contract_7.txt"  # as pipeline/fetch_maud.py fetches


def test_texts_round_trip_load_contract(src, tmp_path):
    d = tmp_path / "files"
    d.mkdir()
    for cid, text in src["texts"].items():
        (d / f"{cid}.txt").write_bytes(("﻿" + text.replace("\n", "\r\n")).encode("utf-8"))
    loaded = {p.stem: load_contract(p) for p in d.glob("*.txt")}
    assert loaded == src["texts"]  # the canonical form undoes the BOM and CRLF
    out = tmp_path / "live.db"
    bundle(dict(src, texts=loaded), out)
    assert dict(sqlite3.connect(out).execute("SELECT contract_id, text FROM texts")) == loaded


def test_a_rerun_with_the_same_inputs_rebuilds_nothing(src, tmp_path):
    out = tmp_path / "live.db"
    first = bundle(src, out)
    mtime = out.stat().st_mtime_ns
    assert bundle(src, out) == first | {"rebuilt": False}
    assert out.stat().st_mtime_ns == mtime


def test_a_changed_input_rebuilds(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    src["lexicon"].write_text(json.dumps({"entries": {"walk-away payment": ["Company Termination Fee"]}}))
    assert bundle(src, out)["rebuilt"] is True


def _no_bundle_files(d):
    return not any((d / n).exists() for n in ("live.db", "live.db.building", MANIFEST, MANIFEST + ".tmp"))


def test_a_kill_mid_build_leaves_no_bundle_and_keeps_an_old_one(src, tmp_path, monkeypatch):
    import pipeline.bundle as B
    out = tmp_path / "live.db"

    def die(*a, **k):  # the process dies after VACUUM INTO, before anything is renamed into place
        raise KeyboardInterrupt
    monkeypatch.setattr(B, "_fill", die)
    with pytest.raises(KeyboardInterrupt):
        bundle(src, out)
    assert _no_bundle_files(tmp_path)
    monkeypatch.undo()
    good = bundle(src, out)
    src["lexicon"].write_text(json.dumps({"entries": {}}))
    monkeypatch.setattr(B, "_fill", die)
    with pytest.raises(KeyboardInterrupt):
        bundle(src, out)
    assert bundle_is_current(out) and json.loads(out.with_name(MANIFEST).read_text())["sha256"] == good["sha256"]
    assert not out.with_name("live.db.building").exists()


def test_a_kill_between_the_two_renames_is_caught_and_rebuilt(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    man = out.with_name(MANIFEST)
    doc = json.loads(man.read_text())
    doc["sha256"] = "0" * 64  # the new db landed, the old manifest did not move
    man.write_text(json.dumps(doc))
    assert not bundle_is_current(out)
    assert bundle(src, out)["rebuilt"] is True and bundle_is_current(out)


def test_an_indexed_contract_without_text_is_refused(src, tmp_path):
    with pytest.raises(ValueError, match="no text"):
        bundle(dict(src, texts={"edgar_0001": src["texts"]["edgar_0001"]}), tmp_path / "live.db")
    assert _no_bundle_files(tmp_path)
