import asyncio
import math

import pandas as pd
import pytest

from autoagentnet.agents.agent import build_request
from autoagentnet.cache import CallCache
from autoagentnet.market.caller import MarketCaller
from autoagentnet.market.engine import (Action, Book, Quote, SessionLog, Trader, View, apply_action, make_traders,
                                        polling_order, run_session)
from autoagentnet.market.fake import FakeTraderClient
from autoagentnet.market.metrics import (alpha, period_metrics, placebo_gaps, profit_gap, rank_pair_interval,
                                         senior_breakdown, session_metrics, trader_metrics, waiting_metrics)
from autoagentnet.market.run import MarketConfig, estimate_market, run_market
from autoagentnet.market.schedule import FALLBACK_COSTS, FALLBACK_VALUES, Schedule

FALLBACK = Schedule(values=FALLBACK_VALUES, costs=FALLBACK_COSTS)
from autoagentnet.market.traders import LLMTrader, parse_reply, rules_text, trader_request
from autoagentnet.meter import Ledger
from autoagentnet.providers.registry import ProviderRegistry
from autoagentnet.runtime.local import LocalRuntime
from conftest import ROOT

BUYER = Trader("B2", "buyer", 2, 280, "x")
SELLER = Trader("S2", "seller", 2, 120, "x")


def view_of(trader: Trader, **kw) -> View:
    base = dict(period=1, periods=5, round=1, rounds=8, best_bid=None, best_ask=None, mine_bid=False, mine_ask=False,
                last_prices=[], earlier_means=[], profit=0)
    return View(trader, **{**base, **kw})


# --- equilibrium -------------------------------------------------------------------------------

def test_smith_schedule_equilibrium():
    s = Schedule()  # Smith (1962) Test 1, as in arXiv 2609.02580
    assert s.values[0] == 3.25 and s.costs[0] == 0.75 and len(s.values) == len(s.costs) == 11
    assert (s.q_star, s.p_low, s.p_high, s.p_star) == (6, 2.00, 2.00, 2.00)
    assert s.max_surplus == pytest.approx(7.50)
    assert s.ce_profit("buyer", 6) == 0.0 and s.ce_profit("seller", 1) == pytest.approx(1.25)


def test_fallback_schedule_equilibrium():
    s = FALLBACK
    assert s.q_star == 6
    assert (s.p_low, s.p_high, s.p_star) == (1.95, 2.05, 2.00)
    assert s.max_surplus == pytest.approx(6.10)
    ce = [s.ce_profit("buyer", r) for r in range(1, 12)] + [s.ce_profit("seller", r) for r in range(1, 12)]
    assert sum(ce) == pytest.approx(6.10)
    assert s.ce_profit("buyer", 1) == pytest.approx(1.00) and s.ce_profit("seller", 6) == pytest.approx(0.05)
    assert s.ce_profit("buyer", 7) == 0.0 and s.ce_profit("seller", 7) == 0.0


def test_schedule_must_be_in_rank_order():
    with pytest.raises(ValueError):
        Schedule(values=[1.0, 2.0], costs=[0.5, 0.6])


# --- matching, prices and the budget rule --------------------------------------------------------

def test_quotes_must_improve_and_crossing_trades_at_the_standing_price():
    book = Book()
    assert apply_action(book, BUYER, Action("BID", 150)) == ("posted", None)
    assert apply_action(book, Trader("B3", "buyer", 3, 260, "x"), Action("BID", 150))[0] == "rejected:not_better"
    assert apply_action(book, SELLER, Action("ASK", 250))[0] == "posted"
    assert apply_action(book, Trader("S3", "seller", 3, 140, "x"), Action("ASK", 250))[0] == "rejected:not_better"
    assert (book.bid.price, book.ask.price) == (150, 250)
    # a bid at or above the best ask trades at the ask's price, not at the bid
    outcome, standing = apply_action(book, Trader("B1", "buyer", 1, 300, "x"), Action("BID", 270))
    assert outcome == "trade" and standing == Quote(250, "S2")
    # an ask at or below the best bid trades at the bid's price
    book = Book(bid=Quote(190, "B2"))
    outcome, standing = apply_action(book, SELLER, Action("ASK", 130))
    assert outcome == "trade" and standing.price == 190


