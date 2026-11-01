"""The Phase 3 pruning library (autoagentnet/pruning/replay.py, criteria.py, search.py) on simulated panels
with known answers (analysis/evidence_power.py's generator: latent difficulty per source, repeat and
cross-source correlation, a shared "attractor" wrong answer); offline, $0."""

import numpy as np
import pandas as pd
import pytest

from analysis.evidence_power import SOURCES, USD, plurality, simulate_panel
from autoagentnet.evidence.correlation import n_eff_repeat
from autoagentnet.pruning import criteria as Cr
from autoagentnet.pruning import search as S
from autoagentnet.pruning.replay import (Grid, Panel, PluralityModel, design, evaluate, fit, groups, objective, predict,
                                        replay)


def sim_panel(n=300, seed=1, r_cross=0.6):
    """Haiku x5, Luna x5, Sonnet, Sol (the evidence plan's panel) on n simulated BBEH items."""
    sim = simulate_panel(n, r_cross, np.random.default_rng(seed))
    A = np.column_stack([sim[s]["A"] for s in SOURCES])
    Z = np.column_stack([sim[s]["Z"] for s in SOURCES])
    sources = [s for s in SOURCES for _ in range(sim[s]["A"].shape[1])]
    calls = [c for s in SOURCES for c in range(sim[s]["A"].shape[1])]
    cost = np.tile([USD[s] for s in sources], (n, 1))
    return Panel.from_arrays(A, Z, cost, sources=sources, calls=calls), A


def small_panel(n=300, seed=2, equal_cost=False, copy_sonnet=False):
    """Haiku x5 + Sonnet (Phase 3A's flat panel), optionally with an exact copy of the Sonnet call."""
    sim = simulate_panel(n, 0.6, np.random.default_rng(seed))
    A = np.column_stack([sim["haiku"]["A"], sim["sonnet"]["A"]])
    Z = np.column_stack([sim["haiku"]["Z"], sim["sonnet"]["Z"]])
    sources, calls = ["haiku"] * 5 + ["sonnet"], [0, 1, 2, 3, 4, 0]
    if copy_sonnet:
        A, Z = np.column_stack([A, A[:, -1]]), np.column_stack([Z, Z[:, -1]])
        sources, calls = sources + ["sonnet"], calls + [1]
    unit_cost = np.full(A.shape[1], 0.001) if equal_cost else np.array([USD[s] for s in sources])
    return Panel.from_arrays(A, Z, np.tile(unit_cost, (n, 1)), sources=sources, calls=calls)


# ---------------------------------------------------------------------------------------------------------
# replay

def test_vote_replay_reproduces_the_simulated_plurality_and_dollars():
    panel, A = sim_panel()
    out = replay(panel, panel.all_units())
    answer, top = plurality(A)
    assert np.array_equal(out["correct"].to_numpy(), (answer == 0).astype(float))
    assert np.allclose(out["confidence"], top / 12)
    kept = panel.mask(["haiku:0", "haiku:1", "sonnet:0"])
    assert np.allclose(replay(panel, kept)["dollars"], 2 * USD["haiku"] + USD["sonnet"])
    answer3, _ = plurality(A[:, kept])
    assert np.array_equal(replay(panel, kept)["correct"].to_numpy(), (answer3 == 0).astype(float))


def test_from_calls_groups_answers_with_the_grader_and_drops_incomplete_items():
    rows = []
    for item, answers, gold in [("a", ["yes, no", "yes,no", "no, no"], "yes, no"), ("b", ["(A)", "A", None], "(B)")]:
        for c, ans in enumerate(answers):
            rows.append({"item": item, "source": "haiku", "call": c, "answer": ans, "parsed": ans is not None,
                         "correct": float(ans is not None and ans.replace(" ", "") == gold.replace(" ", "")),
                         "cost_usd": 0.001, "seconds": 2.0 + c})
    rows.append({"item": "c", "source": "haiku", "call": 0, "answer": "x", "parsed": True, "correct": 0.0,
                 "cost_usd": 0.001, "seconds": 1.0})
    panel = Panel.from_calls(pd.DataFrame(rows))
    assert panel.items == ["a", "b"] and panel.dropped == ["c"]
    assert panel.votes.tolist() == [[0, 0, 1], [0, 0, -1]]  # "yes, no" = "yes,no"; "(A)" = "A"; None unparsed
    out = replay(panel, panel.all_units())
    assert out["correct"].tolist() == [1.0, 0.0] and out["seconds"].tolist() == [4.0, 4.0]  # an unparsed call was still made
    assert out["confidence"].tolist() == pytest.approx([2 / 3, 2 / 3])


