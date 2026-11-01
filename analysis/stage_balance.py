"""Stage balance (session M1, section 5.3; exploratory, $0): does a network whose stages are more evenly loaded reach
higher accuracy at the same total tokens?

Plain words first.
  stage load       per task, for each model-call stage: the largest context any of its calls read, its slowest
                   call's seconds and its dollars.
  imbalance ratio  max / mean over a run's stages of one load (1.0 = every stage equal), per task, then averaged
                   over tasks for a configuration.
  matched tokens   configurations are compared at the same total tokens by regression: accuracy on log(total tokens)
                   and the imbalance ratio, one point per configuration. The imbalance coefficient is the accuracy
                   change per unit of imbalance at fixed tokens; its interval is a 95% bootstrap over tasks (B = 500,
                   seed 0; every configuration is recomputed on the resampled tasks).

Data: the pilot's P4 factorial grid (dense_3x6, keep levels 1, 3, 6 per stage, 27 configurations, 80 BBEH gate
items, Haiku with thinking off), replayed exactly from the call cache (state/cache). The replay refuses any call that
is not cached, so it spends nothing. These configurations are nested in the sense the replay needs: every call of
every configuration was made and cached in P4. Latencies are each cached call's original measurement.

Outputs: research/v4/measurement/stage_balance.md, tables/stage_balance_configs.csv, tables/stage_balance_tasks.csv.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoagentnet.cache import CallCache  # noqa: E402
from autoagentnet.experiment import ExperimentConfig, prune_configs, select_tasks  # noqa: E402
from autoagentnet.network.executor import NetworkExecutor  # noqa: E402
from autoagentnet.network.spec import NetworkSpec  # noqa: E402
from autoagentnet.pricing import PriceBook  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402
from autoagentnet.tasks import is_correct  # noqa: E402

OUT = ROOT / "research/v4/measurement"
GRID = [f"configs/experiments/pilot/p4_bbeh_grid_{x}.yaml" for x in "abcdefghijklmnop"]
B, SEED = 500, 0


class CacheOnly:
    """A runtime that never calls a model: a replay must find every call in the cache."""

    async def call(self, request):
        raise RuntimeError(f"not in the cache: {request.spec.agent_id} on {request.input.task_id} (replay spends nothing)")

    async def aclose(self) -> None:
        return None


def stage_loads(result) -> list[dict]:
    """Per model-call stage of one run: peak context, slowest call (cached calls keep their measured seconds),
    dollars and output tokens."""
    rows = []
    for trace in result.stages:
        calls = [o for o in trace.outputs if o.provider != "none"]
        if calls:
            rows.append({"stage": trace.stage, "calls": len(calls),
                         "peak_context": max(o.usage.prompt_tokens for o in calls),
                         "latency_s": max(o.latency_s for o in calls), "usd": sum(o.cost_usd for o in calls),
                         "output_tokens": sum(o.usage.output_tokens for o in calls)})
    return rows


def md_table(frame: pd.DataFrame, index: bool = False) -> str:
    """A markdown table without the optional `tabulate` dependency."""
    frame = frame.reset_index() if index else frame
    head = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([head, rule, *body])


def ratio(values) -> float:
    v = np.asarray(values, float)
    return float(v.max() / v.mean()) if len(v) and v.mean() > 0 else float("nan")


async def replay_grid(cache: CallCache) -> pd.DataFrame:
    rows = []
    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    pricebook = PriceBook.from_yaml(ROOT / "configs/pricing.yaml")
    for path in GRID:
        cfg = ExperimentConfig.from_yaml(ROOT / path)
        network = NetworkSpec.from_yaml(ROOT / cfg.network)
        executor = NetworkExecutor(network, CacheOnly(), registry, pricebook=pricebook, cache=cache,
                                   model_override=cfg.model_override, max_concurrency=cfg.max_concurrency,
                                   warm_cache_first=cfg.warm_cache_first, run_id="replay")
        for task in select_tasks(cfg.model_copy(update={"tasks": str(ROOT / cfg.tasks)})):
            for prune in prune_configs(cfg, network):
                result = await executor.run(task, prune)
                loads = stage_loads(result)
                rows.append({"run": cfg.name, "config_id": prune.config_id, "task_id": task.id,
                             "agents": sum(prune.keep), "correct": float(bool(is_correct(result.final, task.answer, task.grader))),
                             "total_tokens": result.usage.total_tokens, "usd": result.cost_usd,
                             "critical_path_s": result.critical_path_s,
                             "imbalance_context": ratio([r["peak_context"] for r in loads]),
                             "imbalance_latency": ratio([r["latency_s"] for r in loads]),
                             "imbalance_usd": ratio([r["usd"] for r in loads]),
                             "peak_context": max(r["peak_context"] for r in loads),
                             "max_stage_context": loads[int(np.argmax([r["peak_context"] for r in loads]))]["stage"]})
    return pd.DataFrame(rows)


def by_config(tasks: pd.DataFrame) -> pd.DataFrame:
    return tasks.groupby("config_id").agg(
        agents=("agents", "first"), tasks=("task_id", "nunique"), accuracy=("correct", "mean"),
        total_tokens=("total_tokens", "mean"), usd=("usd", "mean"), critical_path_s=("critical_path_s", "mean"),
        peak_context=("peak_context", "mean"), imbalance_context=("imbalance_context", "mean"),
        imbalance_latency=("imbalance_latency", "mean"), imbalance_usd=("imbalance_usd", "mean")).reset_index()


def coefficients(configs: pd.DataFrame) -> dict:
    """OLS of accuracy on log(total tokens) and each imbalance ratio in turn (one point per configuration)."""
    out = {}
    for col in ("imbalance_context", "imbalance_latency", "imbalance_usd"):
        X = np.column_stack([np.ones(len(configs)), np.log(configs["total_tokens"]), configs[col]])
        beta, *_ = np.linalg.lstsq(X, configs["accuracy"].to_numpy(float), rcond=None)
        out[col] = float(beta[2])
    return out


def main() -> None:
    cache = CallCache(ROOT / "state/cache")  # read only: the replay refuses any call it would have to make
    tasks = asyncio.run(replay_grid(cache))
    configs = by_config(tasks)
    point = coefficients(configs)
    rng = np.random.default_rng(SEED)
    ids = tasks["task_id"].unique()
    draws = []
    for _ in range(B):
        pick = pd.DataFrame({"task_id": rng.choice(ids, len(ids))})
        draws.append(coefficients(by_config(pick.merge(tasks, on="task_id"))))
    draws = pd.DataFrame(draws)
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    tasks.to_csv(OUT / "tables/stage_balance_tasks.csv", index=False)
    configs.to_csv(OUT / "tables/stage_balance_configs.csv", index=False)
    corr = configs[["accuracy", "imbalance_context", "imbalance_latency", "imbalance_usd", "total_tokens"]].corr(method="spearman")
    lines = ["# Stage balance and accuracy at matched tokens (session M1, 5.3, exploratory)", "",
             "Made by `analysis/stage_balance.py`: the pilot's P4 factorial grid (27 configurations x "
             f"{tasks['task_id'].nunique()} BBEH gate items, Haiku thinking off) replayed exactly from the call cache "
             "($0; the replay refuses any uncached call). Definitions are in the script's docstring.", "",
             "## Does a lower imbalance ratio reach higher accuracy at the same total tokens?", "",
             "Accuracy regressed on log(total tokens) and one imbalance ratio, one point per configuration; 95% "
             f"bootstrap over tasks (B = {B}).", "",
             "| imbalance of | coefficient (accuracy per unit of ratio) | 95% interval |", "|---|---|---|"]
    for col, value in point.items():
        lo, hi = draws[col].quantile([0.025, 0.975])
        lines.append(f"| {col.removeprefix('imbalance_')} | {value:+.3f} | [{lo:+.3f}, {hi:+.3f}] |")
    lines += ["", "Spearman correlations over the 27 configurations:", "", md_table(corr.round(2), index=True), "",
              "## Configurations", "", md_table(configs.sort_values("total_tokens").round(4)), "",
              "Reading: an interval that includes 0 means the cached grid cannot tell whether balance matters at "
              "fixed tokens. The grid varies stage widths only (1, 3, 6), so imbalance and total tokens move "
              "together; designs that change balance at fixed tokens (fan-in, compression; patching.md) need new "
              "calls, because a communicating network's later stages read different inputs and cannot be replayed.", ""]
    (OUT / "stage_balance.md").write_text("\n".join(lines))
    print("\n".join(lines[:16]))


if __name__ == "__main__":
    main()
