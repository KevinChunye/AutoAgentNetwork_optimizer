"""Phase 3C rebuilt around cascades (session E4; Kevin's K2-K4): the selection rule (step 3.2), frozen into
research/v3/pruning/selected.json, and the one read of the lockbox per task (step 3.3), written to
research/v3/pruning/lockbox_bbeh.md and lockbox_forecast.md. Definitions of every term are in
autoagentnet/pruning/cascade.py.

Search data (BBEH). The 300 Phase 1 items (research/v3/evidence/sealed/bbeh_sealed.txt; runs e13_bbeh_*) for the
base-prompt first rounds, and the 200 Phase 2 items (bbeh_phase2.txt; runs e13_bbeh_* and e22_persona_bbeh_*) for the
persona first rounds. A unit is one call slot, "ref:prompt:call". An unparsed BBEH call is in no answer class and
counts as wrong.

First rounds (FIRST_ROUNDS): Haiku x3, Haiku x5, Luna x3, Luna x5, Haiku x3 + Luna x3 (H7's), Haiku x2 + Luna x2, and
on the Phase 2 items the persona versions: 3 Haiku personas (careful, contrarian, quick), 3 Luna personas, and both.
Escalation models: Sonnet (sonnet_nothink call 0) or Sol (sol61_low call 0).

The rule (3.2).
  1. For every first round and escalation model, cross-fit on two folds (balanced within each BBEH task, seed 0): on
     each fold, the source accuracies (the weights) and the threshold t come from the other fold, t by
     Learn-then-Test at alpha = ALPHA (0.10, delta 0.05); the policy is replayed on the fold. Pooled over both folds:
     accuracy, dollars, acceptance, accepted-wrong, seconds, tokens and rounds per item. Acceptance is also recorded
     at alpha 0.05 and 0.20.
  2. A policy qualifies when its cross-fitted accuracy is at least Sonnet's accuracy on the same items minus MARGIN
     (1 point) and it accepts at least one item (a policy that accepts nothing is the escalation model plus the first
     round's cost; with Sonnet as escalation C1 would compare Sonnet with itself). The selected policy is the qualifying one with the lowest cross-fitted dollars per item (ties: higher
     accuracy, then the order of FIRST_ROUNDS and ESCALATIONS). None qualifies: no policy, and C1 and C2 are void.
  3. Frozen: the selected first round's source accuracies and its threshold, both computed on all its search items
     (t by Learn-then-Test at ALPHA; the thresholds at 0.05 and 0.20 are recorded too). If no threshold is certified
     on all items (the frozen policy would accept nothing), C1 is void.
  4. C2's mixed-vendor first round: among the first rounds that mix Anthropic and OpenAI calls, the one with the
     highest cross-fitted acceptance at ALPHA (ties: lower first-round dollars). It and Haiku x5 are frozen the same
     way, each with its own threshold at ALPHA.
  ForecastBench (exploratory, K3): the same first rounds without personas on the 300 Phase 1 questions
  (forecast_all.txt; e14_forecast_*), escalating when the spread of the first round's log-odds is above s. Per
  first round and escalation model, s is chosen on each fold as the cheapest grid value whose Brier score is at
  most the reference's plus 0.005 on that fold (none: never selected) and scored on the other; the selected policy
  is the cheapest whose cross-fitted Brier is within 0.005 of the reference's. The reference is Sol alone since
  deviation 29 (audit 60; it was Sonnet, whose Brier Sol matches at about half the dollars). An unparsed forecast
  counts as 0.5.

The lockbox read (3.3; preregistered in research/v3/pruning/prereg_cascade.md and the e31_lockbox_* configs).
  C1  frozen policy minus Sonnet, accuracy, paired by item: one-sided item-bootstrap p-value (stratified by task)
      for "the mean difference is at or below -5 points" (non-inferiority). The dollar ratio is reported.
  C2  the frozen mixed-vendor first round's acceptance minus Haiku x5's (each at its own frozen threshold), paired:
      p-value for "at or below 0".
  C1b (exploratory) frozen policy minus its own escalation model alone (Sonnet or Sol), same test as C1: the cascade's
      own cost of stopping early, zero on every escalated item and so far less noisy than C1 when Sol escalates.
  C3  (a check, not a test) the frozen policy's accepted-wrong rate with its one-sided 95% upper bound (exact
      binomial, Clopper-Pearson); flagged when the point estimate is above alpha.
  Holm at 5% over the confirmatory ones among C1 and C2 (STATUS, set from the power simulation,
  research/v3/pruning/power_cascade.md). ForecastBench: the frozen spread policy minus Sol alone in Brier (the
  decision row, deviation 29), and minus Sonnet, each with the wider of the question and source x resolution-week
  bootstrap intervals (H10; deviation 31), the within-source interval, the leave-one-source-out range and a dollar
  ratio; read three ways on the wider interval (audits 61-62): its upper end
  at most +0.01 at under 0.5x Sol's dollars, a candidate; its lower end above 0, Sol is better; otherwise
  inconclusive. Exploratory.

Blind collection (K4). The e31 lockbox calls may be collected before selected.json exists, but this script reads
them only when selected.json is committed and unchanged in git (`lockbox` refuses otherwise), and nothing else in
the repository reads results/e31_*/calls.csv.

Usage: python -m analysis.pruning_cascade select     # once e13, e14 and e22 exist for both vendors and the G2a, G2b and
                                                     # Phase 2 reads are committed (audit 52); refuses to overwrite
       python -m analysis.pruning_cascade select-forecast   # ForecastBench alone, early (audit 63): only with Kevin's
                                                            # approval, or after Oct 30 under a logged deviation
       python -m analysis.pruning_cascade lockbox bbeh       # once selected.json is committed and both e31 BBEH runs exist
       python -m analysis.pruning_cascade lockbox forecast   # once selected.json or selected_forecast.json is committed
       python -m analysis.pruning_cascade frontier   # $0: every base-prompt cascade against Sol on the Phase 1 items
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import beta as beta_dist

from analysis.pruning_phase3a import md
from autoagentnet.evidence.calibration import two_folds
from autoagentnet.evidence.inference import bootstrap, holm, p_above, week_cluster
from autoagentnet.pruning import cascade as C
from autoagentnet.pruning.replay import Panel

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
SEALED = ROOT / "research/v3/evidence/sealed"
OUT = ROOT / "research/v3/pruning/selected.json"
FORECAST_OUT = ROOT / "research/v3/pruning/selected_forecast.json"  # the ForecastBench part frozen early (audit 63)
LOCKBOX_OUT = {k: ROOT / f"research/v3/pruning/lockbox_{k}.md" for k in ("bbeh", "forecast")}
ALPHA, MARGIN, BRIER_MARGIN = 0.10, 0.01, 0.005
C1_MARGIN = -0.05
STATUS = {"C1": "expl", "C2": "expl"}  # set from research/v3/pruning/power_cascade.md (the 70% rule)
N_BOOT = 2000
PERSONAS = ("careful", "contrarian", "quick")
SONNET = "sonnet_nothink:base:0"
ESCALATIONS = {"sonnet": SONNET, "sol": "sol61_low:base:0"}
FORECAST_REFERENCE = ESCALATIONS["sol"]  # deviation 29 (audit 60): Sol alone, not Sonnet, is the forecasting reference


def base(ref: str, k: int) -> list[str]:
    return [f"{ref}:base:{c}" for c in range(k)]


def personas(ref: str) -> list[str]:
    return [f"{ref}:{p}:0" for p in PERSONAS]


FIRST_ROUNDS = {
    "haiku x3": base("haiku_nothink", 3), "haiku x5": base("haiku_nothink", 5),
    "luna x3": base("luna_none", 3), "luna x5": base("luna_none", 5),
    "haiku x3 + luna x3": base("haiku_nothink", 3) + base("luna_none", 3),
    "haiku x2 + luna x2": base("haiku_nothink", 2) + base("luna_none", 2),
    "haiku personas x3": personas("haiku_nothink"), "luna personas x3": personas("luna_none"),
    "haiku personas x3 + luna personas x3": personas("haiku_nothink") + personas("luna_none"),
}
MIXED = [name for name in FIRST_ROUNDS if "haiku" in name and "luna" in name]
FORECAST_ROUNDS = [name for name in FIRST_ROUNDS if "personas" not in name]
SPREADS = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]  # log-odds spreads tried for the ForecastBench cascade
RUNS = {"bbeh": ["e13_bbeh_anth", "e13_bbeh_open", "e22_persona_bbeh_anth", "e22_persona_bbeh_open"],
        "forecast": ["e14_forecast_anth", "e14_forecast_open"]}
LOCKBOX_RUNS = {"bbeh": ["e31_lockbox_bbeh_anth", "e31_lockbox_bbeh_open"],
                "forecast": ["e31_lockbox_forecast_anth", "e31_lockbox_forecast_open"]}


def build(calls: pd.DataFrame, kind: str, units: list[str], items: list[str] | None = None) -> Panel:
    """A panel of the given units from call rows (source = "ref:prompt"), restricted to `items` when given, units in
    the order given. Items missing a unit are dropped (Panel.from_calls)."""
    calls = calls.assign(unit=calls["source"] + ":" + calls["call"].astype(int).astype(str))
    calls = calls[calls["unit"].isin(set(units))]
    if items is not None:
        calls = calls[calls["item"].isin(set(items))]
    if kind == "forecast":
        calls = calls.assign(prob=calls["prob"].where(calls["parsed"].astype(bool) & calls["prob"].notna(), 0.5))
    rank = {u: k for k, u in enumerate(units)}
    calls = calls.assign(rank=calls["unit"].map(rank)).sort_values("rank", kind="stable").drop(columns=["rank", "unit"])
    if "seconds" not in calls:
        calls = calls.assign(seconds=0.0)
    return Panel.from_calls(calls, kind="prob" if kind == "forecast" else "choice")


def strata_of(panel: Panel) -> np.ndarray:
    return np.array([i.split("-")[1] if i.startswith("bbeh-") else "all" for i in panel.items])


def search_panels(calls: pd.DataFrame) -> dict[str, Panel]:
    """"base": the base-prompt units on the 300 Phase 1 items; "persona": every unit on the 200 Phase 2 items."""
    everything = sorted({u for units in FIRST_ROUNDS.values() for u in units} | set(ESCALATIONS.values()))
    plain = [u for u in everything if ":base:" in u]
    return {"base": build(calls, "bbeh", plain, read_items("bbeh_sealed")),
            "persona": build(calls, "bbeh", everything, read_items("bbeh_phase2"))}


def panel_for(panels: dict, name: str) -> Panel:
    return panels["persona"] if "personas" in name else panels["base"]


def policy_table(panels: dict, seed: int = 0) -> pd.DataFrame:
    """Step 1 of the rule: every (first round, escalation model), cross-fitted."""
    rows = []
    for name, units in FIRST_ROUNDS.items():
        panel = panel_for(panels, name)
        folds = two_folds(panel.n, seed=seed, strata=strata_of(panel))
        sonnet = panel.correct_matrix()[:, C.unit_positions(panel, [SONNET])[0]]
        for esc_name, esc in ESCALATIONS.items():
            frame, chosen = C.cross_fit(panel, units, esc, folds, ALPHA)
            row = {"first round": name, "escalation": esc_name, "items": panel.n, **C.summary(frame),
                   "sonnet accuracy": float(sonnet.mean()),
                   "sonnet dollars": float(panel.cost[:, C.unit_positions(panel, [SONNET])[0]].mean()),
                   "t fold 0": chosen[0], "t fold 1": chosen[1]}
            for a in C.ALPHAS:
                if a != ALPHA:
                    other, _ = C.cross_fit(panel, units, esc, folds, a)
                    row[f"acceptance at {a}"] = float(other["accepted"].mean())
            row[f"acceptance at {ALPHA}"] = row["acceptance"]
            # a policy that accepts nothing is Sonnet or Sol plus the first round's cost: it never qualifies (audit 49's
            # trap: C1 would compare Sonnet with itself and pass for free)
            row["qualifies"] = bool(row["accuracy"] >= row["sonnet accuracy"] - MARGIN - 1e-12 and row["acceptance"] > 0)
            rows.append(row)
    return pd.DataFrame(rows)


def freeze(panel: Panel, name: str, escalation: str | None) -> dict:
    """A first round (and escalation unit) frozen on all its search items: source accuracies and thresholds."""
    units = FIRST_ROUNDS[name]
    acc = C.search_accuracy(panel, units)
    first = C.first_round(panel, units, acc)
    thresholds = {str(a): C.ltt(first["share"], first["correct"], a) for a in C.ALPHAS}
    return {"first round": name, "units": units, "escalation": escalation, "accuracy by source": acc.to_dict(),
            "t": thresholds[str(ALPHA)], "t by alpha": thresholds, "alpha": ALPHA, "delta": C.DELTA,
            "search acceptance": float((first["share"] >= (np.inf if thresholds[str(ALPHA)] is None
                                                           else thresholds[str(ALPHA)]) - 1e-9).mean())}


def select(panels: dict, seed: int = 0) -> dict:
    """Steps 1-4 of the rule. Returns the frozen policy (None when nothing qualifies), the frozen C2 pair, the void
    tests and the cross-fitted table."""
    table = policy_table(panels, seed)
    order = {name: k for k, name in enumerate(FIRST_ROUNDS)}
    ranked = table.assign(r1=table["first round"].map(order), r2=table["escalation"].map(list(ESCALATIONS).index))
    qualifying = ranked[ranked["qualifies"]].sort_values(["dollars", "accuracy", "r1", "r2"],
                                                         ascending=[True, False, True, True])
    out = {"policy": None, "c2": None, "void": [], "table": table.to_dict(orient="records")}
    if qualifying.empty:
        out["void"] = ["C1", "C2"]
        return out
    best = qualifying.iloc[0]
    out["policy"] = freeze(panel_for(panels, best["first round"]), best["first round"], ESCALATIONS[best["escalation"]])
    if out["policy"]["t"] is None:  # cross-fitted it accepted items, but on all search items no threshold is certified
        out["void"].append("C1")
    mixed = ranked[ranked["first round"].isin(MIXED) & (ranked["escalation"] == "sonnet")]
    first_dollars = {name: float(panel_for(panels, name).cost[:, C.unit_positions(panel_for(panels, name), units)].sum(axis=1).mean())
                     for name, units in FIRST_ROUNDS.items()}
    mixed = mixed.assign(first_dollars=mixed["first round"].map(first_dollars)).sort_values(
        ["acceptance", "first_dollars", "r1"], ascending=[False, True, True])
    pick = mixed.iloc[0]["first round"]
    out["c2"] = {"mixed": freeze(panel_for(panels, pick), pick, None),
                 "haiku x5": freeze(panels["base"], "haiku x5", None)}
    return out


def forecast_cross_fit(panel: Panel, units, esc: str, folds) -> tuple[pd.DataFrame, dict]:
    """ForecastBench spread cascade, cross-fitted: s chosen on the other fold (cheapest grid value whose Brier is
    within BRIER_MARGIN of the reference's, Sol alone since deviation 29; none: the fold's policy never accepts,
    i.e. always escalates)."""
    ref_g = C.unit_positions(panel, [FORECAST_REFERENCE])[0]
    parts, chosen = [], {}
    for f in np.unique(folds):
        fit, test = np.flatnonzero(folds != f), np.flatnonzero(folds == f)
        ref_brier = float(((panel.votes[fit, ref_g] - panel.outcome[fit]) ** 2).mean())
        options = []
        for s in SPREADS:
            r = C.forecast_replay(panel, units, esc, s, fit)
            if r["brier"].mean() <= ref_brier + BRIER_MARGIN:
                options.append((float(r["dollars"].mean()), s))
        s = min(options)[1] if options else -1.0  # -1: every spread is above it, so every item escalates
        parts.append(C.forecast_replay(panel, units, esc, s, test).assign(fold=f, s=s))
        chosen[int(f)] = s
    return pd.concat(parts), chosen


def forecast_table(calls: pd.DataFrame, seed: int = 0) -> tuple[Panel, pd.DataFrame]:
    """Every ForecastBench (first round, escalation) cross-fitted on the 300 Phase 1 questions, beside the reference
    (Sol alone, deviation 29) and Sonnet alone: Brier, dollars per question, escalation rate, the spread s chosen
    on each fold."""
    units = sorted({u for n in FORECAST_ROUNDS for u in FIRST_ROUNDS[n]} | set(ESCALATIONS.values()))
    panel = build(calls, "forecast", units, read_items("forecast_all"))
    folds = two_folds(panel.n, seed=seed)
    alone = {}
    for name, unit in (("reference", FORECAST_REFERENCE), ("sonnet", SONNET)):
        g = C.unit_positions(panel, [unit])[0]
        alone[name] = (float(((panel.votes[:, g] - panel.outcome) ** 2).mean()), float(panel.cost[:, g].mean()))
    rows = []
    for name in FORECAST_ROUNDS:
        for esc_name, esc in ESCALATIONS.items():
            frame, chosen = forecast_cross_fit(panel, FIRST_ROUNDS[name], esc, folds)
            rows.append({"first round": name, "escalation": esc_name, "brier": float(frame["brier"].mean()),
                         "dollars": float(frame["dollars"].mean()), "escalated": float(frame["escalated"].mean()),
                         "reference brier": alone["reference"][0], "reference dollars": alone["reference"][1],
                         "sonnet brier": alone["sonnet"][0], "s fold 0": chosen[0], "s fold 1": chosen[1]})
    return panel, pd.DataFrame(rows)


def select_forecast(calls: pd.DataFrame, seed: int = 0) -> dict:
    panel, table = forecast_table(calls, seed)
    ref_g = C.unit_positions(panel, [FORECAST_REFERENCE])[0]
    ref_brier = float(((panel.votes[:, ref_g] - panel.outcome) ** 2).mean())
    ok = table[table["brier"] <= ref_brier + BRIER_MARGIN].sort_values(["dollars", "brier"])
    out = {"policy": None, "table": table.to_dict(orient="records")}
    if not ok.empty:
        best = ok.iloc[0]
        units, esc = FIRST_ROUNDS[best["first round"]], ESCALATIONS[best["escalation"]]
        options = [(float(C.forecast_replay(panel, units, esc, s)["dollars"].mean()), s) for s in SPREADS
                   if C.forecast_replay(panel, units, esc, s)["brier"].mean() <= ref_brier + BRIER_MARGIN]
        out["policy"] = {"first round": best["first round"], "units": units, "escalation": esc,
                         "s": min(options)[1] if options else -1.0, "reference": FORECAST_REFERENCE}
    return out


BASE_ROUNDS = [name for name in FIRST_ROUNDS if "personas" not in name]
SOL_GAP, SOL_RATIO = 0.02, 0.8  # audit 59: within 2 points of Sol at no more than 0.8x its dollars


def frontier_vs_sol(panel: Panel, seed: int = 0) -> pd.DataFrame:
    """Every base-prompt cascade against Sol alone on the same items ($0, audit 59 item 2). Two kinds of row:
    "cross-fitted" is the rule's own replay (thresholds by Learn-then-Test on the other fold at alpha 0.05, 0.10,
    0.20); "in-sample" replays every grid threshold on all items, which picks the threshold after seeing the
    labels and so flatters the cascade (an upper envelope). Columns: accuracy and dollars per item, accuracy minus
    Sol's (points), dollars over Sol's, and "near Sol" = within SOL_GAP of Sol at no more than SOL_RATIO its dollars."""
    o = C.unit_positions(panel, [ESCALATIONS["sol"]])[0]
    sol_acc, sol_usd = float(panel.correct_matrix()[:, o].mean()), float(panel.cost[:, o].mean())
    folds = two_folds(panel.n, seed=seed, strata=strata_of(panel))
    rows = []
    for name in BASE_ROUNDS:
        units = FIRST_ROUNDS[name]
        first = C.first_round(panel, units, C.search_accuracy(panel, units))
        for esc_name, esc in ESCALATIONS.items():
            for a in C.ALPHAS:
                frame, _ = C.cross_fit(panel, units, esc, folds, a)
                rows.append({"first round": name, "escalation": esc_name, "kind": "cross-fitted", "setting": f"alpha {a}",
                             **C.summary(frame)})
            esc_frame = C.escalation(panel, esc)
            for t in C.THRESHOLDS:
                rows.append({"first round": name, "escalation": esc_name, "kind": "in-sample", "setting": f"t {t:.2f}",
                             **C.summary(C.replay(first, esc_frame, float(t)))})
    table = pd.DataFrame(rows)
    table = table.assign(minus_sol=100 * (table["accuracy"] - sol_acc), ratio_to_sol=table["dollars"] / sol_usd)
    return table.assign(near_sol=(table["minus_sol"] >= -100 * SOL_GAP - 1e-9) & (table["ratio_to_sol"] <= SOL_RATIO))


def frontier_main() -> None:
    """Writes research/v3/pruning/frontier_sol.md from the Phase 1 BBEH calls (read at G2a; no Phase 2 data)."""
    calls = read_runs(RUNS["bbeh"][:2])
    units = sorted({u for n in BASE_ROUNDS for u in FIRST_ROUNDS[n]} | set(ESCALATIONS.values()))
    panel = build(calls, "bbeh", units, read_items("bbeh_sealed"))
    table = frontier_vs_sol(panel)
    o = C.unit_positions(panel, [ESCALATIONS["sol"]])[0]
    best = (table.sort_values(["minus_sol", "dollars"], ascending=[False, True])
            .groupby(["kind", "first round", "escalation"], sort=False).head(1))
    cheap = table[table["ratio_to_sol"] <= SOL_RATIO].sort_values(["minus_sol", "dollars"], ascending=[False, True])
    cols = ["kind", "first round", "escalation", "setting", "accuracy", "acceptance", "minus_sol", "ratio_to_sol"]
    lines = ["# Phase 3C: the cascade frontier against Sol alone (search data, $0)", "",
             "Written by `python -m analysis.pruning_cascade frontier` (audit 59, item 2) from the Phase 1 BBEH calls "
             f"(e13_bbeh_*; {panel.n} sealed items, read at G2a; no Phase 2 data). Definitions: `frontier_vs_sol`.", "",
             f"Sol alone: accuracy {panel.correct_matrix()[:, o].mean():.1%}, ${panel.cost[:, o].mean():.4f} per item. "
             f"Criterion: within {100 * SOL_GAP:.0f} points of Sol at no more than {SOL_RATIO}x its dollars. "
             f"Rows meeting it: {int(table['near_sol'].sum())} of {len(table)} "
             f"({int(table.loc[table['kind'] == 'cross-fitted', 'near_sol'].sum())} cross-fitted).", "",
             "## The most accurate setting of each cascade", "", md(best[cols]), "",
             f"## The most accurate settings at no more than {SOL_RATIO}x Sol's dollars", "", md(cheap[cols].head(10)), ""]
    out = ROOT / "research/v3/pruning/frontier_sol.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines))
    forecast_frontier_main()


def forecast_frontier_main() -> None:
    """Writes research/v3/pruning/frontier_forecast.md: the ForecastBench rule's cross-fitted table on the 300 Phase 1
    questions (e14_forecast_*, read at G2b) against Sol alone, and the policy the rule would freeze from it ($0, audit
    60 item 2). The rule picks the cheapest of 12 candidates on these questions, so its row flatters it; the lockbox
    is its test."""
    panel, table = forecast_table(read_runs(RUNS["forecast"]))
    sel = select_forecast(read_runs(RUNS["forecast"]))
    table = table.assign(minus_sol=table["brier"] - table["reference brier"],
                         ratio_to_sol=table["dollars"] / table["reference dollars"])
    table = table.sort_values(["dollars", "brier"])
    cols = ["first round", "escalation", "brier", "minus_sol", "ratio_to_sol", "escalated", "s fold 0", "s fold 1"]
    pol = sel["policy"]
    picked = "none qualifies" if pol is None else (f"{pol['first round']}, escalating to {pol['escalation']} when the "
                                                   f"spread of its log-odds is above {pol['s']}")
    lines = ["# Phase 3C: the ForecastBench cascade frontier against Sol alone (search data, $0)", "",
             "Written by `python -m analysis.pruning_cascade frontier` (audit 60, item 2) from e14_forecast_* "
             f"({panel.n} Phase 1 questions, read at G2b). Definitions: `forecast_table` and the module docstring.", "",
             f"Sol alone: Brier {table['reference brier'].iloc[0]:.4f}, ${table['reference dollars'].iloc[0]:.5f} per "
             f"question; Sonnet alone: Brier {table['sonnet brier'].iloc[0]:.4f}. The rule (deviation 29): the cheapest "
             f"policy whose cross-fitted Brier is within {BRIER_MARGIN} of Sol's.", "",
             f"**The rule would freeze: {picked}.** It is the cheapest of {len(table)} candidates chosen on these "
             "questions, so its row is optimistic; the 200 lockbox questions (data-series only) are its test.", "",
             md(table[cols], 4), ""]
    out = ROOT / "research/v3/pruning/frontier_forecast.md"
    out.write_text("\n".join(lines))
    print("\n".join(lines))


def read_items(name: str) -> list[str]:
    return [x for x in (SEALED / f"{name}.txt").read_text().splitlines() if x]


def read_runs(runs: list[str]) -> pd.DataFrame | None:
    paths = [RESULTS / r / "calls.csv" for r in runs]
    if not all(p.exists() for p in paths):
        return None
    return pd.concat([pd.read_csv(p, dtype={"answer": str}) for p in paths], ignore_index=True)


READS_FIRST = [ROOT / "research/v3/evidence/phase1_bbeh.md", ROOT / "research/v3/evidence/phase1_forecast.md",
               ROOT / "research/v3/evidence/phase2.md"]  # the committed G2a, G2b and Phase 2 reads (audit 52)


def early_forecast() -> dict | None:
    """The ForecastBench selection frozen early by `select-forecast`, if it exists. It must be committed unchanged
    (audit 64): an uncommitted file stops the full selection rather than being copied or recomputed over."""
    if not FORECAST_OUT.exists():
        return None
    if not committed(FORECAST_OUT):
        raise SystemExit(f"not selecting: {FORECAST_OUT.name} exists but is not committed unchanged")
    return json.loads(FORECAST_OUT.read_text())["forecast"]


def select_main() -> None:
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: the selection is frozen; it is never rewritten")
    unread = [p.name for p in READS_FIRST if not p.exists() or not committed(p)]
    if unread:
        raise SystemExit(f"not selecting: the selection reads sealed Phase 1-2 labels, so the committed reads come "
                         f"first; missing or uncommitted: {unread}")
    missing = [r for kind in RUNS for r in RUNS[kind] if not (RESULTS / r / "calls.csv").exists()]
    if missing:
        raise SystemExit(f"not selecting: the selection is frozen once, from complete inputs; missing {missing}")
    sel = select(search_panels(read_runs(RUNS["bbeh"])))
    out = {"rule": "analysis/pruning_cascade.py (docstring), research/v3/pruning/selection_rule.md",
           "bbeh": sel, "forecast": early_forecast() or select_forecast(read_runs(RUNS["forecast"])),
           "inputs": {r: hashlib.sha256((RESULTS / r / "calls.csv").read_bytes()).hexdigest()
                      for kind in RUNS for r in RUNS[kind]}}
    OUT.write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(f"wrote {OUT}")


# ---------------------------------------------------------------------------------------------------------
# the lockbox read

def committed(path: Path) -> bool:
    """True when `path` is tracked in git and its working copy matches HEAD."""
    rel = str(path.relative_to(ROOT))
    tracked = subprocess.run(["git", "ls-files", "--error-unmatch", rel], cwd=ROOT, capture_output=True).returncode == 0
    clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", rel], cwd=ROOT, capture_output=True).returncode == 0
    return tracked and clean


def apply_policy(panel: Panel, frozen: dict) -> pd.DataFrame:
    """The frozen cascade on every item of `panel`, without refitting."""
    acc = pd.Series(frozen["accuracy by source"])
    first = C.first_round(panel, frozen["units"], acc)
    return C.replay(first, C.escalation(panel, frozen["escalation"]), frozen["t"])


def accepted_by(panel: Panel, frozen: dict) -> np.ndarray:
    first = C.first_round(panel, frozen["units"], pd.Series(frozen["accuracy by source"]))
    t = frozen["t"]
    return np.zeros(panel.n) if t is None else (first["share"].to_numpy() >= t - 1e-9).astype(float)


def upper_bound(x: int, n: int, level: float = 0.95) -> float:
    """One-sided Clopper-Pearson upper bound of a binomial rate."""
    return 1.0 if x >= n else float(beta_dist.ppf(level, x + 1, n - x))


def lockbox_tests(panel: Panel, bbeh: dict, status: dict = STATUS, seed: int = 0) -> pd.DataFrame:
    """C1, C2 (with Holm over the confirmatory ones) and the C3 check on the lockbox panel."""
    strata = strata_of(panel)
    rows = []
    if "C1" in bbeh["void"]:
        rows.append({"test": "C1", "status": "void"})
    else:
        policy = apply_policy(panel, bbeh["policy"])
        g = C.unit_positions(panel, [SONNET])[0]
        d = policy["correct"].to_numpy() - panel.correct_matrix()[:, g]
        res = bootstrap(lambda idx: float(d[idx].mean()), panel.n, strata=strata, n_boot=N_BOOT, seed=seed)
        cost = policy["dollars"].to_numpy() / panel.cost[:, g].mean()
        rows.append({"test": "C1", "comparison": "policy - Sonnet, accuracy", "difference": res["estimate"],
                     "lo": res["lo"], "hi": res["hi"], "margin": C1_MARGIN, "p": p_above(res["draws"], C1_MARGIN),
                     "dollar ratio": float(cost.mean()), "status": status["C1"]})
        e = C.unit_positions(panel, [bbeh["policy"]["escalation"]])[0]
        d_own = policy["correct"].to_numpy() - panel.correct_matrix()[:, e]
        own = bootstrap(lambda idx: float(d_own[idx].mean()), panel.n, strata=strata, n_boot=N_BOOT, seed=seed)
        rows.append({"test": "C1b", "comparison": "policy - its escalation model alone, accuracy (exploratory)",
                     "difference": own["estimate"], "lo": own["lo"], "hi": own["hi"], "margin": C1_MARGIN,
                     "p": p_above(own["draws"], C1_MARGIN), "status": "expl"})
        o = C.unit_positions(panel, [ESCALATIONS["sol"]])[0]
        d_sol = policy["correct"].to_numpy() - panel.correct_matrix()[:, o]
        sol = bootstrap(lambda idx: float(d_sol[idx].mean()), panel.n, strata=strata, n_boot=N_BOOT, seed=seed)
        rows.append({"test": "C1s", "comparison": "policy - Sol alone, accuracy (headline, exploratory; deviation 28)",
                     "difference": sol["estimate"], "lo": sol["lo"], "hi": sol["hi"],
                     "dollar ratio": float(policy["dollars"].mean() / panel.cost[:, o].mean()), "status": "expl"})
        for name, unit in (("Sonnet alone", SONNET), ("Sol alone", ESCALATIONS["sol"]), ("policy", None)):
            g2 = None if unit is None else C.unit_positions(panel, [unit])[0]
            right = policy["correct"].to_numpy() if unit is None else panel.correct_matrix()[:, g2]
            usd = policy["dollars"].to_numpy() if unit is None else panel.cost[:, g2]
            rows.append({"test": f"comparator: {name}", "comparison": "accuracy; dollars per item in 'dollars'",
                         "difference": float(right.mean()), "dollars": float(usd.mean()), "status": "descriptive"})
        x = int(policy["accepted_wrong"].sum())
        rows.append({"test": "C3", "comparison": "policy accepted-wrong rate (check)", "difference": x / panel.n,
                     "hi": upper_bound(x, panel.n), "margin": bbeh["policy"]["alpha"],
                     "status": "flag" if x / panel.n > bbeh["policy"]["alpha"] else "check"})
    if "C2" in bbeh["void"]:
        rows.append({"test": "C2", "status": "void"})
    else:
        d = accepted_by(panel, bbeh["c2"]["mixed"]) - accepted_by(panel, bbeh["c2"]["haiku x5"])
        res = bootstrap(lambda idx: float(d[idx].mean()), panel.n, strata=strata, n_boot=N_BOOT, seed=seed)
        rows.append({"test": "C2", "comparison": f"{bbeh['c2']['mixed']['first round']} - haiku x5, acceptance",
                     "difference": res["estimate"], "lo": res["lo"], "hi": res["hi"], "margin": 0.0,
                     "p": p_above(res["draws"], 0.0), "status": status["C2"]})
    out = pd.DataFrame(rows)
    if "p" not in out:
        return out
    conf = out[(out["status"] == "conf") & out["p"].notna()]
    if len(conf):
        decided = holm(dict(zip(conf["test"], conf["p"])))
        out = out.merge(decided[["test", "passes"]], on="test", how="left")
    return out


FORECAST_UPPER, FORECAST_RATIO = 0.01, 0.5  # the forecast lockbox's decision (deviation 29, audit 61)


def reading(lo: float, hi: float, ratio: float) -> str:
    """The three-way reading of the policy minus Sol in Brier (audit 61, pre-logged before any lockbox call)."""
    if hi <= FORECAST_UPPER and ratio < FORECAST_RATIO:
        return "candidate"
    if lo > 0:
        return "Sol is better"
    return "inconclusive"


def decision_interval(d: np.ndarray, source: np.ndarray, resolution: np.ndarray) -> tuple[str, dict]:
    """Bootstraps of the mean of the per-question differences d: over questions, over source x resolution-week
    clusters, and over questions within each source. Returns the name of the wider of the first two (H10: it is the
    decision interval) and all three."""
    mean = lambda idx: float(d[idx].mean())
    found = {"question": bootstrap(mean, len(d), n_boot=N_BOOT),
             "source x week": bootstrap(mean, len(d), clusters=week_cluster(source, resolution), n_boot=N_BOOT),
             "within source": bootstrap(mean, len(d), strata=source, n_boot=N_BOOT)}
    return max(("question", "source x week"), key=lambda k: found[k]["hi"] - found[k]["lo"]), found


def forecast_lockbox(panel: Panel, frozen: dict, source: np.ndarray, resolution: np.ndarray) -> list[str]:
    """The ForecastBench lockbox read: the frozen spread policy minus Sol alone (the decision row) and minus Sonnet
    alone, in Brier, paired by question. The decision interval follows the plan's H10 rule (deviation 31): the wider
    of two 95% bootstrap intervals, one resampling questions and one resampling source x resolution-week clusters
    (`week_cluster`; questions resolving the same week from the same source share outcomes). Beside it: the interval
    resampling questions within each source, and the range of the difference when each source is left out in turn.
    Dollar ratio: the policy's dollars per question over the comparator's."""
    r = C.forecast_replay(panel, frozen["units"], frozen["escalation"], frozen["s"])
    lines = [f"## ForecastBench ({panel.n} questions, exploratory)", ""]
    for name, unit in (("Sol alone (the decision row, deviation 29)", FORECAST_REFERENCE), ("Sonnet alone", SONNET)):
        g = C.unit_positions(panel, [unit])[0]
        d = r["brier"].to_numpy() - (panel.votes[:, g] - panel.outcome) ** 2
        primary, found = decision_interval(d, source, resolution)
        lo, hi = found[primary]["lo"], found[primary]["hi"]
        loo = [float(d[source != s].mean()) for s in sorted(set(source))]
        ratio = float(r["dollars"].mean() / panel.cost[:, g].mean())
        lines += [f"Spread policy minus {name}, Brier: {found['question']['estimate']:+.4f} ({primary}, the wider: "
                  f"{lo:+.4f} to {hi:+.4f}; " + "; ".join(f"{k} {v['lo']:+.4f} to {v['hi']:+.4f}" for k, v in found.items()
                                                           if k != primary)
                  + f"; leaving one source out {min(loo):+.4f} to {max(loo):+.4f}); dollar ratio {ratio:.2f}.", ""]
        if unit == FORECAST_REFERENCE:
            lines += [f"Reading (pre-logged, audits 61-62): **{reading(lo, hi, ratio)}**.", ""]
    return lines + [f"Escalated {r['escalated'].mean():.1%}.", ""]


def regrade(calls: pd.DataFrame, kind: str) -> pd.DataFrame:
    """The lockbox runs are collected blind (no `correct`, no `outcome` on disk; audit 52): grade them here, at the
    committed read, from the task file, exactly as the panel runner grades (unparsed = wrong)."""
    from autoagentnet.tasks import answers_match, load_tasks

    tasks = {t.id: t for t in load_tasks(ROOT / f"data/external/evidence/{kind}.jsonl")}
    if kind == "forecast":
        return calls.assign(outcome=[int(tasks[i].answer) for i in calls["item"]])
    right = [float(bool(p) and isinstance(a, str) and answers_match(tasks[i].answer, a, tasks[i].grader))
             for i, a, p in zip(calls["item"], calls["answer"], calls["parsed"])]
    return calls.assign(correct=right)


def frozen_selection() -> dict:
    """The committed selections by task: selected.json (both tasks), and selected_forecast.json (ForecastBench alone,
    frozen early by `select-forecast`), which takes precedence for ForecastBench. A file counts only when it is
    tracked in git and unchanged."""
    sel = {}
    if OUT.exists() and committed(OUT):
        sel = {k: v for k, v in json.loads(OUT.read_text()).items() if k in ("bbeh", "forecast")}
    if FORECAST_OUT.exists() and committed(FORECAST_OUT):
        sel["forecast"] = json.loads(FORECAST_OUT.read_text())["forecast"]
    return sel


def lockbox_main(kind: str) -> None:
    """The one read of one task's lockbox, written to research/v3/pruning/lockbox_<task>.md and never rewritten."""
    out = LOCKBOX_OUT[kind]
    if out.exists():
        raise SystemExit(f"{out} exists: the {kind} lockbox has been read; it is never read again")
    sel = frozen_selection()
    if kind not in sel:
        raise SystemExit(f"not reading the {kind} lockbox: its selection (selected.json, or selected_forecast.json for "
                         f"ForecastBench) must exist and be committed unchanged first")
    calls = read_runs(LOCKBOX_RUNS[kind])
    if calls is None:
        raise SystemExit(f"not reading the {kind} lockbox: a run is missing ({LOCKBOX_RUNS[kind]})")
    lines = [f"# Phase 3C: the {kind} lockbox read (cascades)", "",
             f"Written by `python -m analysis.pruning_cascade lockbox {kind}` from the committed selection and the "
             f"{', '.join(LOCKBOX_RUNS[kind])} calls. Tests and definitions: analysis/pruning_cascade.py.", ""]
    calls = regrade(calls, kind)
    if kind == "bbeh":
        units = sorted({u for units in FIRST_ROUNDS.values() for u in units} | set(ESCALATIONS.values()))
        panel = build(calls, "bbeh", units)
        lines += [f"## BBEH ({panel.n} items)", "", lockbox_tests(panel, sel["bbeh"]).round(4).to_csv(index=False), ""]
    elif sel["forecast"]["policy"] is None:
        lines += ["No ForecastBench policy qualified at selection, so there is nothing to test.", ""]
    else:
        from autoagentnet.tasks import load_tasks

        frozen = sel["forecast"]["policy"]
        units = sorted(set(frozen["units"]) | {frozen["escalation"], SONNET, FORECAST_REFERENCE})
        panel = build(calls, "forecast", units)
        meta = {t.id: t.meta for t in load_tasks(ROOT / "data/external/evidence/forecast.jsonl")}
        lines += forecast_lockbox(panel, frozen, np.array([meta[i]["source"] for i in panel.items]),
                                  np.array([meta[i]["resolution_date"] for i in panel.items]))
    out.write_text("\n".join(lines) + "\n")
    print(f"wrote {out}")


