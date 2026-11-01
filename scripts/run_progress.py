"""Write results/run_progress.md (under results/, so writing it never makes the tree dirty for a preflight): where every ScienceClaw run stands, for Kevin to follow while runs go on.

Read-only on everything it reads (spend ledger, budget rules, results). Definitions:
- spend: the ledger's cost_usd summed over calls made since `--since` (UTC date), by account and model.
- room: what the SpendGovernor still allows per account in the active phase (exactly what `aan status` prints).
- PHOENIX batch: one results/sci_batch_*/batch_status.json; "reported" counts branches that have finished
  (any outcome), "total" the branches in the batch; outcomes are the branch statuses (completed,
  limits_reached, no_positive_feasible_plan, ...).
- batch pace: wall seconds per reported branch, from the first to the last ledger call of the batch's
  branches; ETA = pace x branches left (a rough guide: branches differ in length).
- Self-or-Social run: one results/sos_*/status.json (state, vendor, item range, calls, live calls, new spend).
- not started: a batch config (batch_*.yaml) in the listed config directories with no batch_status.json yet.

Usage: python scripts/run_progress.py [--since 2026-10-31] [--out results/run_progress.md]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

import pandas as pd
import yaml

from autoagentnet.budget import BudgetRules, SpendGovernor
from autoagentnet.meter import Ledger

ET = dt.timezone(dt.timedelta(hours=-4))


def md_table(frame: pd.DataFrame) -> str:
    """Plain markdown table (no optional dependency)."""
    if frame.empty:
        return "(none)"
    cols = [str(c) for c in frame.columns]
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(str(v) for v in row) + " |")
    return "\n".join(lines)


def spend_tables(ledger: Ledger, budget_path: Path, since: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(lifetime spend and room by account, spend since `since` by account and model)."""
    frame = ledger.to_frame()
    status = SpendGovernor(ledger, BudgetRules.from_yaml(budget_path)).status()
    life = frame.groupby("account")["cost_usd"].sum().rename("lifetime_usd").reset_index()
    life["cap_usd"] = life["account"].map(status.get("account_caps_usd", status.get("hard_caps_usd", {})))
    life["room_usd"] = life["account"].map(status.get("room_by_account_usd", {}))
    recent = frame[frame["timestamp"] >= since]
    by_model = recent.groupby(["account", "model"]).agg(calls=("cost_usd", "size"), usd=("cost_usd", "sum"))
    by_model = by_model.reset_index().sort_values("usd", ascending=False)
    return life.round(4), by_model.round(4)


def batch_rows(results: Path, ledger_frame: pd.DataFrame, now: float) -> pd.DataFrame:
    rows = []
    for path in sorted(results.glob("sci_batch_*/batch_status.json")):
        status = json.loads(path.read_text())
        run_ids = [b["run_id"] for b in status["branches"] if b.get("run_id")]
        calls = ledger_frame[ledger_frame["run_id"].isin(run_ids)]
        reported, total = status["branches_reported"], status["branches_total"]
        first = calls["timestamp"].min() if len(calls) else None
        last = calls["timestamp"].max() if len(calls) else None
        pace = (last - first) / reported if reported and first is not None else None
        eta = "" if pace is None or reported >= total else round(pace * (total - reported) / 60, 1)
        outcomes = ", ".join(f"{k} {v}" for k, v in sorted(status["status_counts"].items()))
        rows.append({"batch": status["batch"], "status": status["status"], "done": f"{reported}/{total}",
                     "outcomes": outcomes, "spent_usd": round(status["batch_run_spent_usd"], 4),
                     "last_call_min_ago": None if last is None else round((now - last) / 60, 1),
                     "eta_min": eta})
    return pd.DataFrame(rows)


def not_started(config_roots: list[Path], results: Path) -> pd.DataFrame:
    rows = []
    paths = [path for root in config_roots for path in sorted(root.glob("**/batch_*.yaml"))]
    for path in paths:
        cfg = yaml.safe_load(path.read_text())
        if not (results / cfg["name"] / "batch_status.json").exists():
            rows.append({"batch": cfg["name"], "branches": len(cfg["branches"]), "config": str(path)})
    return pd.DataFrame(rows)


def sos_rows(results: Path) -> pd.DataFrame:
    rows = []
    for path in sorted(results.glob("sos_*/status*.json")):
        status = json.loads(path.read_text())
        rows.append({"file": str(path.relative_to(results)), "state": status.get("state"),
                     "reason": (status.get("reason") or "")[:60], "vendor": status.get("vendor"),
                     "items": status.get("items"), "calls": status.get("calls"),
                     "live_calls": status.get("live_calls"), "new_spend_usd": status.get("new_spend_usd")})
    return pd.DataFrame(rows)


def build(results: Path, ledger_path: Path, budget_path: Path, config_roots: list[Path], since: str) -> str:
    now = dt.datetime.now(dt.timezone.utc)
    start = dt.datetime.fromisoformat(since).replace(tzinfo=dt.timezone.utc).timestamp()
    ledger = Ledger(ledger_path, must_exist=True)
    frame = ledger.to_frame()
    life, recent = spend_tables(ledger, budget_path, start)
    parts = [f"# Run progress (ScienceClaw)\n",
             f"Updated {now:%Y-%m-%d %H:%M} UTC ({now.astimezone(ET):%H:%M} ET). Regenerated by the runners after "
             f"each chunk; `python scripts/run_progress.py` refreshes it by hand.\n",
             "## Spend and room by account\n", md_table(life), "",
             f"## Spend since {since} by model\n", md_table(recent), "",
             f"Total since {since}: ${recent['usd'].sum():.4f}\n",
             "## PHOENIX batches\n", md_table(batch_rows(results, frame, now.timestamp())), "",
             "## PHOENIX batches not started\n", md_table(not_started(config_roots, results)), "",
             "## Self-or-Social runs\n", md_table(sos_rows(results)), ""]
    return "\n".join(parts)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default="2026-10-31")
    p.add_argument("--results", default="results")
    p.add_argument("--ledger", default="state/ledger.jsonl")
    p.add_argument("--budget", default="configs/budget.yaml")
    p.add_argument("--configs", nargs="+", default=["configs/experiments/phoenix_science/matrix",
                                                     "configs/experiments/phoenix_science/family"],
                   help="directories holding the batch configs still to run (superseded calibrations are left out)")
    p.add_argument("--out", default="results/run_progress.md")
    args = p.parse_args()
    text = build(Path(args.results), Path(args.ledger), Path(args.budget), [Path(c) for c in args.configs], args.since)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(text)
    print(text)


if __name__ == "__main__":
    main()
