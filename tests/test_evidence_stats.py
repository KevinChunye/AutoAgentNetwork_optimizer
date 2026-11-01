"""Known-answer tests for autoagentnet/evidence/ (step 0.8): every estimator on simulated data whose
true value is known, plus small hand-worked cases. Offline and seeded."""

import math

import numpy as np
import pandas as pd
import pytest

from autoagentnet.evidence import calibration as C
from autoagentnet.evidence import correlation as R
from autoagentnet.evidence import decisions as D
from autoagentnet.evidence import inference as I
from autoagentnet.evidence.labelfree import dawid_skene


def betabinom_grades(n_items, calls, mu, rho, rng):
    """Item chances from a beta(mu, rho) and `calls` Bernoulli calls per item."""
    s = (1 - rho) / rho
    chance = rng.beta(mu * s, (1 - mu) * s, n_items)
    return (rng.random((n_items, calls)) < chance[:, None]).astype(float), chance


@pytest.mark.parametrize("estimator", ["pairwise", "anova", "betabinom"])
def test_repeat_correlation_recovers_rho_030_at_2000_items(estimator):
    Z, _ = betabinom_grades(2000, 5, 0.5, 0.30, np.random.default_rng(1))
    rho = {"pairwise": R.rho_pairwise, "anova": R.icc_anova, "betabinom": lambda z: R.rho_betabinom(z)[1]}[estimator](Z)
    assert rho == pytest.approx(0.30, abs=0.05)


def test_unequal_calls_per_item_are_allowed():
    rng = np.random.default_rng(2)
    Z, _ = betabinom_grades(3000, 5, 0.4, 0.25, rng)
    Z[rng.random(Z.shape) < 0.3] = np.nan
    assert R.icc_anova(Z) == pytest.approx(0.25, abs=0.05) and R.rho_pairwise(Z) == pytest.approx(0.25, abs=0.05)


def test_independent_sources_have_no_error_association_and_shared_ones_do():
    rng = np.random.default_rng(3)
    Zs, chance = betabinom_grades(4000, 3, 0.5, 0.4, rng)
    Zt_indep, _ = betabinom_grades(4000, 3, 0.6, 0.4, rng)
    indep = R.pair_stats(Zs, Zt_indep)
    assert indep.phi == pytest.approx(0, abs=0.04) and indep.log_error_or == pytest.approx(0, abs=0.12)
    assert indep.shared_error_ratio == pytest.approx(1, abs=0.06)
    Zt_shared = (rng.random((4000, 3)) < chance[:, None]).astype(float)  # same item chances: latent r = 1
    shared = R.pair_stats(Zs, Zt_shared)
    rho_s, rho_t = R.rho_pairwise(Zs), R.rho_pairwise(Zt_shared)
    assert shared.log_error_or > 1 and R.latent_r(shared.phi, rho_s, rho_t) == pytest.approx(1.0, abs=0.08)


def test_latent_r_recovers_a_partial_correlation_of_item_chances():
    rng = np.random.default_rng(4)
    n, r = 6000, 0.5
    z1 = rng.standard_normal(n)
    z2 = r * z1 + math.sqrt(1 - r * r) * rng.standard_normal(n)
    # item chances on the probit scale with a large spread; the latent r of the chances themselves:
    p1, p2 = 1 / (1 + np.exp(-1.7 * z1)), 1 / (1 + np.exp(-1.7 * z2))
    truth = np.corrcoef(p1, p2)[0, 1]
    Z1 = (rng.random((n, 4)) < p1[:, None]).astype(float)
    Z2 = (rng.random((n, 4)) < p2[:, None]).astype(float)
    est = R.latent_r(R.pair_stats(Z1, Z2).phi, R.rho_pairwise(Z1), R.rho_pairwise(Z2))
    assert est == pytest.approx(truth, abs=0.06)


def test_cells_hand_case_and_n_eff():
    Z = np.array([[1, 1, 0], [0, 0, 0]], dtype=float)
    cells = R.pair_cells(Z)  # item 1: pairs (1,1),(1,0),(1,0) of 3; item 2: all wrong
    assert cells[0].tolist() == pytest.approx([1 / 3, 1 / 3, 1 / 3, 0]) and cells[1].tolist() == [0, 0, 0, 1]
    assert R.n_eff_repeat(5, 0.48) == pytest.approx(1.71, abs=0.01)
    Rm = R.panel_correlation({"h": 5, "l": 5}, {"h": 0.5, "l": 0.5}, {("h", "l"): 0.1})
    assert R.n_eff(R.panel_correlation({"h": 5}, {"h": 0.5}, {})) == pytest.approx(R.n_eff_repeat(5, 0.5))
    assert R.n_eff(Rm) == pytest.approx(100 / (10 + 2 * 20 * 0.5 + 2 * 25 * 0.1))


