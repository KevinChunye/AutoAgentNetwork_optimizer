"""Market town: LLM traders in a continuous double auction, scored against the competitive equilibrium.

schedule.py  values, costs and the competitive equilibrium (P*, Q*, maximum surplus, CE profit)
engine.py    the double auction: book, matching, budget rule, periods and polling rounds
traders.py   ZI-C baseline and LLM traders (prompt, reply format, parser)
caller.py    the governed call path (cache, spend governor, ledger) behind AgentRuntime
metrics.py   efficiency, Smith's alpha, extramarginal trades, rejection and parse rates, profits
run.py       market configs for `aan estimate / check / run`
fake.py      offline fake trader for tests and dry runs
"""
