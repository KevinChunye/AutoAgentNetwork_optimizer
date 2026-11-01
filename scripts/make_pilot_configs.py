"""Write the pilot's experiment configs (protocol v2) for one gate candidate and one Haiku worker ref.

    python scripts/make_pilot_configs.py --candidate omni_d44_61 --short omni --ref haiku_nothink
    python scripts/make_pilot_configs.py --banding-only --candidate bbeh_band --short bbeh --ref haiku_nothink

The ref is the Haiku worker P0 chooses (haiku_nothink unless P0 shows thinking is needed).
Every config gets the `prereg:` block of its step, copied verbatim from the YAML block between
the `prereg:begin` / `prereg:end` markers in research/plan.md (amendment 3, rule 16), so the file
and the plan cannot drift apart. Task files come from scripts/prepare_tasks.py; slices follow
its fixed order (protocol v2, section 5.4):

  P0          calibration items 0-4: the single agent once per model ref (Haiku variants, the
              Sonnet control/judge, Luna for P5), and the dense network on items 0-1 with the ref
  P2 banding  <candidate>_banding.jsonl, single agent only (choose the difficulty window)
  P2 probes   calibration items 0-19: single and dense
  P3 confirm  items 0-59 (calibration 0-19 come free from the cache, validation 20-59 are new),
              run first with --task-limit 40 for the futility check (rule 19); plus the matched-cost
              senior (single_sonnet) on validation 20-59, a noise run (replicates 2 on 20-29) and
              optional gate-widening runs p3w (validation 100-119; 60-99 stays clean for P4's held-out half)
  P4          factorial grid, levels 1/3/6 per stage (27 configs, 105 calls per task), on
              validation 20-59 (search half) and 60-99 (held-out half), in parts of --p4-part-size
              items: p4_<short>_grid_a, b, ... (the first half of the parts is the search half)
              plus the single agent on the held-out half (p4_<short>_single_held, the H4 control)
  P4b         judge_cascade live on the held-out half 60-99 (its proposers are the dense run's
              cached calls); vote6, consensus policies and the equimarginal path are offline
  P5          dense + 3 pruned configs on luna_low, held-out items 60-69; the three configs are
              placeholders until P4 picks them
"""

from __future__ import annotations

import argparse
import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "configs/experiments/pilot"
PLAN = ROOT / "research/plan.md"
SINGLE, DENSE = "configs/networks/single.yaml", "configs/networks/dense_3x6.yaml"
SINGLE_SONNET, CASCADE = "configs/networks/single_sonnet.yaml", "configs/networks/judge_cascade.yaml"
P0_REFS = ["haiku", "haiku_nothink", "haiku_low", "sonnet_nothink", "luna_low", "gpt_small"]
SINGLE_MAX_COST = 0.002  # one Haiku or Luna call: worst case is about $0.0005
SONNET_MAX_COST = 0.02  # one Sonnet call: worst case is about $0.01
LETTERS = "abcdefghijklmnopqrst"


def preregs(plan: Path = PLAN) -> dict[str, dict]:
    """The prereg blocks of every step, from the fenced YAML between the markers in plan.md."""
    text = plan.read_text()
    block = re.search(r"<!-- prereg:begin.*?-->\s*```yaml\n(.*?)```\s*<!-- prereg:end -->", text, re.DOTALL)
    if not block:
        raise SystemExit(f"no prereg block between <!-- prereg:begin --> and <!-- prereg:end --> in {plan}")
    return yaml.safe_load(block.group(1))


def expect(max_unparsed: float, min_tasks: int, error_range: bool, max_cost: float, max_truncation: float = 0.05) -> dict:
    """Early-stop rules, checked after every chunk once min_tasks tasks are done (chunk_size is at
    most half of task_limit, so a check fires before the run ends; audit 1, finding 6).
    The error range only catches a broken pipeline (the gate is judged offline) and is left out
    where a handful of tasks makes it noise; cost, truncation and unparsed answers catch token
    blow-ups and grader trouble."""
    return {"min_tasks": min_tasks, "dense_error_range": [0.02, 0.98] if error_range else None,
            "max_dense_cost_per_task_usd": max_cost, "max_truncation_rate": max_truncation, "max_unparsed_rate": max_unparsed}


