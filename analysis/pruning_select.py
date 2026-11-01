"""Phase 3B of the evidence plan (session E3): the static and dynamic pruning rule. Since session E4 (Kevin's K3) it
is descriptive only: Phase 3C's frozen selection is the cascade rule (analysis/pruning_cascade.py, written to
research/v3/pruning/selected.json), and the static tests P1 and P2 left the prereg. This script writes
research/v3/pruning/selected_static.json (refusing to overwrite it) so the static numbers can be reported next to
the cascades.

Data. The search set is the 200 Phase 2 BBEH items (research/v3/evidence/sealed/bbeh_phase2.txt; ForecastBench:
the 200 sealed questions, forecast_sealed.txt), where Phase 1 (e13_bbeh_*, e14_forecast_*) and Phase 2's persona
runs (e22_persona_*) put the 18 calls the lockbox repeats:
  haiku_nothink x5 and luna_none x5 (base prompt, calls 0-4), sonnet_nothink x1 and sol61_low x1 (call 0), and
  haiku_nothink x3 and luna_none x3 under the persona prompts careful, contrarian and quick (one call each).
A unit is one of these 18 call slots ("haiku_nothink:base:3"); a source (Kevin's term: one model at one setting
with one prompt) is NetAdapt's unit of proposal: haiku base (5 calls), luna base (5), sonnet, sol, and each of the
six persona sources (1 call each). The aggregator is Kevin's (autoagentnet/pruning/replay.py): the plurality
answer and a ridge logistic model of P(it is right) on per-source agreement shares (ForecastBench: mean log-odds
times a fitted extremizing factor), refitted after pruning. An unparsed forecast counts as 0.5 (as in Phase 1); an
unparsed BBEH answer is in no answer class.

Terms (plain words; autoagentnet/pruning/ has the rest):
  folds          two halves of the search set, balanced within each BBEH task (ForecastBench: each source), seed 0.
  cross-fitted   each half is scored by a network (or policy) chosen and fitted on the other half; the two
                 halves' per-item results are pooled.
  budget B       dollars per item. NetAdapt's path on a half, read at budget B, is its first (largest) network
                 whose search-half dollars are at most B; the budgets tried are every path's step costs. Networks
                 are matched across halves by budget, not by step index (audit 49: step k can be a Haiku pair on
                 one half and Haiku + Sonnet on the other).
  score          accuracy (BBEH) or minus the Brier score (ForecastBench).
  dollars        mean cost per item, as billed.

The rule.
  Static (S2 NetAdapt, $0.0005 per item per step, the aggregator refitted; Kevin's rule). Run NetAdapt on each half; the
  selected budget is the smallest B whose cross-fitted score is at least Sonnet's minus 1 point of accuracy
  (ForecastBench: whose Brier is at most Sonnet's plus 0.005) and, only if COST_BOUND is set, whose cross-fitted
  dollars are at most COST_BOUND x Sonnet's (Kevin's open choice: None = his rule as written, option (a); 0.8 =
  option (b), a saving by construction). The frozen static network is the full-data NetAdapt path (all 200
  items) read at that budget, its aggregator refitted on all 200. If no budget qualifies there is no static network:
  P1 and P2 are void, never replaced by a fallback (audit 49). If the frozen network is Sonnet alone, P1 is void
  (Sonnet against itself).
  Dynamic. Candidates: two call orders (cheapest-first by measured dollars, ties in unit order; and the greedy
  order by expected gain per dollar, search.gain_order) times the stopping thresholds TAUS. The selected policy is
  the one with the smallest cross-fitted dollars whose cross-fitted score is at least the selected static
  network's cross-fitted score (with no static network: the static rule's floor) and, if COST_BOUND is set,
  whose dollars are within the bound. If none qualifies there is no dynamic policy and P3 is void. It is frozen as
  its order (recomputed on all 200 for the gain order), its tau and every prefix's aggregator fitted on all
  200.
  Dense refit. All 18 units, the aggregator fitted on all 200.
  Sonnet. sonnet_nothink:base:0 alone.

Usage: python -m analysis.pruning_select           # after G2a and G2b; refuses unless every input run is present
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

from autoagentnet.evidence.calibration import two_folds
from autoagentnet.pruning import search as S
from autoagentnet.pruning.replay import Panel, PluralityModel, fit, replay, score_of

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = ROOT / "research/v3/pruning/selected_static.json"
STEP = 0.0005
TAUS = [0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, 1.01]  # 1.01: never stop early (the full order)
MARGIN = {"bbeh": 0.01, "forecast": 0.005}  # accuracy points / Brier, in score units
COST_BOUND = None  # Kevin's choice before G2a: None = his rule as written; 0.8 = selected networks cost <= 0.8x Sonnet
AGGREGATOR = "ridge"  # the one switch for the rule's aggregator (replay.py): "ridge" = Kevin's; "weights" = weighted vote
PERSONAS = ("careful", "contrarian", "quick")
SMALL = ("haiku_nothink", "luna_none")
MID = ("sonnet_nothink", "sol61_low")
SONNET = "sonnet_nothink:base:0"
RUNS = {"bbeh": ["e13_bbeh_anth", "e13_bbeh_open", "e22_persona_bbeh_anth", "e22_persona_bbeh_open"],
        "forecast": ["e14_forecast_anth", "e14_forecast_open", "e22_persona_forecast_anth", "e22_persona_forecast_open"]}
ITEMS = {"bbeh": "bbeh_phase2", "forecast": "forecast_sealed"}


def lockbox_units() -> list[str]:
    """The 18 units, in the order every panel here uses."""
    units = [f"{m}:base:{c}" for m in SMALL for c in range(5)]
    units += [f"{m}:base:0" for m in MID]
    units += [f"{m}:{p}:0" for m in SMALL for p in PERSONAS]
    return units


def layers(panel: Panel) -> dict[str, np.ndarray]:
    """NetAdapt's proposals: one per source (each persona prompt is its own source)."""
    return {name: part.index.to_numpy() for name, part in panel.units.groupby("source", sort=False)}


