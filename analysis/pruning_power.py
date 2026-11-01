"""Phase 3C of the evidence plan: power of the lockbox tests P1-P3 by simulation, before sealing ($0).
Writes research/v3/pruning/power.md.

The tests (BBEH, 200 lockbox items; the networks are frozen by analysis/pruning_select.py on the 200 Phase 2
items and applied to the lockbox without refitting):
  P1  selected static network minus Sonnet, accuracy, is above -5 points (non-inferiority).
  P2  selected static network minus the dense refit (all 18 calls), above -3 points.
  P3  selected dynamic policy minus the selected static network, above -3 points; its cost ratio is reported.
Each is a one-sided item-bootstrap p-value (DRAWS draws) for "the mean paired difference is at or below the
margin"; Holm at 5% over the three.

The simulated panel (plain words first). Each item has a latent difficulty per source: Haiku, Luna, Sonnet and Sol
as in analysis/evidence_power.py (accuracy 0.48 / 0.48 / 0.71 / 0.71, repeat correlation 0.48 / 0.48 / 0.50 /
0.50, cross-vendor same-tier latent r the scenario), plus one latent per persona call whose correlation with its
model's base latent is w_persona (0.85 in the base case, as for H11). A call is right with chance
Phi(a + b z); a wrong call gives the item's attractor answer with probability 0.6, else one of three others.
Calls cost the plan's dollars per call. A study simulates a search set and a lockbox of 200 items each, runs the
whole Phase 3B rule on the search set (analysis/pruning_select.select, exactly as committed), applies the
frozen networks to the lockbox and runs P1-P3. Both versions of the rule Kevin is choosing between are simulated:
option (a), his rule as written (no cost bound), and option (b), selected networks at most 0.8x Sonnet's dollars.

Two power numbers per test:
  pass rate      the share of studies whose p-value clears the threshold, under the model: the model's own
                 expected difference counts. A low pass rate can mean the model expects the hypothesis to be false.
  power at 0     the chance of clearing the threshold if the true difference were exactly 0, from each study's
                 bootstrap standard error: mean over studies of Phi(-margin / SE - z_threshold) (margin is
                 negative, so -margin / SE is the margin's distance from 0 in standard errors). This is the usual
                 non-inferiority power and the number the 70% rule is applied to (at the Holm floor, base case).
  void           a study where the selection makes the test void (no static network; the static network is
                 Sonnet alone, so P1 would compare Sonnet with itself; no dynamic policy). Void studies are left
                 out of that test's power and counted in its void rate: a void test is never a free pass.

Usage: python -m analysis.pruning_power      # about 45 minutes
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from analysis.evidence_power import PARAMS, USD, latent_corr
from analysis.pruning_select import PERSONAS, apply_frozen, lockbox_units, select
from autoagentnet.pruning.replay import Panel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v3/pruning/power.md"
ALPHA, FAMILY, DRAWS = 0.05, 3, 1000
MARGINS = {"P1": -0.05, "P2": -0.03, "P3": -0.03}
BASE = {"r_cross": 0.6, "w_persona": 0.85}
SCENARIOS = [BASE, {"r_cross": 0.3, "w_persona": 0.85}, {"r_cross": 0.8, "w_persona": 0.85}, {"r_cross": 0.6, "w_persona": 1.0}]
OPTIONS = {"(a) as written": None, "(b) <= 0.8x Sonnet": 0.8}
MODEL = {"haiku_nothink": "haiku", "luna_none": "luna", "sonnet_nothink": "sonnet", "sol61_low": "sol"}
ORDER = ["haiku", "luna", "sonnet", "sol"]


def simulate(n: int, r_cross: float, w_persona: float, rng) -> Panel:
    """An 18-unit lockbox-shaped panel on n simulated BBEH items."""
    z = rng.multivariate_normal(np.zeros(4), latent_corr(r_cross), size=n)
    units = lockbox_units()
    answers, right, cost = [], [], []
    for unit in units:
        ref, prompt, _ = unit.split(":")
        s = MODEL[ref]
        latent = z[:, ORDER.index(s)]
        if prompt in PERSONAS:
            latent = w_persona * latent + np.sqrt(1 - w_persona ** 2) * rng.standard_normal(n)
        a, b = PARAMS[s]
        ok = rng.random(n) < norm.cdf(a + b * latent)
        wrong = np.where(rng.random(n) < 0.6, 1, rng.integers(2, 5, n))
        answers.append(np.where(ok, 0, wrong))
        right.append(ok.astype(float))
        cost.append(np.full(n, USD[s]))
    sources = [u.rsplit(":", 1)[0] for u in units]
    calls = [int(u.rsplit(":", 1)[1]) for u in units]
    return Panel.from_arrays(np.column_stack(answers), np.column_stack(right), np.column_stack(cost),
                             sources=sources, calls=calls)


def one_sided(d: np.ndarray, margin: float, rng) -> tuple[float, float]:
    """(p-value for "mean d <= margin", bootstrap standard error of mean d)."""
    idx = rng.integers(0, len(d), (DRAWS, len(d)))
    means = d[idx].mean(axis=1)
    return float((means <= margin).mean()), float(means.std())


def study(n: int, scenario: dict, rng, cost_bound: float | None = None) -> dict:
    search = simulate(n, scenario["r_cross"], scenario["w_persona"], rng)
    lockbox = simulate(n, scenario["r_cross"], scenario["w_persona"], rng)
    sel = select(search, "bbeh", cost_bound=cost_bound)
    t = apply_frozen(lockbox, sel)
    static = sel["static"]
    diffs = {"P1": t["static_score"] - t["sonnet_score"], "P2": t["static_score"] - t["dense_score"],
             "P3": t["dynamic_score"] - t["static_score"]}
    units = static["units"] if static else []
    out = {"static_none": static is None, "static_units": len(units),
           "static_single_mid": units in (["sonnet_nothink:base:0"], ["sol61_low:base:0"]),
           "static_has_mid": any(u.startswith(("sonnet", "sol")) for u in units),
           "static_dollars": t["static_dollars"].mean(), "dynamic_dollars": t["dynamic_dollars"].mean(),
           "sonnet_dollars": t["sonnet_dollars"].mean(), "tau": sel["dynamic"]["tau"] if sel["dynamic"] else np.nan}
    for k, d in diffs.items():
        out[f"{k}_void"] = k in sel["void"]
        if out[f"{k}_void"]:
            out[f"{k}_diff"], out[f"{k}_p"], out[f"{k}_se"] = np.nan, np.nan, np.nan
            continue
        p, se = one_sided(d.to_numpy(), MARGINS[k], rng)
        out[f"{k}_diff"], out[f"{k}_p"], out[f"{k}_se"] = float(d.mean()), p, se
    return out


def label(scenario: dict, option: str) -> str:
    return f"{option}; cross-vendor r {scenario['r_cross']}, persona r {scenario['w_persona']}"


def summarize(sims: pd.DataFrame, scenario: dict, option: str) -> list[dict]:
    rows = []
    z_floor, z_alpha = norm.ppf(1 - ALPHA / FAMILY), norm.ppf(1 - ALPHA)
    for k, margin in MARGINS.items():
        live = sims[~sims[f"{k}_void"].astype(bool)]
        se = live[f"{k}_se"].clip(lower=1e-6)
        rows.append({"test": k, "scenario": label(scenario, option),
                     "studies": len(sims), "void rate": float(sims[f"{k}_void"].mean()),
                     "mean difference (points)": 100 * live[f"{k}_diff"].mean() if len(live) else np.nan,
                     "pass rate at Holm floor": float((live[f"{k}_p"] < ALPHA / FAMILY).mean()) if len(live) else np.nan,
                     "pass rate at alpha": float((live[f"{k}_p"] < ALPHA).mean()) if len(live) else np.nan,
                     "power at 0, Holm floor": float(norm.cdf(-margin / se - z_floor).mean()) if len(live) else np.nan,
                     "power at 0, alpha": float(norm.cdf(-margin / se - z_alpha).mean()) if len(live) else np.nan})
    return rows


def main(reps: int = 100, n: int = 200) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows, extra = [], []
    for option, bound in OPTIONS.items():
        for k, scenario in enumerate(SCENARIOS):
            sims = pd.DataFrame([study(n, scenario, rng, bound) for _ in range(reps if k == 0 else max(reps * 2 // 5, 20))])
            rows += summarize(sims, scenario, option)
            extra.append(picks(sims, scenario, option))
    table = pd.DataFrame(rows)
    write(table, pd.DataFrame(extra), reps, n)
    return table


def picks(sims: pd.DataFrame, scenario: dict, option: str) -> dict:
    return {"scenario": label(scenario, option),
                      "static has Sonnet or Sol": float(sims["static_has_mid"].mean()),
                      "no static network": float(sims["static_none"].mean()),
                      "static is one Sonnet or Sol call": float(sims["static_single_mid"].mean()),
                      "static costs more than Sonnet": float((sims["static_dollars"] > sims["sonnet_dollars"] + 1e-12).mean()),
                      "static calls": float(sims["static_units"].mean()),
                      "static $ / Sonnet $": float((sims["static_dollars"] / sims["sonnet_dollars"]).mean()),
                      "dynamic $ / Sonnet $": float((sims["dynamic_dollars"] / sims["sonnet_dollars"]).mean()),
                      "median tau": float(sims["tau"].median())}


def decision(table: pd.DataFrame, option: str) -> tuple[list, list]:
    """(kept, demoted) by the 70% rule: power at 0 at the Holm floor, base case, under one rule option."""
    base = table[table["scenario"] == label(BASE, option)]
    keep = base[base["power at 0, Holm floor"] >= 0.70]["test"].tolist()  # NaN (always void) is not kept
    return keep, [t for t in base["test"] if t not in keep]


def write(table: pd.DataFrame, picks: pd.DataFrame, reps: int, n: int) -> None:
    def fmt(frame):
        cols = list(frame.columns)
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in frame.itertuples(index=False):
            lines.append("| " + " | ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in r) + " |")
        return "\n".join(lines)

    lines = ["# Phase 3C: power of the lockbox tests P1-P3 by simulation", "",
             f"Written by `python -m analysis.pruning_power` ({reps} simulated studies per rule option in the base case, "
             f"{max(reps * 2 // 5, 20)} in the others; {n} search and {n} lockbox items each; {DRAWS} bootstrap draws; "
             "seed 0). The model, the tests, the two power numbers and the void rule are defined in the script's "
             f"docstring. The Holm floor is alpha / 3 = {ALPHA / FAMILY:.4f}. Rule options: (a) Kevin's rule as written; "
             "(b) the same with selected networks at most 0.8x Sonnet's dollars (research/v3/pruning/selection_rule.md).", "",
             fmt(table), "",
             "A void test is left out of its power and counted in its void rate: the void rate is how often the rule "
             "leaves nothing to test, and the power is for the studies where it does.", "",
             "What the selection rule picked in the simulated studies:", "",
             fmt(picks), "",
             "## Decision (the plan's 70% rule: power at 0 at the Holm floor, base case)", ""]
    for option in OPTIONS:
        keep, demote = decision(table, option)
        lines.append(f"- Rule {option}: confirmatory {', '.join(keep) if keep else 'none'}; exploratory "
                     f"{', '.join(demote) if demote else 'none'} (reported with intervals and one-sided p-values).")
    lines += ["", "The lockbox preregs (e31_lockbox_*) carry the decision for the rule in force "
              "(analysis/pruning_select.COST_BOUND; analysis/pruning_lockbox.STATUS)."]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    import sys

    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
