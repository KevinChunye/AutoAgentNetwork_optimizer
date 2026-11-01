"""The T1-T5 estimators and their pre-registered tests (research/v4/testbed/prereg.md).

Terms (plain words first; compose.py defines vote credit and GPU-seconds, checkers.py defines eta):
  cell           one (size, budget) pair; T1 and T2 compare precisions within a cell, T3 budgets within a size.
  error          1 - correct, per sample.
  error correlation  the Pearson correlation, across items, between the error indicators of two samples; "within"
                 averages it over pairs of different samples of one config, "cross" over pairs of a sample of config
                 A and a sample of config B with different sample numbers.
  single         the mean correctness of one sample (the expected accuracy of one call).
  k-vote         compose.expected_vote with k samples of one config; gain(k) = k-vote - single.
  difficulty     of an item, for an analysis at size s: 1 - the mean correctness of every BF16 sample of the OTHER sizes
                 (all budgets). Using other sizes keeps the tercile cut independent of the samples being compared
                 (cutting on the compared samples themselves would make hard items look worse by selection). With one
                 size only (the pilot), every BF16 sample is used and the result is marked in-sample.
  tercile        items ranked by difficulty and cut into thirds: easy, middle, hard (ties broken by item id).
  paired bootstrap  resample items with replacement (B = 2000, seed 0); an item contributes all its cells together,
                 so items shared across cells stay paired. The 95% interval is the 2.5th to 97.5th percentile.
  kernel seconds GPU-seconds a sample would take on real quantized kernels: its output tokens / the real-kernel
                 benchmark's tokens per second for its size and precision (accuracy runs use fake quantization, which
                 runs every precision at BF16 speed, so their measured seconds do not show a W4 kernel's speed-up).
"""

from __future__ import annotations

import itertools

import numpy as np
import pandas as pd

from . import checkers, compose, factor
from .compose import Samples
from .table import configs

B = 2000
TERCILES = ("easy", "middle", "hard")
T4_LEVEL = 0.99
T5_MAX_RATIO = 0.887  # power.py: at most 5 of 100 misspecified draws below it in each null world (5 and 10 classes)


# ------------------------------------------------------------------------------------------------------------
# helpers

def systems_frame(table: pd.DataFrame) -> pd.DataFrame:
    """One row per config: system, family, size_b, precision (method tag), budget, effort."""
    return configs(table).sort_values(["family", "size_b", "precision", "budget"]).reset_index(drop=True)


def system_of(systems: pd.DataFrame, size, precision, budget) -> str | None:
    hit = systems[(systems["size_b"] == size) & (systems["precision"] == precision) & (systems["budget"] == budget)]
    return None if hit.empty else hit["system"].iloc[0]


def difficulty(table: pd.DataFrame, size=None) -> tuple[pd.Series, bool]:
    """(difficulty per item, in_sample). Leave-size-out when other sizes exist."""
    bf = table[(table["precision"] == "bf16") & (table["family"] == "qwen3.5")]
    bf = bf if not bf.empty else table[table["precision"] == "bf16"]
    others = bf[bf["size_b"] != size] if size is not None else bf
    in_sample = others.empty or size is None
    ref = bf if others.empty else others
    return 1 - ref.groupby("item")["correct"].mean().astype(float), in_sample


