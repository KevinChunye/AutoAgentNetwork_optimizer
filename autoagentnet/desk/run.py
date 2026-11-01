"""Desk configs (configs/experiments/desk/*.yaml, `kind: desk`): estimate, gate and run (W2-A).

`aan estimate`, `aan check` and `aan run` accept these files. A paid desk run uses the same ledger,
call cache, spend governor, run caps, prereg gate and status.json as every other run; it checkpoints
state/ to git after every chunk of events and stops on a missed expectation.

Sequences: `seeds` lists the sequence seeds the run plays; each sequence has `events` events
(events.py). `--task-offset/--task-limit` pick a slice of events inside every sequence, so a long
sequence can run in parts. The seed is the replicate number of every call, so sequences never share
cached calls. Seeds 1-99 are tuning (seed block 1) and 101-199 are judging (sealed seed block 2).

Outputs in results/<name>/ (rows of other events already there are kept, so slices add up):
events.csv (one row per event, with the hidden truth), decisions.csv (one row per event and
structure), calls.csv (one row per model call, with the raw reply) and status.json (the latest run).
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict

from ..agents.agent import prompt_text
from ..budget import BudgetExceeded, BudgetRules, SpendGovernor
from ..cache import CallCache
from ..experiment import Prereg, gate_problems
from ..market.caller import MarketCaller
from ..meter import Ledger
from ..persist import code_version, git_checkpoint
from ..pricing import PriceBook
from ..providers.base import estimate_tokens
from ..providers.registry import ProviderRegistry
from ..runtime.local import LocalRuntime
from ..runtime.maritime import MaritimeRuntime
from .desk import (MEMBERS, Call, DeskSettings, ask, decisions, member_request, risk_request, track_record,
                   trader_request, twin_request, twin_rows)
from .events import Event, make_sequence
from .fake import FakeDeskClient
from .prompts import TEMPLATE_HASHES, TrackRecord, parse_member, parse_risk, parse_trader

TUNING_SEEDS = range(1, 100)
JUDGING_SEEDS = range(101, 200)


class DeskExpect(BaseModel):
    """Stop rules checked after every chunk; a miss stops the run.

    min_calls:            calls of a role in this run before its rates apply
    max_unparsed_rate:    share of a role's replies the parser cannot read (the W2 kill rule: 5%)
    max_truncation_rate:  share of a role's replies cut off by max_tokens
    max_spend_usd:        actual spend of this run; the W2 kill rule sets it at 1.5x the projected
                          actual cost written in the prereg (the worst case is far above it)
    """

    model_config = ConfigDict(extra="forbid")
    min_calls: int = 20
    max_unparsed_rate: float | None = 0.05
    max_truncation_rate: float | None = 0.05
    max_spend_usd: float | None = None


class DeskConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["desk"]
    name: str
    prereg: Prereg | None = None
    seeds: list[int]
    events: int = 200
    event_offset: int = 0
    event_limit: int | None = None
    structures: list[Literal["S1", "S2", "S3", "S4"]] = ["S1", "S2", "S3", "S4"]
    twin: bool = False  # a second trader call without the news item on every event that has one (audit 40)
    model: str = "haiku_nothink"
    max_tokens: int = 400
    temperature: float | None = 1.0
    kelly_fraction: float = 0.5
    model_override: str | None = None
    max_usd: float | None = None  # optional run cap for this config; None = only the phase and hard caps apply
    chunk_events: int = 50
    max_concurrency: int = 8
    expect: DeskExpect = DeskExpect()
    runtime: Literal["local", "maritime"] = "local"
    maritime: str = "configs/runtime/maritime.yaml"
    providers: str = "configs/providers.yaml"
    pricing: str = "configs/pricing.yaml"
    budget: str = "configs/budget.yaml"
    ledger: str = "state/ledger.jsonl"
    cache: str = "state/cache"
    require_ledger: bool = True
    git_checkpoint: bool = True
    out_dir: str = "results"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "DeskConfig":
        return cls(**yaml.safe_load(Path(path).read_text()))

    def model_override_resolved(self) -> str | None:
        return self.model_override or os.getenv("AAN_MODEL_OVERRIDE")

    def settings(self) -> DeskSettings:
        return DeskSettings(model=self.model_override_resolved() or self.model, max_tokens=self.max_tokens,
                            temperature=self.temperature, kelly_fraction=self.kelly_fraction)

    def slice(self) -> tuple[int, int]:
        end = self.events if self.event_limit is None else min(self.events, self.event_offset + self.event_limit)
        return self.event_offset, end

    def needs(self) -> dict[str, bool]:
        return {"trader": True, "members": "S4" in self.structures, "risk": "S2" in self.structures}


def is_desk_config(path: str | Path) -> bool:
    raw = yaml.safe_load(Path(path).read_text())
    return isinstance(raw, dict) and raw.get("kind") == "desk"


def is_free(cfg: DeskConfig, registry: ProviderRegistry) -> bool:
    return registry.provider_of(cfg.settings().model) == "fake"


def estimate_desk(cfg: DeskConfig) -> pd.DataFrame:
    """Worst case: every call of the slice (and, for S2, the trader calls of the events before it) with
    its own prompt at the cache-write rate and the full max_tokens of output; the risk manager is
    asked on every event. Cached calls are ignored, so it is an upper bound."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    pricebook = PriceBook.from_yaml(cfg.pricing)
    s = cfg.settings()
    model_id, provider, account = registry.model_id(s.model), registry.provider_of(s.model), registry.account_of(s.model)
    start, end = cfg.slice()
    worst = TrackRecord(199, 0.99, 0.99)
    requests = []
    for seed in cfg.seeds:
        events = make_sequence(seed, end)
        first = 0 if cfg.needs()["risk"] else start
        requests += [trader_request(e, s) for e in events[first:end]]
        if cfg.needs()["members"]:
            requests += [member_request(e, k, s) for e in events[start:end] for k in MEMBERS]
        if cfg.needs()["risk"]:
            requests += [risk_request(e, 0.99, "YES", worst, s) for e in events[start:end]]
        if cfg.twin:
            requests += [twin_request(e, s) for e in events[start:end] if e.salient]
    costs = [pricebook.worst_case_usd(model_id, provider, estimate_tokens(prompt_text(r.spec, r.input)), r.spec.max_tokens)
             for r in requests]
    table = pd.DataFrame({"account": account, "model": model_id, "worst_case_usd": costs})
    table = table.groupby(["account", "model"]).agg(calls=("worst_case_usd", "size"), worst_case_usd=("worst_case_usd", "sum"))
    table["worst_case_x_safety"] = table["worst_case_usd"] * BudgetRules.from_yaml(cfg.budget).safety_multiplier
    return table


