import json
import sqlite3
from pathlib import Path

from retrieval.vectors import sha1


class CachedReranker:
    """Reranker scores keyed by model, query and the exact candidate texts; committed per query."""

    def __init__(self, inner, path: Path):
        self.inner = inner
        self.name = inner.name
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(path)
        self._db.execute("CREATE TABLE IF NOT EXISTS rr(model TEXT NOT NULL, key TEXT NOT NULL, scores TEXT NOT NULL,"
                         " ms REAL NOT NULL, PRIMARY KEY(model, key))")
        self._db.commit()

    def score(self, query: str, texts: list[str]) -> tuple[list[float], float]:
        if not texts:
            return [], 0.0
        key = sha1(query + "\x00" + "\x01".join(sha1(t) for t in texts))
        row = self._db.execute("SELECT scores, ms FROM rr WHERE model = ? AND key = ?", (self.name, key)).fetchone()
        if row:
            return json.loads(row[0]), row[1]
        scores, ms = self.inner.score(query, texts)
        self._db.execute("INSERT OR REPLACE INTO rr VALUES (?, ?, ?, ?)", (self.name, key, json.dumps(scores), ms))
        self._db.commit()
        return scores, ms
