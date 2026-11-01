"""Market metrics from the turn and trade tables a session writes.

Per period (one row per seed and period):
  trades             units traded
  trade_ratio        trades / Q*
  surplus            sum over trades of (buyer value - seller cost); the price only moves profit
                     between the two sides, so it does not enter
  efficiency         allocative efficiency E = surplus / maximum surplus (schedule.py); 1.0 means
                     every unit went to the right trader
  mean_price         mean trade price
  alpha              Smith's (1962) convergence coefficient: 100 x the root mean squared deviation
                     of the period's trade prices from P*, divided by P* (p_star). Lower = closer
  extramarginal      trades in which the buyer or the seller is extramarginal (rank > Q*); every
                     such trade displaces surplus
  orders / rejected  BID, ASK and ACCEPT actions, and how many the book rejected
  rejected_rate      rejected / orders
  turns / unparsed   trader turns, and LLM replies with no readable ACTION line
  unparsed_rate      unparsed / turns
  truncated_rate     share of turns whose reply was cut off by max_tokens
  cost_usd           list-price dollars of the period's calls (cached calls at their original price)
Per session: the same, summed (or pooled) over its periods; efficiency is the session's surplus over
periods x maximum surplus.
Per trader (one row per seed and trader): profit over the session, CE profit over the session
(schedule.py, times the periods run) and profit_ratio = profit / CE profit (undefined for
extramarginal traders, whose CE profit is 0; group comparisons pool profit and CE profit first).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .schedule import Schedule

TURN_DEFAULTS = {"cost_usd": 0.0, "truncated": False}


def _turns(turns: pd.DataFrame) -> pd.DataFrame:
    out = turns.copy()
    for column, default in TURN_DEFAULTS.items():
        if column not in out:
            out[column] = default
    out["cost_usd"] = out["cost_usd"].fillna(0.0)
    out["truncated"] = out["truncated"].fillna(False).astype(bool)
    out["is_order"] = out["action"].isin(["BID", "ASK", "ACCEPT"])
    out["is_rejected"] = out["outcome"].str.startswith("rejected")
    out["is_unparsed"] = out["outcome"].eq("unparsed")
    return out


def alpha(prices: pd.Series, p_star: float) -> float:
    if len(prices) == 0:
        return float("nan")
    return float(100 * np.sqrt(((prices - p_star) ** 2).mean()) / p_star)


def trade_table(trades: pd.DataFrame, schedule: Schedule) -> pd.DataFrame:
    out = trades.copy()
    out["surplus"] = out["buyer_value"] - out["seller_cost"]
    out["extramarginal"] = (out["buyer_rank"] > schedule.q_star) | (out["seller_rank"] > schedule.q_star)
    return out


def period_metrics(turns: pd.DataFrame, trades: pd.DataFrame, schedule: Schedule) -> pd.DataFrame:
    t = _turns(turns)
    keys = ["seed", "period"]
    base = t.groupby(keys).agg(turns=("trader", "size"), orders=("is_order", "sum"),
                               rejected=("is_rejected", "sum"), unparsed=("is_unparsed", "sum"),
                               truncated=("truncated", "sum"), cost_usd=("cost_usd", "sum"))
    if trades.empty:
        tr = pd.DataFrame(columns=["trades", "surplus", "mean_price", "alpha", "extramarginal"],
                          index=base.index, dtype=float)
    else:
        x = trade_table(trades, schedule)
        tr = x.groupby(keys).agg(trades=("price", "size"), surplus=("surplus", "sum"),
                                 mean_price=("price", "mean"), extramarginal=("extramarginal", "sum"))
        tr["alpha"] = x.groupby(keys)["price"].apply(lambda p: alpha(p, schedule.p_star))
    out = base.join(tr, how="left")
    out[["trades", "surplus", "extramarginal"]] = out[["trades", "surplus", "extramarginal"]].fillna(0)
    out["trade_ratio"] = out["trades"] / schedule.q_star
    out["efficiency"] = out["surplus"] / schedule.max_surplus
    out["rejected_rate"] = out["rejected"] / out["orders"].where(out["orders"] > 0)
    out["unparsed_rate"] = out["unparsed"] / out["turns"]
    out["truncated_rate"] = out["truncated"] / out["turns"]
    return out.reset_index()


def session_metrics(periods: pd.DataFrame, trades: pd.DataFrame, schedule: Schedule) -> pd.DataFrame:
    sums = periods.groupby("seed")[["turns", "orders", "rejected", "unparsed", "truncated", "cost_usd", "trades",
                                    "surplus", "extramarginal"]].sum()
    sums["periods"] = periods.groupby("seed").size()
    sums["efficiency"] = sums["surplus"] / (sums["periods"] * schedule.max_surplus)
    sums["trade_ratio"] = sums["trades"] / (sums["periods"] * schedule.q_star)
    sums["rejected_rate"] = sums["rejected"] / sums["orders"].where(sums["orders"] > 0)
    sums["unparsed_rate"] = sums["unparsed"] / sums["turns"]
    sums["truncated_rate"] = sums["truncated"] / sums["turns"]
    sums["zero_trade_periods"] = periods.assign(zero=periods["trades"].eq(0)).groupby("seed")["zero"].sum()
    if not trades.empty:
        sums["mean_price"] = trades.groupby("seed")["price"].mean()
        last = periods.groupby("seed")["period"].max().rename("last_period")
        last_trades = trades.merge(last, left_on="seed", right_index=True)
        last_trades = last_trades[last_trades["period"] == last_trades["last_period"]]
        sums["last_period_mean_price"] = last_trades.groupby("seed")["price"].mean()
    return sums.reset_index()


def trader_metrics(turns: pd.DataFrame, trades: pd.DataFrame, schedule: Schedule, periods_run: pd.Series) -> pd.DataFrame:
    """periods_run: periods each seed completed (index seed), for the CE profit over the session."""
    traders = turns.groupby(["seed", "trader"]).agg(role=("role", "first"), rank=("rank", "first"),
                                                     model=("model", "first"), limit=("limit", "first")).reset_index()
    if trades.empty:
        traders["profit"] = 0.0
        traders["trades"] = 0
    else:
        buys = trades.assign(trader=trades["buyer"], profit=trades["buyer_value"] - trades["price"])
        sells = trades.assign(trader=trades["seller"], profit=trades["price"] - trades["seller_cost"])
        both = pd.concat([buys, sells])
        made = both.groupby(["seed", "trader"]).agg(profit=("profit", "sum"), trades=("price", "size"))
        traders = traders.merge(made, left_on=["seed", "trader"], right_index=True, how="left")
        traders[["profit", "trades"]] = traders[["profit", "trades"]].fillna(0)
    ce_per_period = [schedule.ce_profit(r, k) for r, k in zip(traders["role"], traders["rank"])]
    traders["ce_profit"] = np.array(ce_per_period) * traders["seed"].map(periods_run).to_numpy()
    traders["intramarginal"] = traders["rank"] <= schedule.q_star
    traders["profit_ratio"] = traders["profit"] / traders["ce_profit"].where(traders["ce_profit"] > 0)
    return traders.sort_values(["seed", "role", "rank"]).reset_index(drop=True)


def waiting_metrics(turns: pd.DataFrame, schedule: Schedule, rounds: int, late_rounds: int = 3) -> pd.DataFrame:
    """How much traders wait (audit 26, finding 3), one row per seed and period.

    late_pass_share  share of turns in the last `late_rounds` rounds, taken by traders with a positive CE
                     profit (they gain from trading at P*; on the Smith schedule ranks 1-5), that are PASS
                     (an unparsed reply counts, since the engine treats it as a PASS; audit 27).
                     Every trader who acts has not traded yet, so these are profitable traders sitting out.
    final_spread     best ask minus best bid after the period's last turn (NaN when a side is empty)
    """
    t = turns.copy()
    t["profitable"] = [schedule.ce_profit(r, k) > 0 for r, k in zip(t["role"], t["rank"])]
    late = t[(t["round"] > rounds - late_rounds) & t["profitable"]].assign(
        passed=lambda d: d["outcome"].isin(["pass", "unparsed"]))  # an unreadable reply acts as a PASS
    share = late.groupby(["seed", "period"])["passed"].mean().rename("late_pass_share")
    last = t.sort_values("turn").groupby(["seed", "period"]).tail(1).set_index(["seed", "period"])
    spread = (last["best_ask_after"] - last["best_bid_after"]).rename("final_spread")
    return pd.concat([share, spread], axis=1).reset_index()


def profit_gap(traders: pd.DataFrame, senior: pd.Series) -> dict:
    """Senior minus junior share of CE profit, in points: 100 x (pooled senior profit / pooled senior CE
    profit - pooled junior profit / pooled junior CE profit), overall and by side. `traders` is
    trader_metrics over the sessions compared; `senior` marks its senior rows (aligned with it)."""
    t = traders.assign(senior=senior.to_numpy())
    out = {}
    for side, part in [("all", t), ("buyer", t[t["role"] == "buyer"]), ("seller", t[t["role"] == "seller"])]:
        pooled = part.groupby("senior")[["profit", "ce_profit"]].sum()
        share = 100 * pooled["profit"] / pooled["ce_profit"]
        out[side] = float(share.get(True, np.nan) - share.get(False, np.nan))
    return out


def rank_pair_interval(traders: pd.DataFrame, senior: pd.Series, draws: int = 10_000, seed: int = 0) -> tuple[float, float]:
    """95% interval of the overall profit gap from resampling (role, rank) pairs: in M4 every rank is senior
    in one session and junior in the other, so each pair holds one senior and one junior trader. Descriptive
    only: it ignores session-to-session variation (audit 26, finding 1)."""
    t = traders.assign(senior=senior.to_numpy())
    pairs = t.pivot_table(index=["role", "rank"], columns="senior", values=["profit", "ce_profit"], aggfunc="sum")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(pairs), size=(draws, len(pairs)))
    s_profit, j_profit = pairs[("profit", True)].to_numpy()[idx].sum(1), pairs[("profit", False)].to_numpy()[idx].sum(1)
    s_ce, j_ce = pairs[("ce_profit", True)].to_numpy()[idx].sum(1), pairs[("ce_profit", False)].to_numpy()[idx].sum(1)
    with np.errstate(invalid="ignore", divide="ignore"):
        gaps = 100 * (s_profit / s_ce - j_profit / j_ce)
    lo, hi = np.nanpercentile(gaps, [2.5, 97.5])
    return float(lo), float(hi)


def placebo_gaps(traders: pd.DataFrame, per_side: int = 1) -> pd.DataFrame:
    """Profit gaps with no senior at all (audit 26, finding 1), from the sessions of one all-same-model
    condition (M2). Every way to pick `per_side` sessions as "A" (odd ranks labeled senior) and `per_side`
    other sessions as "B" (even ranks labeled senior), as M4 does with its A and B sessions. With M2's 4
    sessions: 12 ordered pairs for per_side=1, 6 splits into two A and two B sessions for per_side=2."""
    from itertools import combinations

    rows = []
    seeds = sorted(traders["seed"].unique())
    for group_a in combinations(seeds, per_side):
        rest = [x for x in seeds if x not in group_a]
        for group_b in combinations(rest, per_side):
            part = traders[traders["seed"].isin(group_a + group_b)]
            odd = part["rank"] % 2 == 1
            senior = (part["seed"].isin(group_a) & odd) | (part["seed"].isin(group_b) & ~odd)
            rows.append({"seeds_odd": " ".join(map(str, group_a)), "seeds_even": " ".join(map(str, group_b)),
                         **{f"gap_{k}": v for k, v in profit_gap(part, senior).items()}})
    return pd.DataFrame(rows)


def senior_breakdown(traders: pd.DataFrame, trades: pd.DataFrame, senior_model: str, p_star: float,
                     periods_run: pd.Series) -> dict:
    """Where an M4 profit gap comes from (audit 26, finding 2). periods_run: periods each seed played.

    trade_rate_senior / _junior  share of (trader, period) slots of traders with a positive CE profit that
                                 ended in a trade, by model: who gets to trade
    price_edge                   mean, over trades between a senior and a junior, of the senior's price
                                 advantage relative to P*: P* - price for a senior buyer, price - P* for a
                                 senior seller (dollars): at what price
    cross_trades                 how many such trades there were
    """
    profitable = traders[traders["ce_profit"] > 0].assign(
        slots=lambda d: d["seed"].map(periods_run), is_senior=lambda d: d["model"] == senior_model)
    slots = profitable.groupby("is_senior")[["trades", "slots"]].sum()
    rate = slots["trades"] / slots["slots"]
    cross = trades[(trades["buyer_model"] == senior_model) != (trades["seller_model"] == senior_model)]
    edge = np.where(cross["buyer_model"] == senior_model, p_star - cross["price"], cross["price"] - p_star)
    return {"trade_rate_senior": float(rate.get(True, np.nan)), "trade_rate_junior": float(rate.get(False, np.nan)),
            "price_edge": float(edge.mean()) if len(edge) else float("nan"), "cross_trades": int(len(cross))}
