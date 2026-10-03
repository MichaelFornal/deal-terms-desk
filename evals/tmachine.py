import hashlib
import json
import threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from evals.bootstrap import split_of
from evals.items import Item, _merged
from pipeline.ledger import Ledger
from pipeline.m0 import CANDIDATE_SPECS, LEAD_TOPICS, _json_object
from pipeline.normalise import squash

FAMILIES = ("equity_awards", "termination_fee", "employee_benefits")
TOPICS = {"equity_awards": LEAD_TOPICS["equity_awards"], "termination_fee": LEAD_TOPICS["termination_fee"],
          "employee_benefits": next(sp.topic for sp in CANDIDATE_SPECS if sp.name == "employee_benefits")}
TEMPLATES = {"equity_awards": "What happens to {target} employees' stock options and RSUs in the merger?",
             "termination_fee": "How much does {target} have to pay if the merger agreement is terminated?",
             "employee_benefits": "Will {target} employees keep their pay and benefits after the merger?"}
BARE_TEMPLATES = {"equity_awards": "What happens to employees' stock options and RSUs in the merger?",
                  "termination_fee": "How much does the company have to pay if the merger agreement is terminated?",
                  "employee_benefits": "Will employees keep their pay and benefits after the merger?"}
PASSES = (("a", "claude-opus-5-5"), ("b", "claude-sonnet-5-5"))
MIN_SECTIONS = 10
CHUNK = 6000
STEP2_CAP = 60000
MAX_SECTIONS = 3
MIN_QUOTE = 20
INPUT_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")
FOLD = str.maketrans({chr(0x201C): '"', chr(0x201D): '"', chr(0x2018): "'", chr(0x2019): "'",
                      chr(0x2013): "-", chr(0x2014): "-"})
ELLIPSIS = ("...", chr(0x2026))

STEP1 = """Below is the outline of one merger agreement: one line per section, its id first. For each topic, list the ids of up to 3 sections most likely to contain the provision that governs it, best first. Use [] if no section fits.

Topics:
{topics}

Reply with one JSON object and nothing else, mapping each topic name to a list of ids, for example {example}

Outline:
{outline}"""

STEP2 = """Below are sections of one merger agreement, each headed by its id in square brackets. For each topic, decide whether these sections contain the provision that governs it. If they do, copy up to 3 short passages that state it, each one sentence or clause of 40 to 400 characters, exactly as written in the agreement, and answer the topic in one plain sentence.

Topics:
{topics}

Reply with one JSON object and nothing else, for example {example}

Sections:
{sections}"""


@dataclass(frozen=True)
class Outline:
    lines: tuple[str, ...]
    sections: dict
    fallback: bool


def outline(passages: list[tuple[str, str, int, int]], text: str) -> Outline:
    runs: list[list] = []
    for sid, title, s, e in passages:
        if not sid:
            continue
        if runs and runs[-1][0] == sid:
            runs[-1][3] = max(runs[-1][3], e)
        else:
            runs.append([sid, title, s, e])
    sections, lines, seen = {}, [], {}
    for sid, title, s, e in runs:
        seen[sid] = seen.get(sid, 0) + 1
        key = sid if seen[sid] == 1 else f"{sid}#{seen[sid]}"
        sections[key] = (s, e)
        lines.append(f"{key} {title}".strip())
    if len(sections) >= MIN_SECTIONS:
        return Outline(tuple(lines), sections, False)
    sections, lines = {}, []
    for i, s in enumerate(range(0, len(text), CHUNK), start=1):
        sections[f"C{i}"] = (s, min(len(text), s + CHUNK))
        lines.append(f"C{i}: " + " ".join(text[s:s + 300].split())[:100])
    return Outline(tuple(lines), sections, True)


def locate(quote: str, text: str, spans: list[tuple[int, int]]) -> list[tuple[int, int]]:
    pieces = [quote]
    for e in ELLIPSIS:
        pieces = [p for q in pieces for p in q.split(e)]
    out = []
    for piece in pieces:
        q = "".join(piece.translate(FOLD).split())
        if len(q) < MIN_QUOTE:
            continue
        for s, e in spans:
            sq, idx = squash(text[s:e].translate(FOLD))
            i = sq.find(q)
            if i >= 0:
                out.append((s + idx[i], s + idx[i + len(q) - 1] + 1))
                break
    return out


def _topics_block(topics: dict[str, str]) -> str:
    return "\n".join(f"- {t}: {d}" for t, d in topics.items())


def prompt_sha(prompt: str) -> str:
    return hashlib.sha1(prompt.encode("utf-8")).hexdigest()[:12]


def _ask(ledger, lock, key, prompt, model, runner) -> str:
    sha = prompt_sha(prompt)
    with lock:
        rec = ledger.get(key)
    if rec is not None and rec.get("prompt_sha", sha) != sha:
        rec = None  # the prompt changed since this reply was ledgered; a record without a hash is legacy, trusted
    if rec is None:
        resp = runner(prompt, model)
        usage = resp.get("usage", {})
        rec = {"key": key, "model": model, "prompt_sha": sha, "result": resp["result"],
               "input_tokens": sum(usage.get(k, 0) for k in INPUT_KEYS), "output_tokens": usage.get("output_tokens", 0)}
        with lock:
            ledger.put(rec)
    return rec["result"]


