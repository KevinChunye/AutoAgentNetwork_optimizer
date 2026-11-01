"""Phase 3A of the evidence plan (exploratory, $0): pruning agent networks by information per dollar, on
calls already paid for. Writes research/v3/pruning/phase3a.md, its tables (reports/v3/pruning/tables/) and
figures (reports/v3/pruning/, vector PDF and PNG).

Data (results/*/results.csv, tracked in git):
  (a) the staged grid  p4_bbeh_grid_a..p: the pilot's 27 Haiku designs propose -> critique -> refine ->
      aggregate, each stage keeping 1, 3 or 6 agents, one answer per design on "the 80" BBEH items
      (positions 20-99). A design is only known where it was run: comparisons are between whole grid points.
  (b) the flat panel   5 Haiku calls (w0_haiku5, replicates 0-4) + 1 Sonnet call (p3_bbeh_single_sonnet,
      p4_bbeh_single_sonnet_held) on the same 80 items: 6 units, so every one of its 63 sub-networks is
      replayed exactly.

Definitions (as in autoagentnet/pruning/; plain words there):
  accuracy      share of items whose final answer is right.
  dollars       mean cost per item, as billed (cache-aware list price).
  folds         two halves of the 80 items, balanced within each of the four BBEH tasks (seed 0). A search runs
                on one half (the search half) and is scored on the other (held out); "cross-fitted" numbers
                score every item once, by the network the other half chose, and average the two directions.
  frontier      the best accuracy at each cost or less among all networks evaluated the same way (an oracle
                that has seen the held-out half); regret = frontier accuracy at a network's cost minus its own.
  intervals     95%, resampling items (2,000 draws, seed 0); paired differences resample the per-item
                difference. With 80 items one item is 1.25 points, and every interval below is wide.
  extra call    one more Haiku agent call per item. "Points per extra call" divides an accuracy change by the
                number of calls it took.
  independent-call equivalent  the number of independent calls a set of m correlated calls is worth,
                n_eff(m) = m / (1 + (m - 1) rho), with rho the pairwise correlation of the calls' correctness
                (the variance of a mean of m equally correlated votes). For the staged grid, rho is taken
                from the designs' pairwise correctness correlation (finding 3b, phi 0.65) as a model-based
                translation, not a measurement of the calls inside a design.

Usage: python -m analysis.pruning_phase3a
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analysis.common import color, save_figure, style
from analysis.evidence_cached import GRID, SONNET_HALVES, read
from autoagentnet.evidence import correlation as R
from autoagentnet.evidence.calibration import two_folds
from autoagentnet.evidence.inference import bootstrap
from autoagentnet.pruning import criteria as Cr
from autoagentnet.pruning import search as S
from autoagentnet.pruning.replay import REFITS, Grid, Panel, fit, groups, predict, replay

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v3/pruning/phase3a.md"
FIGURES = ROOT / "reports/v3/pruning"
TABLES = FIGURES / "tables"
STEP = 0.0005  # NetAdapt's cut per step, dollars per item (the plan's value)
DENSE_K = "dense refit (6 calls, Kevin's aggregator)"
S1_LABEL = "S1 sensitivity (per-source curves, threshold)"
TAUS = [0.4, 0.5, 0.6, 0.65, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.01]  # 1.01 = never stop early
N_BOOT = 2000


def md(frame: pd.DataFrame, digits: int = 3) -> str:
    """A markdown table; floats rounded to `digits`."""
    def cell(v):
        if isinstance(v, (float, np.floating)):
            return "" if np.isnan(v) else f"{v:.{digits}f}"
        return str(v)
    lines = ["| " + " | ".join(map(str, frame.columns)) + " |", "|" + "---|" * len(frame.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join(lines)


def ci(values, n_boot: int = N_BOOT) -> tuple[float, float, float]:
    """(mean, lo, hi) of per-item values over an item bootstrap."""
    x = np.asarray(values, dtype=float)
    b = bootstrap(lambda idx: float(x[idx].mean()), len(x), n_boot=n_boot)
    return b["estimate"], b["lo"], b["hi"]


def fmt_ci(t: tuple, scale: float = 100.0, digits: int = 1) -> str:
    return f"{t[0] * scale:+.{digits}f} ({t[1] * scale:+.{digits}f} to {t[2] * scale:+.{digits}f})"


def fmt_acc(t: tuple) -> str:
    return f"{t[0] * 100:.1f} ({t[1] * 100:.1f}-{t[2] * 100:.1f})"


# ---------------------------------------------------------------------------------------------------------
# data

def load_grid() -> Grid:
    return Grid.from_results(pd.concat([read(r) for r in GRID]))


def flat_calls() -> pd.DataFrame:
    sonnet = pd.concat([read(r) for r in SONNET_HALVES])
    items = sonnet["task_id"].tolist()
    haiku = read("w0_haiku5")
    haiku = haiku[haiku["task_id"].isin(set(items))].assign(source="haiku", call=lambda d: d["replicate"])
    sonnet = sonnet.assign(source="sonnet", call=0)
    calls = pd.concat([haiku, sonnet])[["task_id", "source", "call", "answer", "parsed", "correct", "cost_usd",
                                         "critical_path_s", "total_tokens"]]
    calls = calls.rename(columns={"task_id": "item", "critical_path_s": "seconds", "total_tokens": "tokens"})
    order = {item: k for k, item in enumerate(items)}
    return calls.assign(pos=calls["item"].map(order)).sort_values(["pos", "source", "call"], kind="stable").drop(columns="pos")


def task_of(items) -> np.ndarray:
    return np.array([i.split("-")[1] for i in items])


# ---------------------------------------------------------------------------------------------------------
# (a) the staged grid

def grid_part(grid: Grid, folds: np.ndarray, flat_points: dict) -> dict:
    items = grid.items
    t = grid.table
    wide = t.pivot(index="item", columns="design", values="correct").reindex(items)
    pts = grid.points()
    pts["regret"] = S.regret(pts, S.pareto(pts, score="accuracy"), score="accuracy")
    acc_ci = {d: ci(wide[d]) for d in wide.columns}
    pts["acc_lo"] = pts["design"].map(lambda d: acc_ci[d][1])
    pts["acc_hi"] = pts["design"].map(lambda d: acc_ci[d][2])
    pts["calls"] = pts["propose"] + pts["critique"] + pts["refine"] + 1

    # stage sensitivity from the full design (6-6-6), paired per item
    full = "k6-6-6-1"
    sens = S.grid_sensitivity(grid, items)
    sens["diff_ci"] = [fmt_ci(ci(wide[d] - wide[full])) for d in sens["design"]]
    sens["points_per_extra_call"] = 100 * -sens["d_accuracy"] / (6 - sens["level"])

    # main effect per extra call of each stage: level 6 minus level 1, averaged over the other stages' 9 settings
    effects = []
    for s in grid.stages:
        others = [o for o in grid.stages if o != s]
        lo = t[t[s] == 1].pivot_table(index="item", columns=others, values="correct").reindex(items)
        hi = t[t[s] == 6].pivot_table(index="item", columns=others, values="correct").reindex(items)
        per_item = (hi.to_numpy() - lo.to_numpy()).mean(axis=1) / 5
        est = ci(per_item)
        effects.append({"stage": s, "points per extra call": fmt_ci(est), "estimate": est[0] * 100,
                        "dollars per extra call": (t[t[s] == 6]["dollars"].mean() - t[t[s] == 1]["dollars"].mean()) / 5})
    effects = pd.DataFrame(effects)

    # pooled slope: accuracy points per extra call over all 27 designs (least squares on calls), item bootstrap
    calls = pts.set_index("design").loc[wide.columns, "calls"].to_numpy(dtype=float)
    W = wide.to_numpy(dtype=float)

    def slope(idx):
        acc = W[idx].mean(axis=0)
        return float(np.polyfit(calls, acc, 1)[0])

    pooled = bootstrap(slope, len(items), n_boot=N_BOOT)
    phi_designs = R.mean_pairwise(W)["phi"]
    n_eff = {m: m / (1 + (m - 1) * phi_designs) for m in (4, 19)}
    neff_per_call = (n_eff[19] - n_eff[4]) / 15

    # NetAdapt over stage levels, the S1-style sensitivity path, and exhaustive picks: search half -> held-out
    def s1_grid_path(search_items):
        """S1 on the grid: from the full design, apply one-stage moves in the order of the one-at-a-time
        sensitivity table (smallest predicted loss per dollar saved first), never re-measuring."""
        table = S.grid_sensitivity(grid, search_items)
        table["loss_per_dollar"] = -table["d_accuracy"] / -table["d_dollars"]
        moves = table.sort_values(["level", "loss_per_dollar"], ascending=[False, True], kind="stable")
        levels = {s: 6 for s in grid.stages}
        path = [grid.design_of([6, 6, 6])]
        for _, mv in moves.sort_values("loss_per_dollar", kind="stable").iterrows():
            if mv["level"] < levels[mv["stage"]]:
                levels[mv["stage"]] = mv["level"]
                path.append(grid.design_of([levels[s] for s in grid.stages]))
        for s in grid.stages:  # finish at the cheapest design
            if levels[s] > 1:
                levels[s] = 1
                path.append(grid.design_of([levels[s] for s in grid.stages]))
        return path

    budgets = [0.004, 0.005, 0.006, 0.007, 0.008, 0.009, 0.010, 0.0115]
    regret_rows, paths = [], {}
    item_arr = np.array(items)
    for k, (sr, er) in enumerate(S.directions(folds)):
        s_items, e_items = item_arr[sr], item_arr[er]
        s_pts = grid.points(s_items).set_index("design")
        e_pts = grid.points(e_items).set_index("design")
        e_front = S.pareto(e_pts.reset_index(), score="accuracy")
        na = S.grid_netadapt(grid, s_items, STEP)
        s1 = s1_grid_path(s_items)
        paths[k] = {"netadapt": na["design"].tolist(), "s1": s1}
        for b in budgets:
            fits = s_pts[s_pts["dollars"] <= b + 1e-12]
            picks = {
                "exhaustive (search half)": fits["accuracy"].idxmax() if len(fits) else None,
                "NetAdapt": next((d for d in na["design"] if s_pts.loc[d, "dollars"] <= b + 1e-12), None),
                "S1 sensitivity": next((d for d in s1 if s_pts.loc[d, "dollars"] <= b + 1e-12), None),
            }
            for method, d in picks.items():
                if d is None:
                    continue
                row = e_pts.loc[d]
                regret_rows.append({"direction": k, "budget": b, "method": method, "design": d,
                                    "held_out_accuracy": row["accuracy"], "dollars": row["dollars"],
                                    "regret": float(S.frontier_at(e_front, [row["dollars"]], score="accuracy")[0] - row["accuracy"])})
    regrets = pd.DataFrame(regret_rows)
    regret_summary = (regrets.groupby("method")
                      .agg(mean_regret=("regret", "mean"), max_regret=("regret", "max"), picks=("regret", "size"))
                      .reset_index().sort_values("mean_regret", kind="stable"))
    na_full = S.grid_netadapt(grid, items, STEP)
    seconds_path = S.grid_netadapt(grid, items, 1.0, resource="seconds")
    return {"points": pts, "sens": sens, "effects": effects, "pooled": pooled, "phi_designs": phi_designs,
            "n_eff": n_eff, "neff_per_call": neff_per_call, "regrets": regrets, "regret_summary": regret_summary,
            "netadapt": na_full, "netadapt_seconds": seconds_path, "paths": paths, "flat": flat_points, "wide": wide}


# ---------------------------------------------------------------------------------------------------------
# (b) the flat panel

def oof_correct(panel: Panel, kept_by_direction: list, folds: np.ndarray, refit: str = "ridge") -> np.ndarray:
    """Per item: correctness of the network chosen on the other half (fitted there), scored on this half."""
    out = np.full(panel.n, np.nan)
    dollars = np.full(panel.n, np.nan)
    for (sr, er), kept in zip(S.directions(folds), kept_by_direction):
        frame = replay(panel, kept, er, fit(panel, kept, sr, refit))
        out[er] = frame["correct"].to_numpy()
        dollars[er] = frame["dollars"].to_numpy()
    return out, dollars


def path_masks(panel: Panel, path: pd.DataFrame) -> list[np.ndarray]:
    return [panel.mask(k.split("+")) for k in path["kept"]]


def flat_part(panel: Panel, folds: np.ndarray) -> dict:
    out: dict = {}
    units = groups(panel, "unit")
    sources = groups(panel, "source")
    sonnet = int(np.flatnonzero(panel.units["unit"] == "sonnet:0")[0])
    haiku = list(np.flatnonzero(panel.units["source"] == "haiku"))
    dirs = S.directions(folds)

    # reference points (per item, all 80)
    Zc = panel.correct_matrix()
    single = pd.DataFrame({"unit": panel.units["unit"], "accuracy": Zc.mean(axis=0), "dollars": panel.mean_cost()})
    vote5 = predict(panel, S.mask_of(panel, haiku))["correct"].to_numpy()
    refs = {"Sonnet (1 call)": (Zc[:, sonnet], panel.cost[:, sonnet]),
            "Haiku, 1 call (mean of 5)": (Zc[:, haiku].mean(axis=1), panel.cost[:, haiku].mean(axis=1)),
            "Haiku 5-call vote": (vote5, panel.cost[:, haiku].sum(axis=1)),
            "dense vote (6 calls)": (predict(panel, panel.all_units())["correct"].to_numpy(), panel.cost.sum(axis=1))}
    dense_refit, dense_d = oof_correct(panel, [panel.all_units()] * 2, folds)
    refs["dense refit (6 calls, Kevin's aggregator)"] = (dense_refit, dense_d)
    dense_w, dense_wd = oof_correct(panel, [panel.all_units()] * 2, folds, "weights")
    refs["dense weighted vote (6 calls)"] = (dense_w, dense_wd)
    for k in (3, 4, 5):
        c = S.h7_cascade(panel, haiku, sonnet, k)
        refs[f"Haiku cascade, escalate if < {k} of 5 agree"] = (c["correct"].to_numpy(), c["dollars"].to_numpy())
    out["refs"] = refs
    out["single"] = single
    out["panel"] = panel
    out["sonnet_by_half"] = [float(Zc[sr, sonnet].mean()) for sr, er in dirs]

    # criteria on all 80 (descriptive), unit and source granularity
    out["criteria_unit"] = Cr.all_criteria(panel, panel.all_units(), units)
    out["criteria_source"] = Cr.all_criteria(panel, panel.all_units(), sources)

    # exhaustive: 63 sub-networks (every subset of calls), each direction, every refit; and the 11 call-count
    # vectors (S4 proper: calls within a source are exchangeable)
    ex = []
    for k, (sr, er) in enumerate(dirs):
        for refit in REFITS:
            ex.append(S.s4_exhaustive(panel, units, sr, er, refit).assign(direction=k, refit=refit))
    counts = pd.concat([S.s4_counts(panel, sources, sr, er).assign(direction=k) for k, (sr, er) in enumerate(dirs)])
    out["counts"] = (counts.groupby("counts").agg(score=("score", "mean"), dollars=("dollars", "mean"),
                                                   tokens=("tokens", "mean"), seconds=("seconds", "mean")).reset_index()
                     .sort_values("dollars", kind="stable"))
    count_fronts = {k: S.pareto(counts[counts["direction"] == k]) for k in range(len(dirs))}
    out["front_counts"] = S.pareto(out["counts"])
    out["s1_curves"] = S.s1_curves(panel, sources, np.arange(panel.n))
    ex = pd.concat(ex, ignore_index=True)
    out["exhaustive"] = ex
    cross = (ex.groupby(["refit", "kept"]).agg(score=("score", "mean"), dollars=("dollars", "mean"),
                                                n_units=("n_units", "first")).reset_index())
    out["cross"] = cross
    out["refit_summary"] = (cross.groupby("refit").agg(mean_accuracy=("score", "mean"), best=("score", "max"))
                            .reset_index().sort_values("mean_accuracy", ascending=False, kind="stable"))
    fronts = {k: S.pareto(ex[(ex["direction"] == k) & (ex["refit"] == "ridge")]) for k in range(len(dirs))}
    out["front_fold0"] = fronts[0]
    out["front_cross"] = S.pareto(cross[cross["refit"] == "ridge"])
    out["front_cross_weights"] = S.pareto(cross[cross["refit"] == "weights"])
    seconds = (ex[ex["refit"] == "ridge"].groupby("kept").agg(score=("score", "mean"), seconds=("seconds", "mean"))
               .reset_index())
    out["front_seconds"] = S.pareto(seconds, cost="seconds")

    # pruning paths (Kevin's aggregator, refitted), each direction; regret against that direction's frontier
    methods = {"S1 sensitivity (per-source curves, threshold)": lambda sr, er: S.s1_sensitivity(panel, sources, sr, er)}
    for name, fn in Cr.CRITERIA.items():
        for iterative in (False, True):
            label = f"{name} {'iterative' if iterative else 'one-shot'}"
            methods[label] = (lambda fn_, it_: lambda sr, er: S.prune_path(panel, units, fn_, sr, er, it_))(fn, iterative)
    methods["S2 NetAdapt ($0.0005 steps)"] = lambda sr, er: S.s2_netadapt(panel, sources, sr, er, STEP)
    rows, path_frames = [], {}
    for label, fn in methods.items():
        per_dir = []
        for k, (sr, er) in enumerate(dirs):
            p = fn(sr, er).assign(direction=k)
            p["regret"] = S.regret(p, fronts[k])
            p["regret_counts"] = S.regret(p, count_fronts[k])  # the brief's S4: the call-count-vector frontier
            per_dir.append(p)
        frame = pd.concat(per_dir, ignore_index=True)
        path_frames[label] = frame
        first = [str(f.loc[f["step"] == 1, "removed"].iloc[0]) if "removed" in f and (f["step"] == 1).any() else "-"
                 for f in per_dir]
        rows.append({"method": label, "mean regret (points)": 100 * frame["regret"].mean(),
                     "max regret (points)": 100 * frame["regret"].max(),
                     "mean regret vs count vectors": 100 * frame["regret_counts"].mean(),
                     "first removed (fold 0 / fold 1)": " / ".join(first)})
    out["methods"] = pd.DataFrame(rows).sort_values("mean regret (points)", kind="stable")
    out["paths"] = path_frames

    # NetAdapt cross-fitted per step, per-item, for the selection-rule preview and figure
    na_dirs = [S.s2_netadapt(panel, sources, sr, er, STEP) for sr, er in dirs]
    steps = min(len(p) for p in na_dirs)
    na_rows = []
    for k in range(steps):
        kept = [panel.mask(p["kept"].iloc[k].split("+")) for p in na_dirs]
        corr, dollars = oof_correct(panel, kept, folds)
        na_rows.append({"step": k, "kept (fold 0 / fold 1)": " / ".join(p["kept"].iloc[k] for p in na_dirs),
                        "search_accuracy": float(np.mean([p["search_score"].iloc[k] for p in na_dirs])),
                        "cross_fitted_accuracy": float(np.nanmean(corr)), "dollars": float(np.nanmean(dollars)),
                        "per_item": corr, "per_item_dollars": dollars})
    out["netadapt_cf"] = pd.DataFrame(na_rows)

    # S3: CEM controller under budgets, reward from the plain vote (AMC's proxy); proxy test on the 63 networks
    cem = []
    for budget in (0.0036, 0.0075, 0.015):
        kept_dirs, hist_n = [], []
        for sr, er in dirs:
            best, hist = S.s3_controller(panel, sources, sr, budget=budget, iters=10, population=24)
            kept_dirs.append(best)
            hist_n.append(len(hist))
        corr, dollars = oof_correct(panel, kept_dirs, folds)
        cem.append({"budget": budget, "picked (fold 0 / fold 1)": " / ".join(S.kept_names(panel, k) for k in kept_dirs),
                    "held-out accuracy": float(np.mean(corr)), "dollars": float(np.mean(dollars)),
                    "distinct networks evaluated": "/".join(map(str, hist_n))})
    out["cem"] = pd.DataFrame(cem)
    configs = [panel.mask(k.split("+")) for k in cross[cross["refit"] == "ridge"]["kept"]]
    out["proxy"] = S.proxy_spearman(panel, configs, folds, "ridge", n_boot=1000)
    calls = flat_calls()
    flipped = Panel.from_calls(calls.assign(rank=(calls["source"] != "sonnet").astype(int))
                               .sort_values("rank", kind="stable").drop(columns="rank"))
    vote_flipped = [predict(flipped, flipped.mask(k.split("+")))["correct"].mean()
                    for k in cross[cross["refit"] == "ridge"]["kept"]]
    out["vote_sonnet_first"] = float(np.mean(vote_flipped))
    out["proxy_weights"] = S.proxy_spearman(panel, configs, folds, "weights", n_boot=1000)
    crit = out["criteria_unit"].drop(columns=["dollars"])
    out["rank_agreement"] = crit.corr(method="spearman")

    # dynamic policies: gain-per-dollar order and the fixed cheap-first order, each tau, cross-fitted
    dyn = []
    fixed = haiku + [sonnet]
    for label, order in (("gain per $ order", None), ("fixed order: Haiku x5 then Sonnet", fixed)):
        fr = pd.concat([S.dynamic_frontier(panel, list(range(panel.m)), sr, er, TAUS, order=order).assign(direction=k)
                        for k, (sr, er) in enumerate(dirs)])
        mean = fr.groupby("tau").agg(accuracy=("accuracy", "mean"), dollars=("dollars", "mean"), tokens=("tokens", "mean"),
                                     rounds=("rounds", "mean"), seconds=("seconds", "mean")).reset_index()
        order0 = fr[fr["direction"] == 0].set_index("tau")["order"]
        dyn.append(mean.assign(policy=label, **{"order (fold 0)": mean["tau"].map(order0)}))
    out["dynamic"] = pd.concat(dyn, ignore_index=True)[["policy", "tau", "accuracy", "dollars", "tokens", "rounds",
                                                        "seconds", "order (fold 0)"]]
    # static vs dynamic at equal average dollars: the static frontiers' accuracy at each policy's dollars
    eq = out["dynamic"][["policy", "tau", "accuracy", "dollars", "rounds"]].copy()
    eq["static, count vectors"] = S.frontier_at(out["front_counts"], eq["dollars"])
    eq["static, any subset (oracle)"] = S.frontier_at(out["front_cross"], eq["dollars"])
    eq["dynamic minus count-vector static (points)"] = 100 * (eq["accuracy"] - eq["static, count vectors"])
    out["equal_dollars"] = eq.replace(-np.inf, np.nan)
    # per-item cross-fitted dynamic policies at the tau chosen on the search half (the cheapest tau whose
    # search-half accuracy is within 1 point of the best tau's) for the paired comparisons
    def pick_tau(fixed_order):
        corr = np.full(panel.n, np.nan)
        dollars = np.full(panel.n, np.nan)
        chosen = []
        for sr, er in dirs:
            prefixes = S.Prefixes(panel, sr)
            search_fr = []
            for tau in TAUS:
                order = fixed_order or S.gain_order(panel, list(range(panel.m)), sr, tau, prefixes=prefixes)
                f = S.dynamic_replay(panel, order, tau, sr, sr, prefixes=prefixes)
                search_fr.append({"tau": tau, "order": order, "accuracy": f["correct"].mean(), "dollars": f["dollars"].mean()})
            search_fr = pd.DataFrame(search_fr)
            ok = search_fr[search_fr["accuracy"] >= search_fr["accuracy"].max() - 0.01]
            pick = ok.sort_values("dollars", kind="stable").iloc[0]
            chosen.append(pick["tau"])
            f = S.dynamic_replay(panel, pick["order"], pick["tau"], sr, er, prefixes=prefixes)
            corr[er] = f["correct"].to_numpy()
            dollars[er] = f["dollars"].to_numpy()
        return {"tau": chosen, "per_item": corr, "per_item_dollars": dollars}

    out["dynamic_pick"] = pick_tau(None)
    out["dynamic_pick_fixed"] = pick_tau(fixed)

    # baselines at matched cost: random sub-networks around the dynamic pick's cost and around the 5-call vote's
    rand = []
    for target_label, target in (("5-call vote cost", float(panel.cost[:, haiku].sum(axis=1).mean())),
                                 ("Sonnet cost", float(panel.cost[:, sonnet].mean())),
                                 ("dynamic pick (fixed order) cost",
                                  float(np.mean(out["dynamic_pick_fixed"]["per_item_dollars"])))):
        sets = S.random_subsets(panel, list(range(panel.m)), target, n=200, tol=0.25)
        scores = [float(np.mean(oof_correct(panel, [k, k], folds)[0])) for k in sets]
        rand.append({"matched to": target_label, "target $": target, "random networks": len(sets),
                     "distinct": len({S.kept_names(panel, k) for k in sets}),
                     "mean accuracy": float(np.mean(scores)) if scores else np.nan,
                     "90th percentile": float(np.percentile(scores, 90)) if scores else np.nan})
    out["random"] = pd.DataFrame(rand)
    simple = []
    for budget in (0.0036, 0.0075, 0.015, 0.0181):
        for label, picker in (("cheapest-first", S.cheapest_first), ("top-k accurate", S.top_k_accurate)):
            kept_dirs = [picker(panel, list(range(panel.m)), budget, sr) for sr, er in dirs]
            corr_b, dollars_b = oof_correct(panel, kept_dirs, folds)
            simple.append({"baseline": label, "budget": budget, "picked (fold 0)": S.kept_names(panel, kept_dirs[0]),
                           "held-out accuracy": float(np.mean(corr_b)), "dollars": float(np.mean(dollars_b))})
    out["simple"] = pd.DataFrame(simple)
    return out


# ---------------------------------------------------------------------------------------------------------
# figures

def figures(a: dict, b: dict) -> list[str]:
    plt = style()
    paths = []
    # 1. grid frontier
    pts = a["points"]
    fig, ax = plt.subplots(figsize=(5.6, 3.8))
    ax.errorbar(pts["dollars"] * 1000, pts["accuracy"] * 100, yerr=[(pts["accuracy"] - pts["acc_lo"]) * 100,
                (pts["acc_hi"] - pts["accuracy"]) * 100], fmt="o", ms=3.5, color=color(0), alpha=0.45, lw=0.6,
                label="27 staged designs (95% CI)")
    front = S.pareto(pts, score="accuracy")
    ax.step(front["dollars"] * 1000, front["accuracy"] * 100, where="post", color=color(0), lw=1.2, label="frontier of the 27")
    na = a["netadapt"]
    ax.plot(na["dollars"] * 1000, na["accuracy"] * 100, "-", marker="s", ms=3, color=color(1), lw=1, label="NetAdapt path (all 80)")
    for name, mk, ci_ in (("Haiku 5-call vote", "D", 3), ("Sonnet (1 call)", "*", 2)):
        corr, dollars = b["refs"][name]
        ax.plot(np.mean(dollars) * 1000, np.mean(corr) * 100, mk, ms=8, color=color(ci_), label=name)
    for _, r in pts.iterrows():
        if r["design"] in ("k1-1-1-1", "k6-6-6-1", "k3-1-6-1", "k3-3-1-1"):
            ax.annotate(r["design"][1:-2], (r["dollars"] * 1000, r["accuracy"] * 100), fontsize=7, xytext=(3, -8),
                        textcoords="offset points")
    ax.set_xlabel("dollars per item (x 1/1000)")
    ax.set_ylabel("accuracy on the 80 items (%)")
    ax.legend(fontsize=7, loc="lower right")
    ax.set_title("Staged Haiku designs: whole grid points only", fontsize=9)
    paths += save_figure(fig, "grid_frontier", FIGURES)

    # 2. stage sensitivity
    eff = a["sens"]
    fig, ax = plt.subplots(figsize=(5.0, 3.0))
    for k, s in enumerate(["propose", "critique", "refine"]):
        part = eff[eff["stage"] == s]
        for j, (_, r) in enumerate(part.iterrows()):
            d = a["wide"][r["design"]] - a["wide"]["k6-6-6-1"]
            m, lo, hi = ci(d)
            x = k + (j - 0.5) * 0.25
            ax.errorbar(x, m * 100, yerr=[[(m - lo) * 100], [(hi - m) * 100]], fmt="o", color=color(j), ms=4,
                        label=f"6 -> {int(r['level'])}" if k == 0 else None)
    ax.axhline(0, color="black", lw=0.7)
    ax.set_xticks(range(3), ["propose", "critique", "refine"])
    ax.set_ylabel("accuracy change vs 6-6-6 (points)")
    ax.legend(fontsize=7)
    ax.set_title("One stage at a time, others at 6 (paired, 95% CI)", fontsize=9)
    paths += save_figure(fig, "grid_sensitivity", FIGURES)

    # 3. flat panel: 63 sub-networks, frontier, paths, dynamic
    cross = b["cross"]
    w = cross[cross["refit"] == "ridge"]
    fig, ax = plt.subplots(figsize=(7.4, 3.9))
    ax.scatter(w["dollars"] * 1000, w["score"] * 100, s=10, color="grey", alpha=0.5,
               label="63 sub-networks (Kevin's aggregator, cross-fitted)")
    v = cross[cross["refit"] == "weights"]
    ax.scatter(v["dollars"] * 1000, v["score"] * 100, s=8, marker="x", color=color(5), alpha=0.5, label="same, weighted vote")
    f = b["front_cross"]
    ax.step(f["dollars"] * 1000, f["score"] * 100, where="post", color="black", lw=1, label="frontier (Kevin's aggregator)")
    fw = b["front_cross_weights"]
    ax.step(fw["dollars"] * 1000, fw["score"] * 100, where="post", color=color(5), lw=1, ls="--", label="frontier (weighted vote)")
    dyn = b["dynamic"]
    for k, (label, part) in enumerate(dyn.groupby("policy", sort=False)):
        part = part.sort_values("dollars", kind="stable")
        ax.plot(part["dollars"] * 1000, part["accuracy"] * 100, "-o", ms=3, lw=1, color=color(k + 1), label=f"dynamic, {label}")
    for name, mk, c in (("Sonnet (1 call)", "*", 2), ("Haiku 5-call vote", "D", 3), ("Haiku cascade, escalate if < 3 of 5 agree", "P", 4),
                        ("Haiku cascade, escalate if < 4 of 5 agree", "X", 4)):
        corr, dollars = b["refs"][name]
        ax.plot(np.mean(dollars) * 1000, np.mean(corr) * 100, mk, ms=8, color=color(c), label=name)
    ax.set_xlabel("dollars per item (x 1/1000)")
    ax.set_ylabel("held-out accuracy (%) (cascades: all 80, no fitting)")
    ax.legend(fontsize=6.5, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    ax.set_title("Flat panel 5 Haiku + 1 Sonnet: static vs dynamic", fontsize=9)
    paths += save_figure(fig, "flat_frontier", FIGURES)

    # 4. regret by method (flat)
    m = b["methods"]
    fig, ax = plt.subplots(figsize=(5.2, 0.22 * len(m) + 0.8))
    ax.barh(range(len(m)), m["mean regret (points)"], color=color(0))
    ax.set_yticks(range(len(m)), m["method"], fontsize=7)
    ax.invert_yaxis()
    ax.set_xlabel("mean regret over path points (accuracy points)")
    ax.set_title("Pruning paths vs the exhaustive frontier (held-out half)", fontsize=9)
    paths += save_figure(fig, "flat_regret", FIGURES)

    # 5. per-source sensitivity curves (flat panel, all 80) next to the grid's stage curves
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.0))
    curves = b["s1_curves"]
    for k, (name, part) in enumerate(curves.groupby("source", sort=False)):
        part = part.sort_values("kept_calls", kind="stable")
        axes[0].plot(part["kept_calls"], part["score"] * 100, "-o", ms=3, color=color(k), label=name)
    axes[0].set_xlabel("calls kept from this source (others at full)")
    axes[0].set_ylabel("accuracy, all 80 (%)")
    axes[0].set_title("Flat panel: one source at a time", fontsize=9)
    axes[0].legend(fontsize=7)
    t = a["sens"]
    full = a["points"].set_index("design").loc["k6-6-6-1", "accuracy"]
    for k, (stage, part) in enumerate(t.groupby("stage", sort=False)):
        xs = [6] + part["level"].tolist()
        ys = [full * 100] + (part["accuracy"] * 100).tolist()
        axes[1].plot(xs, ys, "-o", ms=3, color=color(k), label=stage)
    axes[1].set_xlabel("agents kept in this stage (others at 6)")
    axes[1].set_title("Staged grid: one stage at a time", fontsize=9)
    axes[1].legend(fontsize=7)
    paths += save_figure(fig, "sensitivity_curves", FIGURES)

    # 6. quality vs dollars per item (log x) for every method (fold 0's path, scored on the held-out half)
    fig, ax = plt.subplots(figsize=(7.4, 4.0))
    shown = [k for k in b["paths"] if k.startswith(("S1", "S2")) or k.endswith("iterative")]
    for k, name in enumerate(shown):
        part = b["paths"][name]
        part = part[part["direction"] == 0].sort_values("dollars", kind="stable")
        ax.plot(part["dollars"], part["score"] * 100, marker="o", ls=["-", "--", ":"][k // 7], ms=2.5, lw=0.9,
                color=color(k), alpha=0.85, label=name)
    f0 = b["front_fold0"]
    ax.step(f0["dollars"], f0["score"] * 100, where="post", color="black", lw=1.2, label="exhaustive frontier (fold 0)")
    ax.set_xscale("log")
    ax.set_xlabel("dollars per item (log scale)")
    ax.set_ylabel("held-out accuracy (%)")
    ax.legend(fontsize=6.5, loc="upper left", bbox_to_anchor=(1.01, 1.0))
    ax.set_title("Every pruning method's path (search on fold 0, scored on fold 1)", fontsize=9)
    paths += save_figure(fig, "flat_methods_logx", FIGURES)

    # 7. rank agreement among criteria (Spearman over the 6 calls)
    ra = b["rank_agreement"]
    fig, ax = plt.subplots(figsize=(5.2, 4.4))
    im = ax.imshow(ra.to_numpy(), vmin=-1, vmax=1, cmap="RdBu_r")
    ax.set_xticks(range(len(ra)), ra.columns, rotation=60, fontsize=7)
    ax.set_yticks(range(len(ra)), ra.index, fontsize=7)
    for i in range(len(ra)):
        for j in range(len(ra)):
            v = ra.iat[i, j]
            ax.text(j, i, "" if np.isnan(v) else f"{v:.1f}", ha="center", va="center", fontsize=6)
    fig.colorbar(im, ax=ax, shrink=0.8, label="Spearman correlation of the 6 calls' scores")
    ax.set_title("Do the criteria rank the calls alike? (all 80 items)", fontsize=9)
    ax.grid(False)
    paths += save_figure(fig, "criteria_rank_agreement", FIGURES)

    # 8. one-shot vs iterative
    m = b["methods"].set_index("method")["mean regret (points)"]
    names = [c for c in ("C1", "C2", "C3", "C3b", "C4", "C5", "C6", "C7a", "C7b")]
    fig, ax = plt.subplots(figsize=(5.6, 3.0))
    x = np.arange(len(names))
    ax.bar(x - 0.2, [m[f"{c} one-shot"] for c in names], 0.4, color=color(0), label="one-shot")
    ax.bar(x + 0.2, [m[f"{c} iterative"] for c in names], 0.4, color=color(1), label="iterative")
    ax.set_xticks(x, names)
    ax.set_ylabel("mean regret (accuracy points)")
    ax.legend(fontsize=7)
    ax.set_title("One-shot vs iterative ranking (lower is better)", fontsize=9)
    paths += save_figure(fig, "one_shot_vs_iterative", FIGURES)

    # 9. dollar vs latency frontiers
    fig, axes = plt.subplots(1, 2, figsize=(7.4, 3.0), sharey=True)
    f = b["front_cross"]
    axes[0].step(f["dollars"] * 1000, f["score"] * 100, where="post", color="black", label="static frontier")
    fs = b["front_seconds"]
    axes[1].step(fs["seconds"], fs["score"] * 100, where="post", color="black", label="static frontier")
    for k, (label, part) in enumerate(b["dynamic"].groupby("policy", sort=False)):
        part = part.sort_values("dollars", kind="stable")
        axes[0].plot(part["dollars"] * 1000, part["accuracy"] * 100, "-o", ms=3, color=color(k + 1), label=f"dynamic, {label}")
        axes[1].plot(part["seconds"], part["accuracy"] * 100, "-o", ms=3, color=color(k + 1), label=f"dynamic, {label}")
    axes[0].set_xlabel("dollars per item (x 1/1000)")
    axes[1].set_xlabel("seconds per item (static: slowest call; dynamic: sum)")
    axes[0].set_ylabel("held-out accuracy (%)")
    axes[1].legend(fontsize=6.5)
    fig.suptitle("Dollar and latency frontiers, flat panel", fontsize=9)
    paths += save_figure(fig, "dollar_vs_latency", FIGURES)
    return [str(p.relative_to(ROOT)) for p in paths]


# ---------------------------------------------------------------------------------------------------------

def main() -> None:
    grid = load_grid()
    panel = Panel.from_calls(flat_calls())
    assert panel.items == grid.items or set(panel.items) == set(grid.items)
    folds = two_folds(panel.n, seed=0, strata=task_of(panel.items))
    grid_folds = pd.Series(folds, index=panel.items).reindex(grid.items).to_numpy()
    b = flat_part(panel, folds)
    a = grid_part(grid, grid_folds, b["refs"])
    figs = figures(a, b)
    TABLES.mkdir(parents=True, exist_ok=True)
    a["points"].to_csv(TABLES / "grid_points.csv", index=False)
    a["regrets"].to_csv(TABLES / "grid_regrets.csv", index=False)
    b["cross"].to_csv(TABLES / "flat_subnetworks.csv", index=False)
    b["dynamic"].to_csv(TABLES / "flat_dynamic.csv", index=False)
    pd.concat([f.assign(method=k) for k, f in b["paths"].items()]).to_csv(TABLES / "flat_paths.csv", index=False)
    write(a, b, figs)


def summary_text(a, b, refs, sonnet_c, sonnet_d, pooled, eff, preview_text) -> str:
    pts = a["points"]
    lo, hi = pts.loc[pts["dollars"].idxmin()], pts.loc[pts["accuracy"].idxmax()]
    s_acc, s_usd = float(np.mean(sonnet_c)), float(np.mean(sonnet_d))
    reg = a["regret_summary"].set_index("method")["mean_regret"] * 100
    per_stage = ", ".join(f"{r.stage} {r.estimate:+.1f}" for r in eff.itertuples())
    acc = lambda name: float(np.mean(refs[name][0])) * 100
    usd = lambda name: float(np.mean(refs[name][1]))
    dq = b["dynamic_pick_fixed"]
    dq_acc, dq_usd = float(np.mean(dq["per_item"])) * 100, float(np.mean(dq["per_item_dollars"]))
    dq_diff = ci(dq["per_item"] - sonnet_c)
    dg = b["dynamic_pick"]
    dg_acc, dg_usd = float(np.mean(dg["per_item"])) * 100, float(np.mean(dg["per_item_dollars"]))
    dg_diff = ci(dg["per_item"] - sonnet_c)
    methods = b["methods"].set_index("method")["mean regret (points)"]
    proxy, proxy_w = b["proxy"], b["proxy_weights"]
    c5_vs = float(b["rank_agreement"].loc["C5", ["C1", "C2", "C3", "C3b", "C6"]].mean())
    front = b["front_cross"]
    oracle = front.sort_values(["score", "dollars"], ascending=[False, True], kind="stable").iloc[0]
    count_best = b["counts"].sort_values(["score", "dollars"], ascending=[False, True], kind="stable").iloc[0]
    ranked = b["methods"].sort_values("mean regret (points)", kind="stable")
    best_m = (ranked["method"].iloc[0], float(ranked["mean regret (points)"].iloc[0]))
    worst_m = (ranked["method"].iloc[-1], float(ranked["mean regret (points)"].iloc[-1]))
    refit = b["refit_summary"].set_index("refit")["mean_accuracy"]
    return " ".join([
        f"**Staged grid.** The 27 Haiku designs run from {lo['accuracy'] * 100:.1f}% ({lo['design']}, "
        f"${lo['dollars']:.4f} per item) to {hi['accuracy'] * 100:.1f}% ({hi['design']}, ${hi['dollars']:.4f}); an extra "
        f"Haiku call adds {pooled['estimate'] * 100:+.2f} points ({pooled['lo'] * 100:+.2f} to {pooled['hi'] * 100:+.2f}), "
        f"per stage {per_stage} points per call, small and alike within noise. The best design is "
        f"{(s_acc - hi['accuracy']) * 100:.1f} points below one Sonnet call at {hi['dollars'] / s_usd:.2f}x its cost.",
        f"Picks made on one half and scored on the other have mean regret {reg.get('S1 sensitivity', np.nan):.1f} (S1 "
        f"sensitivity), {reg.get('exhaustive (search half)', np.nan):.1f} (exhaustive on the search half) and "
        f"{reg.get('NetAdapt', np.nan):.1f} (NetAdapt) points: within about two items of each other.",
        f"**Flat panel.** Sonnet alone scores {s_acc * 100:.1f}% at ${s_usd:.4f}; the Haiku 5-call vote "
        f"{acc('Haiku 5-call vote'):.1f}% at {usd('Haiku 5-call vote') / s_usd:.2f}x; the full panel with Kevin's "
        f"aggregator {acc(DENSE_K):.1f}% and with the weighted vote {acc('dense weighted vote (6 calls)'):.1f}%, both at "
        f"{usd(DENSE_K) / s_usd:.2f}x. The best static sub-network ({oracle['kept']}) scores {oracle['score'] * 100:.1f}% "
        f"({(oracle['score'] - s_acc) * 100:+.1f} points against Sonnet) at {oracle['dollars'] / s_usd:.2f}x its cost, but "
        "it is an oracle pick among 63, made after seeing the held-out halves; among the 11 call-count vectors (the "
        f"first k calls of each source) the best is {count_best['counts']} at {count_best['score'] * 100:.1f}% and "
        f"{count_best['dollars'] / s_usd:.2f}x. Every static network that includes Sonnet costs at least as much as "
        "Sonnet, so static pruning cannot buy Sonnet's accuracy for less. Policies that call Sonnet only when "
        "Haiku is unsure come close for less, but not every one: the Haiku-only cascade of cached finding 8 (escalate "
        "when fewer than 3 of 5 Haiku calls agree; not the plan's H7, which mixes 3 Haiku and 3 Luna calls and needs 4 "
        "of 6, and already scored on items 60-99 in finding 8, so not a fresh test) scores "
        f"{acc('Haiku cascade, escalate if < 3 of 5 agree'):.1f}% at "
        f"{usd('Haiku cascade, escalate if < 3 of 5 agree') / s_usd:.2f}x Sonnet's cost; the dynamic policy with the "
        f"cheap-first order and a refitted confidence stop (tau chosen on the search half, {dq['tau'][0]} / "
        f"{dq['tau'][1]}) {dq_acc:.1f}% at {dq_usd / s_usd:.2f}x (minus Sonnet {fmt_ci(dq_diff)} points); the "
        f"gain-per-dollar order, Phase 3B's other dynamic candidate, only {dg_acc:.1f}% at {dg_usd / s_usd:.2f}x "
        f"(minus Sonnet {fmt_ci(dg_diff)} points). That order degenerates on this panel: with one call the refitted "
        "confidence is the same for every answered item, so the policy stops every item after its first call or none, "
        "and on one half no later call had a positive in-sample gain, so it stopped after one Haiku call.",
        f"Pruning paths' mean regret against the exhaustive frontier (held-out half) ranges from {best_m[1]:.1f} points "
        f"({best_m[0]}) to {worst_m[1]:.1f} ({worst_m[0]}); S1 {methods.get(S1_LABEL, np.nan):.1f}, NetAdapt "
        f"{methods.get('S2 NetAdapt ($0.0005 steps)', np.nan):.1f}, C6 leave-one-out (iterative) "
        f"{methods.get('C6 iterative', np.nan):.1f}. With 6 calls, 5 of them exchangeable, and 40-item halves, these "
        "differences are one or two items. Over the 63 sub-networks, Kevin's aggregator (ridge refit) scores "
        f"{refit['ridge'] * 100:.1f}% on average, the same whichever source is listed first; the plain vote, whose "
        f"ties go to the call listed first, scores {refit['none'] * 100:.1f}% with Haiku listed first and "
        f"{b['vote_sonnet_first'] * 100:.1f}% with Sonnet first (ties are frequent in small sub-networks: a Haiku + "
        f"Sonnet pair splits 1-1); the weighted vote {refit['weights'] * 100:.1f}%. AMC's proxy (the vote without refit) "
        f"ranks the sub-networks like the refitted score: Spearman {proxy['rho']:+.2f} ({proxy['lo']:+.2f} to "
        f"{proxy['hi']:+.2f}) against Kevin's aggregator, {proxy_w['rho']:+.2f} ({proxy_w['lo']:+.2f} to "
        f"{proxy_w['hi']:+.2f}) against the weighted vote. The label-free criteria rank the calls against the "
        f"label-based ones: C5 (reconstruction) correlates {c5_vs:+.1f} on average with C1-C3b and C6 over the six calls "
        "(reconstructing the panel's vote rewards the majority source), so it would prune Sonnet first.",
        "**What Phase 1 must measure:** the Haiku-Luna error correlation (the cross-vendor latent r). On this panel the "
        "only call that carries new information is the expensive one (Haiku-Sonnet phi 0.08 against Haiku-Haiku 0.44), "
        "so pruning can only trade it away; a cheap call from another vendor whose errors are as independent as "
        "Sonnet's would make a cheap network that pruning could keep.",
    ])


def write(a: dict, b: dict, figs: list[str]) -> None:
    refs = b["refs"]
    sonnet_c, sonnet_d = refs["Sonnet (1 call)"]
    ref_rows = []
    for name, (corr, dollars) in refs.items():
        ref_rows.append({"network": name, "accuracy % (95% CI)": fmt_acc(ci(corr)), "$ per item": float(np.mean(dollars)),
                         "minus Sonnet, points": fmt_ci(ci(corr - sonnet_c)) if name != "Sonnet (1 call)" else "-",
                         "cost / Sonnet": float(np.mean(dollars) / np.mean(sonnet_d))})
    dp = b["dynamic_pick"]
    ref_rows.append({"network": f"dynamic, gain per $ (tau picked on the search half: {dp['tau'][0]} / {dp['tau'][1]})",
                     "accuracy % (95% CI)": fmt_acc(ci(dp["per_item"])), "$ per item": float(np.mean(dp["per_item_dollars"])),
                     "minus Sonnet, points": fmt_ci(ci(dp["per_item"] - sonnet_c)),
                     "cost / Sonnet": float(np.mean(dp["per_item_dollars"]) / np.mean(sonnet_d))})
    dq = b["dynamic_pick_fixed"]
    ref_rows.append({"network": f"dynamic, Haiku x5 then Sonnet (tau picked on the search half: {dq['tau'][0]} / {dq['tau'][1]})",
                     "accuracy % (95% CI)": fmt_acc(ci(dq["per_item"])), "$ per item": float(np.mean(dq["per_item_dollars"])),
                     "minus Sonnet, points": fmt_ci(ci(dq["per_item"] - sonnet_c)),
                     "cost / Sonnet": float(np.mean(dq["per_item_dollars"]) / np.mean(sonnet_d))})
    ref_table = pd.DataFrame(ref_rows)

    na = b["netadapt_cf"]
    sonnet_acc = float(np.mean(sonnet_c))
    eligible = na[na["cross_fitted_accuracy"] >= sonnet_acc - 0.01]
    if len(eligible):
        preview = eligible.sort_values("dollars", kind="stable").iloc[0]
        preview_text = (f"step {int(preview['step'])} qualifies: {preview['kept (fold 0 / fold 1)']}, cross-fitted accuracy "
                        f"{preview['cross_fitted_accuracy'] * 100:.1f}% at ${preview['dollars']:.4f} per item.")
    else:
        best = na.sort_values(["cross_fitted_accuracy", "dollars"], ascending=[False, True], kind="stable").iloc[0]
        preview_text = (f"no step qualifies (the best, step {int(best['step'])}, reaches "
                        f"{best['cross_fitted_accuracy'] * 100:.1f}% at ${best['dollars']:.4f} per item); the "
                        "rule now leaves P1 and P2 void rather than test a fallback network.")
    na_table = na.drop(columns=["per_item", "per_item_dollars"])
    halves = na_table["kept (fold 0 / fold 1)"].str.split(" / ")
    n_differ = int(sum(len(set(h)) > 1 for h in halves))

    # the prior "~0.07 independent call per extra Haiku call", two translations of the measured slope
    pooled = a["pooled"]
    eff = a["effects"]
    haiku_cols = np.flatnonzero(b["panel"].units["source"] == "haiku")
    rho_h = R.rho_pairwise(b["panel"].correct_matrix()[:, haiku_cols])
    one = float(np.mean(refs["Haiku, 1 call (mean of 5)"][0]))
    five = float(np.mean(refs["Haiku 5-call vote"][0]))
    neff5 = 5 / (1 + 4 * rho_h)
    per_point = (neff5 - 1) / ((five - one) * 100)  # independent calls bought per accuracy point by repeat votes
    yard = pooled["estimate"] * 100 * per_point
    gain = ci(refs["Haiku 5-call vote"][0] - refs["Haiku, 1 call (mean of 5)"][0])  # the yardstick's own uncertainty
    na_path = a["netadapt"].merge(a["points"][["design", "calls"]], on="design")
    full_usd = float(na_path["dollars"].iloc[0])
    within = na_path[na_path["accuracy"] >= na_path["accuracy"].iloc[0] - 0.0125 - 1e-9]
    keep = within.iloc[-1]
    nxt = na_path.iloc[min(int(within.index[-1]) + 1, len(na_path) - 1)]
    verdict = (
        f"accuracy rises {pooled['estimate'] * 100:+.2f} points per extra call ({pooled['lo'] * 100:+.2f} to "
        f"{pooled['hi'] * 100:+.2f}), and the three stages' per-call effects are alike within noise, so \"flat\" holds in "
        "the sense of small, similar per-call gains: an extra staged call is worth about what an extra repeat vote is "
        f"worth (the 5-call vote gains {(five - one) * 100:+.2f} points over one call, "
        f"{(five - one) * 100 / 4:+.2f} per extra call). In independent-call equivalents the two translations disagree: "
        f"via the repeat-vote yardstick (4 extra votes buy n_eff {neff5:.2f} - 1 = {neff5 - 1:.2f} independent calls at "
        f"Haiku rho {rho_h:.2f}, i.e. {per_point:.3f} independent calls per point), an extra staged call is worth "
        f"{yard:.2f} independent calls, a point estimate only: the yardstick's vote gain is itself uncertain "
        f"({fmt_ci(gain)} points), and its interval reaches 0, where the translation has no upper bound; via the "
        "design-correlation formula, "
        f"{a['neff_per_call']:.3f}. The prior's 0.07 lies between them; these data do not pin the number down, and "
        "only the points-per-call reading is a measurement. The brief's corollary, that NetAdapt removes most of the "
        f"team: its cheapest design within one item of 6-6-6 (all 80 items) is {keep['design']} ({int(keep['calls'])} "
        f"of 19 calls, {keep['dollars'] / full_usd * 100:.0f}% of the dollars), so it removes about "
        f"{(1 - keep['calls'] / 19) * 100:.0f}% of the calls, not most; its next step costs "
        f"{(keep['accuracy'] - nxt['accuracy']) * 100:.1f} points ({nxt['design']}).")

    summary = summary_text(a, b, refs, sonnet_c, sonnet_d, pooled, eff, preview_text)
    lines = [
        "# Phase 3A: pruning agent networks by information per dollar, on cached calls",
        "",
        "Written by `python -m analysis.pruning_phase3a` ($0, no API). Exploratory: nothing here is a confirmatory "
        "test, and with 80 items one item is 1.25 points. Definitions are in the script's docstring and in "
        "`autoagentnet/pruning/` (replay.py, criteria.py, search.py). Folds: two halves of the 80 items, balanced "
        "within each BBEH task (seed 0); intervals resample items (2,000 draws).",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## (a) The staged grid: 27 Haiku designs, whole grid points only",
        "",
        "Each design (propose-critique-refine keep levels, then one aggregator) was run once per item; a pruned "
        "stage changes what later stages read, so nothing between grid points can be replayed. Only the 27 points "
        "are compared.",
        "",
        md(a["points"][["design", "calls", "accuracy", "acc_lo", "acc_hi", "dollars", "seconds", "regret"]], 4),
        "",
        "Regret here is in-sample (all 80): the frontier's accuracy at the design's cost or less minus its own.",
        "",
        "### Stage sensitivity (one stage at a time, the others at 6)",
        "",
        md(a["sens"][["stage", "level", "design", "accuracy", "dollars", "d_accuracy", "d_dollars", "diff_ci",
                      "points_per_extra_call"]], 4),
        "",
        "Main effect per extra call of each stage (level 6 minus level 1, averaged over the other two stages' "
        "nine settings, per item, divided by the 5 extra calls; points, 95% CI):",
        "",
        md(eff[["stage", "points per extra call", "dollars per extra call"]], 5),
        "",
        f"Pooled over all 27 designs, a least-squares line of accuracy on calls per item has slope "
        f"{pooled['estimate'] * 100:+.2f} points per extra call ({pooled['lo'] * 100:+.2f} to {pooled['hi'] * 100:+.2f}).",
        "",
        "**The prior \"stage sensitivity flat (~0.07 independent call per extra Haiku call)\".** "
        f"The designs' outputs are strongly correlated (mean pairwise phi of correctness {a['phi_designs']:.2f}, "
        f"351 pairs). Read through n_eff(m) = m / (1 + (m - 1) rho) with rho = {a['phi_designs']:.2f}, going from 4 "
        f"calls (1-1-1) to 19 (6-6-6) moves n_eff from {a['n_eff'][4]:.2f} to {a['n_eff'][19]:.2f}: "
        f"{a['neff_per_call']:.3f} independent-call equivalents per extra call (a model-based translation: the calls "
        "inside a design are not exchangeable repeats). Measured directly, " + verdict,
        "",
        "### NetAdapt over stage levels ($0.0005 per item per step; all 80 items)",
        "",
        md(a["netadapt"], 4),
        "",
        "With seconds (the critical path) as the resource, 1 s per step:",
        "",
        md(a["netadapt_seconds"], 4),
        "",
        "Rounds do not vary on this grid (every design runs all four stages), so the round-based NetAdapt the plan "
        "names reduces to the dollar one; the critical path in seconds is the latency resource that does vary.",
        "",
        "### Picks under a budget: search half -> held-out half",
        "",
        "Each method picks a design using the search half only; regret is the held-out frontier's accuracy at the "
        "pick's held-out cost or less minus the pick's held-out accuracy, averaged over both directions and the "
        "budgets $0.004 to $0.0115 per item.",
        "",
        md(a["regret_summary"], 4),
        "",
        "## (b) The flat panel: 5 Haiku + 1 Sonnet, every sub-network replayed",
        "",
        "### Reference networks (all 80 items; refit and dynamic rows cross-fitted)",
        "",
        md(ref_table, 4),
        "",
        "### Criteria on the full panel (all 80, descriptive)",
        "",
        "Higher = keep. The five Haiku calls are exchangeable repeats, so differences among them are noise; the "
        "source-level table is the informative one.",
        "",
        md(b["criteria_source"].reset_index().rename(columns={"index": "group"}), 3),
        "",
        md(b["criteria_unit"].reset_index().rename(columns={"index": "unit"}), 3),
        "",
        "### Pruning paths against the exhaustive frontier (refit weights, held-out half, both directions)",
        "",
        md(b["methods"], 2),
        "",
        "### Refit options over the 63 sub-networks (cross-fitted accuracy)",
        "",
        md(b["refit_summary"], 4),
        "",
        "### S2 NetAdapt, cross-fitted per step (descriptive)",
        "",
        md(na_table, 4),
        "",
        ("Rows pool the two halves' networks at the same step index; "
         + (f"at {n_differ} of {len(na_table)} steps they are different networks, so a row's pooled dollars describe "
            "neither" if n_differ else "here the two halves' networks agree at every step, but they need not")
         + ", which is why the Phase 3B rule matches the halves by dollar budget instead (audit 49, "
         f"analysis/pruning_select.py). Read by step index, with Sonnet's {sonnet_acc * 100:.1f}% minus 1 point as the "
         f"floor: " + preview_text + f" Sonnet scores {b['sonnet_by_half'][0] * 100:.1f}% on fold 0's search half and "
         f"{b['sonnet_by_half'][1] * 100:.1f}% on fold 1's: with 40 items a half, that gap alone is several items."),
        "",
        "### S3: CEM controller (reward = plain-vote accuracy on the search half if dollars fit the budget, else -1)",
        "",
        md(b["cem"], 4),
        "",
        (f"AMC's proxy test over the 63 sub-networks: Spearman correlation between plain-vote accuracy (no refit) and "
         f"cross-fitted refit accuracy {b['proxy']['rho']:+.2f} ({b['proxy']['lo']:+.2f} to {b['proxy']['hi']:+.2f}); "
         f"bootstrap share at or below 0: {b['proxy']['p_not_positive']:.3f}; same best network: "
         f"{'yes' if b['proxy']['same_best'] else 'no'}."),
        "",
        "### Static vs dynamic",
        "",
        md(b["dynamic"], 4),
        "",
        "At equal average dollars: each policy's cross-fitted accuracy against the static frontiers' best accuracy at "
        "its dollars or less (count vectors: the first k calls of each source; any subset: the oracle over all 63).",
        "",
        md(b["equal_dollars"], 4),
        "",
        "Call-count vectors (S4 as the brief defines it), cross-fitted, with tokens per item:",
        "",
        md(b["counts"], 4),
        "",
        "### Baselines at matched cost",
        "",
        md(b["random"], 4),
        "",
        "No sub-network costs within 25% of the dynamic pick's dollars: every static network either leaves Sonnet out "
        "(at most $0.0036) or pays for it in full (at least $0.0144). That gap is what a dynamic policy fills.",
        "",
        md(b["simple"], 4),
        "",
        "## Figures",
        "",
        *[f"- `{p}`" for p in figs],
    ]
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
