import json

import pytest

from answer.answerer import Answerer, ParseError, Prepared, _recover_choice, _repair_inner_quotes
from answer.blocks import Block, Part
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


def test_option_mode_prompt_always_fills_choice_and_template_hash_covers_choices():
    import hashlib

    from answer.prompt import CHOICES, TEMPLATE
    p = render("Type of Consideration", [], choices=("All Cash", "All Stock"))
    assert "Always fill \"choice\"" in p and "likeliest" in p and "not_stated" in p
    assert TEMPLATE_SHA == hashlib.sha1((TEMPLATE + CHOICES).encode("utf-8")).hexdigest()[:12]


QUOTE_SHAPES = [
    'immediately prior to the consummation of the Merger (a "Vested Company RSU"),',
    'under the Plan (the "Excluded Benefits"))',
    'any benefits (collectively, "Excluded Benefits"))',
]


def quote_prepared(quote):
    part = Part("passage", quote.replace('"', "“", 1).replace('"', "”", 1))
    blk = Block("P1", 1, "big", "1.1", False, (part,))
    return Prepared("q", "big", [blk], "prompt", "sha")


def finish(text, quote):
    return Answerer(None, None, "m").finish(quote_prepared(quote), {"result": text, "usage": {}}, 1.0)


@pytest.mark.parametrize("quote", QUOTE_SHAPES)
def test_unescaped_inner_quotes_are_repaired_and_still_gated(quote):
    raw = '```json\n{"state": "answered", "claims": [{"text": "t", "quote": "' + quote + '", "ref": "P1"}]}\n```'
    with pytest.raises(json.JSONDecodeError):
        json.loads(raw.strip("`").removeprefix("json"))
    a = finish(raw, quote)
    assert a.state == "answered" and a.claims[0].quote == quote and not a.dropped
    wrong = raw.replace("Excluded", "Included").replace("Vested", "Unvested")
    assert finish(wrong, quote).dropped[0].reason == "quote_not_found"


def test_escaped_inner_quotes_parse_unchanged():
    quote = QUOTE_SHAPES[0]
    raw = json.dumps({"state": "answered", "claims": [{"text": "t", "quote": quote, "ref": "P1"}]})
    assert '\\"' in raw and _repair_inner_quotes(raw) == raw
    assert finish(raw, quote).claims[0].quote == quote


def test_non_json_garbage_still_raises_parse_error():
    for junk in ("I cannot help with that.", '{"state": "answered", "claims": [oops "x" }', "{not json}"):
        with pytest.raises(ParseError):
            finish(junk, "x")


def test_repair_escapes_only_inner_quotes():
    s = 'Sure: {"state": "answered", "claims": [{"text": "a: b", "quote": "the "Term" x", "ref": "P1"}], "n": [[1], ["a"]]} done'
    assert _repair_inner_quotes(s) == (
        '{"state": "answered", "claims": [{"text": "a: b", "quote": "the \\"Term\\" x", "ref": "P1"}], "n": [[1], ["a"]]}')
    assert _repair_inner_quotes('{"a": "x \\"y\\" z"}') == '{"a": "x \\"y\\" z"}'
    assert _repair_inner_quotes("no braces") == "no braces"


@pytest.mark.parametrize("quote", [
    'the "Term", as defined in Section 1',
    'the "Term": which means the thing',
    'the "Term": 5 days after (the "Company")',
    'any benefit under (the "Company")',
])
def test_inner_quote_before_comma_or_colon_is_repaired(quote):
    raw = '{"state": "answered", "claims": [{"text": "t", "quote": "' + quote + '", "ref": "P1"}], "choice": null}'
    got = json.loads(_repair_inner_quotes(raw))
    assert got["claims"][0]["quote"] == quote and got["choice"] is None
    assert got["state"] == "answered"


def test_closing_rule_keeps_key_and_value_boundaries():
    s = '{"a": "x",\n "b": ["y", "z"], "c": {"d": "1"}, "e": true}'
    assert _repair_inner_quotes(s) == s
    assert json.loads(_repair_inner_quotes('{"quote": "ends (the "Company")", "ref": "P1"}'))["quote"] == 'ends (the "Company")'


def _spy_r6n(ladder):
    seen, real = [], ladder.run

    def run(rung, query, contract_id=None, k=10, rewritten=None):
        if rung == "R6n":
            seen.append((query, contract_id))
        return real(rung, query, contract_id, k, rewritten)
    ladder.run = run
    return seen


def test_picked_deal_name_is_stripped_before_retrieval(deals_ladder):
    seen = _spy_r6n(deals_ladder)
    p = Answerer(deals_ladder, fake_claude(""), "m").prepare("What is the Acme Software outside date?", "edgar_0001")
    assert seen == [("What is the outside date", "edgar_0001")]
    assert isinstance(p, Prepared) and "Question: What is the Acme Software outside date?" in p.prompt


def test_picked_deal_on_the_maud_index_keeps_the_question(ladder):
    seen = _spy_r6n(ladder)
    Answerer(ladder, fake_claude(""), "m").prepare("big termination fee", "big")
    assert seen == [("big termination fee", "big")]


def test_usage_is_carried_into_the_answer(ladder):
    run = fake_claude(reply(state="not_stated", claims=[]))
    a = Answerer(ladder, run, "m").ask("termination fee", "big")
    assert a.usage and a.usage.get("output_tokens") == a.tokens_out
    assert Answerer(None, None, "m").finish(quote_prepared("x"), {"result": reply(state="not_stated", claims=[])},
                                            1.0).usage == {}


