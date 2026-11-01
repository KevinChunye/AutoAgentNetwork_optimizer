"""Power of the anchor's AH1-AH4 by simulation (session E5, step 5.4), run before the anchor items are sealed. $0.

The simulated anchor, in plain words: each item has a difficulty b_i (standard normal). Each arm (model x reasoning
setting) answers with probability sigmoid(a - beta b_i) per call, independently given the item, and when wrong gives
an "attractive" wrong answer with probability `attract` (else one of 8 others), so its wrong calls coincide. A judge
sees the six candidates of two cheap pools; when at least one is right it picks a right one with probability
sigmoid(j0 - j1 b_i) (j1 > 0 means it is worse on hard items: verifier coupling), else it picks a wrong one. Each arm
has a cost per call. The arms' accuracies come from the landscape scan (research/v4/anchor/scan_read.md) and are
passed in as parameters; `power` runs the frozen tests (analysis/anchor_read.py) on many simulated anchors.

Usage: python -m analysis.anchor_power   # writes research/v4/anchor/power.md from the parameters in PARAMS
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import anchor_read as R
from autoagentnet.atlas import factor as F
from autoagentnet.pruning.replay import Panel

ROOT_OUT = "research/v4/anchor/power.md"


def simulate(n: int, arms: dict[str, dict], judge: dict, rng) -> tuple[Panel, dict[str, list[str]], np.ndarray]:
    """A Panel with every arm's calls and one judge call per item; returns (panel, arm -> units, true difficulty)."""
    b = rng.standard_normal(n)
    answers, costs, sources, calls, units = [], [], [], [], {}
    for name, p in arms.items():
        units[name] = []
        own = rng.standard_normal(n) * p.get("sigma", 0.0)  # misspecification: a per-arm item effect (audit 71)
        fixed = rng.random(n) < p.get("w_fixed", 0.0)  # misspecification: items where every wrong call is one attractor
        for c in range(p["calls"]):
            right = rng.random(n) < F.sigmoid(p["a"] - p["beta"] * b + own)
            wrong = np.where(fixed | (rng.random(n) < p["attract"]), 1, rng.integers(2, 10, n))
            answers.append(np.where(right, 0, wrong))
            costs.append(np.full(n, p["usd"]))
            sources.append(f"{name}:base")
            calls.append(c)
            units[name].append(f"{name}:base:{c}")
    pool = np.column_stack([answers[k] for k, s in enumerate(sources)
                            if s.split(":")[0] in judge["pools"]])
    covered = (pool == 0).any(axis=1)
    picks_right = covered & (rng.random(n) < F.sigmoid(judge["j0"] - judge["j1"] * b))
    answers.append(np.where(picks_right, 0, 1))
    costs.append(np.full(n, judge["usd"]))
    sources.append("judge:base")
    calls.append(0)
    A = np.column_stack(answers)
    panel = Panel.from_arrays(A, (A == 0).astype(float), np.column_stack(costs), sources=sources, calls=calls,
                              items=[f"x{i:04d}" for i in range(n)])
    return panel, units, b


def run_tests(panel: Panel, units: dict[str, list[str]], difficulty: np.ndarray | None = None,
              upper_limit: float | None = None, mae_limit: float | None = None,
              gain_limit: float | None = None, gain_upper_limit: float | None = None) -> pd.DataFrame:
    """The four frozen tests on one simulated anchor. AH4's difficulty is fitted from the arms outside the candidate
    pools, as in the read (the true difficulty is not used; the argument is kept for callers that pass it)."""
    pools = ["haiku_off", "luna_low"]
    results = [R.ah1(panel, units["sonnet_off"], units["sonnet_low"], units["sol_low"]),
               R.ah2(panel, units["haiku_low"], units["haiku_off"], units["luna_low"], units["luna_none"]),
               R.ah3(panel, units, upper_limit, mae_limit, gain_limit, gain_upper_limit),
               R.ah4(panel, "judge:base:0", {p: units[p] for p in pools}, R.difficulty_outside(panel, units, pools))]
    return R.family(results)


