"""M0 Task 2: a handful of recorded sec.gov responses, so every parser can be checked against reality.

Seven requests through SecClient (one process, spaced, cached, stop on refusal): two pages of one month's
full-text search, the same month split in two (to test that date ranges include both ends), the submissions
JSON of one EX-2.1 filer, that exhibit, and its filing index. Trimmed copies become test fixtures.
"""
import json
import urllib.request
from datetime import date
from pathlib import Path

from pipeline.edgar_search import doc_url, index_url, is_ex21, row, search_url
from pipeline.env import sec_contact
from pipeline.sec_client import SecClient, _NoRedirect

FIX = Path("tests/fixtures/sec")
JAN = (date(2016, 1, 1), date(2016, 1, 31))


def _logging_opener(log: list):
    """The client's own opener (no redirects, no proxies), recording response headers only."""
    base = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect()).open

    def opener(req, timeout=None):
        resp = base(req, timeout=timeout)
        log.append({"url": req.full_url, "status": getattr(resp, "status", None),
                    "content_type": resp.headers.get("Content-Type"),
                    "content_encoding": resp.headers.get("Content-Encoding")})
        return resp
    return opener


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    headers: list = []
    with SecClient(Path("data/sec"), sec_contact(), opener=_logging_opener(headers)) as c:
        p0 = c.get_json(search_url(*JAN, 0))
        p1 = c.get_json(search_url(*JAN, 100))
        a = c.get_json(search_url(date(2016, 1, 1), date(2016, 1, 30), 0))
        b = c.get_json(search_url(date(2016, 1, 31), date(2016, 1, 31), 0))
        hits = p0["hits"]["hits"] + p1["hits"]["hits"]
        ex21 = [row(h) for h in hits if is_ex21(h["_source"].get("file_type", ""))]
        first = max(ex21, key=lambda r: len(r["ciks"])) if ex21 else None
        sub = doc = idx = None
        if first:
            sub = c.get_json(f"https://data.sec.gov/submissions/CIK{int(first['ciks'][0]):010d}.json")
            doc = c.get(doc_url(first))
            idx = c.get(index_url(first))
        requests = c.requests
    t = lambda p: p["hits"]["total"]
    report = {
        "requests": requests,
        "jan_total": t(p0), "jan_1_30_total": t(a), "jan_31_total": t(b),
        "range_includes_both_ends": t(a)["value"] + t(b)["value"] == t(p0)["value"],
        "page0_len": len(p0["hits"]["hits"]), "page1_len": len(p1["hits"]["hits"]),
        "id_examples": [h["_id"] for h in hits[:3]],
        "source_keys": sorted(set().union(*(h["_source"].keys() for h in hits))) if hits else [],
        "file_types": sorted({h["_source"].get("file_type", "") for h in hits}),
        "ex21_hits": len(ex21),
        "ciks_names_sics_lengths": sorted({(len(h["_source"].get("ciks", [])), len(h["_source"].get("display_names", [])),
                                            len(h["_source"].get("sics", []))) for h in hits}),
        "chosen": first and {k: first[k] for k in ("adsh", "filename", "file_date", "ciks", "names", "sics")},
        "submissions_keys": sub and sorted(k for k in ("cik", "name", "sic", "sicDescription") if k in sub),
        "submissions_sic_type": sub and type(sub.get("sic")).__name__,
        "doc_bytes": doc and len(doc), "index_bytes": idx and len(idx),
        "index_mentions_ex99": idx and (b"EX-99" in idx),
        "headers": headers,
    }
    trimmed = {**p0, "hits": {**p0["hits"], "hits": p0["hits"]["hits"][:5]}}
    (FIX / "fts.json").write_text(json.dumps(trimmed, indent=1), encoding="utf-8")
    if sub:
        (FIX / "submissions.json").write_text(
            json.dumps({k: sub.get(k) for k in ("cik", "name", "sic", "sicDescription")}, indent=1), encoding="utf-8")
    if doc:
        (FIX / "ex21.htm").write_bytes(doc[:40000])
    if idx:
        (FIX / "index.htm").write_bytes(idx[:40000])
    (FIX / "probe_report.json").write_text(json.dumps(report, indent=1, default=str), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("requests", "jan_total", "range_includes_both_ends", "page0_len",
                                             "page1_len", "ex21_hits")}, default=str))


if __name__ == "__main__":
    main()