def test_accept_and_wrong_side_and_empty_book():
    assert apply_action(Book(), BUYER, Action("ACCEPT"))[0] == "rejected:no_quote"
    assert apply_action(Book(), BUYER, Action("ASK", 200))[0] == "rejected:wrong_side"
    assert apply_action(Book(), SELLER, Action("BID", 200))[0] == "rejected:wrong_side"
    assert apply_action(Book(), BUYER, Action("BID", 0))[0] == "rejected:bad_price"
    outcome, standing = apply_action(Book(ask=Quote(200, "S1")), BUYER, Action("ACCEPT"))
    assert outcome == "trade" and standing.price == 200
    assert apply_action(Book(), BUYER, Action("PASS"))[0] == "pass"
    assert apply_action(Book(), BUYER, Action("PASS", parsed=False))[0] == "unparsed"


def test_budget_rule_rejects_and_leaves_the_book_alone():
    book = Book(bid=Quote(100, "B9"), ask=Quote(300, "S9"))
    assert apply_action(book, BUYER, Action("BID", 281))[0] == "rejected:budget"  # value 2.80
    assert apply_action(book, SELLER, Action("ASK", 119))[0] == "rejected:budget"  # cost 1.20
    assert apply_action(book, BUYER, Action("ACCEPT"))[0] == "rejected:budget"  # ask 3.00 > value
    assert apply_action(Book(bid=Quote(110, "B9")), SELLER, Action("ACCEPT"))[0] == "rejected:budget"
    assert (book.bid.price, book.ask.price) == (100, 300)
    # bidding exactly the value is allowed
    assert apply_action(book, BUYER, Action("BID", 280))[0] == "posted"


class Scripted:
    """Plays a fixed list of actions, then passes."""

    def __init__(self, actions):
        self.actions = list(actions)

    async def act(self, view):
        return self.actions.pop(0) if self.actions else Action("PASS")


def test_session_clears_the_book_after_a_trade_and_traders_stop_after_trading():
    schedule = Schedule(values=[3.0], costs=[1.0])
    traders = make_traders(schedule, lambda role, rank: "x")
    agents = {"B1": Scripted([Action("BID", 150), Action("BID", 260)]), "S1": Scripted([Action("ASK", 250)])}
    log = asyncio.run(run_session(schedule, traders, agents, seed=3, periods=2, rounds=4))
    first = [t for t in log.turns if t["period"] == 1]
    trade = [t for t in first if t["outcome"] == "trade"]
    assert len(trade) == 1 and trade[0]["trade_price"] in (1.50, 2.50)  # whoever was standing sets the price
    assert trade[0]["best_bid_after"] is None and trade[0]["best_ask_after"] is None
    assert all(t["turn"] <= trade[0]["turn"] for t in first)  # nobody acts after both traded
    assert len(log.trades) == 1 and log.periods_done == 2  # scripted traders only pass in period 2


def test_polling_order_is_seeded_and_skips_traders_who_traded():
    ids = [f"B{i}" for i in range(1, 12)]
    assert polling_order(1, 1, 1, ids) == polling_order(1, 1, 1, ids)
    assert polling_order(1, 1, 1, ids) != polling_order(2, 1, 1, ids)
    assert sorted(polling_order(1, 2, 3, ids)) == sorted(ids)


# --- replies --------------------------------------------------------------------------------------

def test_parse_reply():
    a = parse_reply("REASON: The spread is wide, so I start low.\nACTION: BID 1.85")
    assert (a.kind, a.price, a.parsed, a.reason) == ("BID", 185, True, "The spread is wide, so I start low.")
    assert parse_reply("REASON: x\nACTION: ASK $2.10").price == 210
    assert parse_reply("**REASON:** fine\n**ACTION:** ACCEPT").kind == "ACCEPT"
    assert parse_reply("REASON: wait\nACTION: pass").kind == "PASS"
    assert not parse_reply("REASON: hmm\nACTION: BID").parsed  # a bid needs a price
    assert not parse_reply("I would bid 1.90").parsed
    assert parse_reply("REASON: x\nACTION: BID 1.999").price == 200  # rounded to cents
    # audit 26, finding 4: markdown around the action, and comma decimals
    assert parse_reply("REASON: x\nACTION: **BID 1.85**").price == 185
    assert parse_reply("REASON: x\nACTION: **BID** 1.85").price == 185
    assert parse_reply("`ACTION: ASK 2.10`").price == 210
    assert not parse_reply("REASON: x\nACTION: BID 1,85").parsed  # never read as $1.00
    assert parse_reply("REASON: x\nACTION: BID 1.85, to test the sellers").price == 185