def ah3_noise_floor(n: int, arms: dict, judge: dict, reps: int = 40, seed: int = 1) -> dict:
    """AH3's MAE and upper bound when the model is true (the simulator is the model): their 90th percentiles, rounded
    up to whole points, are the AH3_MAE and AH3_UPPER the prereg fixes."""
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(reps):
        panel, units, _ = simulate(n, arms, judge, rng)
        r = R.ah3(panel, units)
        rows.append({k: r[k] for k in ("estimate", "upper", "gain_estimate", "gain_upper")})
    f = pd.DataFrame(rows)
    p90 = f.quantile(0.9)
    whole = lambda x: float(np.ceil(100 * x) / 100)  # level limits: whole points
    half = lambda x: float(np.ceil(200 * x) / 200)  # gain limits: half points
    return {"reps": reps, "mae_mean": float(f["estimate"].mean()), "mae_p90": float(p90["estimate"]),
            "upper_p90": float(p90["upper"]), "gain_mean": float(f["gain_estimate"].mean()),
            "gain_p90": float(p90["gain_estimate"]), "gain_upper_p90": float(p90["gain_upper"]),
            "mae_limit": whole(p90["estimate"]), "upper_limit": whole(p90["upper"]),
            "gain_limit": half(p90["gain_estimate"]), "gain_upper_limit": half(p90["gain_upper"])}


AH3_SCENARIOS = {"model true": {}, "per-arm item effect (sd 1.5)": {"sigma": 1.5},
                 "attractors on half the items + per-arm effect (sd 1.5)": {"sigma": 1.5, "w_fixed": 0.5, "attract": 0.1}}


def ah3_power(n: int, limits: dict, reps: int = 30, seed: int = 2, drop: tuple = ()) -> pd.DataFrame:
    """AH3's pass rate (its bound alone) when the model is true and under two misspecifications (audit 71); `drop`
    leaves arms out (audit 74: Haiku effort high has no math cells, so the read's AH3 has 6 three-call arms)."""
    rows = []
    for label, change in AH3_SCENARIOS.items():
        rng = np.random.default_rng(seed)
        arms = {k: {**v, **change} for k, v in arms_for({a: x[0] for a, x in BASE.items()}).items() if k not in drop}
        passed, gains = [], []
        for _ in range(reps):
            panel, units, _ = simulate(n, arms, JUDGE, rng)
            r = R.ah3(panel, units, limits["upper_limit"], limits["mae_limit"], limits["gain_limit"],
                      limits["gain_upper_limit"])
            passed.append(r["passes_bound"])
            gains.append(r["gain_estimate"])
        rows.append({"scenario": label, "reps": reps, "pass_rate": float(np.mean(passed)),
                     "gain_mae_mean": float(np.mean(gains))})
    return pd.DataFrame(rows)


def power(n: int, arms: dict, judge: dict, reps: int = 100, seed: int = 0, upper_limit: float | None = None,
          mae_limit: float | None = None) -> pd.DataFrame:
    """Pass rate of each test under Holm over `reps` simulated anchors of n items."""
    rng = np.random.default_rng(seed)
    out = []
    for _ in range(reps):
        panel, units, b = simulate(n, arms, judge, rng)
        out.append(run_tests(panel, units, b, upper_limit, mae_limit)
                   .assign(passes=lambda t: t["passes"].fillna(False).astype(bool)))
    frame = pd.concat(out)
    return frame.groupby("test").agg(pass_rate=("passes", "mean"), mean_estimate=("estimate", "mean"),
                                     void_rate=("void", "mean")).reset_index()


def a_for(accuracy: float, beta: float = 1.0) -> float:
    """The ability a whose mean accuracy over standard-normal difficulties is `accuracy` (for slope beta)."""
    grid = np.linspace(-6, 6, 2401)
    z = np.random.default_rng(1).standard_normal(20000)
    acc = np.array([F.sigmoid(g - beta * z).mean() for g in grid])
    return float(grid[np.argmin(np.abs(acc - accuracy))])


