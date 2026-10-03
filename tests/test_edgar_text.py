from pipeline.edgar_text import is_merger_agreement, normalise_edgar, own_title
from pipeline.segment import segment


def test_split_headings_are_joined_and_segment():
    raw = ("TABLE OF CONTENTS\n\nSection 1.1\nThe Merger 2\n\nSection 1.2\nClosing 3\n\n"
           "ARTICLE I\n\nSection 1.1\nThe Merger. Merger Sub merges into the Company.\n\n"
           "Section 1.2\nClosing. The closing occurs on the Closing Date.\n")
    t = normalise_edgar(raw)
    assert "Section 1.1 The Merger." in t
    ids = [p.section_id for p in segment("c", t) if p.kind == "section"]
    assert ids == ["1.1", "1.2"]


def test_bare_numbered_headings_are_joined():
    t = normalise_edgar("3.17.\n\nIntellectual Property. The Company owns its IP.\n\n3.18.\n\nBrokers. None.\n")
    assert "3.17. Intellectual Property." in t and "3.18. Brokers." in t


def test_unicode_spaces_become_plain_spaces():
    assert normalise_edgar("Company\u202fOptions\u00a0vest") == "Company Options vest"
    for c in "\u00a0\u1680\u2000\u2005\u200a\u200b\u202f\u205f\u3000":
        assert normalise_edgar(f"a{c}b") == "a b", hex(ord(c))
    assert normalise_edgar("a\u200cb") == "a\u200cb"  # the class stops at the zero-width space


def test_running_lines_are_dropped_but_headings_and_body_kept():
    pages = "".join(f"Body text on page {i} of the agreement.\n[Signature Page to Agreement and Plan of Merger]\n"
                    for i in range(9))
    raw = pages + "Section 2.1 Effect. Each share converts.\n" * 9
    t = normalise_edgar(raw)
    assert "Signature Page" not in t
    assert t.count("Section 2.1 Effect.") == 9
    assert all(f"Body text on page {i} of the agreement." in t for i in range(9))


def test_own_title_and_merger_check():
    assert own_title("Exhibit 2.1\n\nAGREEMENT AND PLAN OF MERGER\n\nby and among …") == "agreement and plan of merger"
    assert is_merger_agreement("Exhibit 2.1\nAGREEMENT AND PLAN OF MERGER\namong …")
    assert not is_merger_agreement("Exhibit 2.1 TERMINATION AGREEMENT Reference is made to the Agreement and Plan of Merger")
    assert not is_merger_agreement("VOTING AND SUPPORT AGREEMENT relating to the Agreement and Plan of Merger")


def test_explanatory_note_is_not_the_title():
    text = ("Exhibit 2.1\n\nEXPLANATORY NOTE TO THIS EXHIBIT\n\nThe representations in this Agreement and Plan of "
            "Merger were made for the parties' benefit.\n\nAGREEMENT AND PLAN OF MERGER\n\namong …")
    assert own_title(text) == "agreement and plan of merger"
    assert is_merger_agreement(text)
