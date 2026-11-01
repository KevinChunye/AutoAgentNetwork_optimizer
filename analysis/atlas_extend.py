"""Atlas extensions P1-P7 (session W1). $0, from the committed response tables in research/v4/atlas/data/ and the
committed anchor read (research/v4/anchor/read.md). Exploratory throughout: public data, chosen after the Atlas and
the anchor were read; nothing here is a test. Writes research/v4/atlas/extend.md and its tables in
research/v4/atlas/tables/extend/.

Plain words first (the factor model's terms are defined in autoagentnet/atlas/factor.py: ability a, difficulty b,
failure beta, all on the log-odds scale).
  call            one answer of one system to one item. A system's "repeats" are its calls on the same item.
  abstention      a call with no parsed answer. In a vote it is a non-vote: it joins no answer class.
  k-vote          the plurality answer of k calls (of one system, or one call each of k systems). Its expected
                  correctness splits a tie evenly among the tied classes (a random tie-break).
  vote gain       k-vote accuracy minus the mean one-call accuracy of the same calls.
  vote rule       the factor model's prediction of a k-vote: per item, each call is right with the model's
                  probability p, abstains with probability (1 - p) z, and otherwise gives the item's common wrong
                  answer with probability r or a wrong answer of its own with probability 1 - r. z is the share of
                  failed calls that abstain; r = sqrt(q), q the share of pairs of wrong answers that coincide, so two
                  wrong calls agree with probability q, as in factor.vote_accuracy (identical for k = 3 when z = 0).
  zero-gain       the predictor "votes add nothing": a k-vote is as accurate as one call (of a random member).
  independence    the predictor that ignores item difficulty: every item is as hard as the average item.
  cross-fitting   items are split into two random halves; each half is predicted from a fit on the other.
  random effects  pooling of per-pair estimates that lets the true effect differ between pairs
                  (DerSimonian-Laird): tau2 is the between-pair variance; the interval is pooled +- 1.96 se.
  coverage        the share of items at least one system of a set gets right (what a perfect selector reaches).
  eta             selection efficiency: (accuracy of the selected answers - best single) / (coverage - best single).
  systematic      var(b) / (var(b) + pi^2/3): the share of latent variation in success that is item difficulty,
  share           shared by every system (L0 fit; A1).

The parts:
  P1  vote rule vs zero-gain on every set with repeats: MathArena (3-4 calls, some sets more), the Phase 1 BBEH panel,
      and the anchor's six 3-call arms (from read.md). Cross-fitted as the anchor's AH3: each item's difficulty is
      inferred from call 0 of the other systems, a system's q and z from its calls on the other half.
  P2  depth moves ability, not the failure pattern: for every public pair of one model at two adjacent reasoning
      settings, the change in ability (delta a) and in failure beta (delta beta), pooled with random effects; and a
      held-out check: the higher setting's per-item accuracy predicted from the lower setting plus one shift, against
      a refit that may also change beta, the higher setting's base rate, and the lower setting unshifted.
  P3  depth vs width at equal dollars (generalises AH2): one call at the higher setting minus the odd-k vote (k = 1 or
      3) of the lower setting whose dollars per item are nearest; MathArena pairs whose lower setting has 3+ calls.
  P4  when label-free selection works: a simulation map (number of systems, accuracy of the others beside one strong
      system, item difficulty spread, wrong-answer coincidence, repeats) of plurality and Dawid-Skene (plain over
      calls; pooled over systems); then MathArena panels drawn with a lone strong system and with many competent ones.
  P5  the price of verification: coverage minus best single, in points and in dollars, for 2-5 system sets; what a
      judge with the anchor's measured eta would realise; and whether any of it beats buying the top system.
  P6  intervals for every systematic share (A1, F17): item bootstrap and system bootstrap, refitting L0 per draw.
  P7  composition where it matters: plurality of mixed panels of weaker MathArena systems (one call each), predicted
      by the factor model (global and per-item wrong-answer coincidence) against independence and zero-gain.
  P8  (added after the related-work check, research/lit/w1_related_work.md) the all-wrong tail on held-out items:
      arXiv 2606.27288 reports that a calibrated one-factor copula underprices the share of items every system fails
      by about 2.5x on open-ended math; here the factor model (one free difficulty per item), the copula and
      independence predict it for held-out systems on held-out items.

Usage: python -m analysis.atlas_extend [--resume]   # --resume reuses research/v4/atlas/tables/extend/*.csv
"""

from __future__ import annotations

import re
import warnings
from functools import lru_cache
from itertools import product
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import atlas_analyses as A
from analysis.pruning_phase3a import md
from autoagentnet.atlas import factor as F

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v4/atlas/extend.md"
TABLES = ROOT / "research/v4/atlas/tables/extend"
DRAWS = ROOT / "runs/w1"  # bootstrap draws of P6 (git-ignored; resumable)
READ = ROOT / "research/v4/anchor/read.md"
SEED, N_BOOT, N_SETS = 0, 200, 200
GAIN_POINTS = 0.03  # P1: cells whose observed vote gain is at least 3 points
Z95 = 1.959964

# P2/P3: one model at two adjacent reasoning settings in one scaffold (low, high). Left out after a look at tokens:
# MathArena's "openai/gpt-52" spends more output tokens than "-high" (its setting is not known), and
# gemini-flash-thinking-2.0 is a different checkpoint from gemini-flash-2.0.
DEPTH_PAIRS = [
    ("swebench_verified", "gpt-5.2", "20251211_mini-v1.17.2_gpt-5.2-2025-12-11",
     "20251211_mini-v1.17.2_gpt-5.2-2025-12-11-high"),
    ("matharena", "gpt-5.2", "openai/gpt-52-low", "openai/gpt-52-high"),
    ("matharena", "o3-mini", "openai/o3-mini--low", "openai/o3-mini--medium"),
    ("matharena", "o3-mini", "openai/o3-mini--medium", "openai/o3-mini"),
    ("matharena", "o4-mini", "openai/o4-mini--low", "openai/o4-mini--medium"),
    ("matharena", "o4-mini", "openai/o4-mini--medium", "openai/o4-mini--high"),
    ("matharena", "gpt-5-nano", "openai/gpt-5-nano-low", "openai/gpt-5-nano"),
    ("matharena", "grok-3-mini", "xai/grok-3-mini-low", "xai/grok-3-mini-high"),
    ("matharena", "gemini-3.1-pro", "gemini/gemini-31-pro-low", "gemini/gemini-31-pro-medium"),
    ("matharena", "gemini-3.1-pro", "gemini/gemini-31-pro-medium", "gemini/gemini-31-pro"),
    ("matharena", "fable 5.1", "anthropic/fable_51_low", "anthropic/fable_51_max"),
    ("matharena", "opus 5.5", "anthropic/opus_55_high", "anthropic/opus_55_max"),
    ("matharena", "gpt-6 astra", "openai/gpt-6-astra-low", "openai/gpt-6-astra"),
    ("livebench", "claude-3.7-sonnet", "claude-3-7-sonnet-20250219-base", "claude-3-7-sonnet-20250219-thinking-25k"),
    ("livebench", "claude-3.7-sonnet", "claude-3-7-sonnet-20250219-thinking-25k",
     "claude-3-7-sonnet-20250219-thinking-64k"),
    ("livebench", "o1", "o1-2024-12-17-low", "o1-2024-12-17-medium"),
    ("livebench", "o1", "o1-2024-12-17-medium", "o1-2024-12-17-high"),
    ("livebench", "o3-mini", "o3-mini-2025-01-31-low", "o3-mini-2025-01-31-medium"),
    ("livebench", "o3-mini", "o3-mini-2025-01-31-medium", "o3-mini-2025-01-31-high"),
]

# P5: the anchor judges' measured eta (research/v4/anchor/read.md, block 2), read by `anchor_judges`
P5_SOURCES = ["swebench_verified", "matharena/aime_2025", "matharena/hmmt_feb_2025", "matharena/hmmt_feb_2026",
              "matharena/arxivmath-0626", "matharena/smt_2025", "livebench"]
P7_SETS = A.MATH_SETS
WEAK = (0.2, 0.7)  # P7: one-call accuracy (on the fit half) of the "weaker" systems


# ---------------------------------------------------------------------------------------------------------
# shared pieces

def plain(table: pd.DataFrame) -> pd.DataFrame:
    """Response-table rows with plain dtypes: answer None when unparsed, correct and cost as floats."""
    t = table[table["correct"].notna()].copy()
    for col in ("item", "system", "benchmark", "family"):
        t[col] = t[col].astype(str)
    t["call"] = t["call"].astype(int)
    t["correct"] = t["correct"].astype(float)
    t["answer"] = t["answer"].astype(object).where(t["answer"].notna(), None)
    t["cost_usd"] = pd.to_numeric(t["cost_usd"], errors="coerce").astype(float)
    return t


@lru_cache(maxsize=None)
def _outcomes(k: int) -> tuple[np.ndarray, np.ndarray]:
    """Every pattern of k calls (0 right, 1 abstain, 2 the item's common wrong answer, 3 a wrong answer of its own)
    and the plurality credit of each pattern (ties split evenly; abstentions join no class)."""
    O = np.array(list(product(range(4), repeat=k)), dtype=int).reshape(-1, k)
    R, W, U = (O == 0).sum(1), (O == 2).sum(1), (O == 3).sum(1)
    top = np.maximum(np.maximum(R, W), (U > 0).astype(int))
    n_top = (R == top).astype(int) + ((W == top) & (W > 0)).astype(int) + U * (top == 1)
    credit = np.where((R > 0) & (R == top), 1.0 / np.maximum(n_top, 1), 0.0)
    return O, credit


def vote_credit(p, z, r) -> np.ndarray:
    """Expected plurality credit of k calls per row: p and z are (n, k) arrays of each call's probability of being
    right and of abstaining; r (scalar or one per row) is the chance that a wrong answer is the row's common wrong
    answer (the vote rule of the docstring)."""
    p = np.atleast_2d(np.asarray(p, dtype=float))
    z = np.broadcast_to(np.asarray(z, dtype=float), p.shape)
    n, k = p.shape
    r = np.broadcast_to(np.asarray(r, dtype=float).reshape(-1, 1) if np.ndim(r) else np.asarray(r, dtype=float),
                        (n, 1))
    w = np.clip(1 - p - z, 0.0, 1.0)
    probs = np.stack([p, z, w * r, w * (1 - r)], axis=2)  # n x k x 4
    O, credit = _outcomes(k)
    combos = np.prod(probs[:, np.arange(k)[None, :], O], axis=2)  # n x patterns
    return combos @ credit


def random_effects(est, se) -> dict:
    """DerSimonian-Laird pooling of estimates with standard errors (pairs with a missing or zero se are left out)."""
    est, se = np.asarray(est, dtype=float), np.asarray(se, dtype=float)
    keep = np.isfinite(est) & np.isfinite(se) & (se > 0)
    est, se = est[keep], se[keep]
    k = len(est)
    if k == 0:
        return {"k": 0, "pooled": np.nan, "se": np.nan, "lo": np.nan, "hi": np.nan, "tau2": np.nan, "Q": np.nan}
    w = 1 / se ** 2
    fixed = float((w * est).sum() / w.sum())
    Q = float((w * (est - fixed) ** 2).sum())
    c = float(w.sum() - (w ** 2).sum() / w.sum())
    tau2 = max(0.0, (Q - (k - 1)) / c) if c > 0 else 0.0
    ws = 1 / (se ** 2 + tau2)
    pooled = float((ws * est).sum() / ws.sum())
    s = float(np.sqrt(1 / ws.sum()))
    return {"k": k, "pooled": pooled, "se": s, "lo": pooled - Z95 * s, "hi": pooled + Z95 * s, "tau2": tau2, "Q": Q}


