"""Latency backfill for every run so far (session M1, section 4; $0, read-only over results/).

Plain words first.
  live call        a call made against the API in that run (from_cache false). Cache hits repeat an earlier call's
                   numbers, so only live calls enter the fits.
  arm              one model ref at one setting (configs/providers.yaml), e.g. haiku_nothink, sonnet_max. Panel runs
                   name it in `ref`; network runs take it from their experiment file (model_override, else the
                   network's default model).
  total seconds    a call's measured wall-clock (`seconds` in calls.csv, `latency_s` in agents.csv): request sent to
                   reply complete, SDK retries included, under whatever concurrency the run used.
  context tokens   everything the call read: input + cache-write + cache-read tokens.
  e2e rate         output tokens / total seconds.
  median regression  total seconds = overhead + output tokens / decode speed, fitted at the median (least absolute
                   deviations, robust to the slow tail). The intercept (overhead) estimates time to first token plus
                   network and queue time; 1 / slope estimates the decode speed in output tokens per second, thinking
                   included. Both are estimates from totals, not stream measurements (timing_source "estimated").
                   Intervals: 95% percentile bootstrap over calls (B = 200, seed 0).
  stage profile    for network runs with stages: per task and stage the largest context, the slowest call and the
                   stage's dollars; the imbalance ratio of a run is max / mean over its stages (1.0 = balanced).

Grades: no `correct` or `answer` column is read here. Study CD's grades are E6's single read (session E6); this
script reads tokens, dollars and seconds only.

Outputs (research/v4/measurement/): backfill.md; tables/latency_by_arm.csv; tables/stage_profile.csv;
tables/calls_backfill.csv.gz (one row per call of every run: context_tokens, e2e_tok_s, timing_source).
Run: python analysis/latency_backfill.py
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = ROOT / "research/v4/measurement"
B, SEED = 200, 0
CALL_COLUMNS = ["item", "task_kind", "source", "ref", "model", "setting", "call", "input_tokens", "cache_write_tokens",
                "cache_read_tokens", "output_tokens", "thinking_tokens", "cost_usd", "seconds", "stop_reason",
                "truncated", "from_cache", "model_version"]
AGENT_COLUMNS = ["config_id", "task_id", "replicate", "stage", "agent_id", "input_tokens", "cache_write_tokens",
                 "cache_read_tokens", "output_tokens", "thinking_tokens", "cost_usd", "stop_reason", "latency_s",
                 "from_cache"]
SLOW_RATE = 50.0  # output tokens per second below which an arm's estimated decode speed is flagged for streaming


def experiment_ref(run: str) -> str | None:
    """The model ref of a network run: its experiment file's model_override, else its network's default model."""
    for path in sorted((ROOT / "configs/experiments").rglob("*.yaml")):
        cfg = yaml.safe_load(path.read_text()) or {}
        if cfg.get("name") == run:
            if cfg.get("model_override"):
                return cfg["model_override"]
            net = yaml.safe_load((ROOT / cfg["network"]).read_text())
            return net.get("default_model")
    return None


def load_panel_calls(results: Path = RESULTS) -> pd.DataFrame:
    """Every panel calls.csv: tokens, dollars and seconds only (no grade columns are read)."""
    frames = []
    for path in sorted(results.glob("*/calls.csv")):
        frame = pd.read_csv(path, usecols=lambda c: c in CALL_COLUMNS, low_memory=False)
        if "seconds" not in frame:
            continue
        frame = frame.assign(run=path.parent.name, kind="panel",
                             arm=frame["ref"] if "ref" in frame else frame.get("source"))
        frames.append(frame)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def load_agent_calls(results: Path = RESULTS) -> pd.DataFrame:
    """Every network agents.csv (the dense config's calls), with the run's model ref as the arm."""
    frames = []
    for path in sorted(results.glob("*/agents.csv")):
        frame = pd.read_csv(path, usecols=lambda c: c in AGENT_COLUMNS, low_memory=False)
        frames.append(frame.rename(columns={"latency_s": "seconds", "task_id": "item"}).assign(
            run=path.parent.name, kind="network", arm=experiment_ref(path.parent.name)))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def per_call(calls: pd.DataFrame) -> pd.DataFrame:
    """The backfilled per-call columns: context_tokens, e2e_tok_s and timing_source = "estimated"."""
    out = calls.copy()
    for col in ("input_tokens", "cache_write_tokens", "cache_read_tokens", "output_tokens", "thinking_tokens"):
        out[col] = pd.to_numeric(out[col], errors="coerce").fillna(0) if col in out else 0
    out["from_cache"] = out["from_cache"].astype(str).str.lower().eq("true")
    out["context_tokens"] = out["input_tokens"] + out["cache_write_tokens"] + out["cache_read_tokens"]
    out["seconds"] = pd.to_numeric(out["seconds"], errors="coerce")
    out["e2e_tok_s"] = (out["output_tokens"] / out["seconds"]).where(out["seconds"] > 0)
    out["timing_source"] = np.where(out["from_cache"], None, "estimated")
    return out


def median_fit(x: np.ndarray, y: np.ndarray) -> tuple[float, float]:
    """(intercept, slope) of the median regression y = a + b x (least absolute deviations)."""
    import statsmodels.api as sm

    if len(np.unique(x)) < 2:
        return float(np.median(y)), float("nan")
    fit = sm.QuantReg(y, sm.add_constant(x, has_constant="add")).fit(q=0.5, max_iter=5000)
    return float(fit.params[0]), float(fit.params[1])


def arm_fit(part: pd.DataFrame, b: int = B, seed: int = SEED) -> dict:
    """The median regression of one arm's live calls, with bootstrap intervals for the overhead and decode speed."""
    x, y = part["output_tokens"].to_numpy(float), part["seconds"].to_numpy(float)
    a, s = median_fit(x, y)
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(b if len(x) >= 10 else 0):
        idx = rng.integers(0, len(x), len(x))
        draws.append(median_fit(x[idx], y[idx]))
    draws = np.array(draws) if draws else np.zeros((0, 2))
    speed = 1 / draws[:, 1][draws[:, 1] > 0] if len(draws) else np.array([])
    return {"overhead_s": a, "overhead_lo": float(np.quantile(draws[:, 0], 0.025)) if len(draws) else None,
            "overhead_hi": float(np.quantile(draws[:, 0], 0.975)) if len(draws) else None,
            "decode_tok_s": 1 / s if s > 0 else None,
            "decode_lo": float(np.quantile(speed, 0.025)) if len(speed) else None,
            "decode_hi": float(np.quantile(speed, 0.975)) if len(speed) else None}


def by_arm(calls: pd.DataFrame, b: int = B) -> pd.DataFrame:
    """Per arm, live calls only: counts, p50 and p95 total seconds, the median regression, tokens and dollars."""
    live = calls[~calls["from_cache"] & calls["seconds"].notna() & calls["arm"].notna()]
    rows = []
    for arm, part in live.groupby("arm"):
        row = {"arm": arm, "model": part["model"].dropna().iloc[0] if "model" in part and part["model"].notna().any() else None,
               "calls": len(part), "runs": part["run"].nunique(),
               "p50_s": float(part["seconds"].quantile(0.5)), "p95_s": float(part["seconds"].quantile(0.95)),
               "output_tokens_p50": float(part["output_tokens"].median()),
               "thinking_tokens_mean": float(part["thinking_tokens"].mean()),
               "context_tokens_p50": float(part["context_tokens"].median()),
               "usd_per_call": float(pd.to_numeric(part["cost_usd"], errors="coerce").mean()),
               "e2e_tok_s_p50": float(part["e2e_tok_s"].median()), **arm_fit(part, b)}
        rows.append(row)
    table = pd.DataFrame(rows).sort_values(["model", "arm"], na_position="last").reset_index(drop=True)
    table["flag"] = np.where(table["decode_tok_s"].fillna(np.inf) < SLOW_RATE, "slow: confirm by streaming", "")
    return table


def stage_profile(agents: pd.DataFrame) -> pd.DataFrame:
    """Per staged network run (more than one stage): for each stage, the mean over tasks of its largest context, its
    slowest call and its dollars; the stage with the largest share; and the imbalance ratio max / mean over stages.
    Cached rows count with their original numbers here (agents.csv keeps each call's measured seconds), since a
    staged run's profile is a property of the network, not of which run paid for the call."""
    staged = agents[agents.groupby("run")["stage"].transform("nunique") > 1]
    if staged.empty:
        return pd.DataFrame()
    per = staged.groupby(["run", "config_id", "item", "replicate", "stage"], sort=False).agg(
        peak_context=("context_tokens", "max"), latency_s=("seconds", "max"),
        usd=("cost_usd", "sum")).reset_index()
    order = {s: k for k, s in enumerate(staged["stage"].drop_duplicates())}
    mean = per.groupby(["run", "config_id", "stage"]).agg(tasks=("item", "nunique"), peak_context=("peak_context", "mean"),
                                                         latency_s=("latency_s", "mean"), usd=("usd", "mean")).reset_index()
    mean = mean.assign(order=mean["stage"].map(order)).sort_values(["run", "config_id", "order"])
    rows = []
    for (run, config), part in mean.groupby(["run", "config_id"], sort=False):
        row = {"run": run, "config_id": config, "tasks": int(part["tasks"].max()),
               "stages": ",".join(part["stage"])}
        for col in ("peak_context", "latency_s", "usd"):
            v = part[col].astype(float)
            row[f"{col}_by_stage"] = ",".join(f"{x:.4g}" for x in v)
            row[f"imbalance_{col}"] = float(v.max() / v.mean()) if v.mean() > 0 else None
            row[f"max_stage_{col}"] = part["stage"].iloc[int(v.to_numpy().argmax())]
        rows.append(row)
    return pd.DataFrame(rows)


def fmt(x, digits=1):
    return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{digits}f}"


