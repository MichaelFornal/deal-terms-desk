import hashlib
import json
import random
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap
from pipeline.claude import run_claude
from pipeline.ledger import Ledger
from pipeline.normalise import squash

DISPUTE_MODEL = "claude-opus-5-5"
SAMPLE = 150
MIN_QUOTE_CHARS = 10
MAX_GOLD_CHARS = 3000
PROMPT = """Lawyers marked the text under GOLD as the part of a merger agreement that answers the question. A search system returned the passage under RETRIEVED instead.

Question: {query}

GOLD:
{gold}

RETRIEVED:
{retrieved}

Does RETRIEVED also contain the clause that answers the question, so that a reader given only RETRIEVED would find the answer? Reply with one JSON object and nothing else: {{"answers": true or false, "quote": "the shortest verbatim quote from RETRIEVED that answers it, or an empty string"}}"""


def sample_misses(rows: dict[str, dict], n: int = SAMPLE, seed: int = 0, split: str = "report") -> list[dict]:
    pool = sorted((r for r in rows.values()
                   if r["split"] == split and r["mrr@10"] < 1.0 and r["top_passage_ids"]),
                  key=lambda r: r["item_id"])
    return sorted(random.Random(seed).sample(pool, min(n, len(pool))), key=lambda r: r["item_id"])


def verdict(result_text: str, retrieved: str) -> bool:
    m = re.search(r"\{.*\}", result_text, re.S)
    try:
        obj = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        return False
    quote = str(obj.get("quote", "")).strip()
    squashed = squash(quote)[0]
    return obj.get("answers") is True and len(squashed) >= MIN_QUOTE_CHARS and squashed in squash(retrieved)[0]


def judge(sample: list[dict], texts: dict[str, str], conn: sqlite3.Connection, cache_path: Path,
          runner=run_claude, model: str = DISPUTE_MODEL) -> list[dict]:
    ledger = Ledger(Path(cache_path), key="key")
    digest = hashlib.sha1(PROMPT.encode()).hexdigest()[:12]
    out = []
    for row in sample:
        pid = row["top_passage_ids"][0]
        key = f"{row['item_id']}|{pid}|{model}|{digest}"
        rec = ledger.get(key)
        if rec is None:
            text = texts[row["contract_id"]]
            s, e = conn.execute("SELECT start_char, end_char FROM passages WHERE passage_id = ?",
                                (pid,)).fetchone()
            retrieved = text[s:e]
            gold = "\n…\n".join(text[a:b] for a, b in row["gold"])[:MAX_GOLD_CHARS]
            resp = runner(PROMPT.format(query=row["query"], gold=gold, retrieved=retrieved), model)
            rec = {"key": key, "passage_id": pid, "model": model,
                   "item_id": row["item_id"], "contract_id": row["contract_id"], "category": row["category"],
                   "disputed": verdict(resp["result"], retrieved), "raw": resp["result"][:2000]}
            ledger.put(rec)
        out.append(rec)
    return out


def summarise(judged: list[dict], n_boot: int = 2000) -> dict:
    by_contract: dict[str, list[float]] = defaultdict(list)
    for r in judged:
        by_contract[r["contract_id"]].append(1.0 if r["disputed"] else 0.0)
    return cluster_bootstrap(by_contract, n_boot=n_boot)
