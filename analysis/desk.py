"""Tables and figures of the conviction desk (W2-A; research/v3/plan_w2.md).

Reads results/<run>/events.csv and decisions.csv of the desk runs, keeps one block (tuning seeds
1-99 or the sealed judging seeds 101-199), and writes reports/v3/tables/desk_<block>_*.csv and
reports/v3/figures/desk_<block>_*.{pdf,png}. Every measure is defined in plain words in
autoagentnet/desk/metrics.py.

Figures:
  calibration   stated p (binned) against the share of events that happened, per structure
  sizing        sizing error against Kelly at the true p and at the structure's own p, per structure
  wealth        log wealth along each sequence, per structure, with Kelly and half Kelly at the true p
  salience      the news item's effect on the trader, paired on the same event (twin calls), and the
                unpaired effect per structure

Usage: python -m analysis.desk --runs w2a_tune --block tune
       python -m analysis.desk --runs w2a_judge_101 w2a_judge_102_105 --block judge
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

from autoagentnet.desk.metrics import (NONINFERIORITY, anchoring, calibration_curve, enrich, flip_rates, kelly_share,
                                       main_rows, oracle_table, salience_table, structure_table, tune_checks,
                                       twin_details, twin_table, versus_solo)

from . import common
from .common import ROOT

RESULTS = ROOT / "results"
REPORT = ROOT / "reports" / "v3"
BLOCKS = {"tune": (1, 99), "judge": (101, 199)}
STRUCTURE_NAMES = {"S1": "S1 solo", "S2": "S2 risk manager", "S3": "S3 half Kelly", "S4": "S4 committee"}


def load_calls(runs: list[str], block: str, results_dir: Path = RESULTS) -> pd.DataFrame:
    """Every model call of the given runs in one seed block, with its raw reply."""
    lo, hi = BLOCKS[block]
    calls = pd.concat([pd.read_csv(results_dir / r / "calls.csv") for r in runs], ignore_index=True)
    calls = calls.drop_duplicates(["event_id", "role", "model"])
    return calls[calls["seed"].between(lo, hi)]


def load(runs: list[str], block: str, results_dir: Path = RESULTS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Events and enriched decisions of the given runs, restricted to one seed block."""
    lo, hi = BLOCKS[block]
    events = pd.concat([pd.read_csv(results_dir / r / "events.csv") for r in runs], ignore_index=True)
    events = events.drop_duplicates("event_id")
    decisions = pd.concat([pd.read_csv(results_dir / r / "decisions.csv") for r in runs], ignore_index=True)
    decisions = decisions.drop_duplicates(["event_id", "structure", "model"])
    events = events[events["seed"].between(lo, hi)]
    decisions = decisions[decisions["seed"].between(lo, hi)]
    return events, enrich(decisions, events)


