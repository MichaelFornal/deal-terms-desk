from evals.align import align_piece, pieces_of
from pipeline.normalise import squash

CONTRACT = (
    "Section 7.2   Conditions to Obligations of Parent and Merger Sub.\n\n"
    "The obligations of Parent and Merger Sub to consummate the Closing are subject to the\n"
    "satisfaction of the following conditions: (a) the representations shall be true; "
    "(b) Performance of Obligations of the Company. The Company shall have performed in all "
    "material respects its covenants and obligations under this Agreement.\n"
)
SQ, IDX = squash(CONTRACT)


def test_pieces_split_on_omitted_and_drop_page_markers_and_short_pieces():
    excerpt = ("Section 7.2 Conditions. <omitted> The Company shall have performed in all material respects "
               "its covenants and obligations under this Agreement. (Pages 81-82)")
    pieces = pieces_of(excerpt)
    assert len(pieces) == 1
    assert pieces[0].startswith("The Company shall have performed")
    assert "(Pages" not in pieces[0]


def test_single_page_marker_is_removed():
    assert "(Page" not in pieces_of("x" * 60 + " (Page 12)")[0]


def test_exact_alignment_ignores_whitespace_differences():
    piece = "The obligations of Parent and Merger Sub to consummate the  Closing are subject to the satisfaction of the following conditions"
    status, s, e = align_piece(piece, SQ, IDX)
    assert status == "exact"
    assert CONTRACT[s:e].startswith("The obligations of Parent")
    assert CONTRACT[s:e].endswith("following conditions")


def test_anchored_alignment_survives_a_changed_middle():
    piece = ("The obligations of Parent and Merger Sub to consummate the Closing are subject to the "
             "satisfaction of the following conditions: (a) the representations 76 shall be true; "
             "(b) Performance of Obligations of the Company. The Company shall have performed in all "
             "material respects its covenants and obligations under this Agreement.")
    status, s, e = align_piece(piece, SQ, IDX)
    assert status == "anchored"
    assert CONTRACT[s:e].startswith("The obligations of Parent")
    assert CONTRACT[s:e].endswith("under this Agreement.")


def test_text_not_in_the_contract_is_unaligned():
    piece = "Each holder of Company Warrants shall receive the Black-Scholes value of such warrant in cash."
    assert align_piece(piece, SQ, IDX) == ("none", -1, -1)


def test_anchors_too_far_apart_are_rejected():
    far = "A" * 40 + " filler " * 2000 + "B" * 40
    sq, idx = squash(far)
    piece = "A" * 40 + " x " + "B" * 40
    assert align_piece(piece, sq, idx)[0] == "none"


# --- occurrence choice, table of contents, truncation, short pieces ---

from evals.align import align_excerpt, short_pieces  # noqa: E402

HEADING = "Section 4.3 Authority; Non-Contravention; Governmental Consents"
TOC_CONTRACT = (
    "TABLE OF CONTENTS\n"
    f"{HEADING} .......... 12\n"
    "Section 4.4 Capitalization of the Company .......... 14\n\n"
    "ARTICLE IV\n\n"
    f"{HEADING}. The Company has all requisite corporate power and authority to enter into this Agreement.\n"
)
TOC_END = TOC_CONTRACT.index("ARTICLE IV")
BODY_AT = TOC_CONTRACT.index(HEADING, TOC_END)


def test_a_match_inside_the_table_of_contents_is_skipped_for_the_body():
    sq, idx = squash(TOC_CONTRACT)
    [got] = align_excerpt(HEADING, sq, idx, exclude=[(0, TOC_END)])
    assert got.status == "exact" and got.start == BODY_AT
    assert got.toc_rescued and not got.toc_only and got.n_candidates == 1


def test_without_exclusions_the_first_occurrence_is_kept():
    sq, idx = squash(TOC_CONTRACT)
    [got] = align_excerpt(HEADING, sq, idx)
    assert got.start == TOC_CONTRACT.index(HEADING) and got.n_candidates == 2 and not got.toc_rescued


def test_touching_table_of_contents_spans_are_excluded_as_one():
    sq, idx = squash(TOC_CONTRACT)
    split_at = TOC_CONTRACT.index("Section 4.4")
    [got] = align_excerpt(HEADING + " .......... 12 Section 4.4", sq, idx,
                          exclude=[(0, split_at), (split_at, TOC_END)])
    assert got.status == "none" and got.toc_only


def test_a_piece_found_only_in_the_table_of_contents_is_unaligned():
    sq, idx = squash(TOC_CONTRACT)
    [got] = align_excerpt("Section 4.4 Capitalization of the Company .......... 14", sq, idx, exclude=[(0, TOC_END)])
    assert (got.status, got.start, got.end) == ("none", -1, -1)
    assert got.toc_only and not got.toc_rescued


REPEATED = "The Company shall not take any action that would reasonably be expected to delay the Closing."
TWO_SECTIONS = (
    "Section 5.1 Conduct of Business. " + REPEATED + " Nothing herein limits the Company.\n\n"
    + "filler text about other matters. " * 40 + "\n\n"
    "Section 6.2 Efforts of the Parties. Each party shall use reasonable best efforts to obtain approvals. "
    + REPEATED + "\n"
)


def test_an_ambiguous_piece_takes_the_occurrence_nearest_the_excerpts_other_pieces():
    sq, idx = squash(TWO_SECTIONS)
    excerpt = ("Section 6.2 Efforts of the Parties. Each party shall use reasonable best efforts to obtain "
               "approvals. <omitted> " + REPEATED)
    unique, repeated = align_excerpt(excerpt, sq, idx)
    assert unique.n_candidates == 1
    assert repeated.n_candidates == 2
    assert repeated.start == TWO_SECTIONS.rindex(REPEATED)


def test_an_ambiguous_piece_alone_falls_back_to_the_first_occurrence():
    sq, idx = squash(TWO_SECTIONS)
    [got] = align_excerpt(REPEATED, sq, idx)
    assert got.n_candidates == 2 and got.start == TWO_SECTIONS.index(REPEATED)


def test_a_tail_phrase_that_recurs_inside_the_clause_does_not_truncate_the_span():
    tail = "in accordance with the terms of this Agreement."
    clause = (
        "Section 3.01 Effect on Capital Stock. Each share shall be converted " + tail
        + " Each option shall be cancelled and the holder paid in cash, without interest, " + tail
        + " Each warrant shall become exercisable for the merger consideration " + tail
    )
    text = "Preamble.\n\n" + clause + "\n\nSection 3.02 Exchange of Certificates. Parent shall deposit the fund.\n"
    sq, idx = squash(text)
    piece = clause.replace("paid in cash", "paid in immediately available cash")
    [got] = align_excerpt(piece, sq, idx)
    assert got.status == "anchored"
    assert text[got.start:got.end] == clause


def test_an_anchored_span_much_shorter_than_the_piece_is_rejected():
    head = "The Company shall pay the Termination Fee to Parent"
    tail = "by wire transfer of immediately available funds."
    text = head + " " + tail
    sq, idx = squash(text)
    piece = head + " within two business days after termination, " * 8 + tail
    [got] = align_excerpt(piece, sq, idx)
    assert got.status == "none"


def test_short_pieces_are_counted_not_silently_dropped():
    excerpt = "Section 7.2 Conditions. <omitted> " + "x" * 60 + " <omitted> (Page 3) <omitted> ok"
    assert len(pieces_of(excerpt)) == 1
    assert short_pieces(excerpt) == 2