def preflight_desk(cfg: DeskConfig, config_path: str | Path) -> tuple[list[str], pd.DataFrame | None]:
    if is_free(cfg, ProviderRegistry.from_yaml(cfg.providers)):
        return [], None
    table = estimate_desk(cfg)
    return gate_problems(cfg, config_path, table), table


def reply_parsed(call: Call) -> bool:
    if call.truncated:
        return False
    if call.role in ("trader", "twin"):
        return parse_trader(call.text).parsed
    if call.role == "risk":
        return parse_risk(call.text) is not None
    return parse_member(call.text) is not None


def expectation_misses(calls: pd.DataFrame, spent: float, expect: DeskExpect) -> list[str]:
    misses = []
    if not calls.empty:
        rates = calls.groupby("role").agg(  # per role, so one failing committee member cannot hide (audit 40)
            calls=("parsed", "size"), unparsed=("parsed", lambda x: (~x.astype(bool)).mean()),
            truncated=("truncated", "mean"))  # (~x).mean(), not 1 - mean: 1 of 20 must be exactly 5%
        for role, r in rates[rates["calls"] >= expect.min_calls].iterrows():
            if expect.max_unparsed_rate is not None and r["unparsed"] > expect.max_unparsed_rate:
                misses.append(f"{r['unparsed']:.1%} of {role} replies unparsed (limit {expect.max_unparsed_rate:.0%})")
            if expect.max_truncation_rate is not None and r["truncated"] > expect.max_truncation_rate:
                misses.append(f"{r['truncated']:.1%} of {role} replies truncated (limit {expect.max_truncation_rate:.0%})")
    if expect.max_spend_usd is not None and spent > expect.max_spend_usd:
        misses.append(f"spent ${spent:.4f}, above the kill line ${expect.max_spend_usd:.4f} (1.5x the projected cost)")
    return misses