# --- prompts and caching --------------------------------------------------------------------------

def test_every_trader_shares_one_cached_prefix_and_own_state_comes_after():
    schedule = Schedule()
    rules = rules_text(11, 11, 5, 8)
    requests = [trader_request(view_of(t, best_bid=150, best_ask=260, last_prices=[200]), "haiku_nothink", rules, 7,
                               200, 1.0) for t in make_traders(schedule, lambda r, k: "haiku_nothink")]
    llm = [build_request(r.spec, r.input, "claude-haiku-5-5") for r in requests]
    assert len({q.system for q in llm}) == 1
    assert len({q.blocks[0].text for q in llm}) == 1 and all(q.blocks[0].cache for q in llm)
    assert len({q.blocks[1].text for q in llm}) == 22  # each trader's situation is its own
    situation = llm[0].blocks[1].text
    assert "Your value: $3.25" in situation and "$3.00" not in situation  # never others' values
    assert "Best bid: $1.50. Best ask: $2.60." in situation


def fake_registry() -> ProviderRegistry:
    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    registry.set_client("fake", FakeTraderClient())
    return registry


def play(seed: int, cache: CallCache, registry: ProviderRegistry, periods: int = 1) -> tuple[SessionLog, MarketCaller]:
    schedule = Schedule()
    traders = make_traders(schedule, lambda role, rank: "fake")
    caller = MarketCaller(LocalRuntime(registry), registry, pricebook=None, cache=cache, governor=None, run_id="t",
                          market="m", condition="fake")
    rules = rules_text(11, 11, periods, 8)
    agents = {t.id: LLMTrader(caller, "fake", rules, seed, 200, 1.0) for t in traders}
    return asyncio.run(run_session(schedule, traders, agents, seed, periods, 8)), caller


def test_sessions_with_different_seeds_never_share_cached_calls():
    cache, registry = CallCache(), fake_registry()
    first, caller1 = play(1, cache, registry)
    second, caller2 = play(2, cache, registry)
    assert caller1.live_calls == len(first.turns) and caller2.live_calls == len(second.turns)
    assert not any(t["from_cache"] for t in second.turns)
    again, caller3 = play(1, cache, registry)
    assert caller3.live_calls == 0 and all(t["from_cache"] for t in again.turns)
    assert again.trades == first.trades  # a cached replay is the same session


# --- metrics --------------------------------------------------------------------------------------

