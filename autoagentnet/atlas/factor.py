"""The Atlas factor model (session E5, section 4.3): why systems fail on the same items, and what that implies for
votes, selection and cascades.

Plain words first.
  ability a_s          how good system s is overall (log-odds scale).
  difficulty b_i       how hard item i is for everyone: the shared, systematic part of failure.
  failure beta beta_s  how strongly system s's success depends on difficulty (1 = like the average system; above 1
                       = its success collapses faster on hard items).
  family shock u_fi    an extra shared draw for the systems of one family (vendor or model family) on item i: what
                       makes two models of one vendor fail together beyond difficulty.
  call luck            what is left: the chance part of one call. Identified only where a system answered an item
                       more than once.
Levels, simplest first (P = probability that one call of s on i is right; sigmoid(x) = 1 / (1 + e^-x)):
  L0  logit P = a_s - b_i
  L1  logit P = a_s - beta_s b_i                 (fitted by alternating logistic fits with a ridge on a, beta and b,
                                                  which keeps the fit finite when items separate systems perfectly;
                                                  b is then reported with mean 0 and sd 1, a and beta rescaled)
  L2  logit P = a_s - beta_s b_i + u_{f(s),i}    (u ridge-penalised: a Gaussian random effect, MAP fit)
  L3  repeats: the counts k_si of right answers out of m_si calls give per-(system, item) success rates; the Pearson
      dispersion of k_si around m_si P_si (1 = binomial call luck only; above 1 = system-item effects beyond the
      model).
All fits are penalised logistic regressions (a small ridge keeps them finite on items every system gets right or
wrong). Evaluate on held-out items and held-out systems (`held_out`).

Derived quantities (each below, with its definition):
  systematic_share     var(b) / (var(b) + pi^2 / 3): the share of latent variation in success that items share
                       (the logistic call-level variance is pi^2 / 3).
  vote_ceiling         accuracy of infinitely many repeats of one system: the share of items whose most common answer
                       is right.
  coverage             coverage@k: the share of items at least one of a set of systems gets right (the ceiling of a
                       perfect selector); all-wrong = 1 - coverage, observed vs implied by a model.
  eta                  selection efficiency: (policy accuracy - best single accuracy) / (coverage - best single).
  vote_accuracy        predicted accuracy of a k-call plurality vote of one system on an item with success p, when
                       two wrong answers coincide with probability q.
  copula               a one-factor Gaussian copula for the tail (A2): system s fails on an item when a latent
                       normal z_s falls below tau_s = Phi^-1(1 - accuracy_s), with every pair of z's correlated rho
                       (one shared normal factor). rho is fitted so that the mean both-wrong rate over pairs matches
                       the observed one; the copula then implies the all-wrong rate of any set.
"""

from __future__ import annotations

from itertools import combinations

import numpy as np
import pandas as pd

LOGISTIC_VAR = np.pi ** 2 / 3
MAX_STEP = 2.0  # largest change of one coefficient in one Newton step


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(np.asarray(x, dtype=float), -500, 500)))


# ---------------------------------------------------------------------------------------------------------
# fitting

def _newton_1d_groups(X: np.ndarray, y: np.ndarray, offset: np.ndarray, groups: np.ndarray, n_groups: int,
                      l2: float, iters: int = 30, start: np.ndarray | None = None) -> np.ndarray:
    """Per-group logistic regression with one or two coefficients (columns of X), sharing nothing across groups:
    for each group g, maximise sum over its rows of log-lik(y | offset + X theta_g) - l2/2 |theta_g|^2. Vectorised
    Newton steps with 2x2 (or 1x1) Hessians, each coefficient's step clipped to MAX_STEP."""
    k = X.shape[1]
    theta = np.zeros((n_groups, k)) if start is None else start.copy()
    for _ in range(iters):
        eta = offset + np.einsum("ij,ij->i", X, theta[groups])
        p = sigmoid(eta)
        w = p * (1 - p)
        g = np.zeros((n_groups, k))
        H = np.zeros((n_groups, k, k))
        for j in range(k):
            np.add.at(g[:, j], groups, X[:, j] * (y - p))
            for m in range(k):
                np.add.at(H[:, j, m], groups, X[:, j] * X[:, m] * w)
        g -= l2 * theta
        H += l2 * np.eye(k)[None]
        step = np.linalg.solve(H + 1e-9 * np.eye(k)[None], g[..., None])[..., 0]
        step = np.clip(step, -MAX_STEP, MAX_STEP)  # a trust region: saturated groups have near-zero curvature
        theta += step
        if np.max(np.abs(step)) < 1e-8:
            break
    return theta


