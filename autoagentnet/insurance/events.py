"""Turn agent traces into an episode table an underwriter can price.

Every loader returns one row per insured episode with the same columns (EPISODE_COLUMNS):

  source       where the row came from: "tau2" (public tau2-bench trajectories),
               "market" (AutoAgentNetwork market-town traders), "network" (AutoAgentNetwork
               pilot networks)
  model        the foundation model that drove the agent (the accumulation key: one model
               defect hits every customer that runs it)
  context      the deployment the agent worked in (airline, retail, telecom, a market role,
               a task family). The rating class
  task_id      the task; repeated trials of one task let us measure how defaults cluster
  trial        trial number within a task (0, 1, ...)
  default      1 if the episode breached its mandate, else 0
  kind         "ok", "commission" (wrong state change), "omission" (needed change not made)
               or "communication" (state right, but the customer was told something wrong)
  n_writes     state-changing tool calls the agent made in the episode
  escalated    1 if the agent handed the case to a human
  exposure_usd gross dollars touched by the episode's state changes (0 if none)
  cost_usd     what the episode cost to run (model spend), for the premium-to-cost ratio

The tau2 loader also reads dollar exposure from the tool results: a refund, cancellation or
return touches the order or reservation it acts on, and its payment history says what that is
worth. Each object counts once per episode (its largest value), however many writes touched it. That figure is gross value at risk, not loss; the loss is LGD x exposure (actuarial.py).
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

EPISODE_COLUMNS = ["source", "model", "context", "task_id", "trial", "default", "kind",
                   "n_writes", "escalated", "exposure_usd", "cost_usd"]

# State-changing agent tools in tau2-bench, by domain. Reads (get_*, search_*, calculate) are not
# here: they cannot cause a loss by themselves.
TAU2_WRITE_TOOLS = {
    "airline": {"book_reservation", "cancel_reservation", "update_reservation_flights",
                "update_reservation_baggages", "update_reservation_passengers", "send_certificate"},
    "retail": {"cancel_pending_order", "modify_pending_order_items", "modify_pending_order_address",
               "modify_pending_order_payment", "modify_user_address", "return_delivered_order_items",
               "exchange_delivered_order_items"},
    "telecom": {"refuel_data", "send_payment_request", "resume_line", "enable_roaming",
                "suspend_line"},
}
ESCALATION_TOOL = "transfer_to_human_agents"


def _payments(obj: dict) -> float:
    """Sum of the 'payment' entries in an order or reservation's payment history."""
    total = 0.0
    for p in obj.get("payment_history") or []:
        if p.get("transaction_type", "payment") == "payment":
            total += float(p.get("amount") or 0.0)
    return total


def write_exposure(arguments: dict, result_text: str | None) -> float:
    """Dollar value a single state-changing call touched (see write_target for which object).

    Rules, in order (first that applies):
      1. the call names an amount (a certificate, a payment request): that amount;
      2. the call names item_ids and the result lists items with prices: those items' prices;
      3. the result has a payment history (order or reservation): what was paid for it;
      4. otherwise 0 (an address change, a line resumed: no money moved).
    """
    if arguments and arguments.get("amount") is not None:
        try:
            return float(arguments["amount"])
        except (TypeError, ValueError):
            pass
    try:
        result = json.loads(result_text) if result_text else None
    except (TypeError, ValueError):
        result = None
    if not isinstance(result, dict):
        return 0.0
    item_ids = (arguments or {}).get("item_ids")
    if item_ids and result.get("items"):
        wanted = set(item_ids)
        priced = [float(i.get("price") or 0.0) for i in result["items"] if i.get("item_id") in wanted]
        if priced:
            return float(sum(priced))
    return _payments(result)


def write_target(arguments: dict) -> str:
    """The object a write acts on (order, reservation, user, line), so two writes to the same
    order count its value once. Falls back to the call's own arguments."""
    for key in ("order_id", "reservation_id", "user_id", "line_id", "customer_id"):
        if arguments and arguments.get(key):
            return f"{key}={arguments[key]}"
    return json.dumps(arguments or {}, sort_keys=True)


def _model_from_filename(name: str) -> tuple[str, str]:
    """tau2 result files are named <agent model>_<domain>_<mode>_<user model>_<n>trials.json."""
    parts = name.split("_")
    return parts[0], parts[1]


