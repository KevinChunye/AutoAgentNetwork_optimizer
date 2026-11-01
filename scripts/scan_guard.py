"""The K2 scan's running stop (session E5, audit 68 item 4): run before every scan config or slice.

    python scripts/scan_guard.py <config.yaml> [--task-offset N] [--task-limit M]   # exit 0 = may start, 1 = stop

Plain words. K2 caps the whole landscape scan at $3. The governor caps each run; nothing caps the scan's runs taken
together, so before each one this script adds
  spent     dollars the ledger has billed to every run of the same scan so far (run ids starting with the scan's
            prefix, `SCANS`), and
  expected  the run's expected dollars: per source, its items in this slice x its calls x its guard dollars per call
            (the config's expect.usd_per_call, the probe-measured cost the stop rules already use),
and refuses (exit 1) if spent + expected would pass the cap. It reads the ledger and never writes anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoagentnet.evidence.panel import PanelConfig, read_ids  # noqa: E402
from autoagentnet.meter import Ledger  # noqa: E402

CAP_USD = 3.0
SCANS = ("e50_scan_", "e52_scan_")  # each K2 scan has its own $3: the landscape scan (e50) and the Sonnet scan (e52)


def spent_usd(ledger_path: str | Path, prefix: str = SCANS[0]) -> float:
    frame = Ledger(ledger_path, must_exist=True).to_frame()
    if frame.empty:
        return 0.0
    return float(frame.loc[frame["run_id"].astype(str).str.startswith(prefix), "cost_usd"].sum())


def expected_usd(cfg: PanelConfig) -> float:
    ids = read_ids(ROOT / cfg.items)[cfg.task_offset:]
    ids = ids[: cfg.task_limit] if cfg.task_limit else ids
    total = 0.0
    for s in cfg.sources:
        mine = ids if s.items is None else [i for i in ids if i in set(read_ids(ROOT / s.items))]
        if s.ref not in cfg.expect.usd_per_call:
            raise KeyError(f"{cfg.name}: no guard dollars per call for {s.ref}")
        total += len(mine) * s.calls * cfg.expect.usd_per_call[s.ref]
    return total


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--task-offset", type=int, default=0)
    parser.add_argument("--task-limit", type=int, default=None)
    args = parser.parse_args()
    cfg = PanelConfig.from_yaml(args.config).model_copy(update={"task_offset": args.task_offset,
                                                                "task_limit": args.task_limit})
    prefix = next((p for p in SCANS if cfg.name.startswith(p)), None)
    if prefix is None:
        raise ValueError(f"{cfg.name} is not a scan run")
    spent, expected = spent_usd(ROOT / cfg.ledger, prefix), expected_usd(cfg)
    verdict = "may start" if spent + expected <= CAP_USD else "STOP"
    print(f"{cfg.name} items {args.task_offset}+{args.task_limit}: scan spent ${spent:.3f} + expected ${expected:.3f}"
          f" = ${spent + expected:.3f} of ${CAP_USD:.2f}: {verdict}")
    return 0 if verdict == "may start" else 1


if __name__ == "__main__":
    sys.exit(main())
