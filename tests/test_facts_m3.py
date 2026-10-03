import json
import sqlite3

import pytest

from evals.items import Item
from evals.run_rung import Context, evaluate
from evals.tmachine import FAMILIES
from facts.m3 import build_m3, present_m3
from retrieval.bm25 import Hit
from retrieval.result import Retrieved

CIDS = {"edgar_a": "report", "edgar_d": "tune"}


def _hit(cid, start, end):
    return Hit(passage_id=1, contract_id=cid, start=start, end=end, score=1.0)


def _write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj), encoding="utf-8")


def _jsonl(path, rows):
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _ctx():
    items = [Item(f"{cid}|{fam}", cid, fam, fam, f"q {fam}", ((100, 200),))
             for cid in CIDS for fam in FAMILIES[:2]]
    return Context(items, {}, {}, {cid: [(100, 200), (300, 400)] for cid in CIDS})


def _retriever(rung_n):
    def retrieve(query, contract_id, k):
        # Later rungs find the gold span for both families; earlier ones miss one.
        found = rung_n >= 2 or "equity" in query
        start, end = (100, 200) if found else (300, 400)
        return Retrieved(hits=[_hit(contract_id or "edgar_a", start, end)], ms=1.0 + rung_n, context=[])
    return retrieve


@pytest.fixture
def m3_tree(tmp_path):
    out, out_m3, data_m3, edgar = tmp_path / "out", tmp_path / "out" / "m3", tmp_path / "data_m3", tmp_path / "edgar"
    ctx = _ctx()
    for n, r in enumerate(("T-R1", "T-R2", "T-R3", "T-R4", "T-R5", "T-R6"), start=1):
        evaluate(ctx, r, _retriever(n), out_m3, n_boot=50)
    for n, r in enumerate(("T-R6-corpus", "T-R7-corpus"), start=6):
        evaluate(ctx, r, _retriever(n), out_m3, n_boot=50, scope="corpus")
    for name in ("r5", "r5_llm", "r5_llm_append"):
        evaluate(ctx, name, _retriever(3), out, n_boot=50)
    _write(out_m3 / "r7_scope.json", {"by_split": {"report": {"right": 3, "wrong": 1, "ambiguous": 1}}})
    rungs = {f"R{i}": {"human": 0.1 * i, "machine": 0.1 * i} for i in range(1, 7)}
    _write(out_m3 / "tier.json", {
        "contracts": 2, "items": 4, "kept": 3, "match": {"mean": 0.5, "lo": 0.25, "hi": 0.75},
        "rungs": rungs, "tau": None, "tau_lo": None, "tau_hi": None,
        "human_order": ["R6", "R5"], "machine_order": ["R5", "R6"]})
    by_family = {fam: {"kept": 2, "absent": 0, "disagree": 0, "one_found": 0, "error": 0} for fam in FAMILIES}
    _write(data_m3 / "tmachine_summary.json", {
        "contracts": 2, "complete": 2, "calls_made": 8, "fallback_contracts": 0, "kept": 4, "absent": 0,
        "disagree": 0, "one_found": 0, "error": 0, "by_family": by_family})
    _jsonl(data_m3 / "tmachine_ledger.jsonl", [
        {"key": "a|claude-opus-5-5|edgar_a|1", "model": "claude-opus-5-5"},
        {"key": "b|claude-sonnet-5-5|edgar_a|1", "model": "claude-sonnet-5-5"}])
    _write(data_m3 / "deals_summary.json", {
        "deals": 2, "maud_deals": 0, "aliases": 3, "schedule_tagged": 1, "amendments_linked": 0,
        "amendments_unlinked": 0, "passages_superseded": 0})
    _write(edgar / "summary.json", {"deals": 3, "kept": 2, "excluded_not_merger": 1, "amendments": 0, "aliases": 3})
    db = tmp_path / "deals.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE passages(contract_id TEXT, kind TEXT)")
    conn.executemany("INSERT INTO passages VALUES (?, ?)", [("edgar_a", "body"), ("edgar_d", "body"), ("edgar_a", "toc")])
    conn.commit()
    conn.close()
    return out_m3, out, data_m3, edgar, db


def test_build_m3_reads_every_input(m3_tree):
    f = build_m3(*m3_tree, n_boot=50)
    assert f["m3_corpus_kept"] == 2 and f["m3_tm_kept"] == 4
    assert f["m3_tm_equity_awards_agreement_rate"] == 1.0
    assert f["m3_tm_model_a"] == "claude-opus-5-5"
    assert {"m3_t_r1_report_recall_at_5", "m3_t_r7_corpus_report_recall_at_5",
            "m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5_delta", "m3_tier_tau", "m3_tier_match_rate",
            "m3_r5_llm_append_report_recall_at_5", "m3_r7_right"} <= set(f)
    assert f["m3_deals_passages"] == 2 and f["m3_tech_passages"] == 2 and f["m3_r7_none"] == 0
    assert f["m3_t_report_items"] == 2 and f["m3_t_report_contracts"] == 1
    assert f["m3_tier_tau"] is None and f["m3_tier_human_order"] == "R6 > R5"


