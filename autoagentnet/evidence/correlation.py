"""How much independent evidence correlated calls carry (step 0.8; plan, "Definitions").

Data layout. A source's grades on n items are a matrix Z with one row per item and one column per call:
Z[i, c] is 1 if call c answered item i correctly and 0 if not; NaN where a call was not made (items may
have different numbers of calls). For forecasts, use the error f - y instead of a grade where noted.

Every pair statistic below is built from the four cells of a 2x2 table of "right / wrong" for a pair of
calls on the same item, averaged first over the call pairs of an item and then over items, so every
item has equal weight:
  P11  both right        P00  both wrong        P10, P01  one right, one wrong
For two different sources s and t, the pairs are (any call of s, any call of t). For one source (s = t),
the pairs are two different calls of it on the same item.

Quantities (plain words first):
  accuracy p(s)           share of a source's calls that are correct (each item weighted equally).
  repeat correlation rho  how much two calls of one source on one item are right or wrong together: 0 for
                          independent calls, 1 for identical ones. pair_stats(Z, Z) gives the pairwise
                          estimator (P11 - p^2) / (p (1 - p)); icc_anova the one-way ANOVA intra-class
                          correlation; rho_betabinom the beta-binomial maximum-likelihood rho (the
                          library's chapter 26, section 10). The three agree closely on balanced data.
  cross correlation phi   the same correlation between a call of s and a call of t on the same item.
  log error odds ratio    log of P00 P11 / (P01 P10): 0 for independent sources. It does not depend on the
                          two accuracies, so it is the primary association measure.
  shared-error ratio SER  P00 / (q_s q_t), q = 1 - p: how often both are wrong relative to chance (1 =
                          independent). It is bounded by 1 / max(q_s, q_t), so it is confounded when
                          accuracies differ; it is reported beside the odds ratio.
  same-wrong-answer rate  among call pairs where both are wrong, the share that give the same wrong answer.
  latent r                phi / sqrt(rho_s rho_t): the correlation of the two sources' per-item chances of
                          being right, with each source's call-to-call noise removed. Needs at least two
                          calls per item from each source.
  n_eff                   K^2 / sum_jk rho_jk over K calls, with rho_jj = 1: how many independent calls the K
                          correlated calls are worth. m calls of one source give m / (1 + (m - 1) rho).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

EPS = 1e-9


def grade_matrix(rows: pd.DataFrame, value: str = "correct", item: str = "item", call: str = "call") -> pd.DataFrame:
    """Long rows (one per call) -> the item x call matrix Z of one source."""
    return rows.pivot_table(index=item, columns=call, values=value, aggfunc="first")


def accuracy(Z) -> float:
    """Mean over items of each item's share of correct calls."""
    Z = np.asarray(Z, dtype=float)
    return float(np.nanmean(np.nanmean(Z, axis=1)))


