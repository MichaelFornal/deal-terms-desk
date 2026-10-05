import pytest

from retrieval.index import build_index
from retrieval.ladder import RUNGS, Ladder, Settings
from retrieval.rerank_cache import CachedReranker
from retrieval.scope import Resolver, Scope
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from tests.fakes import FakeEmbedder, FakeReranker

DOCS = {
    "big": (
        "ARTICLE I\nDEFINITIONS\n\n"
        "Section 1.1 Definitions. “Company Termination Fee” means an amount in cash equal to $50,000,000.\n\n"
        "Section 1.2 Closing. The closing shall occur at the offices of counsel.\n\n"
        "Section 8.3 Fees. The Company shall pay Parent the Company Termination Fee if this Agreement is terminated.\n\n"
        "Section 8.4 Expenses. Each party shall bear its own expenses.\n"
    ),
    "tiny": "Section 1.1 Fees. Parent shall pay a fee.\n",
}


@pytest.fixture
def ladder(tmp_path):
    db = tmp_path / "maud.db"
    build_index(db, DOCS)
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    rr = CachedReranker(FakeReranker(ms=7.0), tmp_path / "rerank.db")
    lexicon = {"walk-away payment": ["Termination Fee"]}
    return Ladder(conn, DOCS, emb, rr, lexicon, Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3))


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
def test_every_rung_stays_inside_the_contract(ladder, rung):
    got = ladder.run(rung, "termination fee", "big", k=10)
    assert got.hits and all(h.contract_id == "big" for h in got.hits)
    assert len(got.context) == min(5, len(got.hits))
    assert got.ms >= 0


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
@pytest.mark.parametrize("query", ["", "   ", "?!", '"'])
def test_queries_without_words_return_empty_lists(ladder, rung, query):
    assert ladder.run(rung, query, "big", k=10).hits == []


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
@pytest.mark.parametrize("query", ["AND OR NOT", 'what\'s the "fee"?', "NEAR(fee closing)", "fee*"])
def test_fts_operators_in_queries_are_inert(ladder, rung, query):
    got = ladder.run(rung, query, "big", k=10)
    assert isinstance(got.hits, list) and all(h.contract_id == "big" for h in got.hits)


@pytest.mark.parametrize("rung", ["R1", "R2", "R3", "R4"])
def test_a_contract_smaller_than_the_depth_returns_what_it_has(ladder, rung):
    assert len(ladder.run(rung, "fee", "tiny", k=10).hits) == 1


def test_r4_orders_the_head_by_reranker_score(ladder):
    got = ladder.run("R4", "Company Termination Fee terminated", "big", k=10)
    scores = [h.score for h in got.hits[:3]]
    assert scores == sorted(scores, reverse=True)


def test_r4_latency_uses_recorded_compute_time_on_a_cache_hit(ladder):
    first = ladder.run("R4", "termination fee", "big", k=10)
    again = ladder.run("R4", "termination fee", "big", k=10)
    assert ladder.reranker.inner.calls == 1
    assert again.ms >= 7.0 and abs(again.ms - first.ms) < 50


def test_unknown_rung_is_refused(ladder):
    with pytest.raises(ValueError, match="unknown rung"):
        ladder.run("R9", "fee", "big")


def test_rungs_are_the_spec_ladder():
    assert RUNGS == ("R1", "R2", "R3", "R4", "R5", "R6")


def test_r5_finds_the_clause_through_the_lexicon(ladder):
    plain = ladder.run("R1", "walk-away payment", "big", k=3)
    assert not any("Termination Fee" in DOCS["big"][h.start:h.end] for h in plain.hits)
    got = ladder.run("R5", "walk-away payment", "big", k=3)
    assert any("Termination Fee" in DOCS["big"][h.start:h.end] for h in got.hits)


def test_r5_without_a_lexicon_is_refused(ladder):
    ladder.lexicon = None
    with pytest.raises(ValueError, match="dtd lexicon"):
        ladder.run("R5", "fee", "big")


def test_r6_shows_definitions_and_matches_through_them(ladder):
    got = ladder.run("R6", "amount in cash", "big", k=5)
    fee = [c for c in got.context if c.startswith("Section 8.3")]
    assert fee and "amount in cash equal to $50,000,000" in fee[0]
    r5 = ladder.run("R5", "amount in cash", "big", k=5)
    assert all(not c.startswith("Section 8.3") or "$50,000,000" not in c for c in r5.context)


@pytest.fixture
def deals_ladder(tmp_path):
    from retrieval.deals import add_deals
    from tests.test_amendments import AMEND
    from tests.test_deals import deals_inputs
    db = tmp_path / "deals.db"
    deals, texts, _ = deals_inputs(tmp_path)
    build_index(db, texts)
    add_deals(db, deals, texts, {"edgar_0002": AMEND})
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    rr = CachedReranker(FakeReranker(ms=7.0), tmp_path / "rerank.db")
    return Ladder(conn, texts, emb, rr, {"walk-away payment": ["Termination Fee"]},
                  Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3),
                  amendment_texts={"edgar_0002": AMEND}, resolver=Resolver(conn))