def _parse(reply: str, keys) -> dict | None:
    try:
        return _json_object(reply, tuple(keys))
    except RuntimeError:
        return None


def _norm_id(x) -> str:
    t = str(x).strip()
    for lead in ("Section ", "section ", "SECTION ", "\u00a7"):
        if t.startswith(lead):
            t = t[len(lead):].strip()
    t = t.split()[0] if t.split() else ""
    return t.rstrip(".:")


def label_contract(cid, text, ol: Outline, topics: dict[str, str], model, runner, ledger, pass_name, group=6,
                   lock=None) -> dict[str, dict]:
    lock = lock or threading.Lock()
    base = f"{pass_name}|{model}|{cid}"
    example1 = json.dumps({t: [] for t in topics})
    reply = _ask(ledger, lock, f"{base}|outline", STEP1.format(topics=_topics_block(topics), example=example1,
                                                              outline="\n".join(ol.lines)), model, runner)
    picked = _parse(reply, topics)
    out = {t: {"found": False, "sections": [], "spans": [], "answer": "", "unlocated": 0, "truncated": False,
               "split": False, "error": picked is None} for t in topics}
    if picked is None:
        return out
    for t in topics:
        out[t]["unmatched"] = 0
        raw = picked.get(t)
        if not isinstance(raw, list):
            out[t]["error"] = True  # the model left the topic out, or gave a non-list
            continue
        ids = list(dict.fromkeys(n for n in (_norm_id(x) for x in raw) if n))
        matched = [i for i in ids if i in ol.sections]
        out[t]["unmatched"] = len(ids) - len(matched)
        out[t]["sections"] = matched[:MAX_SECTIONS]
        if raw and not matched:
            out[t]["error"] = True  # it named sections, none of them exist
    names = list(topics)
    for g, start in enumerate(range(0, len(names), group)):
        chunk = names[start:start + group]
        shown_ids = _in_order({i for t in chunk for i in out[t]["sections"]}, ol)
        if not shown_ids:
            continue
        if sum(ol.sections[i][1] - ol.sections[i][0] for i in shown_ids) <= STEP2_CAP:
            calls = [(f"{base}|sections|{g}", chunk, shown_ids, False)]  # the key and prompt the cache already holds
        else:  # one call per topic rather than cutting the group's sections off at the cap
            calls = [(f"{base}|sections|{g}|{t}", [t], _in_order(set(out[t]["sections"]), ol), True)
                     for t in chunk if out[t]["sections"]]
        for key, asked, ids, split in calls:
            _step2(key, asked, ids, split, text, ol, topics, out, model, runner, ledger, lock)
    return out


def _in_order(ids, ol: Outline) -> list[str]:
    return sorted(ids, key=lambda i: ol.sections[i][0])


def _step2(key, chunk, shown_ids, split, text, ol, topics, out, model, runner, ledger, lock) -> None:
    parts, used, truncated, shown = [], 0, False, []
    for i in shown_ids:
        s, e = ol.sections[i]
        room = STEP2_CAP - used
        if room <= 0:
            truncated = True
            break
        if e - s > room:
            e, truncated = s + room, True
        parts.append(f"[{i}]\n{text[s:e]}")
        shown.append((s, e))
        used += e - s
    example2 = json.dumps({t: {"found": True, "quotes": ["..."], "answer": "..."} for t in chunk})
    prompt = STEP2.format(topics=_topics_block({t: topics[t] for t in chunk}), example=example2,
                          sections="\n\n".join(parts))
    got = _parse(_ask(ledger, lock, key, prompt, model, runner), chunk)
    for t in chunk:
        if out[t]["error"]:
            continue
        out[t]["truncated"], out[t]["split"] = truncated, split
        if got is None:
            out[t]["error"] = True
            continue
        if not isinstance(got.get(t), dict):
            if out[t]["sections"]:
                out[t]["error"] = True  # the model skipped a topic it was shown sections for
            continue
        r = got[t]
        quotes = [q for q in r.get("quotes", []) if isinstance(q, str)][:3]
        located = [locate(q, text, shown) for q in quotes]
        out[t].update(found=bool(r.get("found")), spans=[list(sp) for hit in located for sp in hit],
                      answer=str(r.get("answer", "")), unlocated=sum(1 for hit in located if not hit))


def status(a: dict, b: dict, section_at) -> str:
    if a.get("error") or b.get("error"):
        return "error"
    fa, fb = a["found"] and bool(a["spans"]), b["found"] and bool(b["spans"])
    if not a["found"] and not b["found"]:
        return "absent"
    if not (fa and fb):
        return "one_found"
    if any(s1 < e2 and s2 < e1 for s1, e1 in a["spans"] for s2, e2 in b["spans"]):
        return "kept"
    sa = {section_at(s) for s, _ in a["spans"]} - {""}
    sb = {section_at(s) for s, _ in b["spans"]} - {""}
    return "kept" if sa & sb else "disagree"


