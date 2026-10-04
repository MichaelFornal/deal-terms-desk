import json

import pytest

from answer.answerer import Answerer, ParseError, Prepared
from answer.prompt import TEMPLATE_SHA, render
from tests.fakes import fake_claude
from tests.test_ladder import deals_ladder, ladder  # noqa: F401

FEE_QUOTE = "The Company shall pay Parent the Company Termination Fee"


def reply(**obj):
    return json.dumps(obj)


def fee_ref(ladder, question="termination fee", choices=()):
    """The label the fee passage gets in this fixture (hit order decides it, not the test)."""
    prep = Answerer(ladder, fake_claude(""), "m").prepare(question, "big", choices=choices)
    return next(b.ref for b in prep.blocks if FEE_QUOTE in b.parts[0].text)


def test_answered_with_a_gated_claim(ladder):
    ref = fee_ref(ladder)
    run = fake_claude(reply(state="answered", claims=[{"text": "The Company pays the fee.", "quote": FEE_QUOTE,
                                                       "ref": ref}, {"text": "x", "quote": "made up", "ref": ref}]))
    a = Answerer(ladder, run, "m").ask("termination fee", "big")
    assert a.state == "answered" and len(a.claims) == 1 and a.claims[0].part == "passage"
    assert a.dropped[0].reason == "quote_not_found"
    assert a.tokens_in == 100 and a.tokens_out == 20 and a.prompt_sha and a.contract_id == "big"
    assert run.calls[0][1] == "m" and f"[{ref}]" in run.calls[0][0]


def test_no_surviving_claim_is_not_stated(ladder):
    run = fake_claude(reply(state="answered", claims=[{"text": "x", "quote": "invented words", "ref": "P1"}]))
    assert Answerer(ladder, run, "m").ask("termination fee", "big").state == "not_stated"


def test_model_not_stated_wins_over_claims(ladder):
    run = fake_claude(reply(state="not_stated", claims=[{"text": "x", "quote": FEE_QUOTE, "ref": fee_ref(ladder)}]))
    a = Answerer(ladder, run, "m").ask("termination fee", "big")
    assert a.state == "not_stated" and len(a.claims) == 1 and a.dropped == ()  # claim passed the gate; model decided


def test_which_deal_makes_no_call(deals_ladder):
    run = fake_claude(reply(state="answered", claims=[]))
    a = Answerer(deals_ladder, run, "m").ask("What is the outside date for Zeta Labs?")
    assert a.state == "which_deal" and run.calls == [] and a.candidates == ()


def test_named_deal_is_resolved_and_answered(deals_ladder):
    run = fake_claude(reply(state="not_stated", claims=[]))
    a = Answerer(deals_ladder, run, "m").ask("What is the Acme Software outside date?")
    assert a.contract_id == "edgar_0001" and len(run.calls) == 1
    assert "Acme Software outside date" in run.calls[0][0]  # the prompt keeps the visitor's own question


def test_amended_quote_sets_the_flag(deals_ladder):
    run = fake_claude(reply(state="answered", claims=[{"text": "Fee is $40m.", "quote": "The Termination Fee shall be "
                                                       "$40,000,000", "ref": "P1"}]))
    ans = Answerer(deals_ladder, run, "m")
    prep = ans.prepare("termination fee", "edgar_0001")
    ref = next(b.ref for b in prep.blocks if any(p.kind == "amendment" for p in b.parts))
    run2 = fake_claude(reply(state="answered", claims=[{"text": "Fee is $40m.", "quote": "The Termination Fee shall "
                                                        "be $40,000,000", "ref": ref}]))
    a = Answerer(deals_ladder, run2, "m").ask("termination fee", "edgar_0001")
    assert a.state == "answered" and a.amended and a.claims[0].amendment_no == 2


def test_unfiled_schedule_needs_a_tagged_passage(deals_ladder, ladder):
    # deals fixture: section 7.3 refers to a disclosure schedule and is tagged
    prep = Answerer(deals_ladder, fake_claude(""), "m").prepare("termination fee schedule", "edgar_0001")
    tagged = next(b for b in prep.blocks if b.schedule_ref)
    q = tagged.parts[0].text.split(".")[0]
    run = fake_claude(reply(state="unfiled_schedule", claims=[{"text": "In a schedule.", "quote": q, "ref": tagged.ref}]))
    assert Answerer(deals_ladder, run, "m").ask("termination fee schedule", "edgar_0001").state == "unfiled_schedule"
    run = fake_claude(reply(state="unfiled_schedule", claims=[{"text": "x", "quote": FEE_QUOTE, "ref": fee_ref(ladder)}]))
    a = Answerer(ladder, run, "m").ask("termination fee", "big")
    assert len(a.claims) == 1 and a.state == "not_stated"  # no tags in MAUD index


def test_parse_failure_raises_not_abstains(ladder):
    with pytest.raises(ParseError):
        Answerer(ladder, fake_claude("I cannot help with that."), "m").ask("termination fee", "big")
    with pytest.raises(ParseError):
        Answerer(ladder, fake_claude(reply(state="answered", claims="nope")), "m").ask("termination fee", "big")


def test_reply_in_code_fence_is_parsed(ladder):
    body = reply(state="answered", claims=[{"text": "t", "quote": FEE_QUOTE, "ref": fee_ref(ladder)}])
    run = fake_claude("Here is the answer:\n```json\n" + body + "\n```")
    assert Answerer(ladder, run, "m").ask("termination fee", "big").state == "answered"


def test_option_mode_records_the_choice_and_lists_options(ladder):
    ch = ("All Cash", "All Stock")
    ref = fee_ref(ladder, "Type of Consideration", ch)
    run = fake_claude(reply(state="answered", choice="All Cash", claims=[{"text": "t", "quote": FEE_QUOTE, "ref": ref}]))
    a = Answerer(ladder, run, "m").ask("Type of Consideration", "big", choices=ch)
    assert a.state == "answered" and a.choice == "All Cash"
    assert "- All Cash" in run.calls[0][0] and "- All Stock" in run.calls[0][0]


def test_no_hits_is_not_stated_without_a_call(ladder):
    run = fake_claude(reply(state="answered", claims=[]))
    a = Answerer(ladder, run, "m").ask("!!", "big")
    assert a.state == "not_stated" and run.calls == []


def test_prompt_hash_is_stable_and_template_hash_is_exported(ladder):
    p1 = Answerer(ladder, fake_claude(""), "m").prepare("termination fee", "big")
    p2 = Answerer(ladder, fake_claude(""), "m").prepare("termination fee", "big")
    assert isinstance(p1, Prepared) and p1.prompt_sha == p2.prompt_sha and len(TEMPLATE_SHA) == 12
    assert render("termination fee", p1.blocks) == p1.prompt


def test_missing_or_non_string_result_is_a_parse_error(ladder):
    for bad in ({}, {"result": None}, {"result": 5}):
        ans = Answerer(ladder, lambda prompt, model, bad=bad: bad, "m")
        with pytest.raises(ParseError):
            ans.ask("termination fee", "big")
