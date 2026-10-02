import json
import random
import re
from datetime import date
from pathlib import Path
from statistics import median

from pipeline.claude import run_claude
from pipeline.edgar_search import START, doc_url, index_url, is_ex21, months, search_window
from pipeline.html_text import to_text
from pipeline.ledger import Ledger
from pipeline.normalise import squash
from pipeline.segment import segment
from pipeline.target import deal_key, is_tech, norm, preamble, resolve

M0_DIR = Path("data/m0")
SAMPLE = 30
SEED = 0
FAMILIES = ("equity_awards", "termination_fee", "contingent_consideration")
LEAD_MODEL = "claude-opus-5-5"
MAX_HINT_PASSAGES = 12
MAX_PROMPT_CHARS = 40000
MIN_FEE = 100_000
FEE_TOLERANCE = 0.005
HINTS = {
    "equity_awards": re.compile(r"\b(?:Stock\s+Options?|Company\s+Options?|RSUs?|Restricted\s+Stock(?:\s+Units?)?|"
                                r"PSUs?|Equity\s+Awards?|Stock\s+Awards?)\b", re.I),
    "termination_fee": re.compile(r"\b(?:termination\s+fee|break-?up\s+fee)\b", re.I),
    "contingent_consideration": re.compile(r"\b(?:earn-?outs?|contingent\s+value\s+rights?|CVRs?|"
                                           r"milestone\s+payments?|contingent\s+consideration)\b", re.I),
}
PROMPT = """Below are passages from one merger agreement, separated by ---. For each topic, decide whether these passages contain a provision on it, and quote the shortest verbatim fragment (at most 300 characters) that shows it.

Topics:
- equity_awards: how employee stock options, restricted stock units or other equity awards are treated in the merger
- termination_fee: a fee one party must pay the other if the agreement is terminated
- contingent_consideration: an earn-out, contingent value right, milestone payment or other consideration paid later depending on future events

Reply with one JSON object and nothing else: {{"equity_awards": {{"present": true or false, "quote": "..."}}, "termination_fee": {{"present": true or false, "quote": "..."}}, "contingent_consideration": {{"present": true or false, "quote": "..."}}}}

Passages:
{excerpt}"""
FEE = re.compile(r"termination\s+fee[^;]{0,300}?\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion)?", re.I | re.S)
DOLLARS = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(million|billion)?", re.I)


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def stage_search(client, out: Path = M0_DIR, today: date | None = None) -> dict:
    rows: dict[tuple[str, str], dict] = {}
    for start, end in months(START, today or date.today()):
        for r in search_window(client, start, end):
            rows[(r["adsh"], r["filename"])] = r
    _write_jsonl(Path(out) / "search.jsonl", [rows[k] for k in sorted(rows)])
    return {"docs": len(rows), "ex21": sum(is_ex21(r["file_type"]) for r in rows.values())}


def _filer_sics(client, r: dict) -> list[str]:
    if r["sics"]:
        return [str(s) for s in r["sics"]]
    out = []
    for cik in r["ciks"]:
        sub = client.get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json")
        if sub:
            out.append(str(sub.get("sic", "")))
    return out


def stage_candidates(client, out: Path = M0_DIR) -> dict:
    ex21 = [r for r in _read_jsonl(Path(out) / "search.jsonl") if is_ex21(r["file_type"])]
    cands = [r for r in ex21 if any(is_tech(s) for s in _filer_sics(client, r))]
    _write_jsonl(Path(out) / "candidates.jsonl", cands)
    return {"ex21": len(ex21), "candidates": len(cands)}


def stage_fetch(client, out: Path = M0_DIR) -> dict:
    out = Path(out)
    (out / "text").mkdir(parents=True, exist_ok=True)
    docs = []
    for r in _read_jsonl(out / "candidates.jsonl"):
        raw = client.get(doc_url(r))
        if raw is None:
            docs.append({**r, "missing": True})
            continue
        text = to_text(raw, r["filename"])
        path = out / "text" / f"{r['adsh']}_{r['filename']}.txt"
        tmp = path.with_name(path.name + ".tmp")
        tmp.write_text(text, encoding="utf-8")
        tmp.replace(path)
        p = preamble(text)
        key = deal_key(p)
        docs.append({**r, "missing": False, "chars": len(text), "text": str(path), "company": p.company,
                     "parent": p.parent, "signed": p.signed.isoformat() if p.signed else None,
                     "amendment": p.amendment, "key": list(key) if key else None,
                     "target_cik": resolve(p.company, r["ciks"], r["names"]) if p.company else None})
    _write_jsonl(out / "docs.jsonl", docs)
    return {"candidates": len(docs), "fetched": sum(not d["missing"] for d in docs)}


