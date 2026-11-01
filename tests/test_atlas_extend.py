"""Offline tests of analysis/atlas_extend.py (session W1): the vote rule, random-effects pooling, the vectorised
Dawid-Skene, the difficulty posterior, the depth-pair fits, and the cross-fitted P1 and resumable P6 on synthetic
tables."""

import numpy as np
import pandas as pd
import pytest

from analysis import atlas_extend as X
from autoagentnet.atlas import factor as F
from autoagentnet.evidence.labelfree import dawid_skene, dawid_skene_pooled


def test_vote_credit_matches_the_three_call_formula_and_simple_cases():
    p = np.linspace(0.05, 0.95, 7)
    for q in (0.0, 0.3, 1.0):
        P = np.repeat(p[:, None], 3, axis=1)
        assert np.allclose(X.vote_credit(P, 0.0, np.sqrt(q)), F.vote_accuracy(p, 3, q))
    assert np.allclose(X.vote_credit(p[:, None], 0.0, 0.5), p)  # one call
    z = 0.2 * (1 - p)
    P2 = np.repeat(p[:, None], 2, axis=1)
    # two calls: a right-wrong split is a tie (1/2); a right call beside an abstention wins
    assert np.allclose(X.vote_credit(P2, np.repeat(z[:, None], 2, axis=1), 0.7), p + p * z)


def test_vote_credit_matches_simulation_with_abstentions_and_mixed_members():
    rng = np.random.default_rng(1)
    p = np.array([[0.6, 0.4, 0.3, 0.5, 0.2]])
    z = np.array([[0.1, 0.2, 0.0, 0.3, 0.1]])
    r = 0.6
    n = 200_000
    u = rng.random((n, 5))
    outcome = np.where(u < p, 0, np.where(u < p + z, 1, np.where(rng.random((n, 5)) < r, 2, 3)))
    R, W, U = (outcome == 0).sum(1), (outcome == 2).sum(1), (outcome == 3).sum(1)
    top = np.maximum(np.maximum(R, W), (U > 0).astype(int))
    n_top = (R == top).astype(int) + ((W == top) & (W > 0)).astype(int) + U * (top == 1)
    sim = np.where((R > 0) & (R == top), 1 / np.maximum(n_top, 1), 0).mean()
    assert X.vote_credit(p, z, r)[0] == pytest.approx(sim, abs=0.004)


def test_random_effects():
    out = X.random_effects([0.3, 0.3, 0.3], [0.1, 0.2, 0.1])
    assert out["pooled"] == pytest.approx(0.3) and out["tau2"] == 0.0 and out["k"] == 3
    spread = X.random_effects([0.0, 1.0, 2.0], [0.1, 0.1, 0.1])
    assert spread["tau2"] > 0.5 and spread["pooled"] == pytest.approx(1.0)
    assert spread["hi"] - spread["lo"] > 1.0  # between-pair variance widens the interval
    assert X.random_effects([np.nan], [0.1])["k"] == 0


def _panel(rng, n_items=40, systems=4, calls=3):
    rows = []
    for i in range(n_items):
        for s in range(systems):
            for c in range(calls):
                u = rng.random()
                ans = None if u < 0.1 else ("right" if u < 0.5 + 0.1 * s else rng.choice(["w1", "w2", "w3"]))
                rows.append({"item": f"i{i}", "system": f"s{s}", "call": c, "answer": ans,
                             "correct": float(ans == "right")})
    return pd.DataFrame(rows)


@pytest.mark.parametrize("pooled,labels", [(False, None), (True, None), (False, 20), (True, 20)])
def test_ds_fast_matches_labelfree(pooled, labels):
    rows = _panel(np.random.default_rng(2))
    e = X.encode_calls(rows)
    acc, chosen = X.ds_fast(e["item_idx"], e["source_idx"], e["cand"], len(e["items"]), len(e["sources"]),
                            pooled=pooled, labels=labels)
    ref_acc, ref_table = (dawid_skene_pooled if pooled else dawid_skene)(
        rows[["item", "system", "answer"]].rename(columns={"system": "source"}), lambda a, b: a == b, labels=labels)
    assert np.allclose(acc, ref_acc.reindex(e["sources"]).to_numpy(), atol=1e-6)
    ref_choice = ref_table.set_index("item")["answer"]
    for i, item in enumerate(e["items"]):
        cands = list(dict.fromkeys(a for a in rows.loc[rows["item"] == item, "answer"] if isinstance(a, str)))
        assert (cands[chosen[i]] if chosen[i] >= 0 else None) == ref_choice[item]


def test_label_free_reports_best_single_coverage_and_ranks():
    out = X.label_free(_panel(np.random.default_rng(3)))
    assert 0 <= out["best single"] <= out["coverage"] <= 1
    assert out["Dawid-Skene rank of best"] >= 1


def test_posterior_matches_item_posterior():
    rng = np.random.default_rng(4)
    model = {"a": pd.Series(rng.normal(size=6), index=list("abcdef")),
             "beta": pd.Series(rng.uniform(0.5, 1.5, 6), index=list("abcdef")),
             "b": pd.Series(rng.normal(size=30))}
    y = rng.integers(0, 2, 6).astype(float)
    grid, L = X.grid_loglik(model, list("abcdef"), y)
    g2, w2 = F.item_posterior(model, model["a"].to_numpy(), model["beta"].to_numpy(), y)
    assert np.allclose(grid, g2) and np.allclose(X.posterior(L.sum(axis=0)), w2)


