"""The live bundle: one read-only SQLite file the server loads. It is deals.db (the index the evals measured)
plus the contract texts, the amendment texts and the links a visitor follows, minus the `terms` table, which
nothing reads at query time. It is built through a temp file, then renamed into place with its manifest, so a kill
leaves either the previous bundle or none."""
import hashlib
import json
import os
import sqlite3
from pathlib import Path

from answer.prompt import TEMPLATE_SHA
from pipeline.paths import MAUD_BASE

MANIFEST = "bundle.json"
EXTRA = """
CREATE TABLE texts(contract_id TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE amendment_texts(amendment_id TEXT PRIMARY KEY, text TEXT NOT NULL);
CREATE TABLE links(contract_id TEXT NOT NULL, kind TEXT NOT NULL, amendment_no INTEGER, url TEXT NOT NULL);
CREATE INDEX links_contract ON links(contract_id);
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def maud_url(contract_id: str) -> str:
    """Where pipeline/fetch_maud.py fetched the agreement text (MAUD on Hugging Face, pinned revision)."""
    return f"{MAUD_BASE}/contracts/{contract_id}.txt"


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _sha256_texts(texts: dict[str, str]) -> str:
    h = hashlib.sha256()
    for cid in sorted(texts):
        h.update(cid.encode("utf-8") + b"\0" + texts[cid].encode("utf-8") + b"\0")
    return h.hexdigest()


def _inputs(deals_db: Path, texts, amendment_texts, deals_jsonl: Path, settings_path: Path,
            lexicon_path: Path) -> dict[str, str]:
    return {"deals_db_sha256": _sha256_file(deals_db), "texts_sha256": _sha256_texts(texts),
            "amendment_texts_sha256": _sha256_texts(amendment_texts),
            "deals_jsonl_sha256": _sha256_file(deals_jsonl), "settings_sha256": _sha256_file(settings_path),
            "lexicon_sha256": _sha256_file(lexicon_path), "template_sha": TEMPLATE_SHA}


def bundle_is_current(out: Path) -> bool:
    """The bundle matches the sha its manifest records. Both are renamed into place, the db first, so a kill
    between the renames leaves a mismatch (rebuilt next run), never a false match."""
    out = Path(out)
    man = out.with_name(MANIFEST)
    if not (out.exists() and man.exists()):
        return False
    try:
        doc = json.loads(man.read_text(encoding="utf-8"))
    except ValueError:
        return False
    return doc.get("sha256") == _sha256_file(out)


def _fill(conn: sqlite3.Connection, texts: dict[str, str], amendment_texts: dict[str, str], deals_jsonl: Path,
          meta: dict[str, str]) -> None:
    conn.execute("DROP TABLE IF EXISTS terms")
    conn.executescript(EXTRA)
    cids = [r[0] for r in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id")]
    missing = [c for c in cids if c not in texts]
    if missing:
        raise ValueError(f"{len(missing)} indexed contracts have no text, e.g. {missing[0]}")
    conn.executemany("INSERT INTO texts VALUES (?, ?)", [(c, texts[c]) for c in cids])
    linked = conn.execute("SELECT DISTINCT amendment_id, amendment_no FROM superseded ORDER BY amendment_id").fetchall()
    gone = sorted({a for a, _ in linked if a not in amendment_texts})
    if gone:
        raise ValueError(f"{len(gone)} linked amendments have no text, e.g. {gone[0]}")
    conn.executemany("INSERT OR IGNORE INTO amendment_texts VALUES (?, ?)",
                     [(a, amendment_texts[a]) for a, _ in linked])
    for cid, source, url in conn.execute("SELECT contract_id, source, url FROM deals ORDER BY contract_id").fetchall():
        filing = url if source == "edgar" else maud_url(cid)
        if filing:
            conn.execute("INSERT INTO links VALUES (?, 'filing', NULL, ?)", (cid, filing))
    urls: dict[str, tuple[str, str]] = {}
    for line in Path(deals_jsonl).read_text(encoding="utf-8").splitlines():
        if line.strip():
            d = json.loads(line)
            for am in d.get("amendments", []):
                if am.get("url"):
                    urls[am["contract_id"]] = (d["contract_id"], am["url"])
    for aid, no in linked:
        if aid in urls:
            cid, url = urls[aid]
            conn.execute("INSERT INTO links VALUES (?, 'amendment', ?, ?)", (cid, no, url))
    conn.executemany("INSERT INTO meta VALUES (?, ?)", sorted(meta.items()))


def _clear(tmp: Path) -> None:
    for suffix in ("", "-journal", "-wal", "-shm"):
        tmp.with_name(tmp.name + suffix).unlink(missing_ok=True)


def build_bundle(deals_db: Path, out: Path, *, texts: dict[str, str], amendment_texts: dict[str, str],
                 deals_jsonl: Path, settings_path: Path, lexicon_path: Path) -> dict:
    deals_db, out = Path(deals_db), Path(out)
    man = out.with_name(MANIFEST)
    meta = _inputs(deals_db, texts, amendment_texts, Path(deals_jsonl), Path(settings_path), Path(lexicon_path))
    keys = ("sha256", "bytes", "contracts", "passages")
    if bundle_is_current(out):
        doc = json.loads(man.read_text(encoding="utf-8"))
        if doc.get("meta") == meta:
            return {k: doc[k] for k in keys} | {"rebuilt": False}
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(out.name + ".building")
    part = man.with_name(man.name + ".tmp")
    _clear(tmp)  # a SIGKILLed earlier build leaves these behind; VACUUM INTO refuses an existing file, and a stale
    # journal beside a fresh temp file could be rolled into it
    try:
        src = sqlite3.connect(deals_db)
        try:
            src.execute("VACUUM INTO ?", (str(tmp),))
        finally:
            src.close()
        conn = sqlite3.connect(tmp)
        try:
            _fill(conn, texts, amendment_texts, Path(deals_jsonl), meta)
            conn.commit()
            conn.execute("VACUUM")
            counts = {"contracts": conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0],
                      "passages": conn.execute("SELECT COUNT(*) FROM passages").fetchone()[0]}
        finally:
            conn.close()
        doc = {"sha256": _sha256_file(tmp), "bytes": tmp.stat().st_size, **counts, "meta": meta}
        part.write_text(json.dumps(doc, indent=2, sort_keys=True), encoding="utf-8")
        os.replace(tmp, out)
        os.replace(part, man)
    finally:
        _clear(tmp)
        part.unlink(missing_ok=True)
    return {k: doc[k] for k in keys} | {"rebuilt": True}
