"""Session E5, step 5.3: write the API anchor's panel configs (configs/experiments/v4/e51_*.yaml). $0.

    python scripts/make_anchor_configs.py      # after sealing (research/v4/anchor/sealed/) and the prereg

Plain words. One config per vendor, task kind and group of arms, so that each `aan run` calls one vendor and its worst
case can be sliced under the run cap (scripts/anchor_slices.py). Every config carries the same prereg block, which
points to research/v4/anchor/prereg.md (the full text), uses parser v2 (anchor only, audits 69-70) and the anchor's
stop rules: over 5% unparsed (Kevin's Oct 19 note), over 2% truncated (the brief: such a run stops for an audit), or
a cost per call above twice the scans' measured one. Arms are named by effort (audits 69-70); ceilings (max_tokens)
are fixed per arm and task kind in CEILINGS.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs/experiments/v4"
A = "research/v4/anchor"
TASKS = {"bbeh": "data/external/bbeh_all.jsonl", "math": "data/external/evidence/math.jsonl"}
ITEMS = {"bbeh": f"{A}/sealed/bbeh_anchor_order.txt", "math": "research/v3/evidence/sealed/math_all.txt"}  # BBEH
# interleaved across the tasks (audit 71), so every slice covers all four
SECOND = {kind: f"{A}/sealed/{kind}_second_call.txt" for kind in ("bbeh", "math")}
CEILINGS = {  # ref: (bbeh, math)
    "haiku_nothink": (4000, 4000), "haiku_low": (12288, 12288), "haiku_high": (18432, 36864),
    "sonnet_nothink": (4000, 4000), "sonnet_low": (12288, 12288), "sonnet_high": (18432, 36864),
    "opus_nothink": (12288, 12288),
    "luna_none": (2000, 4000), "luna_low_ev": (6144, 12288), "luna_med": (12288, 24576),
    "sol61_low": (6144, 12288), "sol61_med": (12288, 24576), "astra_low": (12288, 12288),
}  # audit 81 (blind, before any OpenAI math call): the OpenAI reasoning arms' math ceilings doubled, so that, as the
# prereg intends, truncation is not part of an arm (on the anchor's math, 19.7% of Haiku-low and 4.9% of Sonnet-low
# calls went past 6,144 tokens); Sol's math self-check and judge take Sol low's
GUARD = {  # dollars per call, (bbeh, math): BBEH the dearest of the 4 tasks in the scans (audit 71: a mix mean made
    # false stops likely on linguini); math the scans' mean; unmeasured arms assumed (analysis/anchor_cost.py)
    "haiku_nothink": (0.00044, 0.0006), "haiku_low": (0.0010, 0.0010), "haiku_high": (0.0016, 0.0100),
    "sonnet_nothink": (0.0107, 0.0126), "sonnet_low": (0.0095, 0.0133), "sonnet_high": (0.0300, 0.0400),
    "opus_nothink": (0.0240, 0.0270),
    "luna_none": (0.0002, 0.0004), "luna_low_ev": (0.0005, 0.0016), "luna_med": (0.0013, 0.0040),
    "sol61_low": (0.0044, 0.0300), "sol61_med": (0.0110, 0.0750), "astra_low": (0.0220, 0.0720),
}  # audit 81: the OpenAI reasoning arms' math guards rebased to the scan price x 2.1 (on the anchor's math the
# reasoning arms cost 1.47x and 2.06x their scan price, so the scan means would make a cost stop a coin flip)
UNPARSED = {"bbeh": 0.05, "math": 0.30}  # math: Kevin's Oct 19 allowance for math abstentions (the scans: up to 2 of 10)
PREREG = {
    "question": ("API anchor (session E5, step 5.3; research/v4/anchor/prereg.md is the full prereg). On fresh sealed items "
                 "(4 BBEH tasks and 93 arXivMath items), how do width (repeat calls), depth (reasoning effort, a stronger "
                 "tier) and verification (self-checks, judges) trade off per dollar, for Anthropic and OpenAI models?"),
    "prediction": "As in research/v4/anchor/prereg.md (predictions P1-P6).",
    "kill": ("Over every call of the config so far: stop if a source leaves over 5% unparsed (BBEH; math 30%) or truncates "
             "over 2% of its calls (the brief: such a run stops for an audit), costs over 2x its guard per call, or the "
             "governor projects a vendor past its cap; no slice starts if the anchor's spend plus the slice's expected "
             "cost would pass K3 (scripts/run_anchor.py)."),
    "decision": "As in research/v4/anchor/prereg.md (AH1-AH4 under Holm, the demotions from power.md, the exploratory reads).",
}


def source(ref: str, kind: str, calls: int = 1, first_call: int = 0, items: str | None = None,
           prompt: str = "base", checks: str | None = None) -> dict:
    s = {"ref": ref, "calls": calls, "max_tokens": CEILINGS[ref][0 if kind == "bbeh" else 1]}
    if first_call:
        s["first_call"] = first_call
    if items:
        s["items"] = items
    if prompt != "base":
        s["prompt"] = prompt
    if checks:
        s["checks"] = checks
    return s


def config(name: str, kind: str, sources: list[dict], items: str | None = None, truncation: float = 0.02,
           guard: dict | None = None, **extra) -> dict:
    refs = {s["ref"] for s in sources}
    usd = {r: GUARD[r][0 if kind == "bbeh" else 1] for r in sorted(refs)}
    return {"kind": "panel", "name": name, "task_kind": kind, "tasks": TASKS[kind], "items": items or ITEMS[kind],
            "sources": sources, "parser": "v2", "max_usd": 4.0, "chunk_size": 25, "max_concurrency": 8,
            "stop_over_config": True,
            "expect": {"min_calls": 20, "max_unparsed_rate": UNPARSED[kind], "max_truncation_rate": truncation,
                       "usd_per_call": {**usd, **(guard or {})}, "max_cost_ratio": 2.0},
            "prereg": with_kill(PREREG, truncation), **extra}


def with_kill(prereg: dict, truncation: float) -> dict:
    """The prereg block, its kill text naming this config's truncation stop when it is not the default 2% (audit 76)."""
    if truncation == 0.02:
        return prereg
    kill = prereg["kill"].replace("truncates over 2% of its calls (the brief: such a run stops for an audit)",
                                  f"truncates over {truncation:.0%} of its calls (the pre-declared fallback stop)")
    return {**prereg, "kill": kill}


