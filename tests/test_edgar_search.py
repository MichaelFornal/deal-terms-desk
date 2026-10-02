from datetime import date
from urllib.parse import parse_qs, urlparse

import pytest

from pipeline.edgar_search import (CAP, PAGE, doc_url, index_url, is_ex21, months, row, search_url,
                                   search_window)


def hit(i, file_type="EX-2.1"):
    return {"_id": f"0001193125-16-{i:06d}:d{i}dex21.htm",
            "_source": {"ciks": ["0000012345"], "display_names": ["Acme Software Inc  (ACME)  (CIK 0000012345)"],
                        "file_type": file_type, "file_date": "2016-01-05", "form": "8-K",
                        "adsh": f"0001193125-16-{i:06d}", "sics": ["7372"]}}


class FakeClient:
    """Serves search pages from a function of (start, end) -> total hits in that window."""

    def __init__(self, total_of):
        self.total_of = total_of
        self.urls = []

    def get_json(self, url):
        self.urls.append(url)
        q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
        start, end, offset = date.fromisoformat(q["startdt"]), date.fromisoformat(q["enddt"]), int(q["from"])
        total = self.total_of(start, end)
        relation = "gte" if total >= CAP else "eq"
        n = min(PAGE, max(0, min(total, CAP) - offset))
        base = (start.toordinal() % 1000) * 100000
        return {"hits": {"total": {"value": min(total, CAP), "relation": relation},
                         "hits": [hit(base + offset + i) for i in range(n)]}}


def test_search_url_carries_phrase_form_window_and_offset():
    q = parse_qs(urlparse(search_url(date(2016, 1, 1), date(2016, 1, 31), 200)).query)
    assert q["q"] == ['"agreement and plan of merger"'] and q["forms"] == ["8-K"]
    assert q["startdt"] == ["2016-01-01"] and q["enddt"] == ["2016-01-31"] and q["from"] == ["200"]


def test_months_cover_the_range_without_gaps():
    ms = months(date(2015, 1, 1), date(2015, 3, 10))
    assert ms == [(date(2015, 1, 1), date(2015, 1, 31)), (date(2015, 2, 1), date(2015, 2, 28)),
                  (date(2015, 3, 1), date(2015, 3, 10))]


def test_a_window_is_paged_to_its_total():
    c = FakeClient(lambda s, e: 250)
    rows = search_window(c, date(2016, 1, 1), date(2016, 1, 31))
    assert len(rows) == 250 and len(c.urls) == 3


def test_a_window_at_the_cap_is_split_until_each_part_is_under_it():
    c = FakeClient(lambda s, e: 30 * ((e - s).days + 1) * (500 if (e - s).days > 20 else 1))
    rows = search_window(c, date(2016, 1, 1), date(2016, 1, 31))
    assert len(rows) == 30 * 31
    assert len(c.urls) > 1  # the month was split, not read as one capped window


def test_a_single_day_over_the_cap_raises_instead_of_truncating():
    with pytest.raises(ValueError, match="cap"):
        search_window(FakeClient(lambda s, e: CAP), date(2016, 1, 1), date(2016, 1, 1))


def test_row_and_urls():
    r = row(hit(7))
    assert r["adsh"] == "0001193125-16-000007" and r["filename"] == "d7dex21.htm" and r["sics"] == ["7372"]
    assert doc_url(r) == "https://www.sec.gov/Archives/edgar/data/12345/000119312516000007/d7dex21.htm"
    assert index_url(r) == "https://www.sec.gov/Archives/edgar/data/12345/000119312516000007/0001193125-16-000007-index.htm"


@pytest.mark.parametrize("t,ok", [("EX-2.1", True), ("ex-2.1", True), ("EX-2.01", True), ("EX-2.2", False),
                                  ("EX-99.1", False), ("", False)])
def test_is_ex21(t, ok):
    assert is_ex21(t) is ok


def test_a_short_later_page_raises_instead_of_returning_fewer_rows():
    class Short(FakeClient):
        def get_json(self, url):
            r = super().get_json(url)
            if "from=100" in url:
                r["hits"]["hits"] = r["hits"]["hits"][:-1]
            return r

    with pytest.raises(ValueError, match="expected 250"):
        search_window(Short(lambda s, e: 250), date(2016, 1, 1), date(2016, 1, 31))


def test_doc_url_without_ciks_raises_clearly():
    with pytest.raises(ValueError, match="no CIK"):
        doc_url({"adsh": "0001-16-000001", "filename": "a.htm", "ciks": []})
