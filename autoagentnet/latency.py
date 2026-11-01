"""Per-call, per-stage and per-run timing and context columns (session M1; research/v4/measurement.md).

Plain words first.
  context tokens   everything the model reads in one call: input + cache-write + cache-read tokens.
  peak context     the largest context of any call: per stage, the largest in the stage; per run, the largest in the run.
  timing           the provider's stamps for one live call (providers/timing.py): time to first token (TTFT), time
                   to first answer token (TTFAT), first thinking event, decode speed, end-to-end rate, total
                   seconds, retries and the seconds lost to them, and the number of calls in flight when it was
                   sent (concurrency).
  timing_source    "measured" for a live call timed in this run; "estimated" for numbers inferred later from totals
                   (analysis/latency_backfill.py); missing for a cache hit, which carries no timing of this run and
                   keeps from_cache true.

`call_columns(output)` gives the columns appended to calls.csv (panel) and agents.csv (network); `stage_rows` and
`run_columns` give the network executor's per-stage table (stages.csv) and per-run columns (results.csv). Existing
columns keep their names and meaning; these are appended after them.
"""

from __future__ import annotations

import math

import pandas as pd

# columns appended to calls.csv and agents.csv, in this order
TIMING_COLUMNS = ["ttft_s", "ttfat_s", "t_first_thinking_s", "decode_tok_s", "e2e_tok_s", "total_s", "retries",
                  "retry_s", "concurrency", "streamed", "context_tokens", "timing_source", "ttft_kind",
                  "decode_basis", "http_status", "request_id", "region", "ratelimit_remaining_requests",
                  "ratelimit_remaining_tokens", "t_submit_utc"]
FROM_EXTRA = [c for c in TIMING_COLUMNS if c not in ("context_tokens", "timing_source", "total_s", "e2e_tok_s")]


def call_columns(output) -> dict:
    """The appended per-call columns of one AgentOutput. A cache hit keeps only context_tokens (a property of the
    call, not of this run); every timing column is missing. total_s equals the call's seconds (latency_s); e2e_tok_s
    is output tokens / total_s."""
    context = output.usage.prompt_tokens
    if output.from_cache or output.provider == "none":
        return {**{c: None for c in TIMING_COLUMNS}, "context_tokens": context}
    x = output.extra or {}
    total = float(output.latency_s)
    row = {c: x.get(c) for c in FROM_EXTRA}
    row.update(total_s=total, e2e_tok_s=output.usage.output_tokens / total if total > 0 else None,
               context_tokens=context, timing_source="measured")
    if "streamed" not in x:  # a provider without timing (the fake model, an older Maritime agent)
        row["streamed"] = None
    return {c: row.get(c) for c in TIMING_COLUMNS}


def imbalance(values: list[float]) -> float:
    """max / mean over stages: 1.0 when every stage is equal; NaN when the mean is 0 or there are no stages."""
    values = [v for v in values if v is not None and not (isinstance(v, float) and math.isnan(v))]
    if not values or sum(values) == 0:
        return math.nan
    return max(values) / (sum(values) / len(values))


def stage_rows(result) -> list[dict]:
    """One row per model-call stage of one network run (a NetworkResult; vote and exit stages make no call):
      calls                  model calls in the stage; live_calls, those made live in this run
      peak_context_tokens    the largest context of a call in the stage
      stage_latency_s        the slowest live call's seconds (cache hits carry no timing; missing if none is live)
      stage_critical_path_s  the executor's stage time (the cache-warming call, then the slowest of the rest)
      stage_ttfat_s          seconds from the stage's start to its first answer token, over its live streamed calls
                             (when the stage warmed the prompt cache, the later calls start after the first one)
      usd, output_tokens     the stage's dollars (cached calls at their original price) and output tokens"""
    rows = []
    for trace in result.stages:
        calls = [o for o in trace.outputs if o.provider != "none"]
        if not calls:
            continue
        live = [o for o in calls if not o.from_cache]
        offset = {id(o): (calls[0].latency_s if trace.warmed and o is not calls[0] else 0.0) for o in calls}
        ttfat = [offset[id(o)] + o.extra["ttfat_s"] for o in live if (o.extra or {}).get("ttfat_s") is not None]
        rows.append({
            "config_id": result.config_id, "task_id": result.task_id, "replicate": result.replicate,
            "stage": trace.stage, "calls": len(calls), "live_calls": len(live),
            "peak_context_tokens": max(o.usage.prompt_tokens for o in calls),
            "stage_latency_s": max(o.latency_s for o in live) if live else None,
            "stage_critical_path_s": trace.critical_path_s,
            "stage_ttfat_s": min(ttfat) if ttfat else None,
            "usd": sum(o.cost_usd for o in calls),
            "output_tokens": sum(o.usage.output_tokens for o in calls),
        })
    return rows


