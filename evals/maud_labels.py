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
