from retrieval.lexicon import rewrite

LEX = {
    "break-up fee": ["Termination Fee", "Company Termination Fee"],
    "fee": ["Expenses"],
    "stock options": ["Company Options"],
}


def test_rewrite_appends_expansions_for_phrases_found():
    assert rewrite("What is the break-up fee?", LEX) == "What is the break-up fee? Termination Fee Company Termination Fee Expenses"


def test_rewrite_matches_whole_words_case_insensitively():
    assert rewrite("STOCK OPTIONS vesting", LEX) == "STOCK OPTIONS vesting Company Options"
    assert rewrite("feeling fine", LEX) == "feeling fine"


def test_rewrite_skips_terms_already_in_the_query_and_never_repeats():
    assert rewrite("termination fee and break-up fee", LEX) == \
        "termination fee and break-up fee Company Termination Fee Expenses"


def test_rewrite_with_no_match_or_empty_lexicon_is_the_identity():
    assert rewrite("Knowledge Definition", LEX) == "Knowledge Definition"
    assert rewrite("", LEX) == ""
    assert rewrite("break-up fee", {}) == "break-up fee"
