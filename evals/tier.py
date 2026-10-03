import math
import random
from collections import defaultdict
from types import SimpleNamespace

from evals.bootstrap import CI_HIGH, CI_LOW, cluster_bootstrap
from evals.metrics import recall_at_k

TIER_CONTRACTS = 30
SEED = 0
RUNG_NAMES = ("R1", "R2", "R3", "R4", "R5", "R6")
STATUSES = ("kept", "absent", "disagree", "one_found", "error")


def tier_sample(r1_rows: dict[str, dict], n: int = TIER_CONTRACTS, seed: int = SEED) -> list[str]:
    report = sorted({r["contract_id"] for r in r1_rows.values() if r["split"] == "report"})
    return sorted(random.Random(seed).sample(report, min(n, len(report))))


def tier_topics(r1_rows: dict[str, dict], cid: str) -> tuple[dict[str, str], dict[str, str]]:
    ids = sorted(i for i, r in r1_rows.items() if r["contract_id"] == cid)
    return ({f"T{n}": r1_rows[i]["query"] for n, i in enumerate(ids, start=1)},
            {f"T{n}": i for n, i in enumerate(ids, start=1)})


def tau_b(x: list[float], y: list[float]) -> float | None:
    conc = disc = tx = ty = 0
    for i in range(len(x)):
        for j in range(i + 1, len(x)):
            dx = (x[i] > x[j]) - (x[i] < x[j])
            dy = (y[i] > y[j]) - (y[i] < y[j])
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                tx += 1
            elif dy == 0:
                ty += 1
            elif dx == dy:
                conc += 1
            else:
                disc += 1
    denom = math.sqrt((conc + disc + tx) * (conc + disc + ty))
    return (conc - disc) / denom if denom else None


def _overlaps(a, b) -> bool:
    return any(s1 < e2 and s2 < e1 for s1, e1 in a for s2, e2 in b)


def _means(per_contract: dict[str, list[tuple[list[float], list[float]]]], cids: list[str]):
    h, m, n = [0.0] * len(RUNG_NAMES), [0.0] * len(RUNG_NAMES), 0
    for c in cids:
        for hv, mv in per_contract[c]:
            h = [a + b for a, b in zip(h, hv)]
            m = [a + b for a, b in zip(m, mv)]
            n += 1
    return [v / n for v in h], [v / n for v in m]


def tier_report(rows, keymap, rung_rows, spans, n_boot: int = 2000, seed: int = 0) -> dict:
    status = {st: sum(1 for r in rows if r["status"] == st) for st in STATUSES}
    kept = [r for r in rows if r["status"] == "kept"]
    match_by_contract: dict[str, list[float]] = defaultdict(list)
    per_contract: dict[str, list] = defaultdict(list)
    for r in kept:
        item_id = keymap[(r["contract_id"], r["family"])]
        human_gold = [tuple(g) for g in rung_rows["R1"][item_id]["gold"]]
        machine_gold = [tuple(g) for g in r["gold"]]
        match_by_contract[r["contract_id"]].append(1.0 if _overlaps(machine_gold, human_gold) else 0.0)
        hv, mv = [], []
        for rung in RUNG_NAMES:
            row = rung_rows[rung][item_id]
            hits = [SimpleNamespace(start=spans[p][0], end=spans[p][1]) for p in row["top_passage_ids"][:5]]
            hv.append(row["recall@5"])
            mv.append(recall_at_k(hits, machine_gold, 5))
        per_contract[r["contract_id"]].append((hv, mv))
    cids = sorted(per_contract)
    human, machine = _means(per_contract, cids)
    rng, taus = random.Random(seed), []
    for _ in range(n_boot):
        t = tau_b(*_means(per_contract, [cids[rng.randrange(len(cids))] for _ in cids]))
        if t is not None:
            taus.append(t)
    taus.sort()
    return {
        "contracts": len({r["contract_id"] for r in rows}), "items": len(rows), **status,
        "kept_rate": status["kept"] / len(rows) if rows else None,
        "match": cluster_bootstrap(match_by_contract, n_boot=n_boot, seed=seed),
        "rungs": {r: {"human": h, "machine": m} for r, h, m in zip(RUNG_NAMES, human, machine)},
        "tau": tau_b(human, machine),
        "tau_lo": taus[int(CI_LOW * len(taus))] if taus else None,
        "tau_hi": taus[min(len(taus) - 1, int(CI_HIGH * len(taus)))] if taus else None,
        "tau_defined": len(taus), "n_boot": n_boot,
        "human_order": [r for _, r in sorted(zip(human, RUNG_NAMES), key=lambda p: (-p[0], p[1]))],
        "machine_order": [r for _, r in sorted(zip(machine, RUNG_NAMES), key=lambda p: (-p[0], p[1]))],
    }
