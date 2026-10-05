import sqlite3

import pytest

from retrieval.index import build_index
from retrieval.scope import Resolver, Scope, scope_question, strip_alias


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
    assert strip_alias("Is it true that True Corp pays?", "true") == "Is it true that pays"
    assert strip_alias("acme fee and Acme options", "acme software") == "acme fee and Acme options"


def make_with_fts(tmp_path, rows, docs):
    db = tmp_path / "d.db"
    build_index(db, docs)
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)", rows)
    return Resolver(conn)


def _common_docs(word: str, n: int) -> dict[str, str]:
    # one contract with n sections that each use `word`; build_index cuts on "Section x.y"
    return {"contract_9": "\n\n".join(f"Section 1.{i} Terms. The {word} amount is due." for i in range(1, n + 1))}


def test_sentence_initial_common_word_does_not_scope(tmp_path, monkeypatch):
    import retrieval.scope as scope
    monkeypatch.setattr(scope, "COMMON_MIN_PASSAGES", 3)
    r = make_with_fts(tmp_path, [("base", "edgar_2", "target"), ("true", "edgar_1", "target")],
                      _common_docs("base", 5) | {"contract_8": _common_docs("true", 5)["contract_9"]})
    assert r.resolve("Base salary continues for a year?") == Scope(None, None, ())
    assert r.resolve("What about Base?").contract_id == "edgar_2"  # not at a sentence start: still a name
    assert r.resolve("True Corp options").contract_id == "edgar_1"  # a corporate suffix follows: a name
    assert r.resolve("True salary continues") == Scope(None, None, ())  # common, no suffix: not a name


def test_rare_sentence_initial_alias_still_scopes(tmp_path, monkeypatch):
    import retrieval.scope as scope
    monkeypatch.setattr(scope, "COMMON_MIN_PASSAGES", 3)
    r = make_with_fts(tmp_path, [("oracle", "edgar_1", "target")], _common_docs("base", 5))
    assert r.resolve("Oracle options").contract_id == "edgar_1"
    assert r.resolve("Fees? Oracle pays.").contract_id == "edgar_1"


def test_strip_alias_drops_suffix_and_possessive_after_the_name():
    assert strip_alias("What happens to Linear Technology Corporation's options?", "linear technology") == \
        "What happens to options"
    assert strip_alias("Acme Software, Inc. termination fee", "acme software") == "termination fee"
    assert strip_alias("Does the Company pay Acme Software?", "acme software") == "Does the Company pay"


def test_scope_question_keeps_a_picked_deal_and_drops_every_name_of_it_longest_first():
    r = make([("acme software", "edgar_1", "target"), ("acme", "edgar_1", "target"),
              ("big parent", "edgar_1", "parent"), ("zeta", "edgar_2", "target")])
    assert scope_question(r, "Acme Software and Big Parent fee", "edgar_1") == (Scope("edgar_1", None, ()), "and fee")
    # another deal's name is left alone: the visitor picked edgar_1
    assert scope_question(r, "Zeta fee", "edgar_1") == (Scope("edgar_1", None, ()), "Zeta fee")


def test_scope_question_without_a_resolver_keeps_a_picked_question_as_is():
    assert scope_question(None, "Acme fee", "contract_1") == (Scope("contract_1", None, ()), "Acme fee")


def test_scope_question_resolves_and_strips_only_when_one_deal_is_found():
    r = make([("acme software", "edgar_1", "target"), ("oracle", "edgar_2", "parent"), ("oracle", "edgar_3", "parent")])
    assert scope_question(r, "Acme Software fee") == (Scope("edgar_1", "acme software", ("edgar_1",)), "fee")
    assert scope_question(r, "Oracle fee") == (Scope(None, "oracle", ("edgar_2", "edgar_3")), "Oracle fee")
    assert scope_question(r, "fee") == (Scope(None, None, ()), "fee")


def test_scope_question_needs_a_resolver_when_no_deal_is_picked():
    with pytest.raises(ValueError, match="resolver"):
        scope_question(None, "fee")
