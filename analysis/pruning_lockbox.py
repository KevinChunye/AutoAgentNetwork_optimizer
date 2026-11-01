"""Phase 3C of the evidence plan, static networks (session E3): descriptive since session E4 (Kevin's K3; the
preregistered read is analysis/pruning_cascade.py). Applies the networks in research/v3/pruning/selected_static.json
(analysis/pruning_select.py) to the lockbox calls without refitting, computes P1-P3 as descriptives and writes
research/v3/pruning/lockbox_static.md. Like the cascade read, it refuses to open any lockbox call until the cascade
selection (research/v3/pruning/selected.json) is committed unchanged in git.

Tests (BBEH; definitions in analysis/pruning_power.py): paired per-item differences of accuracy,
  P1  static - Sonnet         above -5 points
  P2  static - dense refit    above -3 points
  P3  dynamic - static        above -3 points (cost ratios reported)
each with a one-sided item-bootstrap p-value (N_BOOT draws, stratified by task) for "mean difference at or below
the margin", Holm at 5% over the confirmatory ones (STATUS, set from the power simulation,
research/v3/pruning/power.md; scripts/make_evidence_configs.py reads the same dict for the preregs). A test the
selection made void (selected.json "void": no static network, the static network is Sonnet itself, or no
dynamic policy) gets no p-value and leaves the Holm family. ForecastBench: the same differences in Brier,
exploratory, with intervals.
Cost ratios: mean dollars per item of one network over another's, with a 95% item-bootstrap interval.

Usage: python -m analysis.pruning_lockbox      # once, after the e31_lockbox_* runs
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.pruning_cascade import OUT as CASCADE_SELECTED, committed
from analysis.pruning_select import build_panel, apply_frozen, strata_of
from autoagentnet.evidence.inference import bootstrap, holm, p_above

ROOT = Path(__file__).resolve().parents[1]
SELECTED = ROOT / "research/v3/pruning/selected_static.json"
OUT = ROOT / "research/v3/pruning/lockbox_static.md"
RUNS = {"bbeh": ["e31_lockbox_bbeh_anth", "e31_lockbox_bbeh_open"],
        "forecast": ["e31_lockbox_forecast_anth", "e31_lockbox_forecast_open"]}
MARGINS = {"P1": ("static", "sonnet", -0.05), "P2": ("static", "dense", -0.03), "P3": ("dynamic", "static", -0.03)}
STATUS = {"P1": "expl", "P2": "expl", "P3": "expl"}  # descriptive: power under 0.70 (session E3), out of the prereg (K3)
N_BOOT = 2000


def tests(table: pd.DataFrame, strata, kind: str, status: dict = STATUS, void=()) -> pd.DataFrame:
    """One row per test: difference, 95% interval, one-sided p (BBEH) and Holm decision; plus cost ratios."""
    rows = []
    n = len(table)
    for name, (a, b, margin) in MARGINS.items():
        if name in void or table[f"{a}_score"].isna().all() or table[f"{b}_score"].isna().all():
            rows.append({"test": name, "comparison": f"{a} - {b}", "status": "void"})
            continue
        d = (table[f"{a}_score"] - table[f"{b}_score"]).to_numpy()
        if kind == "forecast":
            d = -d  # Brier difference: the score is minus the squared error
        res = bootstrap(lambda idx: float(d[idx].mean()), n, strata=strata, n_boot=N_BOOT)
        ratio = bootstrap(lambda idx: float(table[f"{a}_dollars"].to_numpy()[idx].mean() / table[f"{b}_dollars"].to_numpy()[idx].mean()),
                          n, strata=strata, n_boot=N_BOOT)
        row = {"test": name, "comparison": f"{a} - {b}", "difference": res["estimate"], "lo": res["lo"], "hi": res["hi"],
               "cost ratio": ratio["estimate"], "ratio lo": ratio["lo"], "ratio hi": ratio["hi"]}
        if kind == "bbeh":
            row["margin"] = margin
            row["p"] = p_above(res["draws"], margin)  # "above the margin": the share of draws at or below it
            row["status"] = status[name]
        else:
            row["status"] = "expl"  # ForecastBench is exploratory
        rows.append(row)
    out = pd.DataFrame(rows)
    if kind == "bbeh":
        conf = out[(out["status"] == "conf") & out["p"].notna()]
        decided = holm(dict(zip(conf["test"], conf["p"]))) if len(conf) else pd.DataFrame(columns=["test", "passes"])
        out = out.merge(decided[["test", "passes"]], on="test", how="left")
    return out


def read_calls(kind: str) -> pd.DataFrame | None:
    frames = [pd.read_csv(ROOT / "results" / r / "calls.csv", dtype={"answer": str}) for r in RUNS[kind]
              if (ROOT / "results" / r / "calls.csv").exists()]
    return pd.concat(frames, ignore_index=True) if len(frames) == len(RUNS[kind]) else None


def main() -> None:
    if not CASCADE_SELECTED.exists() or not committed(CASCADE_SELECTED):
        raise SystemExit("not reading the lockbox: research/v3/pruning/selected.json must exist and be committed unchanged first")
    sel = json.loads(SELECTED.read_text())
    lines = ["# Phase 3C: the lockbox read", "", "Written by `python -m analysis.pruning_lockbox` from "
             "research/v3/pruning/selected.json (frozen before any lockbox call) and the e31_lockbox_* calls.", ""]
    for kind in ("bbeh", "forecast"):
        calls = read_calls(kind)
        if calls is None or kind not in sel:
            lines += [f"## {kind}", "", "Not read: the lockbox calls or the frozen selection are missing.", ""]
            continue
        panel = build_panel(calls, kind)
        table = apply_frozen(panel, sel[kind])
        result = tests(table, strata_of(panel, kind), kind, void=sel[kind]["void"])
        lines += [f"## {kind} ({panel.n} items)", "", result.round(4).to_csv(index=False), ""]
    OUT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