def terciles(diff: pd.Series) -> pd.Series:
    order = diff.sort_index().sort_values(kind="mergesort")  # stable: ties stay in item-id order
    labels = np.array(TERCILES)[np.minimum((np.arange(len(order)) * 3) // len(order), 2)]
    return pd.Series(labels, index=order.index)


def bootstrap(sums: np.ndarray, counts: np.ndarray | None = None, seed: int = 0, n: int = B) -> tuple[float, float, float]:
    """(estimate, low, high) of sum(sums) / sum(counts) over items, resampling items."""
    counts = np.ones_like(sums) if counts is None else counts
    keep = counts > 0
    sums, counts = sums[keep], counts[keep]
    if len(sums) == 0:
        return float("nan"), float("nan"), float("nan")
    idx = np.random.default_rng(seed).integers(len(sums), size=(n, len(sums)))
    boot = sums[idx].sum(axis=1) / counts[idx].sum(axis=1)
    return float(sums.sum() / counts.sum()), float(np.percentile(boot, 2.5)), float(np.percentile(boot, 97.5))


def pairwise_corr(X: np.ndarray, Y: np.ndarray | None = None) -> float:
    """Mean Pearson correlation across items between columns of X (within, pairs j < j') or between X[:, j] and
    Y[:, j'] with j != j' (cross). Columns with no variance are skipped."""
    k = X.shape[1]
    Z = X if Y is None else np.hstack([X, Y])
    with np.errstate(invalid="ignore", divide="ignore"):
        R = np.corrcoef(Z.T)
    if Y is None:
        a, b = np.triu_indices(k, 1)
        values = R[a, b]
    else:
        block = R[:k, k:]
        values = block[~np.eye(k, Y.shape[1], dtype=bool)]
    return float(np.nanmean(values)) if np.isfinite(values).any() else float("nan")


class Pool:
    """Per-item sums and counts of a difference pooled over cells (for the item bootstrap)."""

    def __init__(self, items: list[str]):
        self.pos = {item: i for i, item in enumerate(items)}
        self.sums = np.zeros(len(items))
        self.counts = np.zeros(len(items))

    def add(self, items: list[str], values: np.ndarray, mask: np.ndarray | None = None) -> None:
        mask = np.ones(len(items), dtype=bool) if mask is None else mask
        rows = np.array([self.pos[i] for i in items])
        np.add.at(self.sums, rows[mask], values[mask])
        np.add.at(self.counts, rows[mask], 1)

    def result(self, seed: int = 0) -> dict:
        est, low, high = bootstrap(self.sums, self.counts, seed)
        return {"estimate": est, "low": low, "high": high, "items": int((self.counts > 0).sum())}


# ------------------------------------------------------------------------------------------------------------
# T1: does quantization error diversify?

def boot_stat(fn, n_items: int, n: int = 1000, seed: int = 0) -> dict:
    """(estimate, low, high) of a statistic fn(rows) of the items at positions `rows`, by item bootstrap."""
    rng = np.random.default_rng(seed)
    values = np.array([fn(rng.integers(n_items, size=n_items)) for _ in range(n)])
    return {"estimate": float(fn(np.arange(n_items))), "low": float(np.nanpercentile(values, 2.5)),
            "high": float(np.nanpercentile(values, 97.5))}


def disattenuated(Ea: np.ndarray, Eb: np.ndarray) -> float:
    """r = cross / sqrt(within_a x within_b): the error correlation of a sample of A and a sample of B, divided by
    what it would be if A's and B's errors came from one shared item-level propensity (the within-config
    correlations measure how reliable each propensity is). r = 1: A and B share everything that makes copies of A
    agree; r < 1: copies of A share an error component that B lacks."""
    wa, wb, x = pairwise_corr(Ea), pairwise_corr(Eb), pairwise_corr(Ea, Eb)
    return x / np.sqrt(wa * wb) if wa > 0 and wb > 0 else float("nan")


def t1(table: pd.DataFrame, s: Samples, low: str = "w4", ref: str = "bf16", k: int | None = None,
       budgets=None, n_boot: int = 1000) -> dict:
    """T1, per cell (size, budget) and pooled over cells. The primary is descriptive: "the W4 deficit survives 6 votes
    on the hard third" (gap_persists). It holds whenever W4 loses accuracy on hard items, whether or not the loss is
    shared by its copies, so it says nothing about the mechanism; the mechanism test (shared_shock) is exploratory for
    lack of power (prereg.md, section 5).
    Quantities:
      shared_shock   1 - r, r the disattenuated cross-correlation of `low` and `ref` errors (all items),
                     averaged over cells. Above 0 = copies of the quantized model share errors the reference does
                     not make: quantization error does not diversify. A shift that only lowers every item's success
                     (even one larger on hard items) leaves r near 1; a fixed item-specific perturbation of the
                     weights lowers it.
      gap_persists   on hard items, k-vote(ref) - k-vote(low): above 0 = at equal width the quantized model stays
                     behind ("k W4 copies do not recover BF16 accuracy on the hardest third", at equal k).
      concentration  (single ref - single low) on hard items minus on easy items: above 0 = quantization lowers
                     ability mainly on hard items.
      gap_change     on hard items, the precision gap at k votes minus at 1 sample: below 0 = width narrows it.
      literal        on hard items, k-vote(low) - single(ref), the brief's literal comparison; it counts only when
                     gap_persists is supported (otherwise it measures the reference's own vote gain).
    Intervals: item bootstrap (n_boot draws); every cell's statistic is recomputed on the same resampled items."""
    systems = systems_frame(table)
    k = k or s.k
    rows, cells_data = [], []
    for size in sorted(systems["size_b"].unique()):
        diff, in_sample = difficulty(table, size)
        terc = terciles(diff).reindex(s.items)
        hard, easy = (terc == "hard").to_numpy(), (terc == "easy").to_numpy()
        for budget in sorted(systems["budget"].unique()) if budgets is None else budgets:
            a, b = system_of(systems, size, low, budget), system_of(systems, size, ref, budget)
            if a is None or b is None:
                continue
            Ea, Eb = 1 - s.right[a], 1 - s.right[b]
            vote_a, vote_b = compose.expected_vote(s, [(a, k)]), compose.expected_vote(s, [(b, k)])
            single_a, single_b = s.right[a].mean(axis=1), s.right[b].mean(axis=1)
            cells_data.append({"Ea": Ea, "Eb": Eb, "hard": hard, "easy": easy, "gap1": single_b - single_a,
                               "gapk": vote_b - vote_a, "literal": vote_a - single_b})
            rows.append({"size_b": size, "budget": budget, "low": a, "ref": b, "in_sample_terciles": in_sample,
                         "corr_within_low": pairwise_corr(Ea), "corr_within_ref": pairwise_corr(Eb),
                         "corr_cross": pairwise_corr(Ea, Eb), "disattenuated_r": disattenuated(Ea, Eb),
                         "single_low": single_a.mean(), "single_ref": single_b.mean(),
                         f"vote{k}_low": vote_a.mean(), f"vote{k}_ref": vote_b.mean(),
                         "gain_low": (vote_a - single_a).mean(), "gain_ref": (vote_b - single_b).mean(),
                         "hard_single_low": single_a[hard].mean(), "hard_single_ref": single_b[hard].mean(),
                         "easy_single_low": single_a[easy].mean(), "easy_single_ref": single_b[easy].mean(),
                         f"hard_vote{k}_low": vote_a[hard].mean(), f"hard_vote{k}_ref": vote_b[hard].mean()})
    cells = pd.DataFrame(rows)
    if cells.empty:
        return {"cells": cells}

    def mean_over(rows_, key, mask):
        values = [c[key][rows_][c[mask][rows_]].mean() for c in cells_data if c[mask][rows_].any()]
        return float(np.mean(values)) if values else float("nan")

    def shock(rows_):
        return float(np.nanmean([1 - disattenuated(c["Ea"][rows_], c["Eb"][rows_]) for c in cells_data]))

    n = len(s.items)
    gap = boot_stat(lambda r: mean_over(r, "gapk", "hard"), n, n_boot)
    out = {"cells": cells,
           "primary": gap,
           "shared_shock": boot_stat(shock, n, n_boot),
           "gap_persists": gap,
           "concentration": boot_stat(lambda r: mean_over(r, "gap1", "hard") - mean_over(r, "gap1", "easy"), n, n_boot),
           "gap_change": boot_stat(lambda r: mean_over(r, "gapk", "hard") - mean_over(r, "gap1", "hard"), n, n_boot),
           "literal": boot_stat(lambda r: mean_over(r, "literal", "hard"), n, n_boot)}
    for name in ("shared_shock", "gap_persists", "concentration"):
        out[name]["supported"] = bool(out[name]["low"] > 0)
    out["gap_change"]["supported"] = bool(out["gap_change"]["high"] < 0)  # width narrows the gap
    out["literal"]["counts"] = out["gap_persists"]["supported"]
    out["literal"]["supported"] = bool(out["literal"]["counts"] and out["literal"]["high"] < 0)
    return out


# ------------------------------------------------------------------------------------------------------------
# T2: width vs precision at equal weight memory

MEMORY_EQUAL = (("w4", 4), ("w8", 2), ("bf16", 1))


def kernel_seconds(table: pd.DataFrame, kernel: pd.DataFrame) -> pd.Series:
    """Per row: GPU-seconds on real kernels = cost_tokens / the real-kernel run's output tokens per second for its size
    and precision (kernel.csv: columns size_b, precision, tokens_per_s)."""
    rate = table[["size_b", "precision"]].astype({"size_b": float}).merge(
        kernel.astype({"size_b": float}), on=["size_b", "precision"], how="left")["tokens_per_s"].to_numpy()
    return pd.Series(compose.cost_tokens(table).to_numpy() / rate, index=table.index)


def t2(table: pd.DataFrame, s: Samples, picks: pd.DataFrame | None = None, judge: str | None = None,
       kernel: pd.DataFrame | None = None) -> dict:
    """Per cell: 4 x W4 (4-vote, and the judge's pick among 4), 2 x W8 (the judge's pick among 2; a 2-vote equals one
    sample in expectation, so it is reported as single W8) and 1 x BF16. At equal GPU-seconds (with the real-kernel
    table): each precision's k-vote at the k whose kernel seconds per sample come closest to 1 x BF16's (k <= k_max;
    `capped` when more would be needed). Primary: 4-vote(W4) - single(BF16), pooled over cells, two-sided."""
    systems = systems_frame(table)
    rows, primary = [], Pool(s.items)
    sk = Samples.from_table(table, kernel_seconds(table, kernel)) if kernel is not None and not kernel.empty else None
    for (size, budget), _ in systems.groupby(["size_b", "budget"]):
        names = {p: system_of(systems, size, p, budget) for p, _ in MEMORY_EQUAL}
        if any(v is None for v in names.values()):
            continue
        row = {"size_b": size, "budget": budget}
        w4 = compose.expected_vote(s, [(names["w4"], 4)])
        bf = s.right[names["bf16"]].mean(axis=1)
        row.update({"vote_4xw4": w4.mean(), "single_w8": s.right[names["w8"]].mean(), "single_bf16": bf.mean()})
        primary.add(s.items, w4 - bf)
        if picks is not None and judge is not None and "candidates" in picks:
            for p, n in (("w4", 4), ("w8", 2)):
                sel = picks[(picks["judge"] == judge) & (picks["system"] == names[p]) & (picks["candidates"] == n)]
                if not sel.empty:
                    t = table[(table["system"] == names[p]) & (table["call"] < n)]
                    frame = checkers.pick_by_judge(t, sel.drop(columns=["candidates"]), judge)
                    row[f"judge_{n}x{p}"] = frame["picked"].mean()
        if sk is not None:
            target = sk.cost[names["bf16"]].mean()
            for p, _ in MEMORY_EQUAL:
                ratio = target / max(sk.cost[names[p]].mean(), 1e-12)
                n = int(np.clip(round(ratio), 1, s.k))
                row.update({f"equal_gpu_k_{p}": n, f"equal_gpu_capped_{p}": ratio > s.k + 0.5,
                            f"equal_gpu_vote_{p}": compose.expected_vote(s, [(names[p], n)]).mean()})
        rows.append(row)
    out = primary.result()
    out["supported"] = bool(out["low"] > 0 or out["high"] < 0)
    return {"cells": pd.DataFrame(rows), "primary": out}


# ------------------------------------------------------------------------------------------------------------
# T3: depth vs width at equal GPU-seconds

def odd_mixture(s: Samples, system: str, ratio: float, k_max: int) -> tuple[np.ndarray, tuple]:
    """Per item: the expected accuracy of a cost-matched vote of `ratio` samples, as a mixture of the two neighbouring
    odd vote sizes (k_lo <= ratio <= k_hi, weights so that the expected number of samples is `ratio`). Odd sizes
    only, because an even vote ties and a 2-vote is worth one sample."""
    odds = [k for k in range(1, k_max + 1, 2)]
    lo = max([k for k in odds if k <= ratio], default=1)
    hi = min([k for k in odds if k >= ratio], default=odds[-1])
    if hi == lo:
        return compose.expected_vote(s, [(system, lo)]), (lo, lo, 1.0)
    w = (hi - ratio) / (hi - lo)
    return (w * compose.expected_vote(s, [(system, lo)]) + (1 - w) * compose.expected_vote(s, [(system, hi)]),
            (lo, hi, round(w, 3)))


def t3(table: pd.DataFrame, s: Samples, precision: str = "bf16", pairs=((4096, 1024), (1024, 0))) -> dict:
    """Per size and (deep, shallow) budget pair, BF16 only: one sample at the deep budget against a cost-matched vote
    at the shallow budget. The ratio r of their mean cost per sample (cost_tokens: within one checkpoint GPU time is
    about proportional to it, and it is immune to cached calls) is matched by a mixture of the two neighbouring odd
    vote sizes (odd_mixture). A pair with r above the largest odd vote that k samples allow (5 of 6), or below 1, is
    "capped": it is reported but left out of the primary. Primary: deep minus wide, pooled over the uncapped cells, two-sided."""
    systems = systems_frame(table)
    rows, primary = [], Pool(s.items)
    k_odd = s.k if s.k % 2 else s.k - 1
    for size in sorted(systems["size_b"].unique()):
        for deep, shallow in pairs:
            d, w = system_of(systems, size, precision, deep), system_of(systems, size, precision, shallow)
            if d is None or w is None:
                continue
            ratio = s.cost[d].mean() / max(s.cost[w].mean(), 1e-9)
            capped = ratio > k_odd or ratio < 1  # r < 1: one shallow sample already costs more than the deep one
            deep_acc = s.right[d].mean(axis=1)
            wide_acc, mix = odd_mixture(s, w, min(ratio, k_odd), k_odd)
            if not capped:
                primary.add(s.items, deep_acc - wide_acc)
            rows.append({"size_b": size, "deep": deep, "shallow": shallow, "cost_ratio": ratio, "k_low": mix[0],
                         "k_high": mix[1], "weight_low": mix[2], "capped": capped, "deep_single": deep_acc.mean(),
                         "wide_vote": wide_acc.mean(), "deep_minus_wide": (deep_acc - wide_acc).mean()})
    out = primary.result()
    out["supported"] = bool(out["low"] > 0 or out["high"] < 0)
    return {"cells": pd.DataFrame(rows), "primary": out}


# ------------------------------------------------------------------------------------------------------------
# T4: verifier coupling

def selections(table: pd.DataFrame, checks: pd.DataFrame | None, picks: pd.DataFrame | None,
               judges: list[str]) -> dict[str, pd.DataFrame]:
    out = {"margin": checkers.pick_by_signal(table, "signal_margin"),
           "logprob_mean": checkers.pick_by_signal(table, "signal_logprob_mean"),
           "entropy": checkers.pick_by_signal(table, "signal_entropy", higher=False)}
    if checks is not None and not checks.empty:
        out["self_check"] = checkers.pick_by_self_check(table, checks)
    for j in judges:
        if picks is not None and not picks.empty:
            p = picks[picks["candidates"] == checkers.JUDGE_CANDIDATES] if "candidates" in picks else picks
            out[f"judge:{j}"] = checkers.pick_by_judge(table, p, j)
    if "signal_exec_visible" in table and table["signal_exec_visible"].notna().any():
        out["execution"] = checkers.pick_by_execution(table)
    return out


def candidate_free_terciles(table: pd.DataFrame, first: int = checkers.JUDGE_CANDIDATES) -> pd.Series:
    """Item terciles from samples no checker ever chose among (calls `first`.. of every config), cut within each
    benchmark family (bbeh, math, code). The candidates (calls 0..first-1) then do not enter the cut, so a lucky draw
    of right candidates cannot make an item "easy"; and cutting within a benchmark keeps "hard" from meaning "math"
    when benchmarks differ in difficulty and the judge differs by benchmark (audit T1-3)."""
    rest = table[table["call"] >= first]
    family = rest["benchmark"].astype(str).str.split("/").str[0]
    parts = [terciles(1 - part.groupby("item")["correct"].mean().astype(float)) for _, part in rest.groupby(family)]
    return pd.concat(parts)


def coupling_gap(frame: pd.DataFrame, terc: pd.Series, n: int, n_boot: int = 0, seed: int = 0):
    """Within each stratum (config, benchmark family, m = 1..n-1 right candidates): eta(easy) - eta(hard); averaged
    over strata with weights min(units easy, units hard). Strata m = 0 and m = n have no room to select and are left
    out. Within a stratum m is fixed, so eta's random pick (m / n) and oracle (1) are constants and the gap is a
    scaled difference of pick accuracies. The config (audit T1-2) and the benchmark (audit T1-3) are in the stratum
    because easy and hard units differ in which models wrote them and which benchmark they come from, and a judge's
    skill may depend on either.
    Returns the estimate, or with n_boot > 0 (estimate, bootstrap values): items resampled with replacement, every
    sum recomputed as (item multiplicities) @ (per-item sums)."""
    f = frame.assign(tercile=frame["item"].map(terc), m=checkers.candidates_right(frame, n))
    f = f[(f["m"] > 0) & (f["m"] < n) & f["tercile"].isin(["easy", "hard"])]
    items = np.array(sorted(frame["item"].unique()))
    if f.empty:
        return (float("nan"), np.full(n_boot, np.nan)) if n_boot else float("nan")
    bench = f["benchmark"].astype(str).str.split("/").str[0] if "benchmark" in f else "all"
    f = f.assign(stratum=f["system"].astype(str) + "|" + bench + "|" + f["m"].astype(str), units=1.0)
    sums = f.groupby(["item", "stratum", "tercile"])[["picked", "random", "oracle", "units"]].sum()
    wide = sums.unstack(["stratum", "tercile"]).reindex(items).fillna(0.0).astype(float)  # items x (quantity, stratum, tercile)

    def stat(weights: np.ndarray) -> np.ndarray:
        """weights: draws x items. Returns the weighted gap per draw."""
        tot = {q: weights @ wide[q].to_numpy(dtype=float) for q in ("picked", "random", "oracle", "units")}
        cols = wide["units"].columns
        out_num, out_den = np.zeros(len(weights)), np.zeros(len(weights))
        for stratum in cols.get_level_values(0).unique():
            if (stratum, "easy") not in cols or (stratum, "hard") not in cols:
                continue
            e, h = cols.get_loc((stratum, "easy")), cols.get_loc((stratum, "hard"))
            eta_e = (tot["picked"][:, e] - tot["random"][:, e]) / (tot["oracle"][:, e] - tot["random"][:, e])
            eta_h = (tot["picked"][:, h] - tot["random"][:, h]) / (tot["oracle"][:, h] - tot["random"][:, h])
            w = np.minimum(tot["units"][:, e], tot["units"][:, h])
            gap = eta_e - eta_h
            ok = np.isfinite(gap) & (w > 0)
            out_num += np.where(ok, w * gap, 0.0)
            out_den += np.where(ok, w, 0.0)
        return np.where(out_den > 0, out_num / np.maximum(out_den, 1e-12), np.nan)

    with np.errstate(divide="ignore", invalid="ignore"):
        estimate = float(stat(np.ones((1, len(items))))[0])
        if not n_boot:
            return estimate
        rng = np.random.default_rng(seed)
        draws = rng.multinomial(len(items), np.full(len(items), 1 / len(items)), size=n_boot).astype(float)
        return estimate, stat(draws)


def t4(table: pd.DataFrame, checks: pd.DataFrame | None = None, picks: pd.DataFrame | None = None,
       judges: list[str] = (), primary_checker: str | None = None, n_boot: int = 2000,
       level: float = T4_LEVEL) -> dict:
    """eta per checker, difficulty tercile and number of right candidates (checkers.eta_table), with terciles cut on
    samples that were never candidates (candidate_free_terciles). Primary: for `primary_checker` (default the first
    judge, else margin), the stratified coupling gap (coupling_gap: eta easy minus eta hard within each config,
    benchmark and number of right candidates), item bootstrap; coupling is supported when the `level` (99%) interval
    is above 0. The 99% level was chosen on the power simulation, before any data: at 95% the one-sided false-positive
    rates in the null worlds were 0.03 / 0.05 / 0.03 (the config-dependent judge at twice the nominal 0.025), at 99%
    0.00 / 0.02 / 0.00, while the planted gap stays far from 0 (prereg.md, sections 4 and 5)."""
    terc = candidate_free_terciles(table)
    sel = selections(table, checks, picks, list(judges))
    n_of = {name: (len(checkers.SELF_CHECK_SAMPLES) if name == "self_check" else
                   checkers.JUDGE_CANDIDATES if name.startswith("judge:") else int(table["call"].max()) + 1)
            for name in sel}
    etas = checkers.eta_table(sel, terc, n_of)
    name = primary_checker or (f"judge:{judges[0]}" if judges else "margin")
    frame, n = sel[name], n_of[name]
    frame = frame.assign(benchmark=frame["item"].map(table.drop_duplicates("item").set_index("item")["benchmark"]))
    estimate, boot = coupling_gap(frame, terc, n, n_boot)
    tail = 100 * (1 - level) / 2
    primary = {"checker": name, "estimate": estimate, "level": level, "low": float(np.nanpercentile(boot, tail)),
               "high": float(np.nanpercentile(boot, 100 - tail))}
    primary["supported"] = bool(primary["low"] > 0)
    return {"eta": etas, "primary": primary}


# ------------------------------------------------------------------------------------------------------------
# T5: compositional prediction

def t5(table: pd.DataFrame, fit_items: list[str], heldout_items: list[str], escalate: str | None = None,
       rank: int = 2, draws: int = 400, margin: float = 0.03, probe_call: int = 0,
       max_ratio: float | None = None) -> dict:
    """Fit the factor model's config parameters on the fit items (all calls); on the held-out items, fit item
    parameters and wrong-answer distributions on call `probe_call` only, predict every composition of the other calls
    (k - 1 = 5 per config: votes of 1..5, mixes of 2 and 4, 3-vote cascades) and compare with their exact replay.
    Supported when the factor model's mean absolute error is below `max_ratio` (T5_MAX_RATIO) times the baseline's
    (factor.Predictor with baseline=True: the same unique mass, shared wrong answers spread evenly). The bar was set
    on the power simulation, before any data, as the largest that keeps the false-positive rate at or below 0.05 in
    every misspecified world (5 and 10 answer classes; with 2 classes the baseline equals the model; prereg.md,
    section 5). The brief's absolute criteria (at least 90% of compositions, and every composition,
    within 3 points) are reported too, but cannot be the test: with 109 held-out items and 5 samples per config, the
    replay itself is noisy: predicting with the true world's own probabilities met the 90% bar in 5 of 8 simulated
    draws, with a mean absolute error of 1.5 points (prereg.md, section 5)."""
    t = table if "cls" in table else compose.add_classes(table)
    held = t[t["item"].isin(heldout_items)]
    s_fit = Samples.from_table(t[t["item"].isin(fit_items)])
    s_probe = Samples.from_table(held[held["call"] == probe_call].assign(call=0))
    rest = held[held["call"] != probe_call]
    rest = rest.assign(call=rest["call"] - (rest["call"] > probe_call))  # renumber 0..k-2
    s_test = Samples.from_table(rest)
    systems = sorted(s_fit.cls)
    comps = compose.compositions(systems_frame(t), s_test.k, escalate)
    actual = np.array([compose.score(s_test, c)[0].mean() for c in comps])
    pred = factor.predict_heldout(s_fit, s_probe, systems, comps, rank, draws)
    base = factor.predict_heldout(s_fit, s_probe, systems, comps, rank, draws, baseline=True)
    frame = pd.DataFrame({"kind": [c["kind"] for c in comps], "composition": [c["name"] for c in comps],
                          "actual": actual, "predicted": pred, "baseline": base})
    frame["error"] = frame["predicted"] - frame["actual"]
    frame["baseline_error"] = frame["baseline"] - frame["actual"]
    within = float((frame["error"].abs() <= margin + 1e-12).mean())
    primary = {"compositions": len(frame), "share_within": within, "every_within": bool(within == 1.0),
               "mae": float(frame["error"].abs().mean()), "max_abs_error": float(frame["error"].abs().max()),
               "baseline_mae": float(frame["baseline_error"].abs().mean())}
    max_ratio = T5_MAX_RATIO if max_ratio is None else max_ratio
    primary["mae_ratio"] = primary["mae"] / max(primary["baseline_mae"], 1e-12)
    primary["within_90"] = bool(within >= 0.9)
    primary["supported"] = bool(primary["mae_ratio"] < max_ratio)
    by_kind = frame.assign(abs_error=frame["error"].abs()).groupby("kind")[["abs_error"]].agg(["mean", "max"])
    return {"compositions": frame, "by_kind": by_kind, "primary": primary}
