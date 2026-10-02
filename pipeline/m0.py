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
PASSAGE_SEP = "\n\n---\n\n"
MIN_FEE = 100_000
FEE_TOLERANCE = 0.005
HINTS = {
    "equity_awards": re.compile(r"\b(?:Stock\s+Options?|Company\s+Options?|RSUs?|Restricted\s+Stock(?:\s+Units?)?|"
                                r"PSUs?|Equity\s+Awards?|Stock\s+Awards?)\b", re.I),
    "termination_fee": re.compile(r"\b(?:termination\s+fee|break-?up\s+fee)\b", re.I),
    "contingent_consideration": re.compile(r"\b(?:earn-?outs?|contingent\s+value\s+rights?|CVRs?|"
                                           r"milestone\s+payments?|contingent\s+consideration)\b", re.I),
}
PROMPT = """Below are passages from one merger agreement, separated by ---. For each topic, decide whether these passages contain a provision on it, and quote a verbatim fragment of 40 to 300 characters that shows it.

Topics:
- equity_awards: how employee stock options, restricted stock units or other equity awards are treated in the merger
- termination_fee: a fee one party must pay the other if the agreement is terminated
- contingent_consideration: an earn-out, contingent value right, milestone payment or other consideration paid later depending on future events

Reply with one JSON object and nothing else: {{"equity_awards": {{"present": true or false, "quote": "..."}}, "termination_fee": {{"present": true or false, "quote": "..."}}, "contingent_consideration": {{"present": true or false, "quote": "..."}}}}

Passages:
{excerpt}"""
SCALE = r"(?:\s*(million|billion|mm|bn|m|b)\b)?"
FEE = re.compile(r"termination\s+fee[^;]{0,300}?\$\s?(\d[\d,]*(?:\.\d+)?)" + SCALE, re.I | re.S)
DOLLARS = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)" + SCALE, re.I)
SCALES = {"million": 1e6, "mm": 1e6, "m": 1e6, "billion": 1e9, "bn": 1e9, "b": 1e9}
QUOTE_MIN = 20
SNIPPET = 100
MERGER_HEAD = 1500
MERGER_TITLES = ("agreement and plan of merger", "plan and agreement of merger", "agreement of merger",
                 "plan of merger", "merger agreement")
_PUNCT = str.maketrans({"\u2018": "'", "\u2019": "'", "\u201c": '"', "\u201d": '"', "\u2013": "-", "\u2014": "-"})


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def _read_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]


def stage_search(client, out: Path = M0_DIR, today: date | None = None) -> dict:
    """`today` pins the search's end date; a rerun passes the one recorded in search_meta.json."""
    last = today or date.today()
    rows: dict[tuple[str, str], dict] = {}
    for start, end in months(START, last):
        for r in search_window(client, start, end):
            rows[(r["adsh"], r["filename"])] = r
    _write_jsonl(Path(out) / "search.jsonl", [rows[k] for k in sorted(rows)])
    meta = Path(out) / "search_meta.json"
    tmp = meta.with_name(meta.name + ".tmp")
    tmp.write_text(json.dumps({"end": last.isoformat()}, sort_keys=True), encoding="utf-8")
    tmp.replace(meta)
    return {"docs": len(rows), "ex21": sum(is_ex21(r["file_type"]) for r in rows.values()), "end": last.isoformat()}


def search_end(out: Path = M0_DIR) -> date | None:
    """The end date an earlier search recorded, so a rerun asks EDGAR the same windows."""
    meta = Path(out) / "search_meta.json"
    if not meta.exists():
        return None
    return date.fromisoformat(json.loads(meta.read_text(encoding="utf-8"))["end"])


def _filer_sics(client, r: dict) -> list[str]:
    if r["sics"] and len(r["sics"]) >= len(r["ciks"]):
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


def _is_merger(text: str) -> bool:
    head = " ".join(text[:MERGER_HEAD].split()).lower()
    return any(t in head for t in MERGER_TITLES)


