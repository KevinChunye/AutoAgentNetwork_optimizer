"""Command line.

  aan estimate configs/experiments/smoke.yaml   worst-case cost before spending anything
  aan run configs/experiments/smoke.yaml        run an experiment (chunked, budget-governed)
  aan run ... --model-override fake             same, routed to the offline fake model
  aan check configs/experiments/x.yaml          the gate a paid run must pass (prereg, committed, fits budget)
  aan run configs/experiments/market/m2.yaml --session-offset 1 --session-limit 1
                                                a market config (kind: market): one session of the condition
  aan run configs/experiments/desk/w2a_tune.yaml --task-offset 0 --task-limit 20
                                                a desk config (kind: desk): events 0-19 of each sequence
  aan run configs/experiments/evidence/e13_bbeh_anthropic.yaml --task-offset 0 --task-limit 50
                                                a panel config (kind: panel): items 0-49 of its id list
  aan status                                    spend vs hard caps and the active phase
  aan bill                                      spend by account and model
  aan agents configs/networks/dense_3x6.yaml    list the network's agents
  aan models haiku gpt_small                    model IDs each ref's key can use (free GET /v1/models)
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path

import pandas as pd

from .budget import BudgetRules, SpendGovernor
from .experiment import ExperimentConfig, estimate_experiment, preflight, run_experiment
from .desk.run import DeskConfig, estimate_desk, is_desk_config, preflight_desk, run_desk
from .market.run import MarketConfig, estimate_market, is_market_config, preflight_market, run_market
from .evidence.panel import PanelConfig, estimate_panel, is_panel_config, preflight_panel, run_panel
from .phoenix.run import PhoenixConfig, estimate_phoenix, is_phoenix_config, preflight_phoenix, run_phoenix
from .phoenix.batch import PhoenixBatchConfig, estimate_batch, is_batch_config, preflight_batch, run_batch
from .self_or_social.run import SelfOrSocialConfig, estimate_sos, is_sos_config, preflight_sos, run_sos
from .meter import Ledger
from .network.spec import NetworkSpec
from .providers.registry import ProviderRegistry


def load_cfg(args) -> ExperimentConfig | MarketConfig | DeskConfig:
    """A network experiment, a market config (kind: market), whose sessions the task flags pick, or a
    desk config (kind: desk), whose events in each sequence the task flags pick."""
    if is_batch_config(args.config):
        cfg = PhoenixBatchConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "task_limit": args.task_limit,
                   "task_offset": args.task_offset}
    elif is_phoenix_config(args.config):
        cfg = PhoenixConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "task_limit": args.task_limit,
                   "task_offset": args.task_offset}
    elif is_sos_config(args.config):
        cfg = SelfOrSocialConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "task_limit": args.task_limit,
                   "task_offset": args.task_offset}
    elif is_panel_config(args.config):
        cfg = PanelConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "task_limit": args.task_limit,
                   "task_offset": args.task_offset}
    elif is_desk_config(args.config):
        cfg = DeskConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "event_limit": args.task_limit,
                   "event_offset": args.task_offset}
    elif is_market_config(args.config):
        cfg = MarketConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "session_limit": args.task_limit,
                   "session_offset": args.task_offset}
    else:
        cfg = ExperimentConfig.from_yaml(args.config)
        updates = {"model_override": args.model_override, "task_limit": args.task_limit,
                   "task_offset": args.task_offset}
    if getattr(args, "no_checkpoint", False):
        updates["git_checkpoint"] = False
    return cfg.model_copy(update={k: v for k, v in updates.items() if v is not None})


def record_estimate(table: pd.DataFrame, cfg: ExperimentConfig | MarketConfig, config_path: str, csv_path: str) -> None:
    """Append one row per account/model to a CSV, so the budget statement can compare
    each run's estimate with its actual spend (analysis/budget.py). For a market config the
    offset and limit count sessions."""
    market, desk = isinstance(cfg, MarketConfig), isinstance(cfg, DeskConfig)
    rows = table.reset_index().assign(
        date=pd.Timestamp.now(tz="UTC").strftime("%Y-%m-%d %H:%M"),
        experiment=cfg.name,
        config=config_path,
        task_offset=cfg.session_offset if market else cfg.event_offset if desk else cfg.task_offset,
        task_limit=cfg.session_limit if market else cfg.event_limit if desk else cfg.task_limit,
        model_override=cfg.model_override_resolved(),
    )
    path = Path(csv_path)
    rows.to_csv(path, mode="a", header=not path.exists(), index=False)
    print(f"recorded in {path}")


def print_room(cfg, table: pd.DataFrame | None) -> None:
    """Each account's room under its tightest cap (hard cap, the phase's account cap, the phase total),
    after the safety multiplier, next to this config's worst case for that account."""
    rules = BudgetRules.from_yaml(cfg.budget)
    governor = SpendGovernor(Ledger(cfg.ledger, must_exist=False), rules)
    worst = table.groupby(level="account")["worst_case_usd"].sum() if table is not None and len(table) else pd.Series(dtype=float)
    phase = rules.active_phase
    print(f"phase {rules.phase!r}: total ${phase.total_usd if phase else float('nan'):.0f}, run cap "
          f"${phase.max_run_usd if phase else float('nan'):.2f}, account caps {phase.account_caps_usd if phase else {}}")
    for account, room in governor.room_by_account().items():
        print(f"  {account}: room ${room:.2f} of new estimated spend; this config's worst case ${worst.get(account, 0.0):.2f}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="aan", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    for name, text in [("run", "run an experiment config"), ("estimate", "worst-case cost of a config"),
                       ("check", "the gate a paid run must pass")]:
        p = sub.add_parser(name, help=text)
        p.add_argument("config")
        p.add_argument("--model-override", default=None)
        p.add_argument("--task-limit", "--session-limit", dest="task_limit", type=int, default=None)
        p.add_argument("--task-offset", "--session-offset", dest="task_offset", type=int, default=None)
        if name == "run":
            p.add_argument("--no-checkpoint", action="store_true", help="skip git commit/push of state/")
        elif name == "estimate":
            p.add_argument("--record", default=None, help="append the estimate to this CSV (e.g. research/estimates.csv)")

    agents = sub.add_parser("agents", help="list a network's agents")
    agents.add_argument("network")
    models = sub.add_parser("models", help="list the model IDs each ref's key can use (free)")
    models.add_argument("refs", nargs="+")
    models.add_argument("--providers", default="configs/providers.yaml")
    for name in ("bill", "status"):
        p = sub.add_parser(name, help=f"show {name}")
        p.add_argument("--ledger", default="state/ledger.jsonl")
        p.add_argument("--budget", default="configs/budget.yaml")

    args = parser.parse_args()
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 30)

    if args.command in ("run", "check"):
        cfg = load_cfg(args)
        market, desk, panel = isinstance(cfg, MarketConfig), isinstance(cfg, DeskConfig), isinstance(cfg, PanelConfig)
        phoenix, sos = isinstance(cfg, PhoenixConfig), isinstance(cfg, SelfOrSocialConfig)
        batch = isinstance(cfg, PhoenixBatchConfig)
        problems, table = (preflight_batch(cfg, args.config) if batch else
                           preflight_phoenix(cfg, args.config) if phoenix else
                           preflight_market(cfg, args.config) if market else preflight_desk(cfg, args.config) if desk
                           else preflight_panel(cfg, args.config) if panel
                           else preflight_sos(cfg, args.config) if sos else preflight(cfg, args.config))
        if table is not None:
            print(table.round(4).to_string())
            print_room(cfg, table)
        if problems:
            print("NOT CLEARED to run:\n- " + "\n- ".join(problems))
            raise SystemExit(1)
        print("cleared" + (" (dry run)" if table is None else ""))
    if args.command == "run" and batch:
        status = run_batch(cfg, args.config)
        print(json.dumps({k: v for k, v in status.items() if k != "branches"}, indent=2, default=str))
        if status["status"] != "completed":
            raise SystemExit(1)
    elif args.command == "run" and phoenix:
        _, _, status = asyncio.run(run_phoenix(cfg, args.config))
        print(json.dumps(status, indent=2))
        if status["status"].startswith("error") or status["status"] == "state_sync_failed":
            raise SystemExit(1)
    elif args.command == "run" and sos:
        _, status = asyncio.run(run_sos(cfg))
        print(json.dumps({k: v for k, v in status.items() if k != "team"}, indent=2, default=str))
    elif args.command == "run" and panel:
        _, status = asyncio.run(run_panel(cfg))
        print(json.dumps({k: v for k, v in status.items() if k != "sources"}, indent=2, default=str))
    elif args.command == "run":
        rows, summary, status = asyncio.run(run_market(cfg) if market else run_desk(cfg) if desk else run_experiment(cfg))
        if desk:
            summary = pd.DataFrame()  # the desk's tables are in results/<name>/; analysis/desk.py reads them
        if not summary.empty:
            print(summary.round(4).to_string())
        print(json.dumps(status, indent=2))
    elif args.command == "estimate":
        cfg = load_cfg(args)
        table = (estimate_batch(cfg) if isinstance(cfg, PhoenixBatchConfig) else
                 estimate_phoenix(cfg) if isinstance(cfg, PhoenixConfig) else
                 estimate_market(cfg) if isinstance(cfg, MarketConfig) else estimate_desk(cfg) if isinstance(cfg, DeskConfig)
                 else estimate_panel(cfg) if isinstance(cfg, PanelConfig)
                 else estimate_sos(cfg) if isinstance(cfg, SelfOrSocialConfig) else asyncio.run(estimate_experiment(cfg)))
        print(table.round(4).to_string())
        run_cap = "none of its own (phase and hard caps apply)" if cfg.max_usd is None else f"${cfg.max_usd}"
        print(f"\nupper bound, ignores cached calls; run cap for this config: {run_cap}")
        print_room(cfg, table)
        if args.record:
            record_estimate(table, cfg, args.config, args.record)
    elif args.command == "agents":
        network = NetworkSpec.from_yaml(args.network)
        table = pd.DataFrame([s.model_dump(include={"agent_id", "model", "max_tokens"}) for s in network.all_agents()])
        print(table.to_string(index=False))
    elif args.command == "models":
        registry = ProviderRegistry.from_yaml(args.providers)
        for ref in args.refs:
            ids = asyncio.run(registry.client(ref).list_models())
            wanted = registry.model_id(ref)
            print(f"{ref}: configured {wanted!r} {'IS' if wanted in ids else 'IS NOT'} listed; {len(ids)} models")
            print("  " + ", ".join(sorted(ids)))
    elif args.command == "bill":
        ledger = Ledger(args.ledger, must_exist=True)
        print(ledger.bill().to_string() if ledger.records else "no paid calls yet")
        print(f"total: ${ledger.spent_usd():.4f}")
    elif args.command == "status":
        governor = SpendGovernor(Ledger(args.ledger, must_exist=True), BudgetRules.from_yaml(args.budget))
        print(json.dumps(governor.status(), indent=2))


if __name__ == "__main__":
    main()
