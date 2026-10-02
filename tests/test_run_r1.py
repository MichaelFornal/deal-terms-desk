import json

from evals.run_r1 import METRICS, run
from retrieval.index import build_index

HEADER = "data_type,contract_name,text,answer,label,question,subquestion,text_type,id,category\n"


def contract(fee):
    return (
        "Section 1.1 Closing. The closing shall occur at the offices of counsel on the Closing Date.\n\n"
        "Section 2.6 Type of Consideration. Each Company Share shall be converted into the right to receive cash.\n\n"
        f"Section 8.3 Termination Fee. The Company shall pay Parent a termination fee of {fee} dollars in cash.\n"
    )


def setup(tmp_path):
    cdir = tmp_path / "raw" / "contracts"
    cdir.mkdir(parents=True)
    texts = {f"contract_{i}": contract(f"{i + 1}0,000,000") for i in range(4)}
    for cid, t in texts.items():
        (cdir / f"{cid}.txt").write_text(t, encoding="utf-8")
    body = ""
    for i, (cid, t) in enumerate(texts.items()):
        consideration = t.split("\n\n")[1]
        fee = t.split("\n\n")[2].strip()
        body += f'main,{cid},"{consideration} (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,{i},General Information\n'
        body += f'main,{cid},"{fee} (Page 70)",Yes,1,Termination Fee-Answer,<NONE>,Termination Fee,{i + 100},Deal Protection and Related Provisions\n'
    body += 'main,contract_404,"Section 2.6 Type of Consideration. Each Company Share shall be converted. (Page 9)",All Cash,0,Type of Consideration-Answer,<NONE>,Type of Consideration,999,General Information\n'
    csv_path = tmp_path / "raw" / "MAUD_dev.csv"
    csv_path.write_text(HEADER + body, encoding="utf-8")
    db = tmp_path / "index" / "maud.db"
    build_index(db, texts)
    return db, [csv_path], cdir, tmp_path / "out"


def test_run_writes_results_with_every_metric(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    assert json.loads((out / "r1.json").read_text()) == result
    assert result["rung"] == "R1" and result["scope"] == "within-agreement"
    assert set(result["overall"]) == set(METRICS)
    assert result["overall"]["recall@10"]["n_items"] == 8
    assert result["overall"]["recall@10"]["n_clusters"] == 4
    assert result["overall"]["recall@5"]["mean"] == 1.0
    assert result["latency_ms"]["p50"] >= 0 and result["latency_ms"]["p95"] >= result["latency_ms"]["p50"]


def test_run_reports_the_missing_contract(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    assert result["alignment"]["items_missing_contract"] == 1
    assert result["alignment"]["items_scored"] == 8
    assert json.loads((out / "alignment.json").read_text()) == result["alignment"]


def test_run_breaks_results_down_by_category_and_split(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    assert set(result["by_category"]) == {"General Information", "Deal Protection and Related Provisions"}
    assert result["by_category"]["General Information"]["recall@10"]["n_items"] == 4
    total = sum(result["by_split"][s]["recall@10"]["n_items"] for s in result["by_split"])
    assert total == 8


def test_run_is_deterministic(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    a = run(db, csvs, cdir, out, n_boot=100)
    b = run(db, csvs, cdir, out, n_boot=100)
    for r in (a, b):
        r.pop("latency_ms"); r.pop("load")
    assert a == b


def test_run_writes_one_result_line_per_item(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=100)
    lines = [json.loads(l) for l in (out / "r1_items.jsonl").read_text().splitlines()]
    assert len(lines) == result["overall"]["recall@5"]["n_items"] == 8
    assert [l["item_id"] for l in lines] == sorted(l["item_id"] for l in lines)
    first = lines[0]
    assert set(first) == {"item_id", "contract_id", "split", "category", "gold", "top_passage_ids", "query", "latency_ms",
                         "context_tokens", *METRICS}
    assert first["item_id"] == "contract_0|Termination Fee" and first["contract_id"] == "contract_0"
    assert 1 <= len(first["top_passage_ids"]) <= 10 and all(isinstance(p, int) for p in first["top_passage_ids"])
    assert first["recall@5"] == 1.0
    assert not list(out.glob("*.tmp"))


def test_gold_inside_the_indexed_table_of_contents_is_not_used(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    import sqlite3
    conn = sqlite3.connect(db)
    conn.execute("UPDATE passages SET kind = 'toc' WHERE contract_id = 'contract_0' AND ordinal = 1")
    conn.commit(); conn.close()
    result = run(db, csvs, cdir, out, n_boot=100)
    assert result["alignment"]["pieces_toc_only"] == 1