def test_superseded_hit_carries_the_amending_text(deals_ladder):
    got = deals_ladder.run("R1", "Outside Date June 30", "edgar_0001", k=5)
    assert got.amended == ("edgar_0002",)
    shown = next(c for c in got.context if "Outside Date" in c)
    assert "[Amended by Amendment No. 2, filed 2020-02-01]" in shown and "September 30" in shown


def test_maud_index_has_no_amendments(ladder):
    got = ladder.run("R1", "termination fee", None, k=5)
    assert got.amended == ()


def test_r7_scopes_to_the_named_deal_and_falls_back_corpus_wide(deals_ladder):
    got = deals_ladder.run("R7", "Acme Software outside date", k=5)
    assert got.hits and all(h.contract_id == "edgar_0001" for h in got.hits)
    assert got.scope.contract_id == "edgar_0001"
    q = "outside date"
    free = deals_ladder.run("R7", q, k=5)
    base = deals_ladder.run("R6", q, None, k=5)
    assert [h.passage_id for h in free.hits] == [h.passage_id for h in base.hits]
    assert free.scope == Scope(None, None, ())


def test_r7_needs_a_resolver(ladder):
    with pytest.raises(ValueError):
        ladder.run("R7", "termination fee")


def _spy_r6(ladder, rung="R6"):
    seen, real = [], ladder.run

    def run(rung_, query, contract_id=None, k=10, rewritten=None):
        if rung_ == rung:
            seen.append((query, contract_id))
        return real(rung_, query, contract_id, k, rewritten)
    ladder.run = run
    return seen


def test_r7_drops_the_company_name_once_it_has_found_the_deal(deals_ladder):
    seen = _spy_r6(deals_ladder)
    got = deals_ladder.run("R7", "What is the Acme Software outside date?", k=5)
    assert seen == [("What is the outside date", "edgar_0001")]
    assert got.scope.contract_id == "edgar_0001"
    seen.clear()
    deals_ladder.run("R7", "outside date for Zeta Labs", k=5)  # no deal found: the question is unchanged
    assert seen == [("outside date for Zeta Labs", None)]
    seen.clear()
    deals_ladder.run("R7", "Acme Software", k=5)  # nothing left once the name is gone: the original
    assert seen == [("Acme Software", "edgar_0001")]


def test_r7_keeps_the_question_when_the_deal_is_ambiguous(deals_ladder):
    from retrieval.scope import Scope as S

    class Ambiguous:
        def resolve(self, q):
            return S(None, "acme software", ("edgar_0001", "edgar_0009"))
    deals_ladder.resolver = Ambiguous()
    seen = _spy_r6(deals_ladder)
    deals_ladder.run("R7", "Acme Software outside date", k=5)
    assert seen == [("Acme Software outside date", None)]


def test_r7_latency_includes_the_resolver(deals_ladder):
    import time
    real = deals_ladder.resolver

    class Slow:
        def resolve(self, q):
            time.sleep(0.05)
            return real.resolve(q)
    deals_ladder.resolver = Slow()
    assert deals_ladder.run("R7", "Acme Software outside date", k=5).ms >= 50.0


from retrieval.ladder import ANSWER_RUNGS, load_answer_path


def test_r6n_is_r6_without_the_reranker(ladder):
    got = ladder.run("R6n", "termination fee amount in cash", "big", k=5)
    want = ladder.run("R3", "termination fee amount in cash", "big", k=5)
    # same fusion as R3 but on the lexicon-rewritten query over the definitions table; never reranked
    assert got.hits and all(h.contract_id == "big" for h in got.hits)
    assert any("$50,000,000" in c for c in got.context)  # definitions are shown, as in R6
    assert ANSWER_RUNGS == ("R6n", "R7n")
    assert want.hits  # R3 still runs


def test_r6n_never_calls_the_reranker(ladder):
    class Boom:
        def score(self, q, texts):
            raise AssertionError("reranker called")
    ladder.reranker = Boom()
    assert ladder.run("R6n", "termination fee", "big", k=5).hits


def test_r7n_scopes_strips_and_skips_the_reranker(deals_ladder):
    class Boom:
        def score(self, q, texts):
            raise AssertionError("reranker called")
    deals_ladder.reranker = Boom()
    got = deals_ladder.run("R7n", "What is the Acme Software outside date?", k=5)
    assert got.scope.contract_id == "edgar_0001" and all(h.contract_id == "edgar_0001" for h in got.hits)
    same = deals_ladder.run("R6n", "What is the outside date", "edgar_0001", k=5)
    assert [h.passage_id for h in got.hits] == [h.passage_id for h in same.hits]


def test_answer_path_is_r7n():
    assert load_answer_path() == "R7n"


def test_r7n_keeps_a_picked_deal_and_drops_only_its_own_names(deals_ladder):
    seen = _spy_r6(deals_ladder, "R6n")
    got = deals_ladder.run("R7n", "Acme Software outside date", "contract_1", k=5)
    assert got.scope == Scope("contract_1", None, ())
    assert got.hits and all(h.contract_id == "contract_1" for h in got.hits)
    assert seen == [("Acme Software outside date", "contract_1")]
    seen.clear()
    deals_ladder.run("R7n", "What is the Acme Software outside date?", "edgar_0001", k=5)
    assert seen == [("What is the outside date", "edgar_0001")]
