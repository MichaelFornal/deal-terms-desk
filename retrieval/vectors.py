import hashlib
import sqlite3
from pathlib import Path

import sqlite_vec

from retrieval.models import EMBED_DIM, MAX_TOKENS

CACHE_SCHEMA = ("CREATE TABLE IF NOT EXISTS emb(model TEXT NOT NULL, sha1 TEXT NOT NULL, n_tokens INTEGER NOT NULL,"
                " vec BLOB NOT NULL, PRIMARY KEY(model, sha1))")


def connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def sha1(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


def open_cache(path: Path) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    cache = sqlite3.connect(path)
    cache.execute(CACHE_SCHEMA)
    cache.commit()
    return cache


def indexed_passages(conn: sqlite3.Connection) -> list[tuple[int, str, str]]:
    return conn.execute(
        "SELECT p.passage_id, p.contract_id, f.text FROM passages p"
        " JOIN passages_fts f ON f.rowid = p.passage_id ORDER BY p.passage_id").fetchall()


def fill_cache(cache: sqlite3.Connection, embedder, texts: list[str], batch: int = 32, on_batch=None) -> dict:
    """Embed every text not yet cached for this model. Commits after each batch, so a kill loses one batch."""
    have = {r[0] for r in cache.execute("SELECT sha1 FROM emb WHERE model = ?", (embedder.name,))}
    distinct = {sha1(t): t for t in texts}
    todo = [t for h, t in distinct.items() if h not in have]
    for i in range(0, len(todo), batch):
        chunk = todo[i:i + batch]
        vecs = embedder.embed_passages(chunk)
        cache.executemany(
            "INSERT OR REPLACE INTO emb VALUES (?, ?, ?, ?)",
            [(embedder.name, sha1(t), embedder.count_tokens(t), sqlite_vec.serialize_float32(v))
             for t, v in zip(chunk, vecs)])
        cache.commit()
        if on_batch:
            on_batch(i + len(chunk), len(todo))
    return {"embedded": len(todo), "cached": len(distinct) - len(todo)}


def build_vectors(conn: sqlite3.Connection, cache: sqlite3.Connection, model: str, dim: int = EMBED_DIM) -> dict:
    """(Re)create passages_vec from the cache. Refuses, leaving it empty, if any passage is missing."""
    conn.execute("DROP TABLE IF EXISTS passages_vec")
    conn.execute(f"CREATE VIRTUAL TABLE passages_vec USING vec0(passage_id integer primary key,"
                 f" contract_id text partition key, embedding float[{dim}] distance_metric=cosine)")
    rows, missing, truncated = [], 0, 0
    for pid, cid, text in indexed_passages(conn):
        got = cache.execute("SELECT vec, n_tokens FROM emb WHERE model = ? AND sha1 = ?", (model, sha1(text))).fetchone()
        if got is None:
            missing += 1
            continue
        rows.append((pid, cid, got[0]))
        truncated += got[1] > MAX_TOKENS
    if missing:
        conn.commit()
        raise ValueError(f"{missing} passages have no cached embedding for {model}; run `dtd embed` to finish")
    conn.executemany("INSERT INTO passages_vec(passage_id, contract_id, embedding) VALUES (?, ?, ?)", rows)
    conn.execute("CREATE TABLE IF NOT EXISTS vec_meta(model TEXT NOT NULL, vectors INTEGER NOT NULL,"
                 " truncated INTEGER NOT NULL)")
    conn.execute("DELETE FROM vec_meta")
    conn.execute("INSERT INTO vec_meta VALUES (?, ?, ?)", (model, len(rows), truncated))
    conn.commit()
    return {"vectors": len(rows), "truncated": truncated}
