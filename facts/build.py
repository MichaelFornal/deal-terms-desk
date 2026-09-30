import json
import sqlite3
from pathlib import Path

from evals.maud_labels import census
from facts.queries import CATEGORIES, QUERIES

# Wall-clock measurements differ between runs, so --check does not compare them.
UNSTABLE = {"r1_latency_ms_p50", "r1_latency_ms_p95"}


def build(db_path: Path, r1_path: Path, csv_paths: list[Path]) -> dict:
    conn = sqlite3.connect(db_path)
    r1 = json.loads(Path(r1_path).read_text(encoding="utf-8"))
    unnamed = sorted(set(r1.get("by_category", {})) - set(CATEGORIES.values()))
    if unnamed:
        raise ValueError(f"categories with no named facts (add them to facts.queries.CATEGORIES): {unnamed}")
    labels = census(csv_paths)
    return {name: QUERIES[name](conn, r1, labels) for name in sorted(QUERIES)}


def check(db_path: Path, r1_path: Path, facts_path: Path, csv_paths: list[Path]) -> list[str]:
    facts_path = Path(facts_path)
    if not facts_path.exists():
        return sorted(QUERIES)
    stored = json.loads(facts_path.read_text(encoding="utf-8"))
    fresh = build(db_path, r1_path, csv_paths)
    return sorted(n for n in fresh if n not in UNSTABLE and stored.get(n) != fresh[n])
