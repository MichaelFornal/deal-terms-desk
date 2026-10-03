import pytest

from evals.tier import tau_b, tier_report, tier_sample, tier_topics


def test_tau_b_known_values():
    assert tau_b([1, 2, 3], [1, 2, 3]) == 1.0
    assert tau_b([1, 2, 3], [3, 2, 1]) == -1.0
    assert tau_b([1, 2, 2, 3], [1, 3, 2, 4]) == pytest.approx(0.9129, abs=1e-4)  # scipy.stats.kendalltau
    assert tau_b([1, 1, 1], [1, 2, 3]) is None


def rows_for(cids, split="report"):
    out = {}
    for c in cids:
        for t in ("Type A", "Type B"):
            out[f"{c}|{t}"] = {"item_id": f"{c}|{t}", "contract_id": c, "split": split, "query": f"{t} question",
                               "gold": [[100, 200]], "recall@5": 1.0, "top_passage_ids": [1, 2, 3, 4, 5]}
    return out


def test_sample_is_seeded_sorted_and_report_only():
    rows = rows_for([f"contract_{i}" for i in range(50)]) | rows_for(["contract_t"], split="tune")
    a, b = tier_sample(rows, n=10), tier_sample(rows, n=10)
    assert a == b == sorted(a) and len(a) == 10 and "contract_t" not in a


def test_topics_use_short_keys():
    topics, keymap = tier_topics(rows_for(["contract_1"]), "contract_1")
    assert topics == {"T1": "Type A question", "T2": "Type B question"}
    assert keymap == {"T1": "contract_1|Type A", "T2": "contract_1|Type B"}


def test_report_match_rate_and_tau():
    cids = ["contract_1", "contract_2"]
    base = rows_for(cids)
    spans = {1: (100, 200), 2: (300, 400), 3: (500, 600), 4: (700, 800), 5: (900, 1000)}
    # Machine gold: Type A agrees with the lawyers (100-200); Type B points elsewhere (300-400).
    label_rows, keymap = [], {}
    for c in cids:
        for key, t, gold in (("T1", "Type A", [[120, 180]]), ("T2", "Type B", [[300, 350]])):
            label_rows.append({"contract_id": c, "family": key, "status": "kept", "gold": gold})
            keymap[(c, key)] = f"{c}|{t}"
    rung_rows = {}
    for n, r in enumerate(("R1", "R2", "R3", "R4", "R5", "R6")):
        rows = {}
        for i, row in base.items():
            hit_human = n >= 3          # later rungs find the lawyers' span ...
            hit_machine_b = n >= 3      # ... and, for Type B, the machine's span too
            top = ([1] if hit_human else [9]) + ([2] if hit_machine_b and row["item_id"].endswith("B") else [8]) + [7, 6, 5]
            rows[i] = row | {"recall@5": 1.0 if hit_human else 0.0, "top_passage_ids": top}
        rung_rows[r] = rows
    spans |= {6: (1100, 1200), 7: (1300, 1400), 8: (1500, 1600), 9: (1700, 1800)}
    got = tier_report(label_rows, keymap, rung_rows, spans, n_boot=200)
    assert got["kept"] == 4 and got["match"]["mean"] == 0.5
    assert got["rungs"]["R1"]["human"] == 0.0 and got["rungs"]["R6"]["machine"] == 1.0
    assert got["tau"] == pytest.approx(1.0)
