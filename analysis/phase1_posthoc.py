"""Post-hoc, exploratory rows for the two Phase 1 reads (G2a BBEH, G2b ForecastBench), chosen after both were read
(audit 59, required item 3, and the G2b read itself). $0, from the same calls; writes
research/v3/evidence/phase1_posthoc.md. Nothing here is confirmatory, and nothing changes the reads.

BBEH (audit 59, required item 3):
  Sol-only correction  H6's setup (y = the 12-call plurality is right; the same two folds, stratified by task, seed 0)
                       with one feature: the share of Sol's calls agreeing with the plurality (its call 0, so 0 or 1).
                       Its Brier beside the Haiku-only and whole-panel corrections, and whole-panel minus Sol-only with
                       a 95% item-bootstrap interval: an interval around 0 means H6's whole-panel gain is Sol's vote.

ForecastBench (after the G2b read):
  pooled forecast  a source's sigmoid(mean log-odds of its calls), as in the read; "Sonnet+Sol" is the sigmoid of the
                   mean of those two sources' log-odds; the panel's is over its 12 calls (10 of them Haiku or Luna).
  paired Brier difference  a minus b over the same questions; negative = a forecasts better. Intervals use H10's two
                   clusters (question; source x resolution week), the wider primary, as in the read. "p, a worse"
                   is the one-sided p-value for "a minus b above 0" (the share of draws at or below 0 under the
                   primary cluster): small means a forecasts worse than b.
                   On the 200 sealed: the panel minus Sol and minus Sonnet; Sonnet+Sol minus Sol; Sol minus Sonnet;
                   Haiku minus Sonnet. On the 100 sealed market questions: Sol, Sonnet, Haiku, Luna and the panel
                   minus the freeze price (shown in every market prompt).
  within-outcome correlation  the read correlates errors (f - y) between sources; y is shared, so that correlation
                   is high even for forecasts that differ. Here: the correlation of two sources' pooled forecasts
                   among questions with the same outcome (y = 0 and y = 1 apart, averaged weighted by count); on the
                   market questions also of their forecasts minus the price (what each adds to the price).

Usage: python -m analysis.phase1_posthoc
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analysis.evidence_phase1 import (N_BOOT, NAMES, PAIRS, ROOT, SEED, add_cross_fits, bbeh_items, boot_two,
                                      forecast_table, ids, read_calls)
from analysis.pruning_phase3a import md
from autoagentnet.evidence import calibration as C
from autoagentnet.evidence.inference import cluster_draws
from autoagentnet.tasks import load_tasks

OUT = ROOT / "research/v3/evidence/phase1_posthoc.md"
POOLS = ROOT / "data/external/evidence"


def sol_only(t: pd.DataFrame) -> dict:
    """Brier of the Haiku-only, whole-panel and Sol-only corrections of the 12-call plurality (cross-fitted), and
    whole-panel minus Sol-only with a 95% item-bootstrap interval. t needs task, panel12_right and the four agree
    columns (h_agree, l_agree, s_agree, o_agree)."""
    t, folds = add_cross_fits(t)
    y = t["panel12_right"].to_numpy(dtype=float)
    t = t.assign(pred_sol_only=C.cross_fit(t[["o_agree"]].to_numpy(), y, folds, l2=1e-3))
    preds = {name: t[col].to_numpy() for name, col in
             (("Haiku-only", "pred_haiku_only"), ("whole-panel (H6)", "pred_whole"), ("Sol-only", "pred_sol_only"))}
    stat = lambda i: C.brier(preds["whole-panel (H6)"][i], y[i]) - C.brier(preds["Sol-only"][i], y[i])
    draws = np.array([stat(i) for i in cluster_draws(np.arange(len(t)), N_BOOT, SEED)])
    return {"brier": {k: C.brier(v, y) for k, v in preds.items()}, "diff": stat(np.arange(len(t))),
            "ci": (float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))),
            "n": len(t), "sol_agrees": float(t["o_agree"].mean()), "right_when_sol_agrees":
            float(t.loc[t["o_agree"] == 1, "panel12_right"].mean())}


def pooled(t: pd.DataFrame) -> dict[str, np.ndarray]:
    """Pooled forecasts per question (no parsed forecast: 50%, as in the read)."""
    f = {NAMES[k]: C.sigmoid(t[f"logit_{k}"].fillna(0.0).to_numpy()) for k in "HLSO" if f"logit_{k}" in t}
    f["Sonnet+Sol"] = C.sigmoid((t["logit_S"].fillna(0.0).to_numpy() + t["logit_O"].fillna(0.0).to_numpy()) / 2)
    f["panel"] = C.sigmoid(t["panel_logit"].to_numpy())
    if t["market"].all() and len(t):
        f["price"] = C.clip(t["price"].to_numpy())
    return f


def brier_diffs(t: pd.DataFrame, pairs: list[tuple[str, str]]) -> pd.DataFrame:
    f, y = pooled(t), t["outcome"].to_numpy(dtype=float)
    rows = []
    for a, b in pairs:
        res = boot_two(lambda i, a=a, b=b: C.brier(f[a][i], y[i]) - C.brier(f[b][i], y[i]), t)
        lo, hi, p = res[res["primary"]]
        rows.append({"a minus b": f"{a} minus {b}", "Brier diff": res["estimate"], "low": lo, "high": hi,
                     "p, a worse": p, "other cluster": f"{res[_other(res['primary'])][0]:+.4f} to "
                     f"{res[_other(res['primary'])][1]:+.4f}", "primary": res["primary"]})
    return pd.DataFrame(rows)


def _other(primary: str) -> str:
    return "question" if primary == "source x week" else "source x week"


def within_outcome(t: pd.DataFrame, minus_price: bool = False) -> pd.DataFrame:
    """Correlation of two sources' pooled forecasts among questions with the same outcome, weighted by count."""
    f, y = pooled(t), t["outcome"].to_numpy()
    rows = []
    for x, z in PAIRS:
        a, b = f[NAMES[x]], f[NAMES[z]]
        if minus_price:
            a, b = a - f["price"], b - f["price"]
        rs = [(np.corrcoef(a[y == v], b[y == v])[0, 1], int((y == v).sum())) for v in (0, 1) if (y == v).sum() > 2]
        r = sum(r * n for r, n in rs) / sum(n for _, n in rs) if rs else float("nan")
        rows.append({"pair": f"{NAMES[x]}-{NAMES[z]}", "r": r})
    return pd.DataFrame(rows)