def test_fit_ab_and_fit_shift_recover_what_was_simulated():
    rng = np.random.default_rng(5)
    b = rng.normal(size=4000)
    y = (rng.random(4000) < F.sigmoid(0.8 - 1.3 * b)).astype(float)
    a, beta = X.fit_ab(b, y)
    assert a == pytest.approx(0.8, abs=0.15) and beta == pytest.approx(1.3, abs=0.15)
    base = 0.5 - b
    y2 = (rng.random(4000) < F.sigmoid(base + 1.0)).astype(float)
    assert X.fit_shift(base, y2) == pytest.approx(1.0, abs=0.15)


def _world(rng, n_items=60, n_systems=10, calls=4, shift=None):
    """A synthetic MathArena-like table: L1 successes, an item's common wrong answer, repeats."""
    b = rng.normal(0, 1.5, n_items)
    rows = []
    for s in range(n_systems):
        a = rng.normal(0.5, 1.0)
        for c in range(calls):
            p = F.sigmoid(a - b)
            right = rng.random(n_items) < p
            common = rng.random(n_items) < 0.5
            for i in range(n_items):
                ans = "r" if right[i] else ("w" if common[i] else f"u{s}{c}{i}")
                rows.append({"benchmark": "x/set", "item": str(i), "system": f"s{s}", "family": f"f{s % 3}",
                             "call": c, "answer": ans, "correct": float(right[i]), "cost_usd": 0.01 * (1 + s)})
    return pd.DataFrame(rows)


def test_p1_vote_rule_tracks_votes_better_than_zero_gain_on_a_world_it_describes():
    rows = X.p1_set(_world(np.random.default_rng(6)), "x/set", k=3)
    assert {"pred_vote", "pred_one", "obs_vote", "obs_one"} <= set(rows.columns)
    cells = rows.groupby("cell")[["obs_vote", "obs_one", "pred_vote", "pred_one"]].mean()
    stat = X.p1_stat(cells)
    assert stat["rule level MAE"] < stat["zero-gain level MAE"] + 0.01
    assert stat["mean predicted gain"] > 0


def test_p2_pair_finds_no_slope_change_when_the_high_setting_is_a_shift():
    rng = np.random.default_rng(7)
    b = pd.Series(rng.normal(size=300), index=[str(i) for i in range(300)])

    def calls(a, n):
        p = F.sigmoid(a - b.to_numpy())
        return pd.DataFrame([{"item": it, "call": c, "correct": float(rng.random() < p[j])}
                             for j, it in enumerate(b.index) for c in range(n)])

    res = X.p2_pair(calls(-0.5, 4), calls(1.0, 4), b)
    assert res["delta a"] == pytest.approx(1.5, abs=0.4)
    assert res["delta beta lo"] < 0 < res["delta beta hi"]
    assert res["base rate minus shift"] > 0  # the item pattern carries over


def test_p6_source_resumes_from_its_cache(tmp_path):
    rng = np.random.default_rng(8)
    t = _world(rng, n_items=30, n_systems=6, calls=1)
    t["item"] = "x/set:" + t["item"]
    fam = pd.Series("x/set", index=sorted(t["item"].unique()))
    cache = tmp_path / "draws.csv"
    first = X.p6_source(t, "x", fam, n_boot=3, cache=cache)
    again = X.p6_source(t, "x", fam, n_boot=3, cache=cache)
    assert len(first) == len(again) and cache.exists()
    summary = X.p6_summary(again)
    whole = summary[summary["quantity"] == "(all) L0"].iloc[0]
    assert whole["item draws"] == 3 and whole["halves"] == 2 * X.N_HALVES
    assert whole["half-split min"] <= whole["half-split max"]


def test_read_table_parses_the_committed_anchor_read():
    ah3 = X.read_table(["arm", "q", "predicted", "observed", "predicted_gain"])
    assert len(ah3) == 6 and ah3["observed"].between(0, 1).all()
    assert len(X.p1_anchor()) == 6
    assert set(X.anchor_judges()["judge"]) == {"haiku_high_judge", "sol_low_judge"}


def test_p8_tail_on_a_factor_world_is_predicted_by_the_factor_model():
    rng = np.random.default_rng(9)
    b = rng.normal(0, 2.0, 200)
    a = rng.normal(1.0, 1.0, 24)
    Y = pd.DataFrame((rng.random((200, 24)) < F.sigmoid(a[None, :] - b[:, None])).astype(float),
                     index=[f"i{i}" for i in range(200)], columns=[f"s{s}" for s in range(24)])
    out = X.p8_matrix(Y, {}, "x")
    whole = out[out["k"] == "all"].iloc[0]
    # the factor model and the copula get the same (calibration) information; the item-level variant gets more
    assert {"factor model, test-item difficulty", "fit systems all wrong on the test items"} <= set(out.columns)
    assert out.loc[out["k"].astype(str) == "5", "observed minus factor model lo"].iloc[0] < 0.05
    assert whole["observed / factor model lo"] < 1.0 < whole["observed / factor model hi"]
    assert whole["observed minus independence lo"] > 0  # independence misses the shared difficulty
    assert np.isnan(whole["observed / independence"])  # no ratio over a predicted rate under 1%
    assert 0 <= whole["observed lo (Clopper-Pearson)"] <= whole["observed all-wrong"] <= whole["observed hi (Clopper-Pearson)"]
