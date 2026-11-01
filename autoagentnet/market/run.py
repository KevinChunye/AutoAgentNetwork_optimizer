"""Market configs (configs/experiments/market/*.yaml, `kind: market`): estimate, gate and run.

`aan estimate`, `aan check` and `aan run` accept these files as well as network experiments. A paid
market run uses the same ledger (state/ledger.jsonl), call cache (state/cache), spend governor, run
caps, prereg gate and status.json as a network experiment. It checkpoints state/ to git after every
period, writes its tables after every period, and stops on a missed expectation.

Sessions: `seeds` lists the session seeds of the condition; `--session-offset/--session-limit` (aliases
of --task-offset/--task-limit) pick which ones a run plays. The seed sets the polling order and is the
replicate number of every call, so sessions are independent samples and never share cached calls.
Seeds must therefore be unique across all conditions of a study.

Outputs in results/<name>/ (rows of other seeds already there are kept, so runs of single sessions add
up): periods.csv, sessions.csv, traders.csv, trades.csv, turns.csv (one row per turn, with each LLM
trader's reason and raw reply; skipped when save_turns is false) and status.json (the latest run).
"""

from __future__ import annotations

import json
import os
import random
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
from ..meter import Ledger
from ..persist import git_checkpoint
from ..pricing import PriceBook
from ..providers.base import estimate_tokens
from ..providers.registry import ProviderRegistry
from ..runtime.local import LocalRuntime
from ..runtime.maritime import MaritimeRuntime
from .caller import MarketCaller
from .engine import HISTORY_PRICES, SessionLog, Trader, View, make_traders, run_session
from .fake import FakeTraderClient
from .metrics import period_metrics, session_metrics, trade_table, trader_metrics
from .schedule import Schedule
from .traders import LLMTrader, ZICTrader, rules_text, trader_request


class MarketExpect(BaseModel):
    """Stop rules checked after every period; a miss stops the run.

    min_turns:                LLM turns in this run before the two rate checks apply
    max_unparsed_rate:        share of LLM replies with no readable ACTION line
    max_truncation_rate:      share of LLM replies cut off by max_tokens
    stop_after_zero_trade_periods: this many periods in a row without a trade in one session
    """

    model_config = ConfigDict(extra="forbid")
    min_turns: int = 40
    max_unparsed_rate: float | None = 0.10
    max_truncation_rate: float | None = 0.05
    stop_after_zero_trade_periods: int | None = 2


