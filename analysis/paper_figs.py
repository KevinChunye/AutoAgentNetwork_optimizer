"""The paper's figures (session W1), as vector PDFs in paper/figs/, drawn from committed tables only.

  fig_share      systematic failure share per source: L0 share with its item-bootstrap interval and the range over system
                 half-splits (P6), and the
                 anchor's shares (no interval yet)
  fig_tail       SWE-bench Verified, held-out systems on held-out tasks: coverage of k-system sets (one minus the share
                 every member fails) observed, from the factor model, the one-factor copula and independence (P8)
  fig_depth      depth pairs: change in ability and in failure beta per pair, with the random-effects pool (P2)
  fig_dw         one deeper call minus the nearest-dollar vote: the anchor's AH2 and the public pairs (P3)
  fig_judge      the anchor's BBEH verification: cheap pools, plurality, the judge, coverage and the judge model alone
  fig_labelfree  the label-free selection map: gain over the best system, plain and fixed-label Dawid-Skene (P4)
  fig_frontier   SWE-bench Verified accuracy against dollars per task, with the price frontier (A7)

Colours: the categorical order blue, orange, aqua, yellow of the dataviz reference palette; the diverging blue-red
pair with a grey midpoint for gains. Usage: python -m analysis.paper_figs
"""

from __future__ import annotations

import os
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

from analysis.atlas_extend import read_table  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ATLAS = ROOT / "research/v4/atlas/tables"
EXT = ATLAS / "extend"
READ = ROOT / "research/v4/anchor/read.md"
OUT = ROOT / "paper/figs"
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
DIVERGING = LinearSegmentedColormap.from_list("gain", ["#d03b3b", "#f0efec", "#2a78d6"])
COL, TEXT = 3.3, 6.75  # inches: the ICML column and text widths (figures are drawn at their printed size)

plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 8, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.5, "legend.frameon": False,
    "pdf.fonttype": 42, "savefig.bbox": "tight"})


def settings(low: str, high: str) -> tuple[str, str]:
    """The two setting names of a depth pair: what is left of the system names after their common prefix
    ("default" when nothing is left), e.g. openai/o3-mini--medium and openai/o3-mini -> (medium, default)."""
    common = len(os.path.commonprefix([low, high]))
    return tuple((name[common:].strip("-_") or "default") for name in (low, high))


def pair_label(model: str, low: str, high: str, source: str = "") -> str:
    a, b = settings(low, high)
    where = {"swebench_verified": "SWE-bench", "matharena": "MathArena", "livebench": "LiveBench"}.get(source, "")
    return f"{model}{f' ({where})' if where else ''}: {a} \u2192 {b}"


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)


def fig_share() -> None:
    p6 = pd.read_csv(EXT / "p6_shares.csv")
    p6 = p6[p6["quantity"] == "(all) L0"]
    names = {"swebench_verified": "SWE-bench Verified (173)", "swebench_verified (39 with details)":
             "SWE-bench Verified, 39 with details", "matharena": "MathArena (24 sets)",
             "livebench": "LiveBench (3 tasks)", "bbeh_phase1": "BBEH, Phase 1 panel (4 arms)"}
    p6 = p6[p6["source"].isin(names)].assign(label=lambda d: d["source"].map(names)).sort_values("share")
    tail = read_table(["k", "observed", "independent", "L0", "L1", "copula", "rho", "items"], READ)
    anchor = tail[tail["items"].isin(["bbeh", "math"])].drop_duplicates("items")
    fig, ax = plt.subplots(figsize=(COL, 2.3))
    y = np.arange(len(p6))
    ax.hlines(y, p6["half-split min"], p6["half-split max"], color=BLUE, lw=1, alpha=0.5, label="system half-splits (range)")
    ax.hlines(y, p6["item lo"], p6["item hi"], color=BLUE, lw=3, label="item bootstrap")
    ax.plot(p6["share"], y, "o", color=BLUE, ms=5)
    ya = np.arange(len(p6), len(p6) + len(anchor))
    ax.plot(anchor["systematic_share_L0"], ya, "o", mfc="white", mec=ORANGE, ms=5, label="API anchor (no interval yet)")
    ax.set_yticks(list(y) + list(ya))
    ax.set_yticklabels(list(p6["label"]) + [f"anchor, {i}" for i in anchor["items"]], color=INK2)
    ax.set_xlim(0, 1)
    ax.set_xlabel("systematic share of failure variation (L0)")
    ax.legend(loc="upper center", bbox_to_anchor=(0.35, -0.22), ncol=2, fontsize=6.5, columnspacing=1.0, handlelength=1.5)
    save(fig, "fig_share")