def _right_counts(Z: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per item: number of calls made (m) and number right (a)."""
    made = ~np.isnan(Z)
    return made.sum(axis=1).astype(float), np.where(made, Z, 0).sum(axis=1)


@dataclass
class PairStats:
    """The 2x2 cells (averaged over call pairs, then items) and the measures built from them."""

    p11: float
    p10: float
    p01: float
    p00: float
    p_s: float
    p_t: float
    n_items: int

    @property
    def phi(self) -> float:
        denom = math.sqrt(max(self.p_s * (1 - self.p_s) * self.p_t * (1 - self.p_t), EPS))
        return (self.p11 - self.p_s * self.p_t) / denom

    @property
    def log_error_or(self) -> float:
        cells = [max(c, EPS) for c in (self.p00, self.p11, self.p01, self.p10)]
        return math.log(cells[0]) + math.log(cells[1]) - math.log(cells[2]) - math.log(cells[3])

    @property
    def shared_error_ratio(self) -> float:
        return self.p00 / max((1 - self.p_s) * (1 - self.p_t), EPS)

    def as_dict(self) -> dict:
        return {"n_items": self.n_items, "p_s": self.p_s, "p_t": self.p_t, "phi": self.phi,
                "log_error_or": self.log_error_or, "shared_error_ratio": self.shared_error_ratio, "p_both_wrong": self.p00}


def pair_cells(Zs: np.ndarray, Zt: np.ndarray | None = None) -> np.ndarray:
    """Per-item cell probabilities, shape (n_items, 4) = (P11, P10, P01, P00). Zt None means pairs of
    different calls of one source (items with fewer than two calls get NaN)."""
    Zs = np.asarray(Zs, dtype=float)
    ms, a_s = _right_counts(Zs)
    if Zt is None:
        pairs = ms * (ms - 1)
        with np.errstate(invalid="ignore", divide="ignore"):
            p11 = a_s * (a_s - 1) / pairs
            p00 = (ms - a_s) * (ms - a_s - 1) / pairs
            p10 = a_s * (ms - a_s) / pairs
        cells = np.column_stack([p11, p10, p10, p00])
        cells[pairs <= 0] = np.nan
        return cells
    Zt = np.asarray(Zt, dtype=float)
    mt, a_t = _right_counts(Zt)
    with np.errstate(invalid="ignore", divide="ignore"):
        rs, rt = a_s / ms, a_t / mt
    cells = np.column_stack([rs * rt, rs * (1 - rt), (1 - rs) * rt, (1 - rs) * (1 - rt)])
    cells[(ms == 0) | (mt == 0)] = np.nan
    return cells


def stats_from_cells(cells: np.ndarray) -> PairStats:
    keep = ~np.isnan(cells).any(axis=1)
    c = cells[keep].mean(axis=0)
    return PairStats(p11=c[0], p10=c[1], p01=c[2], p00=c[3], p_s=c[0] + c[1], p_t=c[0] + c[2], n_items=int(keep.sum()))


def pair_stats(Zs, Zt=None) -> PairStats:
    """Pair measures between sources s and t, or between different calls of s when Zt is None."""
    return stats_from_cells(pair_cells(Zs, Zt))


def rho_pairwise(Z) -> float:
    """Repeat correlation of one source: phi between two different calls on the same item."""
    return pair_stats(Z).phi


def icc_anova(Z) -> float:
    """One-way ANOVA intra-class correlation, unequal calls per item allowed:
    (MSB - MSW) / (MSB + (k0 - 1) MSW), with k0 = (N - sum m_i^2 / N) / (n - 1)."""
    Z = np.asarray(Z, dtype=float)
    m, a = _right_counts(Z)
    keep = m > 0
    m, a = m[keep], a[keep]
    n, N = len(m), m.sum()
    grand = a.sum() / N
    msb = (m * (a / m - grand) ** 2).sum() / (n - 1)
    msw = (a - a ** 2 / m).sum() / (N - n)
    k0 = (N - (m ** 2).sum() / N) / (n - 1)
    return float((msb - msw) / (msb + (k0 - 1) * msw))


def rho_betabinom(Z) -> tuple[float, float]:
    """Beta-binomial maximum likelihood: each item has its own chance of a correct call, drawn from a
    beta distribution with mean mu and intra-class correlation rho = 1 / (alpha + beta + 1); the k right
    of m calls is binomial given that chance. Returns (mu, rho)."""
    from scipy.optimize import minimize
    from scipy.stats import betabinom

    m, a = _right_counts(np.asarray(Z, dtype=float))
    keep = m > 0
    m, a = m[keep].astype(int), a[keep].astype(int)

    def nll(theta):
        mu, rho = 1 / (1 + np.exp(-theta[0])), 1 / (1 + np.exp(-theta[1]))
        alpha, beta = mu * (1 - rho) / rho, (1 - mu) * (1 - rho) / rho
        return -betabinom.logpmf(a, m, alpha, beta).sum()

    p0 = min(max(a.sum() / m.sum(), 0.02), 0.98)
    start = np.array([math.log(p0 / (1 - p0)), math.log(0.2 / 0.8)])
    best = minimize(nll, start, method="Nelder-Mead", options={"xatol": 1e-6, "fatol": 1e-8, "maxiter": 2000})
    mu, rho = 1 / (1 + np.exp(-best.x))
    return float(mu), float(rho)


def latent_r(phi: float, rho_s: float, rho_t: float) -> float:
    """phi / sqrt(rho_s rho_t); NaN when a repeat correlation is not positive."""
    return phi / math.sqrt(rho_s * rho_t) if rho_s > 0 and rho_t > 0 else float("nan")


def n_eff(R) -> float:
    """K^2 / sum of all entries of the K x K call correlation matrix R (ones on the diagonal)."""
    R = np.asarray(R, dtype=float)
    return float(R.shape[0] ** 2 / R.sum())


def n_eff_repeat(m: int, rho: float) -> float:
    """m calls of one source: m / (1 + (m - 1) rho)."""
    return m / (1 + (m - 1) * rho)


def panel_correlation(counts: dict[str, int], rho: dict[str, float], phi: dict[tuple[str, str], float]) -> np.ndarray:
    """The call correlation matrix of a panel: counts[s] calls of each source s; two calls of one source
    correlate by rho[s], calls of s and t by phi[(s, t)] (either order)."""
    labels = [s for s in counts for _ in range(counts[s])]
    K = len(labels)
    R = np.eye(K)
    for j in range(K):
        for k in range(K):
            if j == k:
                continue
            s, t = labels[j], labels[k]
            R[j, k] = rho[s] if s == t else phi[(s, t)] if (s, t) in phi else phi[(t, s)]
    return R


def same_wrong_answer_rate(answers_s: pd.DataFrame, correct_s: pd.DataFrame, answers_t: pd.DataFrame | None,
                           correct_t: pd.DataFrame | None, same) -> float:
    """Among call pairs on the same item where both calls are wrong, the share giving the same wrong answer.
    Inputs are item x call matrices aligned on items; `same(a, b)` says whether two answers match (the
    task's grader). Unparsed answers (None or NaN) never match. Pairs: any call of s with any call of t, or
    two different calls of s when answers_t is None."""
    both_wrong = same_answer = 0
    within = answers_t is None
    for item in answers_s.index:
        a_s, c_s = answers_s.loc[item].tolist(), correct_s.loc[item].tolist()
        a_t, c_t = (a_s, c_s) if within else (answers_t.loc[item].tolist(), correct_t.loc[item].tolist())
        for j in range(len(a_s)):
            for k in range(len(a_t)):
                if within and k <= j:
                    continue
                if c_s[j] == 0 and c_t[k] == 0:
                    both_wrong += 1
                    x, y = a_s[j], a_t[k]
                    ok = isinstance(x, str) and isinstance(y, str)
                    same_answer += int(ok and same(x, y))
    return same_answer / both_wrong if both_wrong else float("nan")


def mean_pairwise(G) -> dict:
    """The average over every pair of distinct columns of G (items x sources, one call each, no NaN) of
    each pair's phi, log error odds ratio and shared-error ratio. This is the measure for "two different
    sources", such as two of the pilot's 27 team designs: each pair is a 2x2 table, and the pairs are
    averaged with equal weight."""
    G = np.asarray(G, dtype=float)
    n, k = G.shape
    W = 1 - G
    p = G.mean(axis=0)
    p11 = G.T @ G / n
    p00 = W.T @ W / n
    p10 = G.T @ W / n
    upper = np.triu_indices(k, 1)
    with np.errstate(invalid="ignore", divide="ignore"):
        phi = (p11 - np.outer(p, p)) / np.sqrt(np.maximum(np.outer(p * (1 - p), p * (1 - p)), EPS))
        ser = p00 / np.maximum(np.outer(1 - p, 1 - p), EPS)
        lor = (np.log(np.maximum(p00, EPS)) + np.log(np.maximum(p11, EPS))
               - np.log(np.maximum(p10, EPS)) - np.log(np.maximum(p10.T, EPS)))
    return {"phi": float(phi[upper].mean()), "shared_error_ratio": float(ser[upper].mean()),
            "log_error_or": float(lor[upper].mean()), "pairs": len(upper[0])}