def encode(table: pd.DataFrame) -> dict:
    """Integer codes for systems, items and families, and the 0/1 outcome, from response-table rows (rows with a
    missing `correct` are dropped)."""
    t = table[table["correct"].notna()]
    systems = pd.Index(sorted(t["system"].unique()))
    items = pd.Index(sorted(t["item"].unique()))
    fam_of = t.drop_duplicates("system").set_index("system")["family"].reindex(systems).fillna("unknown")
    families = pd.Index(sorted(fam_of.unique()))
    return {"s": systems.get_indexer(t["system"]), "i": items.get_indexer(t["item"]),
            "y": t["correct"].to_numpy(dtype=float), "systems": systems, "items": items,
            "family_of_system": families.get_indexer(fam_of), "families": families}


def fit(table: pd.DataFrame, level: str = "L1", l2: float = 0.1, l2_shock: float = 1.0, l2_beta: float = 1.0,
        iters: int = 30) -> dict:
    """Fit L0, L1 or L2 to response-table rows. Returns a, b, beta (1 for L0), u (zeros unless L2) as pandas objects
    indexed by system / item, and the fitted encoding. Ridges: l2 on a and b, l2_beta on beta - 1 (a prior centred on
    the average system), l2_shock on the family shocks."""
    e = encode(table)
    s, i, y = e["s"], e["i"], e["y"]
    S, I = len(e["systems"]), len(e["items"])
    a, b, beta = np.zeros(S), np.zeros(I), np.ones(S)
    F = len(e["families"])
    u = np.zeros((F, I))
    f = e["family_of_system"][s]
    ones = np.ones((len(y), 1))
    for _ in range(iters):
        shock = u[f, i] if level == "L2" else 0.0
        # items: b_i with the systems fixed (coefficient -beta_s on b_i)
        b = _newton_1d_groups((-beta[s])[:, None], y, a[s] + shock, i, I, l2, start=b[:, None])[:, 0]
        # systems: a_s alone (L0) or (a_s, beta_s) (L1, L2) with the items fixed
        if level == "L0":
            a = _newton_1d_groups(ones, y, -b[i] + shock, s, S, l2, start=a[:, None])[:, 0]
        else:
            # beta = 1 + d: the offset carries the average slope, the ridge pulls d to 0; columns are scaled so that
            # one call of the ridge applies l2 to a and l2_beta to d
            r = np.sqrt(l2_beta / l2)
            theta = _newton_1d_groups(np.column_stack([np.ones(len(y)), -b[i] / r]), y, -b[i] + shock, s, S, l2,
                                      start=np.column_stack([a, (beta - 1) * r]))
            a, beta = theta[:, 0], 1 + theta[:, 1] / r
        if level == "L2":  # family shocks: one coefficient per (family, item), ridge l2_shock
            cell = f * I + i
            u = _newton_1d_groups(ones, y, a[s] - beta[s] * b[i], cell, F * I, l2_shock,
                                  start=u.reshape(-1, 1))[:, 0].reshape(F, I)
    if level != "L0" and b.std() > 0:  # report b with mean 0 and sd 1; a and beta absorb the shift and scale exactly
        mu, sd = b.mean(), b.std()
        a, beta, b = a - beta * mu, beta * sd, (b - mu) / sd
    return {"level": level, "a": pd.Series(a, index=e["systems"]), "b": pd.Series(b, index=e["items"]),
            "beta": pd.Series(beta, index=e["systems"]),
            "u": pd.DataFrame(u, index=e["families"], columns=e["items"]),
            "family": pd.Series(e["families"][e["family_of_system"]], index=e["systems"]), "encoding": e}


def predict(model: dict, systems, items, family=None) -> np.ndarray:
    """P(right) for each (system, item) pair (arrays of names; unknown items get b = 0, unknown systems a = 0)."""
    a = model["a"].reindex(systems).fillna(0.0).to_numpy()
    beta = model["beta"].reindex(systems).fillna(1.0).to_numpy()
    b = model["b"].reindex(items).fillna(0.0).to_numpy()
    eta = a - beta * b
    if model["level"] == "L2":
        fam = model["family"].reindex(systems).to_numpy() if family is None else np.asarray(family)
        u = model["u"]
        eta = eta + np.array([u.at[f, it] if (f in u.index and it in u.columns) else 0.0 for f, it in zip(fam, items)])
    return sigmoid(eta)


