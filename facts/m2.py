import json
import os
import re
import sqlite3
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap
from evals.compare import load_items, paired_bootstrap
from evals.failures import CLASSES
from evals.tune import MAX_P95_MS
from facts.queries import CATEGORIES, REPORT_METRICS

LADDER = ("r1", "r2", "r3", "r4", "r5", "r6")
SIDE = ("r3_fixed", "r5_llm")
CORPUS = ("r1_corpus", "best_corpus")
CMP_METRICS = {"recall_at_5": "recall@5", "mrr_at_10": "mrr@10", "ndcg_at_10": "ndcg@10"}
CHAR_KS = (1, 2, 4, 8, 16, 32, 64)
CEILING_LO = 0.95
LBR_METHODS = ("naive", "rcts", "rcts_cohere")


def is_unstable(name: str) -> bool:
    return "latency_ms" in name or "load_avg" in name or name.endswith("index_bytes")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def present(out_dir: Path) -> bool:
    return (Path(out_dir) / "r2.json").exists()


def _required(out_dir: Path) -> list[Path]:
    names = [f"{r}.json" for r in LADDER + SIDE + CORPUS] + [f"{r}_items.jsonl" for r in LADDER + SIDE]
    names += [f"failures_{r}.json" for r in LADDER] + ["disputes.json"]
    return [Path(out_dir) / n for n in names]


def _ci(f: dict, name: str, block: dict) -> None:
    f[name] = round(block["mean"], 4)
    f[name + "_lo"] = round(block["lo"], 4)
    f[name + "_hi"] = round(block["hi"], 4)


def _delta(f: dict, name: str, cmp: dict) -> None:
    f[name + "_delta"] = round(cmp["delta"], 4)
    f[name + "_lo"] = round(cmp["lo"], 4)
    f[name + "_hi"] = round(cmp["hi"], 4)


