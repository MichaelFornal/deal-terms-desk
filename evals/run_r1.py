import json
import sqlite3
import time
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap, split_of
from evals.items import build_items
from evals.maud_labels import load_rows
from evals.metrics import is_relevant, mrr, ndcg_at_k, recall_at_k
from pipeline.normalise import load_contract
from retrieval.bm25 import search

METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")
K = 10


def _summarise(per_item: list[dict], n_boot: int) -> dict:
    out = {}
    for metric in METRICS:
        by_contract: dict[str, list[float]] = defaultdict(list)
        for row in per_item:
            by_contract[row["contract_id"]].append(row[metric])
        out[metric] = cluster_bootstrap(by_contract, n_boot=n_boot)
    return out


def _percentile(sorted_values: list[float], q: float) -> float:
    return sorted_values[min(len(sorted_values) - 1, int(q * len(sorted_values)))]


def _write_json(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(path)


def run(db_path: Path, csv_paths: list[Path], contracts_dir: Path, out_dir: Path, n_boot: int = 2000) -> dict:
    conn = sqlite3.connect(db_path)
    contract_ids = [r[0] for r in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id")]
    texts = {cid: load_contract(Path(contracts_dir) / f"{cid}.txt") for cid in contract_ids}
    items, alignment = build_items(load_rows(csv_paths), texts)

    passages: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cid, s, e in conn.execute("SELECT contract_id, start_char, end_char FROM passages WHERE kind != 'toc'"):
        passages[cid].append((s, e))

    per_item = []
    latencies = []
    for item in items:
        t0 = time.perf_counter()
        hits = search(conn, item.query, contract_id=item.contract_id, k=K)
        latencies.append((time.perf_counter() - t0) * 1000.0)
        n_relevant = sum(1 for s, e in passages[item.contract_id] if is_relevant(s, e, item.gold))
        per_item.append({
            "item_id": item.item_id,
            "contract_id": item.contract_id,
            "category": item.category,
            "split": split_of(item.contract_id),
            "recall@1": recall_at_k(hits, item.gold, 1),
            "recall@5": recall_at_k(hits, item.gold, 5),
            "recall@10": recall_at_k(hits, item.gold, 10),
            "mrr@10": mrr(hits, item.gold, K),
            "ndcg@10": ndcg_at_k(hits, item.gold, n_relevant, K),
        })
    if not per_item:
        raise ValueError("no scorable eval items: check that the index and the label CSVs describe the same contracts")

    latencies.sort()
    result = {
        "rung": "R1",
        "scope": "within-agreement",
        "alignment": alignment,
        "overall": _summarise(per_item, n_boot),
        "by_split": {
            split: _summarise([r for r in per_item if r["split"] == split], n_boot)
            for split in sorted({r["split"] for r in per_item})
        },
        "by_category": {
            cat: _summarise([r for r in per_item if r["category"] == cat], n_boot)
            for cat in sorted({r["category"] for r in per_item})
        },
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
    }
    out_dir = Path(out_dir)
    _write_json(out_dir / "alignment.json", alignment)
    _write_json(out_dir / "r1.json", result)
    return result
