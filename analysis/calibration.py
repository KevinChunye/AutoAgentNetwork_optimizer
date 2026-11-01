"""P0 calibration: what each model ref really does per call, from the ledger and agents.csv.

Per experiment named p0_* (one per model ref):
  calls                 live calls in the ledger
  prompt_ratio          actual prompt tokens (input + cache write + cache read) / the estimate made before the
                        call (3 characters per token since protocol v2); above 1 means worst cases run low
  prompt_ratio_rule17   prompt_ratio / 0.75: actual tokens against estimated x 3/4, the yardstick of plan
                        amendment 3, rule 17 (its prediction: 1.0 to 1.4)
  output_tokens         mean billed output tokens per call (hidden thinking included)
  visible_tokens        mean estimated tokens of the visible reply (from agents.csv)
  hidden_ratio          output_tokens / visible_tokens; well above 1 = hidden thinking or reasoning tokens.
                        A ratio of means: calls cut off at max_tokens with no visible text inflate it
  hidden_ratio_completed_min / _median / _max
                        output / visible tokens per call, over calls that finished (not cut off at max_tokens);
                        read next to truncated_share (audit 5)
  truncated_share       share of calls that stopped at max_tokens
  stop_reasons          counts of each stop reason
  latency_s_mean / max  wall-clock seconds per live call
  cost_per_call_usd     mean actual dollars per call

Usage: python -m analysis.calibration
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from autoagentnet.meter import Ledger
from autoagentnet.providers.base import TRUNCATED_STOP_REASONS

from .common import ROOT, save_table


def calibration_table(ledger: Ledger, results_dir: Path = ROOT / "results", prefix: str = "p0_") -> pd.DataFrame:
    df = ledger.to_frame()
    if df.empty:
        return pd.DataFrame()
    df["experiment"] = df["run_id"].str.rsplit("-", n=1).str[0]
    df = df[df["experiment"].str.startswith(prefix)].copy()
    if df.empty:
        return pd.DataFrame()
    df["prompt_tokens"] = df["input_tokens"] + df["cache_write_tokens"] + df["cache_read_tokens"]
    df["truncated"] = df["stop_reason"].isin(TRUNCATED_STOP_REASONS)
    out = df.groupby(["experiment", "model"]).agg(
        calls=("cost_usd", "size"),
        prompt_tokens=("prompt_tokens", "mean"),
        estimated_prompt_tokens=("estimated_prompt_tokens", "mean"),
        output_tokens=("output_tokens", "mean"),
        truncated_share=("truncated", "mean"),
        latency_s_mean=("latency_s", "mean"),
        latency_s_max=("latency_s", "max"),
        cost_per_call_usd=("cost_usd", "mean"),
    ).reset_index()
    out["prompt_ratio"] = out["prompt_tokens"] / out["estimated_prompt_tokens"]
    out["prompt_ratio_rule17"] = out["prompt_ratio"] / 0.75
    reasons = df.groupby("experiment")["stop_reason"].value_counts().rename("n").reset_index()
    reasons["text"] = reasons["stop_reason"].astype(str) + ":" + reasons["n"].astype(str)
    out["stop_reasons"] = out["experiment"].map(reasons.groupby("experiment")["text"].agg(" ".join))
    visible, per_call = {}, []
    for exp in out["experiment"]:
        agents_csv = results_dir / exp / "agents.csv"
        if agents_csv.exists():
            agents = pd.read_csv(agents_csv, dtype={"answer": str})
            visible[exp] = agents["visible_output_tokens"].mean()
            if {"output_tokens", "stop_reason"} <= set(agents.columns):
                done = agents[~agents["stop_reason"].isin(TRUNCATED_STOP_REASONS) & (agents["visible_output_tokens"] > 0)]
                per_call.append(pd.DataFrame({"experiment": exp, "ratio": done["output_tokens"] / done["visible_output_tokens"]}))
    out["visible_tokens"] = out["experiment"].map(visible)
    out["hidden_ratio"] = out["output_tokens"] / out["visible_tokens"]
    if per_call:
        ratios = pd.concat(per_call).groupby("experiment")["ratio"]
        for stat in ["min", "median", "max"]:
            out[f"hidden_ratio_completed_{stat}"] = out["experiment"].map(ratios.agg(stat))
    return out


def main(ledger_path: Path = ROOT / "state/ledger.jsonl") -> pd.DataFrame:
    table = calibration_table(Ledger(ledger_path, must_exist=True))
    if table.empty:
        print("no p0_* calls in the ledger yet")
        return table
    save_table(table.round(4), "p0_calibration")
    print(table.round(3).to_string(index=False))
    return table


if __name__ == "__main__":
    main()
