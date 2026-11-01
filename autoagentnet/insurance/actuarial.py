"""Rate-making from episode tables: frequency with credibility, clustering, severity, premium.

Terms (defined before use):
  cell           one rating class: a (model, context) pair, e.g. (gpt-4.1, retail)
  n, k           episodes in the cell, and how many of them had the event (a default, or a
                 commission default)
  raw rate       k / n
  ICC (rho)      intra-class correlation of the event among trials of the same task. 0 means
                 every trial is an independent coin flip; 1 means a task either always fails or
                 never does. Estimated from tasks with m trials each by the beta-binomial method
                 of moments: rho = (m * var(k_task / m) / (p (1 - p)) - 1) / (m - 1), clipped to [0, 1]
  design effect  1 + (m - 1) rho: how much clustering inflates the variance of the raw rate
  n_eff          n / design effect: the number of independent episodes the cell is worth
  credibility Z  Buhlmann weight on the cell's own rate: Z = n_eff / (n_eff + K), where K is the
                 ratio of within-cell noise to between-cell spread in the same context. Cells with
                 little data are pulled toward the context's average rate
  credible rate  Z * raw rate + (1 - Z) * context rate
  pass^k         probability that k independent trials of the same task all succeed (tau-bench);
                 estimated per task without bias as C(s, k) / C(m, k), s = successes of m trials
  pure premium   expected loss per episode: sum over default kinds of
                 P(kind) * expected dollars lost per default of that kind
  loaded premium pure premium plus a risk load (cost of the capital the insurer holds against the
                 tail) and expenses, as a share of premium
"""

from __future__ import annotations

from dataclasses import dataclass
from math import comb

import numpy as np
import pandas as pd


def task_counts(episodes: pd.DataFrame, event: str = "default", cell: list[str] | None = None) -> pd.DataFrame:
    """Per task: trials m and events k, inside each cell."""
    cell = cell or ["model", "context"]
    return episodes.groupby(cell + ["task_id"], as_index=False).agg(m=(event, "size"), k=(event, "sum"))


def icc_beta_binomial(counts: pd.DataFrame) -> float:
    """Method-of-moments ICC from per-task (m, k). Uses the modal trial count m."""
    if counts.empty:
        return float("nan")
    m = int(counts["m"].mode().iloc[0])
    c = counts[counts["m"].eq(m)]
    if m < 2 or len(c) < 2:
        return float("nan")
    share = c["k"] / m
    p = share.mean()
    if p <= 0 or p >= 1:
        return 0.0
    rho = (m * share.var(ddof=1) / (p * (1 - p)) - 1) / (m - 1)
    return float(np.clip(rho, 0.0, 1.0))


def cluster_bootstrap_ci(episodes: pd.DataFrame, event: str, n_boot: int = 2000, seed: int = 0) -> tuple[float, float]:
    """95% interval for the event rate, resampling whole tasks (trials of one task move together)."""
    per_task = episodes.groupby("task_id")[event].agg(["sum", "size"])
    if len(per_task) < 2:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(per_task), size=(n_boot, len(per_task)))
    k = per_task["sum"].to_numpy()[idx].sum(axis=1)
    n = per_task["size"].to_numpy()[idx].sum(axis=1)
    rates = k / n
    return (float(np.percentile(rates, 2.5)), float(np.percentile(rates, 97.5)))


def pass_hat_k(episodes: pd.DataFrame, k: int, cell: list[str] | None = None) -> pd.DataFrame:
    """pass^k per cell: the mean over tasks of C(successes, k) / C(trials, k)."""
    cell = cell or ["model", "context"]
    c = task_counts(episodes, "default", cell)
    c = c[c["m"] >= k].copy()
    c["successes"] = c["m"] - c["k"]
    c["pass_k"] = [comb(int(s), k) / comb(int(m), k) for s, m in zip(c["successes"], c["m"])]
    out = c.groupby(cell, as_index=False)["pass_k"].mean()
    out["k"] = k
    return out


def frequency_table(episodes: pd.DataFrame, event: str = "default", cell: list[str] | None = None,
                    pool: str = "context", n_boot: int = 2000) -> pd.DataFrame:
    """Credibility-weighted event rates per cell.

    The complement of credibility (where a thin cell borrows from) is the pooled rate of its
    `pool` group (by default every model in the same context).
    """
    cell = cell or ["model", "context"]
    rows = []
    for key, g in episodes.groupby(cell):
        key = key if isinstance(key, tuple) else (key,)
        counts = task_counts(g, event, cell)
        rho = icc_beta_binomial(counts)
        m = int(counts["m"].mode().iloc[0]) if not counts.empty else 1
        deff = 1 + (m - 1) * (0.0 if np.isnan(rho) else rho)
        lo, hi = cluster_bootstrap_ci(g, event, n_boot=n_boot)
        row = dict(zip(cell, key))
        row.update({"n": len(g), "tasks": g["task_id"].nunique(), "k": int(g[event].sum()),
                    "raw_rate": float(g[event].mean()), "ci_lo": lo, "ci_hi": hi, "icc": rho,
                    "design_effect": deff, "n_eff": len(g) / deff})
        rows.append(row)
    t = pd.DataFrame(rows)
    if t.empty:
        return t
    # Buhlmann K per pool group: expected process variance / variance of hypothetical means.
    pooled = []
    for _, g in t.groupby(pool):
        p_pool = (g["k"].sum()) / g["n"].sum()
        epv = p_pool * (1 - p_pool)
        between = np.average((g["raw_rate"] - p_pool) ** 2, weights=g["n_eff"])
        within = np.average(g["raw_rate"] * (1 - g["raw_rate"]) / g["n_eff"], weights=g["n_eff"])
        vhm = max(between - within, 1e-6)
        g = g.copy()
        g["pool_rate"] = p_pool
        g["K"] = epv / vhm
        g["Z"] = g["n_eff"] / (g["n_eff"] + g["K"])
        g["credible_rate"] = g["Z"] * g["raw_rate"] + (1 - g["Z"]) * g["pool_rate"]
        pooled.append(g)
    return pd.concat(pooled).sort_values(cell).reset_index(drop=True)