def _json(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def build_m2(out_dir: Path, index_db: Path, fixed_db: Path, settings_path: Path, lexicon_path: Path,
             external_path: Path, n_boot: int = 2000) -> dict:
    out_dir = Path(out_dir)
    needed = _required(out_dir) + [Path(p) for p in (fixed_db, settings_path, lexicon_path, external_path)]
    missing = [str(p) for p in needed if not p.exists()]
    if missing:
        raise FileNotFoundError("M2 inputs missing: " + ", ".join(missing))
    res = {r: _json(out_dir / f"{r}.json") for r in LADDER + SIDE + CORPUS}
    items = {r: load_items(out_dir / f"{r}_items.jsonl") for r in LADDER + SIDE}
    f: dict = {}

    for r in LADDER + SIDE:
        report = res[r]["by_split"]["report"]
        for name, key in REPORT_METRICS.items():
            _ci(f, f"m2_{r}_report_{name}", report[key])
        f[f"m2_{r}_latency_ms_p50"] = round(res[r]["latency_ms"]["p50"], 2)
        f[f"m2_{r}_latency_ms_p95"] = round(res[r]["latency_ms"]["p95"], 2)
        f[f"m2_{r}_load_avg"] = round(res[r]["load"]["before"][0], 2)
        tokens = res[r]["context_tokens"]
        f[f"m2_{r}_context_tokens_mean"] = round(tokens["mean"], 1) if tokens else None
    f["m2_report_items"] = res["r1"]["by_split"]["report"]["recall@5"]["n_items"]
    f["m2_report_contracts"] = res["r1"]["by_split"]["report"]["recall@5"]["n_clusters"]
    f["m2_deal_points"] = len({i.split("|", 1)[1] for i in items["r1"]})

    for i, r in enumerate(LADDER[1:], start=1):
        for name, key in CMP_METRICS.items():
            _delta(f, f"m2_cmp_{r}_vs_r1_{name}", paired_bootstrap(items["r1"], items[r], key, n_boot=n_boot))
            if i > 1:
                prev = LADDER[i - 1]
                _delta(f, f"m2_cmp_{r}_vs_prev_{name}", paired_bootstrap(items[prev], items[r], key, n_boot=n_boot))
    for name, key in CMP_METRICS.items():
        _delta(f, f"m2_cmp_r3_fixed_vs_r3_{name}", paired_bootstrap(items["r3"], items["r3_fixed"], key, n_boot=n_boot))
        _delta(f, f"m2_cmp_r5_llm_vs_r5_{name}", paired_bootstrap(items["r5"], items["r5_llm"], key, n_boot=n_boot))

    for s, category in CATEGORIES.items():
        rows = [row for row in items["r1"].values() if row["split"] == "report" and row["category"] == category]
        f[f"m2_cat_{s}_items"] = len(rows)
        if not rows:
            continue
        by_contract: dict[str, list[float]] = defaultdict(list)
        for row in rows:
            by_contract[row["contract_id"]].append(row["recall@5"])
        r1 = cluster_bootstrap(by_contract, n_boot=n_boot)
        f[f"m2_cat_{s}_contracts"] = len(by_contract)
        f[f"m2_cat_{s}_ceiling"] = r1["lo"] >= CEILING_LO
        f[f"m2_r1_cat_{s}_recall_at_5"] = round(r1["mean"], 4)
        for r in LADDER[1:]:
            cmp = paired_bootstrap(items["r1"], items[r], "recall@5", category=category, n_boot=n_boot)
            f[f"m2_{r}_cat_{s}_recall_at_5"] = round(cmp["b_mean"], 4)
            _delta(f, f"m2_cmp_{r}_vs_r1_cat_{s}_recall_at_5", cmp)

    for r in LADDER:
        fail = _json(out_dir / f"failures_{r}.json")["by_split"]["report"]
        f[f"m2_fail_{r}_misses"] = fail["misses"]
        for c in CLASSES:
            f[f"m2_fail_{r}_{c}"] = fail[c]
    disputes = _json(out_dir / "disputes.json")
    _ci(f, "m2_machine_disputed_share", disputes["share"])
    f["m2_machine_disputed_n"] = disputes["sample"]
    f["m2_machine_disputed_rung"] = disputes["rung"]
    f["m2_machine_disputed_model"] = disputes["model"]

    tuned = _json(settings_path)
    for key in ("depth", "rrf_k0", "reranker", "rerank_depth"):
        f[f"m2_tuned_{key}"] = tuned["settings"][key]
    f["m2_tuned_live_path_ok"] = tuned["live_path_ok"]
    f["m2_tuned_items"] = tuned["tuned_on"]["items"]
    f["m2_tuned_contracts"] = tuned["tuned_on"]["contracts"]
    f["m2_tune_max_p95_ms"] = MAX_P95_MS
    for row in tuned["evidence"]["rerankers"]:
        f[f"m2_bake_{slug(row['reranker'])}_recall_at_5"] = row["recall@5"]
        f[f"m2_bake_{slug(row['reranker'])}_p95_ms"] = row["p95_ms"]

    lexicon = _json(lexicon_path)
    f["m2_lexicon_entries"] = len(lexicon["entries"])
    f["m2_lexicon_model"] = lexicon["_meta"]["model"]
    llm = res["r5_llm"]["extra"]
    f["m2_llm_rewrite_model"] = llm["model"]
    f["m2_llm_rewrite_queries"] = llm["queries"]
    f["m2_llm_rewrite_input_tokens_mean"] = round(llm["input_tokens_mean"], 1)
    f["m2_llm_rewrite_output_tokens_mean"] = round(llm["output_tokens_mean"], 1)

    conn = sqlite3.connect(index_db)
    model, vectors, truncated = conn.execute("SELECT model, vectors, truncated FROM vec_meta").fetchone()
    indexed = conn.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]
    f["m2_vec_model"], f["m2_vec_passages"], f["m2_vec_truncated"] = model, vectors, truncated
    f["m2_defs_per_passage_mean"] = round(conn.execute("SELECT COUNT(*) FROM passage_defs").fetchone()[0] / indexed, 2)
    f["m2_passages_with_defs_share"] = round(
        conn.execute("SELECT COUNT(DISTINCT passage_id) FROM passage_defs").fetchone()[0] / indexed, 4)
    f["m2_index_bytes"] = os.path.getsize(index_db)
    fixed = sqlite3.connect(fixed_db)
    f["m2_fixed_size_chars"] = fixed.execute("SELECT size FROM chunking").fetchone()[0]
    f["m2_fixed_passages_indexed"] = fixed.execute("SELECT COUNT(*) FROM passages_fts").fetchone()[0]

    for which in CORPUS:
        overall = res[which]["overall"]
        f[f"m2_{which}_rung"] = res[which]["extra"].get("rung", "R1")
        f[f"m2_{which}_recall_at_5"] = round(overall["recall@5"]["mean"], 4)
        for k in CHAR_KS:
            f[f"m2_{which}_char_recall_at_{k}_pct"] = round(100 * overall[f"char_recall@{k}"]["mean"], 2)
            f[f"m2_{which}_char_precision_at_{k}_pct"] = round(100 * overall[f"char_precision@{k}"]["mean"], 2)

    ext = _json(external_path)["legalbench_rag"]
    if list(ext["k"]) != list(CHAR_KS):
        raise ValueError(f"facts/external.json k {ext['k']} differs from CHAR_KS {CHAR_KS}")
    f["m2_lbr_verified"] = ext["verified_against_pdf"]
    f["m2_lbr_source"] = ext["source"]
    for m in LBR_METHODS:
        method = ext["methods"][m]
        f[f"m2_lbr_{m}_table"] = method["table"]
        for k, p, r in zip(ext["k"], method["precision_pct"], method["recall_pct"]):
            f[f"m2_lbr_{m}_precision_at_{k}_pct"] = p
            f[f"m2_lbr_{m}_recall_at_{k}_pct"] = r
    return dict(sorted(f.items()))
