"""Data for the pilot demo page (reports/pilot/demo/data.json). Everything is computed from
the repo's own code and configs; nothing here is a model result.

  configs         every keep config of dense_3x6: calls per task and the worst-case dollars per
                  task when run on its own (the governor's bound: every prompt token at the
                  cache-write rate, every agent writing its full max_tokens), averaged over the
                  calibration slice of the chosen task file, model ref haiku_nothink
  shared_calls    distinct agent calls per task when all 216 configs run together (call cache)
  grid_calls      the same for the protocol-v2 factorial grid (1, 3 or 6 agents per stage: 27 configs)
  stages          the dense network's stages: width, max_tokens, worst-case prompt tokens per agent
  plan / spend    protocol allocations, ledger spend, recorded estimates

It also renders reports/pilot/demo/pilot_demo.html from analysis/demo_template.html.

Usage: python -m analysis.demo_data data/external/omni_d44_61.jsonl
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import pandas as pd

from autoagentnet.experiment import EstimatingRuntime
from autoagentnet.meter import Ledger
from autoagentnet.network.executor import NetworkExecutor
from autoagentnet.network.spec import NetworkSpec, PruneConfig
from autoagentnet.cache import CallCache
from autoagentnet.budget import BudgetRules, SpendGovernor
from autoagentnet.pricing import PriceBook
from autoagentnet.providers.registry import ProviderRegistry
from autoagentnet.pruning.space import PruneSpace
from autoagentnet.tasks import load_tasks

from .budget import PLAN_USD, spend_by_run
from .common import REPORT, ROOT

GRID_LEVELS = [1, 3, 6]  # the P4 factorial grid (protocol v2)


def worst_case_by_config(task_file: Path, ref: str = "haiku_nothink", n_tasks: int = 20) -> tuple[pd.DataFrame, float, float, pd.DataFrame]:
    network = NetworkSpec.from_yaml(ROOT / "configs/networks/dense_3x6.yaml")
    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    pricebook = PriceBook.from_yaml(ROOT / "configs/pricing.yaml")
    tasks = load_tasks(task_file)[:n_tasks]
    unlimited = BudgetRules(hard_caps_usd={registry.account_of(r): float("inf") for r in registry.models})

    def executor(runtime, cache=None):
        return NetworkExecutor(network, runtime, registry, pricebook=pricebook, cache=cache or CallCache(),
                               governor=SpendGovernor(Ledger(), unlimited), model_override=ref, warm_cache_first=False)

    rows = []
    for config in PruneSpace(network).configs():
        runtime = EstimatingRuntime(registry, pricebook)
        asyncio.run(_run_all(executor(runtime), tasks, [config]))
        cost = sum(c["worst_case_usd"] for c in runtime.calls) / len(tasks)
        rows.append({"id": config.config_id, "keep": config.keep[:3], "calls": sum(config.keep), "worst_usd": cost})
    shared = EstimatingRuntime(registry, pricebook)
    asyncio.run(_run_all(executor(shared), tasks, PruneSpace(network).configs()))
    shared_calls = len(shared.calls) / len(tasks)
    grid = EstimatingRuntime(registry, pricebook)
    asyncio.run(_run_all(executor(grid), tasks, PruneSpace(network).factorial(GRID_LEVELS)))
    grid_calls = len(grid.calls) / len(tasks)

    dense = EstimatingRuntime(registry, pricebook)
    asyncio.run(_run_all(executor(dense), tasks, [PruneConfig.dense(network)]))
    per_call = pd.DataFrame(dense.calls)
    return pd.DataFrame(rows), shared_calls, grid_calls, per_call


async def _run_all(executor, tasks, configs):
    await asyncio.gather(*(executor.run(t, c) for t in tasks for c in configs))


def results_tables() -> dict:
    """The hand-back's result tables (session 4), when they exist: headline comparisons and the designs scoreboard."""
    out = {}
    for name in ["headline", "designs"]:
        path = REPORT / "tables" / f"{name}.csv"
        if path.exists():
            table = pd.read_csv(path)
            out[name] = table.astype(object).where(table.notna(), None).to_dict("records")
    return out


def main(task_file: str = "data/external/bbeh_gate.jsonl") -> Path:
    path = ROOT / task_file
    configs, shared_calls, grid_calls, _ = worst_case_by_config(path)
    network = NetworkSpec.from_yaml(ROOT / "configs/networks/dense_3x6.yaml")
    prices = PriceBook.from_yaml(ROOT / "configs/pricing.yaml").price("claude-haiku-5-5", "anthropic")
    ledger = Ledger(ROOT / "state/ledger.jsonl", must_exist=True)
    rules = BudgetRules.from_yaml(ROOT / "configs/budget.yaml")
    estimates = pd.read_csv(ROOT / "research/estimates.csv") if (ROOT / "research/estimates.csv").exists() else pd.DataFrame()
    cards = []
    cards_path = ROOT / "data/external/cards.jsonl"
    if cards_path.exists():
        cards = [json.loads(line) for line in cards_path.read_text().splitlines() if line.strip()]
    import subprocess

    collected = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT, capture_output=True, text=True)
    n_tests = sum(1 for line in collected.stdout.splitlines() if "::" in line)
    data = {
        "task_file": task_file,
        "n_tests": n_tests,
        "configs": configs.round(6).to_dict("records"),
        "shared_calls_per_task": shared_calls,
        "grid_calls_per_task": grid_calls,
        "grid_levels": GRID_LEVELS,
        "naive_calls_per_task": int(configs["calls"].sum()),
        "stages": [{"name": s.name, "width": s.width, "max_tokens": s.max_tokens or network.default_max_tokens,
                    "perspectives": s.perspectives} for s in network.stages],
        "prices": prices.model_dump(),
        "plan_usd": PLAN_USD,
        "spent": {a: ledger.spent_usd(a) for a in rules.hard_caps_usd},
        "spent_by_step": spend_by_run(ledger).groupby("step")["actual_usd"].sum().to_dict(),
        "caps": {"hard": rules.hard_caps_usd, "phase": rules.active_phase.total_usd, "run": rules.active_phase.max_run_usd,
                 "safety": rules.safety_multiplier},
        "estimates": estimates.astype(object).where(estimates.notna(), None).to_dict("records"),  # NaN is not valid JSON
        "cards": [{k: c.get(k) for k in ["name", "source", "hf_id", "licence", "grader", "where", "tasks_after_filter",
                                         "banding_pool", "splits"]} for c in cards],
        **results_tables(),
    }
    out = REPORT / "demo" / "data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=1, default=str))
    page = REPORT / "demo" / "pilot_demo.html"
    template = Path(__file__).with_name("demo_template.html").read_text()
    page.write_text(template.replace("__DATA__", json.dumps(data, default=str).replace("</", "<\\/")))
    print(f"wrote {out} and {page}: {len(configs)} configs, {shared_calls:.0f} shared calls/task vs {data['naive_calls_per_task']} naive")
    return page


if __name__ == "__main__":
    main(*sys.argv[1:])
