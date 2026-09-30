import hashlib
import random

TUNE_TENTHS = 3
# The report says "95%"; tests/test_facts.py pins these so the two cannot drift apart.
CI_LOW = 0.025
CI_HIGH = 0.975


def split_of(contract_id: str) -> str:
    bucket = hashlib.sha1(contract_id.encode("utf-8")).digest()[0] % 10
    return "tune" if bucket < TUNE_TENTHS else "report"


def cluster_bootstrap(values_by_cluster: dict[str, list[float]], n_boot: int = 2000, seed: int = 0) -> dict:
    clusters = sorted(c for c, vs in values_by_cluster.items() if vs)
    if not clusters:
        raise ValueError("no values to bootstrap")
    sums = [sum(values_by_cluster[c]) for c in clusters]
    counts = [len(values_by_cluster[c]) for c in clusters]
    mean = sum(sums) / sum(counts)
    rng = random.Random(seed)
    stats = []
    for _ in range(n_boot):
        total = 0.0
        n = 0
        for _ in clusters:
            j = rng.randrange(len(clusters))
            total += sums[j]
            n += counts[j]
        stats.append(total / n)
    stats.sort()
    lo = stats[int(CI_LOW * n_boot)]
    hi = stats[min(n_boot - 1, int(CI_HIGH * n_boot))]
    return {"mean": mean, "lo": lo, "hi": hi, "n_items": sum(counts), "n_clusters": len(clusters)}
