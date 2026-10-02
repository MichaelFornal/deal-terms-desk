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


def search(conn: sqlite3.Connection, query: str, contract_id: str | None = None, k: int = 10,
           table: str = "passages_fts") -> list[Hit]:
    if table not in FTS_TABLES:
        raise ValueError(f"unknown FTS table {table!r}")
    match = fts_query(query)
    if not match:
        return []
    sql = (
        f"SELECT p.passage_id, p.contract_id, p.start_char, p.end_char, -bm25({table})"
        f" FROM {table} JOIN passages p ON p.passage_id = {table}.rowid"
        f" WHERE {table} MATCH ?"
    )
    params: list = [match]
    if contract_id is not None:
        sql += " AND p.contract_id = ?"
        params.append(contract_id)
    sql += f" ORDER BY bm25({table}), p.passage_id LIMIT ?"
    params.append(k)
    return [Hit(*row) for row in conn.execute(sql, params)]
