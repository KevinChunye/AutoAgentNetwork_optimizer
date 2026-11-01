"""Budget statement: planned allocation, estimate and actual spend per pilot step and per run.

Sources (read only):
  state/ledger.jsonl        every paid call; run_id = "<experiment name>-<unix time>"
  research/estimates.csv    rows appended by `aan estimate <config> --record research/estimates.csv`
  PLAN_USD below            the allocations of docs/RESEARCH_PROTOCOL.md section 6 (v2)

An experiment's step is the prefix of its name up to the first underscore ("p2_omni_dense" -> "p2");
the gate widening (p3w) counts as P3, the gate step it belongs to.
Outputs: tables/budget_by_run.csv, tables/budget_by_step.csv, tables/budget_by_account.csv and
figure (f) planned against actual by step.

Usage: python -m analysis.budget
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from autoagentnet.budget import BudgetRules
from autoagentnet.meter import Ledger

from .common import ROOT, color, save_figure, save_table, style

PLAN_USD = {"p0": 0.10, "p1": 0.0, "p2": 0.50, "p3": 1.60, "p4": 6.00, "p4b": 1.00, "p5": 0.46, "reserve": 2.00}


def step_of(experiment: str) -> str:
    head = experiment.split("_")[0]
    if head == "p3w":
        return "p3"
    return head if head in PLAN_USD else "other"


def spend_by_run(ledger: Ledger) -> pd.DataFrame:
    df = ledger.to_frame()
    if df.empty:
        return pd.DataFrame(columns=["run_id", "experiment", "step", "account", "calls", "actual_usd", "started"])
    df["experiment"] = df["run_id"].str.rsplit("-", n=1).str[0]
    out = df.groupby(["run_id", "experiment", "account"]).agg(
        calls=("cost_usd", "size"), actual_usd=("cost_usd", "sum"), started=("timestamp", "min")
    ).reset_index()
    out["step"] = out["experiment"].map(step_of)
    return out.sort_values("started")


def latest_estimates(estimates_csv: Path) -> pd.DataFrame:
    """The most recent recorded worst case (x safety) per experiment, summed over accounts.
    Estimates made for fake-model dry runs are skipped (they cost nothing)."""
    if not estimates_csv.exists():
        return pd.DataFrame(columns=["experiment", "estimate_usd"])
    est = pd.read_csv(estimates_csv)
    est = est[est["account"] != "fake"]
    last = est.groupby("experiment")["date"].transform("max")
    est = est[est["date"] == last]
    return est.groupby("experiment")["worst_case_x_safety"].sum().rename("estimate_usd").reset_index()


def budget_tables(ledger: Ledger, estimates_csv: Path, rules: BudgetRules,
                  pilot_only: bool = False) -> dict[str, pd.DataFrame]:
    """pilot_only keeps the pilot's steps (p0-p5), so the pilot report's statement does not grow with the
    later work of the same budget phase (the market town and v3, which report their own spend)."""
    runs = spend_by_run(ledger)
    if pilot_only:
        runs = runs[runs["step"] != "other"]
    by_exp = runs.groupby(["experiment", "step"])[["calls", "actual_usd"]].sum().reset_index()
    by_run = by_exp.merge(latest_estimates(estimates_csv), on="experiment", how="left")
    by_run["actual_over_estimate"] = by_run["actual_usd"] / by_run["estimate_usd"]
    by_step = pd.DataFrame({"step": list(PLAN_USD), "planned_usd": list(PLAN_USD.values())})
    actual = runs.groupby("step")["actual_usd"].sum()
    by_step["actual_usd"] = by_step["step"].map(actual).fillna(0.0)
    accounts = pd.DataFrame({"account": list(rules.hard_caps_usd), "hard_cap_usd": list(rules.hard_caps_usd.values())})
    if pilot_only:
        accounts["spent_usd"] = accounts["account"].map(runs.groupby("account")["actual_usd"].sum()).fillna(0.0)
    else:
        accounts["spent_usd"] = accounts["account"].map(lambda a: ledger.spent_usd(a))
    phase = rules.active_phase
    accounts.attrs["phase_cap_usd"] = phase.total_usd if phase else None
    accounts.attrs["spent_total_usd"] = float(accounts["spent_usd"].sum()) if pilot_only else ledger.spent_usd()
    return {"by_run": by_run, "by_step": by_step, "by_account": accounts}


def plot_burn(by_step: pd.DataFrame, phase_cap: float | None, safety: float):
    """Figure (f): planned allocation against actual spend per pilot step."""
    plt = style()
    fig, ax = plt.subplots(figsize=(5.2, 3.0))
    x = range(len(by_step))
    ax.bar([i - 0.2 for i in x], by_step["planned_usd"], width=0.4, color=color(5), label="planned (protocol v2, section 6)")
    ax.bar([i + 0.2 for i in x], by_step["actual_usd"], width=0.4, color=color(0), label="actual (ledger)")
    ax.set_xticks(list(x), by_step["step"])
    ax.set_ylabel("USD")
    title = f"Budget by step: spent ${by_step['actual_usd'].sum():.2f}"
    if phase_cap:
        title += f" of ${phase_cap:.0f} (governor stops near ${phase_cap / safety:.2f} estimated)"
    ax.set_title(title, fontsize=8)
    ax.legend(fontsize=7)
    return fig


def main(ledger_path: Path = ROOT / "state/ledger.jsonl", estimates_csv: Path = ROOT / "research/estimates.csv",
         budget_path: Path = ROOT / "configs/budget.yaml", pilot_only: bool = False) -> dict[str, pd.DataFrame]:
    rules = BudgetRules.from_yaml(budget_path)
    tables = budget_tables(Ledger(ledger_path, must_exist=True), estimates_csv, rules, pilot_only)
    for name, table in tables.items():
        save_table(table.round(4), f"budget_{name}")
        print(name, "\n", table.round(4).to_string(index=False), "\n")
    accounts = tables["by_account"]
    save_figure(plot_burn(tables["by_step"], accounts.attrs["phase_cap_usd"], rules.safety_multiplier), "f_budget_burn")
    return tables


if __name__ == "__main__":
    main()