def stage_deals(client, out: Path = M0_DIR) -> dict:
    docs = [d for d in _read_jsonl(Path(out) / "docs.jsonl") if not d["missing"]]
    groups: dict[tuple, list[dict]] = {}
    for d in docs:
        if d["key"] and not d["amendment"]:
            groups.setdefault(tuple(d["key"]), []).append(d)
    amended = [(norm(d["company"]), norm(d["parent"])) for d in docs
               if d["amendment"] and d["company"] and d["parent"]]
    rows = []
    for key, copies in sorted(groups.items()):
        cik = next((c["target_cik"] for c in copies if c["target_cik"]), None)
        sub = client.get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json") if cik else None
        sic = str(sub.get("sic", "")) if sub else None
        canonical = min(copies, key=lambda c: (c["file_date"], c["adsh"]))
        rows.append({"key": list(key), "signed": key[2], "target_cik": cik, "target_sic": sic,
                     "tech": bool(cik) and is_tech(sic), "copies": len(copies),
                     "amendments": sum(1 for a in amended if a == key[:2]),
                     "canonical": {k: canonical[k] for k in ("adsh", "filename", "ciks", "file_date", "text")}})
    _write_jsonl(Path(out) / "deals.jsonl", rows)
    return {"deals": len(rows), "resolved": sum(bool(r["target_cik"]) for r in rows),
            "tech": sum(r["tech"] for r in rows)}


def _gate_deals(out: Path) -> list[dict]:
    return [d for d in _read_jsonl(Path(out) / "deals.jsonl") if d["tech"] and d["signed"] >= START.isoformat()]


def hint_passages(text: str) -> dict[str, list[str]]:
    chunks = [text[p.start:p.end] for p in segment("m0", text)]
    return {f: [c for c in chunks if HINTS[f].search(c)][:MAX_HINT_PASSAGES] for f in FAMILIES}


def _json_object(s: str) -> dict:
    m = re.search(r"\{.*\}", s, re.S)
    try:
        return json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return {}


def lead_families(text: str, runner, model: str) -> dict:
    hints = hint_passages(text)
    out = {f: {"present": False, "regex": bool(hints[f]), "quote": ""} for f in FAMILIES}
    asked = [f for f in FAMILIES if hints[f]]
    if not asked:
        return out
    excerpt = "\n\n---\n\n".join(dict.fromkeys(c for f in asked for c in hints[f]))[:MAX_PROMPT_CHARS]
    answer = _json_object(runner(PROMPT.format(excerpt=excerpt), model)["result"])
    shown = squash(excerpt)[0]
    for f in asked:
        got = answer.get(f) if isinstance(answer.get(f), dict) else {}
        quote = str(got.get("quote", "")).strip()
        out[f] = {"present": got.get("present") is True and bool(quote) and squash(quote)[0] in shown,
                  "regex": True, "quote": quote[:300]}
    return out


def stage_sample(out: Path = M0_DIR, runner=run_claude, model: str = LEAD_MODEL) -> dict:
    deals = sorted(_gate_deals(out), key=lambda d: d["key"])
    picked = random.Random(SEED).sample(deals, min(SAMPLE, len(deals)))
    ledger = Ledger(Path(out) / "sample_ledger.jsonl", key="adsh")
    rows = []
    for d in sorted(picked, key=lambda d: d["key"]):
        adsh = d["canonical"]["adsh"]
        rec = ledger.get(adsh)
        if rec is None:
            text = Path(d["canonical"]["text"]).read_text(encoding="utf-8")
            rec = {"adsh": adsh, "model": model, **lead_families(text, runner, model)}
            ledger.put(rec)
        rows.append({**rec, "key": d["key"]})
    _write_jsonl(Path(out) / "sample.jsonl", rows)
    return {"sample": len(rows), "of": len(deals)}