def wealth_paths(df: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Log wealth after each event, per (model, structure, seed), plus Kelly and half Kelly at the true p."""
    paths = main_rows(df).sort_values("index").assign(
        log_wealth=lambda d: d.groupby(["model", "structure", "seed"])["log_growth"].cumsum())
    rows = [paths[["model", "structure", "seed", "index", "log_wealth"]]]
    for fraction, label in ((1.0, "Kelly at true p"), (0.5, "half Kelly at true p")):
        e = events.sort_values("index").copy()
        k = e["true_kelly"]
        stake = fraction * k.abs()
        win = np.where(k > 0, e["outcome"] == 1, e["outcome"] == 0)
        payoff = np.where(k > 0, 1 / e["price"], 1 / (1 - e["price"]))
        growth = np.where(k == 0, 1.0, np.where(win, 1 - stake + stake * payoff, 1 - stake))
        e["log_wealth"] = pd.Series(np.log(growth), index=e.index).groupby(e["seed"]).cumsum()
        rows.append(e.assign(model="oracle", structure=label)[["model", "structure", "seed", "index", "log_wealth"]])
    return pd.concat(rows, ignore_index=True)


def fig_calibration(curve: pd.DataFrame):
    import matplotlib.pyplot as plt

    models = sorted(curve["model"].unique())
    fig, axes = plt.subplots(1, len(models), figsize=(4.2 * len(models), 3.8), squeeze=False)
    for ax, model in zip(axes[0], models):
        part = curve[curve["model"] == model]
        ax.plot([0, 1], [0, 1], color="0.7", lw=1, label="perfect calibration")
        for i, (structure, g) in enumerate(part.groupby("structure")):
            ax.plot(g["p"], g["happened"], color=common.color(i), lw=1, label=STRUCTURE_NAMES.get(structure, structure))
            ax.scatter(g["p"], g["happened"], s=8 + 40 * g["n"] / g["n"].max(), color=common.color(i))  # area ~ events
        ax.set_xlabel("stated probability (bin mean)")
        ax.set_ylabel("share of events that happened")
        ax.set_title(model, fontsize=9)
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
    axes[0][0].legend(fontsize=7, frameon=False)
    return fig


def fig_sizing(table: pd.DataFrame, oracle: pd.DataFrame | None = None):
    """Bars: sizing error per structure (S4 may cover fewer events). Lines: staying out and half Kelly
    at the true p on the whole block, the bar a design must beat and the best a half-Kelly rule can do."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6.5, 3.4))
    labels = [f"{STRUCTURE_NAMES.get(s, s)}\n{m}" for m, s in zip(table["model"], table["structure"])]
    x = np.arange(len(table))
    ax.bar(x - 0.2, table["size_err_true"], 0.4, color=common.color(0), label="against Kelly at the true p")
    ax.bar(x + 0.2, table["size_err_own"], 0.4, color=common.color(1), label="against Kelly at its own p")
    if oracle is not None:
        refs = oracle.set_index("benchmark")["size_err_true"]
        for name, style in (("stay out", ":"), ("0.5 Kelly at true p", "--")):
            if name in refs:
                ax.axhline(refs[name], color="0.4", ls=style, lw=1)
                ax.text(len(table) - 0.5, refs[name], f" {name}", fontsize=7, va="bottom", ha="right", color="0.3")
    labels = [f"{label}\n({n} events)" for label, n in zip(labels, table["events"])]
    ax.set_xticks(x, labels, fontsize=7)
    ax.set_ylabel("mean |stake - Kelly stake|")
    ax.set_ylim(0, 1.25 * max(table["size_err_true"].max(), oracle["size_err_true"].max() if oracle is not None else 0))
    ax.legend(fontsize=7, frameon=False, ncol=2, loc="upper left")
    ax.set_title("Sizing error by structure (share of bankroll)", fontsize=9)
    return fig


def fig_wealth(paths: pd.DataFrame):
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(7, 3.8))
    groups = list(paths.groupby(["model", "structure"]))
    for i, ((model, structure), g) in enumerate(groups):
        style = "--" if model == "oracle" else "-"
        for j, (_, s) in enumerate(g.groupby("seed")):
            ax.plot(s["index"], s["log_wealth"], style, color=common.color(i), lw=1, alpha=0.8,
                    label=f"{STRUCTURE_NAMES.get(structure, structure)} ({model})" if j == 0 else None)
    ax.axhline(np.log(0.01), color="0.5", lw=0.8, ls=":")
    ax.text(0, np.log(0.01), " ruin (1% of the start)", fontsize=7, va="bottom", color="0.4")
    ax.set_xlabel("event in the sequence")
    ax.set_ylabel("log wealth (start = 0)")
    ax.legend(fontsize=6, frameon=False, ncol=2)
    ax.set_title("Wealth paths, one line per sequence", fontsize=9)
    return fig


def fig_salience(twin: pd.DataFrame, unpaired: pd.DataFrame):
    """Left: the paired effect on the trader (same event with and without its item). Right: the unpaired
    effect on each structure's stake (events with an item minus events without)."""
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, 2, figsize=(8.5, 3.3))
    panels = [(axes[0], twin, lambda r: f"{r['measure']} ({r['model']})", "paired, trader (S1): with item minus without"),
              (axes[1], unpaired[unpaired["measure"] == "stake"],
               lambda r: f"{STRUCTURE_NAMES.get(r['structure'], r['structure'])} ({r['model']})",
               "unpaired, stake: events with an item minus without")]
    for ax, part, label, title in panels:
        part = part.reset_index(drop=True)
        y = np.arange(len(part))
        if len(part):
            ax.errorbar(part["effect"], y, xerr=[part["effect"] - part["lo"], part["hi"] - part["effect"]], fmt="o",
                        color=common.color(4), capsize=3)
        ax.axvline(0, color="0.6", lw=0.8)
        ax.set_yticks(y, [label(r) for _, r in part.iterrows()], fontsize=6.5)
        ax.set_title(title, fontsize=8)
    fig.tight_layout()
    return fig