def _fetch_one(client, out: Path, r: dict) -> dict:
    raw = client.get(doc_url(r))
    if raw is None:
        return {**r, "missing": True}
    text = to_text(raw, r["filename"])
    path = out / "text" / f"{r['adsh']}_{r['filename']}.txt"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)
    p = preamble(text)
    key = deal_key(p)
    row = {**r, "missing": False, "chars": len(text), "text": str(path), "company": p.company,
           "parent": p.parent, "signed": p.signed.isoformat() if p.signed else None,
           "amendment": p.amendment, "restated": p.restated, "key": list(key) if key else None, "not_merger": not _is_merger(text),
           "target_cik": None}
    if p.company:
        try:
            row["target_cik"] = resolve(p.company, r["ciks"], r["names"])
        except ValueError as e:  # the filing's filer lists disagree: keep the document, unresolved
            row["resolve_error"] = str(e)
    return row


def stage_fetch(client, out: Path = M0_DIR) -> dict:
    out = Path(out)
    (out / "text").mkdir(parents=True, exist_ok=True)
    docs = []
    for r in _read_jsonl(out / "candidates.jsonl"):
        try:
            docs.append(_fetch_one(client, out, r))
        except ValueError as e:
            docs.append({**r, "missing": True, "error": str(e)})
    _write_jsonl(out / "docs.jsonl", docs)
    return {"candidates": len(docs), "fetched": sum(not d["missing"] for d in docs),
            "errors": sum("error" in d for d in docs)}


def stage_deals(client, out: Path = M0_DIR) -> dict:
    docs = [d for d in _read_jsonl(Path(out) / "docs.jsonl") if not d["missing"] and not d["not_merger"]]
    groups: dict[tuple, list[dict]] = {}
    for d in docs:
        if d["key"] and not d["amendment"]:
            groups.setdefault(tuple(d["key"]), []).append(d)
    originals = {k[:2] for k in groups}
    orphans = []
    for d in docs:  # an amended and restated agreement whose original we never saw stands as its own deal
        if d["key"] and d["amendment"] and d.get("restated") and (norm(d["company"]), norm(d["parent"])) not in originals:
            groups.setdefault(tuple(d["key"]), []).append(d)
            orphans.append(d)
    orphan_keys = {tuple(d["key"]) for d in orphans}
    amended = [(norm(d["company"]), norm(d["parent"])) for d in docs
               if d["amendment"] and d["company"] and d["parent"] and not any(d is o for o in orphans)]
    rows = []
    for key, copies in sorted(groups.items()):
        cik = next((c["target_cik"] for c in copies if c["target_cik"]), None)
        conflict = len({c["target_cik"] for c in copies if c["target_cik"]}) > 1
        sub = client.get_json(f"https://data.sec.gov/submissions/CIK{int(cik):010d}.json") if cik else None
        sic = str(sub.get("sic", "")) if sub else None
        canonical = min(copies, key=lambda c: (c["file_date"], c["adsh"]))
        rows.append({"key": list(key), "signed": key[2], "target_cik": cik, "target_sic": sic,
                     "tech": bool(cik) and is_tech(sic), "copies": len(copies), "target_conflict": conflict,
                     "orphan_restated": key in orphan_keys,
                     "amendments": sum(1 for a in amended if a == key[:2]),
                     "canonical": {k: canonical[k] for k in ("adsh", "filename", "ciks", "file_date", "text")}})
    _write_jsonl(Path(out) / "deals.jsonl", rows)
    return {"deals": len(rows), "orphan_restated": sum(r["orphan_restated"] for r in rows), "resolved": sum(bool(r["target_cik"]) for r in rows),
            "tech": sum(r["tech"] for r in rows)}


def _gate_deals(out: Path) -> list[dict]:
    return [d for d in _read_jsonl(Path(out) / "deals.jsonl") if d["tech"] and d["signed"] >= START.isoformat()]


def _all_hints(text: str) -> dict[str, list[str]]:
    chunks = [text[p.start:p.end] for p in segment("m0", text)]
    return {f: [c for c in chunks if HINTS[f].search(c)] for f in FAMILIES}