SEALED_PAIRS = [("panel", "Sol"), ("panel", "Sonnet"), ("Sonnet+Sol", "Sol"), ("Sol", "Sonnet"), ("Haiku", "Sonnet"),
                ("Luna", "Haiku")]
MARKET_PAIRS = [("Sol", "price"), ("Sonnet", "price"), ("Haiku", "price"), ("Luna", "price"), ("panel", "price")]


def forecast_posthoc(t: pd.DataFrame) -> dict:
    sealed = t[t["split"] == "sealed"].reset_index(drop=True)
    markets = sealed[sealed["market"]].reset_index(drop=True)
    series = sealed[~sealed["market"]].reset_index(drop=True)
    return {"sealed": brier_diffs(sealed, SEALED_PAIRS), "market": brier_diffs(markets, MARKET_PAIRS),
            "within market": within_outcome(markets), "within market minus price": within_outcome(markets, True),
            "within data-series": within_outcome(series)}


def report(b: dict, f: dict) -> str:
    L = ["# Phase 1: post-hoc rows (exploratory, chosen after both reads)", "",
         "Written by `python -m analysis.phase1_posthoc`; definitions in its docstring. Nothing here is confirmatory.", "",
         "## BBEH: a correction built from Sol alone (audit 59, item 3)", "",
         f"y = the 12-call plurality is right, {b['n']} sealed items, two folds stratified by task (seed 0), as for H6. "
         f"Sol agrees with the plurality on {b['sol_agrees']:.1%} of items; the plurality is right on "
         f"{b['right_when_sol_agrees']:.1%} of those.", "",
         md(pd.DataFrame([{"correction": k, "Brier": v} for k, v in b["brier"].items()]), 4), "",
         f"Whole-panel minus Sol-only (Brier): {b['diff']:+.4f} (95% item bootstrap {b['ci'][0]:+.4f} to "
         f"{b['ci'][1]:+.4f}).", "",
         "## ForecastBench: paired Brier differences (a minus b; negative = a better)", "",
         "*200 sealed questions*", "", md(f["sealed"], 4), "",
         "*100 sealed market questions (the price is in every prompt)*", "", md(f["market"], 4), "",
         "## ForecastBench: correlation of forecasts among questions with the same outcome", "",
         "The read's error correlations share y; these do not.", ""]
    names = [("within market", "market"), ("within market minus price", "market, forecast minus price"),
             ("within data-series", "data-series")]
    table = pd.concat([f[k].assign(kind=label) for k, label in names])
    wide = table.pivot_table(index="pair", columns="kind", values="r", aggfunc="first")[[label for _, label in names]]
    L += [md(wide.reset_index(), 2), ""]
    return "\n".join(L)


def main() -> str:
    calls = read_calls(ROOT / "results", ["e13_bbeh_anth", "e13_bbeh_open"])
    tasks = {t.id: t.meta["task"] for t in load_tasks(POOLS / "bbeh.jsonl")}
    items = [i for i in ids("bbeh_sealed") if i in set(calls["item"])]
    _, t = bbeh_items(calls, items, tasks)
    fc = read_calls(ROOT / "results", ["e14_forecast_anth", "e14_forecast_open"])
    meta = {t_.id: {**t_.meta, "outcome": int(t_.answer)} for t_ in load_tasks(POOLS / "forecast.jsonl") if t_.id in set(fc["item"])}
    text = report(sol_only(t), forecast_posthoc(forecast_table(fc, meta)))
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    main()
