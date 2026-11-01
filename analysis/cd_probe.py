"""Study CD's cost probe (session E6, section 4.2; research/v4/cd/probe.md): tokens and dollars per arm, never accuracy.

    python -m analysis.cd_probe            # prints the table and writes research/v4/cd/probe_costs.md

Plain words. For each probe run (results/e60_cd_probe_*/calls.csv) and each arm (source) and family:
  calls            calls made;
  output_mean, output_p90, output_p99, output_max
                   output tokens per call (thinking included); p99 is the 99th percentile;
  thinking_mean    measured thinking tokens per call (usage.output_tokens_details.thinking_tokens; OpenAI's reasoning
                   tokens);
  truncated        share of calls cut by the ceiling; unparsed: share with no readable answer;
  usd_mean         dollars per call as billed; seconds_mean: wall-clock seconds per call (both over live calls only:
                   a call served from the cache costs nothing and takes no time, audit 98);
  ceiling_main     the main run's ceiling the probe sets: output_p99 x 1.5, rounded up to a multiple of 1,024, at least
                   4,096 (a cut call counts at its ceiling, which it reports as its output);
  guard_main       the main run's guard dollars per call: usd_mean x 1.5.
Only these columns are read from calls.csv; the grade columns are never loaded.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd

from autoagentnet.ladder.core import markdown_table

ROOT = Path(__file__).resolve().parents[1]
COLUMNS = ["item", "task_kind", "source", "ref", "call", "parsed", "output_tokens", "thinking_tokens", "cost_usd",
           "seconds", "truncated", "stop_reason", "from_cache"]


def probe_calls(results: Path = ROOT / "results") -> pd.DataFrame:
    frames = [pd.read_csv(p, usecols=lambda c: c in COLUMNS) for p in sorted(results.glob("e60_cd_probe_*/calls.csv"))]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=COLUMNS)


def ceiling(p99: float) -> int:
    return max(4096, int(math.ceil(1.5 * p99 / 1024) * 1024))


def table(calls: pd.DataFrame) -> pd.DataFrame:
    calls = calls.assign(thinking_tokens=calls["thinking_tokens"].fillna(0) if "thinking_tokens" in calls else 0)
    live = ~calls["from_cache"].fillna(False).astype(bool) if "from_cache" in calls else pd.Series(True, calls.index)
    calls = calls.assign(cost_usd=calls["cost_usd"].where(live), seconds=calls["seconds"].where(live))
    out = calls.groupby(["ref", "task_kind"]).agg(
        calls=("item", "size"), output_mean=("output_tokens", "mean"),
        output_p90=("output_tokens", lambda x: x.quantile(0.9)), output_p99=("output_tokens", lambda x: x.quantile(0.99)),
        output_max=("output_tokens", "max"), thinking_mean=("thinking_tokens", "mean"),
        truncated=("truncated", "mean"), unparsed=("parsed", lambda x: 1 - x.astype(bool).mean()),
        usd_mean=("cost_usd", "mean"), seconds_mean=("seconds", "mean")).reset_index()
    return out.assign(ceiling_main=out["output_p99"].map(ceiling), guard_main=1.5 * out["usd_mean"]).sort_values(
        ["task_kind", "ref"]).reset_index(drop=True)


def stage2_cells(t: pd.DataFrame, spent: float, cap: float = 6.0, items_left: int = 7) -> pd.DataFrame:
    """The probe's stage-2 rule (research/v4/cd/probe.md, audit 98): each cell (ref x family) projected at items_left x
    its stage-1 mean dollars per call; cells taken in ascending projected cost while spent + the taken cells' projections
    stays at or under cap. Returns every cell with its projection and whether it is taken."""
    cells = t[["ref", "task_kind", "usd_mean"]].assign(projected=lambda d: items_left * d["usd_mean"])
    cells = cells.sort_values(["projected", "ref", "task_kind"]).reset_index(drop=True)
    return cells.assign(taken=spent + cells["projected"].cumsum() <= cap)


def main() -> pd.DataFrame:
    t = table(probe_calls())
    text = "\n".join(["# Study CD probe: tokens and dollars per arm (no accuracy)", "",
                      "Written by `python -m analysis.cd_probe` (definitions in its docstring).", "",
                      markdown_table(t.round(4)), ""])
    (ROOT / "research/v4/cd/probe_costs.md").write_text(text)
    print(text)
    return t


if __name__ == "__main__":
    main()