def build(runs: list[str], block: str, results_dir: Path = RESULTS, out: Path = REPORT) -> dict[str, pd.DataFrame]:
    events, df = load(runs, block, results_dir)
    tables = {"structures": structure_table(df), "versus_solo": versus_solo(df), "salience": salience_table(df),
              "twin": twin_table(df), "twin_details": twin_details(df), "kelly_share": kelly_share(df),
              "oracle": oracle_table(events), "calibration": calibration_curve(df),
              "anchoring": anchoring(df), "tune_checks": tune_checks(df),
              "flips": flip_rates(load_calls(runs, block, results_dir), events)}
    for name, table in tables.items():
        common.save_table(table.round(5), f"desk_{block}_{name}", out / "tables")
    paths = wealth_paths(df, events)
    figures = {"calibration": fig_calibration(tables["calibration"]), "sizing": fig_sizing(tables["structures"], tables["oracle"]),
               "wealth": fig_wealth(paths), "salience": fig_salience(tables["twin"], tables["salience"])}
    for name, fig in figures.items():
        common.save_figure(fig, f"desk_{block}_{name}", out / "figures")
    return tables


def decision_lines(tables: dict[str, pd.DataFrame]) -> list[str]:
    """The plan's decision rules (research/v3/plan_w2.md), read from the judging block's tables.
    Rule 1, recommended design: sizing error against Kelly at the true p at most 2/3 of S1's; log growth
    not worse than S1's by more than NONINFERIORITY (lower end of the 95% interval of the difference);
    and better than staying out (sizing error below the stay-out benchmark's, log growth above 0).
    Rule 2, salience (paired twin calls on S1): 2a the item raises the stake, 2b it pulls the stake toward
    its side, each when the 95% interval is above 0."""
    lines = []
    structures = tables["structures"].set_index(["model", "structure"])
    stay_out = tables["oracle"].set_index("benchmark").loc["stay out", "size_err_true"]
    s1_events = tables["versus_solo"].set_index(["model", "structure"])["events"]
    for _, r in tables["versus_solo"].iterrows():
        if r["structure"] == "S1":
            continue
        if r["events"] < s1_events.get((r["model"], "S1"), 0):  # S4 on sequence 101 only (plan_w2.md, tuning rule)
            lines.append(f"{r['model']} {r['structure']}: descriptive on {r['events']} events only "
                         f"(sizing error {r['size_err_ratio']:.2f}x S1's on the same events); not judged under rule 1")
            continue
        own = structures.loc[(r["model"], r["structure"])]
        checks = {"cuts sizing error by a third": r["size_err_ratio"] <= 2 / 3,
                  "log growth non-inferior": r["diff_lo"] > -NONINFERIORITY,
                  "beats staying out": own["size_err_true"] < stay_out and own["log_growth"] > 0}
        failed = [name for name, ok in checks.items() if not ok]
        lines.append(f"{r['model']} {r['structure']}: sizing error {r['size_err_ratio']:.2f}x S1's "
                     f"({r['ratio_lo']:.2f} to {r['ratio_hi']:.2f}), closing {r['gap_closed']:.0%} of the gap to half Kelly "
                     f"at the true p; log growth {r['log_growth_diff']:+.4f} per event "
                     f"({r['diff_lo']:+.4f} to {r['diff_hi']:+.4f}) -> "
                     + ("meets the recommended-design rule" if not failed else "does not meet the rule: " + ", ".join(failed)))
    twin = tables["twin"]
    readings = {"stake": ("consistent with the item raising conviction (2a)",
                          "consistent with the item lowering conviction (a prediction 7 miss)",
                          "no evidence that the item changes the stake (2a)"),
                "stake_pull": ("consistent with the item pulling the stake toward its side (2b)",
                               "consistent with the item pushing the stake away from its side (a prediction 7 miss)",
                               "no evidence that the item pulls the stake (2b)")}
    for measure, (above, below, neither) in readings.items():
        for _, r in twin[twin["measure"] == measure].iterrows():
            reading = above if r["lo"] > 0 else below if r["hi"] < 0 else neither
            lines.append(f"{r['model']} S1 paired, {measure}: {r['effect']:+.4f} ({r['lo']:+.4f} to {r['hi']:+.4f}) over "
                         f"{r['pairs']} events -> {reading}")
    return lines


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--runs", nargs="+", required=True)
    p.add_argument("--block", choices=list(BLOCKS), required=True)
    args = p.parse_args()
    common.style()
    tables = build(args.runs, args.block)
    pd.set_option("display.width", 220)
    print(tables["structures"].round(4).to_string(index=False))
    print(tables["versus_solo"].round(4).to_string(index=False))
    print(tables["salience"].round(4).to_string(index=False))
    print(tables["oracle"].round(4).to_string(index=False))
    print(tables["anchoring"].round(4).to_string(index=False))
    print(tables["twin"].round(4).to_string(index=False))
    print(tables["tune_checks"].to_string(index=False))
    print(tables["flips"].round(4).to_string(index=False))
    print("\n".join(decision_lines(tables)))


if __name__ == "__main__":
    main()

