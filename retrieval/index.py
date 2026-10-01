import os
import sqlite3
from pathlib import Path

from collections import Counter

from pipeline.definitions import MAX_DEFS, UBIQUITY, definition_spans, term_pattern, terms_used
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
CREATE TABLE passage_defs(
    passage_id INTEGER NOT NULL,
    rank INTEGER NOT NULL,
    term TEXT NOT NULL,
    def_start INTEGER NOT NULL,
    def_end INTEGER NOT NULL
);
CREATE INDEX passage_defs_passage ON passage_defs(passage_id);
CREATE VIRTUAL TABLE passages_x_fts USING fts5(text, tokenize='porter unicode61');
"""


def build_index(db_path: Path, contracts: dict[str, str], chunker=segment) -> dict:
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
        terms = extract_terms(text)
        spans = definition_spans(text, terms)
        pattern = term_pattern(list(spans))
        passages = chunker(contract_id, text)
        used = {p.ordinal: terms_used(text[p.start:p.end], pattern) for p in passages}
        # A term's own defining passage does not count as a use of it.
        uses = Counter(t for p in passages for t in used[p.ordinal] if not (p.start <= spans[t][0] < p.end))
        n = max(1, len(passages))
        for p in passages:
            cur = conn.execute(
                "INSERT INTO passages(contract_id, ordinal, start_char, end_char, section_id, section_title, kind,"
                " section_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (p.contract_id, p.ordinal, p.start, p.end, p.section_id, p.section_title, p.kind, p.section_path),
            )
            summary["passages"] += 1
            if p.kind == "toc":
                continue
            pid = cur.lastrowid
            defs = [t for t in used[p.ordinal]
                    if uses[t] / n <= UBIQUITY and not (p.start <= spans[t][0] < p.end)][:MAX_DEFS]
            for rank, t in enumerate(defs):
                conn.execute("INSERT INTO passage_defs VALUES (?, ?, ?, ?, ?)", (pid, rank, t, *spans[t]))
            body = text[p.start:p.end]
            conn.execute("INSERT INTO passages_fts(rowid, text) VALUES (?, ?)", (pid, body))
            conn.execute("INSERT INTO passages_x_fts(rowid, text) VALUES (?, ?)",
                         (pid, "\n\n".join([body] + [text[s:e] for s, e in (spans[t] for t in defs)])))
            summary["indexed"] += 1
        for t in terms:
            conn.execute("INSERT INTO terms VALUES (?, ?, ?, ?, ?)", (contract_id, t.term, t.start, t.end, t.style))
            summary["terms"] += 1
    conn.commit()
    conn.close()
    os.replace(tmp, db_path)
    return summary
