from evals.items import build_items
from evals.maud_labels import LabelRow

TEXT = (
    "Section 2.6 Conversion of Securities. Each Company Share shall be converted into the right to receive cash.\n\n"
    "Section 7.2 Conditions. The Company shall have performed in all material respects its covenants hereunder.\n"
)
EX_26 = "Section 2.6 Conversion of Securities. Each Company Share shall be converted into the right to receive cash. (Page 9)"
EX_72 = "Section 7.2 Conditions. The Company shall have performed in all material respects its covenants hereunder. (Page 80)"


def row(contract, text, text_type, question, category="General Information"):
    return LabelRow(contract, text, question, "<NONE>", "answer", text_type, category)


def test_one_item_per_contract_and_text_type_with_combined_query():
    rows = [
        row("contract_1", EX_26, "Type of Consideration", "Type of Consideration-Answer"),
        row("contract_1", EX_26, "Type of Consideration", "Stock Deal-Answer"),
        row("contract_1", EX_72, "Compliance with Covenant Closing Condition", "Compliance-Answer", "Conditions to Closing"),
    ]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert [i.item_id for i in items] == [
        "contract_1|Compliance with Covenant Closing Condition", "contract_1|Type of Consideration"]
    toc = items[1]
    assert toc.query == "Type of Consideration. Stock Deal"
    assert len(toc.gold) == 1
    s, e = toc.gold[0]
    assert TEXT[s:e].startswith("Section 2.6") and TEXT[s:e].endswith("receive cash.")
    assert report["items"] == 2 and report["items_scored"] == 2 and report["pieces_exact"] == 2


def test_identical_excerpts_give_one_gold_span():
    rows = [row("contract_1", EX_26, "Type of Consideration", q) for q in ("A-Answer", "B-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert len(items[0].gold) == 1 and report["pieces"] == 1


def test_unalignable_excerpt_excludes_the_item_and_is_counted():
    bad = "Each holder of Company Warrants shall receive the Black-Scholes value of such warrant in cash at closing."
    rows = [row("contract_1", bad, "Warrants", "Warrants-Answer"),
            row("contract_1", EX_26, "Type of Consideration", "Type of Consideration-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert [i.text_type for i in items] == ["Type of Consideration"]
    assert report["items"] == 2 and report["items_scored"] == 1 and report["items_no_gold"] == 1
    assert report["pieces_unaligned"] == 1


def test_contract_without_a_file_is_counted_not_raised():
    rows = [row("contract_404", EX_26, "Type of Consideration", "Type of Consideration-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert items == []
    assert report["items_missing_contract"] == 1 and report["items_scored"] == 0


def test_overlapping_and_touching_gold_spans_are_merged():
    first = "Section 2.6 Conversion of Securities. Each Company Share shall be converted"
    overlapping = "Each Company Share shall be converted into the right to receive cash."
    rows = [row("contract_1", first + " (Page 9)", "Type of Consideration", "A-Answer"),
            row("contract_1", overlapping + " (Page 9)", "Type of Consideration", "B-Answer")]
    items, report = build_items(rows, {"contract_1": TEXT})
    assert report["pieces_exact"] == 2
    [(s, e)] = items[0].gold
    assert TEXT[s:e] == EX_26[: -len(" (Page 9)")]


def test_separate_gold_spans_stay_separate():
    rows = [row("contract_1", EX_26 + " <omitted> " + EX_72, "Mixed", "Mixed-Answer")]
    items, _ = build_items(rows, {"contract_1": TEXT})
    assert len(items[0].gold) == 2


def test_query_strips_every_answer_suffix_variant():
    questions = ["Relational language (MAE carveout)-Answer (Y/N)", "Knowledge Definition-Answer (Y/",
                 "Bringdown Standard Answer", "COR standard-answer", "Knowledge requirement - answer"]
    rows = [row("contract_1", EX_26, "Type of Consideration", q) for q in questions]
    items, _ = build_items(rows, {"contract_1": TEXT})
    assert items[0].query == ("Type of Consideration. Bringdown Standard. COR standard. Knowledge Definition. "
                              "Knowledge requirement. Relational language (MAE carveout)")


def test_table_of_contents_matches_are_skipped_and_counted():
    toc = "TABLE OF CONTENTS\n" + EX_26.replace(" (Page 9)", "") + "\n\n"
    text = toc + TEXT
    rows = [row("contract_1", EX_26, "Type of Consideration", "Type of Consideration-Answer")]
    items, report = build_items(rows, {"contract_1": text}, toc={"contract_1": [(0, len(toc))]})
    [(s, e)] = items[0].gold
    assert s == len(toc)
    assert report["pieces_toc_rescued"] == 1 and report["pieces_toc_only"] == 0
    assert report["pieces_ambiguous"] == 0


def test_ambiguous_and_short_pieces_are_counted():
    rows = [row("contract_1", EX_26 + " <omitted> Short bit. <omitted> " + EX_26, "Type of Consideration", "Q-Answer")]
    doubled = TEXT + "\n" + TEXT
    _, report = build_items(rows, {"contract_1": doubled})
    assert report["pieces_short"] == 1
    assert report["pieces_ambiguous"] == 2