def configs() -> dict[str, dict]:
    out = {}
    for kind in ("bbeh", "math"):
        k = kind
        if kind == "bbeh":
            out[f"e51_haiku_{k}"] = config(f"e51_haiku_{k}", kind, [
                source("haiku_nothink", kind, 3), source("haiku_low", kind, 3), source("haiku_high", kind, 3)])
        else:  # Haiku effort high on math in its own config (audit 71): if it stops on truncation, its math cells
            # are dropped (the scan's math decision) without stopping the other Haiku arms
            out["e51_haiku_math"] = config("e51_haiku_math", kind, [source("haiku_nothink", kind, 3),
                                                                     source("haiku_low", kind, 3)])
            out["e51_haiku_high_math"] = config("e51_haiku_high_math", kind, [source("haiku_high", kind, 3)])
            # audit 73, option (d): e51_haiku_math stopped on haiku_low's truncation at 12,288; Haiku off continues alone
            # (its first 25 items come from the cache), Haiku effort low reruns on math at 36,864 with the 2% stop, and
            # if that stops on truncation the pre-declared fallback (a) resumes it at 12,288 with a 30% stop
            out["e51_haiku_off_math"] = config("e51_haiku_off_math", kind, [source("haiku_nothink", kind, 3)])
            low36 = {**source("haiku_low", kind, 3), "max_tokens": 36864}
            out["e51_haiku_low_math36"] = config("e51_haiku_low_math36", kind, [low36], guard={"haiku_low": 0.0025})
            out["e51_haiku_low_math12"] = config("e51_haiku_low_math12", kind, [source("haiku_low", kind, 3)],
                                                 truncation=0.30, guard={"haiku_low": 0.0025})
        out[f"e51_sonnet_{k}"] = config(f"e51_sonnet_{k}", kind, [
            source("sonnet_nothink", kind), source("sonnet_low", kind),
            source("sonnet_nothink", kind, first_call=1, items=SECOND[kind]),
            source("sonnet_low", kind, first_call=1, items=SECOND[kind])])
        if kind == "math":  # the pre-declared fallback (audits 73 and 75): e51_sonnet_math stopped on Sonnet effort
            # low's truncation (1 of 38 calls at 12,288), so it resumes at the same ceilings with a 30% truncation stop
            out["e51_sonnet_math_t30"] = config("e51_sonnet_math_t30", kind, out["e51_sonnet_math"]["sources"],
                                                truncation=0.30)
        out[f"e51_luna_{k}"] = config(f"e51_luna_{k}", kind, [
            source("luna_none", kind, 3), source("luna_low_ev", kind, 3), source("luna_med", kind, 3)])
        out[f"e51_sol_{k}"] = config(f"e51_sol_{k}", kind, [source("sol61_low", kind, 3), source("sol61_med", kind)])
        if kind == "math":  # audit 87: Sol medium's math cells are dropped as whole cells (a long Sol medium request
            # failed server-side on every attempt, streamed or not); Sol low continues alone, its calls so far from cache
            out["e51_sol_math_low"] = config("e51_sol_math_low", kind, [source("sol61_low", kind, 3)])
        # tier 2 (only if tier 1's measured cost leaves room under K3; Astra only if OpenAI tier 1 is under $20)
        out[f"e51_tier2_anth_{k}"] = config(f"e51_tier2_anth_{k}", kind, [
            source("opus_nothink", kind, items=f"{A}/sealed/{k}_tier2_opus.txt"),
            source("sonnet_high", kind, items=f"{A}/sealed/{k}_tier2_sonnet_high.txt")])
        out[f"e51_tier2_open_{k}"] = config(f"e51_tier2_open_{k}", kind, [
            source("astra_low", kind, items=f"{A}/sealed/{k}_tier2_astra.txt")])
        # verification, after the generators: self-checks on own call 0; judges on the cheap pools (AH4). On math the
        # Haiku pools come from the runs audit 73 kept (Haiku off: e51_haiku_off_math; Haiku effort low:
        # e51_haiku_low_math12), and Haiku effort high's math judge cells are dropped like its generator cells
        # (audit 74); Haiku effort low's math self-check keeps its generator's 30% truncation stop
        off = f"results/e51_haiku_{k}/calls.csv" if kind == "bbeh" else "results/e51_haiku_off_math/calls.csv"
        low = f"results/e51_haiku_{k}/calls.csv" if kind == "bbeh" else "results/e51_haiku_low_math12/calls.csv"
        anth, open_ = off, f"results/e51_luna_{k}/calls.csv"  # judge pools: Haiku off, Luna low
        if kind == "bbeh":
            out[f"e51_verify_anth_{k}"] = config(f"e51_verify_anth_{k}", kind, [
                source("haiku_low", kind, prompt="self_check", checks="haiku_low:base"),
                source("haiku_high", kind, prompt="judge")],
                panel_results=[open_, low], panel_sources={"luna_low_ev:base": 3})
        else:
            out[f"e51_verify_anth_{k}"] = config(f"e51_verify_anth_{k}", kind, [
                source("haiku_low", kind, prompt="self_check", checks="haiku_low:base")],
                panel_results=[low], truncation=0.30, guard={"haiku_low": 0.0025})  # its generator's math price
        sol = f"results/e51_sol_{k}/calls.csv" if kind == "bbeh" else "results/e51_sol_math_low/calls.csv"  # audit 87
        out[f"e51_verify_open_{k}"] = config(f"e51_verify_open_{k}", kind, [
            source("sol61_low", kind, prompt="self_check", checks="sol61_low:base")],
            panel_results=[sol])
        out[f"e51_judge_open_{k}"] = config(f"e51_judge_open_{k}", kind, [source("sol61_low", kind, prompt="judge")],
                                            panel_results=[anth, open_],
                                            panel_sources={"haiku_nothink:base": 3, "luna_low_ev:base": 3})
    # pre-declared fallbacks written ahead (audit 76): the same sources and ceilings with a 30% truncation stop, run
    # only if the config stops on truncation (after its post-stop audit)
    for name in ("e51_luna_bbeh", "e51_verify_anth_bbeh", "e51_tier2_anth_bbeh", "e51_tier2_anth_math", "e51_sol_math_low"):
        base = out[name]
        out[f"{name}_t30"] = {**base, "name": f"{name}_t30", "prereg": with_kill(PREREG, 0.30),
                              "expect": {**base["expect"], "max_truncation_rate": 0.30}}
    return out


