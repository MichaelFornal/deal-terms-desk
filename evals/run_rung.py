import json
import os
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Callable

from evals.bootstrap import cluster_bootstrap, split_of
from evals.items import Item, build_items
from evals.maud_labels import load_rows
from evals.metrics import char_precision_at_k, char_recall_at_k, is_relevant, mrr, ndcg_at_k, recall_at_k
from pipeline.normalise import load_contract
from retrieval.result import Retrieved

METRICS = ("recall@1", "recall@5", "recall@10", "mrr@10", "ndcg@10")
K = 10
Retriever = Callable[[str, str | None, int], Retrieved]


@dataclass
class Context:
    items: list[Item]
    alignment: dict
    texts: dict[str, str]
    passages: dict[str, list[tuple[int, int]]]


def load_context(db_path: Path, csv_paths: list[Path], contracts_dir: Path) -> Context:
    conn = sqlite3.connect(db_path)
    contract_ids = [r[0] for r in conn.execute("SELECT contract_id FROM contracts ORDER BY contract_id")]
    texts = {cid: load_contract(Path(contracts_dir) / f"{cid}.txt") for cid in contract_ids}
    toc: dict[str, list[tuple[int, int]]] = defaultdict(list)
    passages: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for cid, s, e, kind in conn.execute("SELECT contract_id, start_char, end_char, kind FROM passages"):
        (toc if kind == "toc" else passages)[cid].append((s, e))
    items, alignment = build_items(load_rows(csv_paths), texts, toc=dict(toc))
    conn.close()
    return Context(items, alignment, texts, dict(passages))


def _summarise(per_item: list[dict], metrics: tuple[str, ...], n_boot: int) -> dict:
    out = {}
    for metric in metrics:
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


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text("".join(json.dumps(r, sort_keys=True) + "\n" for r in rows), encoding="utf-8")
    tmp.replace(path)


def evaluate(ctx: Context, rung: str, retrieve: Retriever, out_dir: Path, n_boot: int = 2000,
             count_tokens: Callable[[str], int] | None = None, scope: str = "within-agreement", k: int = K,
             char_ks: tuple[int, ...] = (), extra: dict | None = None) -> dict:
    metrics = METRICS + tuple(f"char_{m}@{c}" for c in char_ks for m in ("recall", "precision"))
    load_before = list(os.getloadavg())
    per_item = []
    for item in ctx.items:
        got = retrieve(item.query, item.contract_id if scope == "within-agreement" else None, k)
        # A hit from another agreement can never be relevant: blank its span before scoring.
        hits = [h if h.contract_id == item.contract_id else replace(h, start=-1, end=-1) for h in got.hits]
        n_relevant = sum(1 for s, e in ctx.passages.get(item.contract_id, []) if is_relevant(s, e, item.gold))
        row = {
            "item_id": item.item_id,
            "contract_id": item.contract_id,
            "category": item.category,
            "query": item.query,
            "split": split_of(item.contract_id),
            "recall@1": recall_at_k(hits, item.gold, 1),
            "recall@5": recall_at_k(hits, item.gold, 5),
            "recall@10": recall_at_k(hits, item.gold, 10),
            "mrr@10": mrr(hits, item.gold, K),
            "ndcg@10": ndcg_at_k(hits, item.gold, n_relevant, K),
            "gold": [list(g) for g in item.gold],
            "top_passage_ids": [h.passage_id for h in got.hits[:K]],
            "latency_ms": got.ms,
            "context_tokens": count_tokens("\n\n".join(got.context)) if count_tokens else None,
        }
        for c in char_ks:
            row[f"char_recall@{c}"] = char_recall_at_k(hits, item.gold, c)
            row[f"char_precision@{c}"] = char_precision_at_k(hits, item.gold, c)
        per_item.append(row)
    if not per_item:
        raise ValueError("no scorable eval items: check that the index and the label CSVs describe the same contracts")
    latencies = sorted(r["latency_ms"] for r in per_item)
    tokens = [r["context_tokens"] for r in per_item if r["context_tokens"] is not None]
    result = {
        "rung": rung,
        "scope": scope,
        "alignment": ctx.alignment,
        "overall": _summarise(per_item, metrics, n_boot),
        "by_split": {
            split: _summarise([r for r in per_item if r["split"] == split], metrics, n_boot)
            for split in sorted({r["split"] for r in per_item})
        },
        "by_category": {
            cat: _summarise([r for r in per_item if r["category"] == cat], metrics, n_boot)
            for cat in sorted({r["category"] for r in per_item})
        },
        "latency_ms": {"p50": _percentile(latencies, 0.50), "p95": _percentile(latencies, 0.95)},
        "context_tokens": {"mean": sum(tokens) / len(tokens)} if tokens else None,
        "load": {"before": load_before, "after": list(os.getloadavg())},
        "extra": extra or {},
    }
    name = rung.lower().replace("-", "_")
    out_dir = Path(out_dir)
    _write_json(out_dir / "alignment.json", ctx.alignment)
    _write_jsonl(out_dir / f"{name}_items.jsonl", sorted(per_item, key=lambda r: r["item_id"]))
    _write_json(out_dir / f"{name}.json", result)
    return result
