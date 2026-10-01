from pipeline.definitions import MAX_DEF_CHARS, definition_spans, term_pattern, terms_used
from pipeline.terms import extract_terms

HARD_WRAPPED = (
    "“Company Option” means each option to purchase\nshares of Company Common Stock granted under\na Company Plan.\n"
    "“Company Plan” means each equity plan.\n\n"
    "Section 2.1 Options. Each Company Option shall vest.\n"
)


def test_means_definition_spans_wrapped_lines_and_stops_at_the_next_definition():
    spans = definition_spans(HARD_WRAPPED, extract_terms(HARD_WRAPPED))
    s, e = spans["Company Option"]
    assert HARD_WRAPPED[s:e].endswith("a Company Plan.")
    s, e = spans["Company Plan"]
    assert HARD_WRAPPED[s:e] == "“Company Plan” means each equity plan."


def test_parenthetical_definition_is_its_sentence():
    text = "Recitals. Acme Inc is a Delaware corporation (the “Company”). Parent is a buyer."
    s, e = definition_spans(text, extract_terms(text))["Company"]
    assert text[s:e] == "Acme Inc is a Delaware corporation (the “Company”)."
    # Known limit, stated in the report: an abbreviation such as "Corp." ends the sentence early.


def test_means_is_preferred_over_a_parenthetical():
    text = "The buyer (“Parent”) agrees.\n\n“Parent” means Buyer Inc.\n"
    s, e = definition_spans(text, extract_terms(text))["Parent"]
    assert text[s:e].startswith("“Parent” means")


def test_long_definitions_are_capped():
    text = "“Material Adverse Effect” means " + "any change, " * 200 + "\n\n"
    s, e = definition_spans(text, extract_terms(text))["Material Adverse Effect"]
    assert e - s == MAX_DEF_CHARS


def test_longest_term_wins_and_terms_are_listed_once_in_order():
    pat = term_pattern(["Company", "Company Option", "Company Stock Option", "Parent"])
    got = terms_used("Each Company Stock Option and Company Option of the Company, per Parent and the Company.", pat)
    assert got == ["Company Stock Option", "Company Option", "Company", "Parent"]


def test_term_matching_is_case_sensitive_and_whole_word():
    pat = term_pattern(["Company"])
    assert terms_used("the company and Companywide policy", pat) == []
    assert term_pattern([]) is None


SAME_LINE = ("“Affiliate” means any Person controlling another Person. “SEC” means the Securities and Exchange "
             "Commission. “Securities Act” means the Securities Act of 1933.")


def test_same_line_definitions_end_at_the_next_opener():
    spans = definition_spans(SAME_LINE, extract_terms(SAME_LINE))
    s, e = spans["SEC"]
    assert SAME_LINE[s:e] == "“SEC” means the Securities and Exchange Commission."
    s, e = spans["Affiliate"]
    assert SAME_LINE[s:e] == "“Affiliate” means any Person controlling another Person."


def test_same_line_has_the_meaning_ends_the_previous_span():
    text = "“SEC” means the Commission. “Act” has the meaning set forth in Section 1."
    s, e = definition_spans(text, extract_terms(text))["SEC"]
    assert text[s:e] == "“SEC” means the Commission."
