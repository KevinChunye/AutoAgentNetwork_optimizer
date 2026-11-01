"""Write the market-town configs (configs/experiments/market/*.yaml).

    python scripts/make_market_configs.py

Every paid config gets the `prereg:` block of its run, copied verbatim from the YAML block between the
`prereg:begin` / `prereg:end` markers in research/market/plan.md, so the files and the plan cannot drift
apart. Seeds are unique across the study, so no session can reuse another's cached calls:

  zic             seeds 1000-1999   ZI-C baseline (free)
  m1_smoke        seed 1            all Haiku, 2 periods
  m2_haiku        seeds 11-14       all Haiku, 5 periods (one paid run per session)
  m3_sonnet       seeds 21-22       all Sonnet
  m4_mixed_odd    seeds 31, 33      Sonnet on the odd ranks of both sides (6 + 6), Haiku elsewhere
  m4_mixed_even   seeds 32, 34      Sonnet on the even ranks of both sides (5 + 5)
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs/experiments/market"
PLAN = ROOT / "research/market/plan.md"
HAIKU, SONNET = "haiku_nothink", "sonnet_nothink"
ROUNDS, PERIODS = 8, 5


def preregs(plan: Path = PLAN) -> dict[str, dict]:
    text = plan.read_text()
    block = re.search(r"<!-- prereg:begin.*?-->\s*```yaml\n(.*?)```\s*<!-- prereg:end -->", text, re.DOTALL)
    if not block:
        raise SystemExit(f"no prereg block between <!-- prereg:begin --> and <!-- prereg:end --> in {plan}")
    return yaml.safe_load(block.group(1))


def expect(zero_trade_periods: int) -> dict:
    """In-run stops (MarketExpect): unparsed over 10% or truncation over 5% of LLM replies, once 40 turns
    are in; or this many periods in a row without a trade in a session."""
    return {"min_turns": 40, "max_unparsed_rate": 0.10, "max_truncation_rate": 0.05,
            "stop_after_zero_trade_periods": zero_trade_periods}


def configs(blocks: dict[str, dict]) -> dict[str, dict]:
    llm = {"kind": "market", "trader": "llm", "rounds": ROUNDS, "max_tokens": 200, "temperature": 1.0}
    return {
        "zic": {"kind": "market", "name": "market_zic", "condition": "zic", "trader": "zic",
                "seeds": list(range(1000, 2000)), "periods": PERIODS, "rounds": ROUNDS, "zic_low": 0.01,
                "zic_high": 4.00, "save_turns": False},
        "m1_smoke": {**llm, "name": "m1_smoke", "condition": "haiku_smoke", "prereg": blocks["m1_smoke"],
                     "seeds": [1], "periods": 2, "model": HAIKU, "max_usd": 0.5, "expect": expect(2)},
        "m2_haiku": {**llm, "name": "m2_haiku", "condition": "haiku", "prereg": blocks["m2_haiku"],
                     "seeds": [11, 12, 13, 14], "periods": PERIODS, "model": HAIKU, "max_usd": 0.25,
                     "expect": expect(3)},
        "m3_sonnet": {**llm, "name": "m3_sonnet", "condition": "sonnet", "prereg": blocks["m3_sonnet"],
                      "seeds": [21, 22], "periods": PERIODS, "model": SONNET, "max_usd": 4.0, "expect": expect(3)},
        "m4_mixed_odd": {**llm, "name": "m4_mixed_odd", "condition": "mixed_odd", "prereg": blocks["m4_mixed"],
                         "seeds": [31, 33], "periods": PERIODS, "model": HAIKU, "senior_model": SONNET,
                         "senior_ranks": [1, 3, 5, 7, 9, 11], "max_usd": 3.0, "expect": expect(3)},
        "m4_mixed_even": {**llm, "name": "m4_mixed_even", "condition": "mixed_even", "prereg": blocks["m4_mixed"],
                          "seeds": [32, 34], "periods": PERIODS, "model": HAIKU, "senior_model": SONNET,
                          "senior_ranks": [2, 4, 6, 8, 10], "max_usd": 3.0, "expect": expect(3)},
    }


class FlowListDumper(yaml.SafeDumper):
    """Block style for mappings (readable prereg text), flow style for lists (seeds, ranks)."""


FlowListDumper.add_representer(list, lambda d, v: d.represent_sequence("tag:yaml.org,2002:seq", v, flow_style=True))

HEADER = {
    "zic": "# ZI-C baseline (Gode and Sunder 1993): quotes uniform within the budget rule, bids on [$0.01, value],\n"
           "# asks on [cost, $4.00]. Free. Written by scripts/make_market_configs.py; edit the script, not this file.\n",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, cfg in configs(preregs()).items():
        header = HEADER.get(name, f"# Market town {name}: prereg copied from research/market/plan.md by "
                                  "scripts/make_market_configs.py; edit the plan and the script, not this file.\n")
        (OUT / f"{name}.yaml").write_text(header + yaml.dump(cfg, Dumper=FlowListDumper, sort_keys=False, width=120,
                                                              default_flow_style=False))
        print(f"wrote {OUT / name}.yaml")


if __name__ == "__main__":
    main()