def test_efficiency_alpha_and_extramarginal_arithmetic():
    schedule = FALLBACK
    trades = pd.DataFrame([
        # B1 (3.00) buys from S1 (1.00) at 2.00: surplus 2.00
        {"seed": 1, "period": 1, "price": 2.00, "buyer": "B1", "seller": "S1", "buyer_rank": 1, "seller_rank": 1,
         "buyer_value": 3.00, "seller_cost": 1.00},
        # B7 (1.95, extramarginal) buys from S2 (1.20) at 1.90: surplus 0.75
        {"seed": 1, "period": 1, "price": 1.90, "buyer": "B7", "seller": "S2", "buyer_rank": 7, "seller_rank": 2,
         "buyer_value": 1.95, "seller_cost": 1.20},
    ])
    turns = pd.DataFrame([
        {"seed": 1, "period": 1, "trader": "B1", "role": "buyer", "rank": 1, "model": "x", "limit": 3.0,
         "action": "BID", "outcome": "trade"},
        {"seed": 1, "period": 1, "trader": "S1", "role": "seller", "rank": 1, "model": "x", "limit": 1.0,
         "action": "ASK", "outcome": "rejected:budget"},
        {"seed": 1, "period": 1, "trader": "B7", "role": "buyer", "rank": 7, "model": "x", "limit": 1.95,
         "action": "UNPARSED", "outcome": "unparsed"},
        {"seed": 1, "period": 1, "trader": "S2", "role": "seller", "rank": 2, "model": "x", "limit": 1.2,
         "action": "ACCEPT", "outcome": "trade"},
    ])
    p = period_metrics(turns, trades, schedule).iloc[0]
    assert p["efficiency"] == pytest.approx(2.75 / 6.10)
    assert p["trade_ratio"] == pytest.approx(2 / 6)
    assert p["extramarginal"] == 1 and p["mean_price"] == pytest.approx(1.95)
    assert p["alpha"] == pytest.approx(100 * math.sqrt((0 + 0.1 ** 2) / 2) / 2.0)
    assert p["rejected_rate"] == pytest.approx(1 / 3) and p["unparsed_rate"] == pytest.approx(1 / 4)
    assert alpha(pd.Series([2.0, 2.0]), 2.0) == 0.0
    s = session_metrics(period_metrics(turns, trades, schedule), trades, schedule).iloc[0]
    assert s["efficiency"] == pytest.approx(2.75 / 6.10) and s["zero_trade_periods"] == 0
    traders = trader_metrics(turns, trades, schedule, pd.Series({1: 1})).set_index("trader")
    assert traders.loc["B1", "profit"] == pytest.approx(1.00) and traders.loc["B1", "profit_ratio"] == pytest.approx(1.0)
    assert traders.loc["S2", "profit"] == pytest.approx(0.70) and traders.loc["S2", "ce_profit"] == pytest.approx(0.80)
    assert traders.loc["B7", "profit"] == pytest.approx(0.05) and math.isnan(traders.loc["B7", "profit_ratio"])


def test_zic_traders_are_efficient(tmp_path):
    cfg = MarketConfig(kind="market", name="zic", condition="zic", trader="zic", seeds=list(range(60)),
                       out_dir=str(tmp_path), save_turns=False)
    periods, sessions, status = asyncio.run(run_market(cfg))
    assert status["state"] == "completed" and status["sessions_done"] == 60
    assert sessions["efficiency"].mean() > 0.85
    assert (sessions["unparsed"] == 0).all() and (sessions["cost_usd"] == 0).all()
    assert len(pd.read_csv(tmp_path / "zic" / "periods.csv")) == 60 * 5


# --- runs -----------------------------------------------------------------------------------------