def test_weighted_vote_favours_the_stronger_source_and_beats_the_vote_out_of_fold():
    panel, _ = sim_panel()
    w = fit(panel, panel.all_units(), refit="weights")
    unit_w = pd.Series(w[:panel.m], index=panel.units["unit"])  # the last entry is the intercept
    assert unit_w["sonnet:0"] > 2 * unit_w.filter(like="haiku").mean()
    folds = np.arange(panel.n) % 2
    assert evaluate(panel, panel.all_units(), folds, "weights")["score"] > evaluate(panel, panel.all_units(), folds, "none")["score"]


def test_kevins_aggregator_answers_the_plurality_and_breaks_ties_by_its_model():
    """Kevin's aggregator: the plurality answer; P(right) from per-source agreement shares; a tie goes to the
    class the model rates most likely right (here Sonnet's answer over a single Haiku call's)."""
    panel, _ = sim_panel()
    model = fit(panel, panel.all_units())
    assert isinstance(model, PluralityModel) and len(model.beta) == 5  # 4 sources + intercept
    ridge, vote = predict(panel, panel.all_units(), w=model), predict(panel, panel.all_units())
    top = (panel.votes[:, :, None] == np.arange(panel.class_correct.shape[1])).sum(axis=1)
    clear = (top == top.max(axis=1, keepdims=True)).sum(axis=1) == 1  # items without a plurality tie
    assert np.array_equal(ridge["slot"][clear], vote["slot"][clear])
    pair = panel.mask(["haiku:0", "sonnet:0"])
    pm = fit(panel, pair)
    out = predict(panel, pair, w=pm)
    split = panel.votes[:, 0] != panel.votes[:, 10]  # Haiku and Sonnet disagree: a 1-1 tie
    sonnet_slot = panel.votes[:, 10]
    assert pm.beta[2] > pm.beta[0]  # sources haiku, luna, sonnet, sol: Sonnet's agreement outweighs Haiku's
    assert np.array_equal(out["slot"][split & (sonnet_slot >= 0)], sonnet_slot[split & (sonnet_slot >= 0)])
    restricted = fit(panel, pair, refit="restrict")  # the dense aggregator, not refitted
    assert np.allclose(restricted.beta, model.beta)
    assert 0 < out["confidence"].min() and out["confidence"].max() < 1


def test_gradient_and_hessian_match_finite_differences():
    panel, _ = sim_panel(n=80)
    X, valid, gold = design(panel, panel.all_units())
    rng = np.random.default_rng(0)
    w = rng.normal(0, 0.5, X.shape[2])
    v, g, H = objective(w, X, valid, gold)
    eps = 1e-5
    num_g = np.array([(objective(w + eps * e, X, valid, gold)[0] - objective(w - eps * e, X, valid, gold)[0]) / (2 * eps)
                      for e in np.eye(len(w))])
    num_H = np.array([(objective(w + eps * e, X, valid, gold)[1] - objective(w - eps * e, X, valid, gold)[1]) / (2 * eps)
                      for e in np.eye(len(w))])
    assert np.allclose(g, num_g, atol=1e-4) and np.allclose(H, num_H, atol=1e-4)


