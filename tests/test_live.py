import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from answer.prompt import TEMPLATE_SHA
from evals.live_parity import r7n_parity
from pipeline.bundle import maud_url
from retrieval.ladder import Ladder, Settings
from retrieval.live import build_live_ladder, bundle_meta, links_for, open_bundle
from retrieval.scope import Resolver
from retrieval.vectors import connect
from tests.fakes import FakeEmbedder
from tests.test_bundle import LEXICON, bundle, src  # noqa: F401

SETTINGS = Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3)
QUESTIONS = [("What is the Acme Software outside date?", None), ("termination fee", "edgar_0001"),
             ("Acme Software outside date", "contract_1"), ("outside date", None), ("closing date", "contract_1")]


def source_ladder(src):
    conn = connect(src["db"])
    return Ladder(conn, src["texts"], FakeEmbedder(), None, LEXICON, SETTINGS,
                  amendment_texts=src["amendment_texts"], resolver=Resolver(conn))


def test_r7n_over_the_bundle_equals_r7n_over_the_source(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    live, ref = build_live_ladder(out, FakeEmbedder(), LEXICON, SETTINGS), source_ladder(src)
    for q, cid in QUESTIONS:
        a, b = live.run("R7n", q, cid, 5), ref.run("R7n", q, cid, 5)
        assert [h.passage_id for h in a.hits] == [h.passage_id for h in b.hits]
        assert a.context == b.context and a.scope == b.scope and a.amended == b.amended
    assert r7n_parity(QUESTIONS, live, ref, k=5) == {"checked": 5, "same": 5, "differ": []}


def test_the_bundle_is_read_only_and_reading_it_writes_no_files(src, tmp_path):
    out = tmp_path / "live" / "live.db"
    bundle(src, out)
    before = sorted(p.name for p in out.parent.iterdir())
    ladder = build_live_ladder(out, FakeEmbedder(), LEXICON, SETTINGS)
    assert ladder.reranker is None
    assert ladder.run("R7n", "What is the Acme Software outside date?", None, 5).hits
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        ladder.conn.execute("CREATE TABLE x(a)")
    assert sorted(p.name for p in out.parent.iterdir()) == before


def test_open_bundle_works_from_another_thread_and_a_path_with_spaces(src, tmp_path):
    out = tmp_path / "a dir" / "live.db"
    bundle(src, out)
    conn = open_bundle(out)
    with ThreadPoolExecutor(1) as ex:
        n = ex.submit(lambda: conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]).result()
    assert n > 0


def test_meta_and_links(src, tmp_path):
    out = tmp_path / "live.db"
    bundle(src, out)
    conn = open_bundle(out)
    assert bundle_meta(conn)["template_sha"] == TEMPLATE_SHA
    assert links_for(conn, "edgar_0001") == {"filing": "https://example.test/a",
                                             "amendments": {2: "https://example.test/b"}}
    assert links_for(conn, "contract_1") == {"filing": maud_url("contract_1"), "amendments": {}}
    assert links_for(conn, "nope") == {"filing": None, "amendments": {}}


def test_open_bundle_without_a_file_names_the_command(tmp_path):
    with pytest.raises(FileNotFoundError, match="dtd bundle"):
        open_bundle(tmp_path / "missing.db")
