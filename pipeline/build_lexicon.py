import json
import re
import sqlite3
from collections import Counter
from datetime import date
from pathlib import Path

from evals.bootstrap import split_of
from pipeline.claude import run_claude

LEXICON_MODEL = "claude-opus-5-5"
TOP_TERMS = 400
PROMPT = """You are building a search lexicon for merger agreements (agreements and plans of merger for acquisitions of US public companies).

People ask questions in everyday words. The agreements use their own vocabulary. Map everyday words and phrases to the words a merger agreement uses for the same thing.

Here are defined terms that occur in merger agreements, most common first:
{terms}

Write between 150 and 300 entries. Each key is an everyday word or short phrase that a non-lawyer, or a lawyer using shorthand or an abbreviation, might type. Each value is a list of one to six words or phrases that appear in merger agreements, preferring the defined terms above where they fit. Cover the whole of a typical merger agreement: the merger and its consideration, employee equity awards, representations and warranties, covenants, closing conditions, termination and termination fees, earn-outs and contingent value rights, remedies and definitions.

Output one JSON object and nothing else."""


def vocabulary(conn: sqlite3.Connection, top: int = TOP_TERMS) -> list[str]:
    """Defined terms by the number of tune-split agreements that define them."""
    df: Counter = Counter()
    for cid, term in conn.execute("SELECT DISTINCT contract_id, term FROM terms WHERE style IN ('means', 'paren')"):
        if split_of(cid) == "tune":
            df[term] += 1
    return [t for t, _ in sorted(df.items(), key=lambda x: (-x[1], x[0]))[:top]]


def prompt(vocab: list[str]) -> str:
    return PROMPT.format(terms="\n".join(vocab))


def parse(result_text: str, tune_texts: list[str]) -> dict[str, list[str]]:
    m = re.search(r"\{.*\}", result_text, re.S)
    raw = json.loads(m.group(0)) if m else {}
    corpus = "\n".join(tune_texts).lower()
    out: dict[str, list[str]] = {}
    for phrase, terms in raw.items():
        key = phrase.strip().lower()
        if len(key) < 3 or not isinstance(terms, list):
            continue
        kept = [t.strip() for t in terms if isinstance(t, str) and t.strip() and t.strip().lower() in corpus]
        if kept:
            out[key] = list(dict.fromkeys(kept))
    return dict(sorted(out.items()))


def build(conn: sqlite3.Connection, tune_texts: list[str], out_path: Path, runner=run_claude,
          model: str = LEXICON_MODEL) -> dict:
    vocab = vocabulary(conn)
    resp = runner(prompt(vocab), model) if vocab else {"result": "{}", "usage": {}}
    doc = {
        "_meta": {"built_by": "machine", "model": model, "built_on": date.today().isoformat(),
                  "source": "defined terms of the tune-split MAUD agreements", "saw_eval_queries": False,
                  "usage": resp.get("usage", {})},
        "entries": parse(resp["result"], tune_texts),
    }
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return doc
