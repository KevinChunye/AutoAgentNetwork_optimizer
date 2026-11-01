"""The automatic gate of a Self-or-Social run: the prereg's five go/no-go rules on its first slice of items.

Kevin (2026-11-01): no separate pilot run; the first slice of the real run is checked and, if it passes, the run
continues. This script reads that slice's rows and prints a verdict (exit 0 = GO, 1 = NO-GO, 2 = cannot judge).

Rules (research/self_or_social_shortlist/prereg_arxivmath.md "Pilot and go/no-go", applied per team for LAB-Bench):
1. Per model (ref) and phase (first answer, or revision = branch and full review), the share of the slice's live
   calls that failed is at most 10%. A call failed if it is truncated, refused or unparsed; an unparsed math reply
   that explicitly abstains (mathread.abstained, audit 88) is not counted. The run did not stop on a governor refusal.
2. Actual cost per item (live dollars of the slice / items in it) is at most 2x the expected cost per item.
3. The pipeline ran end to end: every item of the slice has every expected row (first answers, 9 branches, full
   review: 15 for a team of three) and every row is graded (correct is not empty).
4. status.json says completed and every checkpoint of the run was committed and pushed.
5. Projected cost = slice live dollars x (items still to run, all runs of the study / items in the slice) x 1.3 fits
   the room of the billed account (SpendGovernor room, the same number `aan status` prints).

Usage: python scripts/sos_gate.py --results results/sos_lab_claude_dev --offset 0 --limit 8 \
           --items-per-run-file research/.../dev.txt --expected-item-usd 0.31 --projected-items 288
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

from autoagentnet.budget import BudgetRules, SpendGovernor
from autoagentnet.evidence.mathread import abstained
from autoagentnet.meter import Ledger

REFUSALS = ("refusal", "content_filter", "invalid_prompt")
MAX_FAILED = 0.10


def failed_rates(rows: pd.DataFrame) -> pd.DataFrame:
    """Failed share of live calls per model (ref) and phase (initial / revision); see rule 1."""
    live = rows[~rows["from_cache"].astype(bool) & ~rows["reused"].fillna(False).astype(bool)]
    live = live.assign(phase2=live["phase"].where(live["phase"] == "initial", "revision"))
    unparsed = ~live["parsed"].astype(bool)
    abstain = unparsed & (live["task_kind"] == "math") & live["answer"].map(lambda a: abstained(a) if isinstance(a, str) else False)
    failed = (unparsed & ~abstain) | live["truncated"].fillna(False).astype(bool) | live["stop_reason"].isin(REFUSALS)
    live = live.assign(failed=failed)
    return live.groupby(["ref", "phase2"]).agg(calls=("failed", "size"), failed=("failed", "mean")).reset_index()


def verdict(rows: pd.DataFrame, status: dict, items: list[str], expected_item_usd: float, projected_items: int,
            room_usd: float, rows_per_item: int) -> dict:
    """The five rules on the slice's rows; `items` are the slice's item ids."""
    out = {"items": len(items), "rules": {}, "notes": []}
    rates = failed_rates(rows)
    bad = rates[rates["failed"] > MAX_FAILED]
    refused = status.get("state") == "stopped" and str(status.get("reason", "")).startswith("budget")
    out["rules"]["1_failed_share"] = bad.empty and not refused
    out["failed_rates"] = rates.round(4).to_dict("records")
    live_usd = float(rows.loc[~rows["from_cache"].astype(bool), "cost_usd"].sum())
    per_item = live_usd / len(items) if items else float("inf")
    out["live_usd"], out["usd_per_item"] = round(live_usd, 5), round(per_item, 5)
    out["rules"]["2_cost_per_item"] = per_item <= 2 * expected_item_usd
    counts = rows.groupby("item").size()
    complete = all(counts.get(i, 0) >= rows_per_item for i in items)
    out["rules"]["3_end_to_end"] = complete and bool(rows["correct"].notna().all())
    checkpoints = status.get("checkpoints", [])
    out["rules"]["4_completed_and_pushed"] = (status.get("state") == "completed" and bool(checkpoints)
                                              and all(c in ("committed and pushed", "nothing new to checkpoint")
                                                      for c in checkpoints))
    projected = per_item * projected_items * 1.3
    out["projected_usd"], out["room_usd"] = round(projected, 2), round(room_usd, 2)
    out["rules"]["5_projection_fits_room"] = projected <= room_usd
    out["go"] = all(out["rules"].values())
    return out


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--results", required=True, help="results/<run name> (calls.csv and status.json)")
    p.add_argument("--items-file", required=True, help="the run's item list in frozen order (one id per line)")
    p.add_argument("--offset", type=int, required=True)
    p.add_argument("--limit", type=int, required=True)
    p.add_argument("--expected-item-usd", type=float, required=True)
    p.add_argument("--projected-items", type=int, required=True, help="items still to run in the whole study")
    p.add_argument("--account", required=True, help="the billed account (anthropic or openai)")
    p.add_argument("--rows-per-item", type=int, default=15)
    p.add_argument("--ledger", default="state/ledger.jsonl")
    p.add_argument("--budget", default="configs/budget.yaml")
    args = p.parse_args()
    results = Path(args.results)
    if not (results / "calls.csv").exists() or not (results / "status.json").exists():
        print(json.dumps({"go": False, "error": "no calls.csv or status.json"}))
        return 2
    ids = [line.strip() for line in Path(args.items_file).read_text().splitlines() if line.strip()]
    items = ids[args.offset: args.offset + args.limit]
    rows = pd.read_csv(results / "calls.csv")
    rows = rows[rows["item"].isin(items)]
    status = json.loads((results / "status.json").read_text())
    room = SpendGovernor(Ledger(args.ledger, must_exist=True), BudgetRules.from_yaml(args.budget)).room_by_account()
    out = verdict(rows, status, items, args.expected_item_usd, args.projected_items, room[args.account],
                  args.rows_per_item)
    print(json.dumps(out, indent=2))
    return 0 if out["go"] else 1


if __name__ == "__main__":
    sys.exit(main())
