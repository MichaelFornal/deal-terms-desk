import json
import sqlite3
import threading
import time
from pathlib import Path

CACHEABLE = ("answered", "not_stated", "unfiled_schedule")  # what a model call produced; nothing momentary
SCHEMA = ("CREATE TABLE IF NOT EXISTS cache(model TEXT NOT NULL, prompt_sha TEXT NOT NULL, payload TEXT NOT NULL,"
          " created REAL NOT NULL, PRIMARY KEY(model, prompt_sha))")


def normalise_question(q: str) -> str:
    """Whitespace collapsed and trimmed. Nothing else: case and punctuation reach the prompt."""
    return " ".join(q.split())


class AnswerCache:
    """Answers by (model, prompt hash). The prompt carries the question, the retrieved passages and the template,
    so any change to the bundle, lexicon, settings or template misses on its own; the desk's model string also
    carries its thinking budget and output cap."""

    def __init__(self, db):
        db = Path(db)
        db.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(db, check_same_thread=False, isolation_level=None, timeout=5.0)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA busy_timeout=5000")
        self._conn.execute(SCHEMA)

    def get(self, model: str, prompt_sha: str) -> dict | None:
        with self._lock:
            row = self._conn.execute("SELECT payload FROM cache WHERE model = ? AND prompt_sha = ?",
                                     (model, prompt_sha)).fetchone()
        return json.loads(row[0]) if row else None

    def put(self, model: str, prompt_sha: str, payload: dict) -> None:
        if payload.get("state") not in CACHEABLE:
            return
        with self._lock:
            self._conn.execute("INSERT OR REPLACE INTO cache VALUES (?, ?, ?, ?)",
                               (model, prompt_sha, json.dumps(payload, sort_keys=True), time.time()))