def test_forecast_refit_recovers_known_logistic_weights():
    rng = np.random.default_rng(3)
    n = 4000
    x = rng.normal(0, 1, (n, 3))
    y = (rng.random(n) < 1 / (1 + np.exp(-(0.3 + 1.0 * x[:, 0] + 0.5 * x[:, 1])))).astype(float)
    panel = Panel.from_probs(1 / (1 + np.exp(-x)), y, np.full((n, 3), 0.001))
    w = fit(panel, panel.all_units(), refit="weights")
    assert w[:3] == pytest.approx([1.0, 0.5, 0.0], abs=0.1) and w[3] == pytest.approx(0.3, abs=0.1)
    folds = np.arange(n) % 2
    assert evaluate(panel, panel.all_units(), folds, "weights")["brier"] < evaluate(panel, panel.all_units(), folds, "none")["brier"]


def test_forecast_aggregator_recovers_a_known_extremizing_factor():
    """Kevin's forecast aggregator: P(yes) = sigmoid(a x mean log-odds); data made with a = 1.8."""
    rng = np.random.default_rng(4)
    n = 6000
    truth = rng.normal(0, 1, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-1.8 * truth))).astype(float)
    logits = truth[:, None] + rng.normal(0, 0.3, (n, 3))  # three calls: the truth plus small noise
    panel = Panel.from_probs(1 / (1 + np.exp(-logits)), y, np.full((n, 3), 0.001))
    model = fit(panel, panel.all_units())
    assert isinstance(model, PluralityModel) and model.beta[0] == pytest.approx(1.8, abs=0.15)  # noise attenuates a little


# ---------------------------------------------------------------------------------------------------------
# criteria

def test_every_criterion_scores_every_group_and_c2_c6_rank_sonnet_first():
    panel, _ = sim_panel()
    table = Cr.all_criteria(panel, panel.all_units(), groups(panel, "unit"))
    assert list(table.index) == panel.units["unit"].tolist() and table.notna().all().all()
    for name in ("C1", "C2", "C3", "C3b", "C6"):
        assert table[name].idxmax() in ("sonnet:0", "sol:0"), name
    by_source = Cr.all_criteria(panel, panel.all_units(), groups(panel, "source"))
    assert set(by_source.index) == {"haiku", "luna", "sonnet", "sol"}


def test_obs_is_beta_squared_over_twice_the_inverse_hessian_diagonal():
    panel = small_panel()
    names, beta, H, F, y, wt = Cr.aggregator_fit(panel, panel.all_units(), groups(panel, "unit"))
    obs = Cr.c3b_obs(panel, panel.all_units(), groups(panel, "unit"))
    Hinv = np.linalg.inv(H)
    assert names == panel.units["unit"].tolist() and F.shape[1] == 6 and wt.sum() == pytest.approx(panel.n)
    assert obs.to_numpy() == pytest.approx(beta[:6] ** 2 / (2 * np.diag(Hinv)[:6]))
    eps = 1e-5  # H is the Hessian of the weighted ridge log loss: check one entry by finite differences
    A = np.column_stack([F, np.ones(len(y))])
    grad = lambda b: A.T @ (wt * (1 / (1 + np.exp(-(A @ b))) - y)) + np.r_[np.ones(6), 0.0] * b
    e = np.eye(7)[5]
    assert (grad(beta + eps * e) - grad(beta - eps * e))[5] / (2 * eps) == pytest.approx(H[5, 5], rel=1e-4)


def test_label_free_criteria_spot_a_noise_call_and_an_always_unparsed_call():
    panel, A = sim_panel()
    rng = np.random.default_rng(5)
    noise = rng.integers(0, 5, panel.n)
    dead = np.full(panel.n, -1)
    Z = panel.correct_matrix()
    big = Panel.from_arrays(np.column_stack([A, noise, dead]), np.column_stack([Z, noise == 0, np.zeros(panel.n)]),
                            np.full((panel.n, 14), 0.001), sources=list(panel.units["source"]) + ["noise", "dead"],
                            calls=list(panel.units["call"]) + [0, 0])
    grp = groups(big, "unit")
    agree = Cr.agreement(big, big.all_units(), grp)
    flip = Cr.c4_flip(big, big.all_units(), grp)
    recon = Cr.c5_reconstruction(big, big.all_units(), grp)
    assert flip["dead:0"] == 0 and agree["dead:0"] == 0
    assert agree.drop("dead:0").idxmin() == "noise:0"
    assert recon.drop("dead:0").idxmin() == "noise:0"


