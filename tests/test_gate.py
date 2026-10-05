from answer.blocks import Block, Part, build_blocks
from answer.gate import check, normalise
from tests.test_ladder import deals_ladder, ladder  # noqa: F401  (fixtures)

PASSAGE = "Section 8.3 Fees. The Company shall pay Parent the\nCompany Termination Fee if this Agreement is terminated."
DEF = "“Company Termination Fee” means an amount in cash equal to $50,000,000."
AMEND = "(b) The Termination Fee shall be $40,000,000."
BLOCKS = [Block("P1", 7, "big", "Article VIII › 8.3", False,
                (Part("passage", PASSAGE, None), Part("definition", DEF, None), Part("amendment", AMEND, 2)))]


def test_exact_quote_passes_and_names_its_part():
    blk, part = check("The Company shall pay Parent the Company Termination Fee", "P1", BLOCKS)
    assert blk.passage_id == 7 and part.kind == "passage"
    assert check("an amount in cash equal to $50,000,000", "P1", BLOCKS)[1].kind == "definition"
    blk, part = check("The Termination Fee shall be $40,000,000", "P1", BLOCKS)
    assert part.kind == "amendment" and part.amendment_no == 2


def test_typographic_and_whitespace_variants_pass():
    assert check('"Company Termination Fee" means an   amount', "P1", BLOCKS)[1].kind == "definition"
    assert normalise("a  b\n\tc — ’") == "a b c - '"


def test_quote_spanning_two_parts_fails():
    assert check("is terminated. “Company Termination Fee” means", "P1", BLOCKS) == "quote_not_found"


def test_bad_ref_and_empty_quote():
    assert check("The Company shall pay", "P9", BLOCKS) == "bad_ref"
    assert check("The Company shall pay", "p1", BLOCKS)[0].ref == "P1"  # ref case and brackets tolerated
    assert check("The Company shall pay", "[P1]", BLOCKS)[0].ref == "P1"
    assert check("   ", "P1", BLOCKS) == "empty_quote"


def test_paraphrase_fails():
    assert check("The Company must pay Parent the fee", "P1", BLOCKS) == "quote_not_found"


def test_build_blocks_carries_definitions_amendments_and_schedule_tags(deals_ladder):
    got = deals_ladder.run("R6n", "termination fee", "edgar_0001", k=5)
    blocks = build_blocks(deals_ladder, got.hits[:5])
    assert [b.ref for b in blocks] == [f"P{i}" for i in range(1, len(blocks) + 1)]
    fee = next(b for b in blocks if any(p.kind == "amendment" for p in b.parts))
    assert fee.parts[0].kind == "passage" and fee.section_path
    assert any(b.schedule_ref for b in blocks)  # non-vacuous: section 7.3 is schedule-tagged
    assert any(b.schedule_ref for b in blocks) == any(
        deals_ladder.conn.execute("SELECT 1 FROM passage_tags WHERE passage_id = ?", (b.passage_id,)).fetchone()
        for b in blocks)


def test_build_blocks_on_maud_index_has_no_tags_table(ladder):
    got = ladder.run("R6n", "termination fee", "big", k=5)
    blocks = build_blocks(ladder, got.hits[:5])
    assert blocks and not any(b.schedule_ref for b in blocks)
    assert any(p.kind == "definition" for b in blocks for p in b.parts)


def _one(text):
    return [Block("P1", 1, "c", "s", False, (Part("passage", text, None),))]


def test_quote_must_start_and_end_on_word_boundaries():
    assert check("reasonable efforts", "P1", _one("use unreasonable efforts")) == "quote_not_found"
    assert check("shall pay", "P1", _one("shall payback the sum")) == "quote_not_found"
    assert check("not", "P1", _one("Parent cannot close")) == "quote_not_found"
    assert check("reasonable efforts", "P1", _one("use reasonable efforts to close"))[1].kind == "passage"
    assert check("is terminated.", "P1", BLOCKS)[1].kind == "passage"
    assert check('"Company Termination Fee" means', "P1", _one('x“Company Termination Fee” means y'))[1].kind == "passage"
