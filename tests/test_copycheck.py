import json

from facts.copycheck import FLAGGED, check, render

FACTS = {
    "m4_thuman_haiku_report_accuracy": 0.6039,     # human-labelled (MAUD)
    "m4_tmachine_haiku_report_agree": 0.8125,      # machine-built (m4_tmachine_ prefix)
    "m5_model_cap_usd": 2.91,
    "m5_price_input_per_mtok": 1.0,
    "m5_bundle_passages": 88628,
    "m2_best_corpus_char_recall_at_1_pct": 12.5,   # a _pct key: already a percent
    "m5_price_checked": "2026-10-05",
    "m5_cap_trip_new_question_refused": True,      # a boolean must never match "1"
}


def one(text: str, facts: dict = FACTS):
    found = check(text, facts)
    assert len(found) == 1, found
    return found[0]


def test_an_exact_number_names_its_fact():
    f = one("Accuracy was 0.6039 on MAUD's questions.")
    assert (f.line, f.raw, f.status, f.keys) == (1, "0.6039", "fact", ("m4_thuman_haiku_report_accuracy",))


def test_rounded_numbers_and_percents_match_the_fact_they_round():
    assert one("about 0.60 of them").status == "rounded"
    f = one("about 60% of them")
    assert (f.raw, f.status, f.keys) == ("60%", "rounded", ("m4_thuman_haiku_report_accuracy",))
    assert one("12.5% of characters").keys == ("m2_best_corpus_char_recall_at_1_pct",)


def test_one_significant_digit_is_never_a_rounding():
    assert one("roughly 0.6 of them").status == "no fact"


def test_dollars_and_thousands_separators():
    assert one("a $2.91 model budget").keys == ("m5_model_cap_usd",)
    f = one("$1 per million input tokens")
    assert (f.raw, f.keys) == ("$1", ("m5_price_input_per_mtok",))  # never the boolean fact
    assert one("88,628 passages").keys == ("m5_bundle_passages",)


def test_dates_match_string_facts():
    f = one("prices checked on 2026-10-05")
    assert (f.raw, f.status, f.keys) == ("2026-10-05", "fact", ("m5_price_checked",))
    assert one("written on 2026-10-07").status == "no fact"


def test_a_number_no_fact_holds_is_flagged():
    f = one("it answers 17 questions")
    assert f.status == "no fact" and f.status in FLAGGED and f.keys == ()


def test_code_links_list_markers_and_names_are_not_numbers():
    text = ("1. Run `dtd copycheck README.md` first[^2]\n"
            "See [the report](docs/m5/REPORT.md#3) or https://deals.forn.al/v4/5.\n"
            "M5 ships R7n with bge-small-en-v1.5 and claude-haiku-4-5-20251001 in 2.0x mode.\n"
            "[7]: https://example.com/8\n"
            "```\nuv run pytest -q  # 870 tests\n```\n")
    assert check(text, FACTS) == []


def test_machine_built_numbers_need_the_label_nearby():
    assert one("The machine-built answers agreed 0.8125 of the time.").status == "fact"
    f = one("Answers agreed 0.8125 of the time.")
    assert (f.status, f.keys) == ("needs machine-built label", ("m4_tmachine_haiku_report_agree",))
    assert f.status in FLAGGED
    assert one("Answers agreed 81% of the time.").status == "needs machine-built label"  # rounded matches count
    assert one("Answers agreed\n0.8125 of the time (machine-built).\n").status == "fact"  # one paragraph, two lines


def test_a_heading_labels_its_section_only():
    assert one("## Tech deals (machine-built)\n\nAnswers agreed 0.8125 of the time.\n").status == "fact"
    text = "## Tech deals (machine-built)\n\nFine.\n\n## MAUD\n\nAnswers agreed 0.8125 of the time.\n"
    assert one(text).status == "needs machine-built label"


def test_the_lexicon_method_name_is_not_a_label():
    assert one("With a machine-built lexicon, answers agreed 0.8125.").status == "needs machine-built label"


def test_list_items_and_table_rows_stand_alone():
    assert one("- machine-built: yes\n- agreed 0.8125\n").status == "needs machine-built label"
    assert one("| tier | agree |\n|---|---|\n| machine-built | 0.8125 |\n").status == "fact"
    assert one("| machine-built | x |\n| human | 0.8125 |\n").status == "needs machine-built label"


def test_the_report_lists_every_number_and_counts_the_flags():
    out = render("README.md", check("Budget $2.91.\n\nIt answers 17 questions.\n", FACTS))
    assert out.splitlines() == ['README.md:1  "$2.91"  fact  m5_model_cap_usd',
                                'README.md:3  "17"  no fact',
                                "README.md: 2 numbers (1 exact, 0 rounded), 1 flagged"]