def grid_loglik(model: dict, systems, y) -> tuple[np.ndarray, np.ndarray]:
    """(difficulty grid, systems x grid log-likelihood of their 0/1 answers y) for one item, abilities frozen; the
    grid spans the fitted difficulties' distribution as in factor.item_posterior."""
    m, sd = float(model["b"].mean()), max(float(model["b"].std()), 1e-3)
    grid = m + sd * F.GRID_SD
    a = model["a"].reindex(systems).to_numpy(float)
    beta = model["beta"].reindex(systems).to_numpy(float)
    logit = a[:, None] - beta[:, None] * grid[None, :]
    y = np.asarray(y, dtype=float)[:, None]
    return grid, y * -np.logaddexp(0, -logit) + (1 - y) * -np.logaddexp(0, logit)


def posterior(loglik_sum: np.ndarray) -> np.ndarray:
    """Posterior weights on the grid from a summed log-likelihood and the normal prior (factor.item_posterior)."""
    lp = loglik_sum - 0.5 * F.GRID_SD ** 2
    w = np.exp(lp - lp.max())
    return w / w.sum()


def halves(items, seed: int = SEED) -> list[tuple[np.ndarray, np.ndarray]]:
    """Two (fit, predicted) splits of the items into random halves, each half predicted once."""
    order = np.random.default_rng(seed).permutation(np.asarray(sorted(items)))
    a, b = np.sort(order[: len(order) // 2]), np.sort(order[len(order) // 2:])
    return [(a, b), (b, a)]


def abstain_share(rows: pd.DataFrame) -> float:
    """Share of a system's failed calls that have no parsed answer."""
    wrong = rows[rows["correct"] == 0]
    return float(wrong["answer"].isna().mean()) if len(wrong) else 0.0


def coincidence(rows: pd.DataFrame, by: str = "system") -> float:
    """Share of pairs of wrong parsed answers on one item that coincide; by="system": pairs within one system's
    repeats; by="item": pairs of different systems' calls (cross-system). 0.5 when there are no pairs."""
    w = rows[(rows["correct"] == 0) & rows["answer"].notna()]
    same = total = 0
    keys = ["item", "system"] if by == "system" else ["item"]
    for _, g in w.groupby(keys):
        counts = g["answer"].value_counts().to_numpy()
        same += int((counts * (counts - 1) // 2).sum())
        total += len(g) * (len(g) - 1) // 2
    return same / total if total else 0.5


def shrunk_coincidence(wrong_answers, prior_q: float, prior_pairs: float = 5.0) -> float:
    """Share of pairs among one item's wrong answers (from different systems) that coincide, shrunk towards prior_q
    with the weight of prior_pairs pairs (an item few systems got wrong stays near the global value)."""
    counts = pd.Series(list(wrong_answers), dtype=object).value_counts().to_numpy()
    n = int(counts.sum())
    return float(((counts * (counts - 1) // 2).sum() + prior_q * prior_pairs) / (n * (n - 1) // 2 + prior_pairs))


def observed_votes(rows: pd.DataFrame, k: int) -> pd.DataFrame:
    """Per (system, item): plurality credit and mean correctness of the first k calls."""
    t = rows[rows["call"] < k].sort_values("call")
    g = t.groupby(["system", "item"])
    return pd.DataFrame({"obs_vote": g.apply(lambda x: A.plurality_right(list(x["answer"]), list(x["correct"]))),
                         "obs_one": g["correct"].mean()}).reset_index()


def boot_cells(rows: pd.DataFrame, cols: list[str], stat, n_boot: int = N_BOOT, seed: int = SEED,
               cell: str = "cell", group: str = "set") -> dict:
    """Item bootstrap within each group (paired across the group's cells): per draw, each cell's mean of `cols`
    over the resampled items, then stat(frame of cell means) -> dict of numbers. Returns the full-sample value and
    the 2.5 / 97.5 percentiles of each number. Resampling adds item noise to every cell mean, which inflates a mean
    absolute error, so the intervals that compare predictors are taken on differences of mean squared errors, where
    that noise adds the same variance to both predictors and cancels."""
    rng = np.random.default_rng(seed)
    mats = []
    for name, g in rows.groupby(group):
        piv = {c: g.pivot_table(index="item", columns=cell, values=c) for c in cols}
        mats.append((name, piv))

    def means(draw):
        parts = []
        for name, piv in mats:
            first = piv[cols[0]]
            idx = np.arange(len(first)) if draw is None else draw[name]
            with warnings.catch_warnings():  # a cell with no item in a draw has no mean (NaN, skipped by the stat)
                warnings.simplefilter("ignore", RuntimeWarning)
                frame = pd.DataFrame({c: np.nanmean(piv[c].to_numpy()[idx], axis=0) for c in cols},
                                     index=first.columns)
            parts.append(frame.assign(**{group: name}))
        return pd.concat(parts).reset_index().rename(columns={"index": cell})

    full = stat(means(None))
    draws = []
    for _ in range(n_boot):
        draw = {name: rng.integers(0, len(piv[cols[0]]), len(piv[cols[0]])) for name, piv in mats}
        draws.append(stat(means(draw)))
    D = pd.DataFrame(draws)
    return {key: (val, float(np.nanpercentile(D[key], 2.5)), float(np.nanpercentile(D[key], 97.5)))
            for key, val in full.items()}


def read_tables(path: Path = READ) -> list[pd.DataFrame]:
    """Every markdown table of a committed read, in order, as frames of strings."""
    tables, block = [], []
    for line in path.read_text().splitlines() + [""]:
        if line.startswith("|"):
            block.append(line)
            continue
        if len(block) >= 2:
            head = [h.strip() for h in block[0].strip("|").split("|")]
            body = [[c.strip() for c in r.strip("|").split("|")] for r in block[2:]]
            tables.append(pd.DataFrame(body, columns=head))
        block = []
    return tables


def numeric_or_text(col: pd.Series) -> pd.Series:
    """A column as numbers when every non-empty cell parses as one ("nan" included), else unchanged."""
    num = pd.to_numeric(col.replace("", np.nan), errors="coerce")
    return num if num.notna().sum() == (col.replace("", np.nan).dropna() != "nan").sum() else col


def read_table(columns: list[str], path: Path = READ) -> pd.DataFrame:
    """The first table of a read whose header starts with `columns` (numbers converted where they parse)."""
    for t in read_tables(path):
        if list(t.columns[: len(columns)]) == columns:
            return t.apply(numeric_or_text)
    raise KeyError(columns)


# ---------------------------------------------------------------------------------------------------------
# P1: the vote rule against zero-gain

def p1_set(table: pd.DataFrame, name: str, k: int = 3, seed: int = SEED) -> pd.DataFrame:
    """Per (system, predicted item): observed and predicted k-vote and one-call accuracy for the systems with at
    least k calls, cross-fitted over two item halves (docstring, P1)."""
    t = A.pooled(plain(table))
    single = t[t["call"] == 0]
    rep = A.repeats(t, k)
    if rep.empty:
        return pd.DataFrame()
    obs = observed_votes(rep, k).set_index(["system", "item"])
    rows = []
    for fit_items, test_items in halves(single["item"].unique(), seed):
        model = F.fit(single[single["item"].isin(fit_items)], "L1")
        known = set(model["a"].index)
        fit_rep = rep[rep["item"].isin(fit_items)]
        voters = [s for s in rep["system"].unique() if s in known]
        q = {s: coincidence(fit_rep[fit_rep["system"] == s]) for s in voters}
        zs = {s: abstain_share(fit_rep[fit_rep["system"] == s]) for s in voters}
        test_rep = rep[rep["item"].isin(test_items)]
        for item, g in single[single["item"].isin(test_items) & single["system"].isin(known)].groupby("item"):
            systems = g["system"].to_numpy()
            grid, L = grid_loglik(model, systems, g["correct"].to_numpy())
            total = L.sum(axis=0)
            pos = {s: j for j, s in enumerate(systems)}
            for s in test_rep.loc[test_rep["item"] == item, "system"].unique():
                if s not in q:
                    continue
                w = posterior(total - (L[pos[s]] if s in pos else 0.0))
                p = F.sigmoid(model["a"][s] - model["beta"][s] * grid)
                P = np.repeat(p[:, None], k, axis=1)
                v = vote_credit(P, (1 - P) * zs[s], np.sqrt(q[s]))
                o = obs.loc[(s, item)]
                rows.append({"set": name, "cell": f"{name}|{s}", "system": s, "item": item, "k": k, "q": q[s],
                             "z": zs[s], "pred_vote": float(w @ v), "pred_one": float(w @ p),
                             "obs_vote": float(o["obs_vote"]), "obs_one": float(o["obs_one"])})
    return pd.DataFrame(rows)


def p1_stat(cells: pd.DataFrame) -> dict:
    """MAE of level and gain, vote rule and zero-gain, over cells (cell means of one bootstrap draw)."""
    rule_level = (cells["obs_vote"] - cells["pred_vote"]).abs().mean()
    zero_level = (cells["obs_vote"] - cells["pred_one"]).abs().mean()
    obs_gain = cells["obs_vote"] - cells["obs_one"]
    rule_gain = (obs_gain - (cells["pred_vote"] - cells["pred_one"])).abs().mean()
    zero_gain = obs_gain.abs().mean()
    pred_gain = cells["pred_vote"] - cells["pred_one"]
    # squared errors in points^2: item noise in the observed gain adds the same variance to both, so the difference
    # is unbiased for the difference of the predictors' true squared errors
    mse = {"rule": (10_000 * (obs_gain - pred_gain) ** 2).mean(), "zero": (10_000 * obs_gain ** 2).mean()}
    level = {"rule": (10_000 * (cells["obs_vote"] - cells["pred_vote"]) ** 2).mean(),
             "zero": (10_000 * (cells["obs_vote"] - cells["pred_one"]) ** 2).mean()}
    return {"gain MSE, zero-gain minus rule (points^2)": mse["zero"] - mse["rule"], "rule gain MSE (points^2)": mse["rule"],
            "zero-gain gain MSE (points^2)": mse["zero"],
            "level MSE, zero-gain minus rule (points^2)": level["zero"] - level["rule"],
            "rule level MAE": rule_level, "zero-gain level MAE": zero_level,
            "level MAE, zero-gain minus rule": zero_level - rule_level, "rule gain MAE": rule_gain,
            "zero-gain gain MAE": zero_gain, "gain MAE, zero-gain minus rule": zero_gain - rule_gain,
            "mean observed gain": obs_gain.mean(), "mean predicted gain": (cells["pred_vote"] - cells["pred_one"]).mean()}


def p1_rows(tables: dict) -> pd.DataFrame:
    parts = []
    ma = tables["matharena"]
    for bench in sorted(ma["benchmark"].unique()):
        sub = ma[ma["benchmark"] == bench]
        for k in (3, 5):
            parts.append(p1_set(sub, bench, k))
    for k in (3, 5):
        parts.append(p1_set(tables["bbeh_phase1"], "bbeh_phase1", k))
    return pd.concat([p for p in parts if len(p)], ignore_index=True)


def p1_summary(rows: pd.DataFrame) -> pd.DataFrame:
    cells = rows.groupby(["cell", "set", "k"])[["obs_vote", "obs_one", "pred_vote", "pred_one"]].mean().reset_index()
    cells["obs_gain"] = cells["obs_vote"] - cells["obs_one"]
    cells["pred_gain"] = cells["pred_vote"] - cells["pred_one"]
    points = int(100 * GAIN_POINTS)
    # cells picked on the observed gain favour the vote rule by construction (zero-gain is wrong there by at least
    # the cut); cells picked on the predicted gain are the fair check
    scopes = {"all cells": lambda c: c["k"] == c["k"], f"observed gain >= {points} points": lambda c: c["obs_gain"] >= GAIN_POINTS,
              f"predicted gain >= {points} points": lambda c: c["pred_gain"] >= GAIN_POINTS}
    out = []
    for k in sorted(rows["k"].unique()):
        for scope, pick in scopes.items():
            chosen = cells[(cells["k"] == k) & pick(cells)]
            sub = rows[rows["cell"].isin(chosen["cell"]) & (rows["k"] == k)]
            if sub.empty:
                continue
            b = boot_cells(sub, ["obs_vote", "obs_one", "pred_vote", "pred_one"], p1_stat)
            row = {"k": k, "scope": scope, "cells": len(chosen), "sets": chosen["set"].nunique()}
            for key, (v, lo, hi) in b.items():
                row[key], row[f"{key} lo"], row[f"{key} hi"] = v, lo, hi
            pred_gain = chosen["pred_vote"] - chosen["pred_one"]
            row["corr(predicted, observed gain)"] = float(np.corrcoef(pred_gain, chosen["obs_gain"])[0, 1]) \
                if len(chosen) > 2 else np.nan
            out.append(row)
    return pd.DataFrame(out)


def p1_anchor() -> pd.DataFrame:
    """The anchor's six 3-call arms from read.md (AH3 table): the vote rule's errors beside zero-gain's."""
    t = read_table(["arm", "q", "predicted", "observed", "predicted_gain"])
    return pd.DataFrame({"arm": t["arm"], "observed_one": t["observed_one"], "observed": t["observed"],
                         "observed_gain": t["observed_gain"], "rule_predicted": t["predicted"],
                         "rule_predicted_gain": t["predicted_gain"], "zero_gain_predicted": t["predicted_one"],
                         "rule_level_error": t["observed"] - t["predicted"],
                         "zero_gain_level_error": t["observed"] - t["predicted_one"],
                         "rule_gain_error": t["observed_gain"] - t["predicted_gain"],
                         "zero_gain_gain_error": t["observed_gain"]})


# ---------------------------------------------------------------------------------------------------------
# P2: depth as a shift along the difficulty axis

def fit_ab(b, y, l2: float = 0.1) -> tuple[float, float]:
    """(a, beta) of one system from 0/1 rows y (one per call) on items with frozen difficulties b; the ridge pulls a
    towards 0 and beta towards 1 (the average system)."""
    b = np.asarray(b, dtype=float)
    theta = F._newton_1d_groups(np.column_stack([np.ones(len(b)), -b]), np.asarray(y, dtype=float), -b,
                                np.zeros(len(b), int), 1, l2)[0]
    return float(theta[0]), float(1 + theta[1])


def fit_shift(base_logit, y, l2: float = 1e-3) -> float:
    """The one shift delta that best fits 0/1 rows y on top of fixed log-odds base_logit."""
    x = np.asarray(base_logit, dtype=float)
    return float(F._newton_1d_groups(np.ones((len(x), 1)), np.asarray(y, dtype=float), x, np.zeros(len(x), int), 1,
                                     l2)[0, 0])


def loss_rows(p, y) -> np.ndarray:
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    y = np.asarray(y, dtype=float)
    return -(y * np.log(p) + (1 - y) * np.log(1 - p))


def p2_pair(low: pd.DataFrame, high: pd.DataFrame, b: pd.Series, seed: int = SEED, splits: int = 5) -> dict:
    """Depth pair on the items both settings answered (every call a row): delta a and delta beta with an item
    bootstrap, and the held-out log loss of four predictors of the higher setting (docstring, P2)."""
    items = np.array(sorted(set(low["item"]) & set(high["item"]) & set(b.index)))
    low, high = low[low["item"].isin(items)], high[high["item"].isin(items)]
    pos = {it: j for j, it in enumerate(items)}
    li, hi = low["item"].map(pos).to_numpy(), high["item"].map(pos).to_numpy()
    ly, hy = low["correct"].to_numpy(float), high["correct"].to_numpy(float)
    bb = b.reindex(items).to_numpy(float)
    a_l, be_l = fit_ab(bb[li], ly)
    a_h, be_h = fit_ab(bb[hi], hy)
    rng = np.random.default_rng(seed)
    da, dbeta = [], []
    for _ in range(N_BOOT):
        draw = rng.integers(0, len(items), len(items))
        mult = np.bincount(draw, minlength=len(items))
        lr, hr = np.repeat(np.arange(len(li)), mult[li]), np.repeat(np.arange(len(hi)), mult[hi])
        (x0, y0), (x1, y1) = fit_ab(bb[li[lr]], ly[lr]), fit_ab(bb[hi[hr]], hy[hr])
        da.append(x1 - x0)
        dbeta.append(y1 - y0)
    # held out: each item's high calls predicted from a fit on the other half, over `splits` random halvings
    low_logit = a_l - be_l * bb
    k_low = np.bincount(li, weights=ly, minlength=len(items))
    m_low = np.bincount(li, minlength=len(items))
    emp_logit = np.log((k_low + 0.5) / (m_low - k_low + 0.5))
    names = ["low as is", "low + one shift", "refit a and beta", "base rate", "low's own items + one shift"]
    loss = {n: np.zeros(len(items)) for n in names}
    for sp in range(splits):
        for fit_i, test_i in halves(np.arange(len(items)), seed + sp):
            fr, tr = np.isin(hi, fit_i), np.isin(hi, test_i)
            delta = fit_shift(low_logit[hi[fr]], hy[fr])
            delta_emp = fit_shift(emp_logit[hi[fr]], hy[fr])
            a2, be2 = fit_ab(bb[hi[fr]], hy[fr])
            base = np.clip(hy[fr].mean(), 1e-3, 1 - 1e-3)
            preds = {"low as is": F.sigmoid(low_logit[hi[tr]]), "low + one shift": F.sigmoid(low_logit[hi[tr]] + delta),
                     "refit a and beta": F.sigmoid(a2 - be2 * bb[hi[tr]]), "base rate": np.full(tr.sum(), base),
                     "low's own items + one shift": F.sigmoid(emp_logit[hi[tr]] + delta_emp)}
            for n, p in preds.items():
                per_row = loss_rows(p, hy[tr])
                loss[n] += np.bincount(hi[tr], weights=per_row, minlength=len(items)) / splits
    calls_per_item = np.maximum(np.bincount(hi, minlength=len(items)), 1)
    per_item = {n: v / calls_per_item for n, v in loss.items()}  # mean loss per call, per item
    out = {"items": len(items), "low calls": float(m_low.mean()), "high calls": float(calls_per_item.mean()),
           "acc low": float(ly.mean()), "acc high": float(hy.mean()), "a low": a_l, "a high": a_h,
           "delta a": a_h - a_l, "delta a se": float(np.std(da)), "delta a lo": float(np.percentile(da, 2.5)),
           "delta a hi": float(np.percentile(da, 97.5)), "beta low": be_l, "beta high": be_h,
           "delta beta": be_h - be_l, "delta beta se": float(np.std(dbeta)),
           "delta beta lo": float(np.percentile(dbeta, 2.5)), "delta beta hi": float(np.percentile(dbeta, 97.5))}
    for n in names:
        out[f"loss: {n}"] = float(per_item[n].mean())
    for other in ("refit a and beta", "base rate", "low as is", "low's own items + one shift"):
        d = per_item[other] - per_item["low + one shift"]  # positive: the one-shift predictor is better
        draws = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(N_BOOT)]
        out[f"{other} minus shift"] = float(d.mean())
        out[f"{other} minus shift se"] = float(np.std(draws))
    return out


def p2(tables: dict) -> pd.DataFrame:
    singles = {src: A.single(plain(tables[src])) for src in {p[0] for p in DEPTH_PAIRS}}
    full = {src: A.pooled(plain(tables[src])) for src in singles}
    rows = []
    for src, model_name, low, high in DEPTH_PAIRS:
        s = singles[src]
        b = F.fit(s[~s["system"].isin([low, high])], "L1")["b"]  # difficulties from every other system
        t = full[src]
        res = p2_pair(t[t["system"] == low], t[t["system"] == high], b)
        rows.append({"source": src, "model": model_name, "low": low, "high": high, **res})
    return pd.DataFrame(rows)


# pairs left out of P2 and P3 after a look at output tokens, shown for completeness (never pooled): MathArena's
# "openai/gpt-52" spends more output tokens than "-high" (its setting is unknown), and gemini-flash-thinking-2.0 is a
# different checkpoint from gemini-flash-2.0
EXCLUDED_PAIRS = [
    ("matharena", "gpt-5.2 (setting unknown)", "openai/gpt-52-high", "openai/gpt-52"),
    ("matharena", "gemini 2.0 flash (thinking checkpoint)", "gemini/gemini-flash-2.0", "gemini/gemini-flash-thinking-2.0"),
]


def p2_excluded(tables: dict) -> pd.DataFrame:
    s = A.single(plain(tables["matharena"]))
    t = A.pooled(plain(tables["matharena"]))
    rows = []
    for src, model_name, low, high in EXCLUDED_PAIRS:
        b = F.fit(s[~s["system"].isin([low, high])], "L1")["b"]
        rows.append({"source": src, "model": model_name, "low": low, "high": high,
                     **p2_pair(t[t["system"] == low], t[t["system"] == high], b)})
    return pd.DataFrame(rows)


def widest(pairs: pd.DataFrame) -> pd.DataFrame:
    """One pair per (source, model): the adjacent pair with the most items (a sensitivity check: adjacent pairs of
    one model share a setting, so they are not independent)."""
    return pairs.sort_values(["source", "model", "items"], ascending=[True, True, False]).drop_duplicates(
        ["source", "model"])


def p2_pooled(pairs: pd.DataFrame) -> pd.DataFrame:
    out = []
    for scope, frame in (("all adjacent pairs", pairs), ("one pair per model", widest(pairs))):
        for q in ("delta a", "delta beta", "refit a and beta minus shift", "base rate minus shift",
                  "low as is minus shift", "low's own items + one shift minus shift"):
            out.append({"scope": scope, "quantity": q, **random_effects(frame[q], frame[f"{q} se"])})
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------------------------------------
# P3: one deeper call against the nearest-dollar vote of the shallower setting

def p3(tables: dict) -> pd.DataFrame:
    t = A.pooled(plain(tables["matharena"]))
    rows = []
    rng = np.random.default_rng(SEED)
    for src, model_name, low, high in DEPTH_PAIRS:
        if src != "matharena":
            continue
        lo3 = A.repeats(t[t["system"] == low], 3)
        hi_rows = t[(t["system"] == high) & t["item"].isin(lo3["item"])]
        items = np.array(sorted(set(lo3["item"]) & set(hi_rows["item"])))
        lo3 = lo3[lo3["item"].isin(items)]
        hi_rows = hi_rows[hi_rows["item"].isin(items)]
        priced = min((lo3["cost_usd"] > 0).mean() if len(lo3) else 0, (hi_rows["cost_usd"] > 0).mean() if len(hi_rows) else 0)
        if len(items) < 10 or priced < 0.5:
            rows.append({"model": model_name, "low": low, "high": high, "items": len(items),
                         "note": "lower setting has under 3 calls, or under half the calls are priced"})
            continue
        # dollars per call: the mean over priced calls (MathArena books 0 where the price is unknown)
        per_call = {name: float(r.loc[r["cost_usd"] > 0, "cost_usd"].mean()) for name, r in (("low", lo3), ("high", hi_rows))}
        deep = hi_rows.groupby("item")["correct"].mean().reindex(items).to_numpy()
        deep_usd = per_call["high"]
        votes = {k: observed_votes(lo3, k).set_index("item")["obs_vote"].reindex(items).to_numpy() for k in (1, 3)}
        usd = {k: k * per_call["low"] for k in (1, 3)}
        k = min((1, 3), key=lambda kk: abs(usd[kk] - deep_usd))
        row = {"model": model_name, "low": low, "high": high, "items": len(items), "nearest k": k,
               "deep acc": float(deep.mean()), "deep usd": deep_usd, "wide acc": float(votes[k].mean()),
               "wide usd": usd[k], "deep / wide dollars": deep_usd / usd[k], "low one-call acc": float(votes[1].mean()),
               "low 3-vote acc": float(votes[3].mean()), "low 3-vote usd": usd[3]}
        for label, wide in (("difference", votes[k]), ("difference vs 3-vote", votes[3])):
            d = deep - wide
            draws = [d[rng.integers(0, len(d), len(d))].mean() for _ in range(N_BOOT)]
            row[label], row[f"{label} se"] = float(d.mean()), float(np.std(draws))
            row[f"{label} lo"], row[f"{label} hi"] = float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))
        rows.append(row)
    return pd.DataFrame(rows)


NEAR_DOLLARS = 1.5  # P3: pairs whose deeper call costs within this factor of the matched vote


def p3_pooled(pairs: pd.DataFrame) -> pd.DataFrame:
    ok = pairs[pairs["difference"].notna()] if "difference" in pairs else pairs.iloc[:0]
    out = []
    near = ok[(ok["deep / wide dollars"] >= 1 / NEAR_DOLLARS) & (ok["deep / wide dollars"] <= NEAR_DOLLARS)]
    for scope, frame in (("all pairs", ok), (f"dollars within a factor of {NEAR_DOLLARS}", near)):
        for q in ("difference", "difference vs 3-vote"):
            out.append({"scope": scope, "quantity": q, **random_effects(frame[q], frame[f"{q} se"])})
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------------------------------------
# P4: when label-free selection works

def ds_fast(item_idx, source_idx, cand, n_items: int, n_sources: int, pooled: bool = False, labels: int | None = None,
            iters: int = 100, tol: float = 1e-8) -> tuple[np.ndarray, np.ndarray]:
    """The one-coin Dawid-Skene of autoagentnet.evidence.labelfree, vectorised over calls: item_idx, source_idx and
    cand (the call's candidate index on its item in order of first appearance, -1 when unparsed) are arrays with one
    entry per call. pooled=True weighs each call by 1 / (the source's calls on that item), which is
    `dawid_skene_pooled`. labels: the size of the label space (None: the item's observed candidates; L: a wrong call
    picks one of L - 1 labels and the truth may be a label nobody gave), as in labelfree. Returns (accuracy per source,
    chosen candidate per item; -1 for an item with none)."""
    item_idx, source_idx, cand = (np.asarray(x, dtype=int) for x in (item_idx, source_idx, cand))
    K = np.zeros(n_items, int)
    np.maximum.at(K, item_idx, cand + 1)
    L = K if labels is None else np.maximum(int(labels), K)
    # the last column is the "unobserved" candidate: the truth is a label nobody gave (prior weight L - K)
    unobserved = np.where(L > K, np.log(np.maximum(L - K, 1)), -np.inf)
    Kmax = max(int(K.max()), 1)
    if pooled:
        n_is = pd.Series(1, index=pd.MultiIndex.from_arrays([item_idx, source_idx])).groupby(level=[0, 1]).transform(
            "size").to_numpy()
        weight = 1.0 / n_is
    else:
        weight = np.ones(len(cand))
    parsed = cand >= 0
    valid = np.column_stack([np.arange(Kmax)[None, :] < K[:, None], np.isfinite(unobserved) & (K > 0)])
    acc = np.full(n_sources, 0.7)
    post = np.zeros((n_items, Kmax + 1))
    for _ in range(iters):
        wrong = np.log(np.maximum((1 - acc[source_idx]) / np.maximum(L[item_idx] - 1, 1), 1e-12))
        base = np.where(parsed, wrong, np.log(1 - acc[source_idx])) * weight
        logp = np.zeros((n_items, Kmax + 1))
        logp += np.bincount(item_idx, weights=base, minlength=n_items)[:, None]
        logp[:, Kmax] += np.where(np.isfinite(unobserved), unobserved, 0.0)
        np.add.at(logp, (item_idx[parsed], cand[parsed]),
                  ((np.log(acc[source_idx]) - wrong) * weight)[parsed])
        logp = np.where(valid, logp, -np.inf)
        mx = np.max(np.where(valid, logp, -1e300), axis=1, keepdims=True)
        e = np.where(valid, np.exp(logp - mx), 0.0)
        post = e / np.maximum(e.sum(axis=1, keepdims=True), 1e-300)
        right = np.bincount(source_idx[parsed], weights=(post[item_idx[parsed], cand[parsed]] * weight[parsed]),
                            minlength=n_sources)
        total = np.bincount(source_idx, weights=weight, minlength=n_sources)
        new = np.clip(right / np.maximum(total, 1e-12), 0.01, 0.99)
        done = np.max(np.abs(new - acc)) < tol
        acc = new
        if done:
            break
    chosen = np.where(K > 0, np.argmax(np.where(valid[:, :Kmax], post[:, :Kmax], -1.0), axis=1), -1)
    return acc, chosen


def encode_calls(rows: pd.DataFrame) -> dict:
    """Integer codes for ds_fast: items, sources and each call's candidate in order of first appearance on its
    item (rows in their given order, on a 0..n-1 index); `right[(i, c)]` is 1 when candidate c of item i is right."""
    items = pd.Index(pd.unique(rows["item"]))
    sources = pd.Index(sorted(rows["system"].unique()))
    item_idx = items.get_indexer(rows["item"])
    cand = np.full(len(rows), -1)
    right = {}
    for i, (item, g) in enumerate(rows.groupby(item_idx, sort=True)):
        seen = {}
        for pos, a, c in zip(g.index, g["answer"], g["correct"]):
            if not isinstance(a, str):  # unparsed (None or NaN), as in labelfree.candidates
                continue
            if a not in seen:
                seen[a] = len(seen)
            cand[pos] = seen[a]
            right[(item, seen[a])] = max(right.get((item, seen[a]), 0.0), c)
    return {"item_idx": item_idx, "source_idx": sources.get_indexer(rows["system"]), "cand": cand,
            "items": items, "sources": sources, "right": right}


OPEN_LABELS = 100  # a fixed label space for open-ended answers (audit 68's fix; E5's consensus_inversion.md)
LABEL_FREE = [("Dawid-Skene", False, None), ("pooled Dawid-Skene", True, None),
              ("pooled Dawid-Skene, fixed labels", True, OPEN_LABELS)]
POLICIES = ["plurality"] + [name for name, _, _ in LABEL_FREE]


def label_free(rows: pd.DataFrame) -> dict:
    """Accuracy of the answers picked by plurality (ties split) and by each Dawid-Skene variant of LABEL_FREE over
    `rows` (calls of several systems, repeats allowed), the best single system's accuracy and the coverage; with each
    variant's rank of the truly best system (1 = rated best)."""
    rows = rows.reset_index(drop=True)
    e = encode_calls(rows)
    n_i, n_s = len(e["items"]), len(e["sources"])
    truth = rows.groupby("system")["correct"].mean().reindex(e["sources"])
    best = truth.idxmax()
    out = {"best single": float(truth.max()),
           "coverage": float(rows.groupby("item")["correct"].max().mean()),
           "plurality": float(rows.groupby("item").apply(
               lambda x: A.plurality_right(list(x["answer"]), list(x["correct"]))).mean())}
    for name, pooled, labels in LABEL_FREE:
        acc, chosen = ds_fast(e["item_idx"], e["source_idx"], e["cand"], n_i, n_s, pooled=pooled, labels=labels)
        out[name] = float(np.mean([e["right"].get((it, c), 0.0) if c >= 0 else 0.0
                                   for it, c in zip(np.arange(n_i), chosen)]))
        est = pd.Series(acc, index=e["sources"])
        out[f"{name} rank of best"] = int(est.rank(ascending=False, method="min")[best])
    return out


def ability_for(target: float, sd_b: float) -> float:
    """The ability a whose mean accuracy over items with difficulty N(0, sd_b^2) is `target` (bisection)."""
    lo, hi = -15.0, 15.0
    for _ in range(60):
        mid = (lo + hi) / 2
        acc = (F.GH_WEIGHTS * F.sigmoid(mid - sd_b * F.GH_NODES)).sum() / np.sqrt(2 * np.pi)
        lo, hi = (mid, hi) if acc < target else (lo, mid)
    return (lo + hi) / 2


def simulate_panel(n_systems: int, top: float, others: float, sd_b: float, r_self: float, repeats: int,
                   n_items: int, rng, r_shared: float = 0.3) -> pd.DataFrame:
    """One simulated panel: one system at accuracy `top`, the rest at `others`; item difficulty N(0, sd_b^2), success
    sigmoid(a - b) per call (calls independent given the item); a wrong call gives the item's common wrong answer
    with probability r_shared, else its own system's usual wrong answer on that item with probability r_self (what
    makes repeats of one system agree), else an answer of its own. No abstentions."""
    b = rng.normal(0, sd_b, n_items)
    acc = [top] + [others] * (n_systems - 1)
    rows = []
    for s, target in enumerate(acc):
        a = ability_for(target, sd_b)
        for c in range(repeats):
            right = rng.random(n_items) < F.sigmoid(a - b)
            u, v = rng.random(n_items), rng.random(n_items)
            wrong = np.where(u < r_shared, "w", np.where(v < r_self, f"w{s}", [f"x{s}.{c}.{i}" for i in range(n_items)]))
            ans = np.where(right, "right", wrong)
            rows.append(pd.DataFrame({"item": np.arange(n_items).astype(str), "system": f"s{s}", "call": c,
                                      "answer": ans.astype(object), "correct": right.astype(float)}))
    return pd.concat(rows, ignore_index=True)


P4_GRID = {"systems": [3, 5, 9], "others": [0.3, 0.5, 0.7], "sd_b": [0.5, 2.0], "r_self": [0.2, 0.8],
           "repeats": [1, 3]}
P4_TOP, P4_ITEMS, P4_REPS = 0.85, 150, 8


def p4_simulation(seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    rows = []
    for S, others, sd_b, r_self, m in product(*P4_GRID.values()):
        for rep in range(P4_REPS):
            panel = simulate_panel(S, P4_TOP, others, sd_b, r_self, m, P4_ITEMS, rng)
            rows.append({"systems": S, "others": others, "sd_b": sd_b,
                         "systematic share": sd_b ** 2 / (sd_b ** 2 + F.LOGISTIC_VAR), "r_self": r_self,
                         "repeats": m, "rep": rep, **label_free(panel)})
    return pd.DataFrame(rows)


def p4_map(sim: pd.DataFrame) -> pd.DataFrame:
    keys = list(P4_GRID)
    g = sim.groupby(keys)
    out = g[["best single", "coverage"] + POLICIES].mean()
    for name in POLICIES:
        out[f"{name} gain"] = out[name] - out["best single"]
    for name in POLICIES[1:]:  # "inverts": the truly best system is not rated best
        out[f"{name} inverts"] = g[f"{name} rank of best"].apply(lambda x: float((x > 1).mean()))
    return out.reset_index()


P4_PANEL_SETS = ["matharena/aime_2025", "matharena/hmmt_feb_2025", "matharena/smt_2025", "matharena/apex_shortlist",
                 "matharena/brumo_2025", "matharena/cmimc_2025"]


def p4_panels(tables: dict, draws: int = 30, seed: int = SEED) -> pd.DataFrame:
    """MathArena panels with 4 calls per system: a lone strong system (one-call accuracy >= 0.85) with weak ones
    (<= 0.5), and many competent systems (all in 0.6-0.85); every call of every system, or call 0 only."""
    rng = np.random.default_rng(seed)
    rows = []
    ma = tables["matharena"]
    for bench in P4_PANEL_SETS:
        t = plain(ma[ma["benchmark"] == bench])
        rep = A.repeats(t, 4)
        Y = A.complete(F.outcome_matrix(rep))
        rep = rep[rep["item"].isin(Y.index) & rep["system"].isin(Y.columns)]
        acc = rep.groupby("system")["correct"].mean()
        strong, weak = list(acc.index[acc >= 0.85]), list(acc.index[acc <= 0.5])
        competent = list(acc.index[(acc >= 0.6) & (acc <= 0.85)])
        for S in (3, 5):
            for kind in ("lone strong", "many competent"):
                if (kind == "lone strong" and (not strong or len(weak) < S - 1)) or \
                        (kind == "many competent" and len(competent) < S):
                    continue
                for d in range(draws):
                    if kind == "lone strong":
                        members = [rng.choice(strong)] + list(rng.choice(weak, S - 1, replace=False))
                    else:
                        members = list(rng.choice(competent, S, replace=False))
                    panel = rep[rep["system"].isin(members)]
                    best = acc[members].idxmax()
                    for calls in ("all 4 calls", "call 0"):
                        sub = panel if calls == "all 4 calls" else panel[panel["call"] == 0]
                        row = {"set": bench, "kind": kind, "systems": S, "calls": calls, "draw": d,
                               **label_free(sub[["item", "system", "answer", "correct"]])}
                        # matched calls: S systems with one call each against the best system's own S-call vote
                        # (only for S <= 4, the repeats MathArena has)
                        if calls == "call 0" and S <= 4:
                            mine = panel[panel["system"] == best]
                            row["best system's own vote, same calls"] = float(
                                observed_votes(mine, S)["obs_vote"].mean())
                        rows.append(row)
    return pd.DataFrame(rows)


def p4_panels_summary(panels: pd.DataFrame) -> pd.DataFrame:
    g = panels.groupby(["kind", "systems", "calls"])
    cols = ["best single", "coverage"] + POLICIES
    if "best system's own vote, same calls" in panels:
        cols.append("best system's own vote, same calls")
    out = g[cols].mean()
    if "best system's own vote, same calls" in out:
        for name in POLICIES:
            out[f"{name} minus best system's own vote"] = out[name] - out["best system's own vote, same calls"]
    for name in POLICIES:
        out[f"{name} gain"] = out[name] - out["best single"]
    for name in POLICIES[1:]:  # "inverts": the truly best system is not rated best
        out[f"{name} inverts"] = g[f"{name} rank of best"].apply(lambda x: float((x > 1).mean()))
    out["panels"] = g.size()
    return out.reset_index()


# ---------------------------------------------------------------------------------------------------------
# P5: the price of verification

def anchor_judges() -> pd.DataFrame:
    """The anchor judges' eta and accuracy beside the judge model's own one call (read.md, blocks 1 and 2)."""
    judges = read_table(["judge", "items", "n", "judge_accuracy"])
    width = read_table(["items", "arm", "k", "n", "accuracy"])
    own = {"sol_low_judge": "sol_low", "haiku_high_judge": "haiku_high"}
    rows = []
    for r in judges.itertuples():
        arm = width[(width["items"] == r.items) & (width["arm"] == own[r.judge]) & (width["k"] == 1)]
        rows.append({"judge": r.judge, "items": r.items, "n": r.n, "judge accuracy": r.judge_accuracy, "eta": r.eta,
                     "eta lo": r.eta_lo, "eta hi": r.eta_hi, "best pool arm": r.best_single, "coverage": r.coverage,
                     "judge model alone": float(arm["accuracy"].iloc[0]) if len(arm) else np.nan,
                     "judge model alone usd": float(arm["dollars_per_item"].iloc[0]) if len(arm) else np.nan,
                     "judge usd": r.judge_dollars, "pool usd": r.pool_dollars})
    return pd.DataFrame(rows)


def p5_source(Y: pd.DataFrame, cost: pd.Series | None, name: str, etas: dict, rng) -> pd.DataFrame:
    """Random 2-5 system sets (one call each): the room above the best single system (coverage minus best single)
    in points, its price in extra dollars (sum of the set's dollars minus the best member's), what a judge with each
    measured eta would realise, and how often the set beats the benchmark's top system at no more of its dollars."""
    acc = Y.mean()
    tied = acc.index[acc == acc.max()]
    top = cost.reindex(tied).idxmin() if cost is not None else tied[0]  # the cheapest of the most accurate
    rows = []
    for k in range(2, 6):
        for s in F.sample_sets(list(Y.columns), k, N_SETS, rng):
            sub = Y[list(s)]
            best = acc[list(s)].idxmax()
            cov = float((sub.max(axis=1) > 0).mean())
            row = {"source": name, "k": k, "best single": float(acc[best]), "coverage": cov,
                   "room": cov - float(acc[best]), "top system": float(acc[top])}
            if cost is not None:
                row["set usd"] = float(cost[list(s)].sum())
                row["extra usd"] = row["set usd"] - float(cost[best])
                row["top usd"] = float(cost[top])
            for label, e in etas.items():
                row[f"realised at eta {label}"] = row["best single"] + e * row["room"]
            rows.append(row)
    return pd.DataFrame(rows)


def p5(tables: dict) -> pd.DataFrame:
    judges = anchor_judges()
    etas = {f"{r.judge.replace('_judge', '')} {r.items} ({r.eta:.2f})": float(r.eta) for r in judges.itertuples()}
    etas["1 (perfect selector)"] = 1.0
    rng = np.random.default_rng(SEED)
    parts = []
    for name in P5_SOURCES:
        if name == "livebench":
            lb = tables["livebench"]
            for bench in sorted(lb["benchmark"].unique()):
                Y = A.complete(F.outcome_matrix(lb[lb["benchmark"] == bench])).astype(float)
                parts.append(p5_source(Y, None, str(bench), etas, rng))
            continue
        if name == "swebench_verified":
            t = plain(tables[name])
        else:
            ma = tables["matharena"]
            t = plain(ma[ma["benchmark"] == name])
        t0 = t[t["call"] == 0]
        cost = t0[t0["cost_usd"] > 0].groupby("system")["cost_usd"].mean()
        Y = A.complete(F.outcome_matrix(t0[t0["system"].isin(cost.index)])).astype(float)
        parts.append(p5_source(Y, cost.reindex(Y.columns), name, etas, rng))
    return pd.concat(parts, ignore_index=True)


def p5_summary(sets: pd.DataFrame) -> pd.DataFrame:
    g = sets.groupby(["source", "k"])
    out = g[["best single", "coverage", "room", "top system"]].mean()
    if "extra usd" in sets:
        out["extra usd"] = g["extra usd"].mean()
        out["extra usd per point of room"] = g["extra usd"].mean() / (100 * g["room"].mean())
        out["top usd"] = g["top usd"].mean()
        cheap = sets["set usd"] <= sets["top usd"]
        out["sets at or under the top's dollars"] = sets.assign(c=cheap).groupby(["source", "k"])["c"].mean()
    for col in [c for c in sets.columns if c.startswith("realised at eta")]:
        above = sets[col] > sets["top system"]
        out[f"above top, {col[len('realised at '):]}"] = above.groupby([sets["source"], sets["k"]]).mean()
        if "set usd" in sets:
            cheap = above & (sets["set usd"] <= sets["top usd"])
            out[f"above top at its dollars, {col[len('realised at '):]}"] = cheap.groupby(
                [sets["source"], sets["k"]]).mean()
    return out.reset_index()


# ---------------------------------------------------------------------------------------------------------
# P6: intervals for the systematic shares

def resample(t: pd.DataFrame, col: str, draw: np.ndarray, names: np.ndarray) -> pd.DataFrame:
    """Rows of the resampled names of `col` (duplicates renamed so a fit sees them as different items/systems)."""
    picked = names[draw]
    frame = pd.DataFrame({col: picked, "copy": np.arange(len(picked))})
    out = t.merge(frame, on=col)
    out[col] = out[col] + "#" + out["copy"].astype(str)
    return out.drop(columns="copy")


def p6_source(t: pd.DataFrame, name: str, family_of: pd.Series, n_boot: int, seed: int = SEED,
              cache: Path | None = None) -> pd.DataFrame:
    """Systematic shares (L0; and the median L1 share) of one source and its families: full fit, then n_boot item
    draws (items resampled within each family) and n_boot system draws, each refitting L0 and L1. Draws already in
    `cache` are reused (resumable)."""
    done = pd.read_csv(cache) if cache is not None and cache.exists() else pd.DataFrame()
    have = set(zip(done["kind"], done["draw"])) if len(done) else set()
    rng = np.random.default_rng(seed)
    items = np.array(sorted(t["item"].unique()))
    systems = np.array(sorted(t["system"].unique()))
    fam = family_of.reindex(items).to_numpy()

    def shares(frame, fam_of_item) -> dict:
        m0, m1 = F.fit(frame, "L0"), F.fit(frame, "L1")
        out = {"(all) L0": F.systematic_share(m0["b"]),
               "(all) L1 median": float(np.median(m1["beta"] ** 2 / (m1["beta"] ** 2 + F.LOGISTIC_VAR)))}
        b = m0["b"]
        for f, g in pd.Series(fam_of_item).groupby(pd.Series(fam_of_item)):
            if len(g) >= 2:
                out[f"{f} L0"] = F.systematic_share(b.reindex(g.index))
        return out

    rows = []
    jobs = [("full", 0)] + [("item", d) for d in range(n_boot)] + [("system", d) for d in range(n_boot)] + \
        [("half", d) for d in range(2 * N_HALVES)]
    draws = {}
    for kind, d in jobs:  # the draws are fixed by the seed whether or not a job is cached
        if kind == "item":
            draws[(kind, d)] = np.concatenate([rng.choice(np.where(fam == f)[0], (fam == f).sum())
                                               for f in pd.unique(fam)])
        elif kind == "system":
            draws[(kind, d)] = rng.integers(0, len(systems), len(systems))
        elif kind == "half" and d % 2 == 0:  # a random split of the systems into two halves, no system repeated
            order = rng.permutation(len(systems))
            draws[(kind, d)], draws[(kind, d + 1)] = order[: len(order) // 2], order[len(order) // 2:]
    for kind, d in jobs:
        if (kind, d) in have:
            continue
        if kind == "full":
            frame, fam_items = t, pd.Series(fam, index=items)
        elif kind == "item":
            draw = draws[(kind, d)]
            frame = resample(t, "item", draw, items)
            fam_items = pd.Series(fam[draw], index=[f"{it}#{j}" for j, it in enumerate(items[draw])])
        elif kind == "system":
            frame = resample(t, "system", draws[(kind, d)], systems)
            fam_items = pd.Series(fam, index=items)
        else:
            frame = t[t["system"].isin(systems[draws[(kind, d)]])]
            fam_items = pd.Series(fam, index=items)
        res = shares(frame, fam_items)
        new = pd.DataFrame([{"source": name, "kind": kind, "draw": d, "quantity": q, "value": v}
                            for q, v in res.items()])
        rows.append(new)
        if cache is not None:
            cache.parent.mkdir(parents=True, exist_ok=True)
            new.to_csv(cache, mode="a", header=not cache.exists(), index=False)
    every = pd.concat([done] + rows, ignore_index=True) if len(done) or rows else pd.DataFrame()
    return every


N_HALVES = 20  # P6: random splits of the systems into two halves


def p6_summary(draws: pd.DataFrame) -> pd.DataFrame:
    """Per share: the item-bootstrap 95% interval, and the range of the share over the system half-splits (each half
    fitted on its own; no system repeated). Bootstrap draws of systems repeat systems, which raises the share, so
    they are not reported (audit W1-1, item 3)."""
    full = draws[draws["kind"] == "full"].set_index(["source", "quantity"])["value"]
    out = []
    for (src, q), v in full.items():
        row = {"source": src, "quantity": q, "share": v}
        x = draws[(draws["source"] == src) & (draws["quantity"] == q) & (draws["kind"] == "item")]["value"]
        row["item lo"] = float(np.percentile(x, 2.5)) if len(x) else np.nan
        row["item hi"] = float(np.percentile(x, 97.5)) if len(x) else np.nan
        row["item draws"] = len(x)
        x = draws[(draws["source"] == src) & (draws["quantity"] == q) & (draws["kind"] == "half")]["value"]
        row["half-split min"] = float(x.min()) if len(x) else np.nan
        row["half-split max"] = float(x.max()) if len(x) else np.nan
        row["halves"] = len(x)
        out.append(row)
    return pd.DataFrame(out)


def p6_sources(tables: dict) -> dict:
    """(single-call rows, family per item) per source, as in A1, plus the 39 SWE-bench submissions of F17."""
    out = {}
    for src, table in tables.items():
        t = A.single(plain(table))[["item", "system", "family", "correct", "benchmark"]]
        out[src] = (t, t.drop_duplicates("item").set_index("item")["benchmark"])
    sw = plain(tables["swebench_verified"])
    per = pd.read_csv(A.DATA / "swebench_verified_systems.csv").set_index("system")["per_instance"]
    t = A.single(sw[sw["system"].isin(per.index[per])])[["item", "system", "family", "correct", "benchmark"]]
    out["swebench_verified (39 with details)"] = (t, t.drop_duplicates("item").set_index("item")["benchmark"])
    return out


def p6(tables: dict, n_boot: int = N_BOOT) -> pd.DataFrame:
    parts = []
    for name, (t, fam) in p6_sources(tables).items():
        cache = DRAWS / f"p6_{re.sub(r'[^a-z0-9]+', '_', name.lower())}.csv"
        parts.append(p6_source(t, name, fam, n_boot, cache=cache))
    return p6_summary(pd.concat(parts, ignore_index=True))


# ---------------------------------------------------------------------------------------------------------
# P7: mixed panels of weaker systems

def p7_set(table: pd.DataFrame, name: str, seed: int = SEED) -> pd.DataFrame:
    """Per (panel, predicted item): observed plurality credit of k weaker systems (one call each, averaged over the
    calls 0..3 every member has), and the vote rule's predictions (factor model with the set's wrong-answer
    coincidence, and with the item's coincidence among systems outside the panel), independence and zero-gain."""
    t = A.pooled(plain(table))
    single = t[t["call"] == 0]
    rng = np.random.default_rng(seed)
    rows = []
    for half, (fit_items, test_items) in enumerate(halves(single["item"].unique(), seed)):
        fit = single[single["item"].isin(fit_items)]
        model = F.fit(fit, "L1")
        acc_fit = fit.groupby("system")["correct"].mean()
        weak = [s for s in acc_fit.index[(acc_fit >= WEAK[0]) & (acc_fit <= WEAK[1])] if s in model["a"].index]
        q_global = coincidence(fit, by="item")
        z = {s: abstain_share(fit[fit["system"] == s]) for s in weak}
        test = t[t["item"].isin(test_items) & (t["call"] < 4)]
        calls = {(r.item, r.call, r.system): (r.answer, r.correct) for r in test.itertuples()}
        test0 = single[single["item"].isin(test_items) & single["system"].isin(model["a"].index)]
        per_item = {}
        for it, g in test0.groupby("item"):
            systems = g["system"].to_numpy()
            grid, L = grid_loglik(model, systems, g["correct"].to_numpy())
            wrong = g[(g["correct"] == 0) & g["answer"].notna()]
            per_item[it] = (grid, L, {s: j for j, s in enumerate(systems)}, dict(zip(wrong["system"], wrong["answer"])))
        for k in (3, 5):
            if len(weak) < k:
                continue
            for s in F.sample_sets(weak, k, N_SETS, rng):
                members = list(s)
                zz = np.array([z[m] for m in members])[None, :]
                pi = np.array([[acc_fit[m] for m in members]])
                indep = float(vote_credit(pi, (1 - pi) * zz, np.sqrt(q_global))[0])
                for it in test_items:
                    if it not in per_item:
                        continue
                    have = [c for c in range(4) if all((it, c, m) in calls for m in members)]
                    if not have:
                        continue
                    obs = np.mean([A.plurality_right([calls[(it, c, m)][0] for m in members],
                                                     [calls[(it, c, m)][1] for m in members]) for c in have])
                    grid, L, pos, wrong = per_item[it]
                    inside = [pos[m] for m in members if m in pos]
                    w = posterior(L.sum(axis=0) - L[inside].sum(axis=0))
                    P = np.column_stack([F.sigmoid(model["a"][m] - model["beta"][m] * grid) for m in members])
                    Z = (1 - P) * zz
                    q_item = shrunk_coincidence([a for sy, a in wrong.items() if sy not in members], q_global)
                    rows.append({"set": name, "cell": f"{name}|{half}|{'+'.join(members)}", "k": k, "item": it,
                                 "obs_vote": float(obs),
                                 "pred: factor model": float(w @ vote_credit(P, Z, np.sqrt(q_global))),
                                 "pred: factor model, item coincidence": float(w @ vote_credit(P, Z, np.sqrt(q_item))),
                                 "pred: independence": indep, "pred: zero-gain": float((w @ P).mean())})
    return pd.DataFrame(rows)


P7_PREDICTORS = ["factor model", "factor model, item coincidence", "independence", "zero-gain"]


def p7_stat(cells: pd.DataFrame) -> dict:
    out = {f"MAE {n}": (cells["obs_vote"] - cells[f"pred: {n}"]).abs().mean() for n in P7_PREDICTORS}
    out.update({f"bias {n}": (cells[f"pred: {n}"] - cells["obs_vote"]).mean() for n in P7_PREDICTORS})
    for n in ("independence", "zero-gain"):  # positive: the factor model's error is smaller
        out[f"MAE {n} minus factor model"] = out[f"MAE {n}"] - out["MAE factor model"]
        # in points^2; item noise adds the same variance to both squared errors, so the difference is unbiased
        out[f"MSE {n} minus factor model (points^2)"] = 10_000 * (
            ((cells["obs_vote"] - cells[f"pred: {n}"]) ** 2).mean() -
            ((cells["obs_vote"] - cells["pred: factor model"]) ** 2).mean())
    out["mean observed vote"] = cells["obs_vote"].mean()
    out["mean member accuracy (zero-gain)"] = cells["pred: zero-gain"].mean()
    return out


def p7(tables: dict) -> pd.DataFrame:
    ma = tables["matharena"]
    return pd.concat([p7_set(ma[ma["benchmark"] == b], b) for b in P7_SETS], ignore_index=True)


def p7_summary(rows: pd.DataFrame) -> pd.DataFrame:
    """Point estimates over all panels, and how many sets replicate each comparison (the factor model's mean absolute
    error below the other predictor's within the set). Item-bootstrap intervals were dropped after audit W1-1: with
    few test items per set they were far from symmetric around their estimates."""
    cols = ["obs_vote"] + [f"pred: {n}" for n in P7_PREDICTORS]
    out = []
    for k in sorted(rows["k"].unique()):
        sub = rows[rows["k"] == k]
        cells = sub.groupby(["set", "cell"])[cols].mean().reset_index()
        row = {"k": k, "panels": sub["cell"].nunique(), "sets": sub["set"].nunique(), **p7_stat(cells)}
        by_set = cells.groupby("set").apply(lambda g: pd.Series(p7_stat(g)))
        for n in ("zero-gain", "independence"):
            row[f"sets where the factor model beats {n}"] = int((by_set[f"MAE {n}"] > by_set["MAE factor model"]).sum())
        out.append(row)
    return pd.DataFrame(out)


def p7_by_set(rows: pd.DataFrame) -> pd.DataFrame:
    cols = ["obs_vote"] + [f"pred: {n}" for n in P7_PREDICTORS]
    cells = rows.groupby(["k", "set", "cell"])[cols].mean().reset_index()
    return cells.groupby(["k", "set"]).apply(lambda g: pd.Series({"panels": len(g), **p7_stat(g)})).reset_index()


# ---------------------------------------------------------------------------------------------------------
# P8: the all-wrong tail on held-out items (the test 2606.27288 runs on the one-factor copula)

P8_K = (2, 3, 5, 10, 20)


def p8_matrix(Y: pd.DataFrame, fam: dict, name: str, seed: int = SEED) -> pd.DataFrame:
    """Half the systems fit item difficulties (L1); each held-out system's ability and beta are fitted on a random
    half of the items (the calibration half) with the difficulties frozen; on the other half (test items) the share
    of items every member of a k-set of held-out systems gets wrong is compared with predictions that use the same
    information, the calibration half only (audit W1-1, item 1):
      factor model   difficulties fitted on the calibration items; the test items' difficulties are unknown and drawn
                     from the calibration items' distribution;
      copula         the one-factor Gaussian copula, rho fitted to the held-out systems' pairwise both-wrong rate on
                     the calibration half;
      independence   the product of calibration error rates.
    Shown beside them, with more information: the factor model given each test item's difficulty from the fit
    systems' answers on that item, and the share of test items the fit systems all fail (what that information
    alone says). "all" is the whole held-out set."""
    rng = np.random.default_rng(seed)
    systems = list(rng.permutation(Y.columns))
    fit_s, held = systems[: len(systems) // 2], systems[len(systems) // 2:]
    items = list(rng.permutation(Y.index))
    cal, test = items[: len(items) // 2], items[len(items) // 2:]
    # with extra information: test-item difficulties from the fit systems' answers on those very items
    b = F.fit(A.long(Y[fit_s], fam), "L1")["b"]
    P = {}
    for s in held:  # each held-out system's success probability on the test items
        a, beta = fit_ab(b[cal].to_numpy(), Y.loc[cal, s].to_numpy(float))
        P[s] = F.sigmoid(a - beta * b[test].to_numpy())
    P = pd.DataFrame(P, index=test)
    # with the copula's information (calibration items only): difficulties fitted on the calibration items, and the
    # test items' difficulties drawn from their distribution (each calibration item's difficulty one draw)
    b_cal = F.fit(A.long(Y.loc[cal, fit_s], fam), "L1")["b"].reindex(cal).to_numpy()
    Q = {}
    for s in held:
        a, beta = fit_ab(b_cal, Y.loc[cal, s].to_numpy(float))
        Q[s] = F.sigmoid(a - beta * b_cal)  # calibration-difficulty draws x systems
    Q = pd.DataFrame(Q)
    others_all_wrong = float((Y.loc[test, fit_s].max(axis=1) == 0).mean())
    acc_cal = Y.loc[cal, held].mean()
    rho = F.fit_copula_rho(Y.loc[cal, held])
    Yt = Y.loc[test, held].to_numpy(float)
    Pt = P[held].to_numpy()
    col = {s: j for j, s in enumerate(held)}
    rows = []
    for k in [kk for kk in P8_K if kk < len(held)] + [len(held)]:
        sets = [tuple(held)] if k == len(held) else F.sample_sets(held, k, N_SETS, rng)
        idx = [[col[s] for s in st] for st in sets]
        obs = np.column_stack([(Yt[:, j].max(axis=1) == 0) for j in idx]).astype(float)  # test items x sets
        mod = np.column_stack([np.prod(1 - Pt[:, j], axis=1) for j in idx])
        Qt = Q[held].to_numpy()
        pop = np.array([float(np.prod(1 - Qt[:, j], axis=1).mean()) for j in idx])
        cop = np.array([F.copula_all_wrong(acc_cal[list(st)].to_numpy(), rho) for st in sets])
        ind = np.array([float(np.prod(1 - acc_cal[list(st)].to_numpy())) for st in sets])
        draws = [rng.integers(0, len(test), len(test)) for _ in range(N_BOOT)]
        pred = {"factor model": lambda d: pop.mean(), "copula": lambda d: cop.mean(),
                "independence": lambda d: ind.mean(), "factor model, test-item difficulty": lambda d: mod[d].mean()}
        row = {"benchmark": name, "k": "all" if k == len(held) else k, "members": k, "sets": len(sets),
               "test items": len(test), "copula rho": rho, "observed all-wrong": float(obs.mean()),
               "factor model": float(pop.mean()), "copula": float(cop.mean()), "independence": float(ind.mean()),
               "factor model, test-item difficulty": float(mod.mean()),
               "fit systems all wrong on the test items": others_all_wrong}
        every = np.arange(len(test))
        for n, f in pred.items():
            gap = [obs[d].mean() - f(d) for d in draws]  # observed minus predicted, in rate units
            row[f"observed minus {n}"] = float(obs.mean() - f(every))
            row[f"observed minus {n} lo"] = float(np.percentile(gap, 2.5))
            row[f"observed minus {n} hi"] = float(np.percentile(gap, 97.5))
            # the ratio only where the predicted rate is at least 1% (below it the ratio is noise over zero)
            ok = f(every) >= 0.01
            ratios = [obs[d].mean() / f(d) for d in draws if f(d) > 0]
            row[f"observed / {n}"] = float(obs.mean() / f(every)) if ok else np.nan
            row[f"observed / {n} lo"] = float(np.percentile(ratios, 2.5)) if ok and ratios else np.nan
            row[f"observed / {n} hi"] = float(np.percentile(ratios, 97.5)) if ok and ratios else np.nan
        if k == len(held):  # Clopper-Pearson interval of the observed all-wrong rate of the whole set
            from scipy.stats import beta as beta_dist
            x, n = int(obs.sum()), len(test)
            row["all-wrong items"] = x
            row["observed lo (Clopper-Pearson)"] = float(beta_dist.ppf(0.025, x, n - x + 1)) if x > 0 else 0.0
            row["observed hi (Clopper-Pearson)"] = float(beta_dist.ppf(0.975, x + 1, n - x)) if x < n else 1.0
        rows.append(row)
    return pd.DataFrame(rows)


def p8(tables: dict) -> pd.DataFrame:
    mats = A.matrices(tables)
    return pd.concat([p8_matrix(Y.astype(float), fam, name) for name, (Y, fam) in mats.items() if Y.shape[1] >= 8],
                     ignore_index=True)


# ---------------------------------------------------------------------------------------------------------

def section(name: str, fn, resume: bool) -> pd.DataFrame:
    """Compute one table and save it to research/v4/atlas/tables/extend/<name>.csv; with resume, reuse it."""
    path = TABLES / f"{name}.csv"
    if resume and path.exists():
        return pd.read_csv(path)
    TABLES.mkdir(parents=True, exist_ok=True)
    frame = fn()
    frame.to_csv(path, index=False)
    return frame


def pct(x: float, digits: int = 1) -> str:
    """A rate as points (0.123 -> "12.3")."""
    return f"{100 * x:.{digits}f}"


def msed(row, key: str = "gain MSE, zero-gain minus rule (points^2)") -> str:
    """A squared-error difference with its interval, in points^2."""
    return f"{row[key]:.1f} ({row[key + ' lo']:.1f} to {row[key + ' hi']:.1f})"


def pooled_row(frame: pd.DataFrame, scope: str, quantity: str) -> pd.Series:
    return frame[(frame["scope"] == scope) & (frame["quantity"] == quantity)].iloc[0]


def p4_compact(m: pd.DataFrame) -> pd.DataFrame:
    """The simulation map averaged over the number of systems and the repeat agreement r_self (P4)."""
    keys = ["others", "sd_b", "repeats"]
    cols = [f"{n} gain" for n in POLICIES] + [f"{n} inverts" for n in POLICIES[1:]]
    out = m.groupby(keys)[["best single", "coverage"] + cols].mean().reset_index()
    out.insert(2, "systematic share", out["sd_b"] ** 2 / (out["sd_b"] ** 2 + F.LOGISTIC_VAR))
    return out


def report(r: dict) -> str:
    """research/v4/atlas/extend.md from the computed tables (every number below comes from them)."""
    s1, a1 = r["r1s"], r["r1a"]
    k3 = s1[(s1["k"] == 3)].set_index("scope")
    allc, obsc, predc = k3.iloc[0], k3.iloc[1], k3.iloc[2]
    p2p, p3p = r["r2p"], r["r3p"]
    da, db = pooled_row(p2p, "all adjacent pairs", "delta a"), pooled_row(p2p, "all adjacent pairs", "delta beta")
    sl = pooled_row(p2p, "all adjacent pairs", "refit a and beta minus shift")
    br = pooled_row(p2p, "all adjacent pairs", "base rate minus shift")
    own = pooled_row(p2p, "all adjacent pairs", "low's own items + one shift minus shift")
    d3, d3n = pooled_row(p3p, "all pairs", "difference"), pooled_row(p3p, "dollars within a factor of 1.5", "difference")
    s7 = r["r7s"].set_index("k")
    j = r["r5j"].set_index(["judge", "items"])
    sol = j.loc[("sol_low_judge", "bbeh")]
    sw5 = r["r5s"][(r["r5s"]["source"] == "swebench_verified")].set_index("k")
    t8 = r["r8"]
    sw8 = t8[(t8["benchmark"] == "swebench_verified") & (t8["k"].astype(str) == "all")].iloc[0]
    math8 = t8[t8["benchmark"].str.startswith("matharena") & (t8["k"].astype(str) == "5")]
    lone = r["r4ps"][(r["r4ps"]["kind"] == "lone strong") & (r["r4ps"]["calls"] == "call 0")]
    m3 = r["r4ps"][(r["r4ps"]["calls"] == "call 0") & (r["r4ps"]["systems"] == 3)].set_index("kind")
    m3l, m3c = m3.loc["lone strong"], m3.loc["many competent"]
    matched = [f"{name} minus best system's own vote" for name in POLICIES]
    comp = r["r4ps"][(r["r4ps"]["kind"] == "many competent") & (r["r4ps"]["calls"] == "all 4 calls")]
    lines = [
        "# Atlas extensions P1-P8 (session W1)", "",
        "Written by `python -m analysis.atlas_extend` from research/v4/atlas/data/ and the committed anchor read "
        "(research/v4/anchor/read.md); definitions in the script's docstring. **Exploratory throughout**: public data "
        "and analyses chosen after the Atlas and the anchor were read; nothing here is a test, and nothing here changes a "
        "preregistered decision. Intervals are 95% item-bootstrap intervals (200 draws) unless named otherwise. Where "
        "predictors are compared (P1, P7), the interval is on the difference of mean squared errors in points^2: "
        "item noise adds the same variance to both squared errors and cancels, while a mean absolute error is "
        "inflated by it, so absolute errors are reported without intervals. Tables: "
        "research/v4/atlas/tables/extend/.", "",
        "## P1. The vote rule against zero-gain", "",
        f"Every set with repeats: {int(allc['cells'])} (system, set) cells with 3 calls in {int(allc['sets'])} sets "
        f"(23 MathArena sets and the Phase 1 BBEH panel). The vote rule predicts each cell's 3-vote from single-call "
        f"data, cross-fitted as AH3; zero-gain predicts no gain.",
        f"- All cells: the mean absolute vote-gain error is {pct(allc['rule gain MAE'])} points for the vote rule and "
        f"{pct(allc['zero-gain gain MAE'])} for zero-gain; the squared-error difference is "
        f"{msed(allc)} points^2 (positive favours the rule). The "
        f"observed gain averages {pct(allc['mean observed gain'])} points, the predicted "
        f"{pct(allc['mean predicted gain'])}; predicted and observed gains correlate at "
        f"{allc['corr(predicted, observed gain)']:.2f} across cells.",
        f"- Cells where the vote rule predicts a gain of 3 points or more ({int(predc['cells'])} cells; the fair "
        f"check): error {pct(predc['rule gain MAE'])} against {pct(predc['zero-gain gain MAE'])}; squared-error "
        f"difference {msed(predc)} points^2; the rule predicts {pct(predc['mean predicted gain'])} "
        f"and {pct(predc['mean observed gain'])} is observed.",
        f"- The 3-vote level (accuracy, not gain): mean absolute error {pct(allc['rule level MAE'])} points for the "
        f"vote rule against {pct(allc['zero-gain level MAE'])} for zero-gain (one-call prediction); squared-error "
        f"difference {msed(allc, 'level MSE, zero-gain minus rule (points^2)')} points^2. On level the rule is worse: "
        "it adds its overstated gain to a one-call prediction that already carries the model's error.",
        f"- Cells where votes gained 3 points or more ({int(obsc['cells'])} cells; picked on the outcome, which "
        f"favours the rule by construction): error {pct(obsc['rule gain MAE'])} against "
        f"{pct(obsc['zero-gain gain MAE'])}; squared-error difference {msed(obsc)} points^2.",
        f"- The anchor's six 3-call arms (read.md, AH3): mean absolute gain error "
        f"{pct(a1['rule_gain_error'].abs().mean())} points for the rule against "
        f"{pct(a1['zero_gain_gain_error'].abs().mean())} for zero-gain; the largest observed gain is "
        f"{pct(a1['observed_gain'].max())} points.",
        "- Reading: on gains the vote rule beats zero-gain on squared error, mostly through the cells with larger "
        "gains; on absolute error the two are close, the rule overstates gains by about one point on average (two "
        "where it predicts large ones), and on the 3-vote level it is worse than zero-gain. It ranks where votes pay; "
        "it does not yet price them. Votes of two calls cannot gain at all in expectation (a right-wrong split is a "
        "tie), which is why the AH2 2-vote equals one call.", "", md(s1[["k", "scope", "cells", "sets", "rule gain MAE", "zero-gain gain MAE",
                            "gain MSE, zero-gain minus rule (points^2)", "gain MSE, zero-gain minus rule (points^2) lo",
                            "gain MSE, zero-gain minus rule (points^2) hi", "rule level MAE", "zero-gain level MAE",
                            "level MSE, zero-gain minus rule (points^2)", "level MSE, zero-gain minus rule (points^2) lo",
                            "level MSE, zero-gain minus rule (points^2) hi",
                            "mean observed gain", "mean predicted gain", "corr(predicted, observed gain)"]], 4), "",
        "Anchor arms (from read.md):", "", md(a1, 3), "",
        "## P2. Depth moves ability, not the failure pattern", "",
        f"{len(r['r2'])} adjacent pairs of one model at two reasoning settings ({r['r2']['model'].nunique()} models; "
        f"MathArena, LiveBench, SWE-bench Verified). Pooled with random effects:",
        f"- ability rises by {da['pooled']:.2f} logits ({da['lo']:.2f} to {da['hi']:.2f}; between-pair variance "
        f"{da['tau2']:.2f});",
        f"- failure beta changes by {db['pooled']:+.2f} ({db['lo']:.2f} to {db['hi']:.2f}; between-pair variance "
        f"{db['tau2']:.2f});",
        f"- held out, the higher setting's calls are predicted better by the lower setting plus one shift than by a "
        f"refit that may also change beta (log loss per call {sl['pooled']:+.4f}, {sl['lo']:+.4f} to {sl['hi']:+.4f}; "
        f"positive favours the shift), and far better than by the higher setting's base rate ({br['pooled']:+.3f}, "
        f"{br['lo']:+.3f} to {br['hi']:+.3f}): the items a model fails at the higher setting are the items that are "
        f"hard for everyone (the difficulties come from every other system).",
        f"- The lower setting's own item outcomes plus one shift predict no better than the shared difficulty plus one "
        f"shift ({own['pooled']:+.3f}, {own['lo']:+.3f} to {own['hi']:+.3f}; positive favours the shared difficulty): "
        f"the test is of the population difficulty axis, not of the model's own hard items, which its few repeats "
        f"measure poorly.",
        f"- The two pairs left out after a look at tokens (table below; never pooled) change failure beta by "
        f"{r['r2x']['delta beta'].min():+.2f} and {r['r2x']['delta beta'].max():+.2f}.",
        "- One pair per model gives the same reading (table). Adjacent pairs of one model share a setting, so the "
        "all-pairs pooling counts some evidence twice.", "",
        md(r["r2"][["source", "model", "low", "high", "items", "acc low", "acc high", "delta a", "delta a lo",
                    "delta a hi", "delta beta", "delta beta lo", "delta beta hi", "refit a and beta minus shift",
                    "base rate minus shift"]], 3), "", md(p2p, 4), "", "Pairs left out of the pooling:", "",
        md(r["r2x"][["source", "model", "low", "high", "items", "acc low", "acc high", "delta a", "delta a lo",
                     "delta a hi", "delta beta", "delta beta lo", "delta beta hi"]], 3), "",
        "## P3. One deeper call against the nearest-dollar vote (AH2 on public data)", "",
        f"MathArena pairs whose lower setting has 3 or more calls: {int(d3['k'])} pairs. One call at the higher "
        f"setting minus the odd-k vote of the lower setting with the nearest dollars per item (always the 3-vote "
        f"here): {pct(d3['pooled'])} points ({pct(d3['lo'])} to {pct(d3['hi'])}); on the {int(d3n['k'])} pairs whose "
        f"dollars are within a factor of 1.5, {pct(d3n['pooled'])} ({pct(d3n['lo'])} to {pct(d3n['hi'])}). The step "
        "pays least at the top of a model's range (Gemini 3.1 Pro medium to default, Opus 5.5 high to max).", "",
        md(r["r3"][[c for c in ["model", "low", "high", "items", "nearest k", "deep acc", "deep usd", "wide acc",
                                "wide usd", "deep / wide dollars", "difference", "difference lo", "difference hi",
                                "note"] if c in r["r3"]]], 3), "", md(p3p, 4), "",
        "## P4. When label-free selection works", "",
        "Simulation map (one system at 0.85 one-call accuracy beside others at 0.3, 0.5 or 0.7; item difficulty sd "
        "0.5 or 2.0, a systematic share of 0.07 or 0.55; 1 or 3 calls per system; averaged over 3, 5 and 9 systems and "
        "two levels of repeat agreement; 8 panels of 150 items per cell). Gains are over the best single system; "
        "\"inverts\" is the share of panels where the method rates another system above the truly best one.",
        "- With weak companions and one call each, plain and pooled Dawid-Skene (observed-answer label space) invert "
        "and fall far below the strong system; a fixed label space (100 labels) removes the inversion but still loses "
        "to the strong system when difficulty is shared.",
        "- With competent companions and little shared difficulty, every policy gains about 14 points; with a high "
        "systematic share the gain shrinks to about 5.",
        f"- MathArena panels: one strong system (0.85 or more) with weak ones (0.5 or less), one call each: every "
        f"policy loses {pct(-lone['plurality gain'].max())} to {pct(-lone['Dawid-Skene gain'].min())} points to the "
        f"strong system and Dawid-Skene ranks another system first in "
        f"{pct(lone['Dawid-Skene inverts'].min(), 0)}-{pct(lone['Dawid-Skene inverts'].max(), 0)}% of panels; with "
        f"4 calls each, plain Dawid-Skene matches the strong system. Many competent systems (0.6-0.85) with 4 calls: "
        f"every policy gains {pct(comp['plurality gain'].min())}-{pct(comp['Dawid-Skene gain'].max())} points over one "
        "call of the best system, at four times its calls. Among competent systems the \"best\" one is a near tie, "
        "so its rank says little. LiveBench has no answers, so it cannot enter.",
        f"- Matched calls (three systems, one call each, against the best system's own 3-vote): lone strong, every "
        f"policy loses {pct(-m3l[matched].max())} to {pct(-m3l[matched].min())} points; many competent, plurality "
        f"{pct(m3c[matched[0]])}, plain Dawid-Skene {pct(m3c[matched[1]])} points.",
        f"- On MathArena the fixed label space does not remove the inversion: with one call each it ranks another "
        f"system first in {pct(lone['pooled Dawid-Skene, fixed labels inverts'].min(), 0)}-"
        f"{pct(lone['pooled Dawid-Skene, fixed labels inverts'].max(), 0)}% of lone-strong panels, against "
        f"{pct(lone['Dawid-Skene inverts'].min(), 0)}-{pct(lone['Dawid-Skene inverts'].max(), 0)}% for plain "
        "Dawid-Skene, unlike in the simulation.", "", md(p4_compact(r["r4m"]), 3), "", "MathArena panels:", "",
        md(r["r4ps"], 3), "",
        "## P5. The price of verification", "",
        "Random 2-5 system sets, one call each. Room: coverage minus the best member, what a perfect selector adds. "
        "Price: the set's dollars minus the best member's, per point of room. \"Above top at its dollars\": the share "
        "of sets whose selected accuracy (best member + eta x room) beats the benchmark's most accurate system while "
        "costing no more. Judge calls are not priced here, so these shares are upper bounds.",
        f"- SWE-bench Verified: the room grows from {pct(sw5.loc[2, 'room'])} points (pairs) to "
        f"{pct(sw5.loc[5, 'room'])} (5 systems) at ${sw5.loc[2, 'extra usd per point of room']:.3f} to "
        f"${sw5.loc[5, 'extra usd per point of room']:.3f} per point per task; a judge with the anchor's best measured "
        f"eta beats Claude Opus 4.5 (high) at its dollars in at most "
        f"{pct(sw5['above top at its dollars, eta sol_low bbeh (0.70)'].max(), 0)}% of sets, a perfect selector in "
        f"at most {pct(sw5['above top at its dollars, eta 1 (perfect selector)'].max(), 0)}%.",
        "- MathArena: the room is 1 to 4.5 points, because the top systems are near 100% on most sets.",
        f"- The anchor (read.md): the Sol low judge captured eta {sol['eta']:.2f} ({sol['eta lo']:.2f} to "
        f"{sol['eta hi']:.2f}) of the room over cheap pools on BBEH, reaching {pct(sol['judge accuracy'])}%, yet Sol "
        f"low answering alone scored {pct(sol['judge model alone'])}% at ${sol['judge model alone usd']:.4f} per item "
        f"against ${sol['judge usd'] + sol['pool usd']:.4f} for the judge and its pools. The pools covered only "
        f"{pct(sol['coverage'])}% of the items, below Sol alone, so even a perfect selector over them would have lost: "
        "the comparison measures the pools, not the judge's signal. A fair test needs pools whose coverage exceeds "
        "the judge model's own accuracy.", "",
        md(r["r5s"][["source", "k", "best single", "coverage", "room", "extra usd", "extra usd per point of room",
                     "top system", "top usd", "above top at its dollars, eta sol_low bbeh (0.70)",
                     "above top at its dollars, eta 1 (perfect selector)"]], 3), "", "Anchor judges:", "",
        md(r["r5j"], 4), "",
        "## P6. Intervals for the systematic shares", "",
        "L0 share var(b) / (var(b) + pi^2/3) and the median L1 share, refitted per draw. Item draws resample items "
        "within each task family (95% interval). For systems, a bootstrap repeats systems and raises the share, so "
        "the systems are instead split at random into two halves, 20 times, each half fitted on its own; the table "
        "gives the range of the 40 half shares (a half has fewer systems, so the range is wider than an interval for "
        "the full set would be). The anchor's shares (0.65 BBEH, 0.43 math) need the gold files in data/external/ and "
        "wait for E6's fetch script.", "", md(r["r6"], 3), "",
        "## P7. Composition where it matters: mixed panels of weaker systems", "",
        f"Panels of 3 and 5 different MathArena systems with one-call accuracy 0.2-0.7 (one call each; "
        f"{int(s7.loc[3, 'panels'])} and {int(s7.loc[5, 'panels'])} panels in {int(s7.loc[3, 'sets'])} sets), "
        f"cross-fitted. The vote gains {pct(s7.loc[3, 'mean observed vote'] - s7.loc[3, 'mean member accuracy (zero-gain)'])} "
        f"points over the mean member with 3 systems and "
        f"{pct(s7.loc[5, 'mean observed vote'] - s7.loc[5, 'mean member accuracy (zero-gain)'])} with 5.",
        f"- Factor model: error {pct(s7.loc[3, 'MAE factor model'])} and {pct(s7.loc[5, 'MAE factor model'])} points, "
        f"bias {pct(s7.loc[3, 'bias factor model'])} and {pct(s7.loc[5, 'bias factor model'])}.",
        f"- Zero-gain: absolute error larger by {pct(s7.loc[3, 'MAE zero-gain minus factor model'])} and "
        f"{pct(s7.loc[5, 'MAE zero-gain minus factor model'])} points; the factor model is closer in "
        f"{int(s7.loc[3, 'sets where the factor model beats zero-gain'])} of {int(s7.loc[3, 'sets'])} sets (3 systems) "
        f"and {int(s7.loc[5, 'sets where the factor model beats zero-gain'])} of {int(s7.loc[5, 'sets'])} (5).",
        f"- Independence: absolute error larger by {pct(s7.loc[3, 'MAE independence minus factor model'])} and "
        f"{pct(s7.loc[5, 'MAE independence minus factor model'])} points; the factor model is closer in "
        f"{int(s7.loc[3, 'sets where the factor model beats independence'])} and "
        f"{int(s7.loc[5, 'sets where the factor model beats independence'])} sets.",
        "- No intervals: with 15-25 test items per set, item-bootstrap intervals of these errors were far from "
        "symmetric (audit W1-1); the per-set table replaces them.",
        "- The item-level wrong-answer coincidence (from systems outside the panel) changes nothing material.", "",
        md(s7.reset_index(), 4), "", md(r["r7b"], 4), "",
        "## P8. The all-wrong tail on held-out items", "",
        "arXiv 2606.27288 reports that a calibrated one-factor copula underprices the share of items every system "
        "fails by about 2.5x on open-ended math. Here half the systems fit difficulties, held-out systems are fitted "
        "on half the items (calibration), and the tail is scored on the other half (test). The factor model and the "
        "copula get the same information, the calibration items only (audit W1-1, item 1); the factor model given "
        "each test item's difficulty from the other systems' answers on it is shown beside them, with the share of "
        "test items those other systems all fail.",
        f"- SWE-bench Verified, all {int(sw8['members'])} held-out systems: {pct(sw8['observed all-wrong'])}% of test "
        f"tasks are failed by all ({int(sw8['all-wrong items'])} of {int(sw8['test items'])}; Clopper-Pearson "
        f"{pct(sw8['observed lo (Clopper-Pearson)'])} to {pct(sw8['observed hi (Clopper-Pearson)'])}). Same "
        f"information: factor model {pct(sw8['factor model'])}, copula {pct(sw8['copula'])}, independence "
        f"{pct(sw8['independence'], 2)}. More information: factor model with test-item difficulty "
        f"{pct(sw8['factor model, test-item difficulty'])}; the other systems alone fail "
        f"{pct(sw8['fit systems all wrong on the test items'])}%.",
        f"- MathArena, 5-system sets: the factor model underpredicts the tail on "
        f"{int((math8['observed minus factor model lo'] > 0).sum())} of {len(math8)} sets (interval above 0), the "
        f"copula on {int((math8['observed minus copula lo'] > 0).sum())}; the test halves hold "
        f"{int(t8[t8['benchmark'].str.startswith('matharena')]['test items'].min())} to "
        f"{int(t8[t8['benchmark'].str.startswith('matharena')]['test items'].max())} items, so the math tail is "
        "poorly measured.", "",
        md(t8[["benchmark", "k", "members", "test items", "observed all-wrong", "factor model", "copula",
               "independence", "observed minus factor model", "observed minus factor model lo",
               "observed minus factor model hi", "observed minus copula", "observed minus copula lo",
               "observed minus copula hi", "factor model, test-item difficulty",
               "fit systems all wrong on the test items", "all-wrong items"]], 4), "",
    ]
    return "\n".join(lines)


def main(resume: bool = False) -> str:
    tables = A.load()
    r1 = section("p1_rows", lambda: p1_rows(tables), resume)
    r1s = section("p1_summary", lambda: p1_summary(r1), resume)
    r1a = section("p1_anchor", p1_anchor, resume)
    r2 = section("p2_pairs", lambda: p2(tables), resume)
    r2p = section("p2_pooled", lambda: p2_pooled(r2), resume)
    r2x = section("p2_excluded", lambda: p2_excluded(tables), resume)
    r3 = section("p3_pairs", lambda: p3(tables), resume)
    r3p = section("p3_pooled", lambda: p3_pooled(r3), resume)
    r4 = section("p4_simulation", p4_simulation, resume)
    r4m = section("p4_map", lambda: p4_map(r4), resume)
    r4p = section("p4_panels", lambda: p4_panels(tables), resume)
    r4ps = section("p4_panels_summary", lambda: p4_panels_summary(r4p), resume)
    r5j = section("p5_anchor_judges", anchor_judges, resume)
    r5 = section("p5_sets", lambda: p5(tables), resume)
    r5s = section("p5_summary", lambda: p5_summary(r5), resume)
    r6 = section("p6_shares", lambda: p6(tables), resume)
    r7 = section("p7_rows", lambda: p7(tables), resume)
    r7s = section("p7_summary", lambda: p7_summary(r7), resume)
    r7b = section("p7_by_set", lambda: p7_by_set(r7), resume)
    r8 = section("p8_tail", lambda: p8(tables), resume)
    text = report(locals())
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    import sys

    main(resume="--resume" in sys.argv)
