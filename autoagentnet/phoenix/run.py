"""Governed PHOENIX configuration, estimate and preflight integration for `aan`."""
from __future__ import annotations

import asyncio
import json
import importlib.metadata
import os
import subprocess
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import Field, PrivateAttr, model_validator

from ..budget import BudgetRules, SpendGovernor
from ..cache import CallCache
from ..experiment import Prereg, gate_problems
from ..market.caller import MarketCaller
from ..meter import Ledger
from ..persist import code_version, git_checkpoint
from ..pricing import PriceBook
from ..providers.registry import ModelConfig, ProviderRegistry
from ..runtime.local import LocalRuntime
from .fake import FakePhoenixClient
from .planner import CapabilityTable
from .prompts import TEMPLATE_HASH
from .store import atomic_json, file_sha
from .types import Strict, digest

POLICIES = ("fixed", "llm", "full", "no_dependency", "no_cost", "static")


class PhoenixConfig(Strict):
    kind: Literal["phoenix"] = "phoenix"
    name: str = Field(pattern=r"^[A-Za-z0-9_-]+$")
    mode: Literal["recover", "calibrate"] = "recover"
    prereg: Prereg | None = None
    checkpoint: str | None = None
    capability_table: str | None = None
    frozen_hashes: dict[str, str] = Field(default_factory=dict)
    policy: Literal["fixed", "llm", "full", "no_dependency", "no_cost", "static"] = "full"
    fault: Literal["healthy", "F0", "F1"] = "F1"
    withdrawn_model: str = "sonnet_low"
    shutdown_member: Literal["A", "B", "C"] = "A"
    models: list[str] = Field(default_factory=lambda: ["luna_low_ev", "sol61_low", "sonnet_low"])
    planner_model: str = "luna_low_ev"
    api_budget_usd: float = Field(default=0.05, gt=0)
    cpu_budget_s: float = Field(default=120, gt=0)
    max_calls: int = Field(default=8, ge=1, le=90)
    max_tools: int = Field(default=24, ge=1)
    wall_s: float = Field(default=1200, gt=0, le=7200)  # science tables: see docs/PHOENIX_SCIENCE_ADDENDUM.md
    tool_timeout_s: float = Field(default=30, gt=0, le=120)  # science tables: see docs/PHOENIX_SCIENCE_ADDENDUM.md
    # Output ceiling per model call. 4,096 for the main science study; the family arms (Opus 5.5 / GPT-6.1 Sol
    # planners at medium effort, whose thinking counts against it) use 16,384 so reasoning is not cut.
    max_tokens: int = Field(default=4096, ge=128, le=32768)
    max_input_tokens: int = Field(default=6000, ge=1000, le=6000)
    proposal_rounds: int = Field(default=3, ge=0, le=3)
    seed: int = Field(default=101, ge=0)
    # Replicate draw of the model calls (audit SC-8: per-case outcomes are dominated by which replies are drawn).
    # 0 keeps the main study's cache keys (replicate = seed); k > 0 uses replicate seed + 1000 k, so the same
    # request is sent again as a fresh draw instead of replaying the cache.
    draw: int = Field(default=0, ge=0, le=9)
    model_override: str | None = None
    task_offset: int = Field(default=0, ge=0)
    task_limit: int | None = Field(default=None, ge=1)
    calibration_model: str | None = None
    calibration_data: list[str] = Field(default_factory=list)
    max_usd: float | None = Field(default=None, gt=0)  # optional run cap; None = only the phase and hard caps apply
    providers: str = "configs/providers.yaml"
    pricing: str = "configs/pricing.yaml"
    budget: str = "configs/budget.yaml"
    ledger: str = "state/ledger.jsonl"
    cache: str = "state/cache"
    require_ledger: bool = True
    git_checkpoint: bool = True
    out_dir: str = "results"
    fixed_proposals: str | None = None
    _source: str | None = PrivateAttr(default=None)

    @model_validator(mode="after")
    def validate_config(self):
        if len(set(self.models)) != len(self.models) or not self.models:
            raise ValueError("model pool must be nonempty and unique")
        if self.planner_model not in self.models:
            raise ValueError("planner model must be in the common model pool")
        if self.fault == "F1" and (self.withdrawn_model not in self.models or self.withdrawn_model == self.planner_model):
            raise ValueError("F1 must withdraw a declared non-planner model")
        if self.model_override not in (None, "fake"):
            raise ValueError("only the explicit offline fake override is supported")
        if self.mode == "recover" and not self.checkpoint:
            raise ValueError("recovery needs a checkpoint")
        if self.mode == "calibrate" and (not self.calibration_model or not self.calibration_data):
            raise ValueError("calibration needs a model and training-only calibration partitions")
        return self

    @classmethod
    def from_yaml(cls, path):
        cfg = cls.model_validate(yaml.safe_load(Path(path).read_text()))
        cfg._source = str(path)
        return cfg

    def model_override_resolved(self):
        override = self.model_override or os.getenv("AAN_MODEL_OVERRIDE")
        if override not in (None, "fake"):
            raise ValueError("PHOENIX refuses implicit real-model substitution")
        return override