def test_end_to_end_fake_session_writes_every_table(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    cfg = MarketConfig(kind="market", name="m_fake", seeds=[11, 12], periods=2, model_override="fake",
                       out_dir=str(tmp_path))
    periods, sessions, status = asyncio.run(run_market(cfg))
    assert status["state"] == "completed" and status["sessions_done"] == 2 and status["checkpoints"] == []
    out = tmp_path / "m_fake"
    turns = pd.read_csv(out / "turns.csv")
    assert set(turns["seed"]) == {11, 12} and (turns["model"] == "fake").all()
    assert sessions["trades"].gt(0).all() and sessions["efficiency"].between(0, 1).all()
    assert turns["reason"].fillna("").str.len().gt(0).mean() > 0.9
    assert {"periods.csv", "sessions.csv", "traders.csv", "trades.csv", "turns.csv", "status.json"} <= {
        p.name for p in out.iterdir()}
    # a later run of one more session adds its rows and keeps the others
    asyncio.run(run_market(cfg.model_copy(update={"seeds": [11, 12, 13], "session_offset": 2})))
    assert set(pd.read_csv(out / "sessions.csv")["seed"]) == {11, 12, 13}


def paid_like_market(tmp_path, **updates) -> MarketConfig:
    """The real (non-dry) path: a fake model that is priced and billed to 'anthropic'."""
    (tmp_path / "providers.yaml").write_text(
        "models:\n  haiku_nothink: {provider: fake, model: fake-model, account: anthropic}\n")
    (tmp_path / "pricing.yaml").write_text("fake-model: {input: 1.0, output: 5.0}\n")
    (tmp_path / "ledger.jsonl").touch()
    base = dict(kind="market", name="m_paid", seeds=[5], periods=2, providers=str(tmp_path / "providers.yaml"),
                pricing=str(tmp_path / "pricing.yaml"), ledger=str(tmp_path / "ledger.jsonl"),
                cache=str(tmp_path / "cache"), out_dir=str(tmp_path / "results"))
    return MarketConfig(**{**base, **updates})


def test_paid_like_run_is_billed_once_checkpointed_per_period_and_stopped_by_the_run_cap(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    checkpoints = []
    monkeypatch.setattr("autoagentnet.market.run.git_checkpoint",
                        lambda paths, message: checkpoints.append(message) or "committed and pushed")
    cfg = paid_like_market(tmp_path)
    table = estimate_market(cfg)
    _, sessions, first = asyncio.run(run_market(cfg))
    spent = Ledger(cfg.ledger).spent_usd("anthropic")
    assert first["state"] == "completed" and spent > 0 and first["live_calls"] == sessions["turns"].sum()
    assert len(checkpoints) == 2 and all("period" in m for m in checkpoints)  # one per period
    assert spent < table["worst_case_usd"].sum()
    assert sessions["cost_usd"].sum() == pytest.approx(spent)
    _, _, second = asyncio.run(run_market(cfg))
    assert second["live_calls"] == 0 and Ledger(cfg.ledger).spent_usd("anthropic") == pytest.approx(spent)

    (tmp_path / "capped").mkdir()
    capped = paid_like_market(tmp_path / "capped", max_usd=0.02)
    _, _, status = asyncio.run(run_market(capped))
    assert status["state"] == "stopped" and "run cap" in status["reason"]
    assert Ledger(capped.ledger).spent_usd() * 1.15 <= 0.02
    assert (tmp_path / "capped" / "results" / "m_paid" / "turns.csv").exists()  # what was paid for is kept


def test_unparsed_replies_stop_the_run(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    monkeypatch.setattr("autoagentnet.market.fake.fake_trader_reply", lambda text, digest: "no idea")
    cfg = MarketConfig(kind="market", name="m_bad", seeds=[3], periods=3, model_override="fake", out_dir=str(tmp_path))
    _, sessions, status = asyncio.run(run_market(cfg))
    assert status["state"] == "stopped" and "readable ACTION" in status["reason"]
    assert sessions["turns"].sum() == 44  # checked after every round: stops once 40 turns are in (round 2)


def test_a_sonnet_session_fits_the_run_cap():
    cfg = MarketConfig(kind="market", name="m3", seeds=[21], model="sonnet_nothink")
    table = estimate_market(cfg)
    assert table["calls"].sum() == 22 * 8 * 5
    assert table["worst_case_x_safety"].sum() <= 4.0


def test_mixed_sessions_put_the_senior_on_the_chosen_ranks():
    cfg = MarketConfig(kind="market", name="m4", seeds=[31], model="haiku_nothink", senior_model="sonnet_nothink",
                       senior_ranks=[1, 3, 5, 7, 9, 11])
    traders = {t.id: t.model for t in make_traders(cfg.schedule, cfg.model_of)}
    assert traders["B1"] == traders["S11"] == "sonnet_nothink" and traders["B2"] == traders["S10"] == "haiku_nothink"
    assert sum(m == "sonnet_nothink" for m in traders.values()) == 12


def test_cli_gate_refuses_an_uncommitted_market_config_without_prereg(tmp_path, monkeypatch):
    from autoagentnet.market.run import is_market_config, preflight_market

    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    path = tmp_path / "m.yaml"
    path.write_text("kind: market\nname: m\nseeds: [1]\nperiods: 1\n")
    assert is_market_config(path) and not is_market_config(ROOT / "configs/experiments/smoke.yaml")
    problems, table = preflight_market(MarketConfig.from_yaml(path), path)
    assert any("prereg" in p for p in problems) and any("commit" in p for p in problems)
    assert table["calls"].sum() == 22 * 8
    assert preflight_market(MarketConfig.from_yaml(path).model_copy(update={"model_override": "fake"}), path) == ([], None)


def test_market_configs_carry_the_plan_preregs_verbatim():
    import importlib.util

    spec = importlib.util.spec_from_file_location("make_market_configs", ROOT / "scripts/make_market_configs.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    blocks = module.preregs()
    for name, block in [("m1_smoke", "m1_smoke"), ("m2_haiku", "m2_haiku"), ("m3_sonnet", "m3_sonnet"),
                        ("m4_mixed_odd", "m4_mixed"), ("m4_mixed_even", "m4_mixed")]:
        cfg = MarketConfig.from_yaml(ROOT / f"configs/experiments/market/{name}.yaml")
        assert cfg.prereg.model_dump() == blocks[block]
        assert estimate_market(cfg.model_copy(update={"session_limit": 1}))["worst_case_x_safety"].sum() <= 4.0
    seeds = [s for name in ["m1_smoke", "m2_haiku", "m3_sonnet", "m4_mixed_odd", "m4_mixed_even", "zic"]
             for s in MarketConfig.from_yaml(ROOT / f"configs/experiments/market/{name}.yaml").seeds]
    assert len(seeds) == len(set(seeds))  # no two sessions of the study share a seed (and so cached calls)


def test_waiting_metrics():
    schedule = Schedule()  # ranks 1-5 have a positive CE profit, rank 6 none
    turns = pd.DataFrame([
        {"seed": 1, "period": 1, "round": 6, "turn": 1, "role": "buyer", "rank": 2, "outcome": "pass",
         "best_bid_after": 1.5, "best_ask_after": 2.5},
        {"seed": 1, "period": 1, "round": 7, "turn": 2, "role": "seller", "rank": 3, "outcome": "posted",
         "best_bid_after": 1.5, "best_ask_after": 2.4},
        {"seed": 1, "period": 1, "round": 8, "turn": 3, "role": "buyer", "rank": 6, "outcome": "pass",  # zero CE profit
         "best_bid_after": 1.5, "best_ask_after": 2.4},
        {"seed": 1, "period": 1, "round": 2, "turn": 0, "role": "buyer", "rank": 1, "outcome": "pass",  # early round
         "best_bid_after": None, "best_ask_after": None},
    ])
    w = waiting_metrics(turns, schedule, rounds=8).iloc[0]
    assert w["late_pass_share"] == pytest.approx(0.5) and w["final_spread"] == pytest.approx(0.9)


def traders_frame(rows):
    return pd.DataFrame(rows, columns=["seed", "trader", "role", "rank", "model", "profit", "ce_profit", "trades"])


def test_profit_gap_placebo_and_breakdown():
    # two sessions, one buyer and one seller rank each side; senior = odd ranks in seed 1, even in seed 2
    traders = traders_frame([
        (1, "B1", "buyer", 1, "S", 6.0, 6.25, 5), (1, "B2", "buyer", 2, "H", 4.0, 5.0, 5),
        (2, "B1", "buyer", 1, "H", 5.0, 6.25, 5), (2, "B2", "buyer", 2, "S", 5.0, 5.0, 5),
    ])
    senior = traders["model"] == "S"
    gap = profit_gap(traders, senior)
    assert gap["all"] == pytest.approx(100 * (11 / 11.25 - 9 / 11.25))
    assert gap["buyer"] == pytest.approx(gap["all"]) and math.isnan(gap["seller"])
    lo, hi = rank_pair_interval(traders, senior, draws=500)
    assert lo <= gap["all"] <= hi
    placebo = placebo_gaps(traders.assign(model="H"))
    assert len(placebo) == 2 and placebo.loc[0, "gap_all"] == pytest.approx(gap["all"])  # same labels as M4's
    four = pd.concat([traders.assign(seed=traders["seed"] + 10 * k) for k in range(2)], ignore_index=True)
    splits = placebo_gaps(four, per_side=2)  # 4 sessions: choose 2 as A, the other 2 as B
    assert len(splits) == 6 and splits["seeds_odd"].str.split().str.len().eq(2).all()
    trades = pd.DataFrame([{"seed": 1, "period": 1, "price": 1.90, "buyer_model": "S", "seller_model": "H"},
                           {"seed": 1, "period": 2, "price": 2.20, "buyer_model": "H", "seller_model": "S"},
                           {"seed": 2, "period": 1, "price": 2.00, "buyer_model": "H", "seller_model": "H"}])
    b = senior_breakdown(traders, trades, "S", 2.0, pd.Series({1: 5, 2: 5}))
    assert b["cross_trades"] == 2 and b["price_edge"] == pytest.approx(0.15)  # +0.10 as buyer, +0.20 as seller
    assert b["trade_rate_senior"] == pytest.approx(1.0) and b["trade_rate_junior"] == pytest.approx(1.0)


def test_format_stops_are_checked_per_model(tmp_path, monkeypatch):
    # audit 27, finding 2: Sonnet only on rank 11 of each side (extramarginal, so it acts every round), unreadable
    # 30% of the time; pooled over both models the unparsed rate stays under the 10% limit, Sonnet's own does not
    import hashlib

    from autoagentnet.market.run import expectation_misses

    complete = FakeTraderClient.complete

    async def flaky_senior(self, request):
        response = await complete(self, request)
        roll = int(hashlib.sha256(request.model_dump_json().encode()).hexdigest()[:8], 16) % 10
        if request.model == "fake-sonnet" and roll < 3:
            return response.model_copy(update={"text": "no idea"})
        return response

    monkeypatch.setattr(FakeTraderClient, "complete", flaky_senior)
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    (tmp_path / "providers.yaml").write_text(
        "models:\n  haiku_nothink: {provider: fake, model: fake-haiku}\n  sonnet_nothink: {provider: fake, model: fake-sonnet}\n")
    (tmp_path / "ledger.jsonl").touch()
    cfg = MarketConfig(kind="market", name="m_mixed", seeds=[7], periods=3, model="haiku_nothink",
                       senior_model="sonnet_nothink", senior_ranks=[11], providers=str(tmp_path / "providers.yaml"),
                       ledger=str(tmp_path / "ledger.jsonl"), cache=str(tmp_path / "cache"), out_dir=str(tmp_path / "out"),
                       git_checkpoint=False)
    _, sessions, status = asyncio.run(run_market(cfg))
    assert status["state"] == "stopped" and "sonnet_nothink replies have no readable ACTION" in status["reason"]
    turns = pd.read_csv(tmp_path / "out" / "m_mixed" / "turns.csv")
    assert turns["outcome"].eq("unparsed").mean() < 0.10  # the pooled rate would not have stopped it
    # and a model below min_turns is not judged yet
    few = pd.DataFrame({"model": ["a"] * 5, "outcome": ["unparsed"] * 5, "truncated": [False] * 5})
    assert expectation_misses(few, pd.DataFrame(), cfg.expect) == []


def test_a_truncated_reply_is_an_unparsed_pass_even_if_it_has_an_action_line(tmp_path, monkeypatch):
    # audit 30: a reply cut at "ACTION: ASK 2." was read as an ask of $2.00
    from autoagentnet.agents.spec import AgentOutput
    from autoagentnet.providers.base import Usage

    class Cut:
        def __init__(self, text, stop):
            self.text, self.stop = text, stop

        async def call(self, request, replicate):
            return AgentOutput(agent_id="S7", content=self.text, usage=Usage(), provider="fake", model="fake",
                               latency_s=0.0, stop_reason=self.stop)

    seller = Trader("S7", "seller", 7, 225, "x")
    text = "REASON: ask just above my cost.\nACTION: ASK 2.30\nREASON: on second thought\nACTION: ASK 2."
    cut = asyncio.run(LLMTrader(Cut(text, "max_tokens"), "x", "rules", 1, 200, 1.0).act(view_of(seller)))
    assert (cut.kind, cut.parsed, cut.meta["truncated"]) == ("PASS", False, True)
    whole = asyncio.run(LLMTrader(Cut("REASON: fine\nACTION: ASK 2.30", "end_turn"), "x", "rules", 1, 200, 1.0)
                        .act(view_of(seller)))
    assert (whole.kind, whole.price, whole.parsed) == ("ASK", 230, True)

    # end to end: a fake model whose every reply stops at max_tokens never trades and logs every turn as unparsed
    complete = FakeTraderClient.complete

    async def always_cut(self, request):
        return (await complete(self, request)).model_copy(update={"stop_reason": "max_tokens"})

    monkeypatch.setattr(FakeTraderClient, "complete", always_cut)
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    cfg = MarketConfig(kind="market", name="m_cut", seeds=[4], periods=1, model_override="fake", out_dir=str(tmp_path),
                       expect={"max_unparsed_rate": None, "max_truncation_rate": None})
    _, sessions, _ = asyncio.run(run_market(cfg))
    turns = pd.read_csv(tmp_path / "m_cut" / "turns.csv")
    assert turns["outcome"].eq("unparsed").all() and sessions["trades"].sum() == 0
