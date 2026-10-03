import json

import pytest

from evals.tmachine import (CHUNK, MIN_SECTIONS, TEMPLATES, items_from_rows, label_all, label_contract, locate,
                            outline, status)
from pipeline.ledger import Ledger

TEXT = ("AGREEMENT AND PLAN OF MERGER\n\n"
        "Section 2.3 Treatment of Company Options. Each Company Option shall be cancelled and converted into the "
        "right to receive cash equal to the spread.\n\n"
        "Section 6.9 Employee Matters. For one year after the Closing, Parent shall provide each Continuing "
        "Employee base pay no less favorable than before.\n\n"
        "Section 8.3 Termination Fee. The Company shall pay Parent a fee of $25,000,000 (the “Termination Fee”).\n\n"
        "Section 9.1 Notices. Each Company Option holder shall be notified.\n")


def passages_of(text):
    out = []
    for sid, title in (("2.3", "Treatment of Company Options"), ("6.9", "Employee Matters"),
                       ("8.3", "Termination Fee"), ("9.1", "Notices")):
        s = text.index(f"Section {sid}")
        e = text.find("\n\nSection", s + 1)
        out.append((sid, title, s, len(text) if e < 0 else e))
    return out


def test_outline_lines_and_fallback():
    ol = outline(passages_of(TEXT), TEXT)
    assert ol.fallback  # only 4 sections, under MIN_SECTIONS
    big = [(f"{i}.1", f"Title {i}", i * 100, i * 100 + 90) for i in range(1, MIN_SECTIONS + 1)]
    ol2 = outline(big, "x" * 2000)
    assert not ol2.fallback and ol2.lines[0] == "1.1 Title 1" and ol2.sections["1.1"] == (100, 190)
    fb = outline([], "y" * (CHUNK * 2 + 5))
    assert fb.fallback and list(fb.sections) == ["C1", "C2", "C3"] and fb.sections["C3"] == (CHUNK * 2, CHUNK * 2 + 5)


def test_repeated_section_id_gets_a_suffix():
    rows = [(f"{i}.1", "T", i * 10, i * 10 + 5) for i in range(1, MIN_SECTIONS + 1)] + [("1.1", "Again", 500, 520)]
    assert "1.1#2" in outline(rows, "z" * 600).sections


def test_locate_only_inside_the_given_spans():
    s23 = TEXT.index("Section 2.3")
    s91 = TEXT.index("Section 9.1")
    quote = "Each Company Option"
    # the phrase occurs in 2.3 and 9.1; with only 9.1 given, it is found there and nowhere else
    got = locate(quote + " holder shall be notified", TEXT, [(s91, len(TEXT))])
    assert got and got[0][0] >= s91
    assert locate("Each Company Option shall be cancelled", TEXT, [(s91, len(TEXT))]) == []
    assert locate("Each Company Option shall be cancelled", TEXT, [(s23, s91)])[0][0] >= s23


def test_locate_folds_quotes_whitespace_and_ellipses():
    s83 = TEXT.index("Section 8.3")
    got = locate('a fee of $25,000,000   (the "Termination Fee")', TEXT, [(s83, len(TEXT))])
    assert len(got) == 1
    two = locate("For one year after the Closing ... base pay no less favorable than before", TEXT, [(0, len(TEXT))])
    assert len(two) == 2


class FakeRunner:
    """Step 1 picks sections by keyword; step 2 quotes from the sections shown."""

    SECTION_IDS = {"equity_awards": ["2.3"], "termination_fee": ["8.3"], "employee_benefits": ["6.9"]}

    def __init__(self, quotes, ids=None):
        self.quotes, self.ids, self.calls = quotes, ids or self.SECTION_IDS, []

    def __call__(self, prompt, model):
        self.calls.append(model)
        if prompt.startswith("Below is the outline"):
            reply = self.ids
        else:
            reply = {t: ({"found": True, "quotes": [q], "answer": f"{t} answer"} if q else
                         {"found": False, "quotes": [], "answer": ""}) for t, q in self.quotes.items()
                     if f'"{t}"' in prompt}
        return {"result": json.dumps(reply), "usage": {"input_tokens": 10, "output_tokens": 5}}


QUOTES = {"equity_awards": "Each Company Option shall be cancelled and converted",
          "termination_fee": "The Company shall pay Parent a fee of $25,000,000",
          "employee_benefits": "base pay no less favorable than before"}
CHUNK_IDS = {t: ["C1"] for t in QUOTES}  # TEXT has 4 sections, so its outline is one fixed chunk, C1


def big_outline():
    from evals.tmachine import Outline
    ps = passages_of(TEXT)
    return Outline(tuple(f"{s} {t}" for s, t, _, _ in ps), {s: (a, b) for s, _, a, b in ps}, False)


