"""Run many frozen PHOENIX branch configs concurrently inside ONE process (`kind: phoenix_batch`).

Why one process: the SpendGovernor's reservations and the Ledger's running totals live in memory, so two `aan`
processes would not see each other's spend. Here every branch shares one governor and one ledger:
- every check, reservation, release and settlement (which appends to the ledger) happens under one lock, so
  the summed worst case of all calls in flight never passes a cap (hard, account, phase, run);
- an identical request made by two branches at once is paid once: a per-request-key lock makes the second
  branch wait and read the call cache, exactly as it would in serial order;
- each branch runs in its own thread with its own event loop and provider clients; its CPU is its thread's CPU
  plus its own tool processes' CPU (engine.py thread_time, tools.run_child os.wait4), so concurrency does not
  move CPU between branches.

Each branch still passes its own gate (preflight_phoenix: frozen hashes, prereg, committed config, clean tree),
and the batch passes the summed gate. State (ledger, cache) and each branch's result files are committed and
pushed once per completed chunk of branches. A rerun of the same batch skips finished branches and resumes the
others from their own state.json.
"""
from __future__ import annotations

import asyncio
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import Field

from ..budget import BudgetRules, SpendGovernor
from ..cache import CallCache, make_key
from ..experiment import Prereg, gate_problems
from ..market.caller import MarketCaller
from ..meter import Ledger
from ..persist import code_version, git_checkpoint
from ..pricing import PriceBook
from ..runtime.local import LocalRuntime
from .run import PhoenixConfig, estimate_phoenix, frozen_inputs, is_free, preflight_phoenix, registry_for
from .store import atomic_json
from .types import Strict, digest

# Statuses after which a branch is finished; anything else (error, a missing file) is retried on resume.
FINISHED = ("completed", "validation_ceiling", "no_positive_feasible_plan", "limits_reached", "budget_stopped",
            "selector_pool_unavailable", "wall_stopped")
# Small per-branch files committed with the state; fitted models, features and tool scratch stay local.
COMMITTED_FILES = ("status.json", "state.json", "events.jsonl", "calls.jsonl", "trajectory.json",
                   "recovery_plan.json", "frozen.json", "calibration_state.json", "capability_table.json", "calls.json")


class PhoenixBatchConfig(Strict):
    """A list of frozen branch configs run together. task_offset/task_limit select a slice of `branches`."""
    kind: Literal["phoenix_batch"] = "phoenix_batch"
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    prereg: Prereg | None = None
    branches: list[str] = Field(min_length=1)
    concurrency: int = Field(default=4, ge=1, le=8)
    chunk_size: int | None = Field(default=None, ge=1)  # branches per state commit; default = concurrency
    max_usd: float | None = Field(default=None, gt=0)  # optional run cap for the whole batch
    model_override: str | None = None
    task_offset: int = Field(default=0, ge=0)
    task_limit: int | None = Field(default=None, ge=1)
    providers: str = "configs/providers.yaml"
    pricing: str = "configs/pricing.yaml"
    budget: str = "configs/budget.yaml"
    ledger: str = "state/ledger.jsonl"
    cache: str = "state/cache"
    require_ledger: bool = True
    git_checkpoint: bool = True
    out_dir: str = "results"

    @classmethod
    def from_yaml(cls, path):
        return cls.model_validate(yaml.safe_load(Path(path).read_text()))

    def model_override_resolved(self):
        if self.model_override not in (None, "fake"):
            raise ValueError("only the explicit offline fake override is supported")
        return self.model_override

    def selected(self) -> list[str]:
        end = None if self.task_limit is None else self.task_offset + self.task_limit
        return self.branches[self.task_offset:end]

    def branch_configs(self) -> list[tuple[str, PhoenixConfig]]:
        out = []
        for path in self.selected():
            cfg = PhoenixConfig.from_yaml(path)
            if self.model_override:
                cfg = cfg.model_copy(update={"model_override": self.model_override})
                cfg._source = str(path)
            out.append((str(path), cfg))
        return out


def is_batch_config(path) -> bool:
    raw = yaml.safe_load(Path(path).read_text())
    return isinstance(raw, dict) and raw.get("kind") == "phoenix_batch"


