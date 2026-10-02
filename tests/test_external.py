import json
from pathlib import Path

DOC = json.loads(Path("facts/external.json").read_text())["legalbench_rag"]


def test_external_numbers_were_checked_against_the_paper():
    assert DOC["verified_against_pdf"] is True


def test_every_method_has_a_table_and_a_value_per_k():
    assert set(DOC["methods"]) == {"naive", "rcts", "rcts_cohere"}
    for m in DOC["methods"].values():
        assert isinstance(m["table"], int)
        assert len(m["precision_pct"]) == len(m["recall_pct"]) == len(DOC["k"])
        assert all(0 <= v <= 100 for v in m["precision_pct"] + m["recall_pct"])