def test_same_wrong_answer_rate_hand_case():
    answers = pd.DataFrame([["a", "b", "b"], ["x", "x", "y"]], index=["i1", "i2"])
    correct = pd.DataFrame([[0, 0, 0], [1, 1, 0]], index=["i1", "i2"])
    # within: item 1 has 3 wrong pairs, one of them (b, b) the same; item 2 has no wrong pair
    assert R.same_wrong_answer_rate(answers, correct, None, None, lambda a, b: a == b) == pytest.approx(1 / 3)


def test_calibration_measures_on_known_cases():
    rng = np.random.default_rng(5)
    true = rng.uniform(0.05, 0.95, 20000)
    y = (rng.random(20000) < true).astype(float)
    a, b = C.intercept_slope(true, y)
    assert a == pytest.approx(0, abs=0.06) and b == pytest.approx(1, abs=0.06)
    over = C.sigmoid(2 * C.logit(true))  # too extreme: slope 1/2
    assert C.intercept_slope(over, y)[1] == pytest.approx(0.5, abs=0.04)
    assert C.ece(true, y) < 0.02 and C.ece(over, y) > 0.05
    assert C.brier([1, 0], [1, 1]) == 0.5 and C.calibration_gap([0.9, 0.9], [1, 0]) == pytest.approx(0.4)
    assert C.ece([0.1, 0.9], [0, 1], bins=2) == pytest.approx(0.1)
    assert C.log_loss([1.0], [1]) == pytest.approx(-math.log(0.99))  # clipped


def test_cross_fit_scores_out_of_sample_and_recovers_the_truth():
    rng = np.random.default_rng(6)
    x = rng.uniform(0, 1, 4000)
    y = (rng.random(4000) < C.sigmoid(-2 + 4 * x)).astype(float)
    folds = C.two_folds(4000, seed=0)
    assert set(np.bincount(folds)) == {2000}
    pred = C.cross_fit(x, y, folds)
    assert C.calibration_gap(pred, y) == pytest.approx(0, abs=0.02)
    assert C.brier(pred, y) < C.brier(np.full(4000, y.mean()), y)
    beta = C.fit_correction(x, y)
    assert beta == pytest.approx([-2, 4], abs=0.3)


def test_extremizing_factor_is_recovered():
    rng = np.random.default_rng(7)
    n, k = 8000, 4
    signal = rng.normal(0, 1.2, n)
    y = (rng.random(n) < C.sigmoid(signal)).astype(float)
    forecasts = C.sigmoid(signal[:, None] / 2 + rng.normal(0, 0.01, (n, k)))  # each forecaster shrinks by half
    assert C.fit_extremizing(forecasts, y) == pytest.approx(2.0, abs=0.15)
    assert C.extremize([[0.6, 0.6]], 1.0)[0] == pytest.approx(0.6)


def test_kelly_hand_cases():
    assert D.kelly_stake(0.7, 0.5, fraction=1.0) == pytest.approx(0.4)
    assert D.kelly_stake(0.3, 0.5, fraction=0.5) == pytest.approx(-0.2)
    # YES stake 0.2 at q = 0.5 doubles: return +0.2; on NO it loses 0.2
    assert D.kelly_log_growth(0.7, 0.5, 1) == pytest.approx(math.log(1.2))
    assert D.kelly_log_growth(0.7, 0.5, 0) == pytest.approx(math.log(0.8))
    assert D.kelly_log_growth(0.5, 0.5, 1) == pytest.approx(0.0)
    rng = np.random.default_rng(8)  # a forecaster who knows the truth grows the bankroll against a wrong price
    p = rng.uniform(0.1, 0.9, 5000)
    y = (rng.random(5000) < p).astype(float)
    assert D.kelly_log_growth(p, np.clip(p + rng.normal(0, 0.15, 5000), 0.05, 0.95), y).mean() > 0


