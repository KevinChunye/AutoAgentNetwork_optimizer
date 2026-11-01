"""The anchor's expected cost against K3 (session E5, step 5.6), from measured dollars per call. $0.

    python -m analysis.anchor_cost <n per task>    # writes research/v4/anchor/cost.md

Plain words. Expected dollars of a cell = items x calls x dollars per call, with BBEH and math priced apart (math
replies are longer). Dollars per call come from the two scans (research/v4/anchor/scan_read.md, the e52 Sonnet scan)
where the arm was measured, else they are assumed from a measured arm and list prices (marked "assumed"). K3: Anthropic
expected at most $48 with every call by Oct 31; OpenAI at most $34; Astra only in tier 2 and only if OpenAI tier 1's
measured cost is under $20. Drop order if K3 breaks (5.6): Sonnet effort high, Opus, Astra, Luna medium, then the
second-call subsets. Worst cases are not here: `aan estimate` gives them per config before any run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

from analysis.pruning_phase3a import md

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v4/anchor/cost.md"
N_MATH = 93
K3 = {"anthropic": 48.0, "openai": 34.0}
# arm: (account, dollars per call on BBEH, on math, source of the numbers)
PRICE = {
    "haiku_off": ("anthropic", 0.0003, 0.0006, "measured"),
    "haiku_low": ("anthropic", 0.0005, 0.0010, "measured (ceiling 6,144; the anchor's 12,288 adds only where it truncated)"),
    "haiku_high": ("anthropic", 0.0007, 0.0100, "BBEH measured on 8 calls; math assumed: measured $0.0058 at 18,432 with 4 of 10 truncated, doubled ceiling"),
    "sonnet_off": ("anthropic", 0.0056, 0.0126, "measured (e52)"),
    "sonnet_low": ("anthropic", 0.0054, 0.0133, "measured (e52)"),
    "sonnet_high": ("anthropic", 0.0160, 0.0400, "assumed: 3x Sonnet low"),
    "opus_low": ("anthropic", 0.0110, 0.0270, "assumed: 2x Sonnet low (Opus list prices are 2x Sonnet's)"),
    "luna_none": ("openai", 0.0001, 0.0002, "BBEH measured in Phase 1; math assumed"),
    "luna_low": ("openai", 0.0003, 0.0007, "measured"),
    "luna_med": ("openai", 0.0008, 0.0018, "assumed: 2.5x Luna low"),
    "sol_low": ("openai", 0.0021, 0.0143, "measured"),
    "sol_med": ("openai", 0.0053, 0.0360, "assumed: 2.5x Sol low"),
    "astra_low": ("openai", 0.0105, 0.0720, "assumed: 5x Sol low (Astra list prices are 5x Sol's)"),
}


def cells(per_task: int) -> list[dict]:
    """(tier, arm, BBEH items, math items, calls) of the brief's design (5.3) at `per_task` BBEH items per task."""
    b = 4 * per_task
    out = []
    for arm, calls in [("haiku_off", 3), ("haiku_low", 3), ("haiku_high", 3), ("sonnet_off", 1), ("sonnet_low", 1)]:
        out.append({"tier": "1", "arm": arm, "bbeh": b, "math": N_MATH, "calls": calls})
    for arm in ("sonnet_off", "sonnet_low"):  # second calls on 50 items, in the anchor's mix
        out.append({"tier": "1 second calls", "arm": arm, "bbeh": 34, "math": 16, "calls": 1})
    for arm, calls in [("luna_none", 3), ("luna_low", 3), ("luna_med", 3), ("sol_low", 3), ("sol_med", 1)]:
        out.append({"tier": "1", "arm": arm, "bbeh": b, "math": N_MATH, "calls": calls})
    out += [{"tier": "2", "arm": "opus_low", "bbeh": 68, "math": 32, "calls": 1},
            {"tier": "2", "arm": "sonnet_high", "bbeh": 41, "math": 19, "calls": 1},
            {"tier": "2", "arm": "astra_low", "bbeh": 68, "math": 32, "calls": 1}]
    # verification: self-checks on own call-0 answers; Sol low judges two cheap pools; Haiku high judges the Luna pool
    out += [{"tier": "verification", "arm": "haiku_low", "bbeh": b, "math": N_MATH, "calls": 1, "note": "self-check"},
            {"tier": "verification", "arm": "sol_low", "bbeh": b, "math": N_MATH, "calls": 1, "note": "self-check"},
            {"tier": "verification", "arm": "sol_low", "bbeh": 2 * b, "math": 2 * N_MATH, "calls": 1, "note": "judge, 2 pools"},
            {"tier": "verification", "arm": "haiku_high", "bbeh": b, "math": N_MATH, "calls": 1, "note": "judge, Luna pool"}]
    return out


def table(per_task: int) -> pd.DataFrame:
    t = pd.DataFrame(cells(per_task))
    t["account"] = t["arm"].map(lambda a: PRICE[a][0])
    t["usd"] = t["calls"] * (t["bbeh"] * t["arm"].map(lambda a: PRICE[a][1]) + t["math"] * t["arm"].map(lambda a: PRICE[a][2]))
    t["prices"] = t["arm"].map(lambda a: PRICE[a][3])
    return t


def main(per_task: int) -> str:
    t = table(per_task)
    by = t.groupby(["account", "tier"])["usd"].sum().reset_index()
    total = t.groupby("account")["usd"].sum()
    open_t1 = float(t[(t["account"] == "openai") & (t["tier"] == "1")]["usd"].sum())
    fits = {a: bool(total.get(a, 0.0) <= K3[a]) for a in K3}
    text = "\n".join([
        f"# Anchor expected cost against K3 ({per_task} BBEH items per task + {N_MATH} math)", "",
        "Written by `python -m analysis.anchor_cost`; prices per call in its docstring table (measured or assumed, "
        "column prices). Expected cost only; each config's worst case comes from `aan estimate` before it runs.", "",
        md(t[["tier", "arm", "account", "bbeh", "math", "calls", "usd", "prices"]], 3), "",
        md(by, 2), "",
        f"Totals: Anthropic ${total.get('anthropic', 0.0):.2f} (K3 $48: {'fits' if fits['anthropic'] else 'breaks'}); "
        f"OpenAI ${total.get('openai', 0.0):.2f} (K3 $34: {'fits' if fits['openai'] else 'breaks'}). OpenAI tier 1 "
        f"${open_t1:.2f}: Astra {'allowed' if open_t1 < 20 else 'not allowed'} by K3 (needs under $20).", ""])
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    main(int(sys.argv[1]) if len(sys.argv) > 1 else 110)
