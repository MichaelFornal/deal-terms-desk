import json
import os
from dataclasses import asdict, replace
from pathlib import Path

from evals.bootstrap import split_of
from evals.metrics import recall_at_k
from evals.run_rung import Context
from retrieval.ladder import Ladder, Settings
from retrieval.models import RERANKERS
from retrieval.rerank_cache import CachedReranker

GRID_DEPTH = (20, 50, 100)
GRID_K0 = (10, 60)
PROBE_DEPTH = 20
GRID_RERANK_DEPTH = (10, 20, 30)
MAX_P95_MS = 3000.0
RULE = ("Fusion: highest tune recall@5 on R3 (ties: smaller depth, then larger k0). Reranker, then rerank depth: "
        "highest tune recall@5 on R4 among settings whose p95 latency on the development machine is at most "
        "MAX_P95_MS (ties: faster); if none qualifies, the fastest, with live_path_ok false.")


def _score(ladder: Ladder, rung: str, items) -> dict:
    recalls, ms = [], []
    for it in items:
        got = ladder.run(rung, it.query, it.contract_id, 10)
        recalls.append(recall_at_k(got.hits, it.gold, 5))
        ms.append(got.ms)
    ms.sort()
    return {"recall@5": round(sum(recalls) / len(recalls), 4),
            "p95_ms": round(ms[min(len(ms) - 1, int(0.95 * len(ms)))], 2), "n_items": len(items)}


def _pick(rows: list[dict]) -> tuple[dict, bool]:
    ok = [r for r in rows if r["p95_ms"] <= MAX_P95_MS]
    if not ok:
        return min(rows, key=lambda r: r["p95_ms"]), False
    return max(ok, key=lambda r: (r["recall@5"], -r["p95_ms"])), True


def tune(ctx: Context, conn, embedder, make_reranker, cache_path: Path, out_path: Path,
         rerankers: tuple[str, ...] = RERANKERS) -> dict:
    items = [i for i in ctx.items if split_of(i.contract_id) == "tune"]
    if not items:
        raise ValueError("no tune-split items to tune on")
    fusion = [{"depth": d, "rrf_k0": k0,
               **_score(Ladder(conn, ctx.texts, embedder, None, None, Settings(depth=d, rrf_k0=k0)), "R3", items)}
              for d in GRID_DEPTH for k0 in GRID_K0]
    best = max(fusion, key=lambda r: (r["recall@5"], -r["depth"], r["rrf_k0"]))
    base = Settings(depth=best["depth"], rrf_k0=best["rrf_k0"])
    made: dict[str, CachedReranker] = {}

    def run(name: str, rdepth: int) -> dict:
        if name not in made:
            made[name] = CachedReranker(make_reranker(name), cache_path)
        ladder = Ladder(conn, ctx.texts, embedder, made[name], None, replace(base, reranker=name, rerank_depth=rdepth))
        return {"reranker": name, "rerank_depth": rdepth, **_score(ladder, "R4", items)}

    bake = [run(name, PROBE_DEPTH) for name in rerankers]
    chosen, _ = _pick(bake)
    depths = [run(chosen["reranker"], d) for d in GRID_RERANK_DEPTH]
    final, live = _pick(depths)
    doc = {
        "settings": asdict(replace(base, reranker=final["reranker"], rerank_depth=final["rerank_depth"])),
        "live_path_ok": live,
        "rule": RULE.replace("MAX_P95_MS", f"{MAX_P95_MS:g} ms"),
        "tuned_on": {"split": "tune", "items": len(items), "contracts": len({i.contract_id for i in items})},
        "load": list(os.getloadavg()),
        "evidence": {"fusion": fusion, "rerankers": bake, "rerank_depth": depths},
    }
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    tmp.replace(out_path)
    return doc
