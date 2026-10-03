import sqlite3

import pytest

from retrieval.bm25 import fts_query, search
from retrieval.index import build_index

DOC_A = (
    "Section 1.1 Closing. The closing shall occur at the offices of counsel.\n\n"
    "Section 2.2 Options. Each Company Option shall vest in full at the Effective Time.\n\n"
    "Section 3.1 Fees. The Company shall pay the Termination Fee to Parent.\n"
)
DOC_B = "Section 1.1 Options. Each option shall be cancelled for no consideration.\n"


@pytest.fixture
def conn(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, {"contract_a": DOC_A, "contract_b": DOC_B})
    return sqlite3.connect(db)


def test_best_hit_is_the_matching_section(conn):
    hits = search(conn, "do options vest", contract_id="contract_a", k=3)
    assert DOC_A[hits[0].start:hits[0].end].startswith("Section 2.2 Options.")
    assert all(h.contract_id == "contract_a" for h in hits)
    assert [h.score for h in hits] == sorted((h.score for h in hits), reverse=True)


def test_without_a_contract_filter_all_contracts_are_searched(conn):
    assert {h.contract_id for h in search(conn, "option", k=10)} == {"contract_a", "contract_b"}


def test_k_limits_the_result_count(conn):
    assert len(search(conn, "the shall", k=2)) == 2


def test_fts_query_quotes_tokens_and_drops_punctuation():
    assert fts_query('what\'s the "fee"?') == '"what" OR "the" OR "fee"'
    assert fts_query("AND OR") == '"and" OR "or"'


@pytest.mark.parametrize("q", ["", "   ", "?!\"'()*:^", "AND OR NOT NEAR", 'what\'s the "fee"?', "a"])
def test_hostile_queries_never_raise(conn, q):
    assert isinstance(search(conn, q, contract_id="contract_a"), list)


def test_empty_query_returns_no_hits(conn):
    assert search(conn, "?!") == []


def test_equal_scores_are_ordered_by_passage_id(tmp_path):
    twin = "Section 4.{} Indemnity. The Buyer shall indemnify the Seller for all losses.\n\n"
    db = tmp_path / "twins.db"
    build_index(db, {"c": "".join(twin.format(i) for i in range(1, 30))})
    hits = search(sqlite3.connect(db), "buyer indemnify seller losses", contract_id="c", k=5)
    assert len({round(h.score, 9) for h in hits}) == 1
    assert [h.passage_id for h in hits] == [1, 2, 3, 4, 5]


def test_contract_filter_runs_inside_fts_with_identical_results(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    from retrieval.bm25 import search
    docs = {f"c{i}": f"Section 1.1 Fees. The Company shall pay a termination fee of {i} dollars.\n\n"
                      f"Section 1.2 Closing. The closing shall occur on the closing date.\n" for i in range(5)}
    db = tmp_path / "i.db"
    build_index(db, docs)
    conn = sqlite3.connect(db)
    for cid in docs:
        old = conn.execute(
            "SELECT p.passage_id, -bm25(passages_fts) FROM passages_fts JOIN passages p ON p.passage_id = passages_fts.rowid"
            " WHERE passages_fts MATCH ? AND p.contract_id = ? ORDER BY bm25(passages_fts), p.passage_id LIMIT 10",
            ('"termination" OR "fee"', cid)).fetchall()
        new = [(h.passage_id, h.score) for h in search(conn, "termination fee", contract_id=cid)]
        assert new == old and new


def test_contract_filter_is_safe_for_operator_like_ids(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    from retrieval.bm25 import search
    db = tmp_path / "i.db"
    build_index(db, {'AND "x" OR': "Section 1.1 Fees. A termination fee applies.\n"})
    conn = sqlite3.connect(db)
    assert len(search(conn, "fee", contract_id='AND "x" OR')) == 1
    assert search(conn, "fee", contract_id="unknown") == []
