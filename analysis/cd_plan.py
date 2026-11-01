"""Study CD: tier A's plan from the probe's measured costs (session E6, sections 4.2-4.3). Written and committed before
any probe call, so the rule below cannot follow what the probe shows; it reads costs and tokens only.

    python -m analysis.cd_plan        # reads the probe runs, writes research/v4/cd/plan.json and prints it

Plain words.
  usd(arm, family)   the probe's mean dollars per call of the arm on the family (analysis/cd_probe.py).
  core               the sealed core items (57 BBEH, 60 math, 50 code), every tier-A arm.
  added items        reserve items (research/v4/cd/sealed/*_reserve.txt, in their sealed order, alternating one math
                     and one code item while both last) that get only the arms of the two tests: Sonnet off, Sonnet
                     max, Haiku max and Haiku xhigh (and Sol low in the OpenAI bridge). "If costs come in low, add
                     items (power), not arms."
The rule, in order:
  1. k_probe: the odd k (1, 3, 5) whose k calls of Haiku xhigh cost nearest one Haiku max call, in dollars per item
     over the core; Haiku xhigh runs k_probe + 2 calls, so the read's nearest-k rule (on the main calls) has room on
     both sides.
  2. Tier A on the core: Haiku off x3, low, medium, high x1, xhigh x(k_probe + 2), max x3; Sonnet off, low, medium,
     high, xhigh, max x1. Its projected cost is the sum of usd(arm, family) over arms, calls and core items.
  3. If that is at most PLAN_A (90% of tier A's $40), items are added while tier A stays within PLAN_A and the OpenAI
     bridge's first two parts stay within PLAN_BRIDGE (90% of $10): Sol low on every CD1 item (the test needs it) and
     Luna low x3 on the core, at E5's measured dollars per call (code assumed, BRIDGE_USD). Sol medium (exploratory)
     takes what the bridge has left, on a share of the core set when the bridge is planned from its own probe.
  4. If it is above PLAN_A, the Sonnet arms low, medium, high and xhigh run on the first share s of each family's core
     items (run order), s the largest multiple of 0.05 that fits; if none fits, the Haiku arms low, medium and high
     likewise; if even the test arms alone (and Haiku off and max) pass PLAN_A on the whole core, they run on the first
     share of each family's core that fits (the same multiples of 0.05), and the hand-back says so.
  Ceilings: the probe's 99th percentile of output tokens x 1.5, rounded up to a multiple of 1,024, at least 4,096, at
  most the model's documented maximum output (scripts/make_cd_configs.py MAX_OUTPUT; analysis/cd_probe.py). Guards: the probe's mean dollars per call x 1.5 (the cost stop fires at 2x).
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

from analysis import cd_probe
from autoagentnet.evidence.panel import read_ids

ROOT = Path(__file__).resolve().parents[1]
SEALED = ROOT / "research/v4/cd/sealed"
PLAN_JSON = ROOT / "research/v4/cd/plan.json"
TIER_A, PLAN_A = 40.0, 0.9 * 40.0
BRIDGE, PLAN_BRIDGE = 10.0, 0.9 * 10.0
FAMILIES = ("bbeh", "math", "code")
HAIKU = {"haiku_nothink": 3, "haiku_low": 1, "haiku_med": 1, "haiku_high": 1, "haiku_max": 3}  # + haiku_xhigh
SONNET = {"sonnet_nothink": 1, "sonnet_low": 1, "sonnet_med": 1, "sonnet_high": 1, "sonnet_xhigh": 1, "sonnet_max": 1}
SONNET_MIDDLE = ("sonnet_low", "sonnet_med", "sonnet_high", "sonnet_xhigh")
HAIKU_MIDDLE = ("haiku_low", "haiku_med", "haiku_high")
TEST_ARMS = ("sonnet_nothink", "sonnet_max", "haiku_max", "haiku_xhigh")  # on added items, one call each but xhigh
BRIDGE_USD = {  # dollars per call from E5's anchor runs (research/v4/anchor/read.md), (bbeh, math, code)
    "sol61_low": (0.0024, 0.0321, 0.0200), "sol61_med": (0.0032, 0.0640, 0.0400), "luna_low_ev": (0.0003, 0.0009, 0.0006)}
MAX_CEILING = 128000  # Claude 5.5 models' documented maximum output (audit 98); tier A calls Claude only


def core_items() -> dict[str, int]:
    return {f: len(read_ids(SEALED / f"{f}_core.txt")) for f in FAMILIES}


def reserve_order() -> list[tuple[str, str]]:
    """(family, id) of the reserve items in the order they are added: math and code alternating while both last."""
    math, code = read_ids(SEALED / "math_reserve.txt"), read_ids(SEALED / "code_reserve.txt")
    out = []
    for k in range(max(len(math), len(code))):
        out += [("math", math[k])] if k < len(math) else []
        out += [("code", code[k])] if k < len(code) else []
    return out


def nearest_odd_k(xhigh: float, top: float) -> int:
    ks = [1, 3, 5]
    return ks[int(np.argmin([abs(k * xhigh - top) for k in ks]))]


def plan(costs: pd.DataFrame) -> dict:
    """The plan from the probe table (columns ref, task_kind, usd_mean, output_p99, ceiling_main, guard_main)."""
    usd = costs.set_index(["ref", "task_kind"])["usd_mean"].to_dict()
    n = core_items()
    per_item = lambda ref: sum(n[f] * usd[(ref, f)] for f in FAMILIES) / sum(n.values())
    k_probe = nearest_odd_k(per_item("haiku_xhigh"), per_item("haiku_max"))
    calls = {**HAIKU, "haiku_xhigh": k_probe + 2, **SONNET}

    def cost(share_sonnet: float, share_haiku: float, share_core: float = 1.0) -> float:
        total = 0.0
        for ref, c in calls.items():
            share = share_sonnet if ref in SONNET_MIDDLE else share_haiku if ref in HAIKU_MIDDLE else 1.0
            total += sum(round(share * round(share_core * n[f])) * c * usd[(ref, f)] for f in FAMILIES)
        return total

    grid = np.round(np.arange(1.0, -0.001, -0.05), 2)
    shares = {"sonnet_middle": 1.0, "haiku_middle": 1.0, "core": 1.0}
    core_cost = cost(1.0, 1.0)
    if core_cost > PLAN_A:
        fit = [s for s in grid if cost(s, 1.0) <= PLAN_A]
        shares["sonnet_middle"] = float(fit[0]) if fit else 0.0
        if not fit:
            fit_h = [s for s in grid if cost(0.0, s) <= PLAN_A]
            shares["haiku_middle"] = float(fit_h[0]) if fit_h else 0.0
            if not fit_h:
                fit_c = [s for s in grid if cost(0.0, 0.0, s) <= PLAN_A]
                shares["core"] = float(fit_c[0]) if fit_c else 0.0
    tier_a = cost(shares["sonnet_middle"], shares["haiku_middle"], shares["core"])
    bridge_core = sum(n[f] * (BRIDGE_USD["sol61_low"][k] + 3 * BRIDGE_USD["luna_low_ev"][k])
                      for k, f in enumerate(FAMILIES))
    added: list[tuple[str, str]] = []
    if core_cost <= PLAN_A:
        bridge = bridge_core
        for fam, item in reserve_order():
            extra = sum((k_probe + 2 if ref == "haiku_xhigh" else 1) * usd[(ref, fam)] for ref in TEST_ARMS)
            extra_bridge = BRIDGE_USD["sol61_low"][FAMILIES.index(fam)]
            if tier_a + extra > PLAN_A or bridge + extra_bridge > PLAN_BRIDGE:
                break
            tier_a, bridge = tier_a + extra, bridge + extra_bridge
            added.append((fam, item))
    bridge_total = bridge_core + sum(BRIDGE_USD["sol61_low"][FAMILIES.index(f)] for f, _ in added)
    table = costs.set_index(["ref", "task_kind"])
    return {
        "k_probe": k_probe, "calls": calls, "shares": shares, "core": n,
        "added": {f: [i for g, i in added if g == f] for f in ("math", "code")},
        "projected_tier_a_usd": round(tier_a, 2), "projected_core_usd": round(core_cost, 2),
        "projected_bridge_usd": round(bridge_total, 2),
        "ceilings": {ref: {f: int(min(MAX_CEILING, table.loc[(ref, f), "ceiling_main"])) for f in FAMILIES}
                     for ref in calls},
        "guards": {ref: {f: round(float(table.loc[(ref, f), "guard_main"]), 6) for f in FAMILIES} for ref in calls},
    }


def main() -> dict:
    out = plan(cd_probe.table(cd_probe.probe_calls()))
    PLAN_JSON.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k != "added"} | {"added": {f: len(v) for f, v in out["added"].items()}},
                     indent=2))
    return out


if __name__ == "__main__" and "--v3" not in sys.argv:
    main()


# ---------------------------------------------------------------------------------------------------------------------
# plan_v3 (after probe stage 1, before any main call; audit 100, which superseded the draft plan_v2 of 44660b7): the
# frozen rule above, run on the probe's costs, shrinks every family alike (ladder middles to 0, core to 50%, $32.78),
# although only Sonnet's xhigh and max on math and code are dear; and ceilings set from 3 probe calls fall far below
# E5's data for the same refs. plan_v3 is a cost-only revision: it reads tokens and dollars, never a grade.
#   ceilings  every thinking arm on math and code, and Haiku's thinking arms on BBEH (audit 101): the model's maximum
#             output (128,000), so no call is cut short; a thinking-off arm, and Sonnet's thinking arms on BBEH: 1.5 x
#             the longest call the probe or E5 saw for that ref (for a ref E5 did not run, its model's highest effort
#             E5 ran: Haiku high, Sonnet high), at least 8,192 (off) or 16,384 (Sonnet thinking on BBEH, audit 101).
#   prices    each arm's dollars per call: the larger of the probe's (a cut probe call priced as if it had used the
#             whole main ceiling) and E5's live mean for the same ref and family.
#   items     BBEH: every core item, every arm. Then blocks of BLOCK items, alternating math and code (math first) in
#             item_order, every arm; a block starts only if tier A's actual spend so far plus the block's projected
#             cost stays within TIER_A_CAP (scripts/run_cd_tier_a.py).
#   stops     arms at 128,000 do not stop on truncation (their cut share is reported and cut calls count as wrong);
#             other arms keep the 2% stop.

TIER_A_CAP, BLOCK = 36.0, 2
MODEL_MAX = 128000  # the Claude 5.5 models' documented maximum output (scripts/make_cd_configs.py MAX_OUTPUT)
PRICE_OUT = {"haiku": 0.50, "sonnet": 10.0}  # dollars per million output tokens (the configured prices)
CALLS_V3 = {**HAIKU, "haiku_xhigh": 3, **SONNET}  # CD2 is exploratory (audit 98): Haiku xhigh x3 suffices for the
# dollar-matched 1- or 3-vote (audit 100: max costs about 2.4x xhigh, so k = 3 is reachable)
POST_CUTOFF = ("arxivcs-0826", "arxivphys-0826")
E5_STAND_IN = {"haiku": "haiku_high", "sonnet": "sonnet_high"}  # the highest effort E5 ran, per model
OFF = ("haiku_nothink", "sonnet_nothink")


def e5_calls(results: Path = ROOT / "results") -> pd.DataFrame:
    """E5's live base-prompt calls (results/e5[0-2]_*/calls.csv): ref, family, output tokens, dollars."""
    frames = []
    for path in sorted(results.glob("e5[0-2]_*/calls.csv")):
        c = pd.read_csv(path, usecols=lambda x: x in ("ref", "task_kind", "prompt", "output_tokens", "cost_usd",
                                                      "from_cache"), low_memory=False)
        frames.append(c[(c["prompt"] == "base") & ~c["from_cache"].astype(bool)])
    return pd.concat(frames, ignore_index=True)


