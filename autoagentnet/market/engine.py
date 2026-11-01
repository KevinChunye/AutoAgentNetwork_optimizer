"""A continuous double auction (CDA) for one good, run as a session of periods and polling rounds.

Terms:
  session    one market history with its own seed: `periods` periods in a row, the same traders,
             the same values and costs every period.
  period     every trader starts with one unit to buy (buyer) or sell (seller); it ends after
             `rounds` polling rounds. Units, the book and "has traded" reset at the next period.
  round      every trader who has not yet traded this period acts once, in an order drawn at
             random from the session seed, period and round (so the order is reproducible).
  turn       one trader acting once: it sees a View and returns an Action.
  limit      a trader's value (buyer) or cost (seller); see schedule.py.
  book       only the best bid (highest standing buy price) and the best ask (lowest standing
             sell price), each with the trader who posted it.
  quote improvement   a new bid must be above the best bid and a new ask below the best ask.
  crossing   a bid at or above the best ask, an ask at or below the best bid, or ACCEPT: it trades
             one unit at the price of the quote that was already standing. Both quotes then clear.
  budget rule   a buyer may not bid or buy above its value, a seller may not ask or sell below
             its cost. An order that breaks it is rejected, counted and treated as PASS.
  rejected order   an order (BID, ASK or ACCEPT) the book refuses: "budget", "not_better" (fails
             quote improvement), "no_quote" (ACCEPT with nothing to accept), "wrong_side" (a buyer's
             ASK or a seller's BID) or "bad_price" (zero or negative).

Prices are integer cents inside the engine (no rounding drift) and dollars at the edges.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Awaitable, Callable, Literal, Protocol

from .schedule import Schedule

Role = Literal["buyer", "seller"]
ActionKind = Literal["BID", "ASK", "ACCEPT", "PASS"]
HISTORY_PRICES = 10  # trade prices of the current period a trader is shown (the most recent ones)


def cents(dollars: float) -> int:
    return int(round(dollars * 100))


def dollars(value: int | None) -> float | None:
    return None if value is None else value / 100


@dataclass
class Trader:
    """id "B3" / "S3"; rank as in the schedule; limit = value or cost in cents; model = a model
    ref for an LLM trader, or "zic" for a zero-intelligence-constrained one."""

    id: str
    role: Role
    rank: int
    limit: int
    model: str


@dataclass
class Quote:
    price: int  # cents
    trader: str


@dataclass
class Action:
    """What a trader does on its turn.

    kind:   BID, ASK, ACCEPT or PASS
    price:  cents, for BID and ASK
    parsed: False when an LLM reply had no readable ACTION line (then kind is PASS)
    reason: the trader's one-sentence reason ("" for ZI-C)
    meta:   call details for the log (model, cost, tokens, stop reason, raw reply)
    """

    kind: ActionKind
    price: int | None = None
    parsed: bool = True
    reason: str = ""
    meta: dict = field(default_factory=dict)


@dataclass
class View:
    """Everything a trader is shown on its turn. Never other traders' values or costs.

    best_bid / best_ask: standing quotes in cents (None when empty); mine_bid / mine_ask say whether
    the standing quote is this trader's own. last_prices: the most recent trade prices this period
    (up to HISTORY_PRICES, oldest first). earlier_means: mean trade price of each earlier period
    (None for a period without trades). profit: this trader's profit so far in the session, cents.
    """

    trader: Trader
    period: int  # 1-based
    periods: int
    round: int  # 1-based
    rounds: int
    best_bid: int | None
    best_ask: int | None
    mine_bid: bool
    mine_ask: bool
    last_prices: list[int]
    earlier_means: list[float | None]
    profit: int
    traded_this_period: bool = False


class TraderAgent(Protocol):
    async def act(self, view: View) -> Action: ...


@dataclass
class Book:
    bid: Quote | None = None
    ask: Quote | None = None

    def clear(self) -> None:
        self.bid = self.ask = None


def apply_action(book: Book, trader: Trader, action: Action) -> tuple[str, Quote | None]:
    """Apply one action to the book. Returns (outcome, standing quote that traded or None).

    outcome: "pass", "unparsed", "posted", "trade" or "rejected:<reason>". A trade happens at the
    standing quote's price; the caller settles it and clears the book."""
    if not action.parsed:
        return "unparsed", None
    if action.kind == "PASS":
        return "pass", None
    buyer = trader.role == "buyer"
    if action.kind == "ACCEPT":
        standing = book.ask if buyer else book.bid
        if standing is None:
            return "rejected:no_quote", None
        if (buyer and standing.price > trader.limit) or (not buyer and standing.price < trader.limit):
            return "rejected:budget", None
        return "trade", standing
    if (action.kind == "BID") != buyer:
        return "rejected:wrong_side", None
    price = action.price
    if price is None or price <= 0:
        return "rejected:bad_price", None
    if (buyer and price > trader.limit) or (not buyer and price < trader.limit):
        return "rejected:budget", None
    if buyer:
        if book.ask is not None and price >= book.ask.price:
            return "trade", book.ask
        if book.bid is not None and price <= book.bid.price:
            return "rejected:not_better", None
        book.bid = Quote(price, trader.id)
    else:
        if book.bid is not None and price <= book.bid.price:
            return "trade", book.bid
        if book.ask is not None and price >= book.ask.price:
            return "rejected:not_better", None
        book.ask = Quote(price, trader.id)
    return "posted", None


