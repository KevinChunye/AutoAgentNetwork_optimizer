"""Search methods on the cached landscape, and their regret against the number of evaluations.

With 27 (v2 grid) or 216 configs exhaustive search is trivial (protocol 4.5), so the question is sample
efficiency: how good a config does each method find after N evaluations, where one
evaluation = running one new config on the search tasks (a paid network run in the full
study; a free table lookup here).

Terms:
  R_search(c)  reward of config c on the search half (what a method sees)
  R_held(c)    reward of c on the held-out half (what we score picks with)
  pick after N the config with the best R_search among the first N distinct configs evaluated
  regret(N)    max over all configs of R_held  -  R_held(pick after N); 0 is the best possible

Methods:
  random       evaluate distinct configs in a random order
  sensitivity  AMC-style: sweep each stage alone with the others dense, combine the per-stage
               bests (a fixed number of evaluations, plotted as one point)
  greedy       start dense; evaluate every move of one stage to its next lower evaluated level;
               move to the best if it improves; stop when none does
  reinforce    a factorized softmax policy over each stage's evaluated keep levels (3 per stage on
               the v2 1/3/6 grid), trained with REINFORCE and a moving-average baseline for up to
               2,000 episodes; repeated configs cost no new evaluation
  exhaustive   all evaluated configs (27 on the v2 grid, 216 on the full landscape)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .common import color, style
from .landscape import STAGES, Landscape, keep_of, reward, sensitivity_pick, summarize


def _regret_trace(order: list[str], r_search: pd.Series, r_held: pd.Series, best_held: float) -> np.ndarray:
    """regret after each new evaluation in `order` (distinct configs)."""
    best_c, best_r, out = None, -np.inf, []
    for c in order:
        if r_search[c] > best_r:
            best_c, best_r = c, r_search[c]
        out.append(best_held - r_held[best_c])
    return np.array(out)


def stage_levels(config_ids) -> list[list[int]]:
    """The keep levels evaluated for each prunable stage, e.g. [[1, 3, 6]] * 3 on the v2 grid or
    [[1, ..., 6]] * 3 on the full landscape."""
    keeps = pd.DataFrame([keep_of(c)[:3] for c in config_ids])
    return [sorted(int(v) for v in keeps[s].unique()) for s in range(3)]


def config_id(keep: list[int]) -> str:
    return f"k{keep[0]}-{keep[1]}-{keep[2]}-1"


def greedy_order(summary: pd.DataFrame, r: pd.Series, dense_id: str) -> list[str]:
    """Start dense; evaluate every move of one stage to its next lower evaluated level (3 -> 1 on
    the 1/3/6 grid, k -> k-1 on the full landscape); move to the best if it improves; stop when
    none does."""
    levels = stage_levels(r.index)
    order, current = [dense_id], dense_id
    while True:
        k = keep_of(current)
        neighbours = []
        for s in range(3):
            lower = [v for v in levels[s] if v < k[s]]
            if lower:
                n = k.copy()
                n[s] = lower[-1]
                neighbours.append(config_id(n))
        neighbours = [c for c in neighbours if c in r.index]
        order += [c for c in neighbours if c not in order]
        if not neighbours:
            return order
        best = r.loc[neighbours].idxmax()
        if r[best] <= r[current]:
            return order
        current = best


def reinforce_order(r: pd.Series, rng: np.random.Generator, episodes: int = 2000, lr: float = 0.5) -> list[str]:
    """Distinct configs in the order a REINFORCE controller first samples them. The policy is a
    softmax over each stage's evaluated keep levels (3 choices on the 1/3/6 grid, 6 on the full
    landscape)."""
    levels = stage_levels(r.index)
    logits = [np.zeros(len(lv)) for lv in levels]
    baseline, order, seen = None, [], set()
    for _ in range(episodes):
        probs = [np.exp(lg - lg.max()) for lg in logits]
        probs = [pr / pr.sum() for pr in probs]
        picks = [int(rng.choice(len(levels[s]), p=probs[s])) for s in range(3)]
        c = config_id([levels[s][picks[s]] for s in range(3)])
        if c not in r.index:  # a grid with holes: skip configs that were never evaluated
            continue
        if c not in seen:
            seen.add(c)
            order.append(c)
        reward_c = r[c]
        baseline = reward_c if baseline is None else 0.9 * baseline + 0.1 * reward_c
        advantage = reward_c - baseline
        for s in range(3):
            grad = -probs[s]
            grad[picks[s]] += 1
            logits[s] += lr * advantage * grad
    return order


def regret_curves(L: Landscape, search: list[str], held: list[str], lam: float = 0.05,
                  seeds: int = 100, label_free: bool = False) -> pd.DataFrame:
    """Rows: method, evaluations, mean regret and the 2.5/97.5 percentiles over seeds."""
    s_search, s_held = summarize(L, search), summarize(L, held)
    r_search = reward(s_search, L.dense_id, lam, label_free)
    r_held = reward(s_held, L.dense_id, lam)  # picks are always scored with labels
    best_held = r_held.max()
    n = len(r_search)
    rows = []

    def add(method: str, traces: list[np.ndarray]):
        length = min(len(t) for t in traces)
        m = np.stack([t[:length] for t in traces])
        for i in range(length):
            rows.append({"method": method, "evaluations": i + 1, "regret": m[:, i].mean(),
                         "lo": np.percentile(m[:, i], 2.5), "hi": np.percentile(m[:, i], 97.5)})

    rng = np.random.default_rng(0)
    add("random", [_regret_trace(list(rng.permutation(r_search.index)), r_search, r_held, best_held) for _ in range(seeds)])
    add("reinforce", [_regret_trace(reinforce_order(r_search, np.random.default_rng(i)), r_search, r_held, best_held)
                      for i in range(seeds)])
    add("greedy", [_regret_trace(greedy_order(s_search, r_search, L.dense_id), r_search, r_held, best_held)])
    sens, evaluated = sensitivity_pick(s_search, r_search)
    rows.append({"method": "sensitivity", "evaluations": len(evaluated), "regret": best_held - r_held[sens],
                 "lo": np.nan, "hi": np.nan})
    exhaustive = r_search.idxmax()
    rows.append({"method": "exhaustive", "evaluations": n, "regret": best_held - r_held[exhaustive],
                 "lo": np.nan, "hi": np.nan})
    return pd.DataFrame(rows)


def plot_regret(curves: pd.DataFrame, title: str):
    """Figure (d): regret (held-out reward points) against evaluations, 95% band over seeds."""
    plt = style()
    fig, ax = plt.subplots(figsize=(5.0, 3.2))
    for i, method in enumerate(["random", "reinforce", "greedy"]):
        c = curves[curves["method"] == method]
        ax.plot(c["evaluations"], 100 * c["regret"], color=color(i), label=method)
        if c["lo"].notna().any() and len(c) > 1:
            ax.fill_between(c["evaluations"], 100 * c["lo"], 100 * c["hi"], color=color(i), alpha=0.15)
    for i, method in enumerate(["sensitivity", "exhaustive"]):
        c = curves[curves["method"] == method]
        ax.scatter(c["evaluations"], 100 * c["regret"], marker="D", color=color(3 + i), label=method, zorder=3)
    ax.set_xscale("log")
    ax.set_xlabel("distinct configs evaluated")
    ax.set_ylabel("regret (held-out reward points)")
    ax.text(0.99, 0.02, "bands: 95% over search seeds only, not task sampling noise", transform=ax.transAxes,
            ha="right", va="bottom", fontsize=6, color="0.35")
    ax.legend(fontsize=7)
    ax.set_title(title, fontsize=9)
    return fig


__all__ = ["STAGES", "regret_curves", "plot_regret", "greedy_order", "reinforce_order"]
