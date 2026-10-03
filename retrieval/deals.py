import re
import sqlite3
from pathlib import Path

from evals.bootstrap import split_of
from pipeline.amendments import amended_sections, amendment_no
from pipeline.target import norm, preamble

SCHEDULE_REF = re.compile(r"\b(?:Company|Parent|Seller|Buyer)\s+Disclosure\s+(?:Letter|Schedule)\b|"
                          r"\bset\s+forth\s+(?:in|on)\s+Schedule\s+\d", re.I)
SCHEMA = """
DROP TABLE IF EXISTS deals; DROP TABLE IF EXISTS aliases; DROP TABLE IF EXISTS passage_tags;
DROP TABLE IF EXISTS superseded;
CREATE TABLE deals(contract_id TEXT PRIMARY KEY, source TEXT NOT NULL, target TEXT, parent TEXT, signed TEXT,
                   url TEXT, split TEXT NOT NULL);
CREATE TABLE aliases(alias TEXT NOT NULL, contract_id TEXT NOT NULL, kind TEXT NOT NULL);
CREATE INDEX aliases_alias ON aliases(alias);
CREATE TABLE passage_tags(passage_id INTEGER NOT NULL, tag TEXT NOT NULL);
CREATE TABLE superseded(passage_id INTEGER NOT NULL, amendment_id TEXT NOT NULL, amendment_no INTEGER NOT NULL,
                        file_date TEXT NOT NULL, section_id TEXT NOT NULL, amend_start INTEGER NOT NULL,
                        amend_end INTEGER NOT NULL);
CREATE INDEX superseded_passage ON superseded(passage_id);
"""
MIN_ALIAS = 4  # "Big Co" normalises to "big"; a 3-letter alias would scope any question using the word


def _maud_row(cid: str, text: str) -> tuple[dict, list[tuple[str, str]]]:
    p = preamble(text)
    aliases = [(norm(n), kind) for n, kind in ((p.company, "target"), (p.parent, "parent")) if n]
    return ({"contract_id": cid, "source": "maud", "target": p.company, "parent": p.parent,
             "signed": p.signed.isoformat() if p.signed else None, "url": None, "split": split_of(cid)},
            [(a, k) for a, k in aliases if len(a) >= MIN_ALIAS])


def add_deals(db_path: Path, deals: list[dict], texts: dict[str, str], amendment_texts: dict[str, str]) -> dict:
    conn = sqlite3.connect(db_path)
    tech = {d["contract_id"]: d for d in deals}
    s = dict.fromkeys(("deals", "maud_deals", "aliases", "schedule_tagged", "amendments", "amendments_linked",
                       "amendments_unlinked", "passages_superseded"), 0)
    conn.executescript("BEGIN;" + SCHEMA)
    try:
        for (cid,) in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id").fetchall():
            if cid in tech:
                d = tech[cid]
                row = {k: d.get(k) for k in ("target", "parent", "signed", "url", "split")} | {
                    "contract_id": cid, "source": "edgar"}
                aliases = [(a, "target") for a in d["aliases"]] + (
                    [(norm(d["parent"]), "parent")] if d.get("parent") else [])
            else:
                row, aliases = _maud_row(cid, texts[cid])
                s["maud_deals"] += 1
            conn.execute("INSERT INTO deals VALUES (:contract_id, :source, :target, :parent, :signed, :url, :split)",
                         row)
            for a, kind in dict.fromkeys(aliases):
                if len(a) >= MIN_ALIAS:
                    conn.execute("INSERT INTO aliases VALUES (?, ?, ?)", (a, cid, kind))
                    s["aliases"] += 1
            s["deals"] += 1
            passages = conn.execute("SELECT passage_id, section_id, start_char, end_char FROM passages"
                                    " WHERE contract_id = ? AND kind != 'toc'", (cid,)).fetchall()
            for pid, _, a, b in passages:
                if SCHEDULE_REF.search(texts[cid][a:b]):
                    conn.execute("INSERT INTO passage_tags VALUES (?, 'schedule_ref')", (pid,))
                    s["schedule_tagged"] += 1
            for n, am in enumerate(tech.get(cid, {}).get("amendments", []), start=1):
                s["amendments"] += 1
                atext = amendment_texts[am["contract_id"]]
                links = amended_sections(atext)
                s["amendments_linked" if links else "amendments_unlinked"] += 1
                no = amendment_no(atext, fallback=n)
                for sec, a0, a1 in links:
                    for pid, psec, _, _ in passages:
                        if psec == sec:
                            conn.execute("INSERT INTO superseded VALUES (?, ?, ?, ?, ?, ?, ?)",
                                         (pid, am["contract_id"], no, am["file_date"], sec, a0, a1))
                            s["passages_superseded"] += 1
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()
    return s
