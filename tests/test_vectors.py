import pytest

from retrieval.dense import search_dense
from retrieval.index import build_index
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder

DOCS = {
    "a": "Section 1.1 Fees. The Company shall pay the Termination Fee to Parent.\n\n"
         "Section 1.2 Options. Each Company Option shall vest at the Effective Time.\n",
    "b": "Section 1.1 Fees. Parent shall pay a Reverse Termination Fee to the Company.\n",
}


@pytest.fixture
def index(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, DOCS)
    return db, tmp_path / "cache" / "emb.db"


def test_fill_cache_embeds_each_distinct_text_once_and_resumes(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    texts = [t for _, _, t in indexed_passages(conn)]
    first = fill_cache(cache, emb, texts[:2], batch=1)
    assert first == {"embedded": 2, "cached": 0}
    second = fill_cache(open_cache(cache_path), emb, texts + texts, batch=1)
    assert second == {"embedded": len(set(texts)) - 2, "cached": 2}
    assert emb.embedded == len(set(texts))


def test_build_vectors_refuses_a_partial_cache(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    texts = [t for _, _, t in indexed_passages(conn)]
    fill_cache(cache, emb, texts[:1])
    with pytest.raises(ValueError, match="dtd embed"):
        build_vectors(conn, cache, emb.name)
    assert conn.execute("SELECT COUNT(*) FROM sqlite_master WHERE name = 'passages_vec'").fetchone()[0] == 0


def test_build_vectors_counts_truncated_passages(index):
    db, cache_path = index
    conn, cache = connect(db), open_cache(cache_path)

    class Long(FakeEmbedder):
        def count_tokens(self, text):
            return 600 if "Reverse" in text else 10
    emb = Long()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    out = build_vectors(conn, cache, emb.name)
    assert out == {"vectors": 3, "truncated": 1}


def test_dense_search_filters_by_contract_inside_the_knn(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    hits = search_dense(conn, emb.embed_query("termination fee"), contract_id="a", k=10)
    assert [h.contract_id for h in hits] == ["a", "a"]
    assert "Termination Fee" in DOCS["a"][hits[0].start:hits[0].end]
    assert hits[0].score >= hits[1].score
    everywhere = search_dense(conn, emb.embed_query("termination fee"), k=10)
    assert {h.contract_id for h in everywhere} == {"a", "b"}


def test_dense_search_returns_fewer_hits_than_k_for_a_small_contract(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    assert len(search_dense(conn, emb.embed_query("fee"), contract_id="b", k=50)) == 1


def _built(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    return conn, cache, emb


def _state(conn):
    return (conn.execute("SELECT COUNT(*) FROM passages_vec").fetchone()[0],
            conn.execute("SELECT model, vectors, truncated FROM vec_meta").fetchall())


def test_refusal_after_a_good_build_keeps_the_old_table_and_meta(index):
    conn, cache, emb = _built(index)
    before = _state(conn)
    assert before == (3, [(emb.name, 3, 0)])
    cache.execute("DELETE FROM emb WHERE sha1 = (SELECT sha1 FROM emb LIMIT 1)")
    cache.commit()
    with pytest.raises(ValueError, match="dtd embed"):
        build_vectors(conn, cache, emb.name)
    assert _state(conn) == before


def test_failure_mid_insert_rolls_back_to_the_previous_table_and_meta(index):
    conn, cache, emb = _built(index)
    before = _state(conn)
    cache.execute("UPDATE emb SET vec = x'00'")
    cache.commit()
    with pytest.raises(Exception):
        build_vectors(conn, cache, emb.name)
    assert not conn.in_transaction
    assert _state(conn) == before
    assert search_dense(conn, emb.embed_query("termination fee"), contract_id="a", k=10)


def test_fill_cache_killed_mid_run_keeps_committed_batches_and_resumes(index):
    db, cache_path = index
    conn = connect(db)
    texts = [t for _, _, t in indexed_passages(conn)]

    class Dies(FakeEmbedder):
        def embed_passages(self, batch):
            if self.embedded >= 1:
                raise RuntimeError("killed")
            return super().embed_passages(batch)
    with pytest.raises(RuntimeError):
        fill_cache(open_cache(cache_path), Dies(), texts, batch=1)
    emb = FakeEmbedder()
    out = fill_cache(open_cache(cache_path), emb, texts, batch=1)
    assert out == {"embedded": len(set(texts)) - 1, "cached": 1}
    assert emb.embedded == len(set(texts)) - 1


def test_vec_table_declares_a_chunk_size(index):
    db, cache_path = index
    conn, cache, emb = connect(db), open_cache(cache_path), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name = 'passages_vec'").fetchone()[0]
    assert "chunk_size=128" in ddl.replace(" ", "")
