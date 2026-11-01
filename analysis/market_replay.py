"""Data for the Market Town Replay artifact: every LLM session, turn by turn.

Writes reports/market/replay/data.json and market_town_replay.html (template.html with the data inlined):
  schedule   values, costs, P*, Q* and maximum surplus (Smith Test 1)
  sessions   one entry per LLM session (M1, M2, M4, M3; a session a stop rule cut short too), with its traders (role, rank, value or cost,
             model) and its turns in order. A turn is a list:
             [period, round, trader, action, price, outcome, best_bid_after, best_ask_after, trade_price,
              counterparty, reason]
             action is BID / ASK / ACCEPT / PASS / UNPARSED; outcome is posted / trade / pass / unparsed /
             rejected:<why>; prices are dollars (null when absent); reason is the trader's one sentence.
The page computes the book, the price path and the running efficiency from these rows.

Usage: python -m analysis.market_replay
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from autoagentnet.market.schedule import Schedule

from .market import CONDITIONS, LABELS, RESULTS, REPORT, load

MODEL_NAMES = {"haiku_nothink": "Haiku", "sonnet_nothink": "Sonnet"}
TURN_COLUMNS = ["period", "round", "trader", "action", "price", "outcome", "best_bid_after", "best_ask_after",
                "trade_price", "counterparty", "reason"]


def clean(value):
    if value is None or (isinstance(value, float) and value != value):
        return None
    return value


def replay_data(results: Path = RESULTS) -> dict:
    s = Schedule()
    out = {"schedule": {"values": s.values, "costs": s.costs, "p_star": s.p_star, "q_star": s.q_star,
                        "max_surplus": s.max_surplus}, "sessions": []}
    for condition, names in CONDITIONS.items():
        for name in names:
            sessions = load([name], "sessions", results)  # stopped sessions too
            turns = load([name], "turns", results)
            if sessions.empty or turns.empty:
                continue
            for seed in sessions["seed"]:
                t = turns[turns["seed"] == seed].sort_values(["period", "turn"])
                traders = t.groupby("trader").agg(role=("role", "first"), rank=("rank", "first"),
                                                  limit=("limit", "first"), model=("model", "first")).reset_index()
                traders = traders.sort_values(["role", "rank"])
                row = sessions[sessions["seed"] == seed].iloc[0]
                out["sessions"].append({
                    "id": f"{name}/{int(seed)}", "condition": LABELS[condition], "config": name, "seed": int(seed),
                    "periods": int(t["period"].max()), "rounds": int(t["round"].max()),
                    "efficiency": float(row["efficiency"]), "trades": int(row["trades"]),
                    "cost_usd": float(row["cost_usd"]),
                    "traders": {r.trader: {"role": r.role, "rank": int(r.rank), "limit": float(r.limit),
                                           "model": MODEL_NAMES.get(r.model, r.model)} for r in traders.itertuples()},
                    "turns": [[clean(v) for v in values] for values in
                              t[TURN_COLUMNS].astype(object).where(pd.notna(t[TURN_COLUMNS]), None).itertuples(index=False)],
                })
    return out


def build_page(data: dict, template: Path = REPORT / "replay" / "template.html") -> str:
    """The artifact page: the template with the session data inlined (one self-contained file)."""
    return template.read_text().replace("/*DATA*/null", json.dumps(data, separators=(",", ":")).replace("</", "<\\/"))


def main(results: Path = RESULTS) -> Path:
    data = replay_data(results)
    folder = REPORT / "replay"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "data.json").write_text(json.dumps(data, separators=(",", ":")))
    page = folder / "market_town_replay.html"
    page.write_text(build_page(data))
    print(f"wrote {page}: {len(data['sessions'])} sessions, {page.stat().st_size / 1e6:.2f} MB")
    return page


if __name__ == "__main__":
    main()
