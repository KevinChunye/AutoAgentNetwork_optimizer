"""Power of the pre-registered tests, by simulation on the synthetic world (world.py).

For each test, a world where its hypothesis is true ("alternative") and a world where it is false ("null") are drawn
R times (salts power-0, power-1, ...), each with the stage-1 design: 363 items (200 BBEH, 63 math, 100 code), 36
configs, k = 6, the 9B BF16 4k judge. Power = the share of alternative draws in which the test concludes as
pre-registered ("supported"); false-positive rate = the same share under the null. A test whose power is below 0.70 is
demoted to exploratory in the prereg (Kevin's rule); audit T1-1 asks for 0.80, a false-positive rate of at most 0.05
and a 95% half-width of at most 3 points, and the prereg flags every test that misses any of these.

After the pilot, `--calibrate results/testbed/pilot` fits the default world's ability, thinking gain and W4 shift to
the pilot's accuracies (world_calibrated.json); every world below then starts from that calibration.

Worlds (WorldParams changes from the default):
  default      as shipped (or calibrated): W4 shift 0.12 x sqrt(4 / size), larger on hard items (kappa 0.6), plus an item-specific
               shock of spread 0.3 fixed per checkpoint (shared by all its samples); judge skill d' falls with
               difficulty (coupling 0.6); wrong answers share one attractor per item.
  strong       W4 shift 0.35, kappa 1.5, shock 0.5: quantization hurts hard items a lot.
  pure_shift   no item-specific W4 shock (shift only): null for T1's shared-shock test (exploratory).
  diversify    the W4 shock drawn per sample instead of per checkpoint: a second null for the shared shock.
  flat_shift   no W4 shock and kappa 0: the W4 loss is the same on every item: null for T1's concentration.
  no_w4_loss   W4 identical to BF16: null for T1's gap_persists and T2.
  flat_judge   judge coupling 0 (constant d'): null for T4.
  config_judge judge coupling 0, d' set by the size of the model that wrote the candidates (3 / 2 / 1 for 2B / 4B /
               9B): a second null for T4, in which skill varies by config but not by difficulty (audit T1-2).
  misspecified each checkpoint has its own attractor (wrong answers not shared across models): null for T5.
  bench_judge  judge coupling 0, d' set by the benchmark (2.5 / 2.0 / 1.0 for BBEH / code / math) and benchmarks far
               apart in difficulty (means 0 / 0.8 / 2.0): a third null for T4 (audit T1-3).
  default_k5, misspecified_k5   the same two with 5 answer classes instead of 10 (audit T1-2: the T5 bar must hold
               across answer-space sizes; with 2 classes the baseline equals the model, so T5 is never supported).
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from multiprocessing import Pool as Processes
from pathlib import Path

import numpy as np
import pandas as pd

from . import analysis, compose, grid
from .world import World, WorldParams

ITEMS = {"bbeh": 200, "math": 63, "code": 100}  # the stage-1 design (363 items)
GRADERS = {"bbeh": "exact", "math": "exact", "code": "exact"}
JUDGE = grid.Config(grid.QWEN, 9, "bf16", 4096)


CALIBRATED_JSON = Path(__file__).resolve().parents[2] / "research/v4/testbed/world_calibrated.json"


def calibrate(pilot: pd.DataFrame, grid_a0=np.arange(-1.5, 1.51, 0.25), grid_gamma=np.arange(0.0, 3.01, 0.5),
              grid_delta=np.arange(0.0, 0.81, 0.1), items: int = 363) -> dict:
    """WorldParams a0 (ability), gamma (thinking gain) and the W4 shift that best reproduce the pilot's mean
    accuracy of its four configs (4B BF16 / W4 x thinking off / 1k): least squares over a grid. Only these three are
    identified by the pilot; every other parameter keeps its literature prior."""
    target = pilot.groupby("system")["correct"].mean().astype(float)
    configs = [grid.Config.from_label(system) for system in target.index]
    best, best_err = None, np.inf
    for a0 in grid_a0:
        for gamma in grid_gamma:
            for delta in grid_delta:
                params = replace(WorldParams(), a0=float(a0), gamma=float(gamma),
                                 delta={**WorldParams().delta, "w4": float(delta)})
                acc = World(items, params, salt="calibrate").table(configs, 6).groupby("system")["correct"].mean()
                err = float(((acc.reindex(target.index) - target) ** 2).sum())
                if err < best_err:
                    best, best_err = {"a0": float(a0), "gamma": float(gamma), "delta_w4": float(delta)}, err
    return {**best, "squared_error": best_err, "target": target.round(4).to_dict()}


def base_params() -> WorldParams:
    """The default world: the shipped priors, or the pilot calibration when world_calibrated.json exists."""
    base = WorldParams()
    if CALIBRATED_JSON.exists():
        import json

        c = json.loads(CALIBRATED_JSON.read_text())
        base = replace(base, a0=c["a0"], gamma=c["gamma"], delta={**base.delta, "w4": c["delta_w4"]})
    return base


def worlds() -> dict[str, WorldParams]:
    base = base_params()
    no_shock = {**base.sigma_q, "w4": 0.0}
    return {
        "default": base,
        "strong": replace(base, delta={**base.delta, "w4": 0.35}, sigma_q={**base.sigma_q, "w4": 0.5}, kappa=1.5),
        "pure_shift": replace(base, sigma_q=no_shock),
        "diversify": replace(base, diversify=True),
        "flat_shift": replace(base, sigma_q=no_shock, kappa=0.0),
        "no_w4_loss": replace(base, sigma_q=no_shock, delta={**base.delta, "w4": 0.0}),
        "flat_judge": replace(base, judge_coupling=0.0),
        "config_judge": replace(base, judge_coupling=0.0, judge_d_by_size={2: 3.0, 4: 2.0, 9: 1.0}),
        "bench_judge": replace(base, judge_coupling=0.0, judge_d_by_bench={"bbeh": 2.5, "code": 2.0, "math": 1.0},
                               bench_mean={"bbeh": 0.0, "code": 0.8, "math": 2.0}),
        "misspecified": replace(base, attractor_by_checkpoint=True),
        "default_k5": replace(base, n_classes=5),
        "misspecified_k5": replace(base, n_classes=5, attractor_by_checkpoint=True),
    }


# test -> (alternative world, null worlds)
TESTS = {
    "T1 primary: the W4 deficit survives 6 votes on the hard third": ("default", ("no_w4_loss",)),
    "T1 secondary: shared W4 shock (1 - disattenuated r) > 0": ("default", ("pure_shift", "diversify")),
    "T1 secondary: W4 loss concentrated on the hard third": ("default", ("flat_shift",)),
    "T1 literal: 6 x W4 vote < 1 x BF16, hard third (counts if gap persists)": ("strong", ("default",)),
    "T2 primary: 4 x W4 vote vs 1 x BF16 (two-sided)": ("default", ("no_w4_loss",)),
    "T3 primary: deep single vs cost-matched wide vote (two-sided)": ("default", ()),
    "T4 primary: judge eta easy - hard within config, benchmark and right candidates > 0 (99%)": ("default", ("flat_judge", "config_judge",
                                                                                          "bench_judge")),
    "T5 primary: factor MAE < bar x baseline MAE": ("default", ("misspecified", "misspecified_k5")),
    "T5 primary (5 answer classes)": ("default_k5", ()),
}
T1_WORLDS = {"default", "strong", "pure_shift", "diversify", "flat_shift", "no_w4_loss"}


def _res(result: dict) -> tuple:
    """(supported, estimate, half-width of the 95% interval)."""
    return result["supported"], result["estimate"], (result["high"] - result["low"]) / 2


def one(args) -> dict:
    """The tests that `world` is used for, on draw r."""
    name, r, t5, only_t5, only_t4 = (*args, False, False)[:5]
    w = World(ITEMS, worlds()[name], salt=f"power-{r}")
    T = compose.add_classes(w.table(grid.stage1([]), 6), GRADERS)
    out = {"world": name, "r": r}
    if name in T1_WORLDS and not (only_t5 or only_t4):
        s = compose.Samples.from_table(T)
        r1 = analysis.t1(T, s, n_boot=500)
        out["T1 primary: the W4 deficit survives 6 votes on the hard third"] = _res(r1["gap_persists"])
        out["T1 secondary: shared W4 shock (1 - disattenuated r) > 0"] = _res(r1["shared_shock"])
        out["T1 secondary: W4 loss concentrated on the hard third"] = _res(r1["concentration"])
        out["T1 literal: 6 x W4 vote < 1 x BF16, hard third (counts if gap persists)"] = _res(r1["literal"])
        if name in ("default", "no_w4_loss"):
            out["T2 primary: 4 x W4 vote vs 1 x BF16 (two-sided)"] = _res(analysis.t2(T, s)["primary"])
        if name == "default":
            out["T3 primary: deep single vs cost-matched wide vote (two-sided)"] = _res(analysis.t3(T, s)["primary"])
    if name in ("default", "flat_judge", "config_judge", "bench_judge") and not only_t5:
        sub = T[T["precision"].isin(["bf16", "w4"])]
        checks, picks = w.checks(sub, JUDGE)
        out["T4 primary: judge eta easy - hard within config, benchmark and right candidates > 0 (99%)"] = _res(
            analysis.t4(sub, checks, picks, [JUDGE.label])["primary"])
    if t5 and not only_t4:
        items = np.array(sorted(T["item"].unique()))
        perm = np.random.default_rng(r).permutation(items)
        cut = int(0.7 * len(items))
        p5 = analysis.t5(T, list(perm[:cut]), list(perm[cut:]), escalate=JUDGE.label, draws=200)["primary"]
        name5 = "T5 primary (5 answer classes)" if name == "default_k5" else "T5 primary: factor MAE < bar x baseline MAE"
        out[name5] = (p5["supported"], p5["mae_ratio"], p5["mae"])
        out["T5 share within 3 points"] = p5["share_within"]
    return out


DRAWS = Path(__file__).resolve().parents[2] / "runs/testbed/power_draws.jsonl"


def run(reps: int = 100, t5_reps: int = 40, processes: int = 4, only_t5: bool = False,
        draws_path: Path = DRAWS, only_t4: bool = False, summarize_only: bool = False) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Every draw is appended to draws_path as it finishes, and draws already there are not redone, so an interrupted
    run resumes where it stopped. Delete draws_path (or the affected lines) after changing a test's code."""
    import json

    if only_t5:
        jobs = [(w, r, True, True) for w in ("default", "misspecified") for r in range(t5_reps)]
    elif only_t4:
        jobs = [(w, r, False, False, True) for w in ("default", "flat_judge", "config_judge", "bench_judge")
                for r in range(reps)]
    else:
        jobs = [("default", r, r < t5_reps) for r in range(reps)]
        jobs += [(w, r, False) for w in ("strong", "pure_shift", "diversify", "flat_shift", "no_w4_loss")
                 for r in range(reps)]
        jobs += [(w, r, False, False, True) for w in ("flat_judge", "config_judge", "bench_judge") for r in range(reps)]
        jobs += [("default_k5", r, True, True) for r in range(t5_reps)]
        jobs += [(w, r, True, True) for w in ("misspecified", "misspecified_k5") for r in range(reps)]
    draws_path.parent.mkdir(parents=True, exist_ok=True)
    done = [json.loads(x) for x in draws_path.read_text().splitlines()] if draws_path.exists() else []
    key = lambda j: f"{j[0]}|{j[1]}|{'t4' if len(j) > 4 and j[4] else 't5' if len(j) > 3 and j[3] else 'all'}"
    have = {d["key"] for d in done}
    todo = [] if summarize_only else [j for j in jobs if key(j) not in have]
    with Processes(processes) as pool, draws_path.open("a") as f:
        for job, res in zip(todo, pool.imap(one, todo, chunksize=1)):
            f.write(json.dumps({"key": key(job), **res}, default=bool) + "\n")
            f.flush()
    results = [json.loads(x) for x in draws_path.read_text().splitlines()]
    rows = []
    for res in results:
        for test, value in res.items():
            if test not in TESTS:
                continue
            supported = bool(value[0])
            if test.startswith("T5"):  # judged at the current bar, from the stored MAE ratio
                supported = bool(value[1] < analysis.T5_MAX_RATIO)
            rows.append({"test": test, "world": res["world"], "r": res["r"], "supported": supported,
                         "estimate": value[1], "spread": value[2]})
    long = pd.DataFrame(rows)
    out = []
    for test, (alt, nulls) in TESTS.items():
        for world, role in [(alt, "power")] + [(n, "false_positive") for n in nulls]:
            part = long[(long["test"] == test) & (long["world"] == world)]
            if part.empty:
                continue
            out.append({"test": test, "role": role, "world": world, "draws": len(part),
                        "rate": part["supported"].mean(), "mean_estimate": part["estimate"].mean(),
                        "mean_halfwidth_or_mae": part["spread"].mean()})
    ratios = pd.DataFrame([{"world": r["world"], "ratio": v[1]} for r in results for k, v in r.items()
                           if k.startswith("T5 primary")])
    if not ratios.empty:  # the largest bar keeping false positives at or below 0.05 in every misspecified world
        nulls = ratios[ratios["world"].str.startswith("misspecified")]
        bar = nulls.groupby("world")["ratio"].quantile(0.05).min()
        print(f"T5: largest bar with <= 5% false positives in every null world: {bar:.3f} "
              f"(current T5_MAX_RATIO {analysis.T5_MAX_RATIO}); ratio quantiles by world:")
        print(ratios.groupby("world")["ratio"].describe(percentiles=[0.05, 0.5, 0.95]).round(3).to_string())
    shares = pd.DataFrame([{"world": r["world"], "share_within_3": r["T5 share within 3 points"]}
                           for r in results if "T5 share within 3 points" in r])
    return pd.DataFrame(out), shares


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--reps", type=int, default=100)
    parser.add_argument("--t5-reps", type=int, default=40)
    parser.add_argument("--processes", type=int, default=4)
    parser.add_argument("--out", default="research/v4/testbed/power.csv")
    parser.add_argument("--only-t5", action="store_true", help="run only the T5 draws")
    parser.add_argument("--only-t4", action="store_true", help="run only the T4 draws (after deleting stale T4 results)")
    parser.add_argument("--summarize", action="store_true", help="summarize the stored draws without running any")
    parser.add_argument("--calibrate", help="a pilot results folder: fit the world to it first (world_calibrated.json)")
    args = parser.parse_args()
    if args.calibrate:
        import json

        from .sample import read_table

        fitted = calibrate(read_table(Path(args.calibrate)))
        CALIBRATED_JSON.write_text(json.dumps(fitted, indent=2))
        print("calibrated:", fitted)
    table, shares = run(args.reps, args.t5_reps, args.processes, args.only_t5, only_t4=args.only_t4,
                        summarize_only=args.summarize)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(args.out, index=False)
    print(table.to_string(index=False))
    if not shares.empty:
        print(shares.groupby("world")["share_within_3"].describe().to_string())


if __name__ == "__main__":
    main()