def test_n_eff_matches_the_equicorrelated_formula_and_ignores_exact_copies():
    R = np.full((5, 5), 0.48) + 0.52 * np.eye(5)
    assert Cr.n_eff(R) == pytest.approx(n_eff_repeat(5, 0.48))
    assert Cr.n_eff(np.ones((3, 3))) == pytest.approx(1.0)
    panel = small_panel(equal_cost=True, copy_sonnet=True)
    score = Cr.c7_neff_per_dollar(panel, panel.all_units(), groups(panel, "unit"))
    assert score["sonnet:0"] == pytest.approx(0, abs=1e-6) and score["sonnet:1"] == pytest.approx(0, abs=1e-6)
    assert (score.drop(["sonnet:0", "sonnet:1"]) > 0).all()


def test_gaussian_copula_mi_known_values():
    rng = np.random.default_rng(0)
    n = 20000
    z = rng.normal(size=n)
    x = 0.6 * z + 0.8 * rng.normal(size=n)
    none = np.zeros((n, 0))
    cn = Cr.copula_normal
    assert Cr.gaussian_cmi(cn(x)[:, None], cn(z)[:, None], none) == pytest.approx(-0.5 * np.log(1 - 0.36), abs=0.01)
    assert Cr.gaussian_cmi(cn(rng.normal(size=n))[:, None], cn(z)[:, None], none) < 0.002
    y = z + rng.normal(size=n)
    assert Cr.gaussian_cmi(cn(x)[:, None], cn(y)[:, None], cn(z)[:, None]) < 0.002  # independent given z


# ---------------------------------------------------------------------------------------------------------
# searches

def test_one_shot_ranking_drops_both_copies_but_iterative_reranking_keeps_one():
    """S1's stated flaw in miniature: each copy of a call looks free to drop while the other is there."""
    panel = small_panel(equal_cost=True, copy_sonnet=True)
    grp = groups(panel, "unit")
    rows = np.arange(panel.n)
    one_shot = S.prune_path(panel, grp, Cr.c7_neff_per_dollar, rows, iterative=False)
    iterative = S.prune_path(panel, grp, Cr.c7_neff_per_dollar, rows, iterative=True)
    assert set(one_shot["removed"].iloc[1:3]) == {"sonnet:0", "sonnet:1"}
    assert iterative["removed"].iloc[1] in {"sonnet:0", "sonnet:1"}
    assert iterative["removed"].iloc[2].startswith("haiku")


def test_every_path_point_is_on_or_below_the_exhaustive_frontier():
    panel = small_panel()
    folds = np.arange(panel.n) % 2
    (search, held), _ = S.directions(folds)
    grp = groups(panel, "unit")
    table = S.s4_exhaustive(panel, grp, search, held)
    assert len(table) == 63
    front = S.pareto(table)
    assert front["dollars"].is_monotonic_increasing and front["score"].is_monotonic_increasing
    assert (S.regret(table, front) >= -1e-12).all() and S.regret(front, front) == pytest.approx(0)
    for path in (S.s1_sensitivity(panel, groups(panel, "source"), search, held),
                 S.s2_netadapt(panel, groups(panel, "source"), search, held),
                 S.prune_path(panel, grp, Cr.c6_leave_out, search, held)):
        assert (S.regret(path, front) >= -1e-12).all()
    counts = S.s4_counts(panel, groups(panel, "source"), search, held)
    assert len(counts) == 6 * 2 - 1  # Haiku keeps 0-5 calls, Sonnet 0-1, not both 0
    assert set(counts["kept"]) <= set(table["kept"])  # count vectors are first-k subsets