def hint_passages(text: str) -> dict[str, list[str]]:
    return {f: v[:MAX_HINT_PASSAGES] for f, v in _all_hints(text).items()}


def _clean(s: str) -> str:
    return squash(s.translate(_PUNCT))[0]


def _json_object(s: str, keys: tuple = ()) -> dict:
    """The whole reply if it is a JSON object, else the first balanced object found by scanning that holds
    at least one of `keys` (a nested object inside a truncated reply never qualifies)."""
    try:
        obj = json.loads(s)
        if isinstance(obj, dict) and (not keys or any(k in obj for k in keys)):
            return obj
    except json.JSONDecodeError:
        pass
    dec = json.JSONDecoder()
    for i, ch in enumerate(s):
        if ch == "{":
            try:
                obj, _ = dec.raw_decode(s, i)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and (not keys or any(k in obj for k in keys)):
                return obj
    raise RuntimeError("lead-family reply had no parseable JSON object")


def _family_block(passages: list[str], cap: int, more: bool) -> tuple[str, bool]:
    parts, used, truncated = [], 0, more
    for c in passages:
        room = cap - used
        if len(c) > room:
            if room > 0:
                parts.append(c[:room])
            truncated = True
            break
        parts.append(c)
        used += len(c) + len(PASSAGE_SEP)
    return PASSAGE_SEP.join(parts), truncated


def lead_families(text: str, runner, model: str) -> dict:
    full = _all_hints(text)
    out = {f: {"present": False, "regex": bool(full[f]), "quote": "", "truncated": False} for f in FAMILIES}
    asked = [f for f in FAMILIES if full[f]]
    if not asked:
        return out
    cap = MAX_PROMPT_CHARS // len(asked)
    blocks, shown = {}, {}
    for f in asked:
        blocks[f], out[f]["truncated"] = _family_block(full[f][:MAX_HINT_PASSAGES], cap,
                                                       len(full[f]) > MAX_HINT_PASSAGES)
        shown[f] = _clean(blocks[f])
    excerpt = PASSAGE_SEP.join(blocks[f] for f in asked)
    answer = _json_object(runner(PROMPT.format(excerpt=excerpt), model)["result"], tuple(asked))
    for f in asked:
        got = answer.get(f) if isinstance(answer.get(f), dict) else {}
        quote = str(got.get("quote", "")).strip()
        q = _clean(quote)
        out[f].update(present=got.get("present") is True and len(q) >= QUOTE_MIN and q in shown[f],
                      quote=quote[:300])
    return out


def stage_sample(out: Path = M0_DIR, runner=run_claude, model: str = LEAD_MODEL) -> dict:
    deals = sorted(_gate_deals(out), key=lambda d: d["key"])
    picked = random.Random(SEED).sample(deals, min(SAMPLE, len(deals)))
    ledger = Ledger(Path(out) / "sample_ledger.jsonl", key="id")
    rows = []
    for d in sorted(picked, key=lambda d: d["key"]):
        adsh = d["canonical"]["adsh"]
        lid = f"{adsh}|{d['canonical']['filename']}|{model}"
        rec = ledger.get(lid)
        if rec is None:
            text = Path(d["canonical"]["text"]).read_text(encoding="utf-8")
            rec = {"id": lid, "adsh": adsh, "filename": d["canonical"]["filename"], "model": model,
                   **lead_families(text, runner, model)}
            ledger.put(rec)
        rows.append({**rec, "key": d["key"]})
    _write_jsonl(Path(out) / "sample.jsonl", rows)
    return {"sample": len(rows), "of": len(deals)}


def _amount(num: str, scale: str | None) -> float:
    return float(num.replace(",", "")) * SCALES.get((scale or "").lower(), 1.0)


def fee_amounts(text: str) -> set[float]:
    return {v for v in (_amount(*m.groups()) for m in FEE.finditer(text)) if v >= MIN_FEE}


def restatement(press_text: str, fees: set[float]) -> tuple[float, str] | None:
    for m in DOLLARS.finditer(press_text):
        v = _amount(*m.groups())
        if any(abs(v - f) <= FEE_TOLERANCE * f for f in fees):
            snip = press_text[max(0, m.start() - SNIPPET):m.end() + SNIPPET]
            return v, " ".join(snip.split())
    return None


