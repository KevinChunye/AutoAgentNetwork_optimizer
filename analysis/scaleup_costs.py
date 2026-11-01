"""Worst-case cost of the scale-up options in the decision memo (protocol v2), from the same
estimator the governor uses (`aan estimate`): every prompt token at the cache-write rate (3
characters per token), every agent writing its full max_tokens, x1.15 safety. The call cache is
counted (configs share upstream calls), calls already paid for are not subtracted, and nothing is
called. Each design's per-task worst case is measured on `n_measure` tasks and scaled linearly.

Designs (Omni-MATH difficulty 4.4-6.1, Haiku 5.5 worker `haiku_nothink`):
  Option B, power-first confirmation on 600 untouched items (positions 320-919, beyond the test
  slice; paired MDE about 5 points, power.csv):
    b_dense_600         dense; vote6, gated_3x6 and every consensus policy come free from its proposers
    b_picks_600_low     3 P4 picks, if P4 picks the 3 grid configs that add the least to a dense run
    b_picks_600_high    3 P4 picks, if P4 picks the 3 that add the most (review-heavy configs such as
                        1-6-6-1 share no calls with dense below the propose stage)
    b_picks_600         P4's actual picks (joint, stage-by-stage, best uniform), once p4_picks.csv exists
    b_single_600        the single Haiku agent
    b_sonnet_600        one Sonnet 5.5 call (sonnet_nothink), the matched-cost senior control
    b_cascade_600       judge_cascade (add-on): pays for aggregators and Sonnet escalations; its
                        proposers are dense's cached calls
  Option C, the production function at n = 200 (the test slice, positions 120-319):
    c_grid_200          factorial grid, levels 1/3/6 per stage (27 configs, 105 calls per task)
    c_single_200        the single Haiku agent on the same items
    c_noise_20          dense on 20 of the items, one extra replicate (run-to-run noise)
    c_mixed_vote6_200   3 Haiku + 3 GPT-6 Luna proposers and a free vote (H6: a mixed team's
                        effective size); bills both accounts

A pick's cost is what it adds to a dense run on the same items: the worst case of dense plus the
pick, minus dense alone (its calls not shared with dense). Summing three picks ignores calls the
picks share with each other, so it errs high.

Outputs: tables/scaleup_costs.csv (one row per design and account) and tables/scaleup_options.csv
(each option's low and high total; they differ only while P4's picks are unknown).

Usage: python -m analysis.scaleup_costs [task file]
"""

from __future__ import annotations

import asyncio
import itertools
import sys

import pandas as pd

from autoagentnet.experiment import ExperimentConfig, estimate_experiment

from .common import TABLES, save_table

TASKS = "data/external/omni_d44_61.jsonl"
NETWORKS = "configs/networks"
DENSE, SINGLE = f"{NETWORKS}/dense_3x6.yaml", f"{NETWORKS}/single.yaml"
GRID = [[a, b, c, 1] for a, b, c in itertools.product([1, 3, 6], repeat=3) if (a, b, c) != (6, 6, 6)]
PICK_METHODS = ["joint (exhaustive, labeled)", "stage-by-stage sensitivity", "best uniform"]


def per_task_worst(cfg: ExperimentConfig, n_measure: int) -> pd.DataFrame:
    """Worst case x safety and calls per task, by billed account."""
    table = asyncio.run(estimate_experiment(cfg.model_copy(update={"task_limit": n_measure})))
    return table.groupby(level="account")[["worst_case_x_safety", "calls"]].sum() / n_measure


def pick_costs(base: dict, n_measure: int) -> pd.Series:
    """Worst case per task that each non-dense grid config adds to a dense run on the same items."""
    dense = per_task_worst(ExperimentConfig(name="x", network=DENSE, **base), n_measure).loc["anthropic", "worst_case_x_safety"]
    added = {}
    for keep in GRID:
        both = per_task_worst(ExperimentConfig(name="x", network=DENSE, configs=[keep], **base), n_measure)
        added["k" + "-".join(map(str, keep))] = both.loc["anthropic", "worst_case_x_safety"] - dense
    return pd.Series(added).sort_values()


