from pipeline.terms import extract_terms


def test_means_style_with_curly_quotes():
    text = "“Company Equity Awards” means the Company Options and the Company RSUs."
    terms = extract_terms(text)
    assert [(t.term, t.style) for t in terms] == [("Company Equity Awards", "means")]
    assert text[terms[0].start:terms[0].end].startswith("“Company Equity Awards” means")


def test_shall_mean_is_a_definition_and_has_the_meaning_is_a_cross_reference():
    text = '"Effective Time" shall mean the time of filing. "Parent Board" has the meaning set forth in Section 1.1.'
    assert [(t.term, t.style) for t in extract_terms(text)] == [("Effective Time", "means"), ("Parent Board", "xref")]


def test_shall_have_the_meaning_is_a_cross_reference():
    text = "“Superior Proposal” shall have the meaning set forth in Section 6.2(e)."
    assert [(t.term, t.style) for t in extract_terms(text)] == [("Superior Proposal", "xref")]


def test_parenthetical_definition():
    text = "equal to fourteen dollars ($14.00) (the “Per Share Merger Consideration”) payable to the holder"
    terms = extract_terms(text)
    assert [(t.term, t.style) for t in terms] == [("Per Share Merger Consideration", "paren")]


def test_each_an_parenthetical():
    text = "become an option (each, an “Assumed Stock Option”) to purchase shares"
    assert [t.term for t in extract_terms(text)] == ["Assumed Stock Option"]


def test_quoted_phrase_that_is_not_a_definition_is_ignored():
    text = "The word “including” is not limiting. He said “Yes” to the offer."
    assert extract_terms(text) == []


def test_results_are_sorted_by_position():
    text = "(the “B Term”) and later “A Term” means something."
    assert [t.term for t in extract_terms(text)] == ["B Term", "A Term"]


def test_non_definition_quote_before_real_definition():
    """Regression test: character class must exclude closing quote, not opening quote."""
    text = 'See “Yes” and “No” here, and Foo” means x.'
    terms = extract_terms(text)
    assert [t.term for t in terms] == []