def merge_write(path: Path, new: pd.DataFrame, keys: list[str]) -> None:
    """Write `new`, keeping rows already in the file whose keys `new` does not cover."""
    if path.exists() and path.stat().st_size > 0 and not new.empty:
        old = pd.read_csv(path)
        old = old[~old.set_index(keys).index.isin(new.set_index(keys).index)]
        new = pd.concat([old, new], ignore_index=True)
    if not new.empty:
        new.sort_values([k for k in ("seed", "index", "structure", "role") if k in new], kind="stable").to_csv(path, index=False)


async def play_chunk(caller, events: list[Event], chunk: list[Event], trader: dict[str, Call], cfg: DeskConfig,
                     s: DeskSettings, gate: asyncio.Semaphore) -> tuple[list[dict], list[dict]]:
    """All calls and decisions of one chunk of one sequence. `trader` holds the trader replies already
    made for this sequence (the risk manager's track record reads them) and is updated in place."""
    seed = chunk[0].seed
    todo = [e for e in events[: chunk[-1].index + 1] if e.event_id not in trader] if cfg.needs()["risk"] else \
        [e for e in chunk if e.event_id not in trader]
    replies = await asyncio.gather(*(ask(caller, trader_request(e, s), seed, gate) for e in todo))
    trader.update({e.event_id: r for e, r in zip(todo, replies)})
    by_event: dict[str, dict[str, Call]] = {e.event_id: {"trader": trader[e.event_id]} for e in chunk}
    jobs, keys = [], []
    if cfg.needs()["members"]:
        for e in chunk:
            for k in MEMBERS:
                jobs.append(ask(caller, member_request(e, k, s), seed, gate))
                keys.append((e.event_id, f"member{k}"))
    if cfg.needs()["risk"]:
        for e in chunk:
            reply = parse_trader(trader[e.event_id].text)
            if reply.parsed and reply.side != "NONE" and not trader[e.event_id].truncated:  # audit 43: no risk call on a cut-off reply
                record = track_record(events, trader, e.index)
                jobs.append(ask(caller, risk_request(e, reply.p, reply.side, record, s), seed, gate))
                keys.append((e.event_id, "risk"))
    if cfg.twin:
        for e in chunk:
            if e.salient:
                jobs.append(ask(caller, twin_request(e, s), seed, gate))
                keys.append((e.event_id, "twin"))
    for (event_id, role), call in zip(keys, await asyncio.gather(*jobs)):
        by_event[event_id][role] = call
    rows, call_rows = [], []
    for e in chunk:
        rows += decisions(e, by_event[e.event_id], s, cfg.structures)
        if "twin" in by_event[e.event_id]:
            rows += twin_rows(e, by_event[e.event_id]["twin"], s)
        for role, call in by_event[e.event_id].items():
            call_rows.append({"event_id": e.event_id, "seed": e.seed, "index": e.index, "role": role, "model": s.model,
                              "parsed": reply_parsed(call), "truncated": call.truncated, "cost_usd": call.cost_usd,
                              "from_cache": call.from_cache, "reply": call.text})
    return rows, call_rows


