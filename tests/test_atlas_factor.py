"""The Atlas factor model (autoagentnet/atlas/factor.py) on simulated response tables with known parameters.
Offline."""

import numpy as np
import pandas as pd
import pytest

from autoagentnet.atlas import factor as F


def simulate(S=20, I=300, calls=1, beta_spread=0.0, shock=0.0, seed=0):
    """Systems with abilities a_s, failure betas around 1, families of 4 systems sharing an item shock."""
    rng = np.random.default_rng(seed)
    a = rng.normal(0.5, 1.0, S)
    beta = 1 + beta_spread * rng.normal(0, 1, S)
    b = rng.normal(0, 1.5, I)
    fam = np.arange(S) // 4
    u = rng.normal(0, shock, (fam.max() + 1, I))
    rows = []
    for s in range(S):
        p = F.sigmoid(a[s] - beta[s] * b + u[fam[s]])
        for c in range(calls):
            y = (rng.random(I) < p).astype(float)
            for i in range(I):
                rows.append({"item": f"i{i:03d}", "system": f"s{s:02d}", "family": f"f{fam[s]}", "call": c,
                             "answer": "right" if y[i] else f"wrong{rng.integers(0, 2)}", "correct": y[i]})
    return pd.DataFrame(rows), {"a": a, "beta": beta, "b": b}


def test_l0_recovers_abilities_and_difficulties():
    t, truth = simulate()
    m = F.fit(t, "L0")
    assert np.corrcoef(m["a"].to_numpy(), truth["a"])[0, 1] > 0.95
    assert np.corrcoef(m["b"].to_numpy(), truth["b"])[0, 1] > 0.9


def test_l1_recovers_failure_betas():
    t, truth = simulate(S=30, I=500, beta_spread=0.4, seed=1)
    m = F.fit(t, "L1")
    assert np.corrcoef(m["beta"].to_numpy(), truth["beta"])[0, 1] > 0.8
    assert abs(m["b"].mean()) < 1e-6 and m["b"].std(ddof=0) == pytest.approx(1.0)


def test_l2_family_shocks_capture_shared_family_item_effects_in_sample():
    with_shock, _ = simulate(S=24, I=300, shock=1.5, seed=2)
    l1, l2 = F.fit(with_shock, "L1"), F.fit(with_shock, "L2")
    p1 = F.predict(l1, with_shock["system"].to_numpy(), with_shock["item"].to_numpy())
    p2 = F.predict(l2, with_shock["system"].to_numpy(), with_shock["item"].to_numpy())
    y = with_shock["correct"].to_numpy()
    assert F.log_loss(p2, y) < F.log_loss(p1, y)
    assert l2["u"].abs().to_numpy().mean() > 0.2


def test_held_out_beats_the_base_rate():
    t, _ = simulate(S=20, I=300, seed=3)
    for by in ("item", "system"):
        r = F.held_out(t, "L1", by=by)
        assert r["log_loss"] < r["log_loss_base_rate"] and r["n_scored"] > 0


def test_dispersion_is_near_one_for_pure_call_luck():
    t, _ = simulate(S=6, I=200, calls=4, seed=4)
    m = F.fit(t, "L1")
    d = F.dispersion(t, m)
    assert d["cells"] == 6 * 200 and 0.8 < d["dispersion"] < 1.25


def test_systematic_share_and_eta():
    assert F.systematic_share(np.zeros(10)) == 0.0
    assert F.systematic_share(np.random.default_rng(0).normal(0, 3, 10000)) == pytest.approx(9 / (9 + np.pi ** 2 / 3), abs=0.02)
    assert F.eta(0.70, 0.60, 0.80) == pytest.approx(0.5)
    assert np.isnan(F.eta(0.7, 0.8, 0.8))


def test_coverage_table_and_tail():
    """A shared difficulty makes all-wrong more common than independence implies; the fitted model's implied
    all-wrong tracks the observed rate."""
    t, _ = simulate(S=8, I=400, seed=5)
    Y = F.outcome_matrix(t)
    m = F.fit(t, "L1")
    ct = F.coverage_table(Y, m, k_max=3)
    k3 = ct[ct["k"] == 3].iloc[0]
    assert k3["all_wrong"] > k3["independent_all_wrong"]
    assert abs(k3["model_all_wrong"] - k3["all_wrong"]) < 0.03
    assert (ct["coverage"].diff().dropna() > 0).all()


def test_vote_accuracy_formulas():
    p = np.array([0.2, 0.5, 0.8])
    assert np.allclose(F.vote_accuracy(p, 1), p)
    three = F.vote_accuracy(p, 3, q=1.0)  # wrong answers identical: binary majority
    assert np.allclose(three, p ** 3 + 3 * p ** 2 * (1 - p))
    assert (F.vote_accuracy(p, 3, q=0.0) >= three).all()


def test_vote_ceiling_uses_the_modal_answer():
    t = pd.DataFrame({"system": "s", "item": ["a"] * 3 + ["b"] * 3, "call": [0, 1, 2] * 2,
                      "answer": ["x", "x", "y", "z", "w", "z"], "correct": [1.0, 1.0, 0.0, 0.0, 1.0, 0.0]})
    assert F.vote_ceiling(t, "s") == 0.5


def test_copula_recovers_its_rho_and_bounds():
    """Systems that fail when a shared normal plus their own noise falls below a threshold: the fitted rho is the
    simulated one, and rho = 0 gives the independent all-wrong rate."""
    from scipy.stats import norm

    rng = np.random.default_rng(6)
    n, rho = 4000, 0.4
    z = rng.standard_normal(n)
    acc = np.array([0.5, 0.6, 0.7, 0.8])
    latent = np.sqrt(rho) * z[:, None] + np.sqrt(1 - rho) * rng.standard_normal((n, 4))
    Y = pd.DataFrame((latent >= norm.ppf(1 - acc)).astype(float), columns=list("abcd"))
    assert F.fit_copula_rho(Y) == pytest.approx(rho, abs=0.06)
    assert F.copula_all_wrong(acc, 0.0) == pytest.approx(np.prod(1 - acc), abs=1e-6)
    observed = float((Y.max(axis=1) == 0).mean())
    assert F.copula_all_wrong(Y.mean().to_numpy(), F.fit_copula_rho(Y)) == pytest.approx(observed, abs=0.02)


def test_item_posterior_concentrates_and_agrees_with_the_point_estimate():
    """A new item answered right by weak systems is easy: its posterior sits below the prior mean, near the MAP."""
    t, _ = simulate(S=20, I=300, seed=7)
    m = F.fit(t, "L1")
    a, beta = m["a"].to_numpy(), m["beta"].to_numpy()
    y = np.ones(len(a))  # every system right
    grid, w = F.item_posterior(m, a, beta, y)
    assert w.sum() == pytest.approx(1.0) and (w >= 0).all()
    mean = float(grid @ w)
    assert mean < m["b"].mean() - 0.5
    assert abs(mean - F.new_item_difficulty(m, a, beta, y)) < 0.5
