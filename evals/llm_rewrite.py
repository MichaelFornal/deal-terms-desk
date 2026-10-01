from pathlib import Path

from pipeline.claude import run_claude
from pipeline.ledger import Ledger

REWRITE_MODEL = "claude-haiku-4-5-20251001"
PROMPT = ("Rewrite this search query for finding the relevant clause in a merger agreement. Keep its meaning, "
          "and add the words a merger agreement would use for the same thing. Reply with the rewritten query "
          "only, on one line.\n\nQuery: {query}")
INPUT_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens")


def clean(result_text: str, query: str) -> str:
    for line in result_text.splitlines():
        line = line.strip().strip('"').strip()
        if line:
            return line
    return query


def rewrite_all(queries: list[str], cache_path: Path, runner=run_claude, model: str = REWRITE_MODEL) -> dict[str, dict]:
    ledger = Ledger(Path(cache_path), key="query")
    out = {}
    for q in dict.fromkeys(queries):
        rec = ledger.get(q)
        if rec is None:
            resp = runner(PROMPT.format(query=q), model)
            usage = resp.get("usage", {})
            rec = {"query": q, "rewrite": clean(resp["result"], q),
                   "input_tokens": sum(usage.get(k, 0) for k in INPUT_KEYS),
                   "output_tokens": usage.get("output_tokens", 0),
                   "api_ms": resp.get("duration_api_ms", 0), "usage": usage}
            ledger.put(rec)
        out[q] = rec
    return out