def is_phoenix_config(path):
    raw = yaml.safe_load(Path(path).read_text())
    return isinstance(raw, dict) and raw.get("kind") == "phoenix"


def registry_for(cfg):
    registry = ProviderRegistry.from_yaml(cfg.providers)
    if cfg.model_override_resolved() == "fake":
        refs = set(cfg.models) | {cfg.planner_model} | ({cfg.calibration_model} if cfg.calibration_model else set())
        for ref in refs:
            registry.models[ref] = ModelConfig(provider="fake", model="fake-phoenix")
            registry.set_client(ref, FakePhoenixClient())
    return registry


def is_free(cfg, registry=None):
    registry = registry or registry_for(cfg)
    refs = [cfg.calibration_model] if cfg.mode == "calibrate" else cfg.models
    return all(registry.provider_of(ref) == "fake" for ref in refs)


def estimate_phoenix(cfg):
    registry, prices = registry_for(cfg), PriceBook.from_yaml(cfg.pricing)
    refs = [cfg.calibration_model] if cfg.mode == "calibrate" else cfg.models
    if cfg.mode == "recover" and cfg.fault == "F1":
        refs = [r for r in refs if r != cfg.withdrawn_model]
    rows = []
    for ref in refs:
        model, provider = registry.model_id(ref), registry.provider_of(ref)
        maximum = 0 if provider == "fake" else prices.worst_case_usd(
            model, provider, cfg.max_input_tokens, cfg.max_tokens)
        # The scientific sub-budget is enforced before EVERY actual call. Each account
        # may conservatively consume the whole branch budget, not a full budget per ref.
        rows.append({"account": registry.account_of(ref), "model": "adaptive_pool",
                     "per_ref_upper": min(cfg.api_budget_usd, cfg.max_calls*maximum)})
    frame = pd.DataFrame(rows)
    table = frame.groupby(["account", "model"]).agg(worst_case_usd=("per_ref_upper", "sum"))
    table["worst_case_usd"] = table["worst_case_usd"].clip(upper=cfg.api_budget_usd)
    table["worst_case_x_safety"] = table.worst_case_usd * BudgetRules.from_yaml(cfg.budget).safety_multiplier
    return table


def frozen_inputs(cfg):
    files = {}
    files["implementation"] = digest({p.name: file_sha(p) for p in Path(__file__).parent.glob("*.py")})
    versions = {}
    for package in ("pydantic", "scikit-learn", "numpy", "scipy", "joblib", "openai", "anthropic", "httpx"):
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = None
    files["runtime_dependencies"] = digest(versions)
    for name in ("providers", "pricing", "budget"):
        files[name] = file_sha(Path(getattr(cfg, name)))
    if cfg.checkpoint:
        for name in ("checkpoint.json", "search.npz"):
            p = Path(cfg.checkpoint) / name
            files["checkpoint_"+name] = file_sha(p)
    if cfg.capability_table:
        files["capability_table"] = file_sha(Path(cfg.capability_table))
    if cfg.fixed_proposals:
        files["fixed_proposals"] = file_sha(Path(cfg.fixed_proposals))
    for i, name in enumerate(cfg.calibration_data):
        files[f"calibration_{i}"] = file_sha(Path(name))
    files["templates"] = TEMPLATE_HASH
    return files


