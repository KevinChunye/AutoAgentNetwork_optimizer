"""Patch 2.4 (session E5): Dawid-Skene over sources (pooled repeats) vs over calls. Offline, simulated panels."""

import numpy as np
import pytest

from analysis.consensus_inversion import SAME, simulate
from autoagentnet.evidence.labelfree import dawid_skene, dawid_skene_pooled


def test_pooled_equals_plain_when_every_source_calls_once():
    rows = simulate(150, 1, 1.5, 0.45, 0.9, np.random.default_rng(0))[["item", "source", "answer"]]
    plain, t1 = dawid_skene(rows, SAME)
    pooled, t2 = dawid_skene_pooled(rows, SAME)
    assert np.allclose(plain.to_numpy(), pooled.to_numpy(), atol=1e-6)
    assert (t1["answer"].to_numpy() == t2["answer"].to_numpy()).all()


def test_correlated_majority_inverts_plain_but_not_pooled():
    """Five correlated calls of a weak source (piling on one wrong answer) against one strong and one medium call."""
    rows = simulate(300, 5, 1.5, 0.45, 0.9, np.random.default_rng(1))[["item", "source", "answer"]]
    plain, _ = dawid_skene(rows, SAME)
    pooled, _ = dawid_skene_pooled(rows, SAME)
    assert plain["strong"] < plain["weak"]  # the inversion
    assert pooled["strong"] > pooled["medium"] > pooled["weak"]
    assert pooled["weak"] == pytest.approx(0.45, abs=0.1)


def test_fixed_label_space_recovers_independent_sources():
    """Audit 68 finding 5: with one independent call per source, the observed-candidates model misranks the sources;
    the model with the simulation's 10 labels recovers their accuracies."""
    rows = simulate(1000, 1, 0.0, 0.45, 0.75, np.random.default_rng(4))
    truth = rows.groupby("source")["correct"].mean()
    plain, _ = dawid_skene(rows[["item", "source", "answer"]], SAME)
    assert plain["medium"] > plain["strong"]  # the misranking under the observed-candidates model
    fixed, _ = dawid_skene(rows[["item", "source", "answer"]], SAME, labels=10)
    for s in ("weak", "medium", "strong"):
        assert fixed[s] == pytest.approx(truth[s], abs=0.05), s
    assert fixed["strong"] > fixed["medium"] > fixed["weak"]
    pooled, _ = dawid_skene_pooled(rows[["item", "source", "answer"]], SAME, labels=10)
    assert np.allclose(fixed.to_numpy(), pooled.to_numpy(), atol=1e-6)


def test_label_space_equal_to_candidates_is_the_default():
    rows = simulate(100, 3, 1.5, 0.45, 0.9, np.random.default_rng(3))[["item", "source", "answer"]]
    a, _ = dawid_skene(rows, SAME)
    b, _ = dawid_skene(rows, SAME, labels=1)  # L = max(1, K) = K on every item
    assert np.allclose(a.to_numpy(), b.to_numpy())
