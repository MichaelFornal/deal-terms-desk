import json
import sqlite3
from pathlib import Path

from facts.queries import QUERIES

# Wall-clock measurements differ between runs, so --check does not compare them.
UNSTABLE = {"r1_latency_ms_p50", "r1_latency_ms_p95"}


def build(db_path: Path, r1_path: Path) -> dict:
    conn = sqlite3.connect(db_path)
    r1 = json.loads(Path(r1_path).read_text(encoding="utf-8"))
    return {name: QUERIES[name](conn, r1) for name in sorted(QUERIES)}


def check(db_path: Path, r1_path: Path, facts_path: Path) -> list[str]:
    facts_path = Path(facts_path)
    if not facts_path.exists():
        return sorted(QUERIES)
    stored = json.loads(facts_path.read_text(encoding="utf-8"))
    fresh = build(db_path, r1_path)
    return sorted(n for n in fresh if n not in UNSTABLE and stored.get(n) != fresh[n])
