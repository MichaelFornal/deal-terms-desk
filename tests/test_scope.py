import sqlite3

from retrieval.scope import Resolver, Scope, strip_alias


def make(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", rows)
    return Resolver(conn)


def test_unique_target_alias_scopes():
    r = make([("linear technology", "edgar_1", "target"), ("lltc", "edgar_1", "target"),
              ("analog devices", "edgar_1", "parent")])
    assert r.resolve("What happens to Linear Technology's stock options?") == Scope("edgar_1", "linear technology", ("edgar_1",))
    assert r.resolve("LLTC termination fee").contract_id == "edgar_1"


def test_longest_alias_wins():
    r = make([("acme", "edgar_1", "target"), ("acme software", "edgar_2", "target")])
    assert r.resolve("Acme Software break-up fee").contract_id == "edgar_2"


def test_ambiguous_alias_falls_back_and_says_so():
    r = make([("oracle", "edgar_1", "parent"), ("oracle", "edgar_2", "parent")])
    s = r.resolve("What did Oracle agree to pay?")
    assert s == Scope(None, "oracle", ("edgar_1", "edgar_2"))


def test_target_beats_parent():
    r = make([("oracle", "edgar_1", "target"), ("oracle", "edgar_2", "parent"), ("oracle", "edgar_3", "parent")])
    assert r.resolve("Oracle options").contract_id == "edgar_1"


def test_no_match_and_punctuation_safe():
    r = make([("at and t", "edgar_9", "target")])
    assert r.resolve("AT&T employees' benefits").contract_id == "edgar_9"
    assert r.resolve('"AND" OR NEAR(* fee') == Scope(None, None, ())
    assert r.resolve("") == Scope(None, None, ())


def test_single_token_alias_needs_a_capital_in_the_raw_query():
    r = make([("true", "edgar_1", "target"), ("base", "edgar_2", "target"), ("lltc", "edgar_3", "target"),
              ("linear technology", "edgar_3", "target")])
    assert r.resolve("Is it true that base salary continues?") == Scope(None, None, ())
    assert r.resolve("True Corp options").contract_id == "edgar_1"
    assert r.resolve("LLTC fee").contract_id == "edgar_3"
    assert r.resolve("lltc fee") == Scope(None, None, ())
    assert r.resolve("linear technology fee").contract_id == "edgar_3"  # multi-token aliases need no capital


def test_strip_alias_drops_the_whole_run_and_keeps_the_rest_in_order():
    q = "What happens to Linear Technology employees' stock options?"
    assert strip_alias(q, "linear technology") == "What happens to employees stock options"
    assert strip_alias("AT&T employees' benefits", "at and t") == "employees benefits"
    assert strip_alias("Acme Software", "acme software") == "Acme Software"  # nothing left: the original
    assert strip_alias("Is it true that True Corp pays?", "true") == "Is it true that Corp pays"
    assert strip_alias("acme fee and Acme options", "acme software") == "acme fee and Acme options"