# The anchor's mix: BBEH items of linguini, nycc, word sorting and causal understanding (n_bbeh in all) and the 93
# arXivMath items. Accuracies and dollars per call are the scans' (research/v4/anchor/scan_read.md, the e52 Sonnet scan;
# parser v1), weighted 200:93 as BBEH:math. Measured: Haiku off, low; Luna low; Sol low; Sonnet off, low (e52). Assumed
# (no scan cell): Luna none, Luna medium, Sol medium, and Haiku high on math (its scan calls truncated at 18,432; the
# anchor doubles the ceiling); named in power.md.
N_MATH = 93
ASSUMED = {"luna_none", "luna_med", "sol_med", "haiku_high (math)"}
BASE = {  # arm: (accuracy on the mix, calls, dollars per call on the mix)
    "haiku_off": (0.32, 3, 0.0004), "haiku_low": (0.40, 3, 0.0007), "haiku_high": (0.48, 3, 0.0030),
    "luna_none": (0.20, 3, 0.0001), "luna_low": (0.28, 3, 0.0004), "luna_med": (0.33, 3, 0.0010),
    "sol_low": (0.69, 3, 0.0060), "sol_med": (0.74, 1, 0.0120),
    "sonnet_off": (0.447, 1, 0.0078), "sonnet_low": (0.532, 1, 0.0079),
}
JUDGE = {"pools": ["haiku_off", "luna_low"], "j0": 1.2, "j1": 0.7, "usd": 0.006}
ATTRACT = 0.5
N_ITEMS = 200 + N_MATH


def arms_for(acc: dict[str, float]) -> dict[str, dict]:
    return {name: {"a": a_for(acc[name]), "beta": 1.0, "calls": BASE[name][1], "usd": BASE[name][2],
                   "attract": ATTRACT} for name in BASE}


def scenarios() -> list[tuple[str, dict, dict]]:
    """(label, accuracies, judge): the measured parameters (the planning case: each test's pass rate there is its
    power), and each test's null."""
    base = {k: v[0] for k, v in BASE.items()}
    gap = base["sol_low"] - base["sonnet_off"]
    return [("measured (scans)", base, JUDGE),
            ("AH1 at its null (R 0.5)", {**base, "sonnet_low": base["sonnet_off"] + 0.5 * gap}, JUDGE),
            ("AH1 if R were 0.8", {**base, "sonnet_low": base["sonnet_off"] + 0.8 * gap}, JUDGE),
            ("AH2 at its null (depth = width)", {**base, "haiku_low": base["haiku_off"], "luna_low": base["luna_none"]}, JUDGE),
            ("AH4 at its null (no coupling, j1 0)", base, {**JUDGE, "j1": 0.0})]