def build_panel(calls: pd.DataFrame, kind: str, items: list[str] | None = None) -> Panel:
    """The 18-unit panel from call rows (columns item, source = "ref:prompt", call, answer/prob, parsed, correct,
    outcome, cost_usd, seconds), restricted to `items` when given."""
    calls = calls.assign(unit=calls["source"] + ":" + calls["call"].astype(int).astype(str))
    calls = calls[calls["unit"].isin(set(lockbox_units()))]
    if items is not None:
        calls = calls[calls["item"].isin(set(items))]
    if kind == "forecast":
        calls = calls.assign(prob=calls["prob"].where(calls["parsed"].astype(bool) & calls["prob"].notna(), 0.5))
    rank = {u: k for k, u in enumerate(lockbox_units())}
    calls = calls.assign(rank=calls["unit"].map(rank)).sort_values(["rank"], kind="stable").drop(columns=["rank", "unit"])
    if "seconds" not in calls:
        calls = calls.assign(seconds=0.0)
    return Panel.from_calls(calls, kind="prob" if kind == "forecast" else "choice")


def strata_of(panel: Panel, kind: str) -> np.ndarray:
    if kind == "bbeh":
        return np.array([i.split("-")[1] if i.startswith("bbeh-") else "all" for i in panel.items])
    return np.zeros(panel.n, dtype=int)


def pooled(panel: Panel, per_direction: list, folds, refit: str = AGGREGATOR) -> dict:
    """Cross-fitted score and dollars of one network per direction (kept masks), pooled over items."""
    frames = []
    for (sr, er), kept in zip(S.directions(folds), per_direction):
        frames.append(replay(panel, kept, er, fit(panel, kept, sr, refit)))
    frame = pd.concat(frames)
    return {"score": score_of(frame, panel.kind), "dollars": float(frame["dollars"].mean())}


def at_budget(path: pd.DataFrame, budget: float) -> str | None:
    """The kept units of a NetAdapt path's first (largest) network costing at most `budget`; None if none does."""
    fits = path[path["dollars"] <= budget + 1e-12]
    return None if fits.empty else str(fits["kept"].iloc[0])


def netadapt_table(panel: Panel, folds) -> tuple[pd.DataFrame, list]:
    """One row per budget (every step cost of either half's path): the two halves' networks at that budget and
    their pooled cross-fitted score and dollars."""
    lay = layers(panel)
    dirs = S.directions(folds)
    paths = [S.s2_netadapt(panel, lay, sr, None, STEP, refit=AGGREGATOR) for sr, er in dirs]
    budgets = sorted({float(d) for p in paths for d in p["dollars"]})
    rows = []
    for b in budgets:
        kept = [at_budget(p, b) for p in paths]
        if None in kept:
            continue
        rows.append({"budget": b, **pooled(panel, [panel.mask(k.split("+")) for k in kept], folds), "kept": " / ".join(kept)})
    return pd.DataFrame(rows), paths


def pick(table: pd.DataFrame, floor: float, max_dollars: float = np.inf) -> pd.Series | None:
    """The cheapest row with score >= floor and dollars <= max_dollars; None if there is none (no fallback)."""
    ok = table[(table["score"] >= floor - 1e-12) & (table["dollars"] <= max_dollars + 1e-12)]
    if ok.empty:
        return None
    return ok.sort_values(["dollars", "score"], ascending=[True, False], kind="stable").iloc[0]


