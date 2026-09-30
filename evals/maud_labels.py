import csv
from dataclasses import dataclass
from pathlib import Path

PSEUDO_CONTRACT = "<RARE_ANSWERS>"


@dataclass(frozen=True)
class LabelRow:
    contract_id: str
    text: str
    question: str
    subquestion: str
    answer: str
    text_type: str
    category: str


def load_rows(csv_paths: list[Path]) -> list[LabelRow]:
    csv.field_size_limit(10**9)
    seen: dict[LabelRow, None] = {}
    for p in csv_paths:
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                if row["data_type"] != "main" or row["contract_name"] == PSEUDO_CONTRACT:
                    continue
                seen[LabelRow(
                    contract_id=row["contract_name"],
                    text=row["text"],
                    question=row["question"],
                    subquestion=row["subquestion"],
                    answer=row["answer"],
                    text_type=row["text_type"],
                    category=row["category"],
                )] = None
    return list(seen)


def census(csv_paths: list[Path]) -> dict:
    """Every row of every label CSV, all data types: the raw material for the recount facts."""
    csv.field_size_limit(10**9)
    rows = 0
    contracts: set[str] = set()
    questions: set[str] = set()
    for p in csv_paths:
        with open(p, encoding="utf-8", errors="replace", newline="") as f:
            for row in csv.DictReader(f):
                rows += 1
                questions.add(row["question"])
                if row["contract_name"] != PSEUDO_CONTRACT:
                    contracts.add(row["contract_name"])
    return {"rows": rows, "contracts": contracts, "questions": questions}
