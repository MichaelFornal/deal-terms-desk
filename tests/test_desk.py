import hashlib
import json
import sqlite3
import threading
import time
from dataclasses import asdict
from pathlib import Path

import pytest

from answer.api_runner import RunnerError
from answer.prompt import TEMPLATE_SHA
from pipeline.bundle import build_bundle
from retrieval.deals import add_deals
from retrieval.index import build_index
from retrieval.ladder import Settings
from retrieval.live import build_live_ladder
from retrieval.vectors import build_vectors, connect, fill_cache, indexed_passages, open_cache
from service.budget import STALE_S, Budget
from service.cache import AnswerCache
from service.config import Config
from service.desk import STATES, Desk
from service.limits import Buckets, Slots
from service.prices import cost_usd, load_prices, worst_case_usd
from tests.fakes import FakeEmbedder, fake_claude
from tests.test_deals import deals_inputs

PRICES = Path("service/prices.json")
LEXICON = {"walk-away payment": ["Termination Fee"]}
SETTINGS = Settings(depth=10, rrf_k0=60, reranker="fake-reranker", rerank_depth=3)
AMEND_QUOTE = "The Termination Fee shall be $40,000,000"
OUTSIDE_QUOTE = "The Outside Date is June 30 of the year"
NOT_STATED = json.dumps({"state": "not_stated", "claims": []})


def make_bundle(tmp_path: Path) -> Path:
    """The deals fixture (one MAUD and one tech agreement, one amendment) as a live bundle with fake vectors."""
    db = tmp_path / "deals.db"
    deals, texts, amends = deals_inputs(tmp_path)
    build_index(db, texts)
    add_deals(db, deals, texts, amends)
    conn, cache, emb = connect(db), open_cache(tmp_path / "emb.db"), FakeEmbedder()
    fill_cache(cache, emb, [t for _, _, t in indexed_passages(conn)])
    build_vectors(conn, cache, emb.name)
    conn.close()
    (tmp_path / "deals.jsonl").write_text("".join(json.dumps(d) + "\n" for d in deals), encoding="utf-8")
    (tmp_path / "settings.json").write_text(json.dumps({"settings": asdict(SETTINGS), "answer_path": "R7n"}),
                                            encoding="utf-8")
    (tmp_path / "lexicon.json").write_text(json.dumps({"entries": LEXICON}), encoding="utf-8")
    out = tmp_path / "live" / "live.db"
    out.parent.mkdir(parents=True, exist_ok=True)
    build_bundle(db, out, texts=texts, amendment_texts=amends, deals_jsonl=tmp_path / "deals.jsonl",
                 settings_path=tmp_path / "settings.json", lexicon_path=tmp_path / "lexicon.json")
    return out


def make_config(tmp_path: Path, bundle: Path, **kw) -> Config:
    facts = tmp_path / "facts.json"
    facts.write_text('{"m4_answer_model": "claude-haiku-4-5-20251001"}\n', encoding="utf-8")
    base = dict(bundle=bundle, state_dir=tmp_path / "state", prices_path=PRICES, facts_path=facts,
                model="claude-haiku-4-5-20251001", max_tokens=1024, month_cap_usd=5.0, day_cap_usd=1.0,
                question_max_chars=300, ask_per_hour=60, search_per_minute=60, fresh_per_hour=60, ask_slots=2,
                git_sha="abc123")
    base.update(kw)
    return Config(**base)


def make_desk(tmp_path: Path, runner, **kw) -> Desk:
    config = make_config(tmp_path, make_bundle(tmp_path), **kw)
    config.state_dir.mkdir(parents=True, exist_ok=True)
    budget = Budget(config.state_dir / "budget.db", config.month_cap_usd, config.day_cap_usd,
                    load_prices(config.prices_path))
    ladder = build_live_ladder(config.bundle, FakeEmbedder(), LEXICON, SETTINGS)
    return Desk(ladder, runner, config, budget, AnswerCache(config.state_dir / "cache.db"),
                Buckets(config.fresh_per_hour, 3600.0), Slots(config.ask_slots))


class Scripted:
    """A runner that replays results (or raises exceptions) in order and records every call."""

    def __init__(self, *results, input_tokens=1000, output_tokens=200):
        self.results, self.calls = list(results), []
        self.usage = {"input_tokens": input_tokens, "output_tokens": output_tokens,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}

    def __call__(self, prompt, model):
        self.calls.append((prompt, model))
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return {"result": r, "usage": dict(self.usage), "stop_reason": "end_turn"}


def reply(**obj) -> str:
    return json.dumps(obj)