def p4_picks() -> list[str]:
    """Config ids of P4's picks (joint, stage-by-stage, best uniform) once P4 has run, dense excluded."""
    path = TABLES / "p4_picks.csv"
    if not path.exists():
        return []
    picks = pd.read_csv(path, dtype={"config_id": str})
    picks = picks[picks["method"].isin(PICK_METHODS) & (picks["config_id"] != "k6-6-6-1")]
    return list(picks["config_id"].drop_duplicates())


def main(tasks: str = TASKS, n_measure: int = 10) -> pd.DataFrame:
    haiku = dict(tasks=tasks, model_override="haiku_nothink")
    own_refs = dict(tasks=tasks, model_override=None)  # networks that name their own refs
    designs = [
        ("b_dense_600", ExperimentConfig(name="x", network=DENSE, task_offset=320, **haiku), 600),
        ("b_single_600", ExperimentConfig(name="x", network=SINGLE, task_offset=320, **haiku), 600),
        ("b_sonnet_600", ExperimentConfig(name="x", network=f"{NETWORKS}/single_sonnet.yaml", task_offset=320, **own_refs), 600),
        ("b_cascade_600", ExperimentConfig(name="x", network=f"{NETWORKS}/judge_cascade.yaml", task_offset=320, **haiku), 600),
        ("c_grid_200", ExperimentConfig(name="x", network=DENSE, task_offset=120, configs={"levels": [1, 3, 6]}, **haiku), 200),
        ("c_single_200", ExperimentConfig(name="x", network=SINGLE, task_offset=120, **haiku), 200),
        ("c_noise_20", ExperimentConfig(name="x", network=DENSE, task_offset=120, replicates=2, **haiku), 20),
        ("c_mixed_vote6_200", ExperimentConfig(name="x", network=f"{NETWORKS}/mixed_vote6.yaml", task_offset=120, **own_refs), 200),
    ]
    rows = []
    for name, cfg, n_tasks in designs:
        for account, r in per_task_worst(cfg, n_measure).iterrows():
            rows.append({"design": name, "account": account, "tasks": n_tasks, "calls_per_task": round(r["calls"], 1),
                         "worst_x_safety_per_task_usd": r["worst_case_x_safety"]})
    added = pick_costs(dict(task_offset=320, **haiku), n_measure)
    picks = {"b_picks_600_low": list(added.index[:3]), "b_picks_600_high": list(added.index[-3:])}
    if p4_picks():
        picks["b_picks_600"] = p4_picks()
    for name, ids in picks.items():
        rows.append({"design": name, "account": "anthropic", "tasks": 600, "calls_per_task": None, "picks": " ".join(ids),
                     "worst_x_safety_per_task_usd": float(added.loc[ids].sum())})
    table = pd.DataFrame(rows)
    table["option"] = table["design"].str[0].str.upper()
    table["worst_x_safety_usd"] = (table["worst_x_safety_per_task_usd"] * table["tasks"]).round(2)
    table["worst_x_safety_per_task_usd"] = table["worst_x_safety_per_task_usd"].round(5)
    save_table(table, "scaleup_costs")
    options = option_totals(table)
    save_table(options, "scaleup_options")
    print(table.to_string(index=False))
    print(options.to_string(index=False))
    return table


def option_totals(table: pd.DataFrame) -> pd.DataFrame:
    """Each option's worst case: B with the cheapest and the dearest possible picks (equal once P4's
    picks are known), B with the cascade add-on, and C."""
    usd = table.groupby("design")["worst_x_safety_usd"].sum()
    b_core = usd[["b_dense_600", "b_single_600", "b_sonnet_600"]].sum()
    if "b_picks_600" in usd.index:
        b_low = b_high = b_core + usd["b_picks_600"]
    else:
        b_low, b_high = b_core + usd["b_picks_600_low"], b_core + usd["b_picks_600_high"]
    c = usd[[d for d in usd.index if d.startswith("c_")]].sum()
    rows = [("B", b_low, b_high), ("B + cascade", b_low + usd["b_cascade_600"], b_high + usd["b_cascade_600"]), ("C", c, c)]
    return pd.DataFrame(rows, columns=["option", "low_usd", "high_usd"]).round(2)


if __name__ == "__main__":
    main(*sys.argv[1:])
