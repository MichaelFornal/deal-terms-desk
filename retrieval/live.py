"""The live index: the bundle opened read-only, and the R7n ladder over it (no reranker model is loaded)."""
import sqlite3
import urllib.parse
from pathlib import Path

import sqlite_vec

from retrieval.ladder import Ladder, Settings
from retrieval.scope import Resolver


def open_bundle(path: Path) -> sqlite3.Connection:
    """Read-only and immutable: no journal, no lock or -wal/-shm files, and every write is refused. Usable from any
    thread; callers serialise access (the service holds one lock around retrieval)."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `dtd bundle` first")
    uri = f"file:{urllib.parse.quote(str(path.resolve()))}?mode=ro&immutable=1"
    conn = sqlite3.connect(uri, uri=True, check_same_thread=False)
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def bundle_meta(conn: sqlite3.Connection) -> dict[str, str]:
    return dict(conn.execute("SELECT key, value FROM meta"))


def links_for(conn: sqlite3.Connection, contract_id: str) -> dict:
    """The filing a visitor can open for an agreement, and the filing of each amendment by its number."""
    out: dict = {"filing": None, "amendments": {}}
    for kind, no, url in conn.execute("SELECT kind, amendment_no, url FROM links WHERE contract_id = ?"
                                      " ORDER BY kind, amendment_no", (contract_id,)):
        if kind == "filing":
            out["filing"] = url
        else:
            out["amendments"][no] = url
    return out


def build_live_ladder(path: Path, embedder, lexicon: dict, settings: Settings) -> Ladder:
    conn = open_bundle(path)
    texts = dict(conn.execute("SELECT contract_id, text FROM texts"))
    amendment_texts = dict(conn.execute("SELECT amendment_id, text FROM amendment_texts"))
    return Ladder(conn, texts, embedder, None, lexicon, settings, amendment_texts=amendment_texts,
                  resolver=Resolver(conn))
