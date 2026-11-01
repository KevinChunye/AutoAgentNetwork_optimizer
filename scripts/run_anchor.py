"""Run one anchor config through all its slices, one paid run at a time (session E5, step 5.3).

    python scripts/run_anchor.py <config.yaml> [--from-offset N] [--to-offset M]

Plain words. The slices come from scripts/anchor_slices.py (each slice's worst case fits the run cap). For each slice,
in order: `aan check` must clear it; `aan run` runs it (with ANTHROPIC_API_KEY and OPENAI_API_KEY removed from the
environment, so only the AAN_* keys can be used); its status.json is read and kept as status_items_<offset>.json; the
results are committed and pushed (state/ is pushed by the run's own checkpoints). The first slice that does not end
"completed" stops the script with its reason, so a stop rule (unparsed, truncation, cost) or a budget refusal ends
paid work on that config until an audit. It prints one line per slice and a total.

A long config runs in several invocations (audit 84): --from-offset and --to-offset keep the slices whose first item
is at least N and below M, so each invocation ends between slices, inside the background limit.

Running guard against K3 (audit 71): before each slice, the anchor's spend so far for the slice's vendor (ledger
rows whose run id starts with "e51_") plus the slice's expected cost (its calls x the config's guard dollars per call)
must stay within K3: $48 Anthropic, $34 OpenAI. Otherwise the script stops before the slice.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import anchor_slices as S  # noqa: E402
from autoagentnet.budget import BudgetRules, effective_run_cap  # noqa: E402
from autoagentnet.evidence.panel import PanelConfig, read_ids  # noqa: E402
from autoagentnet.meter import Ledger  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402

K3 = {"anthropic": 48.0, "openai": 34.0}
RUN_PREFIX = "e51_"


def anchor_spent(cfg: PanelConfig, account: str) -> float:
    frame = Ledger(ROOT / cfg.ledger, must_exist=True).to_frame()
    if frame.empty:
        return 0.0
    mine = frame["run_id"].astype(str).str.startswith(RUN_PREFIX) & (frame["account"] == account)
    return float(frame.loc[mine, "cost_usd"].sum())


def slice_expected(cfg: PanelConfig, offset: int, limit: int) -> float:
    ids = read_ids(ROOT / cfg.items)[offset: offset + limit]
    total = 0.0
    for s in cfg.sources:
        mine = ids if s.items is None else [i for i in ids if i in set(read_ids(ROOT / s.items))]
        total += len(mine) * s.calls * cfg.expect.usd_per_call[s.ref]
    return total


def env() -> dict:
    e = dict(os.environ)
    e.pop("ANTHROPIC_API_KEY", None)
    e.pop("OPENAI_API_KEY", None)
    return e


def sh(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, cwd=ROOT, env=env(), capture_output=True, text=True)


def between(plan: list[tuple], start: int = 0, stop: int | None = None) -> list[tuple]:
    """The slices (offset, limit, worst) whose first item is at least `start` and below `stop` (None: to the end)."""
    return [s for s in plan if s[0] >= start and (stop is None or s[0] < stop)]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--from-offset", type=int, default=0)
    parser.add_argument("--to-offset", type=int, default=None)
    args = parser.parse_args()
    cfg = PanelConfig.from_yaml(args.config)
    rules = BudgetRules.from_yaml(ROOT / cfg.budget)
    cap = effective_run_cap(rules, cfg.max_usd)
    plan = between(S.slices(S.per_item_worst(cfg), cap), args.from_offset, args.to_offset)
    out = ROOT / cfg.out_dir / cfg.name
    total = 0.0
    account = ProviderRegistry.from_yaml(ROOT / cfg.providers).account_of(cfg.sources[0].ref)
    for offset, limit, worst in plan:
        spent, expected = anchor_spent(cfg, account), slice_expected(cfg, offset, limit)
        if spent + expected > K3[account]:
            print(f"{cfg.name} {offset}+{limit}: K3 guard: anchor spent ${spent:.2f} + expected ${expected:.2f} would pass "
                  f"${K3[account]:.0f} ({account})")
            return 1
        slice_args = ["--task-offset", str(offset), "--task-limit", str(limit)]
        check = sh(["aan", "check", args.config, *slice_args])
        if check.returncode != 0 or "cleared" not in check.stdout:
            print(f"{cfg.name} {offset}+{limit}: aan check refused\n{check.stdout[-800:]}{check.stderr[-400:]}")
            return 1
        run = sh(["aan", "run", args.config, *slice_args])
        status = json.loads((out / "status.json").read_text())
        shutil.copy(out / "status.json", out / f"status_items_{offset}.json")
        spent = float(status["budget"]["run_spent_usd"])
        total += spent
        print(f"{cfg.name} {offset}+{limit} (worst ${worst:.2f}): {status['state']} {status['reason']} "
              f"calls {status['calls']} live {status['live_calls']} ${spent:.3f}", flush=True)
        sh(["git", "add", str(out.relative_to(ROOT))])
        sh(["git", "commit", "-q", "-m", f"{cfg.name} slice {offset}+{limit}: {status['state']} (${spent:.3f})"])
        sh(["git", "push", "-q", "origin", "HEAD"])
        if run.returncode != 0 or status["state"] != "completed":
            print(f"STOPPED at {offset}+{limit}: {status['reason'] or run.stderr[-400:]}")
            return 1
    print(f"{cfg.name}: {len(plan)} slices completed, ${total:.3f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
