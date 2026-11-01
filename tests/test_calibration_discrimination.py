"""Patch 2.2 (session E5): AUROC and the Murphy terms beside the calibration measures. Offline, simulated votes."""

import numpy as np
import pytest

from autoagentnet.evidence import calibration as C


def test_auroc_known_values():
    assert C.auroc([0.9, 0.8, 0.2, 0.1], [1, 1, 0, 0]) == 1.0
    assert C.auroc([0.1, 0.2, 0.8, 0.9], [1, 1, 0, 0]) == 0.0
    assert C.auroc([0.5, 0.5, 0.5, 0.5], [1, 0, 1, 0]) == 0.5
    assert np.isnan(C.auroc([0.3, 0.4], [1, 1]))


def test_murphy_terms_add_up_to_brier_on_discrete_confidence():
    rng = np.random.default_rng(0)
    c = rng.choice([0.2, 0.4, 0.6, 0.8, 1.0], 500)
    y = (rng.random(500) < c * 0.9).astype(float)
    m = C.murphy(c, y)
    assert C.brier(c, y) == pytest.approx(m["reliability"] - m["resolution"] + m["uncertainty"])
    assert {"auroc", "resolution", "reliability"} <= set(C.report(c, y))


def votes(n_items, strong, weak, seed):
    """Per item: `strong` correlated voters (right with an item-level chance, wrong answers piling on one attractor)
    and `weak` near-random voters (uniform over 10 answers). Returns (share agreeing with the plurality, plurality
    right)."""
    rng = np.random.default_rng(seed)
    p_item = rng.beta(2, 2, n_items)
    share, right = [], []
    for i in range(n_items):
        a = [0 if rng.random() < p_item[i] else (1 if rng.random() < 0.7 else int(rng.integers(2, 10))) for _ in range(strong)]
        a += list(rng.integers(0, 10, weak))
        counts = np.bincount(a, minlength=10)
        top = int(np.argmax(counts))
        share.append(counts[top] / len(a))
        right.append(float(top == 0))
    return np.array(share), np.array(right)


def test_dilution_shrinks_the_gap_but_not_auroc():
    """Adding near-random voters pulls the vote share down toward accuracy (the overconfidence gap shrinks) without
    making the share rank right and wrong items any better (AUROC does not rise)."""
    base_c, base_y = votes(3000, strong=5, weak=0, seed=1)
    dil_c, dil_y = votes(3000, strong=5, weak=4, seed=1)
    base, diluted = C.report(base_c, base_y), C.report(dil_c, dil_y)
    assert diluted["gap"] < base["gap"] - 0.10
    assert diluted["auroc"] <= base["auroc"] + 0.01
