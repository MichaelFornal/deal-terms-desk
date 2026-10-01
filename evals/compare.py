import json
from collections import defaultdict
from pathlib import Path

from evals.bootstrap import cluster_bootstrap


def load_items(path: Path) -> dict[str, dict]:
    out = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if line.strip():
            row = json.loads(line)
            out[row["item_id"]] = row
    return out


def _select(rows: dict[str, dict], split: str | None, category: str | None) -> dict[str, dict]:
    return {i: r for i, r in rows.items()
            if (split is None or r["split"] == split) and (category is None or r["category"] == category)}


def paired_bootstrap(a: dict[str, dict], b: dict[str, dict], metric: str, split: str | None = "report",
                     category: str | None = None, n_boot: int = 2000, seed: int = 0) -> dict:
    """b minus a on the same items, with an interval from resampling agreements."""
    a, b = _select(a, split, category), _select(b, split, category)
    if set(a) != set(b):
        raise ValueError(f"rungs were scored on different items ({len(set(a) - set(b))} only in the first, "
                         f"{len(set(b) - set(a))} only in the second); rerun both on the same eval set")
    if not a:
        raise ValueError("no items to compare after the split and category filters")
    diffs: dict[str, list[float]] = defaultdict(list)
    for item_id in sorted(a):
        diffs[a[item_id]["contract_id"]].append(b[item_id][metric] - a[item_id][metric])
    ci = cluster_bootstrap(diffs, n_boot=n_boot, seed=seed)
    n = len(a)
    return {"delta": ci["mean"], "lo": ci["lo"], "hi": ci["hi"], "n_items": ci["n_items"],
            "n_clusters": ci["n_clusters"],
            "a_mean": sum(r[metric] for r in a.values()) / n, "b_mean": sum(r[metric] for r in b.values()) / n}
