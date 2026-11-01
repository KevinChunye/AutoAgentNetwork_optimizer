"""One experiment = one network, one task set, a list of pruned configs.

Every config runs on every task; the dense network always runs too, as the
reference for reconstruction error. Tasks run in chunks. After each chunk the
run (1) gzips the cache shard and commits + pushes state/ so nothing paid for is
lost, (2) writes partial results, and (3) checks the experiment's expectations;
a miss, or a budget cap, stops the run early with status "stopped".

Outputs in results/<name>/: results.csv (one row per task x config x replicate),
summary.csv (one row per config), agents.csv (one row per agent call of the dense
network, for within-stage agreement and hidden-token checks) and status.json
(why the run ended, spend). Session M1 adds stages.csv (one row per model-call stage
of every run: calls, peak context, slowest live call, TTFAT, dollars, output tokens;
latency.stage_rows) and run_card.json (date, network path, SDK versions, concurrency
limit, models, timing on or off; latency.run_card).
Re-running is safe and cheap: finished calls come from the call cache.
"""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict

from .agents.agent import prompt_text
from .agents.spec import AgentOutput, AgentRequest
from .budget import BudgetExceeded, BudgetRules, SpendGovernor
from .cache import CallCache, make_key
from .latency import run_card, stage_table
from .meter import Ledger
from .metrics import agent_rows, result_row, summarize
from .network.executor import NetworkExecutor
from .network.spec import NetworkSpec, PruneConfig
from .persist import git_checkpoint
from .pricing import PriceBook
from .providers.base import TRUNCATED_STOP_REASONS, Usage, estimate_tokens
from .providers.registry import ProviderRegistry
from .pruning.space import PruneSpace
from .runtime.local import LocalRuntime
from .runtime.maritime import MaritimeRuntime
from .tasks import Task, load_tasks


class Expectations(BaseModel):
    """Sanity checks run after every chunk once `min_tasks` tasks are done. Any miss
    stops the run, so money is not spent on a setup that is not behaving as planned.

    dense_error_range:           allowed [low, high] error of the dense network; outside it the
                                 task is too easy (nothing to prune) or the pipeline is broken
    max_dense_cost_per_task_usd: dense-network dollars per task; catches token blow-ups such
                                 as hidden reasoning tokens
    max_truncation_rate:         share of agent calls cut off by max_tokens, over the whole run and
                                 within each stage, over the distinct calls of every config (one
                                 aggregator call in 19 hides in the pooled rate; audits 6 and 7)
    max_unparsed_rate:           share of final outputs with no "ANSWER:" line
    """

    min_tasks: int = 10
    dense_error_range: tuple[float, float] | None = None
    max_dense_cost_per_task_usd: float | None = None
    max_truncation_rate: float | None = 0.05
    max_unparsed_rate: float | None = 0.10


class Factorial(BaseModel):
    """Run a grid of keep levels per stage instead of listing configs (PruneSpace.factorial)."""

    model_config = ConfigDict(extra="forbid")
    levels: list[int]


class Prereg(BaseModel):
    """Written and committed in the experiment file before a paid run (protocol rule 4);
    `aan check` and `aan run` refuse a paid run without it.

    question:   the open question this run answers
    prediction: the result expected, with numbers
    kill:       the result that stops this line of work
    decision:   what happens next for each outcome
    """

    model_config = ConfigDict(extra="forbid")
    question: str
    prediction: str
    kill: str
    decision: str


class ExperimentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")  # a typo in a YAML key is an error, not a silent default

    name: str
    network: str  # path to a network YAML
    tasks: str  # path to a JSONL task file
    items: str | None = None  # optional file of task ids, one per line: the tasks run, in that order (sealed lists)
    task_offset: int = 0  # skip this many tasks (for disjoint calibration / validation / test slices)
    task_limit: int | None = None
    configs: Literal["all"] | Factorial | list[list[int] | PruneConfig] = []  # keep lists or full PruneConfigs
    prereg: Prereg | None = None  # required for paid runs
    replicates: int = 1  # independent samples of every call (replicate 0 reuses the cache)
    model_override: str | None = None  # route every agent to this model ref, e.g. "fake"
    max_usd: float | None = None  # optional run cap for this config; None = only the phase and hard caps apply
    chunk_size: int = 10  # tasks per chunk
    expect: Expectations = Expectations()
    runtime: Literal["local", "maritime"] = "local"
    maritime: str = "configs/runtime/maritime.yaml"
    providers: str = "configs/providers.yaml"
    pricing: str = "configs/pricing.yaml"
    budget: str = "configs/budget.yaml"
    ledger: str = "state/ledger.jsonl"  # tracked in git: the project bill
    cache: str = "state/cache"  # tracked in git: every paid call, re-usable for free
    require_ledger: bool = True  # refuse to run if the ledger file is missing
    git_checkpoint: bool = True  # commit + push state/ after every chunk
    out_dir: str = "results"
    max_concurrency: int = 8
    warm_cache_first: bool = True
    timing: bool = False  # session M1: true streams every API request and records TTFT, TTFAT, decode speed (transport
    # only). New configs set it to true; the default stays false (audit M1-1) until the timing probe has run with no
    # stream failure, since a stream cut mid-reply raises StreamCut and is not retried

    @classmethod
    def from_yaml(cls, path: str | Path) -> "ExperimentConfig":
        return cls(**yaml.safe_load(Path(path).read_text()))

    def model_override_resolved(self) -> str | None:
        return self.model_override or os.getenv("AAN_MODEL_OVERRIDE")


def prune_configs(cfg: ExperimentConfig, network: NetworkSpec) -> list[PruneConfig]:
    """The dense config first, then the requested ones."""
    dense = PruneConfig.dense(network)
    if cfg.configs == "all":
        configs = PruneSpace(network).configs()
    elif isinstance(cfg.configs, Factorial):
        configs = PruneSpace(network).factorial(cfg.configs.levels)
    else:
        configs = [c if isinstance(c, PruneConfig) else PruneConfig(keep=c) for c in cfg.configs]
    others = [c for c in configs if c.config_id != dense.config_id]
    return [dense, *others]


def select_tasks(cfg: ExperimentConfig) -> list[Task]:
    tasks = load_tasks(cfg.tasks)
    if cfg.items:
        by_id = {t.id: t for t in tasks}
        tasks = [by_id[i] for i in Path(cfg.items).read_text().split() if i]
    tasks = tasks[cfg.task_offset:]
    return tasks[: cfg.task_limit] if cfg.task_limit else tasks


def check_expectations(rows: pd.DataFrame, summary: pd.DataFrame, dense_id: str, expect: Expectations,
                       agents: pd.DataFrame | None = None) -> list[str]:
    """Return the expectations the results so far violate (empty = all fine).
    `agents` is the table of distinct calls of every config (call_table), for the per-stage truncation check."""
    n_tasks = rows["task_id"].nunique()
    if n_tasks < expect.min_tasks or dense_id not in summary.index:
        return []
    dense = summary.loc[dense_id]
    misses = []
    if expect.dense_error_range is not None and not math.isnan(dense["error"]):
        low, high = expect.dense_error_range
        if not low <= dense["error"] <= high:
            misses.append(f"dense error {dense['error']:.2f} outside [{low}, {high}] after {n_tasks} tasks")
    if expect.max_dense_cost_per_task_usd is not None and dense["cost_usd"] > expect.max_dense_cost_per_task_usd:
        misses.append(f"dense cost ${dense['cost_usd']:.4f}/task above ${expect.max_dense_cost_per_task_usd}")
    truncation = rows["truncated_calls"].sum() / rows["calls"].sum()
    if expect.max_truncation_rate is not None and truncation > expect.max_truncation_rate:
        misses.append(f"{truncation:.1%} of calls truncated by max_tokens (limit {expect.max_truncation_rate:.0%})")
    if expect.max_truncation_rate is not None and agents is not None and not agents.empty:
        truncated = agents.assign(truncated=agents["stop_reason"].isin(TRUNCATED_STOP_REASONS))
        by_stage = truncated.groupby("stage")["truncated"].mean().sort_values(ascending=False)
        for stage, rate in by_stage[by_stage > expect.max_truncation_rate].items():
            misses.append(f"{rate:.1%} of {stage} calls truncated by max_tokens (limit {expect.max_truncation_rate:.0%})")
    unparsed = 1 - rows["parsed"].mean()
    if expect.max_unparsed_rate is not None and unparsed > expect.max_unparsed_rate:
        misses.append(f"{unparsed:.1%} of final outputs have no ANSWER line the grader can read (limit {expect.max_unparsed_rate:.0%})")
    return misses


