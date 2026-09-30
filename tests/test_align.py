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