def report(arms: pd.DataFrame, stages: pd.DataFrame, calls: pd.DataFrame) -> str:
    live = calls[~calls["from_cache"]]
    lines = [
        "# Latency backfill: every run so far (session M1, estimates from totals)", "",
        "Made by `analysis/latency_backfill.py` from every `results/*/calls.csv` and `results/*/agents.csv`; no grade "
        "column is read. Every number below is **estimated** from each call's total seconds and tokens (timing_source "
        "\"estimated\"); none is a stream measurement. Definitions are in the script's docstring and in "
        "`research/v4/measurement.md`.", "",
        f"- Calls: {len(calls):,} rows in {calls['run'].nunique()} runs, {len(live):,} of them live (cache hits are "
        "left out of every fit).",
        "- Total seconds include the agent proxy path of the cloud sessions, the run's concurrency (usually 8) and the "
        "provider's load at that hour; they are not a clean single-request latency.",
        "- Overhead (the intercept) estimates time to first token plus network and queue time; decode speed (1 / "
        "slope) estimates output tokens per second, thinking included. Intervals: 95% bootstrap over calls.", "",
        "## Per arm (live calls)", "",
        "| arm | model | calls | p50 s | p95 s | overhead s [95%] | decode tok/s [95%] | output p50 | thinking mean | "
        "context p50 | $/call | flag |", "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in arms.itertuples():
        lines.append(f"| {r.arm} | {r.model or ''} | {r.calls:,} | {fmt(r.p50_s)} | {fmt(r.p95_s)} | "
                     f"{fmt(r.overhead_s, 2)} [{fmt(r.overhead_lo, 2)}, {fmt(r.overhead_hi, 2)}] | "
                     f"{fmt(r.decode_tok_s, 0)} [{fmt(r.decode_lo, 0)}, {fmt(r.decode_hi, 0)}] | "
                     f"{fmt(r.output_tokens_p50, 0)} | {fmt(r.thinking_tokens_mean, 0)} | {fmt(r.context_tokens_p50, 0)} | "
                     f"{r.usd_per_call:.5f} | {r.flag} |")
    lines += ["", "## Stage profile of staged runs", "",
              "Mean over tasks per stage, then max / mean over stages (1.0 = balanced). Cached rows keep their original "
              "measured seconds here.", "",
              "| run | config | tasks | stages | context by stage | imbalance (max stage) | latency s by stage | "
              "imbalance (max stage) | $ by stage | imbalance (max stage) |", "|---|---|---|---|---|---|---|---|---|---|"]
    for r in stages.itertuples():
        lines.append(f"| {r.run} | {r.config_id} | {r.tasks} | {r.stages} | {r.peak_context_by_stage} | "
                     f"{fmt(r.imbalance_peak_context, 2)} ({r.max_stage_peak_context}) | {r.latency_s_by_stage} | "
                     f"{fmt(r.imbalance_latency_s, 2)} ({r.max_stage_latency_s}) | {r.usd_by_stage} | "
                     f"{fmt(r.imbalance_usd, 2)} ({r.max_stage_usd}) |")
    return "\n".join(lines) + "\n"


def main(argv=None) -> None:
    calls = per_call(pd.concat([load_panel_calls(), load_agent_calls()], ignore_index=True))
    arms = by_arm(calls)
    stages = stage_profile(calls[calls["kind"] == "network"])
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    arms.to_csv(OUT / "tables/latency_by_arm.csv", index=False)
    stages.to_csv(OUT / "tables/stage_profile.csv", index=False)
    keep = ["run", "kind", "arm", "model", "item", "source", "call", "config_id", "stage", "agent_id", "context_tokens",
            "output_tokens", "thinking_tokens", "cost_usd", "seconds", "e2e_tok_s", "from_cache", "timing_source"]
    calls[[c for c in keep if c in calls]].to_csv(OUT / "tables/calls_backfill.csv.gz", index=False)
    (OUT / "backfill.md").write_text(report(arms, stages, calls))
    print(arms[["arm", "calls", "p50_s", "p95_s", "overhead_s", "decode_tok_s", "decode_lo", "decode_hi", "flag"]].round(2).to_string())


if __name__ == "__main__":
    main(sys.argv[1:])