def run_columns(result) -> dict:
    """Per-run columns appended to results.csv:
      critical_path_ttfat_s   time until the final stage's first answer token if each stage runs its agents in
                              parallel: the earlier stages' critical paths plus the final stage's TTFAT (missing when
                              the final stage has no live streamed call)
      imbalance_context, imbalance_latency, imbalance_usd   max / mean over the run's model-call stages of peak
                              context, stage latency (slowest live call) and dollars"""
    rows = stage_rows(result)
    if not rows:
        return {"critical_path_ttfat_s": None, "imbalance_context": None, "imbalance_latency": None,
                "imbalance_usd": None}
    last = rows[-1]
    earlier = sum(r["stage_critical_path_s"] for r in rows[:-1])
    ttfat = None if last["stage_ttfat_s"] is None else earlier + last["stage_ttfat_s"]
    latency = [r["stage_latency_s"] for r in rows]
    return {
        "critical_path_ttfat_s": ttfat,
        "imbalance_context": imbalance([float(r["peak_context_tokens"]) for r in rows]),
        "imbalance_latency": imbalance([float(v) for v in latency]) if all(v is not None for v in latency) else None,
        "imbalance_usd": imbalance([r["usd"] for r in rows]),
    }


def stage_table(results) -> pd.DataFrame:
    """stages.csv: stage_rows over every run, in run order."""
    return pd.DataFrame([row for r in results for row in stage_rows(r)])


def quantiles(values: pd.Series) -> dict:
    """p50 and p95 of a numeric series (missing values dropped); both missing when it is empty."""
    v = pd.to_numeric(values, errors="coerce").dropna()
    if v.empty:
        return {"p50": None, "p95": None}
    return {"p50": float(v.quantile(0.5)), "p95": float(v.quantile(0.95))}


SDK_PACKAGES = ("autoagentnet", "anthropic", "openai", "httpx", "httpx2", "vllm")


def run_card(*, run_id: str, timing: bool | None, max_concurrency: int, model_ids: list[str],
             model_versions: list[str], runtime: str) -> dict:
    """results/<name>/run_card.json: what a latency number from this run depends on.
      date_utc            when the card was written (the run's end)
      host, container     the machine's name and whether it is a container (a cloud session's sandbox)
      network_path        "agent proxy" when outbound HTTPS goes through a proxy (HTTPS_PROXY set: cloud sessions),
                          else "direct"; the proxy's address is not recorded (it may carry credentials)
      python, packages    client and SDK versions (package metadata; no SDK is imported here)
      max_concurrency     the run's limit on calls in flight
      model_ids, model_versions   the model ids requested and the versions the providers reported
      timing              whether API requests were streamed and timed (None: each client's default)
      runtime             local or maritime (a Maritime agent's own client decides its timing)"""
    import os
    import platform
    import socket
    from datetime import datetime, timezone
    from importlib.metadata import PackageNotFoundError, version

    packages = {}
    for name in SDK_PACKAGES:
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            packages[name] = None
    proxied = any(os.getenv(k) for k in ("HTTPS_PROXY", "https_proxy"))
    return {
        "run_id": run_id,
        "date_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "host": socket.gethostname(),
        "container": os.path.exists("/.dockerenv") or os.path.exists("/run/.containerenv") or bool(os.getenv("CLAUDE_CODE_REMOTE")),
        "network_path": "agent proxy" if proxied else "direct",
        "python": platform.python_version(),
        "packages": packages,
        "max_concurrency": max_concurrency,
        "model_ids": sorted(set(model_ids)),
        "model_versions": sorted({str(v) for v in model_versions if v is not None}),
        "timing": timing,
        "runtime": runtime,
    }