def test_s1_curves_cut_one_source_at_a_time_and_a_threshold_picks_counts():
    panel = small_panel()
    sources = groups(panel, "source")
    rows = np.arange(panel.n)
    curves = S.s1_curves(panel, sources, rows)
    assert len(curves) == 6 + 2  # Haiku 5..0 calls, Sonnet 1..0
    assert (curves.loc[curves["kept_calls"] == curves.groupby("source")["kept_calls"].transform("max"), "loss"] == 0).all()
    assert S.s1_keep(curves, sources, 1.0) == {"haiku": 0, "sonnet": 0}
    full = S.s1_keep(curves, sources, -1.0)  # nothing is free: every source stays full
    assert full == {"haiku": 5, "sonnet": 1}
    path = S.s1_sensitivity(panel, sources, rows)
    assert path["dollars"].is_monotonic_decreasing


def test_netadapt_cuts_at_least_one_step_of_dollars_each_time():
    panel, _ = sim_panel()
    rows = np.arange(panel.n)
    path = S.s2_netadapt(panel, groups(panel, "source"), rows, step=0.0005)
    cuts = -np.diff(path["resource"].to_numpy())
    assert (cuts >= 0.0005 - 1e-12).all() and path["n_units"].iloc[-1] == 1
    seconds = S.s2_netadapt(small_panel(), groups(small_panel(), "source"), rows, step=0.5, resource="seconds")
    assert len(seconds) >= 1  # simulated calls take 0 s: nothing to cut, the path stops at once


def test_controller_finds_a_near_best_network_under_a_budget():
    panel, _ = sim_panel()
    layers = groups(panel, "source")
    rows = np.arange(panel.n)
    best, history = S.s3_controller(panel, layers, rows, budget=0.006, iters=10)
    assert S.resource_of(panel, best, rows, "dollars") <= 0.006 + 1e-12
    names = list(layers)
    rewards = []
    for counts in np.ndindex(6, 6, 2, 2):
        clipped = S.clip_counts(panel, layers, counts, 0.006, rows)
        kept = S.keep_counts_to_mask(panel, layers, dict(zip(names, clipped)))
        assert S.resource_of(panel, kept, rows, "dollars") <= 0.006 + 1e-12  # clipping enforces the budget
        rewards.append(S.controller_reward(panel, kept, rows, "budget", 0.006, 0.05, 1.0, "vote")[0])
    assert history["reward"].max() >= np.percentile(rewards, 95)


def test_vote_proxy_ranks_networks_like_the_refit_score():
    panel = small_panel()
    configs = [S.mask_of(panel, list(c)) for r in range(1, 7) for c in __import__("itertools").combinations(range(6), r)]
    out = S.proxy_spearman(panel, configs, np.arange(panel.n) % 2, n_boot=200)
    assert -1 <= out["lo"] <= out["rho"] <= out["hi"] <= 1 and out["rho"] > 0.5 and out["n_configs"] == 63


def test_dynamic_policy_limits_never_stop_equals_static_and_always_stop_pays_one_call():
    panel, _ = sim_panel()
    folds = np.arange(panel.n) % 2
    (search, held), _ = S.directions(folds)
    order = list(range(panel.m))
    never = S.dynamic_replay(panel, order, 1.01, search, held)
    static = replay(panel, panel.all_units(), held, fit(panel, panel.all_units(), search))
    assert np.array_equal(never["correct"], static["correct"]) and np.allclose(never["dollars"], static["dollars"])
    assert (never["rounds"] == panel.m).all()
    always = S.dynamic_replay(panel, order, 0.0, search, held)
    assert (always["rounds"] == 1).all() and np.allclose(always["dollars"], USD["haiku"])
    front = S.dynamic_frontier(panel, order, search, held, [0.6, 0.8, 0.95])
    assert (np.diff(front["dollars"]) >= -1e-12).all()  # a higher tau never calls less