class LockedGovernor(SpendGovernor):
    """A SpendGovernor safe to share between threads: one lock around every read and change of reservations,
    run spend and the ledger."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._lock = threading.RLock()

    def check(self, account, worst_case_usd):
        with self._lock:
            return super().check(account, worst_case_usd)

    def reserve(self, account, worst_case_usd):
        with self._lock:
            return super().reserve(account, worst_case_usd)

    def release(self, reservation):
        with self._lock:
            return super().release(reservation)

    def settle(self, reservation, record):
        with self._lock:
            return super().settle(reservation, record)

    def room_by_account(self):
        with self._lock:
            return super().room_by_account()

    def status(self):
        with self._lock:
            return super().status()


class LockedCache(CallCache):
    """A CallCache safe to share between threads (one lock around reads, appends and shard rotation)."""
    def __init__(self, *args, **kwargs):
        self._lock = threading.RLock()
        super().__init__(*args, **kwargs)

    def get(self, key):
        with self._lock:
            return super().get(key)

    def put(self, key, value):
        with self._lock:
            return super().put(key, value)

    def rotate(self):
        with self._lock:
            return super().rotate()


class KeyLocks:
    """One lock per call-cache key, created on first use."""
    def __init__(self):
        self._guard, self._locks = threading.Lock(), {}

    def get(self, key) -> threading.Lock:
        with self._guard:
            if key not in self._locks:
                self._locks[key] = threading.Lock()
            return self._locks[key]


class BatchCaller(MarketCaller):
    """MarketCaller whose identical requests across branches are serialised: the first pays, the rest hit the cache."""
    def __init__(self, *args, key_locks: KeyLocks, **kwargs):
        super().__init__(*args, **kwargs)
        self.key_locks = key_locks

    async def call(self, request, replicate):
        ref = request.spec.model
        key = make_key(request.spec.model_dump(), self.registry.model_id(ref), self.registry.options_of(ref),
                       request.input.model_dump(), replicate)
        lock = self.key_locks.get(key)
        # Each branch runs alone on its own thread and event loop, so blocking here only pauses this branch.
        with lock:
            return await super().call(request, replicate)


def estimate_batch(bcfg: PhoenixBatchConfig) -> pd.DataFrame:
    """Worst case by account: the sum over branches of each branch's own worst case (estimate_phoenix)."""
    tables = [estimate_phoenix(cfg).reset_index() for _, cfg in bcfg.branch_configs()]
    frame = pd.concat(tables, ignore_index=True)
    table = frame.groupby(["account", "model"]).agg(worst_case_usd=("worst_case_usd", "sum"),
                                                     worst_case_x_safety=("worst_case_x_safety", "sum"))
    return table.sort_values("worst_case_usd", ascending=False)


def preflight_batch(bcfg: PhoenixBatchConfig, config_path):
    """Every branch's own gate, then the batch's: prereg, committed manifest, and the summed worst case fits."""
    problems, branches = [], bcfg.branch_configs()
    names = [cfg.name for _, cfg in branches]
    if len(set(names)) != len(names):
        problems.append("branch names must be unique within a batch")
    free_flags = []
    for path, cfg in branches:
        free_flags.append(is_free(cfg, registry_for(cfg)))
        branch_problems, _ = preflight_phoenix(cfg, path)
        problems.extend(f"{cfg.name}: {p}" for p in branch_problems)
    if any(free_flags) and not all(free_flags):
        problems.append("a batch is either entirely offline (fake) or entirely paid")
    if all(free_flags):
        return problems, None
    table = None
    try:
        table = estimate_batch(bcfg)
        problems.extend(gate_problems(bcfg, config_path, table))
    except (OSError, ValueError, KeyError) as exc:
        problems.append(f"batch preflight failed: {exc}")
    return problems, table


def _finished(out: Path, run_id: str) -> bool:
    path = out / "status.json"
    if not path.exists():
        return False
    status = json.loads(path.read_text())
    return status.get("run_id") == run_id and status.get("status") in FINISHED


async def _run_branch(cfg: PhoenixConfig, shared: dict) -> dict:
    """run_phoenix without its own ledger, governor, cache or git checkpoint: those are the batch's."""
    registry = registry_for(cfg)
    free = shared["free"]
    out = Path(cfg.out_dir) / (("fake_" if free else "") + cfg.name)
    out.mkdir(parents=True, exist_ok=True)
    cache = LockedCache(out / "call_cache") if free else shared["cache"]
    runtime = LocalRuntime(registry)
    run_id = "phoenix_" + digest({"config": cfg.model_dump(), "inputs": frozen_inputs(cfg)})[:24]
    caller = BatchCaller(runtime, registry, pricebook=PriceBook.from_yaml(cfg.pricing), cache=cache,
                         governor=shared["governor"], run_id=run_id, market="phoenix", condition=cfg.policy,
                         purpose="phoenix." + cfg.mode, key_locks=shared["key_locks"])
    try:
        try:
            if cfg.mode == "calibrate":
                from .calibrate import run_calibration
                status = await run_calibration(cfg, caller, out, free)
            else:
                from .engine import RecoveryEngine
                engine = RecoveryEngine.open(cfg, caller, out, free=free, tool_factory=shared["tool_factory"])
                status = await engine.run()
        except Exception as exc:
            status = {"status": "error", "error_type": type(exc).__name__, "reason": str(exc)[:600]}
            if cfg.mode == "calibrate" and (out / "calibration_state.json").exists():
                partial = json.loads((out / "calibration_state.json").read_text())
                # Keep the error visible: the saved calibration status goes beside it, never over it
                # (smoke audit SC-2); an unknown model charge still takes precedence.
                status.update(calibration_status=partial["status"], logical_api_usd=partial["spent"],
                              unknown_model_cost=partial["status"] == "error_unknown_model_cost")
                if partial["status"] == "error_unknown_model_cost":
                    status["status"] = partial["status"]
        status["run_id"] = run_id
        status["new_api_bill_usd"] = sum(r.cost_usd for r in shared["ledger"].records if r.run_id == run_id)
        status["offline_fixture"] = free
        status["code"] = code_version()
        status["batch"] = shared["name"]
        atomic_json(out / "status.json", status)
        return {"name": cfg.name, "out": str(out), **{k: status.get(k) for k in ("status", "run_id", "new_api_bill_usd")}}
    finally:
        await runtime.aclose()