def test_label_contract_locates_quotes_in_the_chosen_sections_and_caches(tmp_path):
    from evals.tmachine import TOPICS
    runner = FakeRunner(QUOTES)
    ledger = Ledger(tmp_path / "l.jsonl", key="key")
    got = label_contract("edgar_1", TEXT, big_outline(), TOPICS, "m", runner, ledger, "a")
    assert all(got[f]["found"] and got[f]["spans"] for f in QUOTES)
    assert got["termination_fee"]["sections"] == ["8.3"]
    n = len(runner.calls)
    label_contract("edgar_1", TEXT, big_outline(), TOPICS, "m", runner, ledger, "a")
    assert len(runner.calls) == n  # second run is all cache


def test_status_rules():
    sec = lambda pos: "2.3" if pos < 200 else "6.9"
    f = lambda spans, found=True: {"found": found, "spans": spans, "error": False}
    assert status(f([[10, 50]]), f([[40, 90]]), sec) == "kept"
    assert status(f([[10, 20]]), f([[100, 120]]), sec) == "kept"  # same section 2.3
    assert status(f([[10, 20]]), f([[300, 320]]), sec) == "disagree"
    assert status(f([], False), f([], False), sec) == "absent"
    assert status(f([[10, 20]]), f([], False), sec) == "one_found"
    assert status(f([]), f([[10, 20]]), sec) == "one_found"  # said found, quote not located
    assert status({"found": False, "spans": [], "error": True}, f([[10, 20]]), sec) == "error"
    assert status(f([[10, 20]]), f([[300, 320]]), lambda pos: "") == "disagree"  # no section: overlap only


def test_unparseable_reply_marks_error_not_absent(tmp_path):
    from evals.tmachine import TOPICS
    runner = lambda prompt, model: {"result": "I cannot help with that.", "usage": {}}
    got = label_contract("edgar_1", TEXT, big_outline(), TOPICS, "m", runner, Ledger(tmp_path / "l.jsonl", key="key"), "a")
    assert all(v["error"] and not v["found"] for v in got.values())