class _NeedsCall(Exception):
    pass


def _cached_only(prompt, model):
    raise _NeedsCall


def _passages(conn, cid) -> list[tuple[str, str, int, int]]:
    return conn.execute("SELECT section_id, section_title, start_char, end_char FROM passages"
                        " WHERE contract_id = ? AND kind != 'toc' ORDER BY start_char", (cid,)).fetchall()


def _section_at(passages):
    def at(pos: int) -> str:
        for sid, _, s, e in passages:
            if s <= pos < e:
                return sid
        return ""
    return at


STATUSES = ("kept", "absent", "disagree", "one_found", "error")


def label_all(conn, texts, contracts, topics, passes, runner, ledger_path, workers=4, max_new=None,
              topics_by_contract=None):
    tps = {cid: (topics_by_contract or {}).get(cid, topics) for cid, _ in contracts}
    ledger, lock = Ledger(Path(ledger_path), key="key"), threading.Lock()
    passages = {cid: _passages(conn, cid) for cid, _ in contracts}
    outlines = {cid: outline(passages[cid], texts[cid]) for cid, _ in contracts}
    calls: list[str] = []

    def counted(prompt, model):
        resp = runner(prompt, model)
        with lock:
            calls.append(model)
        return resp

    def run_one(cid, call):
        return {p: label_contract(cid, texts[cid], outlines[cid], tps[cid], m, call, ledger, p, lock=lock)
                for p, m in passes}

    def cached(cid):
        """The contract's labels if every call it needs is in the ledger, else None (and no call is made)."""
        try:
            return run_one(cid, _cached_only)
        except _NeedsCall:
            return None

    results = {cid: r for cid, _ in contracts if (r := cached(cid)) is not None}
    todo = [cid for cid, _ in contracts if cid not in results]
    if max_new is not None:
        todo = todo[:max_new]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, cid, counted): cid for cid in todo}
        try:
            for fut in as_completed(futures):
                results[futures[fut]] = fut.result()  # a failed call raises here; finished calls are already ledgered
        except BaseException:
            pool.shutdown(wait=True, cancel_futures=True)  # stop queued contracts; running ones finish
            raise
    (pa, _), (pb, _) = passes
    rows = []
    for cid, target in contracts:
        if cid not in results:
            continue
        at = _section_at(passages[cid])
        for t in tps[cid]:
            a, b = results[cid][pa][t], results[cid][pb][t]
            st = status(a, b, at)
            gold = [list(g) for g in _merged([tuple(s) for s in a["spans"] + b["spans"]])] if st == "kept" else []
            rows.append({"contract_id": cid, "family": t, "target": target, "split": split_of(cid), "status": st,
                         "gold": gold, "fallback": outlines[cid].fallback, "a": a, "b": b})
    done = {r["contract_id"] for r in rows}
    summary = {"contracts": len(contracts), "complete": len(done), "calls_made": len(calls),
               "fallback_contracts": sum(1 for cid in done if outlines[cid].fallback),
               "truncated_topics": sum(1 for r in rows if r["a"]["truncated"] or r["b"]["truncated"]),
               "split_groups": sum(1 for cid in done if any(v.get("split") for p in results[cid].values()
                                                             for v in p.values()))}
    summary |= {st: sum(1 for r in rows if r["status"] == st) for st in STATUSES}
    summary["by_family"] = {t: {st: sum(1 for r in rows if r["family"] == t and r["status"] == st) for st in STATUSES}
                            for t in dict.fromkeys(t for cid in done for t in tps[cid])}
    return rows, summary


def items_from_rows(rows: list[dict], bare: bool = False) -> list[Item]:
    """Kept rows as eval items; bare=True asks the same question without naming the company."""
    return [Item(f"{r['contract_id']}|{r['family']}", r["contract_id"], r["family"], r["family"],
                 BARE_TEMPLATES[r["family"]] if bare else TEMPLATES[r["family"]].format(target=r["target"]),
                 tuple(tuple(g) for g in r["gold"]))
            for r in rows if r["status"] == "kept"]


def scope_report(items: list[Item], resolver) -> dict:
    rows, by_split = [], defaultdict(Counter)
    for i in items:
        s = resolver.resolve(i.query)
        outcome = ("right" if s.contract_id == i.contract_id else "wrong" if s.contract_id
                   else "ambiguous" if s.candidates else "none")
        split = split_of(i.contract_id)
        rows.append({"item_id": i.item_id, "split": split, "outcome": outcome, "alias": s.alias,
                     "candidates": list(s.candidates)})
        by_split[split][outcome] += 1
    return {"items": rows, "by_split": {k: dict(v) for k, v in sorted(by_split.items())}}
