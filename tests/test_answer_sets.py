import sqlite3

from evals.answer_sets import (ABSTAIN_GROUPS, AnswerItem, abstain_items, read_items, thuman_items, tmachine_items,
                               write_items)
from evals.maud_labels import LabelRow
from retrieval.scope import Resolver


def lr(cid, q, a, cat="Deal Structure"):
    return LabelRow(cid, "span", q, "", a, "Type of Consideration", cat)


def test_thuman_one_item_per_contract_question_with_all_options():
    rows = [lr("contract_1", "Type of Consideration-Answer", "All Cash"),
            lr("contract_1", "Type of Consideration-Answer", "All Cash"),  # duplicate span rows collapse
            lr("contract_2", "Type of Consideration-Answer", "All Stock"),
            lr("contract_3", "Type of Consideration-Answer", "All Cash"),
            lr("contract_3", "Type of Consideration-Answer", "All Stock"),  # disputed: excluded
            lr("contract_9", "Type of Consideration-Answer", "Mixed")]  # not in the index
    items, ex = thuman_items(rows, {"contract_1", "contract_2", "contract_3"})
    assert [i.item_id for i in items] == ["contract_1|Type of Consideration-Answer",
                                          "contract_2|Type of Consideration-Answer"]
    assert items[0].choices == ("All Cash", "All Stock", "Mixed") and items[0].expected == "All Cash"
    assert items[0].question == "Type of Consideration" and items[0].contract_id == "contract_1"
    assert items[0].set == "thuman" and items[0].group == "Deal Structure"
    assert ex == {"disputed": 1, "not_indexed": 1, "too_many_options": 0, "questions_too_many_options": 0}


def test_thuman_question_carries_the_maud_question_type():
    rows = [LabelRow("contract_1", "span", "A/P/C application to-Answer", "", "Both", "MAE definition", "Deal Protection")]
    items, _ = thuman_items(rows, {"contract_1"})
    assert items[0].question == "MAE definition: A/P/C application to"
    assert items[0].item_id == "contract_1|A/P/C application to-Answer"


def test_thuman_excludes_questions_with_too_many_options():
    rows = [lr(f"contract_{i}", "Big-Answer", f"opt{i}") for i in range(12)]
    items, ex = thuman_items(rows, {f"contract_{i}" for i in range(12)}, max_options=10)
    assert items == [] and ex["questions_too_many_options"] == 1 and ex["too_many_options"] == 12


TM = [{"contract_id": "edgar_1", "family": "termination_fee", "target": "Acme Software, Inc.", "status": "kept",
       "gold": [[10, 20]], "a": {"answer": "Fee is $5m, per Section 7.3 of the Company Disclosure Schedule."},
       "b": {"answer": "A $5m fee; amounts in the disclosure schedule."}},
      {"contract_id": "edgar_1", "family": "employee_benefits", "target": "Acme Software, Inc.", "status": "absent",
       "gold": [], "a": {"answer": "No such covenant."}, "b": {"answer": "None."}},
      {"contract_id": "edgar_2", "family": "equity_awards", "target": "Real Co", "status": "absent", "gold": [],
       "a": {"answer": "Section 2.07's text isn't included, so it can't be confirmed."}, "b": {"answer": "Not included."}},
      {"contract_id": "edgar_2", "family": "termination_fee", "target": "Real Co", "status": "error", "gold": [],
       "a": {"answer": ""}, "b": {"answer": ""}}]


def test_tmachine_items_are_kept_rows_with_the_named_question():
    items = tmachine_items(TM)
    assert len(items) == 1 and items[0].contract_id is None and items[0].expected == "edgar_1"
    assert "Acme Software, Inc." in items[0].question
    assert items[0].meta["a"].startswith("Fee is") and items[0].meta["gold"] == [[10, 20]]


def _resolver():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE aliases(alias TEXT, contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO aliases VALUES (?, ?, ?)",
                     [("acme software", "edgar_1", "target"), ("big parent", "edgar_1", "parent"),
                      ("big parent", "edgar_2", "parent")])
    conn.execute("CREATE TABLE passages(passage_id INTEGER, contract_id TEXT, start_char INTEGER, end_char INTEGER,"
                 " kind TEXT)")
    conn.execute("INSERT INTO passages VALUES (1, 'edgar_1', 0, 50, 'body')")
    conn.execute("CREATE TABLE passage_tags(passage_id INTEGER, tag TEXT)")
    conn.execute("INSERT INTO passage_tags VALUES (1, 'schedule_ref')")
    return Resolver(conn), conn


def test_abstain_groups():
    resolver, conn = _resolver()
    sample = [{"adsh": "0000000001-20-000001", "contingent_consideration": {"present": False}},
              {"adsh": "0000000002-20-000002", "contingent_consideration": {"present": True}}]
    deals = {"edgar_000000000120000001": {"target": "Zed Corp"}}
    names = ["ACME SOFTWARE INC", "NOVEL WIDGETS INC", "OTHER THING CORP"]
    items = abstain_items(TM, sample, deals, names, resolver, conn, n=30)
    by = {}
    for i in items:
        by.setdefault(i.group, []).append(i)
    assert set(by) <= set(ABSTAIN_GROUPS)
    assert [i.contract_id for i in by["absent"]] == ["edgar_1"] and by["absent"][0].expected == "not_stated"
    assert [i.contract_id for i in by["absent_not_filed"]] == ["edgar_2"]
    assert [i.contract_id for i in by["earnout"]] == ["edgar_000000000120000001"]
    assert "Zed Corp" in by["earnout"][0].question
    unknown = {i.meta["name"] for i in by["unknown_deal"]}
    assert unknown == {"NOVEL WIDGETS INC", "OTHER THING CORP"}  # ACME resolves, so it is not unknown
    assert all(i.contract_id is None and i.expected == "which_deal" for i in by["unknown_deal"] + by["ambiguous_deal"])
    assert [i.meta["name"] for i in by["ambiguous_deal"]] == ["Big Parent"]
    assert [i.contract_id for i in by["schedule"]] == ["edgar_1"] and by["schedule"][0].expected == "unfiled_schedule"


def test_items_round_trip(tmp_path):
    items, _ = thuman_items([lr("contract_1", "Type of Consideration-Answer", "All Cash")], {"contract_1"})
    write_items(tmp_path / "x.jsonl", items)
    assert read_items(tmp_path / "x.jsonl") == items
