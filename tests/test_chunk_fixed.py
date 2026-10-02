import sqlite3

from pipeline.chunk_fixed import fixed_chunks, fixed_size
from retrieval.index import build_index

TEXT = ("TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 Merger 6  Section 2.1 Stock 9  Section 2.2 Options 9  "
        "Section 3.1 Fees 12\n\n" + "Section 1.1 Closing. " + "The closing shall occur at the offices of counsel. " * 40)

TOC_DOC = (
    "TABLE OF CONTENTS  Section 1.1 Closing 6  Section 1.2 Merger 6  Section 2.1 Stock 9  Section 2.2 Options 9  "
    "Section 3.1 Fees 12\n\n"
    "Section 1.1 Closing. The closing occurs at the offices of counsel.\n\n"
    "Section 1.2 Merger. The merger becomes effective on the filing of the certificate.\n\n"
    "Section 2.1 Stock. Each share is converted into the right to receive cash.\n\n"
    "Section 2.2 Options. Each option is cancelled at the effective time.\n\n"
    "Section 3.1 Fees. Each party bears its own fees and expenses.\n"
)


def test_fixed_chunks_tile_the_text_and_break_at_whitespace():
    ps = fixed_chunks("c", TEXT, 300)
    assert ps[0].start == 0 and ps[-1].end == len(TEXT)
    assert all(a.end == b.start for a, b in zip(ps, ps[1:]))
    assert all(300 <= p.end - p.start <= 400 for p in ps[:-1])
    assert all(TEXT[p.end].isspace() for p in ps[:-1])
    assert all(p.section_id == "" and p.section_path == "" for p in ps)


def test_windows_inside_the_table_of_contents_are_marked_toc():
    ps = fixed_chunks("c", TOC_DOC, 100)
    assert ps[0].kind == "toc" and ps[-1].kind == "fixed"


def test_empty_text_has_no_chunks():
    assert fixed_chunks("c", "", 300) == []


def test_fixed_size_is_the_rounded_median_section_passage(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": "Section 1.1 A. " + "x " * 70 + "\n\nSection 1.2 B. " + "y " * 120 + "\n"})
    assert fixed_size(sqlite3.connect(db)) in (100, 200, 300)