class MarketConfig(BaseModel):
    """One condition of the market study.

    condition:   short label for tables and the ledger ("haiku", "sonnet", "mixed_odd", "zic")
    trader:      "llm" (model calls) or "zic" (free random baseline)
    model:       model ref of every LLM trader, unless senior_model / senior_ranks say otherwise
    senior_model, senior_ranks: traders of these ranks, on both sides, use senior_model (M4)
    zic_low / zic_high:  price range in dollars for ZI-C bids (low to value) and asks (cost to high)
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["market"]
    name: str
    condition: str = ""
    prereg: Prereg | None = None
    seeds: list[int]
    session_offset: int = 0
    session_limit: int | None = None
    periods: int = 5
    rounds: int = 8
    schedule: Schedule = Schedule()
    trader: Literal["llm", "zic"] = "llm"
    model: str = "haiku_nothink"
    senior_model: str | None = None
    senior_ranks: list[int] = []
    max_tokens: int = 200
    temperature: float | None = 1.0
    zic_low: float = 0.01
    zic_high: float = 4.00
    model_override: str | None = None
    max_usd: float | None = None  # optional run cap for this config; None = only the phase and hard caps apply
    expect: MarketExpect = MarketExpect()
    save_turns: bool = True
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
    def from_yaml(cls, path: str | Path) -> "MarketConfig":
        return cls(**yaml.safe_load(Path(path).read_text()))

    def model_override_resolved(self) -> str | None:
        return self.model_override or os.getenv("AAN_MODEL_OVERRIDE")

    def selected_seeds(self) -> list[int]:
        seeds = self.seeds[self.session_offset:]
        return seeds[: self.session_limit] if self.session_limit else seeds

    def model_of(self, role: str, rank: int) -> str:
        if self.trader == "zic":
            return "zic"
        override = self.model_override_resolved()
        if override:
            return override
        return self.senior_model if self.senior_model and rank in self.senior_ranks else self.model

    def rules(self) -> str:
        return rules_text(len(self.schedule.values), len(self.schedule.costs), self.periods, self.rounds)


def is_market_config(path: str | Path) -> bool:
    raw = yaml.safe_load(Path(path).read_text())
    return isinstance(raw, dict) and raw.get("kind") == "market"


def is_free(cfg: MarketConfig, registry: ProviderRegistry) -> bool:
    """ZI-C runs and runs routed to the fake model spend nothing."""
    override = cfg.model_override_resolved()
    return cfg.trader == "zic" or (bool(override) and registry.provider_of(override) == "fake")


def worst_case_view(trader: Trader, period: int, cfg: MarketConfig, round_: int) -> View:
    """The longest situation text a trader can be shown: both quotes standing and marked as its own, a
    full price history and every earlier period's mean. Under the budget rule a bid, and so every trade
    price, is at most the highest value (under $10), and a session's profit is under $100; an ask has
    no ceiling, so it gets 6 digits."""
    return View(trader, period, cfg.periods, round_, cfg.rounds, 999, 999999, True, True,
                [999] * HISTORY_PRICES, [9.99] * (period - 1), 9999)


def estimate_market(cfg: MarketConfig) -> pd.DataFrame:
    """Worst-case cost of a run, by account and model: every trader acts in every round (no trade ever
    happens) with the longest possible prompt and the full max_tokens of output. Cached calls are
    ignored, so it is an upper bound."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    pricebook = PriceBook.from_yaml(cfg.pricing)
    rows = []
    if cfg.trader == "llm":
        rules = cfg.rules()
        for seed in cfg.selected_seeds():
            for trader in make_traders(cfg.schedule, cfg.model_of):
                model_id, provider = registry.model_id(trader.model), registry.provider_of(trader.model)
                for period in range(1, cfg.periods + 1):
                    for round_ in range(1, cfg.rounds + 1):
                        request = trader_request(worst_case_view(trader, period, cfg, round_), trader.model, rules,
                                                 seed, cfg.max_tokens, cfg.temperature)
                        tokens = estimate_tokens(prompt_text(request.spec, request.input))
                        rows.append({"account": registry.account_of(trader.model), "model": model_id,
                                     "worst_case_usd": pricebook.worst_case_usd(model_id, provider, tokens,
                                                                                cfg.max_tokens)})
    calls = pd.DataFrame(rows, columns=["account", "model", "worst_case_usd"])
    table = calls.groupby(["account", "model"]).agg(calls=("worst_case_usd", "size"),
                                                    worst_case_usd=("worst_case_usd", "sum"))
    table["worst_case_x_safety"] = table["worst_case_usd"] * BudgetRules.from_yaml(cfg.budget).safety_multiplier
    return table


def preflight_market(cfg: MarketConfig, config_path: str | Path) -> tuple[list[str], pd.DataFrame | None]:
    """The same gate as a network experiment (experiment.gate_problems); free runs always pass."""
    if is_free(cfg, ProviderRegistry.from_yaml(cfg.providers)):
        return [], None
    table = estimate_market(cfg)
    return gate_problems(cfg, config_path, table), table


TABLES = ["periods", "sessions", "traders", "trades", "turns"]


def session_tables(log: SessionLog, schedule: Schedule, periods_total: int) -> dict[str, pd.DataFrame]:
    turns = pd.DataFrame(log.turns)
    trades = pd.DataFrame(log.trades)
    if turns.empty:
        return {name: pd.DataFrame() for name in TABLES}
    periods = period_metrics(turns, trades, schedule)
    sessions = session_metrics(periods, trades, schedule).assign(
        periods_planned=periods_total, complete=log.periods_done >= periods_total)
    traders = trader_metrics(turns, trades, schedule, pd.Series({log.seed: log.periods_done}))
    trades = trade_table(trades, schedule) if not trades.empty else trades
    return {"periods": periods, "sessions": sessions, "traders": traders, "trades": trades, "turns": turns}


