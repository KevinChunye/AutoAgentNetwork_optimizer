"""Intervals and tests that respect the data's structure (step 0.8; plan, "Definitions").

Terms (plain words first):
  cluster            the unit an interval resamples: the item (BBEH, MathArena); the question id
                     (ForecastBench, so all of a question's resolution dates move together); or, as a
                     second ForecastBench view, source x resolution week (stocks and macro series share shocks).
  cluster bootstrap  draw clusters with replacement (within strata, if given, so each stratum keeps its size),
                     take every item of each drawn cluster, recompute the statistic; 2,000 draws, seed 0. The
                     95% interval is the 2.5th to 97.5th percentile of the draws.
  one-sided p-value  the share of bootstrap draws on the wrong side of the test's threshold (for "above 0":
                     the share at or below 0).
  Holm               order a family's p-values from smallest; the k-th smallest (k = 1..m) passes at level
                     alpha / (m - k + 1) if every smaller one passed too. Families: Phase 1 = H1, H4-H8;
                     Phase 2 = H11, H15, H16.
  TOST               equivalence within (low, high): both one-sided tests (above low, below high) pass at alpha;
                     its p-value is the larger of the two.
  GEE cross-check    a binomial generalized estimating equation with an exchangeable working correlation per
                     item (the library's chapter 27, section 8): its estimated correlation is a model-based
                     check on the repeat correlation rho.
"""

from __future__ import annotations

from typing import Callable

import numpy as np
import pandas as pd

N_BOOT = 2000
SEED = 0


def cluster_draws(clusters, n_boot: int = N_BOOT, seed: int = SEED, strata=None) -> list[np.ndarray]:
    """Bootstrap index arrays over items: each draw resamples clusters (within strata) and lists the
    items of every drawn cluster. `clusters` gives each item's cluster label."""
    clusters = pd.Series(np.asarray(clusters)).reset_index(drop=True)
    members = {c: g.index.to_numpy() for c, g in clusters.groupby(clusters, sort=True)}
    labels = np.array(list(members))
    if strata is None:
        groups = {0: labels}
    else:
        stratum_of = pd.Series(np.asarray(strata)).groupby(clusters).first()
        groups = {s: stratum_of.index[stratum_of == s].to_numpy() for s in sorted(stratum_of.unique())}
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        picked = np.concatenate([g[rng.integers(0, len(g), len(g))] for g in groups.values()])
        draws.append(np.concatenate([members[c] for c in picked]))
    return draws


def bootstrap(stat: Callable[[np.ndarray], float], n_items: int, clusters=None, n_boot: int = N_BOOT, seed: int = SEED,
              strata=None) -> dict:
    """The statistic on all items, its bootstrap draws and the 95% percentile interval. `stat` takes an
    array of item indices (with repeats) and returns a number. Items are their own clusters by default."""
    clusters = np.arange(n_items) if clusters is None else clusters
    draws = np.array([stat(idx) for idx in cluster_draws(clusters, n_boot, seed, strata)], dtype=float)
    finite = draws[np.isfinite(draws)]
    return {"estimate": float(stat(np.arange(n_items))), "lo": float(np.percentile(finite, 2.5)),
            "hi": float(np.percentile(finite, 97.5)), "draws": draws}


def p_above(draws, threshold: float = 0.0) -> float:
    """One-sided p-value for "above threshold": the share of draws at or below it."""
    draws = np.asarray(draws, dtype=float)
    return float(np.mean(draws[np.isfinite(draws)] <= threshold))


def p_below(draws, threshold: float = 0.0) -> float:
    draws = np.asarray(draws, dtype=float)
    return float(np.mean(draws[np.isfinite(draws)] >= threshold))


def tost_p(draws, low: float, high: float) -> float:
    """Equivalence p-value: the larger of p(above low) and p(below high)."""
    return max(p_above(draws, low), p_below(draws, high))


def holm(pvalues: dict[str, float], alpha: float = 0.05) -> pd.DataFrame:
    """Holm's step-down test within one family: per test its p-value, its threshold and pass or fail."""
    table = pd.DataFrame({"test": list(pvalues), "p": list(pvalues.values())}).sort_values(["p", "test"])
    m = len(table)
    table["threshold"] = [alpha / (m - k) for k in range(m)]
    passed, still = [], True
    for p, t in zip(table["p"], table["threshold"]):
        still = still and p <= t
        passed.append(still)
    table["passes"] = passed
    return table.reset_index(drop=True)


def week_cluster(source, resolution_date) -> np.ndarray:
    """ForecastBench's second cluster: source x ISO resolution week, e.g. "yfinance:2026-W29"."""
    dates = pd.to_datetime(pd.Series(resolution_date))
    iso = dates.dt.isocalendar()
    return (pd.Series(source).astype(str).to_numpy() + ":" + iso["year"].astype(str).to_numpy() + "-W"
            + iso["week"].astype(str).str.zfill(2).to_numpy())


def gee_exchangeable_rho(rows: pd.DataFrame, y: str = "correct", group: str = "item") -> float:
    """Within-item exchangeable correlation from a binomial GEE with an intercept only (statsmodels)."""
    import statsmodels.api as sm

    rows = rows.sort_values(group, kind="stable")
    model = sm.GEE(rows[y].astype(float).to_numpy(), np.ones((len(rows), 1)), groups=rows[group].to_numpy(),
                   family=sm.families.Binomial(), cov_struct=sm.cov_struct.Exchangeable())
    model.fit()
    return float(model.cov_struct.dep_params)
