from collections import defaultdict
from dataclasses import dataclass

from evals.align import align_piece, pieces_of
from evals.maud_labels import LabelRow
from pipeline.normalise import squash

ANSWER_SUFFIX = "-Answer"


@dataclass(frozen=True)
class Item:
    item_id: str
    contract_id: str
    text_type: str
    category: str
    query: str
    gold: tuple[tuple[int, int], ...]


def _query(text_type: str, questions: list[str]) -> str:
    stems = []
    for q in questions:
        stem = q[: -len(ANSWER_SUFFIX)] if q.endswith(ANSWER_SUFFIX) else q
        if stem != text_type and stem not in stems:
            stems.append(stem)
    return ". ".join([text_type] + sorted(stems))


def build_items(rows: list[LabelRow], texts: dict[str, str]) -> tuple[list[Item], dict]:
    report = dict.fromkeys(
        ("rows", "items", "items_scored", "items_no_gold", "items_missing_contract",
         "pieces", "pieces_exact", "pieces_anchored", "pieces_unaligned"), 0)
    report["rows"] = len(rows)
    groups: dict[tuple[str, str], list[LabelRow]] = defaultdict(list)
    for r in rows:
        groups[(r.contract_id, r.text_type)].append(r)
    squashed_cache: dict[str, tuple[str, list[int]]] = {}
    items: list[Item] = []
    for (contract_id, text_type) in sorted(groups):
        group = groups[(contract_id, text_type)]
        report["items"] += 1
        if contract_id not in texts:
            report["items_missing_contract"] += 1
            continue
        if contract_id not in squashed_cache:
            squashed_cache[contract_id] = squash(texts[contract_id])
        squashed, index = squashed_cache[contract_id]
        gold: list[tuple[int, int]] = []
        for excerpt in dict.fromkeys(r.text for r in group):
            for piece in pieces_of(excerpt):
                report["pieces"] += 1
                status, s, e = align_piece(piece, squashed, index)
                if status == "none":
                    report["pieces_unaligned"] += 1
                    continue
                report[f"pieces_{status}"] += 1
                if (s, e) not in gold:
                    gold.append((s, e))
        if not gold:
            report["items_no_gold"] += 1
            continue
        report["items_scored"] += 1
        items.append(Item(
            item_id=f"{contract_id}|{text_type}",
            contract_id=contract_id,
            text_type=text_type,
            category=group[0].category,
            query=_query(text_type, [r.question for r in group]),
            gold=tuple(sorted(gold)),
        ))
    return items, report
