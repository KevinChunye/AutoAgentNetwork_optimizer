"""W3 part b, rung 1 smoke test: one market-town LLM trader inside an ABIDES market, offline.

Run inside the ABIDES virtual environment (autoagentnet/ladder/software.py builds it):

    <venv>/bin/python -I autoagentnet/ladder/smoke_abides.py <repo root>

Two trading agents meet at an ABIDES exchange for 30 simulated minutes:
  - an ABIDES ValueAgent (noisy view of a mean-reverting fundamental value), and
  - LLMBuyer, which wakes every 5 minutes, asks the exchange for the spread, and decides through
    our caller: the market-town LLMTrader and MarketCaller (call cache, then the runtime) with the
    fake provider, so nothing is spent. Its BID or ACCEPT becomes an ABIDES limit order for 1 share.
Prices in ABIDES are cents, as in the market town. The script prints one JSON line with the counts;
the smoke test passes when the kernel finishes, the caller answered, and the exchange accepted at
least one of our orders.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2]))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from abides_core import abides  # noqa: E402
from abides_core.utils import str_to_ns  # noqa: E402
from abides_markets.agents import ExchangeAgent, TradingAgent, ValueAgent  # noqa: E402
from abides_markets.messages.query import QuerySpreadResponseMsg  # noqa: E402
from abides_markets.oracles import SparseMeanRevertingOracle  # noqa: E402
from abides_markets.orders import Side  # noqa: E402
from abides_markets.utils import generate_latency_model  # noqa: E402

from autoagentnet.cache import CallCache  # noqa: E402
from autoagentnet.market.caller import MarketCaller  # noqa: E402
from autoagentnet.market.engine import Trader, View  # noqa: E402
from autoagentnet.market.fake import FakeTraderClient  # noqa: E402
from autoagentnet.market.traders import LLMTrader, rules_text  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402
from autoagentnet.runtime.local import LocalRuntime  # noqa: E402

ROOT = Path(sys.path[0])
TICKER, R_BAR = "ABM", 100_000  # fundamental value $1,000.00, in cents
WAKE = str_to_ns("00:05:00")


class LLMBuyer(TradingAgent):
    """A buyer whose value is the fundamental mean; each turn is one call through our caller."""

    def __init__(self, id: int, trader: LLMTrader, random_state):
        super().__init__(id, "LLM buyer", "LLMBuyer", random_state, starting_cash=10_000_000)
        self.trader = trader
        self.state = "AWAITING_WAKEUP"
        self.n_calls = self.n_orders = self.n_unparsed = 0  # ABIDES uses self.orders for open orders

    def get_wake_frequency(self):
        return WAKE  # first wakeup after the market opens

    def wakeup(self, current_time):
        super().wakeup(current_time)
        if not self.mkt_open or not self.mkt_close or self.mkt_closed:
            return
        self.set_wakeup(current_time + WAKE)
        self.cancel_all_orders()
        self.get_current_spread(TICKER)
        self.state = "AWAITING_SPREAD"

    def receive_message(self, current_time, sender_id, message):
        super().receive_message(current_time, sender_id, message)
        if self.state != "AWAITING_SPREAD" or not isinstance(message, QuerySpreadResponseMsg) or self.mkt_closed:
            return
        self.state = "AWAITING_WAKEUP"
        bid, _, ask, _ = self.get_known_bid_ask(TICKER)
        me = Trader(id="B1", role="buyer", rank=1, limit=R_BAR, model="fake")
        view = View(trader=me, period=1, periods=1, round=self.n_calls + 1, rounds=6, best_bid=bid, best_ask=ask,
                    mine_bid=False, mine_ask=False, last_prices=[], earlier_means=[], profit=0)
        action = asyncio.run(self.trader.act(view))
        self.n_calls += 1
        if not action.parsed:
            self.n_unparsed += 1
        price = action.price if action.kind == "BID" else ask if action.kind == "ACCEPT" else None
        if price is not None:
            self.place_limit_order(TICKER, 1, Side.BID, int(price))
            self.n_orders += 1


def config(seed: int, buyer: LLMBuyer) -> dict:
    rng = np.random.RandomState(seed)
    day = pd.Timestamp("2021-02-05").value  # nanoseconds since 1970, as ABIDES counts time
    open_, close = day + str_to_ns("09:30:00"), day + str_to_ns("10:00:00")
    symbols = {TICKER: {"r_bar": R_BAR, "kappa": 1.67e-16, "sigma_s": 0, "fund_vol": 5e-5,
                        "megashock_lambda_a": 2.77778e-18, "megashock_mean": 1000, "megashock_var": 50_000,
                        "random_state": np.random.RandomState(rng.randint(2**31))}}
    oracle = SparseMeanRevertingOracle(open_, close, symbols)
    agents = [
        ExchangeAgent(id=0, name="EXCHANGE_AGENT", type="ExchangeAgent", mkt_open=open_, mkt_close=close,
                      symbols=[TICKER], book_logging=False, log_orders=False, pipeline_delay=0, computation_delay=0,
                      stream_history=10, random_state=np.random.RandomState(rng.randint(2**31))),
        ValueAgent(id=1, name="Value Agent 1", type="ValueAgent", symbol=TICKER, starting_cash=10_000_000,
                   sigma_n=R_BAR / 100, r_bar=R_BAR, kappa=1.67e-15, lambda_a=1e-11,
                   random_state=np.random.RandomState(rng.randint(2**31))),
        buyer,
    ]
    return {"seed": seed, "start_time": day, "stop_time": close + str_to_ns("1s"), "agents": agents,
            "agent_latency_model": generate_latency_model(len(agents)), "default_computation_delay": 50,
            "custom_properties": {"oracle": oracle}, "random_state_kernel": np.random.RandomState(rng.randint(2**31)),
            "stdout_log_level": "WARNING"}


def main() -> None:
    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    registry.set_client("fake", FakeTraderClient())
    caller = MarketCaller(LocalRuntime(registry), registry, pricebook=None, cache=CallCache(), governor=None,
                          run_id="smoke", market="abides-smoke", condition="fake")
    trader = LLMTrader(caller, "fake", rules_text(1, 1, 1, 6), seed=7, max_tokens=200, temperature=1.0)
    buyer = LLMBuyer(2, trader, np.random.RandomState(7))
    abides.run(config(7, buyer))
    print(json.dumps({"llm_calls": buyer.n_calls, "caller_live_calls": caller.live_calls, "orders_placed": buyer.n_orders,
                      "unparsed": buyer.n_unparsed, "executed": len(buyer.executed_orders)}))


if __name__ == "__main__":
    main()