def test_tier_with_nothing_kept_gives_none_facts(m3_tree):
    path = m3_tree[0] / "tier.json"
    tier = json.loads(path.read_text())
    tier["match"] = None
    tier["rungs"] = {f"R{i}": {"human": None, "machine": None} for i in range(1, 7)}
    tier["human_order"] = tier["machine_order"] = []
    path.write_text(json.dumps(tier))
    f = build_m3(*m3_tree, n_boot=50)
    assert f["m3_tier_match_rate"] is None and f["m3_tier_match_rate_lo"] is None
    assert f["m3_tier_r1_human_recall_at_5"] is None


def test_present_m3(m3_tree, tmp_path):
    assert present_m3(m3_tree[0]) and not present_m3(tmp_path / "nowhere")


def test_missing_inputs_are_named(m3_tree):
    (m3_tree[0] / "tier.json").unlink()
    with pytest.raises(FileNotFoundError, match="tier.json"):
        build_m3(*m3_tree, n_boot=50)


def test_unstable_facts_are_recognised():
    from facts.m2 import is_unstable
    assert is_unstable("m3_t_r1_latency_ms_p95") and is_unstable("m3_deals_index_bytes")
    assert not is_unstable("m3_t_r1_report_recall_at_5")


NEW_SINCE_RERUN = ("m3_t_bare_r1_report_recall_at_5", "m3_cmp_t_bare_r1_vs_t_r1_recall_at_5_delta",
                   "m3_t_bare_r1_equity_awards_recall_at_5", "m3_t_r1_context_tokens_mean",
                   "m3_t_bare_r6_context_tokens_mean", "m3_t_r7_corpus_context_tokens_mean")


def _rerun(m3_tree):
    out_m3, _, data_m3, _, _ = m3_tree
    for n in range(1, 7):
        evaluate(_ctx(), f"T-bare-R{n}", _retriever(n - 1), out_m3, n_boot=50, count_tokens=len)
    for name, extra in (("deals_summary.json", {"maud_duplicates": 2, "maud_duplicate_pairs": [["c", "e"]] * 2}),
                        ("tmachine_summary.json", {"truncated_topics": 3, "split_groups": 1})):
        doc = json.loads((data_m3 / name).read_text())
        (data_m3 / name).write_text(json.dumps(doc | extra))


def test_facts_from_the_fix_wave_are_absent_until_the_rerun(m3_tree):
    f = build_m3(*m3_tree, n_boot=50)
    assert not [k for k in NEW_SINCE_RERUN + ("m3_deals_maud_duplicates", "m3_tm_truncated_topics",
                                               "m3_tm_split_contracts") if k in f]


def test_bare_question_facts_and_their_paired_change(m3_tree):
    _rerun(m3_tree)
    f = build_m3(*m3_tree, n_boot=50)
    assert set(NEW_SINCE_RERUN) <= set(f)
    for n in range(1, 7):
        assert f"m3_t_bare_r{n}_report_recall_at_5_lo" in f and f"m3_cmp_t_bare_r{n}_vs_t_r{n}_recall_at_5_hi" in f
    # bare R1 uses the R0 retriever (misses termination_fee), named R1 the R1 one: the same, so no change
    assert f["m3_cmp_t_bare_r1_vs_t_r1_recall_at_5_delta"] == 0.0
    # bare R2 misses termination_fee where named R2 finds it: bare minus named is negative
    assert f["m3_cmp_t_bare_r2_vs_t_r2_recall_at_5_delta"] == -0.5
    assert f["m3_t_bare_r2_termination_fee_recall_at_5"] == 0.0
    assert f["m3_t_bare_r1_context_tokens_mean"] == 0.0 and f["m3_t_r1_context_tokens_mean"] is None
    assert f["m3_deals_maud_duplicates"] == 2
    assert f["m3_tm_truncated_topics"] == 3 and f["m3_tm_split_contracts"] == 1


def test_a_partial_bare_run_is_named(m3_tree):
    _rerun(m3_tree)
    (m3_tree[0] / "t_bare_r4.json").unlink()
    with pytest.raises(FileNotFoundError, match="t_bare_r4.json"):
        build_m3(*m3_tree, n_boot=50)
