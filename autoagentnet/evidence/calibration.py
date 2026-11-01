"""Honest confidence from correlated agreement (step 0.8; plan, "Definitions").

Terms (plain words first):
  confidence c         the stated probability that an answer is right, or for a forecast that the
                       question resolves YES. y is 1 if right (or YES) and 0 if not.
  clip                 every probability is clipped to [0.01, 0.99] before log-odds, log loss or a stake.
  calibration gap      mean confidence minus accuracy (mean y), in points when multiplied by 100;
                       positive = overconfident.
  Brier score          mean of (c - y)^2; lower is better.
  log loss             mean of -(y log c + (1 - y) log(1 - c)).
  ECE                  sort items into 10 equal-count bins by confidence; the mean over bins of
                       |bin mean confidence - bin accuracy| (bins have equal counts, so equal weights).
  intercept and slope  a logistic regression of y on logit(c): intercept 0 and slope 1 mean calibrated;
                       a slope below 1 means overconfident (too extreme), the intercept is a base-rate shift.
  correction           a logistic regression of y on features of the panel's answers (such as the share
                       agreeing with the plurality and whether a second model agrees), fitted on some items
                       and applied to others.
  cross-fitting        split the items into folds; each fold's predictions come from a fit on the other
                       folds, so every item is scored out of sample.
  extremizing factor a multiplies the panel's mean log-odds: f = sigmoid(a * mean_k logit f_k). a > 1 moves
                       forecasts away from 50%. Fitted by maximum likelihood (a logistic regression of y on the
                       mean log-odds with no intercept).
  discrimination       (session E5, patch 2.2) how well the confidence separates right from wrong, whatever its
                       level. Calibration measures (gap, intercept, slope) can improve while discrimination gets
                       worse, e.g. when near-random voters dilute a vote share: the share drops toward accuracy
                       without ranking items any better. So both are reported together.
  AUROC                the chance that a randomly chosen right item has a higher confidence than a randomly chosen
                       wrong one (ties count one half); 0.5 = no discrimination, 1 = perfect.
  Murphy terms         Brier = reliability - resolution + uncertainty, over groups of items with (nearly) the same
                       confidence: reliability = sum_k (n_k / n) (mean c_k - mean y_k)^2 (miscalibration, lower is
                       better); resolution = sum_k (n_k / n) (mean y_k - mean y)^2 (how far the groups' accuracies
                       spread from the overall rate, higher is better; a discrimination measure); uncertainty =
                       mean y (1 - mean y). Groups are the distinct confidence values when there are at most `bins`
                       of them (vote shares), otherwise `bins` equal-count bins; with bins, the identity is approximate.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

P_CLIP = 0.01


def clip(p, lo: float = P_CLIP):
    return np.clip(np.asarray(p, dtype=float), lo, 1 - lo)


def logit(p):
    p = clip(p)
    return np.log(p / (1 - p))


def sigmoid(x):
    return 1 / (1 + np.exp(-np.asarray(x, dtype=float)))


def calibration_gap(c, y) -> float:
    return float(np.mean(c) - np.mean(y))


def brier(c, y) -> float:
    c, y = np.asarray(c, dtype=float), np.asarray(y, dtype=float)
    return float(np.mean((c - y) ** 2))


def log_loss(c, y) -> float:
    c, y = clip(c), np.asarray(y, dtype=float)
    return float(-np.mean(y * np.log(c) + (1 - y) * np.log(1 - c)))


def ece(c, y, bins: int = 10) -> float:
    """Expected calibration error over `bins` equal-count bins (ties in c are split by position)."""
    c, y = np.asarray(c, dtype=float), np.asarray(y, dtype=float)
    order = np.argsort(c, kind="stable")
    parts = np.array_split(order, bins)
    return float(np.mean([abs(c[p].mean() - y[p].mean()) for p in parts if len(p)]))


def auroc(c, y) -> float:
    """Area under the ROC curve of confidence c for outcome y (Mann-Whitney form, ties one half); NaN when y has
    only one class."""
    c, y = np.asarray(c, dtype=float), np.asarray(y, dtype=float)
    pos, neg = c[y == 1], c[y == 0]
    if len(pos) == 0 or len(neg) == 0:
        return float("nan")
    ranks = pd.Series(np.concatenate([pos, neg])).rank(method="average").to_numpy()
    return float((ranks[:len(pos)].sum() - len(pos) * (len(pos) + 1) / 2) / (len(pos) * len(neg)))


def murphy(c, y, bins: int = 10) -> dict:
    """Murphy's decomposition of the Brier score: reliability, resolution and uncertainty (see the docstring)."""
    c, y = np.asarray(c, dtype=float), np.asarray(y, dtype=float)
    values = np.unique(c)
    if len(values) <= bins:
        groups = np.searchsorted(values, c)
    else:
        groups = np.zeros(len(c), dtype=int)
        for k, part in enumerate(np.array_split(np.argsort(c, kind="stable"), bins)):
            groups[part] = k
    base = y.mean()
    reliability = resolution = 0.0
    for g in np.unique(groups):
        m = groups == g
        w = m.mean()
        reliability += w * (c[m].mean() - y[m].mean()) ** 2
        resolution += w * (y[m].mean() - base) ** 2
    return {"reliability": float(reliability), "resolution": float(resolution), "uncertainty": float(base * (1 - base))}


