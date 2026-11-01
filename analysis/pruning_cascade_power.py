"""Phase 3C (cascades): power of the lockbox tests C1 and C2 by simulation, before the selection is frozen ($0).
Writes research/v3/pruning/power_cascade.md.

The tests (analysis/pruning_cascade.py): C1, the frozen cascade policy minus Sonnet in accuracy, above -5 points
(non-inferiority); C2, the frozen mixed-vendor first round's acceptance minus Haiku x5's, above 0; and, exploratory
(offered to Kevin as a confirmatory alternative, audit 52), C1b: the policy minus its own escalation model alone,
above -5 points. Each is a
one-sided item-bootstrap p-value; Holm at 5% over the two, so the Holm floor is 0.025.

The simulated panel (plain words first) is the evidence plan's model (analysis/evidence_power.py): each item has a
latent difficulty per source (Haiku, Luna, Sonnet, Sol; standard normal, correlated across sources), a call is
right with chance Phi(a + b z) where a and b match the source's accuracy p and repeat correlation rho, and a wrong
call gives the item's attractor answer with probability 0.6, else one of three other wrong answers. Persona calls
use a latent mixed from their model's base latent with weight w_persona = 0.85 (as for H11). Accuracies: Haiku 0.48,
Sonnet 0.71 and Sol 0.71 (the plan's), Luna 0.48 in the base case; rho 0.48 / 0.48 / 0.50 / 0.50. The cross-vendor
same-tier latent r (Haiku-Luna, Sonnet-Sol) is the scenario: 0.3, 0.6 (base) or 0.8. A further scenario sets Luna's
accuracy to 0.30: the probe found that Luna at reasoning none answers BBEH without working, so it may be far less
accurate than Haiku. Calls cost the probe's measured dollars (EST in scripts/make_evidence_configs.py).

A study simulates a search set (300 items; the persona rounds use its first 200, as the real search data does)
and a lockbox of N items, runs the whole selection rule (analysis/pruning_cascade.select, as committed), applies
the frozen policy and the C2 pair to the lockbox and computes both p-values.

Two power numbers per test:
  pass rate      the share of studies whose p-value clears the threshold, under the model's own expected
                 difference.
  power at 0     (C1 only) the chance of clearing the threshold if the true difference were exactly 0, from each
                 study's bootstrap standard error: Phi(-margin / SE - z_threshold), averaged. The usual
                 non-inferiority power; the 70% rule is applied to it for C1 and to the pass rate for C2 (a
                 superiority test has no "difference 0" case), at the Holm floor in the base scenario.
  void           a study where nothing qualifies (C1 and C2 void): left out of the power, counted in the void rate.

Usage: python -m analysis.pruning_cascade_power [reps]     # about 20 minutes at 100 reps
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import norm

from analysis.evidence_power import PARAMS, RHO, chance_params, latent_corr
from analysis.pruning_cascade import C1_MARGIN, ESCALATIONS, FIRST_ROUNDS, SONNET, accepted_by, apply_policy, select
from autoagentnet.pruning import cascade as C
from autoagentnet.pruning.replay import Panel

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v3/pruning/power_cascade.md"
ALPHA, FAMILY, DRAWS = 0.05, 2, 1000
USD = {"haiku": 0.00080, "luna": 0.00017, "sonnet": 0.0136, "sol": 0.0062}  # the probe's measured BBEH costs
MODEL = {"haiku_nothink": "haiku", "luna_none": "luna", "sonnet_nothink": "sonnet", "sol61_low": "sol"}
ORDER = ["haiku", "luna", "sonnet", "sol"]
UNITS = sorted({u for units in FIRST_ROUNDS.values() for u in units} | set(ESCALATIONS.values()))
BASE = {"r_cross": 0.6, "w_persona": 0.85, "p_luna": 0.48}
SCENARIOS = [BASE, {**BASE, "r_cross": 0.3}, {**BASE, "r_cross": 0.8}, {**BASE, "p_luna": 0.30}]
SIZES = [200, 300, 400]


def simulate(n: int, scenario: dict, rng) -> Panel:
    """A panel of every first-round and escalation unit on n simulated BBEH items (tasks "t0"-"t3")."""
    z = rng.multivariate_normal(np.zeros(4), latent_corr(scenario["r_cross"]), size=n)
    params = {**PARAMS, "luna": chance_params(scenario["p_luna"], RHO["luna"])}
    answers, right, cost = [], [], []
    for unit in UNITS:
        ref, prompt, _ = unit.split(":")
        s = MODEL[ref]
        latent = z[:, ORDER.index(s)]
        if prompt != "base":
            w = scenario["w_persona"]
            latent = w * latent + np.sqrt(1 - w ** 2) * rng.standard_normal(n)
        a, b = params[s]
        ok = rng.random(n) < norm.cdf(a + b * latent)
        wrong = np.where(rng.random(n) < 0.6, 1, rng.integers(2, 5, n))
        answers.append(np.where(ok, 0, wrong))
        right.append(ok.astype(float))
        cost.append(np.full(n, USD[s]))
    return Panel.from_arrays(np.column_stack(answers), np.column_stack(right), np.column_stack(cost),
                             sources=[u.rsplit(":", 1)[0] for u in UNITS], calls=[int(u.rsplit(":", 1)[1]) for u in UNITS],
                             items=[f"bbeh-t{i % 4}-{i:04d}" for i in range(n)])


def one_sided(d: np.ndarray, margin: float, rng) -> tuple[float, float]:
    """(p-value for "mean d <= margin", bootstrap standard error of mean d)."""
    idx = rng.integers(0, len(d), (DRAWS, len(d)))
    means = d[idx].mean(axis=1)
    return float((means <= margin).mean()), float(means.std())


def study(scenario: dict, n_lock: int, rng) -> dict:
    search = simulate(300, scenario, rng)
    panels = {"base": search, "persona": search.subset(np.arange(200))}
    sel = select(panels)
    lock = simulate(n_lock, scenario, rng)
    out = {"void": sel["policy"] is None}
    if out["void"]:
        return out
    pol = sel["policy"]
    res = apply_policy(lock, pol)
    g = C.unit_positions(lock, [SONNET])[0]
    d1 = res["correct"].to_numpy() - lock.correct_matrix()[:, g]
    d2 = accepted_by(lock, sel["c2"]["mixed"]) - accepted_by(lock, sel["c2"]["haiku x5"])
    e = C.unit_positions(lock, [pol["escalation"]])[0]
    d1b = res["correct"].to_numpy() - lock.correct_matrix()[:, e]  # C1b: the policy against its own escalation model
    (p1, se1), (p2, _), (p1b, se1b) = one_sided(d1, C1_MARGIN, rng), one_sided(d2, 0.0, rng), one_sided(d1b, C1_MARGIN, rng)
    return {**out, "first round": pol["first round"], "escalation": pol["escalation"].split("_")[0],
            "mixed": sel["c2"]["mixed"]["first round"], "C1 diff": float(d1.mean()), "C1 p": p1, "C1 se": se1,
            "C1b diff": float(d1b.mean()), "C1b p": p1b, "C1b se": se1b,
            "C2 diff": float(d2.mean()), "C2 p": p2, "dollar ratio": float(res["dollars"].mean() / lock.cost[:, g].mean()),
            "acceptance": float(res["accepted"].mean()), "accepted wrong": float(res["accepted_wrong"].mean())}


def summarize(sims: pd.DataFrame, scenario: dict, n_lock: int) -> dict:
    live = sims[~sims["void"].astype(bool)]
    floor, z_floor = ALPHA / FAMILY, norm.ppf(1 - ALPHA / FAMILY)
    se = live["C1 se"].clip(lower=1e-6) if len(live) else pd.Series(dtype=float)
    row = {"cross-vendor r": scenario["r_cross"], "Luna accuracy": scenario["p_luna"], "lockbox items": n_lock,
           "studies": len(sims), "void rate": float(sims["void"].mean())}
    if len(live):
        row.update({"C1 mean diff (pts)": 100 * live["C1 diff"].mean(),
                    "C1 pass rate, floor": float((live["C1 p"] < floor).mean()),
                    "C1 power at 0, floor": float(norm.cdf(-C1_MARGIN / se - z_floor).mean()),
                    "C1b mean diff (pts)": 100 * live["C1b diff"].mean(),
                    "C1b power at 0, floor": float(norm.cdf(-C1_MARGIN / live["C1b se"].clip(lower=1e-6) - z_floor).mean()),
                    "C2 mean diff (pts)": 100 * live["C2 diff"].mean(),
                    "C2 pass rate, floor": float((live["C2 p"] < floor).mean()),
                    "dollar ratio": live["dollar ratio"].mean(), "acceptance": live["acceptance"].mean(),
                    "accepted wrong": live["accepted wrong"].mean()})
    return row


def picks(sims: pd.DataFrame, scenario: dict) -> pd.DataFrame:
    live = sims[~sims["void"].astype(bool)]
    table = live.groupby(["first round", "escalation"]).size().rename("studies").reset_index()
    return table.assign(scenario=f"r {scenario['r_cross']}, Luna {scenario['p_luna']}").sort_values("studies", ascending=False)


def main(reps: int = 100) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows, chosen = [], []
    for k, scenario in enumerate(SCENARIOS):
        for n_lock in SIZES if k == 0 else [200, 300]:
            sims = pd.DataFrame([study(scenario, n_lock, rng) for _ in range(reps if k == 0 else max(reps // 2, 20))])
            rows.append(summarize(sims, scenario, n_lock))
            if n_lock == 200:
                chosen.append(picks(sims, scenario))
    table = pd.DataFrame(rows)
    write(table, pd.concat(chosen), reps)
    return table


def decision(table: pd.DataFrame, n_lock: int) -> dict:
    """The 70% rule in the base scenario at the Holm floor: C1 on its power at 0, C2 on its pass rate."""
    base = table[(table["cross-vendor r"] == BASE["r_cross"]) & (table["Luna accuracy"] == BASE["p_luna"])
                 & (table["lockbox items"] == n_lock)].iloc[0]
    return {"C1": "conf" if base.get("C1 power at 0, floor", 0) >= 0.70 else "expl",
            "C2": "conf" if base.get("C2 pass rate, floor", 0) >= 0.70 else "expl"}


def write(table: pd.DataFrame, chosen: pd.DataFrame, reps: int) -> None:
    def fmt(frame):
        cols = list(frame.columns)
        lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        for r in frame.itertuples(index=False):
            lines.append("| " + " | ".join(f"{v:.2f}" if isinstance(v, float) else str(v) for v in r) + " |")
        return "\n".join(lines)

    lines = ["# Phase 3C (cascades): power of C1 and C2 by simulation", "",
             f"Written by `python -m analysis.pruning_cascade_power {reps}` ({reps} studies per lockbox size in the "
             f"base scenario, {max(reps // 2, 20)} in the others; 300 search items; {DRAWS} bootstrap draws; seed 0). "
             f"The model, the tests and the power numbers are defined in the script's docstring. Holm floor: "
             f"{ALPHA / FAMILY:.3f} (two tests).", "", fmt(table), "",
             "What the rule selected (lockbox 200):", "", fmt(chosen[["scenario", "first round", "escalation", "studies"]]), "",
             "## Decision (70% rule, base scenario, Holm floor)", ""]
    for n_lock in SIZES:
        d = decision(table, n_lock)
        lines.append(f"- Lockbox of {n_lock} BBEH items: C1 {d['C1']}, C2 {d['C2']}.")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 100)