class ResultWriter:
    """Collects each session's tables and writes them, keeping rows of other seeds already on disk."""

    def __init__(self, out: Path, cfg: MarketConfig):
        self.out = out
        self.cfg = cfg
        self.done: dict[str, list[pd.DataFrame]] = {name: [] for name in TABLES}

    def finish(self, log: SessionLog) -> dict[str, pd.DataFrame]:
        tables = session_tables(log, self.cfg.schedule, self.cfg.periods)
        for name in TABLES:
            if name != "turns" or self.cfg.save_turns:
                self.done[name].append(tables[name])
        return tables

    def write(self, current: SessionLog | None = None) -> None:
        self.out.mkdir(parents=True, exist_ok=True)
        frames = {name: list(parts) for name, parts in self.done.items()}
        if current is not None:
            tables = session_tables(current, self.cfg.schedule, self.cfg.periods)
            for name in TABLES:
                frames[name].append(tables[name])
        for name in TABLES:
            if name == "turns" and not self.cfg.save_turns:
                continue
            new = pd.concat([f for f in frames[name] if not f.empty], ignore_index=True) if any(
                not f.empty for f in frames[name]) else pd.DataFrame()
            path = self.out / f"{name}.csv"
            if path.exists() and path.stat().st_size > 0:
                old = pd.read_csv(path)
                if not new.empty and "seed" in old:
                    old = old[~old["seed"].isin(new["seed"].unique())]
                new = pd.concat([old, new], ignore_index=True)
            if not new.empty:
                new.sort_values([c for c in ("seed", "period", "turn", "trade_no", "role", "rank") if c in new],
                                kind="stable").to_csv(path, index=False)


def expectation_misses(turns: pd.DataFrame, periods: pd.DataFrame, expect: MarketExpect) -> list[str]:
    """turns: this run's LLM turns so far; periods: the current session's period table.
    The reply-format rates are checked per model (audit 27, finding 2): in a mixed market a pooled rate would
    let one model's failures hide behind the other's turns. A model's rates apply once it has min_turns turns."""
    misses = []
    if not turns.empty:
        t = turns.assign(unparsed=turns["outcome"].eq("unparsed"),
                         truncated=turns["truncated"].fillna(False).astype(bool) if "truncated" in turns else False)
        rates = t.groupby("model").agg(turns=("unparsed", "size"), unparsed=("unparsed", "mean"),
                                       truncated=("truncated", "mean"))
        for model, r in rates[rates["turns"] >= expect.min_turns].iterrows():
            if expect.max_unparsed_rate is not None and r["unparsed"] > expect.max_unparsed_rate:
                misses.append(f"{r['unparsed']:.1%} of {model} replies have no readable ACTION line "
                              f"(limit {expect.max_unparsed_rate:.0%})")
            if expect.max_truncation_rate is not None and r["truncated"] > expect.max_truncation_rate:
                misses.append(f"{r['truncated']:.1%} of {model} replies truncated by max_tokens "
                              f"(limit {expect.max_truncation_rate:.0%})")
    k = expect.stop_after_zero_trade_periods
    if k and not periods.empty and len(periods) >= k and periods.sort_values("period")["trades"].tail(k).eq(0).all():
        misses.append(f"no trade in the last {k} periods of session {int(periods['seed'].iloc[0])}")
    return misses


