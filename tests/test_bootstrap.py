import pytest

from evals.bootstrap import cluster_bootstrap, split_of


def test_split_is_stable_and_roughly_thirty_seventy():
    ids = [f"contract_{i}" for i in range(152)]
    splits = [split_of(i) for i in ids]
    assert splits == [split_of(i) for i in ids]
    assert set(splits) == {"tune", "report"}
    assert 25 <= splits.count("tune") <= 70


def test_mean_is_over_all_items_not_over_clusters():
    got = cluster_bootstrap({"a": [1.0, 1.0, 1.0], "b": [0.0]}, n_boot=200)
    assert got["mean"] == 0.75
    assert got["n_items"] == 4 and got["n_clusters"] == 2


def test_interval_brackets_the_mean_and_is_reproducible():
    data = {f"c{i}": [float(i % 2)] * 3 for i in range(20)}
    a = cluster_bootstrap(data, n_boot=500, seed=7)
    b = cluster_bootstrap(data, n_boot=500, seed=7)
    assert a == b
    assert a["lo"] <= a["mean"] <= a["hi"]
    assert a["lo"] < a["hi"]


def test_identical_values_give_a_zero_width_interval():
    got = cluster_bootstrap({"a": [0.5, 0.5], "b": [0.5]}, n_boot=100)
    assert got["lo"] == got["hi"] == got["mean"] == 0.5


def test_single_cluster_still_returns_an_interval():
    got = cluster_bootstrap({"a": [0.0, 1.0]}, n_boot=50)
    assert got["mean"] == got["lo"] == got["hi"] == 0.5


def test_no_values_raises():
    with pytest.raises(ValueError):
        cluster_bootstrap({})
