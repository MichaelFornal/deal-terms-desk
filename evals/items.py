import re
from collections import defaultdict
from dataclasses import dataclass

from evals.align import align_excerpt, short_pieces
from evals.maud_labels import LabelRow
from pipeline.normalise import squash
from pipeline.segment import segment

# MAUD question names end "-Answer", "-Answer (Y/N)", " Answer", "-answer", " - answer", ...
ANSWER_SUFFIX = re.compile(r"[\s-]*\bAnswer\b.*$", re.IGNORECASE)


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
        stem = ANSWER_SUFFIX.sub("", q)
        if stem != text_type and stem not in stems:
            stems.append(stem)
    return ". ".join([text_type] + sorted(stems))


def _merged(spans: list[tuple[int, int]]) -> tuple[tuple[int, int], ...]:
    out: list[tuple[int, int]] = []
    for s, e in sorted(spans):
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], e))
        else:
            out.append((s, e))
    return tuple(out)


def _toc_spans(contract_id: str, text: str) -> list[tuple[int, int]]:
    return [(p.start, p.end) for p in segment(contract_id, text) if p.kind == "toc"]


def build_items(rows: list[LabelRow], texts: dict[str, str],
                toc: dict[str, list[tuple[int, int]]] | None = None) -> tuple[list[Item], dict]:
    """`toc` maps a contract to the canonical spans of its table of contents, which gold may not
    sit in because they are never indexed; left out, it is recomputed with `segment`, and a
    contract missing from a given mapping has none."""
    report = dict.fromkeys(
        ("rows", "items", "items_scored", "items_no_gold", "items_missing_contract",
         "pieces", "pieces_exact", "pieces_anchored", "pieces_unaligned", "pieces_short",
         "pieces_ambiguous", "pieces_toc_rescued", "pieces_toc_only"), 0)
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
            text = texts[contract_id]
            excluded = toc.get(contract_id, []) if toc is not None else _toc_spans(contract_id, text)
            squashed_cache[contract_id] = (*squash(text), excluded)
        squashed, index, excluded = squashed_cache[contract_id]
        gold: list[tuple[int, int]] = []
        for excerpt in dict.fromkeys(r.text for r in group):
            report["pieces_short"] += short_pieces(excerpt)
            for a in align_excerpt(excerpt, squashed, index, exclude=excluded):
                report["pieces"] += 1
                report["pieces_toc_rescued"] += a.toc_rescued
                report["pieces_toc_only"] += a.toc_only
                if a.status == "none":
                    report["pieces_unaligned"] += 1
                    continue
                report[f"pieces_{a.status}"] += 1
                report["pieces_ambiguous"] += a.n_candidates > 1
                gold.append((a.start, a.end))
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
            gold=_merged(gold),
        ))
    return items, report
