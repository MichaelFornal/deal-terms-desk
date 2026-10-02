import json
from datetime import date
from urllib.parse import parse_qs, urlparse

from pipeline.m0 import (fee_amounts, lead_families, press_release_url, restates, stage_candidates, stage_deals,
                         stage_fetch, stage_measure, stage_press, stage_sample, stage_search)
from tests.fakes import fake_claude

PRE = ("AGREEMENT AND PLAN OF MERGER\n\nThis AGREEMENT AND PLAN OF MERGER, dated as of {d}, by and among "
       "{p}, a Delaware corporation (“Parent”), and {c}, a Delaware corporation (the “Company”).\n\n"
       "Section 2.3 Company Options. Each Company Option shall be cancelled and converted into cash.\n\n"
       "Section 8.3 Termination Fee. The Company shall pay Parent a termination fee of $45,000,000 in cash.\n")
DOCS = {
    # accession: (filer cik, filer display name, filer sic, text)
    "0000000001-16-000001": ("0000000011", "ACME SOFTWARE INC  (ACME)  (CIK 0000000011)", "7372",
                             PRE.format(d="March 1, 2016", p="Big Buyer Corp.", c="Acme Software, Inc.")),
    "0000000002-16-000002": ("0000000022", "BIG BUYER CORP  (BBC)  (CIK 0000000022)", "7372",
                             PRE.format(d="March 1, 2016", p="Big Buyer Corp.", c="Acme Software, Inc.")),
    "0000000003-16-000003": ("0000000033", "DRUGCO INC  (DRG)  (CIK 0000000033)", "2834",
                             PRE.format(d="March 9, 2016", p="Pharma Parent Inc.", c="DrugCo, Inc.")),
}
PRESS = b"<html><body><p>Acme to be acquired. A termination fee of $45 million may be payable.</p></body></html>"


def hit(adsh, cik, name, sic):
    return {"_id": f"{adsh}:ex21.htm", "_source": {"ciks": [cik], "display_names": [name], "file_type": "EX-2.1",
                                                   "file_date": "2016-03-02", "form": "8-K", "adsh": adsh, "sics": [sic]}}


class FakeEdgar:
    def __init__(self):
        self.urls = []

    def _route(self, url):
        u = urlparse(url)
        if u.hostname == "efts.sec.gov":
            q = parse_qs(u.query)
            in_march = q["startdt"][0] <= "2016-03-02" <= q["enddt"][0]
            hits = [hit(a, c, n, s) for a, (c, n, s, _) in DOCS.items()] if in_march and q["from"][0] == "0" else []
            return json.dumps({"hits": {"total": {"value": len(hits), "relation": "eq"}, "hits": hits}}).encode()
        if u.hostname == "data.sec.gov":
            cik = u.path.split("CIK")[1].split(".")[0]
            sic = next(s for c, _, s, _ in DOCS.values() if int(c) == int(cik))
            return json.dumps({"cik": cik, "name": "x", "sic": sic}).encode()
        if url.endswith("pr.htm"):
            return PRESS
        folder = u.path.split("/")[5]
        adsh = next(a for a in DOCS if a.replace("-", "") == folder)
        if url.endswith("ex21.htm"):
            # Real exhibits are HTML: a newline in the source is only whitespace, paragraphs are tags.
            paras = "".join(f"<p>{p}</p>" for p in DOCS[adsh][3].split("\n\n"))
            return f"<html><body>{paras}</body></html>".encode()
        if url.endswith("-index.htm"):
            return (b'<table><tr><td>1</td><td><a href="/Archives/edgar/data/11/x/ex21.htm">ex21.htm</a></td>'
                    b'<td>EX-2.1</td></tr><tr><td>2</td><td><a href="/Archives/edgar/data/11/x/pr.htm">pr.htm</a>'
                    b'</td><td>EX-99.1</td></tr></table>')
        return None

    def get(self, url):
        self.urls.append(url)
        return self._route(url)

    def get_json(self, url):
        body = self.get(url)
        return None if body is None else json.loads(body)


ANSWER = json.dumps({"equity_awards": {"present": True, "quote": "Each Company Option shall be cancelled"},
                     "termination_fee": {"present": True, "quote": "a termination fee of $45,000,000"},
                     "contingent_consideration": {"present": True, "quote": "an earn-out"}})


def test_the_stages_measure_a_small_fake_edgar(tmp_path):
    edgar = FakeEdgar()
    assert stage_search(edgar, tmp_path, today=date(2016, 4, 30))["ex21"] == 3
    assert stage_candidates(edgar, tmp_path)["candidates"] == 2
    assert stage_fetch(edgar, tmp_path)["fetched"] == 2
    deals = stage_deals(edgar, tmp_path)
    assert deals == {"deals": 1, "resolved": 1, "tech": 1}
    runner = fake_claude(ANSWER)
    assert stage_sample(tmp_path, runner=runner, model="m")["sample"] == 1
    assert stage_press(edgar, tmp_path)["restated"] == 1
    m = stage_measure(tmp_path)
    assert m["tech_deals"] == 1 and m["tech_multi_copy"] == 1
    assert m["family_present"] == {"equity_awards": 1, "termination_fee": 1, "contingent_consideration": 0}
    assert m["family_regex"]["contingent_consideration"] == 0
    assert m["passages_total"] >= 2
    assert len(runner.calls) == 1
    before = len(edgar.urls)
    stage_sample(tmp_path, runner=fake_claude("unused"), model="m")
    assert len(edgar.urls) == before


def test_a_family_with_no_hint_is_absent_without_a_call():
    runner = fake_claude(ANSWER)
    out = lead_families("Section 1.1 Closing. The closing occurs.\n", runner, "m")
    assert all(not v["present"] for v in out.values()) and runner.calls == []


def test_an_unverifiable_quote_does_not_count():
    runner = fake_claude(json.dumps({"termination_fee": {"present": True, "quote": "a fee of one billion"}}))
    out = lead_families("Section 8.3 Fees. The Company shall pay a termination fee of $5,000,000.\n", runner, "m")
    assert out["termination_fee"]["present"] is False and out["termination_fee"]["regex"] is True


def test_fee_amounts_and_restatement():
    fees = fee_amounts("“Termination Fee” means an amount equal to $1,250,000,000.")
    assert fees == {1_250_000_000.0}
    assert restates("a breakup fee of $1.25 billion", fees)
    assert not restates("a fee of $1.5 billion", fees)
    assert fee_amounts("the Termination Fee shall be reduced by $1.00") == set()


def test_press_release_url_reads_the_index_row_typed_ex_99_1():
    html = ('<tr><td><a href="/Archives/edgar/data/1/2/a.htm">a.htm</a></td><td>EX-2.1</td></tr>'
            '<tr><td><a href="/ix?doc=/Archives/edgar/data/1/2/pr.htm">pr.htm</a></td><td>EX-99.1</td></tr>')
    assert press_release_url(html) == "https://www.sec.gov/Archives/edgar/data/1/2/pr.htm"
    assert press_release_url("<tr><td>EX-2.1</td></tr>") is None