def fig_tail() -> None:
    t8 = pd.read_csv(EXT / "p8_tail.csv")
    t = t8[t8["benchmark"] == "swebench_verified"].sort_values("members")
    fig, ax = plt.subplots(figsize=(TEXT * 0.62, 2.4))
    x = t["members"]
    for col, color, label, style in (("independence", AQUA, "independence", "-"), ("copula", YELLOW, "one-factor copula", "-"),
                                     ("factor model", ORANGE, "factor model", "-")):
        ax.plot(x, 1 - t[col], style, color=color, label=label)
    ax.plot(x, 1 - t["observed all-wrong"], "o", color=BLUE, ms=5, label="observed (held out)")
    ax.set_xscale("log")
    ax.set_xticks(list(x))
    ax.set_xticklabels([str(v) for v in x])
    ax.set_xlabel("systems in the set (held-out systems, held-out tasks)")
    ax.set_ylabel("coverage: some member resolves the task")
    ax.legend(fontsize=7, loc="center right", bbox_to_anchor=(1.0, 0.35))
    save(fig, "fig_tail")


def fig_depth() -> None:
    p2 = pd.read_csv(EXT / "p2_pairs.csv")
    pooled = pd.read_csv(EXT / "p2_pooled.csv").query("scope == 'all adjacent pairs'").set_index("quantity")
    p2 = p2.assign(label=[pair_label(m, lo, hi, src) for m, lo, hi, src in zip(p2["model"], p2["low"], p2["high"],
                                                                              p2["source"])])
    fig, axes = plt.subplots(1, 2, figsize=(TEXT, 3.4), sharey=True)
    y = np.arange(len(p2))[::-1]
    for ax, q, title in ((axes[0], "delta a", "change in ability a (logits)"),
                         (axes[1], "delta beta", "change in failure beta")):
        ax.hlines(y, p2[f"{q} lo"], p2[f"{q} hi"], color=BLUE, lw=1.2)
        ax.plot(p2[q], y, "o", color=BLUE, ms=3.5)
        r = pooled.loc[q]
        ax.fill([r["lo"], r["pooled"], r["hi"], r["pooled"]], [-1.5, -1.1, -1.5, -1.9], color=ORANGE)
        ax.axvline(0, color=MUTED, lw=0.8)
        ax.set_xlabel(title)
    axes[0].set_yticks(list(y) + [-1.5])
    axes[0].set_yticklabels(list(p2["label"]) + ["random-effects pool"], fontsize=6, color=INK2)
    save(fig, "fig_depth")


def fig_dw() -> None:
    ah2 = read_table(["vendor", "k", "difference", "lo", "hi", "p"], READ)
    p3 = pd.read_csv(EXT / "p3_pairs.csv").dropna(subset=["difference"])
    pooled = pd.read_csv(EXT / "p3_pooled.csv").query("scope == 'all pairs' and quantity == 'difference'").iloc[0]
    labels = [f"anchor: {v.capitalize()} (AH2, k = {k})" for v, k in zip(ah2["vendor"], ah2["k"])] + \
        [pair_label(m, lo, hi) for m, lo, hi in zip(p3["model"], p3["low"], p3["high"])]
    est = list(ah2["difference"]) + list(p3["difference"])
    lo = list(ah2["lo"]) + list(p3["difference lo"])
    hi = list(ah2["hi"]) + list(p3["difference hi"])
    colors = [ORANGE] * len(ah2) + [BLUE] * len(p3)
    fig, ax = plt.subplots(figsize=(COL, 3.0))
    y = np.arange(len(est))[::-1]
    for yy, e, a, b, c in zip(y, est, lo, hi, colors):
        ax.hlines(yy, 100 * a, 100 * b, color=c, lw=1.2)
        ax.plot(100 * e, yy, "o", color=c, ms=4)
    ax.fill(100 * np.array([pooled["lo"], pooled["pooled"], pooled["hi"], pooled["pooled"]]),
            [-1.5, -1.1, -1.5, -1.9], color=BLUE)
    ax.axvline(0, color=MUTED, lw=0.8)
    ax.set_yticks(list(y) + [-1.5])
    ax.set_yticklabels(labels + ["public pairs, random-effects pool"], fontsize=6.5, color=INK2)
    ax.set_xlabel("one deeper call minus the nearest-dollar vote of the shallower setting (points)")
    save(fig, "fig_dw")