def preflight_phoenix(cfg, config_path):
    registry = registry_for(cfg)
    free = is_free(cfg, registry)
    problems = []
    if cfg.mode == "recover" and (cfg.task_offset or cfg.task_limit is not None):
        problems.append("one recovery config is one branch; task slicing applies only to calibration")
    try:
        if cfg.mode == "recover":
            from .checkpoint import read_checkpoint
            raw_checkpoint = read_checkpoint(cfg.checkpoint, verify_files=True)
            if raw_checkpoint["seed"] != cfg.seed:
                problems.append("configuration seed differs from the checkpoint replicate")
            if cfg.capability_table:
                table = CapabilityTable.model_validate_json(Path(cfg.capability_table).read_text())
                if table.synthetic and not free:
                    problems.append("synthetic capability tables are offline fixtures only")
                if not table.complete and not free:
                    problems.append("partial calibration tables cannot drive production recovery")
                if not free:
                    dataset = raw_checkpoint["dataset"]
                    for kind in ("prepare", "fit", "predict", "validate", "ensemble", "pipeline"):
                        estimate = table.estimate(kind, "cpu", dataset)
                        # Any completed pipeline with a measured quality on this dataset, in any category: the
                        # default-category lookup can match a single failed "generic" row and hide the rest.
                        if kind == "pipeline" and not any(r.kind == "pipeline" and r.dataset == dataset and r.completed
                                                          and r.quality is not None for r in table.records):
                            problems.append("calibration contains no completed pipeline-quality observations")
                    for ref in cfg.models:
                        rows = [r for r in table.records if r.kind == "design" and r.model == ref]
                        if any(sum(r.task_family == family for r in rows) < 10
                               for family in ("design", "diagnose", "plan")):
                            problems.append(f"{ref}: need ten calibration tasks in each of the three families")
            elif not free:
                problems.append("paid recovery requires a frozen development capability table")
            if cfg.fixed_proposals:
                pool = json.loads(Path(cfg.fixed_proposals).read_text())
                expected_case = f'{raw_checkpoint["dataset"]}_{raw_checkpoint["template"]}_{raw_checkpoint["seed"]}'
                if pool.get("source_case_id") != expected_case:
                    problems.append("fixed proposal pool belongs to another checkpoint case")
        else:
            from .data import load_search
            for path in cfg.calibration_data:
                if load_search(path).partition != "calibration":
                    problems.append("calibration may use only training-internal partitions")
    except (OSError, ValueError, KeyError) as exc:
        problems.append(f"invalid input artifact: {exc}")
    if free:
        return problems, None
    if cfg.model_override_resolved() is not None:
        problems.append("paid execution cannot replace the preregistered model pool")
    if not cfg.git_checkpoint or not cfg.require_ledger:
        problems.append("paid execution requires ledger and state checkpointing")
    branch = subprocess.run(["git", "branch", "--show-current"], capture_output=True, text=True)
    if branch.returncode or branch.stdout.strip() in ("", "main", "master"):
        problems.append("paid execution requires a non-main research branch")
    if subprocess.run(["git", "remote", "get-url", "origin"], capture_output=True).returncode:
        problems.append("paid state synchronization requires an origin remote")
    for status_path in Path(cfg.out_dir).glob("*/status.json"):
        previous = json.loads(status_path.read_text())
        if previous.get("unknown_model_cost") and not previous.get("cost_reconciled", False):
            problems.append("a prior PHOENIX run has an unknown model charge; reconcile and audit before paid work")
            break
    for ref in ([cfg.calibration_model] if cfg.mode == "calibrate" else cfg.models):
        if cfg.mode == "recover" and cfg.fault == "F1" and ref == cfg.withdrawn_model:
            continue
        rc = registry.config(ref)
        if rc.model_env:
            problems.append(f"{ref}: mutable model_env is not allowed in a frozen model pool")
        if rc.api_key_env and not rc.resolved_api_key():
            problems.append(f"missing environment variable {rc.api_key_env}")
    try:
        if frozen_inputs(cfg) != cfg.frozen_hashes:
            problems.append("input/template hashes differ from the committed frozen_hashes")
        version = code_version()
        if version["dirty"]:
            problems.append("commit implementation and experiment inputs before paid execution")
        table = estimate_phoenix(cfg)
        problems.extend(gate_problems(cfg, config_path, table))
    except (OSError, ValueError, KeyError) as exc:
        table = None
        problems.append(f"preflight failed: {exc}")
    return problems, table


async def run_phoenix(cfg, config_path=None):
    """Preflight is repeated here, including for programmatic callers."""
    problems, _ = preflight_phoenix(cfg, config_path or cfg._source or "")
    if problems:
        raise RuntimeError("PHOENIX not cleared: " + "; ".join(problems))
    registry = registry_for(cfg)
    free = is_free(cfg, registry)
    name = ("fake_" if free else "") + cfg.name
    out = Path(cfg.out_dir) / name
    out.mkdir(parents=True, exist_ok=True)
    ledger = Ledger() if free else Ledger(cfg.ledger, must_exist=True)
    cache = CallCache(out / "call_cache" if free else cfg.cache)
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    runtime = LocalRuntime(registry)
    run_id = "phoenix_"+digest({"config": cfg.model_dump(), "inputs": frozen_inputs(cfg)})[:24]
    caller = MarketCaller(runtime, registry, pricebook=PriceBook.from_yaml(cfg.pricing), cache=cache,
                          governor=governor, run_id=run_id, market="phoenix", condition=cfg.policy,
                          purpose="phoenix."+cfg.mode)
    try:
        try:
            if cfg.mode == "calibrate":
                from .calibrate import run_calibration
                status = await run_calibration(cfg, caller, out, free)
            else:
                from .engine import RecoveryEngine
                engine = RecoveryEngine.open(cfg, caller, out, free=free)
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
        status["new_api_bill_usd"] = sum(r.cost_usd for r in ledger.records if r.run_id == run_id)
        status["offline_fixture"] = free
        status["code"] = code_version()
        if not free:
            sync = git_checkpoint([cfg.ledger, cfg.cache], f"state: {run_id}")
            status["state_sync"] = sync
            if sync not in ("committed and pushed", "nothing new to checkpoint"):
                status["status"] = "state_sync_failed"
        atomic_json(out / "status.json", status)
        return pd.DataFrame(), pd.DataFrame(), status
    finally:
        await runtime.aclose()