def test_policy_cascade_and_risk_coverage():
    conf = np.array([0.9, 0.6, 0.2])
    cheap, expensive = np.array([1, 0, 0]), np.array([1, 1, 1])
    v = D.policy_value(conf, cheap, expensive, [0.01] * 3, [0.05] * 3, t_answer=0.8, t_escalate=0.5, lam=3)
    assert v == pytest.approx([0.10 - 0.01, 0.10 - 0.06, -0.01])
    assert D.best_thresholds(conf, cheap, expensive, [0.0] * 3, [0.05] * 3)[0] == pytest.approx(0.9, abs=0.051)
    c = D.cascade([6, 3], [1, 0], [0, 1], [0.01, 0.01], [0.05, 0.05], k_agree=4)
    assert c["escalated"].tolist() == [False, True] and c["correct"].tolist() == [1, 1]
    assert c["cost_usd"].tolist() == pytest.approx([0.01, 0.06])
    rc = D.risk_coverage(conf, cheap)
    assert rc["coverage"].tolist() == pytest.approx([1, 2 / 3, 1 / 3])
    folds = np.array([0, 1, 0, 1])
    out = D.cross_fitted_policy([0.9, 0.9, 0.1, 0.1], [1, 1, 0, 0], [1, 1, 1, 1], [0] * 4, [0.2] * 4, folds)
    assert np.isfinite(out).all()


def test_cluster_bootstrap_holm_and_tost():
    rng = np.random.default_rng(9)
    x = rng.normal(1.0, 1.0, 400)
    res = I.bootstrap(lambda idx: x[idx].mean(), 400)
    assert res["lo"] < 1.0 < res["hi"] and res["hi"] - res["lo"] == pytest.approx(4 * 1 / 20, rel=0.25)
    assert I.p_above(res["draws"], 0) == 0.0 and I.p_above(res["draws"], 2) == 1.0
    # clusters move together: two clusters of identical items give draws of whole clusters only
    draws = I.cluster_draws(["a", "a", "b", "b"], n_boot=50)
    assert all(len(d) == 4 and sorted(d[:2] // 2) == [d[0] // 2] * 2 for d in draws)
    strata = I.cluster_draws(["a", "b", "c", "d"], n_boot=50, strata=["s", "s", "t", "t"])
    assert all(sorted(set(np.asarray(d) // 2)) == [0, 1] for d in strata)  # each stratum keeps its size
    table = I.holm({"H1": 0.01, "H4": 0.04, "H5": 0.03})
    assert table["threshold"].tolist() == pytest.approx([0.05 / 3, 0.05 / 2, 0.05])
    assert table["passes"].tolist() == [True, False, False]  # 0.03 > 0.025 stops the chain
    assert I.tost_p(np.linspace(-0.1, 0.1, 101), -0.4, 0.4) == 0.0
    assert I.week_cluster(["fred"], ["2026-07-14"])[0] == "fred:2026-W29"


def test_gee_exchangeable_matches_the_repeat_correlation():
    Z, _ = betabinom_grades(1500, 5, 0.5, 0.3, np.random.default_rng(10))
    rows = pd.DataFrame({"item": np.repeat(np.arange(1500), 5), "correct": Z.ravel()})
    assert I.gee_exchangeable_rho(rows) == pytest.approx(R.icc_anova(Z), abs=0.03)


def test_dawid_skene_recovers_independent_source_accuracies():
    rng = np.random.default_rng(11)
    acc = {"a": 0.8, "b": 0.6, "c": 0.45}
    rows = []
    for i in range(1500):
        for s, a in acc.items():
            for c in range(3):
                right = rng.random() < a
                rows.append({"item": i, "source": s, "answer": "T" if right else f"W{rng.integers(0, 3)}"})
    est, items = dawid_skene(pd.DataFrame(rows), lambda x, y: x == y)
    for s, a in acc.items():
        assert est[s] == pytest.approx(a, abs=0.05)
    assert (items["answer"] == "T").mean() > 0.95


def test_mean_pairwise_equals_the_average_of_pair_stats():
    rng = np.random.default_rng(12)
    G, _ = betabinom_grades(300, 4, 0.5, 0.4, rng)
    pairs = [R.pair_stats(G[:, [a]], G[:, [b]]) for a in range(4) for b in range(a + 1, 4)]
    got = R.mean_pairwise(G)
    assert got["pairs"] == 6
    assert got["phi"] == pytest.approx(np.mean([p.phi for p in pairs]))
    assert got["shared_error_ratio"] == pytest.approx(np.mean([p.shared_error_ratio for p in pairs]))
    assert got["log_error_or"] == pytest.approx(np.mean([p.log_error_or for p in pairs]))