def fig_judge() -> None:
    j = read_table(["judge", "items", "n", "judge_accuracy"], READ)
    j = j[(j["judge"] == "sol_low_judge") & (j["items"] == "bbeh")].iloc[0]
    width = read_table(["items", "arm", "k", "n", "accuracy"], READ)
    sol = width[(width["items"] == "bbeh") & (width["arm"] == "sol_low") & (width["k"] == 1)].iloc[0]
    rows = [("best cheap pool arm", j["best_single"], f"${j['pool_dollars']:.4f} (pools)", BLUE),
            ("plurality of the pools", j["plurality"], "", BLUE),
            ("Sol low judge over the pools", j["judge_accuracy"], f"${j['judge_dollars'] + j['pool_dollars']:.4f}",
             BLUE),
            ("coverage of the pools (perfect selector)", j["coverage"], "", MUTED),
            ("Sol low answering alone", sol["accuracy"], f"${sol['dollars_per_item']:.4f}", ORANGE)]
    fig, ax = plt.subplots(figsize=(COL, 2.0))
    y = np.arange(len(rows))[::-1]
    for yy, (label, v, usd, c) in zip(y, rows):
        ax.barh(yy, 100 * v, color=c, height=0.6)
        ax.text(100 * v + 0.8, yy, f"{100 * v:.1f}%  {usd}", va="center", fontsize=7, color=INK2)
    ax.set_yticks(y)
    ax.set_yticklabels([r[0] for r in rows], color=INK2)
    ax.set_xlim(0, 80)
    ax.set_xlabel("accuracy on the anchor's 440 BBEH items (dollars per item beside each bar)")
    ax.grid(axis="y", visible=False)
    save(fig, "fig_judge")


def fig_labelfree() -> None:
    m = pd.read_csv(EXT / "p4_map.csv")
    g = m.groupby(["others", "sd_b", "repeats"])[["Dawid-Skene gain", "pooled Dawid-Skene, fixed labels gain",
                                                  "plurality gain"]].mean().reset_index()
    fig, axes = plt.subplots(1, 3, figsize=(TEXT, 2.0), sharey=True)
    cols = [(sd, r) for sd in (0.5, 2.0) for r in (1, 3)]
    for ax, (name, title) in zip(axes, (("plurality gain", "plurality"), ("Dawid-Skene gain", "Dawid-Skene, plain"),
                                        ("pooled Dawid-Skene, fixed labels gain", "pooled, fixed labels"))):
        M = np.array([[g[(g["others"] == o) & (g["sd_b"] == sd) & (g["repeats"] == r)][name].iloc[0] for sd, r in cols]
                      for o in (0.7, 0.5, 0.3)])
        ax.imshow(100 * M, cmap=DIVERGING, vmin=-60, vmax=60, aspect="auto")
        for i in range(M.shape[0]):
            for k in range(M.shape[1]):
                ax.text(k, i, f"{100 * M[i, k]:+.0f}", ha="center", va="center", fontsize=6.5, color=INK)
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels([f"{'low' if sd == 0.5 else 'high'}\n{r}" for sd, r in cols], fontsize=6)
        ax.set_xlabel("shared difficulty / calls", fontsize=6)
        ax.set_title(title, fontsize=8, color=INK)
        ax.grid(False)
    axes[0].set_yticks(range(3))
    axes[0].set_yticklabels(["others 0.7", "others 0.5", "others 0.3"], color=INK2)
    save(fig, "fig_labelfree")


def fig_frontier() -> None:
    prices = pd.read_csv(ATLAS / "f18_prices.csv").dropna(subset=["usd"])
    front = set(pd.read_csv(ATLAS / "a7_frontier.csv").query("benchmark == 'swebench_verified'")["system"])
    fig, ax = plt.subplots(figsize=(TEXT * 0.36, 2.4))
    other = prices[~prices["system"].isin(front)]
    on = prices[prices["system"].isin(front)].sort_values("usd")
    ax.plot(other["usd"], 100 * other["accuracy"], "o", color=MUTED, ms=3.5, alpha=0.7, label="submission")
    ax.plot(on["usd"], 100 * on["accuracy"], "o-", color=BLUE, ms=5, label="price frontier")
    offsets = [(4, -10), (-30, 6), (3, -11), (-46, 6)]  # cheapest first; placed by hand so labels do not collide
    for r, off in zip(on.itertuples(), offsets):
        name = r.system.split("_", 2)[-1].replace("-high", " (high)")
        ax.annotate(name, (r.usd, 100 * r.accuracy), textcoords="offset points", xytext=off, fontsize=6, color=INK2,
                    bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.85), zorder=5)
    ax.set_xscale("log")
    ax.set_xlabel("dollars per task (log scale)")
    ax.set_ylabel("tasks resolved (%)")
    ax.legend(fontsize=7, loc="lower right")
    save(fig, "fig_frontier")


FIGURES = [fig_share, fig_tail, fig_depth, fig_dw, fig_judge, fig_labelfree, fig_frontier]


def main() -> None:
    for f in FIGURES:
        f()
    print(f"{len(FIGURES)} figures -> {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