def tau2_episodes(path: str | Path) -> pd.DataFrame:
    """Episodes from one tau2-bench results file (data/tau2/results/final/*.json).

    default: reward < 1 (tau2's own pass/fail).
    kind: commission if the final database is wrong and the agent wrote to it; omission if the
    database is wrong and it wrote nothing; communication if the database matched (or was not
    graded) but another check failed.
    """
    path = Path(path)
    model, domain = _model_from_filename(path.name)
    writes = TAU2_WRITE_TOOLS.get(domain, set())
    data = json.loads(path.read_text())
    rows = []
    for sim in data["simulations"]:
        info = sim.get("reward_info") or {}
        reward = float(info.get("reward") or 0.0)
        db = info.get("db_check") or {}
        db_ok = db.get("db_match", True) if db else True
        messages = sim.get("messages") or []
        results_by_id = {}
        for m in messages:
            if m.get("role") == "tool" and m.get("id"):
                results_by_id[m["id"]] = m.get("content")
        n_writes, escalated = 0, 0
        touched = {}  # object -> largest dollar value any write saw for it
        for m in messages:
            if m.get("role") != "assistant":
                continue
            for call in m.get("tool_calls") or []:
                if call["name"] == ESCALATION_TOOL:
                    escalated = 1
                if call["name"] in writes:
                    n_writes += 1
                    args = call.get("arguments") or {}
                    value = write_exposure(args, results_by_id.get(call.get("id")))
                    target = write_target(args)
                    if target not in touched or value > touched[target]:
                        touched[target] = value
        exposure = float(sum(touched.values()))
        default = int(reward < 1.0)
        if not default:
            kind = "ok"
        elif not db_ok and n_writes > 0:
            kind = "commission"
        elif not db_ok:
            kind = "omission"
        else:
            kind = "communication"
        rows.append({"source": "tau2", "model": model, "context": domain, "task_id": str(sim["task_id"]),
                     "trial": int(sim.get("trial") or 0), "default": default, "kind": kind,
                     "n_writes": n_writes, "escalated": escalated, "exposure_usd": exposure,
                     "cost_usd": float(sim.get("agent_cost") or 0.0)})
    return pd.DataFrame(rows, columns=EPISODE_COLUMNS)


def tau2_dir(directory: str | Path, pattern: str = "*.json") -> pd.DataFrame:
    """All tau2 results files in a folder, stacked."""
    files = sorted(Path(directory).glob(pattern))
    frames = [tau2_episodes(f) for f in files]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame(columns=EPISODE_COLUMNS)


def market_actions(results_dir: str | Path) -> pd.DataFrame:
    """Order-level breach table from market-town runs (results/m*/turns.csv).

    One row per BID, ASK or ACCEPT a trader tried. Columns:
      model, role, run, seed, trader
      breach        1 if the order was outside the trader's mandate: a buyer bidding above its
                    value or a seller asking below its cost. The engine rejects these
                    ("rejected:budget"), so breach = an attempted loss the guardrail stopped.
      overshoot_usd how far past the limit the order was (0 if no breach); the loss per unit
                    the principal would have taken had the guardrail not been there
      limit_usd     the trader's value (buyer) or cost (seller): the mandate's limit
    """
    frames = []
    for f in sorted(Path(results_dir).glob("m*/turns.csv")):
        t = pd.read_csv(f)
        t["run"] = f.parent.name
        frames.append(t)
    if not frames:
        return pd.DataFrame()
    turns = pd.concat(frames, ignore_index=True)
    orders = turns[turns["action"].isin(["BID", "ASK", "ACCEPT"])].copy()
    orders["breach"] = orders["outcome"].eq("rejected:budget").astype(int)
    # The price an ACCEPT would have paid is the standing quote it accepted.
    price = orders["price"].copy()
    accept_buy = orders["action"].eq("ACCEPT") & orders["role"].eq("buyer")
    accept_sell = orders["action"].eq("ACCEPT") & orders["role"].eq("seller")
    price[accept_buy] = price[accept_buy].fillna(orders.loc[accept_buy, "best_ask_before"])
    price[accept_sell] = price[accept_sell].fillna(orders.loc[accept_sell, "best_bid_before"])
    over = np.where(orders["role"].eq("buyer"), price - orders["limit"], orders["limit"] - price)
    orders["overshoot_usd"] = np.where(orders["breach"].eq(1), np.clip(over, 0.0, None), 0.0)
    orders["limit_usd"] = orders["limit"]
    return orders[["run", "seed", "period", "trader", "role", "model", "action", "price", "limit_usd",
                   "outcome", "breach", "overshoot_usd"]].reset_index(drop=True)