def logistic_fit(X, y, l2: float = 0.0, iters: int = 50) -> np.ndarray:
    """Coefficients of a logistic regression of y on X (X includes any constant column), by Newton steps.
    l2 > 0 adds a ridge penalty (not on the first column), which keeps a fit finite on separable data."""
    X, y = np.asarray(X, dtype=float), np.asarray(y, dtype=float)
    beta = np.zeros(X.shape[1])
    penalty = np.full(X.shape[1], l2)
    penalty[0] = 0.0
    for _ in range(iters):
        p = sigmoid(X @ beta)
        w = p * (1 - p)
        grad = X.T @ (y - p) - penalty * beta
        hess = (X * w[:, None]).T @ X + np.diag(penalty) + 1e-10 * np.eye(X.shape[1])
        step = np.linalg.solve(hess, grad)
        beta += step
        if np.max(np.abs(step)) < 1e-10:
            break
    return beta


def with_constant(features) -> np.ndarray:
    F = np.asarray(features, dtype=float)
    F = F[:, None] if F.ndim == 1 else F
    return np.column_stack([np.ones(len(F)), F])


def fit_correction(features, y, l2: float = 0.0) -> np.ndarray:
    return logistic_fit(with_constant(features), y, l2)


def apply_correction(beta, features) -> np.ndarray:
    return sigmoid(with_constant(features) @ beta)


def cross_fit(features, y, folds, l2: float = 0.0) -> np.ndarray:
    """Out-of-sample corrected confidence: each item's prediction comes from a fit on the items of the
    other folds. `folds` gives each item's fold label."""
    F = np.asarray(features, dtype=float)
    F = F[:, None] if F.ndim == 1 else F
    y, folds = np.asarray(y, dtype=float), np.asarray(folds)
    out = np.full(len(y), np.nan)
    for f in np.unique(folds):
        test = folds == f
        beta = fit_correction(F[~test], y[~test], l2)
        out[test] = apply_correction(beta, F[test])
    return out


def two_folds(n: int, seed: int = 0, strata=None) -> np.ndarray:
    """A fixed 2-fold split of n items (balanced within each stratum when strata are given)."""
    rng = np.random.default_rng(seed)
    folds = np.zeros(n, dtype=int)
    groups = np.zeros(n, dtype=int) if strata is None else np.unique(np.asarray(strata), return_inverse=True)[1]
    for g in np.unique(groups):
        idx = np.flatnonzero(groups == g)
        idx = idx[rng.permutation(len(idx))]
        folds[idx[len(idx) // 2:]] = 1
    return folds


def intercept_slope(c, y) -> tuple[float, float]:
    """Calibration intercept and slope: logistic regression of y on logit(clip(c))."""
    beta = logistic_fit(with_constant(logit(c)), y)
    return float(beta[0]), float(beta[1])


def extremize(forecasts, a: float) -> np.ndarray:
    """sigmoid(a * mean log-odds) over the last axis of `forecasts` (items x forecasters)."""
    F = np.asarray(forecasts, dtype=float)
    return sigmoid(a * logit(F).mean(axis=-1))


def fit_extremizing(forecasts, y) -> float:
    """Maximum-likelihood a: logistic regression of y on the mean log-odds, no intercept."""
    x = logit(np.asarray(forecasts, dtype=float)).mean(axis=-1)
    return float(logistic_fit(x[:, None], y)[0])


def report(c, y) -> dict:
    """Every calibration and discrimination measure of one confidence vector."""
    a, b = intercept_slope(c, y)
    return {"n": len(y), "mean_conf": float(np.mean(c)), "accuracy": float(np.mean(y)), "gap": calibration_gap(c, y),
            "brier": brier(c, y), "log_loss": log_loss(c, y), "ece": ece(c, y), "intercept": a, "slope": b,
            "auroc": auroc(c, y), **murphy(c, y)}
