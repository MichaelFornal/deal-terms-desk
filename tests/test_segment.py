from pipeline.segment import segment

TOC = "TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 The Merger 6  Section 2.1 Effect on Stock 9  Section 2.2 Options 9  Section 3.1 Fees 12\n\n"
PREAMBLE = "AGREEMENT AND PLAN OF MERGER dated as of May 1 among Parent, Merger Sub and the Company.\n\nWHEREAS, the parties intend to merge.\n\n"
BODY = (
    "Section 1.1 Closing. The closing shall take place at 10:00 a.m.\n\n"
    "Section 1.2 The Merger. Merger Sub shall be merged into the Company pursuant to Section 1.1 hereof.\n\n"
    "Section 2.1 Effect on Stock. Each share shall be converted.\n\n"
    "Section 2.2 Options. Each Company Option shall vest in full.\n\n"
    "Section 3.1 Fees. The Company shall pay the Termination Fee.\n"
)
DOC = TOC + PREAMBLE + BODY


def check_cover(text, ps, max_chars):
    assert ps[0].start == 0 and ps[-1].end == len(text)
    assert all(a.end == b.start for a, b in zip(ps, ps[1:]))
    assert all(0 < p.end - p.start <= max_chars for p in ps)
    assert [p.ordinal for p in ps] == list(range(len(ps)))


def test_sections_come_from_the_body_not_the_table_of_contents():
    ps = segment("c1", DOC)
    check_cover(DOC, ps, 2400)
    sections = [p for p in ps if p.kind == "section"]
    assert [p.section_id for p in sections] == ["1.1", "1.2", "2.1", "2.2", "3.1"]
    assert sections[0].section_title == "Closing"
    assert DOC[sections[3].start:sections[3].end].startswith("Section 2.2 Options.")


def test_table_of_contents_is_marked_toc_and_preamble_is_front():
    ps = segment("c1", DOC, max_chars=160)
    kinds = {DOC[p.start:p.end][:17]: p.kind for p in ps if p.kind != "section"}
    assert kinds["TABLE OF CONTENTS"] == "toc"
    assert any(p.kind == "front" and "WHEREAS" in DOC[p.start:p.end] for p in ps)


def test_cross_reference_is_not_a_heading():
    ps = segment("c1", DOC)
    assert sum(1 for p in ps if p.section_id == "1.1") == 1


def test_inline_headings_after_wide_spaces_are_found():
    text = "The officers shall remain.   2.6           Conversion of Securities. At the Effective Time each share converts.   2.7   Exchange. The agent shall pay."
    ps = segment("c2", text)
    check_cover(text, ps, 2400)
    assert [p.section_id for p in ps if p.kind == "section"] == ["2.6", "2.7"]
    assert ps[0].kind == "front"


def test_long_section_is_split_at_subclause_boundaries():
    clause = "the Company shall comply with each of its obligations under this Agreement in all respects "
    text = "Section 5.1 Covenants. " + "".join(f"({c}) {clause * 3}" for c in "abcdefgh")
    ps = segment("c3", text, max_chars=600)
    check_cover(text, ps, 600)
    assert len(ps) > 1
    assert all(p.section_id == "5.1" for p in ps)
    assert all(text[p.start:p.end].lstrip().startswith("(") for p in ps[1:])


def test_text_with_no_headings_is_still_covered_and_bounded():
    text = "lorem ipsum dolor sit amet " * 400
    ps = segment("c4", text, max_chars=500)
    check_cover(text, ps, 500)
    assert {p.kind for p in ps} == {"front"}
    assert {p.section_id for p in ps} == {""}


def test_empty_text_gives_no_passages():
    assert segment("c5", "") == []
