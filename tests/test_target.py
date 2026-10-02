from datetime import date

import pytest

from pipeline.target import deal_key, is_tech, norm, preamble, resolve

PRE = ("AGREEMENT AND PLAN OF MERGER\n\nThis AGREEMENT AND PLAN OF MERGER (this “Agreement”), dated as of "
       "March 1, 2016, is entered into by and among Big Buyer Corp., a Delaware corporation (“Parent”), "
       "Buyer Sub, Inc., a Delaware corporation and a wholly owned subsidiary of Parent (“Merger Sub”), "
       "and Acme Software, Inc., a Delaware corporation (the “Company”).\n")


def test_preamble_reads_target_acquirer_date():
    p = preamble(PRE)
    assert p.company == "Acme Software, Inc." and p.parent == "Big Buyer Corp."
    assert p.signed == date(2016, 3, 1) and p.amendment is False


def test_day_of_dates_and_amendments():
    text = ("AMENDMENT NO. 1 TO AGREEMENT AND PLAN OF MERGER\n\nThis Amendment is made this 5th day of June, 2017, "
            "by and among Parent Co, a Nevada corporation (“Parent”), and Target Labs LLC, a Delaware limited "
            "liability company (the “Company”).")
    p = preamble(text)
    assert p.amendment is True and p.signed == date(2017, 6, 5) and p.company == "Target Labs LLC"


def test_no_company_is_unparsed_not_guessed():
    p = preamble("ASSET PURCHASE AGREEMENT between Seller (“Seller”) and Buyer (“Buyer”), dated May 2, 2018.")
    assert p.company is None and deal_key(p) is None


def test_norm_drops_suffixes_and_punctuation():
    assert norm("Acme Software, Inc.") == norm("ACME SOFTWARE INC") == "acme software"
    assert norm("Smith & Jones Holdings, Ltd.") == "smith and jones"


def test_resolve_matches_only_the_filings_own_filers():
    names = ["Big Buyer Corp  (BBC)  (CIK 0000000001)", "ACME SOFTWARE INC  (ACME)  (CIK 0000012345)"]
    assert resolve("Acme Software, Inc.", ["0000000001", "0000012345"], names) == "0000012345"
    assert resolve("Other Target, Inc.", ["0000000001", "0000012345"], names) is None


@pytest.mark.parametrize("sic,ok", [("7372", True), (3576, True), ("3661", True), ("3679", True), ("3680", False),
                                    ("2834", False), ("", False), (None, False), ("n/a", False)])
def test_is_tech(sic, ok):
    assert is_tech(sic) is ok


def _p(text):
    return preamble(text)


def test_resolve_refuses_loose_matches():
    assert resolve("Acme", ["1"], ["Acme Software Inc  (CIK 1)"]) is None
    assert resolve("Oracle Financial Services", ["1"], ["ORACLE CORP (CIK 1)"]) is None
    names = ["Acme Software Holdings Co (CIK 1)", "Acme Software Labs Inc (CIK 2)"]
    assert resolve("Acme Software", ["1", "2"], names) is None
    with pytest.raises(ValueError):
        resolve("Acme Software", ["1"], names)


def test_signing_date_prefers_dated_as_of_and_ignores_case():
    t = ("This Agreement, together with the Voting Agreement dated May 2, 2010 and others, dated as of "
         "March 1, 2016, by and among Big Co, a Delaware corporation (“Parent”), and Acme Inc., a Delaware "
         "corporation (the “Company”).")
    assert _p(t).signed == date(2016, 3, 1)
    assert _p("AGREEMENT DATED AS OF MARCH 1, 2016").signed == date(2016, 3, 1)


