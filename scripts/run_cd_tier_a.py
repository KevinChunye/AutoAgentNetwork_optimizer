"""Run study CD's tier A in plan_v3's order under its spend rule (session E6; analysis/cd_plan.py, audit 100).

    python scripts/run_cd_tier_a.py [--stop-after-blocks N]

Plain words. First every BBEH config over every BBEH item (cheap). Then the math and code blocks (cd_plan.blocks():
BLOCK items each, alternating, math first), every config of the block's family over the block's items. A block starts
only if tier A's actual spend so far (ledger rows of e60_cd_ runs that are not probe runs) plus the block's projected
cost (plan.json per_item_usd x its items) stays within plan.json's tier_a_cap; the first block that does not fit ends
tier A. Inside a block, before each config, tier A's actual spend must also stay under HARD_CAP ($40, the brief's
expected ceiling for tier A), so a block whose calls run far above their projection is cut short there (its items then
lack some arms; the read compares arms on the items they share). Each config runs through scripts/run_cd.py (aan check, the $4 run cap, CD's guard, no Anthropic call after
October 31 UTC, commit and push per slice). A slice whose status_items_<offset>.json already says "completed" is skipped,
so an interrupted run resumes where it stopped: a config starts at its first item that lacks a call (covered(), from
calls.csv), so no slice is replayed (audit 102). The first config that does not complete stops the script.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from analysis import cd_plan  # noqa: E402
from autoagentnet.meter import Ledger  # noqa: E402

CONFIGS = ROOT / "configs/experiments/v4"
HARD_CAP = 40.0
UNTIL = float("inf")  # set by --minutes
GROUPS = {"bbeh": ["haiku_off", "haiku_think", "sonnet", "sonnet_xhigh", "sonnet_max"],
          "other": ["haiku_off", "haiku_think", "sonnet_off", "sonnet_low", "sonnet_med", "sonnet_high", "sonnet_xhigh",
                    "sonnet_max"]}


def tier_a_spent() -> float:
    frame = Ledger(ROOT / "state/ledger.jsonl", must_exist=True).to_frame()
    if frame.empty:
        return 0.0
    run = frame["run_id"].astype(str)
    return float(frame.loc[run.str.startswith("e60_cd_") & ~run.str.startswith("e60_cd_probe"), "cost_usd"].sum())


def covered(name: str) -> set[int]:
    """Positions (in the config's item list) of the items that have every call of every source in the config's
    calls.csv (audit 102: a slice that stopped on a stop rule after making all its calls is covered, so it is not
    replayed; a replay would turn its live rows into cache rows)."""
    from autoagentnet.evidence.panel import PanelConfig, read_ids

    cfg = PanelConfig.from_yaml(CONFIGS / f"{name}.yaml")
    path = ROOT / "results" / name / "calls.csv"
    if not path.exists():
        return set()
    calls = pd.read_csv(path, usecols=["item", "source", "call"])
    have = calls.groupby("item").apply(lambda g: set(zip(g["source"], g["call"])), include_groups=False).to_dict()
    need = {(s.label, c) for s in cfg.sources for c in range(s.first_call, s.first_call + s.calls)}
    ids = read_ids(ROOT / cfg.items)
    return {k for k, i in enumerate(ids) if need <= have.get(i, set())}


def done(name: str, start: int, end: int) -> bool:
    return set(range(start, end)) <= covered(name)


def run(name: str, start: int, end: int) -> bool:
    have = covered(name)
    first = next((k for k in range(start, end) if k not in have), None)
    if first is None:
        print(f"{name} {start}-{end}: already covered", flush=True)
        return True
    if first > start:
        print(f"{name}: items {start}-{first - 1} already covered; starting at {first}", flush=True)
    start = first
    args = ["python", "scripts/run_cd.py", str(CONFIGS / f"{name}.yaml"), "--from-offset", str(start),
            "--to-offset", str(end), "--tier-cap", str(HARD_CAP), "--until", str(UNTIL)]  # checked before every slice
    proc = subprocess.run(args, cwd=ROOT, capture_output=True, text=True)
    print(proc.stdout.strip(), flush=True)
    if proc.returncode == 2:
        print("TIME LIMIT: this invocation ends here; run the script again to resume", flush=True)
        raise SystemExit(0)
    if proc.returncode != 0:
        print(f"STOPPED in {name} {start}-{end}: {proc.stderr[-600:]}", flush=True)
    return proc.returncode == 0


def n_items(name: str) -> int:
    from autoagentnet.evidence.panel import PanelConfig, read_ids

    return len(read_ids(ROOT / PanelConfig.from_yaml(CONFIGS / f"{name}.yaml").items))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stop-after-blocks", type=int, default=None)
    parser.add_argument("--minutes", type=float, default=95.0, help="no slice starts after this many minutes (a "
                        "background job's 2-hour limit minus the longest slice)")
    args = parser.parse_args()
    global UNTIL
    UNTIL = time.time() + 60 * args.minutes
    plan = json.loads(cd_plan.PLAN_JSON.read_text())
    n_bbeh = len(plan["items"]["bbeh"])
    for group in GROUPS["bbeh"]:
        if tier_a_spent() >= HARD_CAP:
            print(f"TIER A HARD STOP before {group} on BBEH: spent ${tier_a_spent():.2f} >= ${HARD_CAP:.0f}", flush=True)
            return 0
        if not run(f"e60_cd_{group}_bbeh", 0, n_items(f"e60_cd_{group}_bbeh")):
            return 1
    for k, (fam, start, end) in enumerate(cd_plan.blocks()):
        if args.stop_after_blocks is not None and k >= args.stop_after_blocks:
            print(f"stopped after {k} blocks as asked", flush=True)
            return 0
        spent, projected = tier_a_spent(), (end - start) * plan["per_item_usd"][fam]
        if all(done(f"e60_cd_{g}_{fam}", start, end) for g in GROUPS["other"]):
            print(f"block {k} {fam} {start}-{end}: already completed", flush=True)
            continue
        started = any(covered(f"e60_cd_{g}_{fam}") & set(range(start, end)) for g in GROUPS["other"])
        if not started and spent + projected > plan["tier_a_cap"]:  # audit 104: a started block is finished (its
            # spend so far is already in `spent`), so a resume does not count part of a block twice
            print(f"TIER A ENDS before block {k} ({fam} {start}-{end}): spent ${spent:.2f} + projected ${projected:.2f} "
                  f"would pass ${plan['tier_a_cap']:.0f}", flush=True)
            return 0
        print(f"block {k} {fam} {start}-{end}: spent ${spent:.2f}, projected ${projected:.2f}", flush=True)
        for group in GROUPS["other"]:
            if tier_a_spent() >= HARD_CAP:
                print(f"TIER A HARD STOP in block {k} before {group}: spent ${tier_a_spent():.2f} >= ${HARD_CAP:.0f}",
                      flush=True)
                return 0
            if not run(f"e60_cd_{group}_{fam}", start, end):
                return 1
    print(f"tier A: every block ran; spent ${tier_a_spent():.2f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
