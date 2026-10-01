import sqlite3
import time
from pathlib import Path

from evals.run_rung import K, METRICS, evaluate, load_context
from retrieval.bm25 import search
from retrieval.result import CONTEXT_K, Retrieved

__all__ = ["K", "METRICS", "run"]


def run(db_path: Path, csv_paths: list[Path], contracts_dir: Path, out_dir: Path, n_boot: int = 2000) -> dict:
    ctx = load_context(db_path, csv_paths, contracts_dir)
    conn = sqlite3.connect(db_path)

    def retrieve(query, contract_id, k):
        t0 = time.perf_counter()
        hits = search(conn, query, contract_id=contract_id, k=k)
        ms = (time.perf_counter() - t0) * 1000.0
        return Retrieved(hits, ms, [ctx.texts[h.contract_id][h.start:h.end] for h in hits[:CONTEXT_K]])
    return evaluate(ctx, "R1", retrieve, out_dir, n_boot=n_boot)
