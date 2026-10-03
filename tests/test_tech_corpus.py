import json

from pipeline.target import norm
from pipeline.tech_corpus import assemble

MERGER = "AGREEMENT AND PLAN OF MERGER\n\nby and among {p} and {t}, dated as of {d}.\n\nARTICLE I\n\nThe Merger. " + "The parties agree. " * 30
TERMINATION = "TERMINATION AGREEMENT\n\nThe parties terminate the merger agreement. " + "Release. " * 30


def make_m0(tmp_path):
    m0, out = tmp_path / "m0", tmp_path / "edgar"
    (m0 / "text").mkdir(parents=True)

    def text(name, body):
        p = m0 / "text" / name
        p.write_text(body, encoding="utf-8")
        return str(p)

    def deal(adsh, fn, target, parent, signed, tech, cik, body):
        return {"key": [norm(target), norm(parent), signed], "signed": signed, "tech": tech, "target_cik": cik,
                "canonical": {"adsh": adsh, "filename": fn, "ciks": [cik], "file_date": signed,
                              "text": text(f"{adsh}_{fn}.txt", body)}}

    def doc(adsh, fn, company, parent, cik, names, body, amendment=False, date="2020-01-02"):
        return {"adsh": adsh, "filename": fn, "company": company, "parent": parent, "amendment": amendment,
                "names": names, "ciks": [cik], "text": text(f"{adsh}_{fn}.txt", body), "missing": False,
                "file_date": date}

    acme_n = ["ACME SOFTWARE INC  (ACME)  (CIK 0000000011)"]
    beta_n = ["BETA SYSTEMS INC  (CIK 0000000022)"]
    deals = [
        deal("0000000001-20-000001", "ex21.htm", "Acme Software, Inc.", "Big Parent, Inc.", "2020-01-02", True,
             "0000000011", MERGER.format(p="Big Parent", t="Acme", d="January 2, 2020")),
        deal("0000000002-21-000002", "ex21.htm", "Beta Systems, Inc.", "Other Buyer, Inc.", "2021-03-04", True,
             "0000000022", MERGER.format(p="Other Buyer", t="Beta", d="March 4, 2021")),
        deal("0000000003-21-000003", "ex21.htm", "Gamma Foods, Inc.", "Food Buyer, Inc.", "2021-05-06", False,
             "0000000033", MERGER.format(p="Food Buyer", t="Gamma", d="May 6, 2021")),
        deal("0000000004-21-000004", "ex21.htm", "Delta Tech, Inc.", "Delta Buyer, Inc.", "2021-07-08", True,
             "0000000044", TERMINATION),
    ]
    docs = [
        doc("0000000001-20-000001", "ex21.htm", "Acme Software, Inc.", "Big Parent, Inc.", "0000000011", acme_n,
            MERGER.format(p="Big Parent", t="Acme", d="January 2, 2020")),
        doc("0000000002-21-000002", "ex21.htm", "Beta Systems, Inc.", "Other Buyer, Inc.", "0000000022", beta_n,
            MERGER.format(p="Other Buyer", t="Beta", d="March 4, 2021")),
        doc("0000000001-20-000009", "ex21a.htm", "Acme Software, Inc.", "Big Parent, Inc.", "0000000011", acme_n,
            "AMENDMENT NO. 1 TO AGREEMENT AND PLAN OF MERGER\n\nThe parties amend section 2. " + "x " * 30,
            amendment=True, date="2020-02-03"),
    ]
    for name, rows in (("deals", deals), ("docs", docs)):
        (m0 / f"{name}.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return m0, out


def test_assemble_keeps_tech_merger_agreements_and_links_amendments(tmp_path):
    m0, out = make_m0(tmp_path)
    summary = assemble(m0, out)
    assert summary == {"deals": 3, "kept": 2, "excluded_not_merger": 1, "amendments": 1, "aliases": 3}
    rows = [json.loads(l) for l in (out / "deals.jsonl").read_text().splitlines()]
    acme = next(r for r in rows if r["target"] == "Acme Software, Inc.")
    assert acme["aliases"] == ["acme software", "acme"]
    assert len(acme["amendments"]) == 1 and (out / "amendments" / f"{acme['amendments'][0]['contract_id']}.txt").exists()
    assert (out / "contracts" / f"{acme['contract_id']}.txt").read_text().startswith("AGREEMENT AND PLAN OF MERGER")
    assert acme["contract_id"].startswith("edgar_") and acme["contract_id"] > "contract_99"


def test_assemble_is_idempotent(tmp_path):
    m0, out = make_m0(tmp_path)
    first = assemble(m0, out)
    assert assemble(m0, out) == first
