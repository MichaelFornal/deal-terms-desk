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