def select_forecast_main() -> None:
    """Freezes the ForecastBench part of the selection alone, into research/v3/pruning/selected_forecast.json (audit
    63, finding 5). Its rule reads only e14_forecast_*, read at G2b, and is deterministic, so freezing it before the
    Phase 2 read changes nothing but the date. Run it only once Kevin approves, or after Oct 30 under a logged
    deviation (research/log.md, audit 63)."""
    if FORECAST_OUT.exists():
        raise SystemExit(f"{FORECAST_OUT} exists: the ForecastBench selection is frozen; it is never rewritten")
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: the full selection already froze ForecastBench")
    g2b = READS_FIRST[1]
    if not g2b.exists() or not committed(g2b):
        raise SystemExit(f"not selecting: the G2b read ({g2b.name}) must be committed first")
    if read_runs(RUNS["forecast"]) is None:
        raise SystemExit(f"not selecting: missing one of {RUNS['forecast']}")
    out = {"rule": "analysis/pruning_cascade.py (docstring; deviations 29-31), research/v3/pruning/selection_rule.md",
           "forecast": select_forecast(read_runs(RUNS["forecast"])),
           "inputs": {r: hashlib.sha256((RESULTS / r / "calls.csv").read_bytes()).hexdigest() for r in RUNS["forecast"]}}
    FORECAST_OUT.write_text(json.dumps(out, indent=1, default=float) + "\n")
    print(f"wrote {FORECAST_OUT}")


if __name__ == "__main__":
    command = sys.argv[1] if len(sys.argv) > 1 else "select"
    if command == "lockbox":
        lockbox_main(sys.argv[2])
    else:
        {"select": select_main, "select-forecast": select_forecast_main, "frontier": frontier_main}[command]()