def severity_table(episodes: pd.DataFrame, group: list[str] | None = None) -> pd.DataFrame:
    """Exposure among commission defaults: how often there is money at stake, and how much."""
    group = group or ["context"]
    c = episodes[episodes["kind"].eq("commission")]
    out = c.groupby(group).agg(
        commissions=("exposure_usd", "size"),
        share_with_money=("exposure_usd", lambda x: float((x > 0).mean())),
        mean_exposure=("exposure_usd", "mean"),
        median_exposure=("exposure_usd", "median"),
        p95_exposure=("exposure_usd", lambda x: float(np.percentile(x, 95))),
        max_exposure=("exposure_usd", "max"),
    ).reset_index()
    return out


@dataclass
class LossAssumptions:
    """Underwriting assumptions that no benchmark can measure. Every one is a stated input.

    lgd                  loss given default for commissions: share of the exposure the principal
                         loses after reversals, chargebacks and recoveries
    commission_floor_usd remediation cost of a commission default with no dollar exposure (an
                         address changed, a line resumed): staff time, goodwill credit
    omission_usd         cost of an omission default (the customer has to come back; a human
                         agent finishes the job)
    communication_usd    cost of telling the customer something wrong with the state correct
    expense_ratio        insurer expenses (acquisition, admin, claims handling) as a share of
                         the gross premium
    cost_of_capital      annual return the insurer's capital providers require on capital
                         held against the tail
    """
    lgd: float = 0.25
    commission_floor_usd: float = 25.0
    omission_usd: float = 12.0
    communication_usd: float = 8.0
    expense_ratio: float = 0.25
    cost_of_capital: float = 0.10


def expected_loss_per_default(severity: pd.DataFrame, assumptions: LossAssumptions) -> pd.DataFrame:
    """Dollars lost per default, by context and kind."""
    rows = []
    for _, s in severity.iterrows():
        money = assumptions.lgd * s["mean_exposure"]
        floor = (1 - s["share_with_money"]) * assumptions.commission_floor_usd
        rows.append({"context": s["context"], "kind": "commission", "loss_usd": money + floor})
    for ctx in severity["context"]:
        rows.append({"context": ctx, "kind": "omission", "loss_usd": assumptions.omission_usd})
        rows.append({"context": ctx, "kind": "communication", "loss_usd": assumptions.communication_usd})
    return pd.DataFrame(rows)


def pure_premium_table(episodes: pd.DataFrame, assumptions: LossAssumptions,
                       n_boot: int = 2000) -> pd.DataFrame:
    """Expected loss per episode and per 1,000 episodes for each (model, context).

    P(kind) comes from frequency_table (credibility-weighted) for each default kind; dollars per
    default come from expected_loss_per_default.
    """
    ep = episodes.copy()
    for kind in ["commission", "omission", "communication"]:
        ep[kind] = ep["kind"].eq(kind).astype(int)
    sev = severity_table(ep)
    per_default = expected_loss_per_default(sev, assumptions)
    out = None
    for kind in ["commission", "omission", "communication"]:
        f = frequency_table(ep, kind, n_boot=n_boot)[["model", "context", "n", "raw_rate", "credible_rate",
                                                       "ci_lo", "ci_hi", "icc"]]
        f = f.rename(columns={"raw_rate": f"p_{kind}", "credible_rate": f"pc_{kind}", "ci_lo": f"lo_{kind}",
                              "ci_hi": f"hi_{kind}", "icc": f"icc_{kind}"})
        loss = per_default[per_default["kind"].eq(kind)][["context", "loss_usd"]].rename(
            columns={"loss_usd": f"loss_{kind}"})
        f = f.merge(loss, on="context", how="left")
        out = f if out is None else out.merge(f.drop(columns=["n"]), on=["model", "context"])
    out["pure_premium"] = sum(out[f"pc_{k}"] * out[f"loss_{k}"] for k in ["commission", "omission", "communication"])
    out["pure_per_1k"] = 1000 * out["pure_premium"]
    return out.sort_values(["context", "pure_premium"]).reset_index(drop=True)


def loaded_premium(expected_loss: float, capital: float, assumptions: LossAssumptions) -> float:
    """Gross premium = (expected loss + cost of capital x capital) / (1 - expense ratio)."""
    return (expected_loss + assumptions.cost_of_capital * capital) / (1 - assumptions.expense_ratio)
