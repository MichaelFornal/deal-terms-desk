import json

import pytest

from evals.run_rung import evaluate, load_context
from retrieval.bm25 import Hit, search
from retrieval.index import build_index
from retrieval.result import CONTEXT_K, Retrieved

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
        fee = t.split("\n\n")[2].strip()
        body += f'main,{cid},"{fee} (Page 70)",Yes,1,Termination Fee-Answer,<NONE>,Termination Fee,{i},Deal Protection and Related Provisions\n'
    csv_path = tmp_path / "raw" / "MAUD_dev.csv"
    csv_path.write_text(HEADER + body, encoding="utf-8")
    db = tmp_path / "index" / "maud.db"
    build_index(db, texts)
    return db, [csv_path], cdir, tmp_path / "out"


def bm25_retriever(db, ctx):
    import sqlite3
    conn = sqlite3.connect(db)

    def retrieve(query, contract_id, k):
        hits = search(conn, query, contract_id=contract_id, k=k)
        return Retrieved(hits, 2.5, [ctx.texts[h.contract_id][h.start:h.end] for h in hits[:CONTEXT_K]])
    return retrieve


def test_evaluate_names_files_by_rung_and_records_tokens_and_load(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    ctx = load_context(db, csvs, cdir)
    result = evaluate(ctx, "R3-fixed", bm25_retriever(db, ctx), out, n_boot=50,
                      count_tokens=lambda s: len(s.split()), extra={"note": "x"})
    assert json.loads((out / "r3_fixed.json").read_text()) == result
    rows = [json.loads(l) for l in (out / "r3_fixed_items.jsonl").read_text().splitlines()]
    assert len(rows) == 4 and all(r["latency_ms"] == 2.5 and r["context_tokens"] > 0 for r in rows)
    assert rows[0]["query"].startswith("Termination Fee")
    assert result["rung"] == "R3-fixed" and result["extra"] == {"note": "x"}
    assert result["context_tokens"]["mean"] > 0
    assert len(result["load"]["before"]) == 3
    assert result["latency_ms"]["p50"] == 2.5


def test_corpus_wide_scope_passes_no_contract_and_never_credits_another_agreement(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    ctx = load_context(db, csvs, cdir)
    seen = []
    inner = bm25_retriever(db, ctx)

    def retrieve(query, contract_id, k):
        seen.append(contract_id)
        return inner(query, contract_id, k)
    result = evaluate(ctx, "R1-corpus", retrieve, out, n_boot=50, scope="corpus-wide", k=64, char_ks=(1, 2))
    assert set(seen) == {None}
    rows = {r["contract_id"]: r for r in map(json.loads, (out / "r1_corpus_items.jsonl").read_text().splitlines())}
    # Foreign hits (identical offsets in the other agreements) really do come back.
    assert any(len(r["top_passage_ids"]) > 1 for r in rows.values())
    assert all(r["recall@10"] == 1.0 for r in rows.values())
    assert "char_recall@2" in rows["contract_0"] and "char_precision@1" in result["overall"]


def test_foreign_passage_at_identical_offsets_earns_no_recall_or_precision(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    ctx = load_context(db, csvs, cdir)
    inner = bm25_retriever(db, ctx)

    def retrieve(query, contract_id, k):
        # Everything except contract_0's own hits: only other agreements' passages come back.
        r = inner(query, None, k)
        return Retrieved([h for h in r.hits if h.contract_id != "contract_0"], r.ms, r.context)
    evaluate(ctx, "R1-foreign", retrieve, out, n_boot=50, scope="corpus-wide", k=64, char_ks=(5,))
    rows = {r["contract_id"]: r for r in map(json.loads, (out / "r1_foreign_items.jsonl").read_text().splitlines())}
    assert rows["contract_0"]["recall@10"] == 0.0 and rows["contract_0"]["mrr@10"] == 0.0
    assert rows["contract_0"]["char_recall@5"] == 0.0 and rows["contract_0"]["char_precision@5"] == 0.0
    assert rows["contract_1"]["recall@10"] == 1.0


def test_char_precision_counts_foreign_characters(tmp_path):
    db, csvs, cdir, out = setup(tmp_path)
    ctx = load_context(db, csvs, cdir)
    item = next(i for i in ctx.items if i.contract_id == "contract_0")
    own = next(h for h in search_all(db, item.query, "contract_0"))
    foreign = Hit(999, "contract_1", own.start, own.end, 1.0)

    def retrieve(query, contract_id, k):
        if query != item.query:
            return Retrieved([], 0.0, [])
        return Retrieved([own, foreign], 1.0, [])
    evaluate(ctx, "R1-prec", retrieve, out, n_boot=50, scope="corpus-wide", char_ks=(2,))
    rows = {r["contract_id"]: r for r in map(json.loads, (out / "r1_prec_items.jsonl").read_text().splitlines())}
    p1 = rows["contract_0"]["char_precision@2"]
    covered = rows["contract_0"]["char_recall@2"] * sum(e - s for s, e in item.gold)
    assert p1 == pytest.approx(covered / (2 * (own.end - own.start)))


def search_all(db, query, cid):
    import sqlite3
    return search(sqlite3.connect(db), query, contract_id=cid, k=1)


def test_run_r1_output_is_unchanged_in_shape(tmp_path):
    from evals.run_r1 import METRICS, run
    db, csvs, cdir, out = setup(tmp_path)
    result = run(db, csvs, cdir, out, n_boot=50)
    assert result["rung"] == "R1" and set(METRICS) <= set(result["overall"])
    assert (out / "r1_items.jsonl").exists() and (out / "alignment.json").exists()