def test_prompt_says_amending_text_replaces_the_passage():
    p = render("q", [])
    assert "[Amended by Amendment No. N]" in p and "replaces the passage above it" in p
    assert "state the amended terms and quote the amending text" in p


QUOTED_OPTS = ('"Inconsistent" with fiduciary duties', '"Breach" of fiduciary duties', "No")


def _bad_choice_reply(ref, line):
    return ('```json\n{\n  "state": "answered",\n' + line + '\n  "claims": [{"text": "t", "quote": "' + FEE_QUOTE
            + '", "ref": "' + ref + '"}]\n}\n```')


def test_option_with_inner_quotes_is_recovered(ladder):
    ref = fee_ref(ladder, "Fiduciary", QUOTED_OPTS)
    run = fake_claude(_bad_choice_reply(ref, '  "choice": "Inconsistent" with fiduciary duties,'))
    a = Answerer(ladder, run, "m").ask("Fiduciary", "big", choices=QUOTED_OPTS)
    assert a.state == "answered" and a.choice == '"Inconsistent" with fiduciary duties'


def test_option_with_typographic_quotes_is_recovered(ladder):
    opts = ("“Reasonably likely/expected” to be inconsistent", "No")
    ref = fee_ref(ladder, "Fiduciary", opts)
    run = fake_claude(_bad_choice_reply(ref, '  "choice": "Reasonably likely/expected" to be inconsistent,'))
    a = Answerer(ladder, run, "m").ask("Fiduciary", "big", choices=opts)
    assert a.choice == opts[0]


def test_unmatched_bad_choice_is_a_parse_error(ladder):
    ref = fee_ref(ladder, "Fiduciary", QUOTED_OPTS)
    run = fake_claude(_bad_choice_reply(ref, '  "choice": "Other" with something,'))
    with pytest.raises(ParseError):
        Answerer(ladder, run, "m").ask("Fiduciary", "big", choices=QUOTED_OPTS)


def test_recover_choice_unit():
    r = '{\n "state": "answered",\n "choice": "Inconsistent" with fiduciary duties,\n "claims": []\n}'
    out = _recover_choice(r, QUOTED_OPTS)
    assert '"choice": "\\"Inconsistent\\" with fiduciary duties",' in out
    assert _recover_choice(r, ("x",)) is None
    assert _recover_choice('{"state": "answered"}', QUOTED_OPTS) is None
    amb = ('"A" b', "A b")
    assert _recover_choice('"choice": "A" b', amb) is None
    assert _recover_choice('"choice": "A" b', ('"A" b',)) == '"choice": ' + json.dumps('"A" b')


def _spy_r6n(ladder):
    seen, real = [], ladder.run

    def run(rung, query, contract_id=None, k=10, rewritten=None):
        if rung == "R6n":
            seen.append((query, contract_id))
        return real(rung, query, contract_id, k, rewritten)
    ladder.run = run
    return seen


@pytest.mark.parametrize("question,picked", [("What is the Acme Software outside date?", None),
                                             ("What is the Acme Software outside date?", "edgar_0001"),
                                             ("Acme Software outside date", "contract_1")])
def test_the_answerer_and_r7n_search_the_same_words_in_the_same_deal(deals_ladder, question, picked):
    seen = _spy_r6n(deals_ladder)
    deals_ladder.run("R7n", question, picked, k=5)
    via_ladder = list(seen)
    seen.clear()
    Answerer(deals_ladder, fake_claude(""), "m").prepare(question, picked)
    assert seen == via_ladder and len(seen) == 1


def test_the_answer_path_comes_from_settings_and_only_r7n_is_accepted(ladder, monkeypatch):
    import answer.answerer as A
    assert Answerer(ladder, fake_claude(""), "m").answer_path == "R7n"
    with pytest.raises(ValueError, match="'R6n'"):
        Answerer(ladder, fake_claude(""), "m", answer_path="R6n")
    monkeypatch.setattr(A, "load_answer_path", lambda: "R4")
    with pytest.raises(ValueError, match="'R4'"):
        Answerer(ladder, fake_claude(""), "m")


# prompt_sha from the M4 code (main a92fcfd, before this task) on these fixtures: the refactor must not move them.
GOLDEN = [
    ("deals", "What is the Acme Software outside date?", None, "5419b0b3f91d", ("edgar_0001",)),
    ("deals", "termination fee", "edgar_0001", "c814656a0121", ()),
    ("deals", "What is the Acme Software outside date?", "edgar_0001", "5419b0b3f91d", ()),
    ("deals", "Acme Software outside date", "contract_1", "2a2f69169918", ()),
    ("maud", "termination fee", "big", "d9e95ed716b4", ()),
    ("maud", "Who pays the walk-away payment?", "big", "2f0d4bff5bdf", ()),
    ("maud", "closing", "tiny", "c06935ff3a20", ()),
]


@pytest.mark.parametrize("which,question,picked,sha,candidates", GOLDEN)
def test_prompts_are_byte_identical_to_m4s(request, which, question, picked, sha, candidates):
    lad = request.getfixturevalue("deals_ladder" if which == "deals" else "ladder")
    p = Answerer(lad, fake_claude(""), "m").prepare(question, picked)
    assert isinstance(p, Prepared) and p.prompt_sha == sha and p.candidates == candidates
