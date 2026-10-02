import json
from datetime import date

import pytest
from urllib.parse import parse_qs, urlparse

from pipeline.m0 import (fee_amounts, restatement, lead_families, press_release_url, restates, stage_candidates, stage_deals,
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
    assert deals == {"deals": 1, "orphan_restated": 0, "resolved": 1, "tech": 1}
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
    again = fake_claude("unused")
    stage_sample(tmp_path, runner=again, model="m")
    assert len(edgar.urls) == before and again.calls == []


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


def _sec(n, body):
    return f"Section {n} Heading. {body}\n\n"


def test_each_family_gets_its_own_budget():
    text = "".join(_sec(f"2.{i}", "Each Company Option vests. " + "x " * 1500) for i in range(30))
    text += _sec("8.3", "The Company shall pay a termination fee of $5,000,000. " + "y " * 1500)
    text += _sec("3.1", "Part of the price is an earn-out payable later.")
    runner = fake_claude(json.dumps({"equity_awards": {"present": False, "quote": ""}}))
    out = lead_families(text, runner, "m")
    assert "earn-out payable later" in runner.calls[0][0]
    assert out["equity_awards"]["truncated"] is True and out["contingent_consideration"]["truncated"] is False


def test_an_unparseable_reply_raises_and_is_not_ledgered(tmp_path):
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    stage_deals(edgar, tmp_path)
    with pytest.raises(RuntimeError):
        stage_sample(tmp_path, runner=fake_claude("I cannot do that."), model="m")
    ledger = tmp_path / "sample_ledger.jsonl"
    assert not ledger.exists() or ledger.read_text() == ""
    assert stage_sample(tmp_path, runner=fake_claude(ANSWER), model="m")["sample"] == 1
    assert "0000000001-16-000001" in ledger.read_text()


TEXT = "Section 8.3 Fees. The Company shall pay Parent a termination fee of $5,000,000 \u2014 in cash.\n"


def _ask(quote, text=TEXT):
    r = fake_claude(json.dumps({"termination_fee": {"present": True, "quote": quote}}))
    return lead_families(text, r, "m")["termination_fee"]["present"]


def test_the_quote_gate_normalises_punctuation_and_needs_length():
    assert _ask("termination fee of $5,000,000 - in cash")
    assert _ask("Parent a \u2018termination fee\u2019 of $5,000,000".replace("\u2018", "").replace("\u2019", ""))
    assert not _ask("termination fee")
    curly = "Section 8.3 Fees. The Company\u2019s \u201ctermination fee\u201d of $5,000,000 is due.\n"
    assert _ask("The Company's \"termination fee\" of $5,000,000", curly)


def test_the_quote_must_come_from_its_own_family_passages():
    text = ("Section 2.1 Options. Each Company Option shall be cancelled for cash at closing.\n\n"
            "Section 8.3 Fees. The Company shall pay a termination fee of $5,000,000.\n")
    r = fake_claude(json.dumps({"termination_fee": {"present": True, "quote": "Each Company Option shall be cancelled"},
                                "equity_awards": {"present": True, "quote": "Each Company Option shall be cancelled"}}))
    out = lead_families(text, r, "m")
    assert out["equity_awards"]["present"] and not out["termination_fee"]["present"]


def test_fetch_gates_and_errors(tmp_path):
    class Edgar(FakeEdgar):
        def _route(self, url):
            if url.endswith("ex21.htm") and "000000000316" in url:
                return b"<html><body><p>Subsidiaries of Acme</p></body></html>"
            return super()._route(url)
    edgar = Edgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    rows = [json.loads(x) for x in (tmp_path / "search.jsonl").read_text().splitlines()]
    rows[0]["ciks"] = []
    rows[0]["sics"] = ["7372"]
    (tmp_path / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = stage_fetch(edgar, tmp_path)
    assert out["errors"] == 1
    stage_deals(edgar, tmp_path)
    m = stage_measure_for(tmp_path)
    assert m["fetch_errors"] == 1 and m["keyed"] == 1


def stage_measure_for(out):
    (out / "sample.jsonl").write_text("")
    (out / "press.jsonl").write_text("")
    return stage_measure(out)


def test_not_merger_is_marked_and_excluded(tmp_path):
    class Edgar(FakeEdgar):
        def _route(self, url):
            if url.endswith("ex21.htm") and "000000000316" in url:
                return b"<html><body><p>Subsidiaries of Acme</p></body></html>"
            return super()._route(url)
    edgar = Edgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    docs = [json.loads(x) for x in (tmp_path / "docs.jsonl").read_text().splitlines()]
    assert sum(d["not_merger"] for d in docs) == 0
    sub = {**docs[0], "adsh": "x", "not_merger": True}
    docs.append(sub)
    (tmp_path / "docs.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
    assert stage_deals(edgar, tmp_path)["deals"] == 1
    m = stage_measure_for(tmp_path)
    assert m["not_merger"] == 1 and m["tech_targets"] == 1


def test_amount_suffixes_and_snippet():
    assert fee_amounts("the Termination Fee is $45M") == {45e6}
    assert fee_amounts("the Termination Fee is $1.2 bn") == {1.2e9}
    assert fee_amounts("the Termination Fee is $45 mm") == {45e6}
    assert fee_amounts("the Termination Fee is $5,000,000 may be due") == {5e6}
    amount, snip = restatement("Intro text. A fee of $45M applies here.", {45e6})
    assert amount == 45e6 and "$45M" in snip


def test_press_index_accepts_ex_99_variants():
    html = '<tr><td><a href="/a/pr.htm">pr.htm</a></td><td>EX-99</td></tr>'
    assert press_release_url(html) == "https://www.sec.gov/a/pr.htm"
    html = ('<tr><td><a href="/a/o.htm">o</a></td><td>EX-99.2</td></tr>'
            '<tr><td><a href="/a/p.htm">p</a></td><td>EX-99.1</td></tr>')
    assert press_release_url(html) == "https://www.sec.gov/a/p.htm"


def test_a_pdf_release_is_unusable(tmp_path):
    class Edgar(FakeEdgar):
        def _route(self, url):
            return b"%PDF-1.4 stuff" if url.endswith("pr.htm") else super()._route(url)
    edgar = Edgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    stage_deals(edgar, tmp_path)
    stage_sample(tmp_path, runner=fake_claude(ANSWER), model="m")
    stage_press(edgar, tmp_path)
    row = json.loads((tmp_path / "press.jsonl").read_text().splitlines()[0])
    assert row["release"] is False and row["unusable"] == "pdf"


def test_short_sics_fall_back_to_submissions(tmp_path):
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    rows = [json.loads(x) for x in (tmp_path / "search.jsonl").read_text().splitlines()]
    for r in rows:
        r["ciks"], r["sics"] = ["0000000033", "0000000011"], ["2834"]
    (tmp_path / "search.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    assert stage_candidates(edgar, tmp_path)["candidates"] == 3
    assert any("data.sec.gov" in u for u in edgar.urls)


def test_merger_titles_and_new_measure_keys(tmp_path):
    from pipeline.m0 import _is_merger
    for t in ("PLAN AND AGREEMENT OF MERGER", "Agreement of  Merger", "PLAN OF MERGER", "This Merger Agreement is"):
        assert _is_merger(t + " by and among X")
    assert not _is_merger("STOCK PURCHASE AGREEMENT by and among X")
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    stage_deals(edgar, tmp_path)
    stage_sample(tmp_path, runner=fake_claude(ANSWER), model="m")
    stage_press(edgar, tmp_path)
    m = stage_measure(tmp_path)
    assert m["family_truncated"] == {"equity_awards": 0, "termination_fee": 0, "contingent_consideration": 0}
    assert m["press_unusable"] == 0


def test_a_resolve_error_keeps_the_document(tmp_path):
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    rows = [json.loads(x) for x in (tmp_path / "search.jsonl").read_text().splitlines()]
    rows[0]["names"] = []
    rows[1]["ciks"] = []
    (tmp_path / "candidates.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    out = stage_fetch(edgar, tmp_path)
    assert out["fetched"] == 2 and out["errors"] == 1
    docs = {d["adsh"]: d for d in map(json.loads, (tmp_path / "docs.jsonl").read_text().splitlines())}
    bad = docs[rows[0]["adsh"]]
    assert bad["missing"] is False and bad["key"] and bad["target_cik"] is None
    assert "1 CIKs but 0 names" in bad["resolve_error"] and "error" not in bad
    assert "error" in docs[rows[1]["adsh"]]
    stage_deals(edgar, tmp_path)
    m = stage_measure_for(tmp_path)
    assert m["resolve_errors"] == 1 and m["fetch_errors"] == 1


def test_the_prompt_asks_for_a_fragment_of_forty_to_three_hundred_characters():
    from pipeline.m0 import PROMPT, QUOTE_MIN
    assert "a verbatim fragment of 40 to 300 characters" in PROMPT and "shortest" not in PROMPT
    assert QUOTE_MIN == 20


def test_a_bad_press_url_is_unusable_not_fatal(tmp_path):
    class Edgar(FakeEdgar):
        def _route(self, url):
            if url.endswith("-index.htm"):
                return b'<tr><td><a href="https://example.com/pr.htm">pr.htm</a></td><td>EX-99.1</td></tr>'
            return super()._route(url)

        def get(self, url):
            if urlparse(url).hostname not in ("www.sec.gov", "efts.sec.gov", "data.sec.gov"):
                raise ValueError(f"host not allowed: {url}")
            return super().get(url)
    edgar = Edgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    stage_deals(edgar, tmp_path)
    stage_sample(tmp_path, runner=fake_claude(ANSWER), model="m")
    assert stage_press(edgar, tmp_path)["sample"] == 1
    row = json.loads((tmp_path / "press.jsonl").read_text().splitlines()[0])
    assert row["unusable"] == "bad-url" and row["release"] is False


def test_the_reply_parser_takes_the_whole_reply_then_the_first_balanced_object():
    from pipeline.m0 import _json_object
    assert _json_object('{"a": {"b": "}"}}') == {"a": {"b": "}"}}
    assert _json_object('Here: {"a": 1} and then {"b": 2}') == {"a": 1}
    assert _json_object('Sure. {"a": "x}"} done') == {"a": "x}"}
    with pytest.raises(RuntimeError):
        _json_object("no object {here")


def test_copies_resolving_to_different_targets_are_a_conflict(tmp_path):
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    assert stage_deals(edgar, tmp_path)["deals"] == 1
    row = json.loads((tmp_path / "deals.jsonl").read_text().splitlines()[0])
    assert row["target_conflict"] is False
    docs = [json.loads(x) for x in (tmp_path / "docs.jsonl").read_text().splitlines()]
    docs[1]["target_cik"] = "0000000022"
    (tmp_path / "docs.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
    stage_deals(edgar, tmp_path)
    row = json.loads((tmp_path / "deals.jsonl").read_text().splitlines()[0])
    assert row["target_conflict"] is True


def test_search_records_and_accepts_its_end_date(tmp_path):
    edgar = FakeEdgar()
    out = stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    assert out["end"] == "2016-04-30"
    assert json.loads((tmp_path / "search_meta.json").read_text()) == {"end": "2016-04-30"}
    q = [parse_qs(urlparse(u).query) for u in edgar.urls]
    assert max(x["enddt"][0] for x in q) == "2016-04-30"


def test_a_truncated_reply_does_not_yield_a_nested_object(tmp_path):
    from pipeline.m0 import _json_object
    trunc = '{"equity_awards": {"present": true, "quote": "x"}, "contingent_consideration": {"pres'
    with pytest.raises(RuntimeError):
        _json_object(trunc, keys=("equity_awards", "contingent_consideration"))
    with pytest.raises(RuntimeError):
        lead_families(PRE.format(d="March 1, 2016", p="P Corp.", c="C Inc."), fake_claude(trunc), "m")
    prose = 'Sure thing. {"termination_fee": {"present": false, "quote": ""}} done'
    assert _json_object(prose, keys=("termination_fee",)) == {"termination_fee": {"present": False, "quote": ""}}
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    stage_deals(edgar, tmp_path)
    with pytest.raises(RuntimeError):
        stage_sample(tmp_path, runner=fake_claude(trunc), model="m")
    ledger = tmp_path / "sample_ledger.jsonl"
    assert not ledger.exists() or ledger.read_text() == ""


def _edit_docs(tmp_path, edit):
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    docs = [json.loads(x) for x in (tmp_path / "docs.jsonl").read_text().splitlines()]
    edit(docs)
    (tmp_path / "docs.jsonl").write_text("".join(json.dumps(d) + "\n" for d in docs))
    return edgar, stage_deals(edgar, tmp_path)


def test_an_amended_and_restated_agreement_with_no_original_is_its_own_deal(tmp_path):
    def edit(docs):
        for d in docs:
            d["amendment"] = d["restated"] = True
    _, res = _edit_docs(tmp_path, edit)
    assert res["deals"] == 1 and res["orphan_restated"] == 1
    row = json.loads((tmp_path / "deals.jsonl").read_text().splitlines()[0])
    assert row["key"][0] == "acme software" and row["signed"] == "2016-03-01"
    assert row["amendments"] == 0 and row["copies"] == 2
    assert stage_measure_for(tmp_path)["orphan_restated"] == 1


def test_an_amended_and_restated_agreement_with_its_original_stays_an_amendment(tmp_path):
    def edit(docs):
        for i, d in enumerate(docs):
            d["restated"] = d["amendment"] = i == 1
            if i == 1:
                d["signed"] = "2016-06-01"
                d["key"] = [d["key"][0], d["key"][1], "2016-06-01"]
    _, res = _edit_docs(tmp_path, edit)
    assert res["deals"] == 1 and res["orphan_restated"] == 0
    row = json.loads((tmp_path / "deals.jsonl").read_text().splitlines()[0])
    assert row["amendments"] == 1 and row["copies"] == 1
    assert stage_measure_for(tmp_path)["orphan_restated"] == 0


def test_a_whole_reply_without_an_asked_key_raises_and_is_not_ledgered(tmp_path):
    from pipeline.m0 import _json_object
    text = PRE.format(d="March 1, 2016", p="P Corp.", c="C Inc.")
    for bad in ("{}", '{"note": "x"}'):
        with pytest.raises(RuntimeError):
            lead_families(text, fake_claude(bad), "m")
        with pytest.raises(RuntimeError):
            _json_object(bad, keys=("termination_fee",))
    assert _json_object('{"termination_fee": {"present": false}}', keys=("termination_fee",))
    edgar = FakeEdgar()
    stage_search(edgar, tmp_path, today=date(2016, 4, 30))
    stage_candidates(edgar, tmp_path)
    stage_fetch(edgar, tmp_path)
    stage_deals(edgar, tmp_path)
    for bad in ("{}", '{"note": "x"}'):
        with pytest.raises(RuntimeError):
            stage_sample(tmp_path, runner=fake_claude(bad), model="m")
    ledger = tmp_path / "sample_ledger.jsonl"
    assert not ledger.exists() or ledger.read_text() == ""


def test_measure_counts_bare_ex2_exhibits(tmp_path):
    rows = [{"file_type": t} for t in ("EX-2", " ex-2 ", "EX-2.1", "EX-2.2", "EX-21")]
    (tmp_path / "search.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    for n in ("docs", "deals", "sample", "press"):
        (tmp_path / f"{n}.jsonl").write_text("")
    assert stage_measure(tmp_path)["ex2_bare_docs"] == 2