def main(reps: int = 60, per_task=(50, 80, 110)) -> str:
    from analysis.pruning_phase3a import md

    frames, floors = [], []
    for k in per_task:
        n = 4 * k + N_MATH
        arms = arms_for({a: v[0] for a, v in BASE.items()})
        floor = ah3_noise_floor(n, arms, JUDGE, reps=max(20, reps // 2))
        floors.append({"per_task": k, "items": n, **floor})
        for label, acc, judge in scenarios() if k == per_task[-1] else scenarios()[:1]:
            frames.append(power(n, arms_for(acc), judge, reps=reps, upper_limit=floor["upper_limit"],
                                mae_limit=floor["mae_limit"]).assign(scenario=label, per_task=k, items=n))
    table = pd.concat(frames, ignore_index=True)[["per_task", "items", "scenario", "test", "pass_rate", "mean_estimate",
                                                 "void_rate"]]
    text = "\n".join([
        "# Power of AH1-AH4 by simulation (session E5, step 5.4; before sealing)", "",
        f"Written by `python -m analysis.anchor_power` ({reps} simulated anchors per row; the frozen tests of "
        "analysis/anchor_read.py; Holm at 5% over the non-void tests). Parameters: analysis/anchor_power.py (BASE, "
        f"JUDGE). Assumed, not measured: {', '.join(sorted(ASSUMED))}.", "",
        "Rows \"measured (scans)\": the pass rate is the test's power if the scans' accuracies are the truth. Under a "
        "test's null the pass rate is its false-positive rate. A test with power under 0.70 at the chosen n is demoted "
        "to exploratory (brief 5.4; for AH1 also the e52 scan's decision).", "",
        "## AH3 limits from the noise floor (the simulated anchor follows the model exactly)", "",
        md(pd.DataFrame(floors), 4), "", "## Pass rates", "", md(table, 3), ""])
    Path(ROOT_OUT).write_text(text)
    print(text)
    return text




def ah3_without_sol_med(reps: int = 30) -> str:
    """Audit 87: AH3's power with Haiku effort high and Sol medium left out (Sol medium's math cells were dropped, so it
    is not a complete arm), at the frozen limits. Prints the section; it is added to power.md by hand between runs."""
    from analysis.pruning_phase3a import md

    limits = {"mae_limit": R.AH3_MAE, "upper_limit": R.AH3_UPPER, "gain_limit": R.AH3_GAIN,
              "gain_upper_limit": R.AH3_GAIN_UPPER}
    table = ah3_power(4 * 110 + N_MATH, limits, reps=reps, drop=("haiku_high", "sol_med"))
    text = "\n".join(["", "## AH3 without Haiku effort high and Sol medium (audit 87: neither has math cells)", "",
                      f"Frozen limits; {reps} simulated anchors per row; the other arms as above.", "", md(table, 3), ""])
    print(text)
    return text


def ah3_six_arms(reps: int = 30) -> str:
    """Audit 74: AH3's power with Haiku effort high left out (6 three-call arms), at the frozen limits."""
    from analysis.pruning_phase3a import md

    limits = {"mae_limit": R.AH3_MAE, "upper_limit": R.AH3_UPPER, "gain_limit": R.AH3_GAIN,
              "gain_upper_limit": R.AH3_GAIN_UPPER}
    table = ah3_power(4 * 110 + N_MATH, limits, reps=reps, drop=("haiku_high",))
    text = "\n".join(["", "## AH3 with 6 three-call arms (audit 74: Haiku effort high has no math cells)", "",
                      f"Frozen limits; {reps} simulated anchors per row; the other arms as above.", "", md(table, 3), ""])
    with Path(ROOT_OUT).open("a") as f:
        f.write(text)
    print(text)
    return text


def ah3_main(n_per_task: int = 110, reps: int = 30) -> str:
    """The AH3 redesign after audit 71: limits from the noise floor (level and gain), then AH3's pass rate when the model
    is true and under two misspecifications. Appends a section to power.md."""
    from analysis.pruning_phase3a import md

    n = 4 * n_per_task + N_MATH
    floor = ah3_noise_floor(n, arms_for({a: v[0] for a, v in BASE.items()}), JUDGE, reps=reps)
    table = ah3_power(n, floor, reps=reps)
    text = "\n".join(["", "## AH3 with the vote-gain criterion (audit 71)", "",
                      f"{n} items ({n_per_task} BBEH per task + {N_MATH} math); {reps} simulated anchors per row. Limits "
                      "from the noise floor: the 90th percentiles when the simulated anchor follows the model, rounded "
                      "up (level to whole points, gain to half points).", "",
                      md(pd.DataFrame([floor]), 4), "", md(table, 3), ""])
    with Path(ROOT_OUT).open("a") as f:
        f.write(text)
    print(text)
    return text


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "ah3":
        ah3_main()
    elif len(sys.argv) > 1 and sys.argv[1] == "ah3_six":
        ah3_six_arms()
    elif len(sys.argv) > 1 and sys.argv[1] == "ah3_no_sol_med":
        ah3_without_sol_med()
    else:
        main(int(sys.argv[1]) if len(sys.argv) > 1 else 60)
