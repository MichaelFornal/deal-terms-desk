import sqlite3
from collections import defaultdict
from pathlib import Path

from evals.compare import load_items
from evals.metrics import is_relevant

K = 5
CLASSES = ("definition_missing", "right_section_wrong_passage", "unsectioned_gold", "wrong_section")
NOT_APPLICABLE = {
    "wrong_deal": "retrieval is scoped to the item's own agreement, so it cannot return another deal",
    "superseded_text": "the MAUD agreements are single documents with no amendments",
    "unfiled_schedule": "every gold span is text inside the filed agreement",
}


def _overlap(a0: int, a1: int, b0: int, b1: int) -> int:
    return max(0, min(a1, b1) - max(a0, b0))


def classify(conn: sqlite3.Connection, items_path: Path, k: int = K) -> dict:
    passages = {pid: (cid, s, e, sec) for pid, cid, s, e, sec in conn.execute(
        "SELECT passage_id, contract_id, start_char, end_char, section_id FROM passages WHERE kind != 'toc'")}
    by_contract: dict[str, list[tuple[int, int, int, str]]] = defaultdict(list)
    for pid, (cid, s, e, sec) in passages.items():
        by_contract[cid].append((pid, s, e, sec))
    defs: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for pid, s, e in conn.execute("SELECT passage_id, def_start, def_end FROM passage_defs"):
        defs[pid].append((s, e))
    counts = {split: dict.fromkeys(CLASSES, 0) for split in ("report", "tune")}
    by_category: dict[str, dict[str, int]] = defaultdict(lambda: dict.fromkeys(CLASSES, 0))
    for row in load_items(items_path).values():
        top = row["top_passage_ids"][:k]
        for p in top:
            if p not in passages:
                raise ValueError(f"{row['item_id']}: top passage {p} is not a passage of this index; "
                                 "were these items scored against another index?")
        top_sections = {passages[p][3] for p in top if passages[p][3]}
        top_defs = [d for p in top for d in defs[p]]
        for g0, g1 in row["gold"]:
            if any(is_relevant(passages[p][1], passages[p][2], [(g0, g1)]) for p in top):
                continue
            home = max(by_contract.get(row["contract_id"], []), default=None,
                       key=lambda x: (_overlap(x[1], x[2], g0, g1), -x[0]))
            if home is None or _overlap(home[1], home[2], g0, g1) == 0:
                raise ValueError(f"{row['item_id']}: gold span [{g0}, {g1}) overlaps no passage of contract "
                                 f"{row['contract_id']}; were these items scored against another index?")
            if any(_overlap(s, e, g0, g1) > 0 for s, e in top_defs):
                cls = "definition_missing"
            elif home[3] and home[3] in top_sections:
                cls = "right_section_wrong_passage"
            elif not home[3]:
                cls = "unsectioned_gold"
            else:
                cls = "wrong_section"
            counts[row["split"]][cls] += 1
            if row["split"] == "report":
                by_category[row["category"]][cls] += 1
    return {"k": k,
            "by_split": {s: {"misses": sum(c.values()), **c} for s, c in counts.items()},
            "by_category_report": dict(by_category),
            "not_applicable": NOT_APPLICABLE}
