import sqlite3

from retrieval.scope import Resolver, Scope


def make(rows):
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", rows)
    return Resolver(conn)


def test_unique_target_alias_scopes():
    r = make([("linear technology", "edgar_1", "target"), ("lltc", "edgar_1", "target"),
              ("analog devices", "edgar_1", "parent")])
    assert r.resolve("What happens to Linear Technology's stock options?") == Scope("edgar_1", "linear technology", ("edgar_1",))
    assert r.resolve("lltc termination fee").contract_id == "edgar_1"


def test_longest_alias_wins():
    r = make([("acme", "edgar_1", "target"), ("acme software", "edgar_2", "target")])
    assert r.resolve("Acme Software break-up fee").contract_id == "edgar_2"


def test_ambiguous_alias_falls_back_and_says_so():
    r = make([("oracle", "edgar_1", "parent"), ("oracle", "edgar_2", "parent")])
    s = r.resolve("What did Oracle agree to pay?")
    assert s == Scope(None, "oracle", ("edgar_1", "edgar_2"))


def test_target_beats_parent():
    r = make([("oracle", "edgar_1", "target"), ("oracle", "edgar_2", "parent"), ("oracle", "edgar_3", "parent")])
    assert r.resolve("oracle options").contract_id == "edgar_1"


def test_no_match_and_punctuation_safe():
    r = make([("at and t", "edgar_9", "target")])
    assert r.resolve("AT&T employees' benefits").contract_id == "edgar_9"
    assert r.resolve('"AND" OR NEAR(* fee') == Scope(None, None, ())
    assert r.resolve("") == Scope(None, None, ())
