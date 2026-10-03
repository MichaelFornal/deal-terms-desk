import sqlite3

import pytest

from retrieval.deals import add_deals
from retrieval.index import build_index
from tests.test_amendments import AMEND

MAUD = ("AGREEMENT AND PLAN OF MERGER\n\nThis Agreement is made as of May 1, 2019, by and among Beta Holdings, Inc., "
        "a Delaware corporation (“Parent”), and Gamma Corp., a Delaware "
        "corporation (the “Company”).\n\nSection 1.1 Closing. The closing shall occur on the Closing Date.\n")
TECH = ("Section 1.4 Outside Date. The Outside Date is June 30 of the year.\n\n"
        "Section 7.3 Fees. The fee is as set out in the Company Disclosure Letter.\n")


def deals_inputs(tmp_path, amendment_text=AMEND):
    deals = [{"contract_id": "edgar_0001", "target": "Acme Software, Inc.", "parent": "Big Parent, Inc.",
              "target_cik": "0000000011", "signed": "2020-01-02", "url": "https://example.test/a", "split": "test",
              "aliases": ["acme software", "acme"],
              "amendments": [{"contract_id": "edgar_0002", "file_date": "2020-02-01", "url": "https://example.test/b"}]}]
    return deals, {"contract_1": MAUD, "edgar_0001": TECH}, {"edgar_0002": amendment_text}


def make_deals_db(tmp_path, amendment_text=AMEND):
    db = tmp_path / "deals.db"
    deals, texts, amends = deals_inputs(tmp_path, amendment_text)
    build_index(db, texts)
    return db, add_deals(db, deals, texts, amends)


@pytest.fixture
def deals_db(tmp_path):
    return make_deals_db(tmp_path)


def test_add_deals_links_explicit_amendments_and_tags_schedules(deals_db):
    db, summary = deals_db
    assert summary["deals"] == 2 and summary["maud_deals"] == 1
    assert summary["amendments"] == 1 and summary["amendments_linked"] == 1 and summary["amendments_unlinked"] == 0
    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT p.section_id, s.amendment_no FROM superseded s JOIN passages p USING(passage_id)"
                        " ORDER BY p.section_id").fetchall()
    assert rows == [("1.4", 2), ("7.3", 2)]
    tagged = conn.execute("SELECT p.section_id FROM passage_tags t JOIN passages p USING(passage_id)"
                          " WHERE t.tag = 'schedule_ref'").fetchall()
    assert tagged == [("7.3",)]
    assert ("acme software", "edgar_0001", "target") in conn.execute("SELECT alias, contract_id, kind FROM aliases").fetchall()
    assert ("gamma", "contract_1", "target") in conn.execute("SELECT alias, contract_id, kind FROM aliases").fetchall()


def test_an_amendment_with_no_explicit_form_is_counted_not_linked(tmp_path):
    db, summary = make_deals_db(tmp_path, amendment_text="Exhibit A to the Agreement is hereby replaced in its entirety.")
    assert summary["amendments_linked"] == 0 and summary["amendments_unlinked"] == 1
    assert sqlite3.connect(db).execute("SELECT COUNT(*) FROM superseded").fetchone()[0] == 0


def test_add_deals_is_idempotent(tmp_path):
    db, first = make_deals_db(tmp_path)
    assert add_deals(db, *deals_inputs(tmp_path)) == first