async def run_desk(cfg: DeskConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Play the selected sequences. Returns (decisions, calls, status) for this run."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    run_id = f"{cfg.name}-{int(time.time())}"
    s = cfg.settings()
    free = is_free(cfg, registry)
    if free:  # nothing is spent, so nothing tracked is touched; dry runs go to runs/dry
        out_dir = "runs/dry" if cfg.out_dir == "results" else cfg.out_dir
        cfg = cfg.model_copy(update={"git_checkpoint": False, "out_dir": out_dir})
        ledger, cache = Ledger(), CallCache()
        registry.set_client(s.model, FakeDeskClient())
    else:
        ledger = Ledger(cfg.ledger, must_exist=cfg.require_ledger)
        cache = CallCache(cfg.cache, shard_prefix=run_id)
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    runtime = LocalRuntime(registry) if cfg.runtime == "local" else MaritimeRuntime.from_yaml(cfg.maritime)
    caller = MarketCaller(runtime, registry, pricebook=PriceBook.from_yaml(cfg.pricing), cache=cache, governor=governor,
                          run_id=run_id, market=cfg.name, condition=",".join(cfg.structures), purpose="desk")
    out = Path(cfg.out_dir) / cfg.name
    out.mkdir(parents=True, exist_ok=True)
    start, end = cfg.slice()
    status = {"run_id": run_id, "state": "completed", "reason": "", "seeds": cfg.seeds, "events": [start, end],
              "structures": cfg.structures, "model": s.model, "template_hashes": TEMPLATE_HASHES, "code": code_version(),
              "checkpoints": []}
    rows: list[dict] = []
    call_rows: list[dict] = []
    events_rows: list[dict] = []
    gate = asyncio.Semaphore(cfg.max_concurrency)

    def write() -> None:
        merge_write(out / "events.csv", pd.DataFrame(events_rows), ["event_id"])
        merge_write(out / "decisions.csv", pd.DataFrame(rows), ["event_id", "structure", "model"])
        merge_write(out / "calls.csv", pd.DataFrame(call_rows), ["event_id", "role", "model"])

    try:
        for seed in cfg.seeds:
            events = make_sequence(seed, end)
            events_rows += [e.row() for e in events[start:end]]
            trader: dict[str, Call] = {}
            for first in range(start, end, cfg.chunk_events):
                chunk = events[first: min(end, first + cfg.chunk_events)]
                new_rows, new_calls = await play_chunk(caller, events, chunk, trader, cfg, s, gate)
                rows += new_rows
                call_rows += new_calls
                cache.rotate()
                if cfg.git_checkpoint:
                    status["checkpoints"].append(git_checkpoint([cfg.ledger, cfg.cache],
                                                                f"state: {run_id} s{seed} events {first}-{chunk[-1].index}"))
                write()
                misses = expectation_misses(pd.DataFrame(call_rows), governor.status()["run_spent_usd"], cfg.expect)
                if misses:
                    status.update(state="stopped", reason="expectation missed: " + "; ".join(misses))
                    break
            if status["state"] != "completed":
                break
    except BudgetExceeded as exc:
        status.update(state="stopped", reason=f"budget: {exc}")
    except BaseException as exc:
        status.update(state="failed", reason=f"{type(exc).__name__}: {exc}")
        raise
    finally:
        await runtime.aclose()
        if not free and status["state"] != "completed":  # what a stopped run already paid for is kept
            cache.rotate()
            if cfg.git_checkpoint:
                status["checkpoints"].append(git_checkpoint([cfg.ledger, cfg.cache], f"state: {run_id} stopped"))
        write()
        status["live_calls"] = caller.live_calls
        status["budget"] = governor.status()
        status["rate_limits"] = registry.rate_limits()
        (out / "status.json").write_text(json.dumps(status, indent=2))
    return pd.DataFrame(rows), pd.DataFrame(call_rows), status