def test_party_names_do_not_swallow_prose():
    p = _p('May 2, 2010. Big Co, a Delaware corporation (“Parent”), and Acme Inc., a Delaware corporation '
           '(the “Company”).')
    assert p.parent == "Big Co"
    p = _p('THIS AGREEMENT, DATED AS OF MARCH 1, 2016, Big Co, a Delaware corporation (“Parent”), and '
           'Acme Inc., a Delaware corporation (the “Company”).')
    assert p.parent == "Big Co" and p.company == "Acme Inc."


def test_trim_keeps_names_with_numbers_and_abbreviations():
    from pipeline.target import _trim
    assert _trim("Company 2000 Ltd.") == "Company 2000 Ltd."
    assert _trim("Acme 2000, Inc.") == "Acme 2000, Inc."
    assert _trim("Foo Corp. Holdings") == "Foo Corp. Holdings"
    p = _p("by and among Company 2000 Ltd., a Delaware corporation (“Parent”), and Acme Inc., a Delaware "
           "corporation (the “Company”).")
    assert p.parent == "Company 2000 Ltd."


def test_a_long_cover_page_and_contents_do_not_hide_the_preamble():
    toc = "".join(f"Section {i // 10}.{i % 10} Heading Number {i} .......... {i}\n" for i in range(200))
    cover = "AGREEMENT AND PLAN OF MERGER\n\nby and among\n\nBig Buyer Corp.\n\nand Acme Software, Inc.\n\n" + toc
    assert len(cover) > 6000
    p = preamble(cover + "\n" + PRE)
    assert p.company == "Acme Software, Inc." and p.parent == "Big Buyer Corp." and p.signed == date(2016, 3, 1)


def test_the_role_may_be_followed_by_more_text_in_its_parenthesis():
    t = ("This AGREEMENT AND PLAN OF MERGER, dated as of March 1, 2016, by and among Big Buyer Corp., a Delaware "
         "corporation (“Parent”), and Acme Software, Inc., a Delaware corporation (the “Company” and, together "
         "with Parent and Merger Sub, the “Parties”).")
    p = preamble(t)
    assert p.company == "Acme Software, Inc." and p.parent == "Big Buyer Corp."


def test_a_trust_is_a_party():
    t = ("This AGREEMENT AND PLAN OF MERGER, dated as of March 1, 2016, by and among Big REIT Inc., a Maryland "
         "corporation (“Parent”), and Acme Realty Trust, a Maryland real estate investment trust (the “Company”).")
    p = preamble(t)
    assert p.company == "Acme Realty Trust" and p.parent == "Big REIT Inc."


def test_an_amended_and_restated_agreement_is_an_amendment():
    t = ("AMENDED AND RESTATED AGREEMENT AND PLAN OF MERGER\n\nThis Amended and Restated Agreement and Plan of "
         "Merger, dated as of March 1, 2016, by and among Big Buyer Corp., a Delaware corporation (“Parent”), and "
         "Acme Software, Inc., a Delaware corporation (the “Company”).")
    assert preamble(t).amendment is True


def test_the_signing_date_is_read_near_the_preamble_not_from_later_definitions():
    later = ("x " * 2000) + ("“Clean Team Agreement” means the amendment to the Confidentiality Agreement, dated as of "
                             "July 21, 2016, by and between Parent and the Company.")
    t = ("THIS AGREEMENT AND PLAN OF MERGER (this “Agreement”), dated March 1, 2016, is entered into by and among "
         "Big Buyer Corp., a Delaware corporation (“Parent”), and Acme Software, Inc., a Delaware corporation "
         "(the “Company”).\n" + later)
    assert preamble(t).signed == date(2016, 3, 1)


def test_restated_flag_marks_only_amended_and_restated():
    t = ("AMENDED AND RESTATED AGREEMENT AND PLAN OF MERGER\n\nThis Amended and Restated Agreement and Plan of Merger, "
         "dated as of May 1, 2016, by and among Big Buyer Corp. (\u201cParent\u201d), and Acme, Inc. (the \u201cCompany\u201d).")
    p = preamble(t)
    assert p.restated is True and p.amendment is True
