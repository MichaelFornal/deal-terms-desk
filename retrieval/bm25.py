import re
import sqlite3
from dataclasses import dataclass

TOKEN = re.compile(r"[A-Za-z0-9]+")


@dataclass(frozen=True)
class Hit:
    passage_id: int
    contract_id: str
    start: int
    end: int
    score: float


def fts_query(q: str) -> str:
    """Every token quoted and OR-joined, so FTS5 operators in user text are inert."""
    tokens = [t for t in dict.fromkeys(TOKEN.findall(q.lower())) if len(t) > 1]
    return " OR ".join(f'"{t}"' for t in tokens)


FTS_TABLES = ("passages_fts", "passages_x_fts")


def _range(conn: sqlite3.Connection, contract_id: str) -> tuple[int, int] | None:
    row = conn.execute("SELECT first_passage_id, last_passage_id FROM contracts WHERE contract_id = ?",
                       (contract_id,)).fetchone()
    return (row[0], row[1]) if row and row[0] is not None else None


def search(conn: sqlite3.Connection, query: str, contract_id: str | None = None, k: int = 10,
           table: str = "passages_fts") -> list[Hit]:
    if table not in FTS_TABLES:
        raise ValueError(f"unknown FTS table {table!r}")
    match = fts_query(query)
    if not match:
        return []
    where, params = f"{table} MATCH ?", [match]
    if contract_id is not None:
        rng = _range(conn, contract_id)
        if rng is None:
            return []
        where += f" AND {table}.rowid BETWEEN ? AND ?"
        params += list(rng)
    sql = (f"SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, s.score FROM"
           f" (SELECT rowid AS rid, -bm25({table}) AS score FROM {table} WHERE {where}"
           f"  ORDER BY bm25({table}), rowid LIMIT ?) s JOIN passages p ON p.passage_id = s.rid"
           f" ORDER BY s.score DESC, p.passage_id")
    params.append(k)
    return [Hit(*row) for row in conn.execute(sql, params)]