def market_episodes(results_dir: str | Path) -> pd.DataFrame:
    """Market traders as insured episodes: one row per trader per session.

    default: the trader tried at least one order outside its mandate in the session.
    exposure_usd: the trader's limit times its orders (the most it could have committed).
    """
    a = market_actions(results_dir)
    if a.empty:
        return pd.DataFrame(columns=EPISODE_COLUMNS)
    g = a.groupby(["run", "seed", "trader", "role", "model"], as_index=False).agg(
        breaches=("breach", "sum"), orders=("breach", "size"), limit=("limit_usd", "first"))
    out = pd.DataFrame({
        "source": "market", "model": g["model"], "context": "market_" + g["role"],
        "task_id": g["run"] + "/" + g["trader"], "trial": g["seed"],
        "default": (g["breaches"] > 0).astype(int),
        "kind": np.where(g["breaches"] > 0, "commission", "ok"),
        "n_writes": g["orders"], "escalated": 0,
        "exposure_usd": g["limit"] * g["orders"], "cost_usd": 0.0})
    return out[EPISODE_COLUMNS]


def network_agents(results_dir: str | Path, pattern: str = "p*") -> pd.DataFrame:
    """Agent-level answers from AutoAgentNetwork pilot runs, one row per distinct agent call.

    Pruned configs re-use the dense network's calls, so the same call appears in many configs;
    rows are de-duplicated on (task, replicate, stage, agent). Columns:
      task_id, family (the task family, e.g. bbeh-web_of_lies), replicate, stage, agent_id,
      correct (1/0), run.
    """
    frames = []
    for f in sorted(Path(results_dir).glob(f"{pattern}/agents.csv")):
        a = pd.read_csv(f)
        a["run"] = f.parent.name
        frames.append(a)
    if not frames:
        return pd.DataFrame()
    a = pd.concat(frames, ignore_index=True)
    a = a.dropna(subset=["correct"])
    a = a.drop_duplicates(subset=["task_id", "replicate", "stage", "agent_id"])
    a["family"] = a["task_id"].str.rsplit("-", n=1).str[0]
    a["correct"] = a["correct"].astype(int)
    return a[["run", "task_id", "family", "replicate", "stage", "agent_id", "correct"]].reset_index(drop=True)


def network_episodes(results_dir: str | Path, pattern: str = "p*") -> pd.DataFrame:
    """Network-level outcomes (results/p*/results.csv) as episodes: one row per network answer.

    Only the full dense network, the single Haiku agent and the single Sonnet agent are kept, so
    every row is a deployable product rather than a pruned variant. default = wrong final answer.
    """
    frames = []
    for f in sorted(Path(results_dir).glob(f"{pattern}/results.csv")):
        r = pd.read_csv(f)
        r["run"] = f.parent.name
        frames.append(r)
    if not frames:
        return pd.DataFrame(columns=EPISODE_COLUMNS)
    r = pd.concat(frames, ignore_index=True).dropna(subset=["correct"])
    dense = r["network"].eq("dense_3x6") & r["config_id"].eq("k6-6-6-1")
    single = r["network"].isin(["single", "single_sonnet"])
    r = r[dense | single].drop_duplicates(subset=["network", "task_id", "replicate"])
    model = np.where(r["network"].eq("single_sonnet"), "sonnet-5.5", "haiku-5.5")
    product = np.where(r["network"].eq("dense_3x6"), "dense_3x6", "single")
    out = pd.DataFrame({
        "source": "network", "model": model, "context": r["task_id"].str.rsplit("-", n=1).str[0],
        "task_id": r["task_id"], "trial": r["replicate"].astype(int),
        "default": (r["correct"] < 1).astype(int), "kind": np.where(r["correct"] < 1, "omission", "ok"),
        "n_writes": 0, "escalated": 0, "exposure_usd": 0.0, "cost_usd": r["cost_usd"]})
    out["product"] = product
    return out.reset_index(drop=True)
