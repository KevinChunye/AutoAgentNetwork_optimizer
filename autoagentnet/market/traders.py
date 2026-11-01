"""Traders: zero-intelligence-constrained (ZI-C) baseline and LLM traders.

ZI-C (Gode and Sunder 1993): on every turn, a buyer bids a price drawn uniformly at random between
`low` and its value, and a seller asks a price drawn uniformly between its cost and `high`. It never
breaks the budget rule, never learns and never accepts on purpose; its quote trades only when it
crosses the standing quote.

LLM trader: on every turn it reads the market rules (identical for every trader, so they form one
cached prompt prefix) followed by its own situation, and replies

    REASON: <one sentence>
    ACTION: BID <price> | ASK <price> | ACCEPT | PASS

Every call goes through an AgentRuntime as an AgentRequest (the Maritime wire format): the rules are
the request's `task` (the shared, cached block) and the trader's situation is its `instruction`.
A reply without a readable ACTION line is a PASS with parsed=False, and is logged; so is any reply cut off by
max_tokens, whose last ACTION line may be cut mid-price ("ACTION: ASK 2." would read as $2.00; audit 30).
"""

from __future__ import annotations

import random
import re

from ..agents.spec import AgentInput, AgentOutput, AgentRequest, AgentSpec
from ..providers.base import TRUNCATED_STOP_REASONS
from .engine import Action, View

SYSTEM = ("You are a trader in a market experiment. Earn as much profit as you can over the session. "
          "Reply in exactly the format the rules give.")

RULES = """MARKET RULES
- A continuous double auction for one good, with {buyers} buyers and {sellers} sellers. In each period every trader has one unit: a buyer can buy one, a seller can sell one.
- The session has {periods} periods of {rounds} rounds. In each round, every trader who has not yet traded in that period gets one turn, in random order.
- Each buyer has a private value and each seller a private cost, the same in every period. Nobody sees anyone else's value or cost.
- Profit: a buyer who buys at price P earns value - P; a seller who sells at P earns P - cost. No trade in a period earns nothing in that period. Profits add up over the periods.
- The order book holds only the best bid (highest buyer offer) and the best ask (lowest seller offer).
- On your turn, choose one action:
  BID <price>: buyers only; must be above the best bid. A bid at or above the best ask buys at the best ask's price.
  ASK <price>: sellers only; must be below the best ask. An ask at or below the best bid sells at the best bid's price.
  ACCEPT: buy at the best ask (buyer) or sell at the best bid (seller).
  PASS: do nothing this turn.
- A trade happens at the price of the quote that was already standing. After every trade both the best bid and the best ask are cleared. A trader who has traded waits for the next period.
- A buyer may not bid or pay more than its value, and a seller may not ask or sell below its cost. An order that breaks a rule is rejected and counts as a PASS.
- Prices are in dollars and cents, for example 1.85.

REPLY FORMAT (exactly two lines, nothing else):
REASON: <one sentence>
ACTION: BID <price> | ASK <price> | ACCEPT | PASS"""


def money(value_cents: int | None) -> str:
    return "none" if value_cents is None else f"${value_cents / 100:.2f}"


def rules_text(buyers: int, sellers: int, periods: int, rounds: int) -> str:
    return RULES.format(buyers=buyers, sellers=sellers, periods=periods, rounds=rounds)


def situation_text(view: View) -> str:
    """The trader-specific part of the prompt; it comes after the shared rules."""
    t = view.trader
    limit = "value" if t.role == "buyer" else "cost"
    bid = money(view.best_bid) + (" (yours)" if view.mine_bid else "")
    ask = money(view.best_ask) + (" (yours)" if view.mine_ask else "")
    prices = ", ".join(money(p) for p in view.last_prices) if view.last_prices else "none yet"
    earlier = "; ".join(f"period {i}: {'no trades' if m is None else f'${m:.2f}'}"
                        for i, m in enumerate(view.earlier_means, 1)) or "none (this is the first period)"
    return "\n".join([
        "YOUR SITUATION",
        f"You are {t.role} {t.id}. Your {limit}: {money(t.limit)}.",
        f"Period {view.period} of {view.periods}, round {view.round} of {view.rounds}. You have not traded yet in this period.",
        f"Best bid: {bid}. Best ask: {ask}.",
        f"Trade prices this period, oldest first: {prices}.",
        f"Mean trade price in earlier periods: {earlier}.",
        f"Your profit so far: {money(view.profit)}.",
        "Your turn: reply in the format above.",
    ])