def cheapest_first(panel: Panel, rows) -> list[int]:
    cost = panel.mean_cost(rows)
    frame = pd.DataFrame({"unit": range(panel.m), "dollars": cost}).sort_values("dollars", kind="stable")
    return frame["unit"].tolist()


def dynamic_table(panel: Panel, folds, orders=("cheapest-first", "gain per $")) -> pd.DataFrame:
    rows = []
    dirs = S.directions(folds)
    prefixes = [S.Prefixes(panel, sr, AGGREGATOR) for sr, er in dirs]
    for rule in orders:
        for tau in TAUS:
            frames = []
            for (sr, er), pre in zip(dirs, prefixes):
                order = (cheapest_first(panel, sr) if rule == "cheapest-first"
                         else S.gain_order(panel, list(range(panel.m)), sr, tau, prefixes=pre))
                frames.append(S.dynamic_replay(panel, order, tau, sr, er, prefixes=pre))
            f = pd.concat(frames)
            score = float(-f["brier"].mean()) if panel.kind == "prob" else float(f["correct"].mean())
            rows.append({"order": rule, "tau": tau, "score": score, "dollars": float(f["dollars"].mean()),
                         "calls": float(f["rounds"].mean())})
    return pd.DataFrame(rows)


def weights_dict(panel: Panel, w) -> dict | None:
    """A fitted aggregator as JSON: Kevin's (feature groups by unit name, coefficients) or a weighted vote."""
    if w is None:
        return None
    names = panel.units["unit"].tolist()
    if isinstance(w, PluralityModel):
        return {"aggregator": "plurality", "kind": w.kind, "groups": [[names[u] for u in g] for g in w.groups],
                "beta": [float(b) for b in w.beta]}
    return {"aggregator": "weights", "units": dict(zip(names, map(float, w[:panel.m]))), "intercept": float(w[panel.m])}


def select(panel: Panel, kind: str, seed: int = 0, orders=("cheapest-first", "gain per $"),
           cost_bound: float | None = COST_BOUND) -> dict:
    """The Phase 3B rule on a search panel; returns the frozen networks (None where the rule selects nothing),
    the void tests and the tables behind them."""
    folds = two_folds(panel.n, seed=seed, strata=strata_of(panel, kind))
    sonnet = panel.mask([SONNET])
    sonnet_score = score_of(replay(panel, sonnet), panel.kind)
    sonnet_dollars = float(panel.mean_cost()[sonnet].sum())
    max_dollars = np.inf if cost_bound is None else cost_bound * sonnet_dollars
    floor = sonnet_score - MARGIN[kind]
    na, _ = netadapt_table(panel, folds)
    static_row = pick(na, floor, max_dollars)
    every = np.arange(panel.n)
    names = panel.units["unit"].tolist()
    void = []
    static = None
    kept_names = None
    if static_row is not None:
        full_path = S.s2_netadapt(panel, layers(panel), every, None, STEP, refit=AGGREGATOR)
        kept_names = at_budget(full_path, float(static_row["budget"]))  # None: no full-data network fits the budget
    if kept_names is None:
        void += ["P1", "P2"]
    else:
        kept = panel.mask(kept_names.split("+"))
        static = {"budget": float(static_row["budget"]), "units": [names[u] for u in np.flatnonzero(kept)],
                  "weights": weights_dict(panel, fit(panel, kept, every, AGGREGATOR)),
                  "cross_fitted_score": float(static_row["score"]), "cross_fitted_dollars": float(static_row["dollars"])}
        if static["units"] == [SONNET]:
            void.append("P1")
    dyn = dynamic_table(panel, folds, orders)
    dyn_row = pick(dyn, floor if static is None else static["cross_fitted_score"], max_dollars)
    dynamic = None
    if dyn_row is None:
        void.append("P3")
    else:
        pre = S.Prefixes(panel, every, AGGREGATOR)
        order = (cheapest_first(panel, every) if dyn_row["order"] == "cheapest-first"
                 else S.gain_order(panel, list(range(panel.m)), every, float(dyn_row["tau"]), prefixes=pre))
        prefix_w = [weights_dict(panel, fit(panel, panel.mask([names[u] for u in order[:j]]), every, AGGREGATOR))
                    for j in range(1, len(order) + 1)]
        dynamic = {"order_rule": dyn_row["order"], "tau": float(dyn_row["tau"]), "order": [names[u] for u in order],
                   "prefix_weights": prefix_w, "cross_fitted_score": float(dyn_row["score"]),
                   "cross_fitted_dollars": float(dyn_row["dollars"])}
    if static is None and "P3" not in void:
        void.append("P3")  # P3 compares the dynamic policy with a static network that does not exist
    return {
        "kind": kind, "n_items": panel.n, "sonnet_score": sonnet_score, "sonnet_dollars": sonnet_dollars,
        "cost_bound": cost_bound, "static": static, "dynamic": dynamic, "void": sorted(set(void)),
        "dense": {"units": names, "weights": weights_dict(panel, fit(panel, panel.all_units(), every, AGGREGATOR))},
        "tables": {"netadapt": na.to_dict("records"), "dynamic": dyn.to_dict("records")},
    }


