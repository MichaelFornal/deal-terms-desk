import json
import sqlite3

import pytest

from evals.failures import CLASSES, NOT_APPLICABLE, classify
from retrieval.index import build_index

DOC = (
    "AGREEMENT AND PLAN OF MERGER among Parent, Merger Sub and the Company, dated as of the date below.\n\n"
    "Section 1.1 Definitions. “Company Termination Fee” means an amount in cash equal to $50,000,000.\n\n"
    "Section 5.1 Covenants. " + "The Company shall conduct its business in the ordinary course. " * 60 + "\n\n"
    "Section 8.3 Fees. The Company shall pay the Company Termination Fee on termination.\n\n"
    + "".join(f"Section 9.{i} Misc. Miscellaneous clause number {i} of this Agreement.\n\n" for i in range(1, 6))
)


def ids(conn):
    rows = conn.execute("SELECT passage_id, section_id, start_char, end_char, kind FROM passages ORDER BY ordinal").fetchall()
    return rows


def test_each_class_is_assigned_by_its_rule(tmp_path):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    conn = sqlite3.connect(db)
    rows = ids(conn)
    sec = {}
    for pid, sid, s, e, kind in rows:
        sec.setdefault(sid or kind, []).append((pid, s, e))
    front, s83 = sec["front"][0], sec["8.3"][0]
    s51a, s51b = sec["5.1"][0], sec["5.1"][1]
    s91, s92 = sec["9.1"][0], sec["9.2"][0]
    fee = DOC.index("$50,000,000")

    def item(name, gold, top):
        return {"item_id": f"c|{name}", "contract_id": "c", "category": "Remedies", "split": "report",
                "gold": [list(g) for g in gold], "top_passage_ids": top}
    items = [
        item("def", [(fee - 30, fee + 11)], [s83[0]]),
        item("split", [(s51b[1] + 10, s51b[1] + 200)], [s51a[0]]),
        item("front", [(front[1] + 5, front[1] + 60)], [s91[0]]),
        item("wrong", [(s92[1] + 2, s92[2] - 2)], [s91[0]]),
        item("hit", [(s91[1] + 2, s91[2] - 2)], [s91[0]]),
    ]
    path = tmp_path / "r6_items.jsonl"
    path.write_text("".join(json.dumps(i) + "\n" for i in items))
    out = classify(conn, path)
    assert out["by_split"]["report"] == {"misses": 4, "definition_missing": 1, "right_section_wrong_passage": 1,
                                         "unsectioned_gold": 1, "wrong_section": 1}
    assert out["by_category_report"]["Remedies"]["wrong_section"] == 1
    assert set(out["not_applicable"]) == set(NOT_APPLICABLE)
    assert CLASSES == ("definition_missing", "right_section_wrong_passage", "unsectioned_gold", "wrong_section")


def _one(tmp_path, item):
    db = tmp_path / "i.db"
    build_index(db, {"c": DOC})
    path = tmp_path / "r_items.jsonl"
    path.write_text(json.dumps({"contract_id": "c", "category": "R", "split": "report", **item}) + "\n")
    return sqlite3.connect(db), path


def test_top_passage_from_another_index_raises(tmp_path):
    conn, path = _one(tmp_path, {"item_id": "c|bad", "gold": [[0, 10]], "top_passage_ids": [999999]})
    with pytest.raises(ValueError, match=r"c\|bad.*999999"):
        classify(conn, path)


def test_gold_beyond_the_text_raises(tmp_path):
    conn, path = _one(tmp_path, {"item_id": "c|far", "gold": [[len(DOC) + 50, len(DOC) + 90]], "top_passage_ids": []})
    with pytest.raises(ValueError, match=r"c\|far"):
        classify(conn, path)
