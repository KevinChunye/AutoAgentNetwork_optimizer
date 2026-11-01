"""Per-run rows and per-config summaries.

Column meanings:
  error               share of tasks answered wrongly (needs gold answers)
  recon_error         share of tasks whose final answer differs from the dense network's
  cost_usd            dollars at list price, prompt-cache aware; cached calls count at their
                      original price, so this is what the config costs when run on its own
  total_tokens        prompt + output tokens over all agent calls
  critical_path_s     latency if each stage runs its agents in parallel
  peak_context_tokens largest prompt any one agent read (the memory analog)
  flops               2 x active parameters x tokens (open-weight models only); MACs = flops / 2
  speedup             dense critical path / this config's critical path
  token_compression   dense tokens / this config's tokens
  cost_compression    dense dollars / this config's dollars
  truncation_rate     share of agent calls cut off by max_tokens
  unparsed_rate       share of final outputs with no "ANSWER:" line the grader can read
                      (for math answers: no clean LaTeX parse)
  visible_output_tokens  estimated tokens of the visible reply text (4 characters per token);
                      output_tokens well above it means hidden thinking / reasoning tokens
  hidden_token_ratio  output_tokens / visible_output_tokens
  recall_cue          1 when an agent's output says it leans on a remembered answer (RECALL_RE),
                      else 0; a descriptive contamination covariate, in agents.csv only

agent_rows() gives one row per agent call (used for the dense network): its stage,
answer, correctness, tokens and stop reason, for within-stage agreement and
hidden-token checks.

Appended in session M1 (latency.py has the definitions): agents.csv gains the per-call
timing and context columns (latency.TIMING_COLUMNS) and results.csv the per-run
critical-path TTFAT and stage imbalance ratios (latency.run_columns).
"""

from __future__ import annotations

import math
import re

import pandas as pd

from .latency import call_columns, run_columns
from .network.executor import NetworkResult
from .providers.base import estimate_tokens
from .tasks import Task, agree, answer_parsed, extract_answer, is_correct

VISIBLE_CHARS_PER_TOKEN = 4.0  # the pre-registered P0 definition of visible tokens; kept fixed
# recall_cue: the output says it leans on a remembered competition answer ("known answer", "HMMT",
# "recall", ...). A descriptive covariate for contamination, fixed before P2b (plan, amendment 6, rule 41).
RECALL_RE = re.compile(
    r"known (?:answer|result)|\b(?:HMMT|AIME|AMC|IMO)\b|\brecall|\bremember|from memory|well[- ]known|standard result",
    re.IGNORECASE,
)


def result_row(result: NetworkResult, task: Task, dense: NetworkResult | None) -> dict:
    usage = result.usage
    correct = is_correct(result.final, task.answer, task.grader)
    return {
        "network": result.network,
        "config_id": result.config_id,
        "task_id": result.task_id,
        "replicate": result.replicate,
        "agents": sum(result.keep),
        "calls": len(result.calls),
        "live_calls": result.live_calls,
        "truncated_calls": result.truncated_calls,
        **usage.model_dump(),
        "total_tokens": usage.total_tokens,
        "visible_output_tokens": sum(estimate_tokens(o.content, VISIBLE_CHARS_PER_TOKEN) for o in result.calls),
        "cost_usd": result.cost_usd,
        "flops": math.nan if result.flops is None else result.flops,
        "critical_path_s": result.critical_path_s,
        "peak_context_tokens": result.peak_context_tokens,
        "answer": extract_answer(result.final),
        "parsed": float(answer_parsed(result.final, task.grader)),
        "correct": math.nan if correct is None else float(correct),
        "agrees_with_dense": math.nan if dense is None else float(agree(result.final, dense.final, task.grader)),
        "exit_stage": result.exit_stage or "",
        "escalated": ",".join(result.escalated),
        **run_columns(result),
    }


def agent_rows(result: NetworkResult, task: Task) -> list[dict]:
    """One row per agent call of one network run."""
    rows = []
    for stage in result.stages:
        for o in stage.outputs:
            correct = is_correct(o.content, task.answer, task.grader)
            rows.append(
                {
                    "config_id": result.config_id,
                    "task_id": result.task_id,
                    "replicate": result.replicate,
                    "stage": stage.stage,
                    "agent_id": o.agent_id,
                    "answer": extract_answer(o.content),
                    "grader": task.grader,
                    "correct": math.nan if correct is None else float(correct),
                    **o.usage.model_dump(),
                    "visible_output_tokens": estimate_tokens(o.content, VISIBLE_CHARS_PER_TOKEN),
                    "recall_cue": float(bool(RECALL_RE.search(o.content))),
                    "cost_usd": o.cost_usd,
                    "stop_reason": o.stop_reason,
                    "latency_s": o.latency_s,
                    "from_cache": o.from_cache,
                    **call_columns(o),
                }
            )
    return rows


def summarize(rows: pd.DataFrame, dense_config_id: str) -> pd.DataFrame:
    df = rows.assign(
        error=1 - rows["correct"],
        recon_error=1 - rows["agrees_with_dense"],
        unparsed_rate=1 - rows["parsed"],
        truncation_rate=rows["truncated_calls"] / rows["calls"],
    )
    columns = [
        "agents", "error", "recon_error", "cost_usd", "total_tokens", "output_tokens", "visible_output_tokens",
        "critical_path_s", "peak_context_tokens", "flops", "truncation_rate", "unparsed_rate",
    ]
    summary = df.groupby("config_id")[columns].mean()
    summary["runs"] = df.groupby("config_id").size()
    summary["hidden_token_ratio"] = summary["output_tokens"] / summary["visible_output_tokens"]
    if dense_config_id not in summary.index:  # e.g. a run stopped before the dense network finished
        summary[["speedup", "token_compression", "cost_compression"]] = math.nan
        return summary.sort_values("total_tokens")
    dense = summary.loc[dense_config_id]
    summary["speedup"] = dense["critical_path_s"] / summary["critical_path_s"]
    summary["token_compression"] = dense["total_tokens"] / summary["total_tokens"]
    summary["cost_compression"] = dense["cost_usd"] / summary["cost_usd"].replace(0, math.nan)
    return summary.sort_values("total_tokens")