def experiment(name, network, tasks, ref, prereg, *, offset=0, limit=None, configs=None, replicates=1,
               max_usd=1.0, chunk=10, concurrency=8, exp=None, note="") -> dict:
    """ref None leaves every agent on the network's own model refs (single_sonnet)."""
    cfg = {"name": name, "network": network, "tasks": tasks, "task_offset": offset, "task_limit": limit,
           "model_override": ref, "max_usd": max_usd, "chunk_size": chunk, "max_concurrency": concurrency}
    if configs is not None:
        cfg["configs"] = configs
    if replicates != 1:
        cfg["replicates"] = replicates
    if exp is not None:
        cfg["expect"] = exp
    cfg["prereg"] = prereg
    return {"_note": note, **cfg}


def write(cfg: dict) -> Path:
    note = cfg.pop("_note")
    path = OUT / f"{cfg['name']}.yaml"
    header = "".join(f"# {line}\n" for line in note.strip().splitlines())
    header += "# Generated by scripts/make_pilot_configs.py; prereg copied from research/plan.md (amendment 3).\n"
    body = yaml.safe_dump({k: v for k, v in cfg.items() if v is not None}, sort_keys=False, width=110)
    path.write_text(header + body)
    return path


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--candidate", required=True, help="task file name under data/external/, without .jsonl")
    p.add_argument("--short", required=True, help="short name used in experiment names, e.g. omni")
    p.add_argument("--ref", default="haiku_nothink", help="the Haiku worker ref chosen in P0")
    p.add_argument("--banding-only", action="store_true")
    p.add_argument("--band-limit", type=int, default=None, help="banding items to run (default: all)")
    p.add_argument("--band-prereg", default="p2_band", help="prereg block for the banding run (p2_band_move after a band move)")
    p.add_argument("--probe-prereg", default="p2_probe", help="prereg block for the P2b dense probe (p2_probe_bbeh for BBEH)")
    p.add_argument("--max-dense-cost", type=float, default=0.02, help="dense $/task early-stop threshold")
    p.add_argument("--p4-part-size", type=int, default=10, choices=[5, 10, 20, 40],
                   help="items per P4 run; smaller parts if P0 shows a low rate limit (amendment 1, rule 7)")
    p.add_argument("--p4-concurrency", type=int, default=16)
    p.add_argument("--sonnet-max-cost", type=float, default=SONNET_MAX_COST,
                   help="single-Sonnet $/task early stop; 0.04 for BBEH (Kevin, STEERING 2026-10-19; plan rule 54)")
    p.add_argument("--cascade-max-cost", type=float, default=0.03,
                   help="judge_cascade $/task early stop; 0.06 for BBEH (Kevin, STEERING 2026-10-19; plan rule 54)")
    p.add_argument("--band-max-truncation", type=float, default=0.05,
                   help="truncation stop of the banding run only; 0.25 for BBEH (Kevin, STEERING 2026-10-19; plan rule 50)")
    p.add_argument("--max-unparsed", type=float, default=0.10,
                   help="unparsed-answer early stop; 0.30 for omni_d61_78 (Kevin, STEERING 2026-10-19; plan rule 45)")
    a = p.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    pr = preregs()
    tasks, band = f"data/external/{a.candidate}.jsonl", f"data/external/{a.candidate}_banding.jsonl"
    c = a.max_dense_cost
    cfgs = [experiment(f"p2_{a.short}_band_single", SINGLE, band, a.ref, pr[a.band_prereg], limit=a.band_limit, max_usd=0.5,
                       chunk=10, exp=expect(a.max_unparsed, 10, False, SINGLE_MAX_COST, a.band_max_truncation),
                       note=f"P2 banding: single agent on the banding pool of {a.candidate} (never in any split).\n"
                            "Choose the difficulty window / tasks from this run only (band rule in research/plan.md).")]
    if not a.banding_only:
        for ref in P0_REFS:
            cost = SONNET_MAX_COST if ref.startswith("sonnet") else SINGLE_MAX_COST
            cfgs.append(experiment(
                f"p0_calib_{ref}", SINGLE, tasks, ref, pr["p0_calib"], limit=5, max_usd=0.25, chunk=5,
                exp=expect(a.max_unparsed, 1000, False, cost),
                note=f"P0 calibration: the single agent on calibration items 0-4 with model ref {ref}.\n"
                     "Measures hidden thinking/reasoning tokens, stop reasons, prompt-token estimate error, latency and\n"
                     "rate limits (python -m analysis.calibration; status.json). 5 calls: read by hand, no early stop."))
        cfgs.append(experiment(
            f"p0_dense_{a.ref}", DENSE, tasks, a.ref, pr["p0_dense"], limit=2, max_usd=0.25, chunk=2,
            exp=expect(a.max_unparsed, 1000, False, c),
            note="P0 calibration: the dense network on calibration items 0-1 with the chosen ref, for stop reasons at\n"
                 "the amendment 6 caps (1600 tokens in every stage), per-stage output tokens and latency (they size P4: amendment 3, rule 20)."))
        cfgs += [
            experiment(f"p2_{a.short}_single", SINGLE, tasks, a.ref, pr["p2_probe"], limit=20, max_usd=0.5,
                       exp=expect(a.max_unparsed, 10, False, SINGLE_MAX_COST), note="P2 gate probe: single agent on calibration items 0-19."),
            experiment(f"p2_{a.short}_dense", DENSE, tasks, a.ref, pr[a.probe_prereg], limit=20, max_usd=2.5,
                       exp=expect(a.max_unparsed, 10, True, c), note="P2 gate probe: dense 3x6+1 on calibration items 0-19."),
            experiment(f"p3_{a.short}_single", SINGLE, tasks, a.ref, pr["p3_gate"], limit=60, max_usd=0.5,
                       exp=expect(a.max_unparsed, 10, False, SINGLE_MAX_COST),
                       note="P3 gate confirm: single agent on items 0-59 (0-19 from cache; validation 20-59 new).\n"
                            "Run with --task-limit 40 first for the futility check (amendment 3, rule 19)."),
            experiment(f"p3_{a.short}_dense", DENSE, tasks, a.ref, pr["p3_gate"], limit=40, max_usd=4.0,
                       exp=expect(a.max_unparsed, 10, True, c),
                       note="P3 gate confirm, slice 1: dense on items 0-39 (0-19 from cache; validation 20-39 new).\n"
                            "The futility check (rule 19) reads 20-39. The gate is judged on validation 20-59 only, with\n"
                            "slice 2 (p3_<cand>_dense_b, 40-59) in its own results directory (audit 15)."),
            experiment(f"p3_{a.short}_dense_b", DENSE, tasks, a.ref, pr["p3_gate"], offset=40, limit=20, max_usd=4.0,
                       exp=expect(a.max_unparsed, 10, True, c),
                       note="P3 gate confirm, slice 2: dense on validation 40-59, run only if the futility check passes.\n"
                            "Its own results directory; analysis/gate.py combines the slices (audit 15)."),
            experiment(f"p3_{a.short}_single_sonnet", SINGLE_SONNET, tasks, None, pr["p3_single_sonnet"], offset=20,
                       limit=40, max_usd=2.0, exp=expect(a.max_unparsed, 10, False, a.sonnet_max_cost),
                       note="P3 matched-cost senior control: one Sonnet 5.5 call (sonnet_nothink) per task on validation 20-59\n"
                            "(amendment 3, rule 18). No model override: the network names its own ref."),
            experiment(f"p3w_{a.short}_single", SINGLE, tasks, a.ref, pr["p3w_gate"], offset=100, limit=20, max_usd=0.5,
                       exp=expect(a.max_unparsed, 10, False, SINGLE_MAX_COST),
                       note="P3 gate widening, run only under amendment 2, rule 12: single on validation 100-119\n"
                            "(amendment 3, rule 23). With it, the gate is judged on validation 20-59 + 100-119 (analysis/gate.py)."),
            experiment(f"p3w_{a.short}_dense", DENSE, tasks, a.ref, pr["p3w_gate"], offset=100, limit=20, max_usd=2.5,
                       exp=expect(a.max_unparsed, 10, True, c),
                       note="P3 gate widening, run only under amendment 2, rule 12: dense on validation 100-119\n"
                            "(amendment 3, rule 23: 60-99 stays clean for P4's held-out half)."),
            experiment(f"p3_{a.short}_noise", DENSE, tasks, a.ref, pr["p3_noise"], offset=20, limit=10, replicates=2,
                       max_usd=2.0, chunk=5, exp=expect(a.max_unparsed, 5, False, c),
                       note="P3 noise: dense on validation 20-29 twice (replicate 0 from cache, replicate 1 new).\n"
                            "There is no temperature setting, so run-to-run noise is measured, not fixed."),
        ]
        size = a.p4_part_size
        n_parts = 80 // size
        for i in range(n_parts):
            lo, hi = 20 + size * i, 20 + size * (i + 1) - 1
            half = "search" if i < n_parts // 2 else "held-out"
            cfgs.append(experiment(
                f"p4_{a.short}_grid_{LETTERS[i]}", DENSE, tasks, a.ref, pr["p4_grid"], offset=lo, limit=size,
                configs={"levels": [1, 3, 6]}, max_usd=4.0, chunk=max(1, size // 2), concurrency=a.p4_concurrency,
                exp=expect(a.max_unparsed, max(1, size // 2), False, c),
                note=f"P4 factorial landscape part {LETTERS[i]} ({half} half): levels 1/3/6 per stage, 27 configs,\n"
                     f"105 calls per task, on validation {lo}-{hi}. The first half of the parts is the search half\n"
                     "(20-59), the rest is held out (60-99). Dense calls on 20-59 come from the P3 cache; on 60-99 they are\n"
                     "new. Part size and concurrency are set from P0's rate limits (amendment 3, rule 20)."))
        cfgs.append(experiment(
            f"p4_{a.short}_single_held", SINGLE, tasks, a.ref, pr["p4_single_held"], offset=60, limit=40, max_usd=0.5,
            exp=expect(a.max_unparsed, 10, False, SINGLE_MAX_COST),
            note="P4 held-out control: the single Haiku agent on validation 60-99, so every held-out pick and design is\n"
                 "compared with the single agent on the same items (H4; research/designs.md)."))
        cfgs.append(experiment(
            f"p4_{a.short}_single_sonnet_held", SINGLE_SONNET, tasks, None, pr["p4_sonnet_held"], offset=60, limit=40,
            max_usd=2.0, exp=expect(a.max_unparsed, 10, False, a.sonnet_max_cost),
            note="P4 held-out senior control: one Sonnet 5.5 call (sonnet_nothink) per task on validation 60-99, the\n"
                 "same items as P4's held-out picks (plan rule 63; Kevin). No model override: the network names its own ref."))
        for suffix, lo in [("", 60), ("_b", 80)]:
            cfgs.append(experiment(
                f"p4b_{a.short}_judge_cascade{suffix}", CASCADE, tasks, a.ref, pr["p4b_cascade"], offset=lo, limit=20,
                max_usd=4.0, chunk=10, exp=expect(a.max_unparsed, 10, False, a.cascade_max_cost),
                note=f"P4b live design: judge_cascade on held-out validation {lo}-{lo + 19} (two slices, each in its own\n"
                     "results directory; audit 15). Proposers are identical to the dense run's (cached); exits on\n"
                     "5-of-6 agreement; the aggregator escalates to sonnet_nothink below 1/2."))
        cfgs.append(experiment(
            f"p5_{a.short}_transfer", DENSE, tasks, "luna_low", pr["p5_transfer"], offset=60, limit=10, chunk=5,
            configs=[[6, 3, 3, 1], [3, 3, 3, 1], [1, 1, 1, 1]], max_usd=1.5, exp=expect(a.max_unparsed, 5, False, c),
            note="P5 transfer smoke: dense + 3 pruned configs on luna_low (GPT-6 Luna, low reasoning), held-out items\n"
                 "60-69 (picks are made on the search half). PLACEHOLDER configs on the 1/3/6 grid: replace them with\n"
                 "P4's joint pick, stage-by-stage pick and best uniform, then re-estimate and dry-run."))
    for cfg in cfgs:
        print(write(cfg).relative_to(ROOT))


if __name__ == "__main__":
    main()
