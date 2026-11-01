"""Pruning criteria for agent networks: how much each group of calls matters (Phase 3 of the evidence plan).

Each criterion scores the groups of a network (see replay.py: a group is a set of units removed together) on
some items; a higher score means "keep". Pruning removes the lowest-scoring group first (ties: the more
expensive group first). The analogies are to neural-network pruning, with a call group in place of a
channel. On choice tasks the "weights" are the coefficients of Kevin's aggregator (replay.py): a ridge
logistic model of P(the plurality answer is right) with one agreement feature per group (the share of the
group's kept calls agreeing with the plurality answer), fitted on the dense network. Forecasts have a one-number
aggregator (the extremizing factor), so there C1-C3b use the weighted-vote coefficients instead (one weight per
call on its log-odds, replay.py "weights"), summed over a group's calls.

  C1  magnitude          |standardized coefficient| = |beta_g| x the (fit-weighted) standard deviation of feature g (forecasts:
                         the sum over the group's calls of |w| x the SD of the call's log-odds); Han et al.
  C2  slimming           the L1 path: refit with penalty lambda * sum_g |beta_g| (forecasts: group lasso on the
                         calls' weights; Liu et al.'s network slimming); the score is the largest lambda, as a share
                         of the lambda at which every coefficient is 0, at which the group is still non-zero, i.e.
                         groups that reach zero first are pruned first.
  C3  OBD                optimal brain damage: 0.5 * h_gg beta_g^2, with h_gg the diagonal of the Hessian of the
                         fitted log loss (the loss increase from zeroing the group, to second order, ignoring how
                         the other coefficients would adjust).
  C3b OBS                optimal brain surgeon: beta_g^2 / (2 [H^-1]_gg), the same loss increase when the other
                         coefficients do adjust (it keeps the cross terms: the correlation-aware version).
  C4  flip rate          label-free (APoZ-like: a channel that rarely changes the output is dispensable):
                         the share of items whose vote answer changes when the group is removed (forecasts:
                         the mean absolute change of the mean probability). `agreement` reports the share of
                         items on which a group's calls agree with the network's vote answer.
  C5  reconstruction     label-free (He et al.'s channel pruning): a non-negative group lasso that rebuilds
                         the network's vote shares (forecasts: its mean probability) from the calls' votes;
                         the score is the largest lambda share at which the group is still used.
  C6  leave-one-out      exact: the out-of-fold log loss of the network without the group minus that of the
                         network, each with its aggregator refitted (two folds of the given items); the log loss
                         is of the confidence against "the answer is right" (forecasts: of P(yes) against the
                         outcome).
  C7  information per $  (a) the group's marginal effective number of calls, n_eff(S) = 1' R_S^-1 1 with
                         R_S the correlation matrix of the kept calls' correctness (forecasts: of their squared
                         errors), n_eff(kept) - n_eff(kept without G), per dollar of the group's calls per
                         item. A flaw: n_eff ignores accuracy, so an uncorrelated bad call counts as a full call.
                         (b) the Gaussian-copula conditional mutual information (nats) between the group's
                         votes and the truth given the other kept calls' votes, per dollar: rows are
                         (item, candidate answer) pairs with truth = "this candidate is right" (forecasts:
                         items, votes = log-odds, truth = outcome); each column is replaced by the normal
                         scores of its ranks (Ince et al. 2017) and I(X; Y | Z) is the Gaussian formula
                         0.5 * log(det S_XZ det S_YZ / (det S_Z det S_XYZ)).

Label-free criteria (C4, C5) never read correctness. Every function has the signature
(panel, kept, grp, rows=None) -> pd.Series indexed by group name, over the groups with at least one kept
unit; `kept` is the network being pruned (boolean over units), `rows` the items to score on.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm, rankdata

from autoagentnet.evidence.calibration import two_folds

from .replay import (L2, Panel, cross_fit, design, fit, logistic_newton, newton, objective, plurality_data, predict,
                     score_of)

N_LAMBDA = 30


def live(kept, grp: dict) -> dict:
    kept = np.asarray(kept, dtype=bool)
    return {name: units[kept[units]] for name, units in grp.items() if kept[units].any()}


def group_dollars(panel: Panel, units, rows=None) -> float:
    return float(panel.mean_cost(rows)[units].sum())


def aggregator_fit(panel: Panel, kept, grp: dict, rows=None):
    """Kevin's aggregator on a choice panel with one feature per live group: (names, beta, H, F, y, weights), H the
    Hessian of the ridge log loss over (features, intercept)."""
    alive = live(kept, grp)
    names = list(alive)
    F, y, wt = plurality_data(panel, kept, rows, [alive[k] for k in names])
    beta = logistic_newton(F, y, L2, wt)
    A = np.column_stack([F, np.ones(len(y))])
    p = 1 / (1 + np.exp(-(A @ beta)))
    H = (A * (wt * p * (1 - p))[:, None]).T @ A + np.diag(np.r_[np.full(len(names), L2), 0.0])
    return names, beta, H, F, y, wt


def c1_magnitude(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    if panel.kind == "choice":
        names, beta, _, F, _, wt = aggregator_fit(panel, kept, grp, rows)
        sd = np.sqrt(np.average((F - np.average(F, axis=0, weights=wt)) ** 2, axis=0, weights=wt))
        return pd.Series({k: float(abs(beta[j]) * sd[j]) for j, k in enumerate(names)})
    w = fit(panel, kept, rows, "weights")
    P = panel.votes[np.arange(panel.n) if rows is None else rows]
    sd = np.log(P / (1 - P)).std(axis=0)
    return pd.Series({name: float((np.abs(w[u]) * sd[u]).sum()) for name, u in live(kept, grp).items()})


def fitted_hessian(panel: Panel, kept, rows=None):
    """(w, H) of the weighted-vote refit, over the kept units and the intercept (the last entry); forecasts."""
    kept = np.asarray(kept, dtype=bool)
    w = fit(panel, kept, rows, "weights")
    X, valid, gold = design(panel, kept, rows)
    pen = np.ones(X.shape[2], dtype=bool)
    pen[-1] = False
    _, _, H = objective(w, X, valid, gold, L2, pen)
    return w, H


def c3_obd(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    if panel.kind == "choice":
        names, beta, H, _, _, _ = aggregator_fit(panel, kept, grp, rows)
        return pd.Series({k: float(0.5 * H[j, j] * beta[j] ** 2) for j, k in enumerate(names)})
    w, H = fitted_hessian(panel, kept, rows)
    h = np.diag(H)
    return pd.Series({name: float(0.5 * (h[u] * w[u] ** 2).sum()) for name, u in live(kept, grp).items()})


def c3b_obs(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    if panel.kind == "choice":
        names, beta, H, _, _, _ = aggregator_fit(panel, kept, grp, rows)
        Hinv = np.linalg.pinv(H)
        return pd.Series({k: float(beta[j] ** 2 / (2 * Hinv[j, j])) for j, k in enumerate(names)})
    w, H = fitted_hessian(panel, kept, rows)
    Hinv = np.linalg.pinv(H)
    out = {}
    for name, u in live(kept, grp).items():
        block = Hinv[np.ix_(u, u)]
        out[name] = float(0.5 * w[u] @ np.linalg.pinv(block) @ w[u])
    return pd.Series(out)


def c4_flip(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    kept = np.asarray(kept, dtype=bool)
    base = predict(panel, kept, rows)
    out = {}
    for name, u in live(kept, grp).items():
        less = kept.copy()
        less[u] = False
        new = predict(panel, less, rows)
        if panel.kind == "prob":
            out[name] = float((new["prob"] - base["prob"]).abs().mean())
        else:
            out[name] = float((new["slot"].to_numpy() != base["slot"].to_numpy()).mean())
    return pd.Series(out)


def agreement(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    """Label-free: the share of items on which a group's calls agree with the network's vote answer (forecasts:
    1 minus the mean absolute gap to the network's mean probability), averaged over the group's calls."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    base = predict(panel, kept, rows)
    out = {}
    for name, u in live(kept, grp).items():
        if panel.kind == "prob":
            out[name] = float(1 - np.abs(panel.votes[rows][:, u] - base["prob"].to_numpy()[:, None]).mean())
        else:
            out[name] = float((panel.votes[rows][:, u] == base["slot"].to_numpy()[:, None]).mean())
    return pd.Series(out)


def log_loss_of(frame: pd.DataFrame, kind: str) -> float:
    """Mean log loss of a replay frame's confidence against "the answer is right" (forecasts: P(yes) vs outcome)."""
    if kind == "prob":
        p, y = frame["prob"].to_numpy(), frame["outcome"].to_numpy()
    else:
        p, y = frame["confidence"].to_numpy(), frame["correct"].to_numpy()
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return float(-(y * np.log(p) + (1 - y) * np.log(1 - p)).mean())


def c6_leave_out(panel: Panel, kept, grp: dict, rows=None, refit: str = "ridge", seed: int = 0) -> pd.Series:
    kept = np.asarray(kept, dtype=bool)
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    sub = panel.subset(rows)
    folds = two_folds(len(rows), seed=seed)
    base = log_loss_of(cross_fit(sub, kept, folds, refit), panel.kind)
    out = {}
    for name, u in live(kept, grp).items():
        less = kept.copy()
        less[u] = False
        out[name] = log_loss_of(cross_fit(sub, less, folds, refit), panel.kind) - base if less.any() else np.inf
    return pd.Series(out)


# ---------------------------------------------------------------------------------------------------------
# group-lasso paths (C2, C5)

def fista(value_grad, w0, lipschitz: float, lam: float, groups: list, nonneg: bool = False, iters: int = 400):
    """Minimize f(w) + lam * sum_G |w_G|_2 by accelerated proximal gradient; entries in no group are free."""
    w = w0.copy()
    y, t = w.copy(), 1.0
    step = 1.0 / lipschitz
    for _ in range(iters):
        _, g = value_grad(y)
        z = y - step * g
        if nonneg:
            z = np.maximum(z, 0)
        for u in groups:
            norm_u = np.linalg.norm(z[u])
            z[u] = 0.0 if norm_u <= step * lam else z[u] * (1 - step * lam / norm_u)
        t_new = (1 + np.sqrt(1 + 4 * t * t)) / 2
        y = z + (t - 1) / t_new * (z - w)
        if np.abs(z - w).max() < 1e-9:
            w = z
            break
        w, t = z, t_new
    return w


def path_scores(value_grad, w_start, lipschitz, groups: dict, nonneg: bool = False, n_lambda: int = N_LAMBDA) -> pd.Series:
    """The largest lambda share (1 = lambda_max) at which each group is non-zero, plus a tie-break of 1e-6
    times its norm at the smallest lambda."""
    names = list(groups)
    us = [groups[k] for k in names]
    _, g0 = value_grad(w_start)
    lam_max = max(float(np.linalg.norm(np.maximum(-g0[u], 0) if nonneg else g0[u])) for u in us)
    if lam_max <= 0:
        return pd.Series(0.0, index=names)
    entry = {k: 0.0 for k in names}
    w = w_start.copy()
    for share in np.geomspace(1, 0.01, n_lambda):
        w = fista(value_grad, w, lipschitz, share * lam_max, us, nonneg)
        for k, u in zip(names, us):
            if entry[k] == 0.0 and np.linalg.norm(w[u]) > 1e-8:
                entry[k] = float(share)
    return pd.Series({k: entry[k] + 1e-6 * float(np.linalg.norm(w[u])) for k, u in zip(names, us)})


def c2_slimming(panel: Panel, kept, grp: dict, rows=None, n_lambda: int = N_LAMBDA) -> pd.Series:
    kept = np.asarray(kept, dtype=bool)
    if panel.kind == "choice":
        alive = live(kept, grp)
        names = list(alive)
        F, y, wt = plurality_data(panel, kept, rows, [alive[k] for k in names])
        A = np.column_stack([F, np.ones(len(y))])
        b0 = np.zeros(A.shape[1])  # the intercept-only fit, where every group's coefficient is 0
        ybar = float(np.average(y, weights=wt))
        b0[-1] = np.log(np.clip(ybar, 1e-6, 1 - 1e-6) / np.clip(1 - ybar, 1e-6, 1))

        def value_grad_b(b):  # the lasso is the penalty; a tiny ridge keeps the path stable
            z = A @ b
            p = 1 / (1 + np.exp(-z))
            pen = np.r_[np.full(len(names), 1e-3), 0.0]
            return float(np.sum(wt * (np.logaddexp(0, z) - y * z))), A.T @ (wt * (p - y)) + pen * b

        lipschitz = float(np.linalg.eigvalsh(A.T @ A).max()) / 4 + 1e-3
        return path_scores(value_grad_b, b0, lipschitz, {k: np.array([j]) for j, k in enumerate(names)}, n_lambda=n_lambda)
    X, valid, gold = design(panel, kept, rows)
    w0 = np.zeros(X.shape[2])  # start from the intercept-only fit, where every unit weight is 0
    w0[-1] = newton(X[:, :, -1:], valid, gold, 0.0, np.zeros(1, dtype=bool))[0]

    def value_grad(w):  # the lasso is the penalty; a tiny ridge keeps the path stable
        v, g, _ = objective(w, X, valid, gold, 1e-3, hessian=False)
        return v, g

    lipschitz = float(np.linalg.eigvalsh(np.einsum("naf,nag->fg", X, X)).max()) + 1e-3
    return path_scores(value_grad, w0, lipschitz, live(kept, grp), n_lambda=n_lambda)


def c5_reconstruction(panel: Panel, kept, grp: dict, rows=None, n_lambda: int = N_LAMBDA) -> pd.Series:
    kept = np.asarray(kept, dtype=bool)
    X, valid, _ = design(panel, kept, rows)
    m = panel.m
    if panel.kind == "prob":
        F = (panel.votes[np.arange(panel.n) if rows is None else rows] * kept)  # items x units
        target = F[:, kept].mean(axis=1)
    else:
        K = X.shape[1] - 1
        F = X[:, :K, :m].reshape(-1, m)  # (item, class) rows x units
        target = F.sum(axis=1) / max(int(kept.sum()), 1)
        keep_rows = valid[:, :K].reshape(-1)
        F, target = F[keep_rows], target[keep_rows]
    N = len(target)

    def value_grad(b):
        r = F @ b - target
        return 0.5 * (r @ r) / N, F.T @ r / N

    lipschitz = float(np.linalg.eigvalsh(F.T @ F / N).max()) + 1e-9
    return path_scores(value_grad, np.zeros(m), lipschitz, live(kept, grp), nonneg=True, n_lambda=n_lambda)


# ---------------------------------------------------------------------------------------------------------
# information per dollar (C7)

def n_eff(R: np.ndarray) -> float:
    """1' R^-1 1 (pseudo-inverse), the effective number of equally informative calls."""
    if len(R) == 0:
        return 0.0
    one = np.ones(len(R))
    return float(one @ np.linalg.pinv(R) @ one)


def correctness_corr(panel: Panel, rows=None) -> np.ndarray:
    Z = panel.correct_matrix()[np.arange(panel.n) if rows is None else rows]
    with np.errstate(invalid="ignore", divide="ignore"):
        R = np.corrcoef(Z, rowvar=False)
    R = np.where(np.isfinite(R), R, 0.0)
    np.fill_diagonal(R, 1.0)
    return R


def c7_neff_per_dollar(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    kept = np.asarray(kept, dtype=bool)
    R = correctness_corr(panel, rows)
    idx = np.flatnonzero(kept)
    full = n_eff(R[np.ix_(idx, idx)])
    out = {}
    for name, u in live(kept, grp).items():
        rest = np.setdiff1d(idx, u)
        out[name] = (full - n_eff(R[np.ix_(rest, rest)])) / max(group_dollars(panel, u, rows), 1e-12)
    return pd.Series(out)


def copula_normal(x: np.ndarray) -> np.ndarray:
    """Normal scores of a column's ranks (average ranks for ties)."""
    return norm.ppf(rankdata(x) / (len(x) + 1))


def gaussian_cmi(X: np.ndarray, Y: np.ndarray, Z: np.ndarray) -> float:
    """I(X; Y | Z) in nats for jointly Gaussian columns (Z may have no columns)."""
    def logdet(*blocks):
        M = np.column_stack(blocks) if blocks else np.zeros((len(X), 0))
        if M.shape[1] == 0:
            return 0.0
        S = np.atleast_2d(np.cov(M, rowvar=False)) + 1e-6 * np.eye(M.shape[1])
        return float(np.linalg.slogdet(S)[1])
    return max(0.0, 0.5 * (logdet(X, Z) + logdet(Y, Z) - logdet(Z) - logdet(X, Y, Z)) if Z.shape[1]
               else 0.5 * (logdet(X) + logdet(Y) - logdet(X, Y)))


def mi_rows(panel: Panel, kept, rows=None) -> tuple[np.ndarray, np.ndarray]:
    """(votes, truth): rows x units votes and the truth column, before the copula transform."""
    kept = np.asarray(kept, dtype=bool)
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    if panel.kind == "prob":
        P = panel.votes[rows]
        return np.log(P / (1 - P)), panel.outcome[rows]
    X, valid, _ = design(panel, kept, rows)
    K = X.shape[1] - 1
    V = X[:, :K, :panel.m].reshape(-1, panel.m)
    y = panel.class_correct[rows][:, :K].reshape(-1)
    use = valid[:, :K].reshape(-1)
    return V[use], y[use]


def c7_mi_per_dollar(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    kept = np.asarray(kept, dtype=bool)
    V, y = mi_rows(panel, kept, rows)
    G = np.column_stack([copula_normal(V[:, g]) for g in range(panel.m)])
    Y = copula_normal(y)[:, None]
    idx = np.flatnonzero(kept)
    out = {}
    for name, u in live(kept, grp).items():
        rest = np.setdiff1d(idx, u)
        out[name] = gaussian_cmi(G[:, u], Y, G[:, rest]) / max(group_dollars(panel, u, rows), 1e-12)
    return pd.Series(out)


def mi_items(panel: Panel, kept, rows=None) -> np.ndarray:
    """The item (row of the panel) of each row `mi_rows` returns, in the same order."""
    kept = np.asarray(kept, dtype=bool)
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    if panel.kind == "prob":
        return rows
    _, valid, _ = design(panel, kept, rows)
    K = valid.shape[1] - 1
    return np.repeat(rows, K)[valid[:, :K].reshape(-1)]


def entropy_nats(y: np.ndarray) -> float:
    """Entropy, in nats, of a 0/1 variable with the mean of y."""
    q = float(np.clip(np.mean(y), 1e-12, 1 - 1e-12))
    return -(q * np.log(q) + (1 - q) * np.log(1 - q))


def predictive_information(F: np.ndarray, y: np.ndarray, groups: np.ndarray, folds: int = 5, l2: float = 1.0,
                           seed: int = 0) -> float:
    """A lower bound on the mutual information I(F; y) in nats: H(y) minus the held-out log loss of a ridge
    logistic regression of y on F (folds by group, so an item's rows are never split). It can never exceed H(y),
    which is at most ln 2 for a 0/1 truth; a negative estimate (no detectable information) is reported as 0."""
    ids = np.unique(groups)
    fold_of = dict(zip(ids, np.random.default_rng(seed).permutation(len(ids)) % folds))
    fold = np.array([fold_of[g] for g in groups])
    p = np.zeros(len(y))
    for k in range(folds):
        test = fold == k
        if not test.any() or test.all():
            continue
        beta = logistic_newton(F[~test], y[~test], l2)
        p[test] = 1 / (1 + np.exp(-(np.column_stack([F[test], np.ones(test.sum())]) @ beta)))
    p = np.clip(p, 1e-6, 1 - 1e-6)
    loss = -np.mean(y * np.log(p) + (1 - y) * np.log(1 - p))
    return max(0.0, entropy_nats(y) - loss)


def set_information(panel: Panel, units, rows=None, pool=None) -> dict:
    """Session E5, patch 2.3: for a set of calls (units), next to its effective number of calls, the information
    its votes carry about the true answer. n_eff ignores accuracy (an independent near-random call counts as a full
    call); the information does not.
      n_eff        1' R^-1 1 over the set's correctness correlations (as in C7a).
      info_nats    predictive information about "this candidate is right" (`predictive_information`): the entropy
                   of that 0/1 truth minus the held-out log loss of a logistic regression of it on the set's votes,
                   on the C7b rows (one row per (item, candidate answer); forecasts: one row per item, votes =
                   log-odds, truth = outcome), folds by item. A lower bound on the mutual information, so at most
                   the truth's entropy (h_nats, at most ln 2 = 0.693). The candidates are those proposed by the
                   `pool` units (default: every unit of the panel), the same for every set, so sets are compared on
                   the same rows. (Until audit 68 this was a Gaussian-copula number, which for 0/1 votes is the
                   information of latent Gaussians, not of the votes, and could exceed ln 2.)
      dollars      mean dollars per item of the set's calls; info_per_dollar = info_nats / dollars."""
    units = np.asarray(units)
    pooled = np.ones(panel.m, dtype=bool) if pool is None else np.isin(np.arange(panel.m), pool)
    R = correctness_corr(panel, rows)
    V, y = mi_rows(panel, pooled, rows)
    groups = mi_items(panel, pooled, rows)
    info = predictive_information(V[:, units].astype(float), y.astype(float), groups)
    dollars = group_dollars(panel, units, rows)
    return {"n_eff": n_eff(R[np.ix_(units, units)]), "info_nats": info, "h_nats": entropy_nats(y),
            "dollars": dollars, "info_per_dollar": info / max(dollars, 1e-12)}


CRITERIA = {"C1": c1_magnitude, "C2": c2_slimming, "C3": c3_obd, "C3b": c3b_obs, "C4": c4_flip,
            "C5": c5_reconstruction, "C6": c6_leave_out, "C7a": c7_neff_per_dollar, "C7b": c7_mi_per_dollar}
LABEL_FREE = {"C4", "C5"}


def all_criteria(panel: Panel, kept, grp: dict, rows=None) -> pd.DataFrame:
    """Every criterion's score (columns) per group (rows), plus each group's dollars per item."""
    frame = pd.DataFrame({name: fn(panel, kept, grp, rows) for name, fn in CRITERIA.items()})
    frame["agreement"] = agreement(panel, kept, grp, rows)
    frame["dollars"] = pd.Series({k: group_dollars(panel, u, rows) for k, u in live(kept, grp).items()})
    return frame