def ref_of(desk, question, deal, pred) -> str:
    """The label a block gets in this fixture (hit order decides it, not the test)."""
    p = desk.answerer.prepare(question, deal)
    return next(b.ref for b in p.blocks if pred(b))


def amended(b) -> bool:
    return any(p.kind == "amendment" for p in b.parts)


def test_states_are_the_spec_states():
    assert set(STATES) == {"answered", "not_stated", "unfiled_schedule", "which_deal", "budget_cached",
                           "budget_reached", "busy", "error"}


def test_answered_carries_quote_section_agreement_and_filing_link(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    q = "What is the Acme Software outside date?"
    ref = ref_of(desk, q, None, lambda b: OUTSIDE_QUOTE in b.parts[0].text)
    run.results.append(reply(state="answered", claims=[{"text": "June 30.", "quote": OUTSIDE_QUOTE, "ref": ref}]))
    got = desk.ask(q)
    assert got["state"] == "answered" and got["served_from"] == "live" and len(run.calls) == 1
    assert got["deal"]["id"] == "edgar_0001" and got["deal"]["link"] == "https://example.test/a"
    c = got["claims"][0]
    assert c["quote"] == OUTSIDE_QUOTE and c["section_path"] and c["link"] == "https://example.test/a"
    assert "Acme Software" in c["agreement"] and c["amendment_no"] is None
    assert got["tokens"] == {"in": 1000, "out": 200} and got["ms"] >= 0


def test_amended_claim_carries_its_number_and_the_amendment_link(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    ref = ref_of(desk, "termination fee", "edgar_0001", amended)
    run.results.append(reply(state="answered", claims=[{"text": "Fee is $40m.", "quote": AMEND_QUOTE, "ref": ref}]))
    got = desk.ask("termination fee", "edgar_0001")
    assert got["state"] == "answered" and got["amended"] is True
    c = got["claims"][0]
    assert c["amendment_no"] == 2 and c["amendment_link"] == "https://example.test/b"


def test_not_stated_by_the_model_and_by_retrieval(tmp_path):
    run = Scripted(NOT_STATED)
    desk = make_desk(tmp_path, run)
    assert desk.ask("termination fee", "edgar_0001")["state"] == "not_stated"
    nothing = desk.ask("???", "edgar_0001")  # no word to search for: no passage, no model call
    assert nothing["state"] == "not_stated" and nothing["served_from"] is None and len(run.calls) == 1


def test_unfiled_schedule(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    p = desk.answerer.prepare("termination fee schedule", "edgar_0001")
    tagged = next(b for b in p.blocks if b.schedule_ref)
    quote = tagged.parts[0].text.split(".")[0]
    run.results.append(reply(state="unfiled_schedule", claims=[{"text": "In a schedule.", "quote": quote,
                                                                "ref": tagged.ref}]))
    assert desk.ask("termination fee schedule", "edgar_0001")["state"] == "unfiled_schedule"


def test_which_deal_makes_no_call(tmp_path):
    run = Scripted()
    got = make_desk(tmp_path, run).ask("What is the outside date for Zeta Labs?")
    assert got["state"] == "which_deal" and run.calls == [] and got["candidates"] == [] and got["deal"] is None


def test_unknown_deal_is_refused(tmp_path):
    desk = make_desk(tmp_path, Scripted())
    with pytest.raises(ValueError):
        desk.ask("termination fee", "edgar_9999")
    with pytest.raises(ValueError):
        desk.search("termination fee", "edgar_9999")


def test_a_repeated_question_is_served_from_the_cache(tmp_path):
    run = Scripted()
    desk = make_desk(tmp_path, run)
    ref = ref_of(desk, "termination fee", "edgar_0001", amended)
    run.results.append(reply(state="answered", claims=[{"text": "t", "quote": AMEND_QUOTE, "ref": ref}]))
    first = desk.ask("termination fee", "edgar_0001")
    again = desk.ask("  termination   fee ", "edgar_0001")
    assert again["served_from"] == "cache" and again["state"] == "answered" and len(run.calls) == 1
    assert again["claims"] == first["claims"] and again["tokens"] is None


def test_busy_when_no_slot_or_no_fresh_call_is_left(tmp_path):
    run = Scripted(NOT_STATED)
    assert make_desk(tmp_path / "a", run, ask_slots=0).ask("termination fee", "edgar_0001")["state"] == "busy"
    assert make_desk(tmp_path / "b", run, fresh_per_hour=0).ask("termination fee", "edgar_0001")["state"] == "busy"
    assert run.calls == []


def test_failures_are_errors_and_book_only_what_was_billed(tmp_path):
    prices = load_prices(PRICES)
    billed = {"input_tokens": 1000, "output_tokens": 0, "cache_creation_input_tokens": 0,
              "cache_read_input_tokens": 0}
    run = Scripted(RunnerError("overloaded", "overloaded"), RunnerError("truncated", "max_tokens", billed),
                   "not json at all")
    desk = make_desk(tmp_path, run)
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"
    assert desk.budget.spent()["month"] == 0.0  # rejected before any work: released, not billed
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"
    after_truncated = desk.budget.spent()["month"]
    assert after_truncated == pytest.approx(cost_usd(prices, billed))
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"  # unparseable: its usage is booked
    assert desk.budget.spent()["month"] > after_truncated and len(run.calls) == 3  # errors are never cached


def test_a_billing_refusal_reads_as_budget_reached(tmp_path):
    run = Scripted(RunnerError("billing", "credit balance too low"))
    assert make_desk(tmp_path, run).ask("termination fee", "edgar_0001")["state"] == "budget_reached"


@pytest.mark.parametrize("kind", ["timeout", "connection"])
def test_a_timeout_or_lost_connection_is_booked_at_worst_case(tmp_path, kind):
    desk = make_desk(tmp_path, Scripted(RunnerError(kind, "no reply")))
    assert desk.ask("termination fee", "edgar_0001")["state"] == "error"
    p = desk.answerer.prepare("termination fee", "edgar_0001")
    worst = worst_case_usd(load_prices(PRICES), len(p.prompt), desk.config.max_tokens)
    assert desk.budget.spent()["month"] == pytest.approx(worst, abs=1e-6)  # spent() rounds to 6 places
    rows = sqlite3.connect(desk.config.state_dir / "budget.db").execute("SELECT status FROM spend").fetchall()
    assert rows == [("settled",)]


def test_the_cap_trips(tmp_path):
    """PRD M5 exit. Once spend reaches the cap, a new question gets budget_reached, a cached one is still served
    as budget_cached, and the model is never called again."""
    run = Scripted(input_tokens=200_000, output_tokens=20_000)  # one call costs far more than the cap
    desk = make_desk(tmp_path, run, month_cap_usd=0.05, day_cap_usd=0.05)
    ref = ref_of(desk, "termination fee", "edgar_0001", amended)
    run.results.append(reply(state="answered", claims=[{"text": "t", "quote": AMEND_QUOTE, "ref": ref}]))
    assert desk.ask("termination fee", "edgar_0001")["state"] == "answered"
    assert desk.health()["budget"] == "reached"
    fresh = desk.ask("What is the Acme Software outside date?")
    cached = desk.ask("termination fee", "edgar_0001")
    assert fresh["state"] == "budget_reached" and fresh["served_from"] is None
    assert cached["state"] == "budget_cached" and cached["cached_state"] == "answered"
    assert cached["served_from"] == "cache" and cached["claims"]
    assert len(run.calls) == 1


def test_search_never_calls_the_model_even_with_the_budget_spent(tmp_path):
    run = Scripted()
    got = make_desk(tmp_path, run, month_cap_usd=0.0, day_cap_usd=0.0).search("What is the Acme Software outside date?")
    assert run.calls == [] and got["hits"] and got["scope"]["deal"] == "edgar_0001"
    h = got["hits"][0]
    assert {"passage_id", "deal", "section_path", "text", "definitions", "link", "score", "stages"} <= set(h)
    assert set(h["stages"]) == {"bm25", "dense"} and h["text"]


def test_concurrent_asks_never_spend_past_the_cap(tmp_path):
    """Every runner call is held open, so reservations pile up at worst case. Only as many calls as the cap covers
    may start; the rest must be refused before the model is called. Non-atomic reservation fails this."""
    gate, cond, state = threading.Event(), threading.Condition(), {"entered": 0, "done": 0}
    calls: list = []

    def runner(prompt, model):
        calls.append(prompt)
        with cond:
            state["entered"] += 1
            cond.notify_all()
        assert gate.wait(30)
        return {"result": NOT_STATED, "usage": {"input_tokens": 100, "output_tokens": 100}, "stop_reason": "end_turn"}

    q, n = "termination fee clause", 20
    desk = make_desk(tmp_path, runner, ask_slots=n)
    prices = load_prices(PRICES)
    worst = worst_case_usd(prices, len(desk.answerer.prepare(q, "edgar_0001").prompt), desk.config.max_tokens)
    cap = worst * 2.5
    desk.budget = Budget(tmp_path / "state" / "capped.db", cap, cap, prices)
    out: list[dict] = []

    def go():
        got = desk.ask(q, "edgar_0001")
        with cond:
            out.append(got)
            state["done"] += 1
            cond.notify_all()

    threads = [threading.Thread(target=go) for _ in range(n)]
    for t in threads:
        t.start()
    with cond:
        settled = cond.wait_for(lambda: state["entered"] + state["done"] >= n, timeout=30)
    try:
        assert settled, "threads neither entered the runner nor returned"
        assert len(calls) <= int(cap // worst) == 2
        assert any(o["state"] == "budget_reached" for o in out)
    finally:
        gate.set()
        for t in threads:
            t.join(30)
    assert len(out) == n and desk.budget.spent()["month"] <= cap


def test_a_crash_between_reserve_and_settle_is_booked_at_worst_case_once(tmp_path):
    """A process killed during the model call leaves an open reservation. It counts at worst case at once; a
    restart after the stale window books it at worst case, and only once."""
    desk = make_desk(tmp_path, Scripted(SystemExit("killed")))
    with pytest.raises(SystemExit):
        desk.ask("termination fee", "edgar_0001")
    p = desk.answerer.prepare("termination fee", "edgar_0001")
    prices = load_prices(PRICES)
    worst = worst_case_usd(prices, len(p.prompt), desk.config.max_tokens)
    db = desk.config.state_dir / "budget.db"
    assert Budget(db, 5.0, 1.0, prices).spent()["month"] == pytest.approx(worst, abs=1e-6)  # open: at worst
    for _ in range(2):  # restarts after the stale window: settled at worst once, never twice
        Budget(db, 5.0, 1.0, prices, clock=lambda: time.time() + STALE_S + 1)
        rows = sqlite3.connect(db).execute("SELECT status, usd FROM spend").fetchall()
        assert len(rows) == 1 and rows[0][0] == "settled" and rows[0][1] == pytest.approx(worst)


def test_health_reports_the_running_code_bundle_and_facts(tmp_path):
    desk = make_desk(tmp_path, Scripted())
    h = desk.health()
    assert h["ok"] is True and h["git_sha"] == "abc123" and h["model"] == "claude-haiku-4-5-20251001"
    assert h["bundle_sha"] == hashlib.sha256(desk.config.bundle.read_bytes()).hexdigest()
    assert h["facts_sha"] == hashlib.sha256(desk.config.facts_path.read_bytes()).hexdigest()
    assert h["template_sha"] == TEMPLATE_SHA and h["budget"] == "ok" and h["rss_mb"] > 0
    assert isinstance(h["bundle_meta"], dict) and "spent" not in h  # spend amounts are never public


def test_deals_lists_every_agreement_for_the_picker(tmp_path):
    rows = make_desk(tmp_path, Scripted()).deals()
    assert {r["id"] for r in rows} == {"contract_1", "edgar_0001"}
    assert all({"id", "target", "parent", "signed", "source", "link"} <= set(r) for r in rows)


def test_a_locked_ledger_reads_as_busy_and_never_calls_the_model(tmp_path):
    run = Scripted(NOT_STATED)
    desk = make_desk(tmp_path, run, ask_slots=1)

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    desk.budget.reserve = locked
    assert desk.ask("termination fee", "edgar_0001")["state"] == "busy"
    assert run.calls == [] and desk.slots.try_acquire() is True


def test_a_reply_with_no_usage_is_booked_at_worst_case(tmp_path):
    ok = reply(state="not_stated", claims=[])
    desk = make_desk(tmp_path, lambda prompt, model: {"result": ok, "usage": {}, "stop_reason": "end_turn"})
    assert desk.ask("termination fee", "edgar_0001")["state"] == "not_stated"
    p = desk.answerer.prepare("termination fee", "edgar_0001")
    worst = worst_case_usd(load_prices(PRICES), len(p.prompt), desk.config.max_tokens)
    assert desk.budget.spent()["month"] == pytest.approx(worst, abs=1e-6)


def test_a_locked_ledger_at_settle_leaves_the_reservation_open_and_still_answers(tmp_path):
    run = Scripted(NOT_STATED)
    desk = make_desk(tmp_path, run)

    def locked(*a, **k):
        raise sqlite3.OperationalError("database is locked")
    desk.budget.settle = locked
    got = desk.ask("termination fee", "edgar_0001")
    assert got["state"] == "not_stated" and got["served_from"] == "live"
    rows = sqlite3.connect(desk.config.state_dir / "budget.db").execute("SELECT status FROM spend").fetchall()
    assert rows == [("open",)]
    again = desk.ask("termination fee", "edgar_0001")
    assert again["served_from"] == "cache" and len(run.calls) == 1