# ---------------------------------------------------------------------------------------------------------
# applying a frozen selection to new items (the lockbox)

def frozen_w(panel: Panel, weights: dict):
    """The aggregator weights_dict() stored, rebuilt on another panel's units (matched by name)."""
    position = {u: k for k, u in enumerate(panel.units["unit"])}
    if weights.get("aggregator", "weights") == "plurality":
        groups = [np.array([position[u] for u in g], dtype=int) for g in weights["groups"]]
        return PluralityModel(weights["kind"], groups, np.array(weights["beta"], dtype=float))
    w = np.zeros(panel.m + 1)
    for u, v in weights["units"].items():
        w[position[u]] = v
    w[panel.m] = weights["intercept"]
    return w


def apply_frozen(panel: Panel, sel: dict) -> pd.DataFrame:
    """Per item: score contribution (correct, or minus the squared error) and dollars of Sonnet, the static
    network, the dense refit and the dynamic policy, all frozen from `sel` (no fitting on these items)."""
    def per_item(frame):
        return -frame["brier"].to_numpy() if panel.kind == "prob" else frame["correct"].to_numpy()

    out = {"item": panel.items}
    nan = np.full(panel.n, np.nan)
    static = sel["static"] or {"units": None, "weights": None}
    for name, units, weights in (("sonnet", [SONNET], None), ("static", static["units"], static["weights"]),
                                 ("dense", sel["dense"]["units"], sel["dense"]["weights"])):
        if units is None:  # the rule selected no static network
            out[f"{name}_score"], out[f"{name}_dollars"] = nan, nan
            continue
        kept = panel.mask(units)
        frame = replay(panel, kept, None, None if weights is None else frozen_w(panel, weights))
        out[f"{name}_score"] = per_item(frame)
        out[f"{name}_dollars"] = frame["dollars"].to_numpy()
    d = sel["dynamic"]
    if d is None:
        out["dynamic_score"], out["dynamic_dollars"] = nan, nan
        return pd.DataFrame(out)
    names = panel.units["unit"].tolist()
    order = [names.index(u) for u in d["order"]]
    pre = S.Prefixes(panel, np.arange(panel.n))
    for j in range(1, len(order) + 1):
        pre.cache[tuple(order[:j])] = (panel.mask(d["order"][:j]), frozen_w(panel, d["prefix_weights"][j - 1]))
    f = S.dynamic_replay(panel, order, d["tau"], np.arange(panel.n), np.arange(panel.n), prefixes=pre)
    out["dynamic_score"] = -f["brier"].to_numpy() if panel.kind == "prob" else f["correct"].to_numpy()
    out["dynamic_dollars"] = f["dollars"].to_numpy()
    return pd.DataFrame(out)


# ---------------------------------------------------------------------------------------------------------

def read_calls(kind: str) -> pd.DataFrame | None:
    frames = [pd.read_csv(RESULTS / r / "calls.csv", dtype={"answer": str}) for r in RUNS[kind]
              if (RESULTS / r / "calls.csv").exists()]
    return pd.concat(frames, ignore_index=True) if len(frames) == len(RUNS[kind]) else None


def main() -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: the selection is frozen; it is never rewritten")
    sealed = ROOT / "research/v3/evidence/sealed"
    missing = [r for kind in RUNS for r in RUNS[kind] if not (RESULTS / r / "calls.csv").exists()]
    if missing:
        raise SystemExit(f"not selecting: the selection is frozen once, from complete inputs; missing {missing}")
    out = {"rule": "analysis/pruning_select.py (docstring), research/v3/pruning/selection_rule.md",
           "cost_bound": COST_BOUND, "inputs": {}}
    for kind in ("bbeh", "forecast"):
        items = [x for x in (sealed / f"{ITEMS[kind]}.txt").read_text().splitlines() if x]
        panel = build_panel(read_calls(kind), kind, items)
        out[kind] = select(panel, kind)
        out["inputs"][kind] = {r: hashlib.sha256((RESULTS / r / "calls.csv").read_bytes()).hexdigest() for r in RUNS[kind]}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(f"wrote {OUT}")


if __name__ == "__main__":
    main()
