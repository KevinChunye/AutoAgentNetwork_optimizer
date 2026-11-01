"""Run one study-CD config through its slices, one paid run at a time (session E6, section 4).

    python scripts/run_cd.py <config.yaml> [--from-offset N] [--to-offset M] [--tier-cap USD]   # items N to M-1 only

Plain words. The same loop as scripts/run_anchor.py (each slice's worst case fits the run cap; `aan check` clears it;
`aan run` runs it with ANTHROPIC_API_KEY and OPENAI_API_KEY removed from the environment; its status.json is kept as
status_items_<offset>.json; results are committed and pushed; the first slice that does not end "completed" stops
the script), with CD's own running guard: before each slice, CD's spend so far for the slice's vendor (ledger rows
whose run id starts with "e60_") plus the slice's expected cost (its calls x the config's guard dollars per call) must
stay within CD_CAP, and before every Anthropic slice the date must be October 31, 2026 or earlier (UTC; the credit
expires on November 1). CD_CAP splits the evidence phase's shared room (audit 97: $150 / 1.15 - $66.31 = $64.13 for
both vendors) as Anthropic $52 and OpenAI $10, leaving $2 for rounding and unledgered attempts; after tier A
(audit 105) as Anthropic $56 and OpenAI $6.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import anchor_slices as S  # noqa: E402
import run_anchor as A  # noqa: E402
from autoagentnet.budget import BudgetRules, effective_run_cap  # noqa: E402
from autoagentnet.evidence.panel import PanelConfig  # noqa: E402
from autoagentnet.meter import Ledger  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402

CD_CAP = {"anthropic": 56.0, "openai": 6.0}  # audit 105: re-split after tier A (the OpenAI bridge needs about $3-5)
RUN_PREFIX = "e60_"
LAST_ANTHROPIC_DAY = "2026-10-31"


def cd_spent(cfg: PanelConfig, account: str) -> float:
    frame = Ledger(ROOT / cfg.ledger, must_exist=True).to_frame()
    if frame.empty:
        return 0.0
    mine = frame["run_id"].astype(str).str.startswith(RUN_PREFIX) & (frame["account"] == account)
    return float(frame.loc[mine, "cost_usd"].sum())


def tier_a_spent(cfg: PanelConfig) -> float:
    """Tier A's spend: ledger rows of e60_cd_ runs that are not probe runs (scripts/run_cd_tier_a.py)."""
    frame = Ledger(ROOT / cfg.ledger, must_exist=True).to_frame()
    if frame.empty:
        return 0.0
    run = frame["run_id"].astype(str)
    return float(frame.loc[run.str.startswith("e60_cd_") & ~run.str.startswith("e60_cd_probe"), "cost_usd"].sum())


def clip(plan: list[tuple], start: int = 0, stop: int | None = None) -> list[tuple]:
    """The slices cut to items [start, stop): a slice that crosses either end is shortened (its worst case only falls),
    so a stage boundary such as the probe's item 3 is exact (research/v4/cd/probe.md)."""
    out = []
    for offset, limit, worst in plan:
        lo, hi = max(offset, start), offset + limit if stop is None else min(offset + limit, stop)
        if hi > lo:
            out.append((lo, hi - lo, worst * (hi - lo) / limit))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--from-offset", type=int, default=0)
    parser.add_argument("--to-offset", type=int, default=None)
    parser.add_argument("--tier-cap", type=float, default=None, help="stop before a slice once tier A has spent this")
    parser.add_argument("--until", type=float, default=None, help="unix time after which no new slice starts")
    args = parser.parse_args()
    cfg = PanelConfig.from_yaml(args.config)
    rules = BudgetRules.from_yaml(ROOT / cfg.budget)
    cap = effective_run_cap(rules, cfg.max_usd)
    plan = clip(S.slices(S.per_item_worst(cfg), cap), args.from_offset, args.to_offset)
    out = ROOT / cfg.out_dir / cfg.name
    total = 0.0
    account = ProviderRegistry.from_yaml(ROOT / cfg.providers).account_of(cfg.sources[0].ref)
    for offset, limit, worst in plan:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if account == "anthropic" and today > LAST_ANTHROPIC_DAY:
            print(f"{cfg.name} {offset}+{limit}: no Anthropic call after {LAST_ANTHROPIC_DAY} (UTC today {today})")
            return 1
        if args.until is not None and time.time() > args.until:  # a background job's time limit: end between slices
            print(f"{cfg.name}: time limit reached before slice {offset}+{limit}; resume from offset {offset}")
            return 2
        if args.tier_cap is not None and tier_a_spent(cfg) >= args.tier_cap:
            print(f"{cfg.name} {offset}+{limit}: tier A has spent ${tier_a_spent(cfg):.2f}, at or above its "
                  f"${args.tier_cap:.0f} cap")
            return 1
        spent, expected = cd_spent(cfg, account), A.slice_expected(cfg, offset, limit)
        if spent + expected > CD_CAP[account]:
            print(f"{cfg.name} {offset}+{limit}: CD guard: CD spent ${spent:.2f} + expected ${expected:.2f} would pass "
                  f"${CD_CAP[account]:.0f} ({account})")
            return 1
        slice_args = ["--task-offset", str(offset), "--task-limit", str(limit)]
        check = A.sh(["aan", "check", args.config, *slice_args])
        if check.returncode != 0 or "cleared" not in check.stdout:
            print(f"{cfg.name} {offset}+{limit}: aan check refused\n{check.stdout[-800:]}{check.stderr[-400:]}")
            return 1
        run = A.sh(["aan", "run", args.config, *slice_args])
        status = json.loads((out / "status.json").read_text())
        shutil.copy(out / "status.json", out / f"status_items_{offset}.json")
        spent = float(status["budget"]["run_spent_usd"])
        total += spent
        print(f"{cfg.name} {offset}+{limit} (worst ${worst:.2f}): {status['state']} {status['reason']} "
              f"calls {status['calls']} live {status['live_calls']} ${spent:.3f}", flush=True)
        A.sh(["git", "add", str(out.relative_to(ROOT))])
        A.sh(["git", "commit", "-q", "-m", f"{cfg.name} slice {offset}+{limit}: {status['state']} (${spent:.3f})"])
        A.sh(["git", "push", "-q", "origin", "HEAD"])
        if run.returncode != 0 or status["state"] != "completed":
            print(f"STOPPED at {offset}+{limit}: {status['reason'] or run.stderr[-400:]}")
            return 1
    print(f"{cfg.name}: {len(plan)} slices completed, ${total:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
