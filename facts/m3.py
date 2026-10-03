import sqlite3
from pathlib import Path

from evals.compare import load_items, paired_bootstrap
from evals.run_rung import _percentile
from evals.tmachine import FAMILIES
from facts.m0 import _rows
from facts.m2 import _ci, _delta, _json

T_LADDER = ("t_r1", "t_r2", "t_r3", "t_r4", "t_r5", "t_r6")
T_CORPUS = ("t_r6_corpus", "t_r7_corpus")
STATUSES = ("kept", "absent", "disagree", "one_found", "error")
SCOPE_OUTCOMES = ("right", "wrong", "ambiguous", "none")


def present_m3(out_m3: Path) -> bool:
    return (Path(out_m3) / "t_r1.json").exists()


def _model(ledger_rows: list[dict], pass_name: str) -> str | None:
    models = sorted({r["model"] for r in ledger_rows if r["key"].startswith(pass_name + "|")})
    return ", ".join(models) or None


def build_m3(out_m3, out_dir, data_m3, edgar_dir, deals_db, n_boot: int = 2000) -> dict:
    out_m3, out_dir, data_m3, edgar_dir, deals_db = map(Path, (out_m3, out_dir, data_m3, edgar_dir, deals_db))
    needed = ([out_m3 / f"{r}.json" for r in T_LADDER + T_CORPUS]
              + [out_m3 / f"{r}_items.jsonl" for r in T_LADDER + T_CORPUS]
              + [out_m3 / "r7_scope.json", out_m3 / "tier.json", out_dir / "r5_items.jsonl",
                 out_dir / "r5_llm_items.jsonl", out_dir / "r5_llm_append.json", out_dir / "r5_llm_append_items.jsonl",
                 data_m3 / "tmachine_summary.json", data_m3 / "tmachine_ledger.jsonl", data_m3 / "deals_summary.json",
                 edgar_dir / "summary.json", deals_db])
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        raise FileNotFoundError("M3 inputs missing: " + ", ".join(missing))
    f: dict = {}

    corpus = _json(edgar_dir / "summary.json")
    for k in ("deals", "kept", "excluded_not_merger", "amendments", "aliases"):
        f[f"m3_corpus_{k}"] = corpus[k]
    deals = _json(data_m3 / "deals_summary.json")
    for k in ("deals", "maud_deals", "aliases", "schedule_tagged", "amendments_linked", "amendments_unlinked",
              "passages_superseded"):
        f[f"m3_deals_{k}"] = deals[k]
    conn = sqlite3.connect(deals_db)
    f["m3_deals_passages"] = conn.execute("SELECT COUNT(*) FROM passages WHERE kind != 'toc'").fetchone()[0]
    f["m3_tech_passages"] = conn.execute("SELECT COUNT(*) FROM passages WHERE kind != 'toc'"
                                         " AND contract_id >= 'edgar_' AND contract_id < 'edgar`'").fetchone()[0]
    conn.close()
    f["m3_deals_index_bytes"] = deals_db.stat().st_size

    tm = _json(data_m3 / "tmachine_summary.json")
    for k in ("contracts", "complete", "fallback_contracts") + STATUSES:
        f[f"m3_tm_{k}"] = tm[k]
    ledger = _rows(data_m3 / "tmachine_ledger.jsonl")
    f["m3_tm_calls"] = len({r["key"] for r in ledger})
    f["m3_tm_model_a"], f["m3_tm_model_b"] = _model(ledger, "a"), _model(ledger, "b")
    for fam in FAMILIES:
        c = tm["by_family"].get(fam, dict.fromkeys(STATUSES, 0))
        for st in STATUSES:
            f[f"m3_tm_{fam}_{st}"] = c[st]
        decided = c["kept"] + c["disagree"] + c["one_found"]
        f[f"m3_tm_{fam}_agreement_rate"] = round(c["kept"] / decided, 4) if decided else None

    res = {r: _json(out_m3 / f"{r}.json") for r in T_LADDER + T_CORPUS}
    items = {r: load_items(out_m3 / f"{r}_items.jsonl") for r in T_LADDER + T_CORPUS}
    f["m3_t_report_items"] = res["t_r1"]["by_split"]["report"]["recall@5"]["n_items"]
    f["m3_t_report_contracts"] = res["t_r1"]["by_split"]["report"]["recall@5"]["n_clusters"]
    for r in T_LADDER + T_CORPUS:
        report = res[r]["by_split"]["report"]
        _ci(f, f"m3_{r}_report_recall_at_5", report["recall@5"])
        _ci(f, f"m3_{r}_report_mrr_at_10", report["mrr@10"])
        rows = [row for row in items[r].values() if row["split"] == "report"]
        f[f"m3_{r}_latency_ms_p95"] = round(_percentile(sorted(row["latency_ms"] for row in rows), 0.95), 2)
        for fam in FAMILIES:
            fr = [row["recall@5"] for row in rows if row["category"] == fam]
            f[f"m3_{r}_{fam}_recall_at_5"] = round(sum(fr) / len(fr), 4) if fr else None
    for i, r in enumerate(T_LADDER[1:], start=1):
        _delta(f, f"m3_cmp_{r}_vs_t_r1_recall_at_5", paired_bootstrap(items["t_r1"], items[r], "recall@5", n_boot=n_boot))
        if i > 1:
            _delta(f, f"m3_cmp_{r}_vs_prev_recall_at_5",
                   paired_bootstrap(items[T_LADDER[i - 1]], items[r], "recall@5", n_boot=n_boot))
    _delta(f, "m3_cmp_t_r7_vs_t_r6_corpus_recall_at_5",
           paired_bootstrap(items["t_r6_corpus"], items["t_r7_corpus"], "recall@5", n_boot=n_boot))
    scope = _json(out_m3 / "r7_scope.json")["by_split"].get("report", {})
    for o in SCOPE_OUTCOMES:
        f[f"m3_r7_{o}"] = scope.get(o, 0)

    tier = _json(out_m3 / "tier.json")
    for k in ("contracts", "items", "kept"):
        f[f"m3_tier_{k}"] = tier[k]
    if tier["match"] is None:
        for suffix in ("", "_lo", "_hi"):
            f[f"m3_tier_match_rate{suffix}"] = None
    else:
        _ci(f, "m3_tier_match_rate", tier["match"])
    for k in ("tau", "tau_lo", "tau_hi"):
        f[f"m3_tier_{k}"] = round(tier[k], 4) if tier[k] is not None else None
    for rung, v in tier["rungs"].items():
        for who in ("human", "machine"):
            f[f"m3_tier_{rung.lower()}_{who}_recall_at_5"] = round(v[who], 4) if v[who] is not None else None
    f["m3_tier_human_order"] = " > ".join(tier["human_order"])
    f["m3_tier_machine_order"] = " > ".join(tier["machine_order"])

    append = load_items(out_dir / "r5_llm_append_items.jsonl")
    _ci(f, "m3_r5_llm_append_report_recall_at_5", _json(out_dir / "r5_llm_append.json")["by_split"]["report"]["recall@5"])
    _delta(f, "m3_cmp_r5_llm_append_vs_r5_recall_at_5",
           paired_bootstrap(load_items(out_dir / "r5_items.jsonl"), append, "recall@5", n_boot=n_boot))
    _delta(f, "m3_cmp_r5_llm_append_vs_r5_llm_recall_at_5",
           paired_bootstrap(load_items(out_dir / "r5_llm_items.jsonl"), append, "recall@5", n_boot=n_boot))
    return f
