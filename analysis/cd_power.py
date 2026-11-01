"""Power of study CD's tests CD1 and CD2 by simulation (session E6, section 4.4), before the CD items are sealed. $0.

The simulated study, in plain words: each item of a family has a difficulty b (standard normal). Each arm answers an
item right with probability sigmoid(a - beta * b) per call, independently given the item (beta is how strongly
difficulty is shared across arms: the Atlas's systematic share of 0.6-0.7 at beta 1.5); `a` is set so the arm's
accuracy in that family is the planning value below. A wrong call gives the item's "attractive" wrong answer with
probability ATTRACT, else one of 8 others, so wrong votes coincide. Dollars per call are planning values (only their
ratio matters, for CD2's k). The frozen tests (analysis/cd_read.py cd1, cd2) run on each simulated study.

Planning accuracies come from E5's anchor read (research/v4/anchor/read.md): BBEH Sonnet off 0.50, Sol low 0.61;
math Sonnet off 0.23, Sol low 0.35; Haiku off 0.39 and 0.11, Haiku high 0.46 on BBEH. Code has no project data;
its values (Sonnet off 0.45, Sol low 0.65) are a guess, varied below. Sonnet max = Sonnet off + R_true x the gap.
Haiku xhigh = Haiku high + 1 point; Haiku max = Haiku xhigh + delta, the depth effect for CD2.

Usage: python -m analysis.cd_power    # writes research/v4/cd/power.md and power.csv
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import cd_read as R
from autoagentnet.atlas import factor as F
from autoagentnet.ladder.core import markdown_table
from autoagentnet.pruning.replay import Panel

OUT = Path(__file__).resolve().parents[1] / "research/v4/cd"
ATTRACT, SIMS, ALPHA = 0.5, 400, 0.025  # ALPHA: Holm's first step over two tests (the strictest a test can face)
PLAN = {  # family: planning accuracy per arm (one call)
    "bbeh": {"sonnet_off": 0.50, "sol_low": 0.61, "haiku_xhigh": 0.47},
    "math": {"sonnet_off": 0.23, "sol_low": 0.35, "haiku_xhigh": 0.17},
    "code": {"sonnet_off": 0.45, "sol_low": 0.65, "haiku_xhigh": 0.40},
}
SIZES = {"core": {"bbeh": 57, "math": 60, "code": 50}, "core+reserve": {"bbeh": 57, "math": 143, "code": 65},
         "all": {"bbeh": 57, "math": 143, "code": 232}}


def intercept(p: float, beta: float) -> float:
    """The a with mean over b ~ N(0, 1) of sigmoid(a - beta b) equal to p (b on a fine quantile grid)."""
    b = np.quantile(np.random.default_rng(0).standard_normal(20001), np.linspace(0.0005, 0.9995, 400))
    lo, hi = -15.0, 15.0
    for _ in range(60):
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if F.sigmoid(mid - beta * b).mean() < p else (lo, mid)
    return (lo + hi) / 2


def simulate(sizes: dict, arms_of: dict, beta: float, rng) -> tuple[Panel, np.ndarray]:
    """A Panel of every arm's calls on every family's items; arms_of: family -> {arm: (accuracy, calls, dollars)}."""
    blocks, families = [], []
    arm_names = list(next(iter(arms_of.values())))
    for fam, n in sizes.items():
        b = rng.standard_normal(n)
        cols = []
        for arm in arm_names:
            p, calls, usd = arms_of[fam][arm]
            a = intercept(min(max(p, 0.005), 0.995), beta)
            for _ in range(calls):
                right = rng.random(n) < F.sigmoid(a - beta * b)
                wrong = np.where(rng.random(n) < ATTRACT, 1, rng.integers(2, 10, n))
                cols.append((np.where(right, 0, wrong), np.full(n, usd)))
        blocks.append(cols)
        families += [fam] * n
    answers = np.vstack([np.column_stack([c[0] for c in cols]) for cols in blocks])
    cost = np.vstack([np.column_stack([c[1] for c in cols]) for cols in blocks])
    sources, calls = [], []
    for arm in arm_names:
        for c in range(arms_of[next(iter(arms_of))][arm][1]):
            sources.append(f"{arm}:base")
            calls.append(c)
    panel = Panel.from_arrays(answers, (answers == 0).astype(float), cost, sources=sources, calls=calls,
                              items=[f"x{i:04d}" for i in range(len(families))])
    return panel, np.array(families)


def units(arm: str, calls: int) -> list[str]:
    return [f"{arm}:base:{c}" for c in range(calls)]


def scenario(sizes: dict, r_true: float, delta: float, beta: float, max_cost_ratio: float, code_gap: float,
             sims: int = SIMS, seed: int = 0) -> dict:
    """Power of CD1 and CD2 (share of simulated studies with p <= ALPHA, and at 0.05) in one scenario."""
    rng = np.random.default_rng(seed)
    arms_of = {}
    for fam, plan in PLAN.items():
        off, sol = plan["sonnet_off"], plan["sol_low"]
        if fam == "code":
            sol = off + code_gap
        xh = plan["haiku_xhigh"]
        arms_of[fam] = {"sonnet_off": (off, 1, 0.01), "sonnet_max": (off + r_true * (sol - off), 1, 0.05),
                        "sol_low": (sol, 1, 0.01), "haiku_xhigh": (xh, 5, 0.004),
                        "haiku_max": (xh + delta, 1, 0.004 * max_cost_ratio)}
    p1, p2, est1, k2 = [], [], [], []
    for _ in range(sims):
        panel, fams = simulate(sizes, arms_of, beta, rng)
        a = R.cd1(panel, fams, units("sonnet_off", 1), units("sonnet_max", 1), units("sol_low", 1))
        b = R.cd2(panel, fams, units("haiku_max", 1), units("haiku_xhigh", 5))
        p1.append(np.nan if a["void"] else a["p"])
        est1.append(a["estimate"])
        p2.append(b["p"])
        k2.append(b["k"])
    p1, p2 = np.array(p1), np.array(p2)
    return {"items": sum(sizes.values()), "R_true": r_true, "delta": delta, "beta": beta,
            "max_cost_ratio": max_cost_ratio, "code_gap": code_gap, "k": int(np.median(k2)),
            "power_CD1": float(np.mean(np.nan_to_num(p1, nan=1.0) <= ALPHA)),
            "power_CD1_at_05": float(np.mean(np.nan_to_num(p1, nan=1.0) <= 0.05)),
            "void_CD1": float(np.mean(np.isnan(p1))), "R_median": float(np.median(est1)),
            "power_CD2": float(np.mean(p2 <= ALPHA)), "power_CD2_at_05": float(np.mean(p2 <= 0.05))}


SCENARIOS = [  # (size name, R_true, delta, beta, max cost / xhigh cost, code gap)
    ("core", 1.0, 0.04, 1.5, 1.0, 0.20), ("core", 1.0, 0.04, 1.5, 3.0, 0.20),
    ("core", 0.75, 0.02, 1.5, 1.0, 0.20), ("core", 1.25, 0.06, 1.5, 1.0, 0.20),
    ("core", 1.0, 0.04, 1.0, 1.0, 0.20), ("core", 1.0, 0.04, 2.0, 1.0, 0.20),
    ("core", 1.0, 0.04, 1.5, 1.0, 0.10), ("core", 1.0, 0.04, 1.5, 1.0, 0.30),
    ("core+reserve", 1.0, 0.04, 1.5, 1.0, 0.20), ("core+reserve", 0.75, 0.02, 1.5, 1.0, 0.20),
    ("core+reserve", 1.25, 0.06, 1.5, 1.0, 0.20), ("core+reserve", 1.0, 0.04, 1.5, 3.0, 0.20),
    ("all", 1.0, 0.04, 1.5, 1.0, 0.20), ("all", 0.75, 0.02, 1.5, 1.0, 0.20), ("all", 1.0, 0.04, 1.5, 3.0, 0.20),
]


DECIDING = {"r_true": 1.0, "delta": 0.04, "beta": 1.5, "code_gap": 0.20}  # the scenario whose power decides the
# demotion (fixed before the probe): reasoning closes the whole gap (R = 1, the threshold is 0.5); one effort step adds
# 4 points (E5: Haiku's effort steps added 3.4-3.8 on BBEH); the Atlas's systematic share; code's gap a guess


def planned(sizes: dict, max_cost_ratio: float, sims: int = SIMS) -> dict:
    """Power of CD1 and CD2 at the planned item counts (research/v4/cd/plan.json: CD1's items are the core plus the
    added items; CD2's the same) and the probe's ratio of one Haiku max call to one Haiku xhigh call. A test whose power
    here is under 0.70 is exploratory (brief 4.4)."""
    return scenario(sizes, DECIDING["r_true"], DECIDING["delta"], DECIDING["beta"], max_cost_ratio,
                    DECIDING["code_gap"], sims=sims, seed=99)


def main(sims: int = SIMS) -> pd.DataFrame:
    rows = []
    for k, (size, r_true, delta, beta, ratio, gap) in enumerate(SCENARIOS):
        row = scenario(SIZES[size], r_true, delta, beta, ratio, gap, sims=sims, seed=k)
        rows.append({"sizes": size, **row})
        print(rows[-1], flush=True)
    table = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    table.to_csv(OUT / "power.csv", index=False)
    lines = ["# Study CD: power by simulation (section 4.4)", "",
             f"Written by `python -m analysis.cd_power` ({sims} simulated studies per row; frozen tests in",
             f"analysis/cd_read.py; a test passes at p <= {ALPHA}, Holm's first step over two tests; the 0.05 column is",
             "the second step). Model and planning values: the module docstring.", "",
             markdown_table(table.round(3)), ""]
    (OUT / "power.md").write_text("\n".join(lines))
    return table


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else SIMS)