CLOSED = {  # configs closed by an audit: written with a $0 run cap so that no paid call can run (audit 74)
    "e51_tier2_open_bbeh": "Astra (tier-2 OpenAI) skipped by Kevin's decision D1 (session E6)",
    "e51_tier2_open_math": "Astra (tier-2 OpenAI) skipped by Kevin's decision D1 (session E6)",
    "e51_haiku_math": "stopped on Haiku effort low's truncation (audit 73)",
    "e51_haiku_low_math36": "stopped on truncation; the 12,288 fallback applies (audit 73)",
    "e51_haiku_high_math": "Haiku effort high's math cells dropped without calls (audit 73)",
    "e51_sonnet_math": "stopped on Sonnet effort low's truncation (2.6%); the pre-declared 30% fallback e51_sonnet_math_t30 "
                       "applies (audits 73, 75)",
    "e51_sol_math": "Sol medium's math cells dropped (a long request failed server-side on every attempt); Sol low "
                    "continues alone in e51_sol_math_low (audits 86, 87)",
}


def main() -> None:
    every = configs()
    for name, why in CLOSED.items():
        every[name] = {**every[name], "max_usd": 0.0}
    for name, cfg in every.items():
        head = ("# Session E5 API anchor (step 5.3). Written by scripts/make_anchor_configs.py; the prereg is "
                "research/v4/anchor/prereg.md.\n")
        if name in CLOSED:
            head += f"# CLOSED: {CLOSED[name]}. max_usd 0 blocks any paid call.\n"
        text = head + yaml.safe_dump(cfg, sort_keys=False, width=120, allow_unicode=True)
        (OUT / f"{name}.yaml").write_text(text)
        print(name)


if __name__ == "__main__":
    main()