def test_baselines_respect_budgets_and_cascade_limits():
    panel, _ = sim_panel()
    pool = list(range(panel.m))
    for pick in (S.cheapest_first(panel, pool, 0.01), S.top_k_accurate(panel, pool, 0.02)):
        assert S.resource_of(panel, pick, np.arange(panel.n), "dollars") <= 0.02 + 1e-12
    assert S.top_k_accurate(panel, pool, 0.02)[panel.units["unit"] == "sonnet:0"].all()
    sets = S.random_subsets(panel, pool, 0.005, n=50)  # 6 to 8 of the cheap calls
    assert len(sets) == 50 and all(abs(panel.mean_cost()[k].sum() - 0.005) <= 0.00075 + 1e-12 for k in sets)
    sonnet = int(np.flatnonzero(panel.units["unit"] == "sonnet:0")[0])
    never = S.h7_cascade(panel, range(5), sonnet, 0)
    vote = predict(panel, S.mask_of(panel, range(5)))
    assert np.array_equal(never["correct"], vote["correct"]) and not never["escalated"].any()
    always = S.h7_cascade(panel, range(5), sonnet, 6)
    assert np.array_equal(always["correct"], panel.correct_matrix()[:, sonnet])
    assert np.allclose(always["dollars"], 5 * USD["haiku"] + USD["sonnet"])


# ---------------------------------------------------------------------------------------------------------
# staged grid

def synthetic_grid(n=100):
    """27 designs; accuracy = 0.30 + 0.10 [propose >= 3] + 0.05 [propose = 6] + 0.02 [refine >= 3], nothing
    from critique; dollars 0.001 per agent."""
    rows = []
    for p in (1, 3, 6):
        for c in (1, 3, 6):
            for r in (1, 3, 6):
                acc = 0.30 + 0.10 * (p >= 3) + 0.05 * (p == 6) + 0.02 * (r >= 3)
                for i in range(n):
                    rows.append({"config_id": f"k{p}-{c}-{r}-1", "task_id": f"t{i}", "correct": float(i < round(acc * n)),
                                 "cost_usd": 0.001 * (p + c + r + 1), "critical_path_s": 10.0 + p})
    return Grid.from_results(pd.DataFrame(rows))


def test_grid_sensitivity_and_netadapt_find_the_free_stage():
    grid = synthetic_grid()
    assert len(grid.points()) == 27
    sens = grid.points().set_index("design").loc["k6-6-6-1"]
    assert sens["accuracy"] == pytest.approx(0.47) and sens["dollars"] == pytest.approx(0.019)
    table = S.grid_sensitivity(grid, grid.items)
    critique = table[table["stage"] == "critique"]
    assert (critique["d_accuracy"] == 0).all() and (table[table["stage"] == "propose"]["d_accuracy"] < 0).all()
    path = S.grid_netadapt(grid, grid.items, step=0.0005)
    assert set(path["moved"].iloc[1:4]) == {"critique", "refine"}  # the free cuts come first
    assert path["design"].iloc[3] == "k6-1-3-1" and np.allclose(path["accuracy"].iloc[:4], 0.47)
    assert (np.diff(path["dollars"]) < 0).all() and path["design"].iloc[-1] == "k1-1-1-1"
    front = S.pareto(grid.points(), score="accuracy")
    assert front["design"].iloc[-1] == "k6-1-3-1"


def test_kevins_aggregator_does_not_depend_on_the_order_of_sources():
    """Audit 50: listing Sonnet before Haiku must not change the answers of a Haiku + Sonnet network (or of any
    sub-network), cross-fitted."""
    panel = small_panel()
    folds = np.arange(panel.n) % 2
    order = [5, 0, 1, 2, 3, 4]  # Sonnet first
    flipped = Panel.from_arrays(*[np.asarray(x)[:, order] for x in (answer_of(panel), panel.correct_matrix(), panel.cost)],
                                sources=[panel.units["source"][k] for k in order], calls=[panel.units["call"][k] for k in order])
    for names in (["haiku:0", "sonnet:0"], ["haiku:0", "haiku:1", "sonnet:0"], ["haiku:0", "haiku:1", "haiku:2", "sonnet:0"]):
        a = evaluate(panel, panel.mask(names), folds)["accuracy"]
        b = evaluate(flipped, flipped.mask(names), folds)["accuracy"]
        assert a == pytest.approx(b), names


def answer_of(panel):
    """Per call, an integer answer that reproduces the panel's classes (class index; -1 unparsed); class 0 of an item
    is right exactly when the class is."""
    return np.where(panel.votes >= 0, panel.votes, -1)
