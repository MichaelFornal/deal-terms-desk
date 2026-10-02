import json

import pytest

from evals.compare import load_items, paired_bootstrap


def rows(values, split="report", category="Knowledge"):
    return {f"c{c}|q{i}": {"item_id": f"c{c}|q{i}", "contract_id": f"c{c}", "split": split,
                           "category": category, "recall@5": v}
            for c, vs in enumerate(values) for i, v in enumerate(vs)}


def test_identical_rungs_have_zero_difference():
    a = rows([[1.0, 0.0], [0.5, 0.5], [0.0, 1.0]])
    out = paired_bootstrap(a, a, "recall@5", n_boot=200)
    assert out["delta"] == 0 and out["lo"] == 0 and out["hi"] == 0
    assert out["n_items"] == 6 and out["n_clusters"] == 3


def test_a_uniform_gain_has_a_degenerate_interval_at_the_gain():
    a = rows([[0.2, 0.4], [0.1, 0.3]])
    b = {k: {**r, "recall@5": r["recall@5"] + 0.25} for k, r in a.items()}
    out = paired_bootstrap(a, b, "recall@5", n_boot=200)
    assert out["delta"] == pytest.approx(0.25)
    assert out["lo"] == pytest.approx(0.25) and out["hi"] == pytest.approx(0.25)
    assert out["b_mean"] - out["a_mean"] == pytest.approx(0.25)


def test_a_gain_from_one_agreement_has_an_interval_reaching_zero():
    a = rows([[0.0]] * 10)
    b = dict(a)
    b["c0|q0"] = {**a["c0|q0"], "recall@5": 1.0}
    out = paired_bootstrap(a, b, "recall@5", n_boot=500)
    assert out["delta"] == pytest.approx(0.1)
    assert out["lo"] == 0.0


def test_rungs_scored_on_different_items_are_refused():
    a = rows([[1.0, 0.0]])
    b = rows([[1.0]])
    with pytest.raises(ValueError, match="different items"):
        paired_bootstrap(a, b, "recall@5")


def test_split_and_category_filters_apply_to_both_rungs():
    a = {**rows([[0.0]], split="tune"), **{k + "r": {**v, "item_id": k + "r"} for k, v in rows([[0.5]]).items()}}
    b = {k: {**v, "recall@5": v["recall@5"] + 0.5} for k, v in a.items()}
    assert paired_bootstrap(a, b, "recall@5", split="report", n_boot=50)["n_items"] == 1
    with pytest.raises(ValueError, match="no items"):
        paired_bootstrap(a, b, "recall@5", category="Remedies")


def test_load_items_reads_the_m1_items_format(tmp_path):
    p = tmp_path / "r1_items.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows([[1.0, 0.0]]).values()))
    assert set(load_items(p)) == {"c0|q0", "c0|q1"}