def make_traders(schedule: Schedule, model_of: Callable[[Role, int], str]) -> list[Trader]:
    buyers = [Trader(f"B{r}", "buyer", r, cents(v), model_of("buyer", r)) for r, v in enumerate(schedule.values, 1)]
    sellers = [Trader(f"S{r}", "seller", r, cents(c), model_of("seller", r)) for r, c in enumerate(schedule.costs, 1)]
    return buyers + sellers


def polling_order(seed: int, period: int, round_: int, ids: list[str]) -> list[str]:
    """A reproducible random order for one round (string seeds hash the same in every process)."""
    order = list(ids)
    random.Random(f"order:{seed}:{period}:{round_}").shuffle(order)
    return order


@dataclass
class SessionLog:
    """Rows for the result tables: one per turn and one per trade (see metrics.py for the columns)."""

    seed: int
    turns: list[dict] = field(default_factory=list)
    trades: list[dict] = field(default_factory=list)
    periods_done: int = 0


PeriodHook = Callable[[SessionLog, int], Awaitable[bool]]  # (log, period) -> keep going?
RoundHook = Callable[[SessionLog, int, int], Awaitable[bool]]  # (log, period, round) -> keep going?


async def run_session(
    schedule: Schedule,
    traders: list[Trader],
    agents: dict[str, TraderAgent],
    seed: int,
    periods: int,
    rounds: int,
    after_period: PeriodHook | None = None,
    log: SessionLog | None = None,
    after_round: RoundHook | None = None,
) -> SessionLog:
    """Run one session. `agents` maps trader id to the agent that decides its turns.
    `after_period` runs after each period (checkpoints, stop rules) and `after_round` after each round
    (cheap stop rules, so a broken reply format costs a round, not a period); returning False from
    either ends the session at once (a period cut short does not count in periods_done)."""
    log = log or SessionLog(seed=seed)
    by_id = {t.id: t for t in traders}
    profit = {t.id: 0 for t in traders}
    means: list[float | None] = []
    for period in range(1, periods + 1):
        book = Book()
        traded: set[str] = set()
        prices: list[int] = []
        turn_no = 0
        for round_ in range(1, rounds + 1):
            for trader_id in polling_order(seed, period, round_, [t.id for t in traders if t.id not in traded]):
                if trader_id in traded:  # traded earlier in this round, when someone accepted its quote
                    continue
                trader = by_id[trader_id]
                view = View(trader, period, periods, round_, rounds, quote_price(book.bid), quote_price(book.ask),
                            book.bid is not None and book.bid.trader == trader_id,
                            book.ask is not None and book.ask.trader == trader_id,
                            prices[-HISTORY_PRICES:], list(means), profit[trader_id])
                action = await agents[trader_id].act(view)
                turn_no += 1
                outcome, standing = apply_action(book, trader, action)
                row = {"seed": seed, "period": period, "round": round_, "turn": turn_no, "trader": trader_id,
                       "role": trader.role, "rank": trader.rank, "model": trader.model, "limit": trader.limit / 100,
                       "best_bid_before": dollars(view.best_bid), "best_ask_before": dollars(view.best_ask),
                       "action": action.kind if action.parsed else "UNPARSED", "price": dollars(action.price),
                       "outcome": outcome, "reason": action.reason, "trade_price": None, "counterparty": None,
                       **action.meta}
                if outcome == "trade":
                    other = by_id[standing.trader]
                    buyer, seller = (trader, other) if trader.role == "buyer" else (other, trader)
                    profit[buyer.id] += buyer.limit - standing.price
                    profit[seller.id] += standing.price - seller.limit
                    traded |= {buyer.id, seller.id}
                    prices.append(standing.price)
                    book.clear()
                    row.update(trade_price=standing.price / 100, counterparty=other.id)
                    log.trades.append({
                        "seed": seed, "period": period, "trade_no": len(prices), "round": round_, "turn": turn_no,
                        "price": standing.price / 100, "buyer": buyer.id, "seller": seller.id,
                        "buyer_rank": buyer.rank, "seller_rank": seller.rank, "buyer_model": buyer.model,
                        "seller_model": seller.model, "buyer_value": buyer.limit / 100, "seller_cost": seller.limit / 100,
                        "initiator": trader.id})
                row.update(best_bid_after=dollars(book.bid.price if book.bid else None),
                           best_ask_after=dollars(book.ask.price if book.ask else None))
                log.turns.append(row)
            if after_round is not None and not await after_round(log, period, round_):
                return log
        means.append(sum(prices) / len(prices) / 100 if prices else None)
        log.periods_done = period
        if after_period is not None and not await after_period(log, period):
            break
    return log


def quote_price(quote: Quote | None) -> int | None:
    """The standing quote's price in cents, or None when that side of the book is empty."""
    return None if quote is None else quote.price