def build_tables(results, tasks: list[Task], dense_id: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    dense_by_task = {(r.task_id, r.replicate): r for r in results if r.config_id == dense_id}
    task_by_id = {t.id: t for t in tasks}
    rows = pd.DataFrame(
        [result_row(r, task_by_id[r.task_id], dense_by_task.get((r.task_id, r.replicate))) for r in results]
    )
    return rows, summarize(rows, dense_id)


def call_table(results) -> pd.DataFrame:
    """One row per distinct agent call across every config (stage and stop reason). Configs share
    calls, so a call is counted once: same task, replicate, stage, agent and reply. The per-stage
    truncation stop reads this table, so a pruned config's own calls count too (audit 7, finding 1)."""
    import hashlib

    rows = [{"task_id": r.task_id, "replicate": r.replicate, "stage": stage.stage, "agent_id": o.agent_id,
             "digest": hashlib.sha256(o.content.encode()).hexdigest(), "stop_reason": o.stop_reason}
            for r in results for stage in r.stages for o in stage.outputs]
    return pd.DataFrame(rows).drop_duplicates(["task_id", "replicate", "stage", "agent_id", "digest"])


def dense_agent_table(results, tasks: list[Task], dense_id: str) -> pd.DataFrame:
    task_by_id = {t.id: t for t in tasks}
    return pd.DataFrame(
        [row for r in results if r.config_id == dense_id for row in agent_rows(r, task_by_id[r.task_id])]
    )


async def run_experiment(cfg: ExperimentConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    network = NetworkSpec.from_yaml(cfg.network)
    tasks = select_tasks(cfg)
    registry = ProviderRegistry.from_yaml(cfg.providers)
    registry.set_timing(cfg.timing)
    run_id = f"{cfg.name}-{int(time.time())}"
    override = cfg.model_override_resolved()
    if override and registry.provider_of(override) == "fake":
        # Dry run: nothing is spent, so nothing tracked (ledger, cache, results) is touched.
        out_dir = "runs/dry" if cfg.out_dir == "results" else cfg.out_dir
        cfg = cfg.model_copy(update={"git_checkpoint": False, "out_dir": out_dir})
        ledger, cache = Ledger(), CallCache()
    else:
        ledger = Ledger(cfg.ledger, must_exist=cfg.require_ledger)
        cache = CallCache(cfg.cache, shard_prefix=run_id)
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    runtime = LocalRuntime(registry) if cfg.runtime == "local" else MaritimeRuntime.from_yaml(cfg.maritime)
    executor = NetworkExecutor(
        network,
        runtime,
        registry,
        pricebook=PriceBook.from_yaml(cfg.pricing),
        cache=cache,
        governor=governor,
        model_override=override,
        max_concurrency=cfg.max_concurrency,
        warm_cache_first=cfg.warm_cache_first,
        run_id=run_id,
    )
    configs = prune_configs(cfg, network)
    dense_id = configs[0].config_id
    out = Path(cfg.out_dir) / cfg.name
    out.mkdir(parents=True, exist_ok=True)

    results: list = []
    rows, summary, agents = pd.DataFrame(), pd.DataFrame(), pd.DataFrame()
    status = {"run_id": run_id, "state": "completed", "reason": "", "checkpoints": []}
    errors: list[BaseException] = []
    try:
        for chunk_index, start in enumerate(range(0, len(tasks), cfg.chunk_size)):
            chunk = tasks[start : start + cfg.chunk_size]
            jobs = [executor.run(t, c, r) for t in chunk for c in configs for r in range(cfg.replicates)]
            outcomes = await asyncio.gather(*jobs, return_exceptions=True)
            results += [o for o in outcomes if not isinstance(o, BaseException)]
            errors = [o for o in outcomes if isinstance(o, BaseException)]

            cache.rotate()
            if cfg.git_checkpoint:
                note = git_checkpoint([cfg.ledger, cfg.cache], f"state: {run_id} chunk {chunk_index}")
                status["checkpoints"].append(note)

            if results:
                rows, summary = build_tables(results, tasks, dense_id)
                rows.to_csv(out / "results.csv", index=False)
                summary.to_csv(out / "summary.csv")
                dense_agent_table(results, tasks, dense_id).to_csv(out / "agents.csv", index=False)
                stage_table(results).to_csv(out / "stages.csv", index=False)
                agents = call_table(results)

            budget_errors = [e for e in errors if isinstance(e, BudgetExceeded)]
            if budget_errors:
                status.update(state="stopped", reason=f"budget: {budget_errors[0]}")
                break
            if errors:
                status.update(state="failed", reason=f"{type(errors[0]).__name__}: {errors[0]}")
                break
            misses = check_expectations(rows, summary, dense_id, cfg.expect, agents)
            if misses:
                status.update(state="stopped", reason="expectation missed: " + "; ".join(misses))
                break
    finally:
        await runtime.aclose()
        status["tasks_done"] = int(rows["task_id"].nunique()) if not rows.empty else 0
        status["budget"] = governor.status()
        status["rate_limits"] = registry.rate_limits()  # sets max_concurrency and run sizes (audit 1, finding 7)
        (out / "status.json").write_text(json.dumps(status, indent=2))
        calls = [o for r in results for o in r.calls]
        card = run_card(run_id=run_id, timing=cfg.timing, max_concurrency=cfg.max_concurrency,
                        model_ids=[registry.model_id(ref) for ref in registry.built_refs()],
                        model_versions=[(o.extra or {}).get("model_version") or o.model for o in calls],
                        runtime=cfg.runtime)
        (out / "run_card.json").write_text(json.dumps(card, indent=2))

    if status["state"] == "failed":
        raise errors[0]
    return rows, summary, status


class EstimatingRuntime:
    """Pretends to run every agent and records each call's worst-case cost.

    Replies are dummy answers of the full max_tokens length, so downstream prompts
    are as long as they can get. Nothing is spent. The estimate ignores calls
    already in the real cache, so it is an upper bound.
    """

    def __init__(self, registry: ProviderRegistry, pricebook: PriceBook):
        self.registry = registry
        self.pricebook = pricebook
        self.calls: list[dict] = []

    async def call(self, request: AgentRequest) -> AgentOutput:
        ref = request.spec.model
        model_id, provider = self.registry.model_id(ref), self.registry.provider_of(ref)
        prompt_tokens = estimate_tokens(prompt_text(request.spec, request.input))
        max_tokens = request.spec.max_tokens
        self.calls.append(
            {
                "account": self.registry.account_of(ref),
                "model": model_id,
                "worst_case_usd": self.pricebook.worst_case_usd(model_id, provider, prompt_tokens, max_tokens),
            }
        )
        unique = make_key(request.model_dump())[:12]  # distinct replies keep distinct downstream calls
        return AgentOutput(
            agent_id=request.spec.agent_id,
            content=unique + "x" * max(max_tokens * 4 - 24, 0) + "\nANSWER: 0",
            usage=Usage(input_tokens=prompt_tokens, output_tokens=max_tokens),
            provider=provider,
            model=model_id,
            latency_s=0.0,
            stop_reason="end_turn",
        )

    async def aclose(self) -> None:
        return None


async def estimate_experiment(cfg: ExperimentConfig) -> pd.DataFrame:
    """Worst-case cost of running `cfg`, by account and model, before spending anything."""
    network = NetworkSpec.from_yaml(cfg.network)
    registry = ProviderRegistry.from_yaml(cfg.providers)
    pricebook = PriceBook.from_yaml(cfg.pricing)
    runtime = EstimatingRuntime(registry, pricebook)
    unlimited = BudgetRules(hard_caps_usd={registry.account_of(ref): math.inf for ref in registry.models})
    executor = NetworkExecutor(
        network,
        runtime,
        registry,
        pricebook=pricebook,
        cache=CallCache(),
        governor=SpendGovernor(Ledger(), unlimited),
        model_override=cfg.model_override_resolved(),
        warm_cache_first=False,
        worst_case_paths=True,
    )
    configs = prune_configs(cfg, network)
    tasks = select_tasks(cfg)
    await asyncio.gather(*(executor.run(t, c, r) for t in tasks for c in configs for r in range(cfg.replicates)))
    calls = pd.DataFrame(runtime.calls)
    table = calls.groupby(["account", "model"]).agg(
        calls=("worst_case_usd", "size"), worst_case_usd=("worst_case_usd", "sum")
    )
    table["worst_case_x_safety"] = table["worst_case_usd"] * BudgetRules.from_yaml(cfg.budget).safety_multiplier
    return table


def is_dry_run(cfg: ExperimentConfig) -> bool:
    override = cfg.model_override_resolved()
    return bool(override) and ProviderRegistry.from_yaml(cfg.providers).provider_of(override) == "fake"


def preflight(cfg: ExperimentConfig, config_path: str | Path) -> tuple[list[str], pd.DataFrame | None]:
    """The deterministic gate before a paid run. Returns (problems, estimate table);
    an empty problem list means the run may start. Dry runs always pass.

    Checks, in order:
      1. the experiment file has a `prereg:` block (question, prediction, kill, decision);
      2. the file is committed and unchanged, so git history proves the prediction came first;
      3. the worst case of the whole run (x safety) fits the run cap, the phase cap and
         every hard cap, given what the ledger has already spent.
    """
    if is_dry_run(cfg):
        return [], None
    table = asyncio.run(estimate_experiment(cfg))
    return gate_problems(cfg, config_path, table), table


def gate_problems(cfg, config_path: str | Path, table: pd.DataFrame) -> list[str]:
    """Checks 1-3 of preflight for any run config with prereg, ledger, require_ledger, budget and
    max_usd fields (experiment and market configs), given its worst-case table by account."""
    import subprocess

    problems = []
    if cfg.prereg is None:
        problems.append("no prereg block: add question / prediction / kill / decision to the experiment file")
    path = str(config_path)
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", path], capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", path], capture_output=True).returncode == 0
    if not (tracked and clean):
        problems.append(f"commit {path} (with its prereg) before running it")
    governor = SpendGovernor(Ledger(cfg.ledger, must_exist=cfg.require_ledger),
                             BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    reservations = []
    try:
        for account, amount in table.groupby(level="account")["worst_case_usd"].sum().items():
            reservations.append(governor.reserve(account, float(amount)))
    except BudgetExceeded as exc:
        problems.append(f"worst case does not fit: {exc}. Split the run (--task-offset/--task-limit) or ask Kevin")
    finally:
        for r in reservations:
            governor.release(r)
    return problems
