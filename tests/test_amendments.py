from pipeline.amendments import AMEND_SPAN_MAX, amended_sections, amendment_no

AMEND = ("AMENDMENT NO. 2 TO AGREEMENT AND PLAN OF MERGER\n\n1. Section 7.3(b) of the Merger Agreement is hereby "
         "amended and restated in its entirety as follows: \"(b) The Termination Fee shall be $40,000,000.\"\n\n"
         "2. Section 1.4 of the Agreement is hereby amended by replacing \"June 30\" with \"September 30\".\n\n"
         "3. Exhibit A to the Agreement is hereby replaced in its entirety.\n")


def test_explicit_section_amendments_are_found_with_their_spans():
    got = amended_sections(AMEND)
    assert [g[0] for g in got] == ["7.3", "1.4"]
    s, e = got[0][1], got[0][2]
    assert "Termination Fee shall be $40,000,000" in AMEND[s:e] and "Section 1.4" not in AMEND[s:e]


def test_other_forms_never_link():
    assert amended_sections("Exhibit A to the Agreement is hereby replaced in its entirety.") == []
    assert amended_sections("The parties agree that the Outside Date shall be extended to May 1.") == []


def test_span_is_capped():
    text = "Section 2.1 of the Agreement is hereby amended as follows: " + "x" * 10000
    (_, s, e), = amended_sections(text)
    assert e - s == AMEND_SPAN_MAX


def test_amendment_number():
    assert amendment_no(AMEND, fallback=1) == 2
    assert amendment_no("FIRST AMENDMENT TO AGREEMENT AND PLAN OF MERGER", fallback=3) == 1
    assert amendment_no("AMENDMENT TO MERGER AGREEMENT", fallback=3) == 3