def _amount(num: str, scale: str | None) -> float:
    return float(num.replace(",", "")) * {"million": 1e6, "billion": 1e9}.get((scale or "").lower(), 1.0)


def fee_amounts(text: str) -> set[float]:
    return {v for v in (_amount(*m.groups()) for m in FEE.finditer(text)) if v >= MIN_FEE}


def restates(press_text: str, fees: set[float]) -> bool:
    found = [_amount(*m.groups()) for m in DOLLARS.finditer(press_text)]
    return any(abs(v - f) <= FEE_TOLERANCE * f for v in found for f in fees)


def press_release_url(index_html: str) -> str | None:
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", index_html, re.S | re.I):
        if re.search(r">\s*EX-99\.1\s*<", tr, re.I):
            m = re.search(r'href="([^"]+)"', tr)
            if m:
                href = m.group(1).replace("/ix?doc=", "")
                return href if href.startswith("http") else "https://www.sec.gov" + href
    return None


def stage_press(client, out: Path = M0_DIR) -> dict:
    deals = {d["canonical"]["adsh"]: d for d in _read_jsonl(Path(out) / "deals.jsonl")}
    rows = []
    for s in _read_jsonl(Path(out) / "sample.jsonl"):
        c = deals[s["adsh"]]["canonical"]
        fees = fee_amounts(Path(c["text"]).read_text(encoding="utf-8"))
        index = client.get(index_url(c))
        url = press_release_url(index.decode("utf-8", errors="replace")) if index else None
        raw = client.get(url) if url else None
        release = to_text(raw, url) if raw else None
        rows.append({"adsh": s["adsh"], "fee": bool(fees), "release": release is not None,
                     "restated": bool(fees) and release is not None and restates(release, fees)})
    _write_jsonl(Path(out) / "press.jsonl", rows)
    return {"sample": len(rows), "restated": sum(r["restated"] for r in rows)}


def stage_measure(out: Path = M0_DIR) -> dict:
    out = Path(out)
    search = _read_jsonl(out / "search.jsonl")
    docs = _read_jsonl(out / "docs.jsonl")
    fetched = [d for d in docs if not d["missing"]]
    deals = _read_jsonl(out / "deals.jsonl")
    gate = _gate_deals(out)
    sample = _read_jsonl(out / "sample.jsonl")
    press = _read_jsonl(out / "press.jsonl")
    passages = [len(segment("m0", Path(d["canonical"]["text"]).read_text(encoding="utf-8"))) for d in gate]
    m = {
        "search_docs": len(search),
        "ex21_docs": sum(is_ex21(r["file_type"]) for r in search),
        "candidates": len(docs),
        "fetched": len(fetched),
        "missing": len(docs) - len(fetched),
        "company_parsed": sum(1 for d in fetched if d["company"]),
        "amendment_docs": sum(1 for d in fetched if d["amendment"]),
        "deals": len(deals),
        "deals_resolved": sum(1 for d in deals if d["target_cik"]),
        "tech_deals": len(gate),
        "tech_multi_copy": sum(1 for d in gate if d["copies"] > 1),
        "tech_amended": sum(1 for d in gate if d["amendments"] > 0),
        "sample": len(sample),
        "family_present": {f: sum(1 for r in sample if r[f]["present"]) for f in FAMILIES},
        "family_regex": {f: sum(1 for r in sample if r[f]["regex"]) for f in FAMILIES},
        "press_fee": sum(r["fee"] for r in press),
        "press_release": sum(r["release"] for r in press),
        "press_both": sum(1 for r in press if r["fee"] and r["release"]),
        "press_restated": sum(r["restated"] for r in press),
        "passages_total": sum(passages),
        "passages_mean": round(sum(passages) / len(passages), 1) if passages else 0.0,
        "passages_median": median(passages) if passages else 0,
        "lead_model": sample[0]["model"] if sample else LEAD_MODEL,
    }
    (out / "measure.json").write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    return m