SONNET_BBEH_FLOOR = 16384  # audit 101: Sonnet's thinking arms on BBEH at least this (E5's longest Sonnet high: 5,170)


def ceiling_v3(ref: str, family: str, probe: pd.DataFrame, e5: pd.DataFrame) -> int:
    if ref not in OFF and (family in ("math", "code") or ref.startswith("haiku") or ref in ("sonnet_xhigh", "sonnet_max")):
        return MODEL_MAX  # audit 101: Haiku's thinking arms on BBEH too (E5's longest Haiku high there was its ceiling);
        # audit 102: Sonnet's xhigh and max on BBEH too (on linguini Haiku max averaged 86,522 tokens per call)
    longest = probe.loc[(probe["ref"] == ref) & (probe["task_kind"] == family), "output_tokens"].max()
    ran = ((e5["ref"] == ref) & (e5["task_kind"] == family)).any()
    stand_in = ref if ran or ref in OFF else E5_STAND_IN[ref.split("_")[0]]  # an off arm borrows no thinking arm's length
    e5_longest = e5.loc[(e5["ref"] == stand_in) & (e5["task_kind"] == family), "output_tokens"].max()
    longest = max(x for x in (longest, e5_longest, 0) if pd.notna(x))
    floor = 8192 if ref in OFF else SONNET_BBEH_FLOOR
    return int(min(MODEL_MAX, max(floor, math.ceil(1.5 * longest / 1024) * 1024)))