def log_loss(p, y) -> float:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def new_item_difficulty(model: dict, a: np.ndarray, beta: np.ndarray, y: np.ndarray) -> float:
    """A new item's difficulty from the answers of systems with known (a, beta), under the fitted difficulties'
    distribution as its prior: b = m + d with m and v the mean and variance of the model's b, d ridge-penalised with
    weight 1 / v (an empirical-Bayes prior; a flat weak ridge gives extreme b to items every system got right)."""
    m, v = float(model["b"].mean()), max(float(model["b"].var()), 1e-6)
    d = _newton_1d_groups((-beta)[:, None], y, a - beta * m, np.zeros(len(y), int), 1, 1.0 / v)[0, 0]
    return m + d


GRID_SD = np.linspace(-4, 4, 81)  # posterior grid for a new item's difficulty, in prior standard deviations


def item_posterior(model: dict, a: np.ndarray, beta: np.ndarray, y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """(grid of b, posterior weights) for a new item's difficulty given the 0/1 answers y of systems with known
    (a, beta), under the fitted difficulties' distribution N(m, v) as the prior (as in `new_item_difficulty`). Used
    to average a nonlinear prediction (a vote's accuracy) over the item's uncertain difficulty instead of plugging in
    a point estimate, which biases it."""
    m, sd = float(model["b"].mean()), max(float(model["b"].std()), 1e-3)
    grid = m + sd * GRID_SD
    logit = a[None, :] - beta[None, :] * grid[:, None]  # grid x systems
    loglik = (y[None, :] * -np.logaddexp(0, -logit) + (1 - y[None, :]) * -np.logaddexp(0, logit)).sum(axis=1)
    logpost = loglik - 0.5 * GRID_SD ** 2
    w = np.exp(logpost - logpost.max())
    return grid, w / w.sum()


def new_system(model: dict, b: np.ndarray, y: np.ndarray, level: str = "L1") -> tuple[float, float]:
    """A new system's (a, beta) on items with known difficulties, with the fitted systems' mean a (and beta) as the
    prior centre and a unit ridge around it (beta stays 1 under L0)."""
    a0 = float(model["a"].mean())
    if level == "L0":
        d = _newton_1d_groups(np.ones((len(y), 1)), y, a0 - b, np.zeros(len(y), int), 1, 1.0)[0, 0]
        return a0 + d, 1.0
    beta0 = float(model["beta"].mean())
    d = _newton_1d_groups(np.column_stack([np.ones(len(y)), -b]), y, a0 - beta0 * b, np.zeros(len(y), int), 1, 1.0)[0]
    return a0 + d[0], beta0 + d[1]


def held_out(table: pd.DataFrame, level: str = "L1", by: str = "item", fraction: float = 0.3, seed: int = 0,
             **kw) -> dict:
    """Held-out evaluation, so that a fit is never scored on what it was fitted to.
    by="item": fit on 70% of the items (all systems); for each held-out item, fit its difficulty b_i on the answers of
    a random half of the systems (abilities frozen; `new_item_difficulty`) and score the other half of the systems on it.
    by="system": fit on 70% of the systems (all items); for each held-out system, fit its (a_s, beta_s) on a random half
    of the items (difficulties frozen; `new_system`) and score it on the other half.
    Returns the scored rows' log loss, the log loss of the training base rate, and the accuracy of predicting
    "right" when P > 0.5."""
    rng = np.random.default_rng(seed)
    t = table[table["correct"].notna()]
    names = sorted(t[by].unique())
    test = set(rng.choice(names, max(1, int(round(fraction * len(names)))), replace=False))
    train = t[~t[by].isin(test)]
    model = fit(train, level, **kw)
    other = "system" if by == "item" else "item"
    held = t[t[by].isin(test)]
    others = sorted(held[other].unique())
    half = set(rng.choice(others, len(others) // 2, replace=False))
    fit_rows, score_rows = held[held[other].isin(half)], held[~held[other].isin(half)]
    if by == "item":  # each held-out item's b from the first half of systems, a and beta frozen
        b_new = {}
        for item, g in fit_rows.groupby("item"):
            a = model["a"].reindex(g["system"]).fillna(0).to_numpy()
            beta = model["beta"].reindex(g["system"]).fillna(1).to_numpy()
            b_new[item] = new_item_difficulty(model, a, beta, g["correct"].to_numpy(float))
        model = {**model, "b": pd.concat([model["b"], pd.Series(b_new)])}
    else:  # each held-out system's (a, beta) from the first half of items
        a_new, beta_new = {}, {}
        for system, g in fit_rows.groupby("system"):
            bb = model["b"].reindex(g["item"]).fillna(0).to_numpy()
            a_new[system], beta_new[system] = new_system(model, bb, g["correct"].to_numpy(float), level)
        model = {**model, "a": pd.concat([model["a"], pd.Series(a_new)]),
                 "beta": pd.concat([model["beta"], pd.Series(beta_new)]), "level": "L1" if level == "L2" else level}
    p = predict(model, score_rows["system"].to_numpy(), score_rows["item"].to_numpy())
    y = score_rows["correct"].to_numpy(float)
    base = np.full(len(y), train["correct"].mean())
    return {"by": by, "level": level, "n_scored": len(y), "log_loss": log_loss(p, y), "log_loss_base_rate": log_loss(base, y),
            "accuracy": float(((p > 0.5) == (y > 0.5)).mean())}


def dispersion(table: pd.DataFrame, model: dict) -> dict:
    """L3: Pearson dispersion of right-answer counts over repeats around the model's prediction, over (system, item)
    cells with at least 2 calls. 1 = binomial call luck only."""
    t = table[table["correct"].notna()]
    cells = t.groupby(["system", "item"])["correct"].agg(["sum", "size"]).reset_index()
    cells = cells[cells["size"] >= 2]
    if cells.empty:
        return {"cells": 0, "dispersion": float("nan")}
    p = np.clip(predict(model, cells["system"].to_numpy(), cells["item"].to_numpy()), 1e-6, 1 - 1e-6)
    m, k = cells["size"].to_numpy(float), cells["sum"].to_numpy(float)
    chi2 = ((k - m * p) ** 2 / (m * p * (1 - p))).sum()
    return {"cells": len(cells), "dispersion": float(chi2 / len(cells))}


# ---------------------------------------------------------------------------------------------------------
# derived quantities

def systematic_share(b) -> float:
    """var(b) / (var(b) + pi^2 / 3), b the item difficulties on the logit scale (with beta near 1)."""
    v = float(np.var(np.asarray(b, dtype=float)))
    return v / (v + LOGISTIC_VAR)


def vote_ceiling(table: pd.DataFrame, system: str) -> float:
    """Share of items whose most common answer of `system` (over its repeats) is right; ties count as half right
    when one of the tied answers is right. Needs the answer column; items with fewer than 2 calls are skipped."""
    t = table[(table["system"] == system) & table["correct"].notna()]
    scores = []
    for _, g in t.groupby("item"):
        if len(g) < 2:
            continue
        counts = g.groupby(g["answer"].fillna("<unparsed>"))["correct"].agg(["size", "max"])
        top = counts[counts["size"] == counts["size"].max()]
        scores.append(top["max"].mean())
    return float(np.mean(scores)) if scores else float("nan")


def outcome_matrix(table: pd.DataFrame, call: int = 0) -> pd.DataFrame:
    """items x systems matrix of 0/1 outcomes for one call index (missing where a system did not answer)."""
    t = table[(table["call"] == call) & table["correct"].notna()]
    return t.pivot_table(index="item", columns="system", values="correct", aggfunc="first")


def coverage(Y: pd.DataFrame, systems) -> float:
    """coverage@k over the items every listed system answered: the share at least one gets right."""
    sub = Y[list(systems)].dropna()
    return float((sub.max(axis=1) > 0).mean())


def all_wrong_implied(model: dict, systems, items) -> float:
    """Mean over items of the model's probability that every listed system is wrong (independent calls given the
    item's difficulty and family shocks)."""
    systems, items = list(systems), list(items)
    prod = np.ones(len(items))
    for s in systems:
        prod *= 1 - predict(model, np.repeat(s, len(items)), np.array(items))
    return float(prod.mean())


def sample_sets(names, k: int, max_sets: int, rng) -> list[tuple]:
    """Every k-subset of `names` when there are at most max_sets of them, else max_sets distinct random ones (drawn
    without listing all subsets, which can number in the billions)."""
    from math import comb

    names = list(names)
    if comb(len(names), k) <= max_sets:
        return list(combinations(names, k))
    seen: set[tuple] = set()
    while len(seen) < max_sets:
        seen.add(tuple(sorted(rng.choice(len(names), k, replace=False))))
    return [tuple(names[j] for j in idx) for idx in sorted(seen)]


def coverage_table(Y: pd.DataFrame, model: dict | None, k_max: int = 5, max_sets: int = 2000, seed: int = 0,
                   rho: float | None = None) -> pd.DataFrame:
    """For k = 1..k_max: mean over (up to max_sets random) k-subsets of systems of the observed coverage, the
    observed all-wrong rate, the all-wrong rate implied by independence of systems (product of 1 - accuracy), and,
    with a model, the model-implied all-wrong rate; with rho, the one-factor Gaussian copula's; plus the best single
    accuracy within the set."""
    rng = np.random.default_rng(seed)
    systems = list(Y.columns)
    acc = Y.mean()
    rows = []
    for k in range(1, k_max + 1):
        for st in sample_sets(systems, k, max_sets, rng):
            sub = Y[list(st)].dropna()
            cov = float((sub.max(axis=1) > 0).mean())
            row = {"k": k, "coverage": cov, "all_wrong": 1 - cov, "best_single": float(acc[list(st)].max()),
                   "independent_all_wrong": float(np.prod(1 - acc[list(st)]))}
            if model is not None:
                row["model_all_wrong"] = all_wrong_implied(model, st, sub.index)
            if rho is not None:
                row["copula_all_wrong"] = copula_all_wrong(sub.mean().to_numpy(), rho)
            rows.append(row)
    return pd.DataFrame(rows).groupby("k").mean().reset_index()


def eta(policy_accuracy: float, best_single: float, cover: float) -> float:
    """Selection efficiency: the share of the gap from the best single system to a perfect selector that a policy
    closes (NaN when the set has no gap)."""
    gap = cover - best_single
    return float((policy_accuracy - best_single) / gap) if gap > 1e-12 else float("nan")


GH_NODES, GH_WEIGHTS = np.polynomial.hermite_e.hermegauss(80)  # E over a standard normal: sum w f(x) / sqrt(2 pi)


def copula_all_wrong(accuracy, rho: float) -> float:
    """P(every system in the set is wrong) under the one-factor Gaussian copula with correlation rho."""
    from scipy.stats import norm

    tau = norm.ppf(1 - np.clip(np.asarray(accuracy, dtype=float), 1e-6, 1 - 1e-6))
    r = float(np.clip(rho, 0.0, 0.999))
    cond = norm.cdf((tau[None, :] - np.sqrt(r) * GH_NODES[:, None]) / np.sqrt(1 - r)).prod(axis=1)
    return float((GH_WEIGHTS * cond).sum() / np.sqrt(2 * np.pi))


def fit_copula_rho(Y: pd.DataFrame, max_pairs: int = 3000, seed: int = 0) -> float:
    """The rho whose mean both-wrong rate over (up to max_pairs random) pairs of systems matches the observed mean
    (each pair on the items both answered); bisection on [0, 0.999]."""
    rng = np.random.default_rng(seed)
    pairs = list(combinations(Y.columns, 2))
    if len(pairs) > max_pairs:
        pairs = [pairs[j] for j in rng.choice(len(pairs), max_pairs, replace=False)]
    acc, observed = [], []
    for s, t in pairs:
        sub = Y[[s, t]].dropna()
        if len(sub) == 0:
            continue
        acc.append(sub.mean().to_numpy())
        observed.append(float(((sub[s] == 0) & (sub[t] == 0)).mean()))
    target = float(np.mean(observed))
    lo, hi = 0.0, 0.999
    for _ in range(40):
        mid = (lo + hi) / 2
        if np.mean([copula_all_wrong(a, mid) for a in acc]) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


def vote_accuracy(p, k: int, q: float = 0.5) -> np.ndarray:
    """Predicted accuracy of a k-call plurality vote of one system, per item with one-call success p, when any two
    wrong answers coincide with probability q (q = 1: all wrong answers are the same; q = 0: all differ). Exact for
    k = 1 and 3; for other k, wrong answers are treated as one block (q = 1), a lower bound. Ties are broken at
    random among the tied answers."""
    p = np.asarray(p, dtype=float)
    if k == 1:
        return p
    if k == 3:
        # 3 right; 2 right; 1 right and 2 wrong that differ (3-way tie, 1/3); 1 right and 2 equal wrong: lost
        return p ** 3 + 3 * p ** 2 * (1 - p) + 3 * p * (1 - p) ** 2 * (1 - q) / 3
    from scipy.stats import binom
    j = np.arange(k + 1)
    right = binom.pmf(j[None, :], k, p[:, None])
    win = np.where(j > k - j, 1.0, np.where(j == k - j, 0.5, 0.0))
    return (right * win[None, :]).sum(axis=1)
