"""Patch 2.3 (session E5): information about the truth beside n_eff. Offline, simulated panels."""

import numpy as np

from autoagentnet.pruning.criteria import set_information
from autoagentnet.pruning.replay import Panel


def panel(n=1500, seed=0):
    """Three good sources sharing item difficulty (right 50-90%), and one near-random source (uniform over 4
    answers, so right 25%, independent of everything)."""
    rng = np.random.default_rng(seed)
    ease = rng.normal(0, 1, n)
    cols = []
    for skill in (1.5, 1.0, 0.5):
        right = rng.random(n) < 1 / (1 + np.exp(-(skill + 1.5 * ease)))
        cols.append(np.where(right, 0, rng.integers(1, 4, n)))
    cols.append(rng.integers(0, 4, n))
    A = np.column_stack(cols)
    return Panel.from_arrays(A, (A == 0).astype(float), np.full(A.shape, 0.001), sources=["a", "b", "c", "noise"],
                             calls=[0, 0, 0, 0])


def test_near_random_source_raises_n_eff_but_adds_no_information():
    p = panel()
    good = set_information(p, [0, 1, 2])
    plus_noise = set_information(p, [0, 1, 2, 3])
    assert plus_noise["n_eff"] - good["n_eff"] > 0.5  # counted as almost a whole extra call
    assert abs(plus_noise["info_nats"] - good["info_nats"]) < 0.01  # but it says nothing about the truth
    assert plus_noise["info_per_dollar"] < good["info_per_dollar"]


def test_information_grows_with_a_good_source():
    p = panel()
    one, two = set_information(p, [0]), set_information(p, [0, 1])
    assert two["info_nats"] > one["info_nats"] > 0.05


def test_posthoc_table_runs_on_named_units():
    from analysis.information_posthoc import table

    rng = np.random.default_rng(3)
    A = np.column_stack([np.where(rng.random(400) < 0.7, 0, rng.integers(1, 4, 400)) for _ in range(3)] + [rng.integers(0, 4, 400)])
    p = Panel.from_arrays(A, (A == 0).astype(float), np.full(A.shape, 0.001), sources=["h:base"] * 3 + ["l:base"],
                          calls=[0, 1, 2, 0])
    t = table(p, {"h x3": ["h:base:0", "h:base:1", "h:base:2"], "l": ["l:base:0"]}).set_index("set")
    assert t.loc["l", "info_nats"] < 0.1 * t.loc["h x3", "info_nats"]  # the random source alone: pool effect only


def test_information_never_exceeds_the_truths_entropy():
    """Audit 68 finding 6: a near-perfect source made the old Gaussian-copula number pass ln 2."""
    rng = np.random.default_rng(5)
    n = 1000
    A = np.column_stack([np.where(rng.random(n) < 0.97, 0, rng.integers(1, 4, n)),
                         np.where(rng.random(n) < 0.5, 0, rng.integers(1, 4, n))])
    p = Panel.from_arrays(A, (A == 0).astype(float), np.full(A.shape, 0.001), sources=["sol", "h"], calls=[0, 0])
    r = set_information(p, [0, 1])
    assert 0 < r["info_nats"] <= r["h_nats"] <= np.log(2) + 1e-12