async def run_market(cfg: MarketConfig) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Play the selected sessions. Returns (periods, sessions, status) for this run's sessions."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    run_id = f"{cfg.name}-{int(time.time())}"
    free = is_free(cfg, registry)
    if free:  # nothing is spent, so nothing tracked (ledger, cache) is touched; dry runs go to runs/dry
        out_dir = "runs/dry" if cfg.trader == "llm" and cfg.out_dir == "results" else cfg.out_dir
        cfg = cfg.model_copy(update={"git_checkpoint": False, "out_dir": out_dir})
        ledger, cache = Ledger(), CallCache()
    else:
        ledger = Ledger(cfg.ledger, must_exist=cfg.require_ledger)
        cache = CallCache(cfg.cache, shard_prefix=run_id)
    for ref in {t.model for t in make_traders(cfg.schedule, cfg.model_of)} - {"zic"}:
        if registry.provider_of(ref) == "fake":  # fake models answer in the trader reply format
            registry.set_client(ref, FakeTraderClient())
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    runtime = LocalRuntime(registry) if cfg.runtime == "local" else MaritimeRuntime.from_yaml(cfg.maritime)
    caller = MarketCaller(runtime, registry, pricebook=PriceBook.from_yaml(cfg.pricing), cache=cache,
                          governor=governor, run_id=run_id, market=cfg.name, condition=cfg.condition or cfg.name)
    out = Path(cfg.out_dir) / cfg.name
    writer = ResultWriter(out, cfg)
    rules = cfg.rules()
    seeds = cfg.selected_seeds()
    status = {"run_id": run_id, "state": "completed", "reason": "", "seeds": seeds, "checkpoints": []}
    llm_turns: list[pd.DataFrame] = []
    log: SessionLog | None = None

    async def after_period(log: SessionLog, period: int) -> bool:
        if cfg.trader == "zic":  # free and fast: tables are written once at the end
            return True
        cache.rotate()
        if cfg.git_checkpoint:
            status["checkpoints"].append(git_checkpoint([cfg.ledger, cfg.cache], f"state: {run_id} s{log.seed} period {period}"))
        writer.write(current=log)
        tables = session_tables(log, cfg.schedule, cfg.periods)
        misses = expectation_misses(pd.concat([*llm_turns, tables["turns"]], ignore_index=True), tables["periods"],
                                    cfg.expect)
        if misses:
            status.update(state="stopped", reason="expectation missed: " + "; ".join(misses))
            return False
        return True

    async def after_round(log: SessionLog, period: int, round_: int) -> bool:
        """Reply-format stops (unparsed, truncated) after every round, over this run's LLM turns so far."""
        if cfg.trader == "zic":
            return True
        misses = expectation_misses(pd.concat([*llm_turns, pd.DataFrame(log.turns)], ignore_index=True),
                                    pd.DataFrame(), cfg.expect)
        if misses:
            status.update(state="stopped", reason="expectation missed: " + "; ".join(misses))
            return False
        return True

    try:
        for seed in seeds:
            traders = make_traders(cfg.schedule, cfg.model_of)
            if cfg.trader == "zic":
                rng = random.Random(f"zic:{seed}")
                agents = {t.id: ZICTrader(rng, round(cfg.zic_low * 100), round(cfg.zic_high * 100)) for t in traders}
            else:
                agents = {t.id: LLMTrader(caller, t.model, rules, seed, cfg.max_tokens, cfg.temperature) for t in traders}
            log = SessionLog(seed=seed)
            await run_session(cfg.schedule, traders, agents, seed, cfg.periods, cfg.rounds, after_period, log,
                              after_round)
            tables = writer.finish(log)
            if cfg.trader == "llm":
                llm_turns.append(tables["turns"])
            log = None
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
        if log is not None:  # a session cut short by a cap or an error
            writer.finish(log)
        writer.write()
        status["sessions_done"] = sum(1 for part in writer.done["sessions"] if not part.empty and part["complete"].all())
        status["live_calls"] = caller.live_calls
        status["budget"] = governor.status()
        status["rate_limits"] = registry.rate_limits()
        (out / "status.json").write_text(json.dumps(status, indent=2))

    def this_run(name: str) -> pd.DataFrame:
        parts = [f for f in writer.done[name] if not f.empty]
        return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()

    return this_run("periods"), this_run("sessions"), status