def _run_in_thread(cfg: PhoenixConfig, shared: dict) -> dict:
    try:
        return asyncio.run(_run_branch(cfg, shared))
    except Exception as exc:  # never lose the rest of the batch to one branch
        return {"name": cfg.name, "status": "error", "reason": f"{type(exc).__name__}: {str(exc)[:300]}"}


def run_batch(bcfg: PhoenixBatchConfig, config_path, tool_factory=None) -> dict:
    """Preflight, then run the selected branches `concurrency` at a time, in chunks; commit state per chunk."""
    from .tools import ToolRunner
    problems, _ = preflight_batch(bcfg, config_path)
    if problems:
        raise RuntimeError("PHOENIX batch not cleared: " + "; ".join(problems))
    branches = bcfg.branch_configs()
    free = all(is_free(cfg, registry_for(cfg)) for _, cfg in branches)
    ledger = Ledger() if free else Ledger(bcfg.ledger, must_exist=True)
    governor = LockedGovernor(ledger, BudgetRules.from_yaml(bcfg.budget), run_cap_usd=bcfg.max_usd)
    shared = {"free": free, "ledger": ledger, "governor": governor, "key_locks": KeyLocks(), "name": bcfg.name,
              "cache": None if free else LockedCache(bcfg.cache), "tool_factory": tool_factory or ToolRunner}
    batch_dir = Path(bcfg.out_dir) / (("fake_" if free else "") + bcfg.name)
    batch_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    chunk = bcfg.chunk_size or bcfg.concurrency
    for start in range(0, len(branches), chunk):
        todo = []
        for _, cfg in branches[start:start + chunk]:
            out = Path(cfg.out_dir) / (("fake_" if free else "") + cfg.name)
            run_id = "phoenix_" + digest({"config": cfg.model_dump(), "inputs": frozen_inputs(cfg)})[:24]
            if _finished(out, run_id):
                rows.append({"name": cfg.name, "out": str(out), "status": "skipped_finished", "run_id": run_id})
            else:
                todo.append(cfg)
        with ThreadPoolExecutor(max_workers=bcfg.concurrency) as pool:
            done = list(pool.map(lambda cfg: _run_in_thread(cfg, shared), todo))
        sync = "offline fixture; not checkpointed"
        if not free and bcfg.git_checkpoint:
            paths = [bcfg.ledger, bcfg.cache] + [str(Path(r["out"]) / f) for r in done if "out" in r
                                                  for f in COMMITTED_FILES if (Path(r["out"]) / f).exists()]
            sync = git_checkpoint(paths, f"state: batch {bcfg.name} branches {start}-{start + len(todo) - 1}")
        for row in done:
            row["state_sync"] = sync
        rows.extend(done)
        status = _batch_status(bcfg, rows, governor, ledger, len(branches))
        atomic_json(batch_dir / "batch_status.json", status)
        if sync not in ("offline fixture; not checkpointed", "committed and pushed", "nothing new to checkpoint"):
            status["status"] = "state_sync_failed"
            atomic_json(batch_dir / "batch_status.json", status)
            return status
    return status


def _batch_status(bcfg, rows, governor, ledger, total) -> dict:
    frame = pd.DataFrame(rows)
    counts = frame.groupby("status").size().sort_values(ascending=False).to_dict() if len(frame) else {}
    errors = [r for r in rows if str(r.get("status", "")).startswith("error") or r.get("status") == "state_sync_failed"]
    return {"batch": bcfg.name, "branches_total": total, "branches_reported": len(rows),
            "status": ("completed" if len(rows) == total and not errors else "partial"),
            "status_counts": counts, "batch_run_spent_usd": round(governor.run_spent_usd, 6),
            "branches": rows, "code": code_version()}
