import re
import sqlite3

from pipeline.segment import Passage, segment

WHITESPACE = re.compile(r"\s")
MAX_SNAP = 100


def fixed_size(conn: sqlite3.Connection) -> int:
    lengths = sorted(e - s for s, e in conn.execute("SELECT start_char, end_char FROM passages WHERE kind != 'toc'"))
    return max(100, round(lengths[len(lengths) // 2] / 100) * 100)


def fixed_chunks(contract_id: str, text: str, size: int) -> list[Passage]:
    toc = [(p.start, p.end) for p in segment(contract_id, text) if p.kind == "toc"]
    out: list[Passage] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + size)
        if end < len(text):
            m = WHITESPACE.search(text, end, min(len(text), end + MAX_SNAP))
            if m:
                end = m.start()
        kind = "toc" if any(a <= start and end <= b for a, b in toc) else "fixed"
        out.append(Passage(contract_id, len(out), start, end, "", "", kind, ""))
        start = end
    return out


def fixed_chunker(size: int):
    return lambda contract_id, text: fixed_chunks(contract_id, text, size)
