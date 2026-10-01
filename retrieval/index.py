import os
import sqlite3
from pathlib import Path

from pipeline.segment import segment
from pipeline.terms import extract_terms

SCHEMA = """
CREATE TABLE contracts(contract_id TEXT PRIMARY KEY, n_chars INTEGER NOT NULL);
CREATE TABLE passages(
    passage_id INTEGER PRIMARY KEY,
    contract_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    section_id TEXT NOT NULL,
    section_title TEXT NOT NULL,
    kind TEXT NOT NULL,
    section_path TEXT NOT NULL
);
CREATE INDEX passages_contract ON passages(contract_id);
CREATE TABLE terms(
    contract_id TEXT NOT NULL,
    term TEXT NOT NULL,
    start_char INTEGER NOT NULL,
    end_char INTEGER NOT NULL,
    style TEXT NOT NULL
);
CREATE VIRTUAL TABLE passages_fts USING fts5(text, tokenize='porter unicode61');
"""


def build_index(db_path: Path, contracts: dict[str, str]) -> dict:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = db_path.with_name(db_path.name + ".building")
    if tmp.exists():
        tmp.unlink()
    conn = sqlite3.connect(tmp)
    conn.executescript(SCHEMA)
    summary = {"contracts": 0, "passages": 0, "indexed": 0, "terms": 0}
    for contract_id in sorted(contracts):
        text = contracts[contract_id]
        conn.execute("INSERT INTO contracts VALUES (?, ?)", (contract_id, len(text)))
        summary["contracts"] += 1
        for p in segment(contract_id, text):
            cur = conn.execute(
                "INSERT INTO passages(contract_id, ordinal, start_char, end_char, section_id, section_title, kind,"
                " section_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p.contract_id, p.ordinal, p.start, p.end, p.section_id, p.section_title, p.kind, p.section_path),
            )
            summary["passages"] += 1
            if p.kind != "toc":
                conn.execute(
                    "INSERT INTO passages_fts(rowid, text) VALUES (?, ?)",
                    (cur.lastrowid, text[p.start:p.end]),
                )
                summary["indexed"] += 1
        for t in extract_terms(text):
            conn.execute("INSERT INTO terms VALUES (?, ?, ?, ?, ?)", (contract_id, t.term, t.start, t.end, t.style))
            summary["terms"] += 1
    conn.commit()
    conn.close()
    os.replace(tmp, db_path)
    return summary