def price_v3(ref: str, family: str, ceiling: int, probe: pd.DataFrame, e5: pd.DataFrame) -> float:
    g = probe[(probe["ref"] == ref) & (probe["task_kind"] == family)]
    rate = PRICE_OUT[ref.split("_")[0]] / 1e6
    extra = np.where(g["truncated"].astype(bool), (ceiling - g["output_tokens"]).clip(lower=0) * rate, 0.0)
    probe_usd = float((g["cost_usd"] + extra).mean())
    e5_usd = e5.loc[(e5["ref"] == ref) & (e5["task_kind"] == family), "cost_usd"].mean()
    return max(probe_usd, float(e5_usd) if pd.notna(e5_usd) else 0.0)


def guard_v3(ref: str, ceiling: int, usd: float) -> float:
    """The cost stop's guard (the stop fires at 2x it): 1.5x the projected dollars per call, but for an arm at the
    model's maximum output at least half a call's output worst case, so its stop sits at the worst case and cannot fire
    (audit 102: at 128,000 a highest-effort arm's mean depends on a few calls that run to the limit, e.g. Haiku max on
    BBEH averaged $0.0169 against a probe-based guard of $0.0021); the tier spend rules ($36 per block, $40 hard cap)
    protect the money instead."""
    floor = 0.5 * ceiling * PRICE_OUT[ref.split("_")[0]] / 1e6 if ceiling >= MODEL_MAX else 0.0
    return round(max(1.5 * usd, floor), 6)