def test_the_summary_splits_exact_from_rounded_and_asks_for_a_check_of_each_rounded_line():
    out = render("post.md", check("Budget $2.91.\n\nAbout 60% of them.\n", FACTS)).splitlines()
    assert out[1] == 'post.md:3  "60%"  rounded  m4_thuman_haiku_report_accuracy'
    assert out[-1] == "post.md: 2 numbers (1 exact, 1 rounded: check each names the fact you mean), 0 flagged"
    one_line = render("one.md", check("Budget $2.91.", FACTS)).splitlines()[-1]
    assert one_line == "one.md: 1 number (1 exact, 0 rounded), 0 flagged"


def test_a_number_many_facts_hold_names_a_few_and_counts_the_rest():
    many = {f"m5_n{i}": 7 for i in range(6)}
    assert 'post.md:1  "7"  fact  m5_n0, m5_n1, m5_n2, m5_n3 +2 more' in render("post.md", check("7 of them", many))


def test_machine_built_keys_are_listed_first_so_more_never_hides_them():
    many = {**{f"m5_n{i}": 7 for i in range(6)}, "m3_tier_tau": 7}  # the machine-built key comes last in facts.json
    out = render("post.md", check("The machine-built tau was 7.", many))
    assert 'post.md:1  "7"  fact  m3_tier_tau [machine-built], m5_n0, m5_n1, m5_n2 +3 more' in out


def test_dtd_copycheck_reports_and_never_writes(tmp_path, monkeypatch, capsys):
    from pipeline import cli
    (tmp_path / "facts.json").write_text(json.dumps(FACTS))
    monkeypatch.setattr(cli, "FACTS", tmp_path / "facts.json")
    clean, flagged = tmp_path / "README.md", tmp_path / "post.md"
    clean.write_text("A $2.91 model budget.\n")
    flagged.write_text("It answers 17 questions.\n")
    before = {p: p.read_bytes() for p in (clean, flagged)}
    assert cli.entry(["copycheck", str(clean)]) == 0
    assert cli.entry(["copycheck", str(clean), str(flagged)]) == 1
    assert f'{flagged}:1  "17"  no fact' in capsys.readouterr().out
    assert {p: p.read_bytes() for p in (clean, flagged)} == before
    assert cli.entry(["copycheck", str(tmp_path / "missing.md")]) == 2
    monkeypatch.setattr(cli, "FACTS", tmp_path / "none.json")
    assert cli.entry(["copycheck", str(clean)]) == 2


def test_the_label_is_case_insensitive_but_the_lexicon_name_still_is_not_one():
    assert one("## Machine-built tech deals\n\nAnswers agreed 0.8125 of the time.\n").status == "fact"
    assert one("Machine-built answers agreed 0.8125 of the time.").status == "fact"
    assert one("With a Machine-Built Lexicon, answers agreed 0.8125.").status == "needs machine-built label"


def test_a_number_with_a_plain_match_is_not_flagged_and_tags_the_machine_keys():
    facts = {"m5_price_input_per_mtok": 1.0, "m3_tier_tau": 1.0}
    f = one("$1 per million input tokens", facts)
    assert f.status == "fact" and f.status not in FLAGGED
    assert f.keys == ("m5_price_input_per_mtok", "m3_tier_tau")
    assert "m3_tier_tau [machine-built], m5_price_input_per_mtok" in render("a.md", [f])


def test_an_unlabelled_number_that_also_matches_a_machine_built_fact_is_counted_not_flagged(tmp_path, monkeypatch):
    facts = {"m5_price_input_per_mtok": 1.0, "m3_tier_tau": 1.0, "m5_model_cap_usd": 2.91}
    out = render("a.md", check("$1 per million input tokens, under a $2.91 budget.", facts)).splitlines()
    assert out[0] == ('a.md:1  "$1"  fact  m3_tier_tau [machine-built], m5_price_input_per_mtok'
                      "  (no machine-built label nearby)")
    assert out[-1] == ("a.md: 2 numbers (2 exact, 0 rounded), 0 flagged;"
                       " 1 unlabelled number also matches a machine-built fact")
    labelled = render("a.md", check("$1 per million input tokens (the machine-built tau is 1 too).", facts))
    assert "label nearby" not in labelled and "also match" not in labelled
    two = render("a.md", check("$1 in, and 1 more.", facts)).splitlines()[-1]
    assert two.endswith("; 2 unlabelled numbers also match a machine-built fact")
    from pipeline import cli
    (tmp_path / "facts.json").write_text(json.dumps(facts))
    monkeypatch.setattr(cli, "FACTS", tmp_path / "facts.json")
    (tmp_path / "a.md").write_text("$1 per million input tokens.\n")
    assert cli.entry(["copycheck", str(tmp_path / "a.md")]) == 0  # reported, never a failure


def test_a_less_than_sign_is_not_an_html_tag():
    assert [f.raw for f in check("n < 5 and m > 3", {})] == ["5", "3"]


def test_markdown_underscore_emphasis_does_not_hide_a_number():
    assert [f.raw for f in check("_60%_ of them, __88,628__ passages, _2026-10-05_", FACTS)] == [
        "60%", "88,628", "2026-10-05"]  # names stay names: test_code_links_list_markers_and_names_are_not_numbers