ACTION_RE = re.compile(r"ACTION\W{0,3}\s*(BID|ASK|ACCEPT|PASS)\b[\s:]*\$?\s*(?:(\d+(?:\.\d+)?)(?!,\d))?",
                       re.IGNORECASE)
REASON_RE = re.compile(r"REASON\W{0,3}\s*(.+)", re.IGNORECASE)
MARKDOWN = re.compile(r"[*_`]")  # bold, italics and code marks around the reply's words (audit 26, finding 4)


def parse_reply(text: str) -> Action:
    """Read the last ACTION line. BID and ASK need a price; anything unreadable is an unparsed PASS.
    Markdown marks are ignored; a comma decimal ("1,85") is unreadable rather than read as 1."""
    clean = MARKDOWN.sub("", text)
    reason_match = REASON_RE.search(clean)
    reason = reason_match.group(1).strip() if reason_match else ""
    matches = ACTION_RE.findall(clean)
    if not matches:
        return Action("PASS", parsed=False, reason=reason)
    kind, price = matches[-1]
    kind = kind.upper()
    if kind in ("BID", "ASK"):
        if not price:
            return Action("PASS", parsed=False, reason=reason)
        return Action(kind, price=int(round(float(price) * 100)), reason=reason)
    return Action(kind, reason=reason)


class ZICTrader:
    """Quotes uniformly at random within the budget rule; low/high bound the price range (cents)."""

    def __init__(self, rng: random.Random, low: int, high: int):
        self.rng = rng
        self.low = low
        self.high = high

    async def act(self, view: View) -> Action:
        t = view.trader
        if t.role == "buyer":
            return Action("BID", price=self.rng.randint(min(self.low, t.limit), t.limit))
        return Action("ASK", price=self.rng.randint(t.limit, max(self.high, t.limit)))


def trader_request(view: View, model: str, rules: str, seed: int, max_tokens: int,
                   temperature: float | None) -> AgentRequest:
    """The AgentRequest for one turn: shared rules as the cached task block, own situation after it."""
    t = view.trader
    spec = AgentSpec(agent_id=t.id, stage=f"period{view.period}", index=t.rank, model=model, system=SYSTEM,
                     instruction=situation_text(view), max_tokens=max_tokens, temperature=temperature)
    return AgentRequest(spec=spec, input=AgentInput(task_id=f"s{seed}", task=rules, shared_prefix=True))


class LLMTrader:
    """Decides each turn with one model call through `caller` (MarketCaller: cache, governor, ledger)."""

    def __init__(self, caller, model: str, rules: str, seed: int, max_tokens: int, temperature: float | None):
        self.caller = caller
        self.model = model
        self.rules = rules
        self.seed = seed
        self.max_tokens = max_tokens
        self.temperature = temperature

    async def act(self, view: View) -> Action:
        request = trader_request(view, self.model, self.rules, self.seed, self.max_tokens, self.temperature)
        output: AgentOutput = await self.caller.call(request, replicate=self.seed)
        action = parse_reply(output.content)
        if output.stop_reason in TRUNCATED_STOP_REASONS:  # an unfinished reply has no final decision: its last
            action = Action("PASS", parsed=False, reason=action.reason)  # ACTION line may be cut mid-price (audit 30)
        action.meta = {
            "call_model": output.model, "cost_usd": output.cost_usd, "from_cache": output.from_cache,
            "stop_reason": output.stop_reason, "truncated": output.stop_reason in TRUNCATED_STOP_REASONS,
            "input_tokens": output.usage.input_tokens, "cache_write_tokens": output.usage.cache_write_tokens,
            "cache_read_tokens": output.usage.cache_read_tokens, "output_tokens": output.usage.output_tokens,
            "latency_s": output.latency_s, "reply": output.content,
        }
        return action