@pytest.fixture
def deals_conn(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    build_index(tmp_path / "d.db", {"edgar_1": TEXT})
    return sqlite3.connect(tmp_path / "d.db", check_same_thread=False)


@pytest.fixture
def deals_conn_two(tmp_path):
    import sqlite3
    from retrieval.index import build_index
    texts = {"edgar_1": TEXT, "edgar_2": TEXT}
    build_index(tmp_path / "d.db", texts)
    return sqlite3.connect(tmp_path / "d.db", check_same_thread=False), texts


def test_label_all_rows_items_and_resume(tmp_path, deals_conn):
    from evals.tmachine import PASSES, TOPICS
    runner = FakeRunner(QUOTES, ids=CHUNK_IDS)
    rows, summary = label_all(deals_conn, {"edgar_1": TEXT}, [("edgar_1", "Acme Software, Inc.")], TOPICS, PASSES,
                              runner, tmp_path / "l.jsonl", workers=2)
    assert summary["kept"] == 3 and summary["complete"] == 1 and summary["fallback_contracts"] == 1
    assert sorted(set(runner.calls)) == sorted(m for _, m in PASSES)
    items = items_from_rows(rows)
    assert {i.item_id for i in items} == {f"edgar_1|{f}" for f in QUOTES}
    ea = next(i for i in items if i.category == "equity_awards")
    assert ea.query == TEMPLATES["equity_awards"].format(target="Acme Software, Inc.")
    assert TEXT[ea.gold[0][0]:ea.gold[0][1]].startswith("Each Company Option shall be cancelled")
    n = len(runner.calls)
    label_all(deals_conn, {"edgar_1": TEXT}, [("edgar_1", "Acme Software, Inc.")], TOPICS, PASSES, runner,
              tmp_path / "l.jsonl")
    assert len(runner.calls) == n


def test_max_new_bounds_the_run(tmp_path, deals_conn_two):
    from evals.tmachine import PASSES, TOPICS
    conn, texts = deals_conn_two  # two contracts, edgar_1 and edgar_2, both TEXT
    runner = FakeRunner(QUOTES, ids=CHUNK_IDS)
    rows, summary = label_all(conn, texts, [("edgar_1", "A"), ("edgar_2", "B")], TOPICS, PASSES, runner,
                              tmp_path / "l.jsonl", max_new=1)
    assert summary["complete"] == 1 and {r["contract_id"] for r in rows} == {"edgar_1"}


def test_topics_by_contract(tmp_path, deals_conn_two):
    from evals.tmachine import PASSES, TOPICS
    conn, texts = deals_conn_two
    runner = FakeRunner(QUOTES, ids=CHUNK_IDS)
    per = {"edgar_2": {"equity_awards": TOPICS["equity_awards"]}}
    rows, summary = label_all(conn, texts, [("edgar_1", "A"), ("edgar_2", "B")], TOPICS, PASSES, runner,
                              tmp_path / "l.jsonl", topics_by_contract=per)
    assert sorted((r["contract_id"], r["family"]) for r in rows) == sorted(
        [("edgar_1", f) for f in QUOTES] + [("edgar_2", "equity_awards")])


def _reply(obj):
    return {"result": json.dumps(obj), "usage": {}}


def test_missing_or_non_list_step1_topic_is_error_but_empty_list_is_absent(tmp_path):
    from evals.tmachine import TOPICS
    r = lambda prompt, model: _reply({"equity_awards": "2.3", "termination_fee": []})
    got = label_contract("e", TEXT, big_outline(), TOPICS, "m", r, Ledger(tmp_path / "l.jsonl", key="key"), "a")
    assert got["equity_awards"]["error"]  # non-list
    assert got["employee_benefits"]["error"]  # key missing
    assert not got["termination_fee"]["error"] and not got["termination_fee"]["found"]


def test_unmatched_ids_are_error_and_lenient_ids_match(tmp_path):
    from evals.tmachine import TOPICS
    runner = FakeRunner(QUOTES, ids={"equity_awards": ["Section 2.3"], "termination_fee": ["8.3.", "99"],
                                     "employee_benefits": ["7.7", "§ 1.1"]})
    runner.ids["employee_benefits"] = ["7.7"]
    got = label_contract("e", TEXT, big_outline(), TOPICS, "m", runner, Ledger(tmp_path / "l.jsonl", key="key"), "a")
    assert got["equity_awards"]["sections"] == ["2.3"] and got["equity_awards"]["found"]
    assert got["termination_fee"]["sections"] == ["8.3"] and got["termination_fee"]["unmatched"] == 1
    assert got["employee_benefits"]["error"] and got["employee_benefits"]["unmatched"] == 1
    from evals.tmachine import _norm_id
    assert _norm_id("2.3 Treatment of Options") == "2.3" and _norm_id("C1:") == "C1" and _norm_id("§2.3") == "2.3"


def test_step2_omitted_topic_is_error(tmp_path):
    from evals.tmachine import TOPICS

    def runner(prompt, model):
        if prompt.startswith("Below is the outline"):
            return _reply(FakeRunner.SECTION_IDS)
        return _reply({"equity_awards": {"found": False, "quotes": [], "answer": ""}, "termination_fee": "oops"})
    got = label_contract("e", TEXT, big_outline(), TOPICS, "m", runner, Ledger(tmp_path / "l.jsonl", key="key"), "a")
    assert not got["equity_awards"]["error"]
    assert got["termination_fee"]["error"] and got["employee_benefits"]["error"]


def test_runner_failure_stops_the_run_and_resume_reuses_the_ledger(tmp_path):
    import sqlite3
    import threading
    from evals.tmachine import PASSES, TOPICS
    from retrieval.index import build_index
    texts = {f"edgar_{i}": TEXT for i in range(8)}
    build_index(tmp_path / "d.db", texts)
    conn = sqlite3.connect(tmp_path / "d.db", check_same_thread=False)
    contracts = [(c, "T") for c in texts]
    good = FakeRunner(QUOTES, ids=CHUNK_IDS)
    attempts, lock = [], threading.Lock()

    def bad(prompt, model):
        with lock:
            attempts.append(1)
            first = len(attempts) == 1
        if first:
            raise RuntimeError("claude down")
        return good(prompt, model)
    with pytest.raises(RuntimeError, match="claude down"):
        label_all(conn, texts, contracts, TOPICS, PASSES, bad, tmp_path / "l.jsonl", workers=2)
    assert len(attempts) < 8 * 4
    ledgered = len((tmp_path / "l.jsonl").read_text().splitlines()) if (tmp_path / "l.jsonl").exists() else 0
    good.calls.clear()
    label_all(conn, texts, contracts, TOPICS, PASSES, good, tmp_path / "l.jsonl", workers=2)
    assert len(good.calls) == 8 * 4 - ledgered


def test_scope_report_outcomes():
    import sqlite3
    from evals.items import Item
    from evals.tmachine import scope_report
    from retrieval.scope import Resolver
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", [
        ("acme software", "edgar_1", "target"), ("polycom", "edgar_2", "target"), ("polycom", "edgar_3", "target"),
        ("zeta labs", "edgar_4", "target")])
    items = [Item("edgar_1|equity_awards", "edgar_1", "equity_awards", "equity_awards", "Acme Software options?", ((0, 5),)),
             Item("edgar_2|termination_fee", "edgar_2", "termination_fee", "termination_fee", "Polycom fee?", ((0, 5),)),
             Item("edgar_5|termination_fee", "edgar_5", "termination_fee", "termination_fee", "Zeta Labs fee?", ((0, 5),)),
             Item("edgar_6|termination_fee", "edgar_6", "termination_fee", "termination_fee", "Unknown Co fee?", ((0, 5),))]
    got = scope_report(items, Resolver(conn))
    assert [r["outcome"] for r in got["items"]] == ["right", "ambiguous", "wrong", "none"]
    assert sum(sum(c.values()) for c in got["by_split"].values()) == 4