def restates(press_text: str, fees: set[float]) -> bool:
    return restatement(press_text, fees) is not None


def press_release_url(index_html: str) -> str | None:
    found = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", index_html, re.S | re.I):
        t = re.search(r">\s*EX-99(\.\d+)?\s*<", tr, re.I)
        m = re.search(r'href="([^"]+)"', tr)
        if t and m:
            href = m.group(1).replace("/ix?doc=", "")
            found.append((t.group(1) not in (None, ".1"), href if href.startswith("http") else "https://www.sec.gov" + href))
    return min(found, key=lambda x: x[0])[1] if found else None


def stage_press(client, out: Path = M0_DIR) -> dict:
    deals = {d["canonical"]["adsh"]: d for d in _read_jsonl(Path(out) / "deals.jsonl")}
    rows = []
    for s in _read_jsonl(Path(out) / "sample.jsonl"):
        c = deals[s["adsh"]]["canonical"]
        fees = fee_amounts(Path(c["text"]).read_text(encoding="utf-8"))
        row = {"adsh": s["adsh"], "fee": bool(fees), "release": False, "restated": False,
               "matched_amount": None, "snippet": None, "unusable": None}
        try:
            index = client.get(index_url(c))
            url = press_release_url(index.decode("utf-8", errors="replace")) if index else None
            raw = client.get(url) if url else None
        except ValueError:  # an off-host or malformed link in the index: count it, do not stop the stage
            row["unusable"] = "bad-url"
            raw = None
        if raw and (raw[:4] == b"%PDF" or url.lower().endswith(".pdf")):
            row["unusable"] = "pdf"
        elif raw:
            release = to_text(raw, url)
            row["release"] = True
            hit = restatement(release, fees) if fees else None
            if hit:
                row.update(restated=True, matched_amount=hit[0], snippet=hit[1])
        rows.append(row)
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
        "ex2_bare_docs": sum(r["file_type"].strip().upper() == "EX-2" for r in search),
        "candidates": len(docs),
        "fetched": len(fetched),
        "missing": sum(1 for d in docs if d["missing"] and "error" not in d),
        "fetch_errors": sum(1 for d in docs if "error" in d),
        "resolve_errors": sum(1 for d in fetched if "resolve_error" in d),
        "not_merger": sum(1 for d in fetched if d["not_merger"]),
        "keyed": sum(1 for d in fetched if d["key"]),
        "company_parsed": sum(1 for d in fetched if d["company"]),
        "amendment_docs": sum(1 for d in fetched if d["amendment"]),
        "deals": len(deals),
        "orphan_restated": sum(1 for d in deals if d.get("orphan_restated")),
        "deals_resolved": sum(1 for d in deals if d["target_cik"]),
        "tech_deals": len(gate),
        "tech_targets": len({d["target_cik"] for d in gate}),
        "tech_multi_copy": sum(1 for d in gate if d["copies"] > 1),
        "tech_amended": sum(1 for d in gate if d["amendments"] > 0),
        "sample": len(sample),
        "family_present": {f: sum(1 for r in sample if r[f]["present"]) for f in FAMILIES},
        "family_regex": {f: sum(1 for r in sample if r[f]["regex"]) for f in FAMILIES},
        "family_truncated": {f: sum(1 for r in sample if r[f]["truncated"]) for f in FAMILIES},
        "press_unusable": sum(1 for r in press if r.get("unusable")),
        "press_fee": sum(r["fee"] for r in press),
        "press_release": sum(r["release"] for r in press),
        "press_both": sum(1 for r in press if r["fee"] and r["release"]),
        "press_restated": sum(r["restated"] for r in press),
        "passages_total": sum(passages),
        "passages_mean": round(sum(passages) / len(passages), 1) if passages else 0.0,
        "passages_median": median(passages) if passages else 0,
        "lead_model": sample[0]["model"] if sample else LEAD_MODEL,
    }
    path = out / "measure.json"
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(m, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)
    return m