def item_order(family: str) -> list[str]:
    """Core items in the order tier A adds them: math's post-cutoff items first (clean for every vendor), then the
    rest; each part in its sealed run order. BBEH and code: the sealed run order."""
    ids = read_ids(SEALED / f"{family}_core.txt")
    if family != "math":
        return ids
    return [i for i in ids if i.startswith(POST_CUTOFF)] + [i for i in ids if not i.startswith(POST_CUTOFF)]


def blocks() -> list[tuple[str, int, int]]:
    """(family, first offset, end offset) of the math and code blocks, alternating, math first."""
    n = {f: len(read_ids(SEALED / f"{f}_core.txt")) for f in ("math", "code")}
    out = []
    for start in range(0, max(n.values()), BLOCK):
        out += [(f, start, min(start + BLOCK, n[f])) for f in ("math", "code") if start < n[f]]
    return out


def plan_v3(probe: pd.DataFrame, e5: pd.DataFrame) -> dict:
    """probe: the probe's live calls (ref, task_kind, output_tokens, cost_usd, truncated)."""
    probe = probe[~probe["from_cache"].fillna(False).astype(bool)] if "from_cache" in probe else probe
    ceilings = {ref: {f: ceiling_v3(ref, f, probe, e5) for f in FAMILIES} for ref in CALLS_V3}
    usd = {ref: {f: round(price_v3(ref, f, ceilings[ref][f], probe, e5), 6) for f in FAMILIES} for ref in CALLS_V3}
    per_item = {f: round(sum(c * usd[ref][f] for ref, c in CALLS_V3.items()), 4) for f in FAMILIES}
    n_bbeh = len(read_ids(SEALED / "bbeh_core.txt"))
    return {"rule": "plan_v3", "calls": CALLS_V3, "items": {f: item_order(f) for f in FAMILIES},
            "ceilings": ceilings, "usd": usd, "guards": {r: {f: guard_v3(r, ceilings[r][f], v) for f, v in u.items()}
                                                          for r, u in usd.items()},
            "per_item_usd": per_item, "bbeh_projected_usd": round(n_bbeh * per_item["bbeh"], 2),
            "tier_a_cap": TIER_A_CAP, "block": BLOCK,
            "expected_items": expected_items(per_item, n_bbeh)}


def expected_items(per_item: dict, n_bbeh: int) -> dict:
    """How many math and code items the block rule would reach if every block cost its projection."""
    total, got = n_bbeh * per_item["bbeh"], {"bbeh": n_bbeh, "math": 0, "code": 0}
    for fam, start, end in blocks():
        cost = (end - start) * per_item[fam]
        if total + cost > TIER_A_CAP:
            break
        total += cost
        got[fam] += end - start
    return {**got, "projected_usd": round(total, 2)}


def main_v3() -> dict:
    cols = cd_probe.COLUMNS
    probe = pd.concat([pd.read_csv(p, usecols=lambda c: c in cols)
                       for p in sorted((ROOT / "results").glob("e60_cd_probe*/calls.csv"))], ignore_index=True)
    out = plan_v3(probe, e5_calls())
    PLAN_JSON.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({k: v for k, v in out.items() if k not in ("items", "guards")}, indent=1))
    return out


if __name__ == "__main__" and "--v3" in sys.argv:
    main_v3()
