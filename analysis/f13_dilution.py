"""Finding F13 (post hoc, exploratory; session E5): calibration by dilution. On the 300 sealed Phase 1 BBEH items
(read at G2a), compare the vote share of 5 Haiku calls with that of a mixed 5 (3 Haiku + 2 Luna calls) as a
confidence for "the plurality answer is right": the overconfidence gap (mean share minus accuracy, points) and the
discrimination (AUROC: the chance a right item has a higher share than a wrong one) and the Murphy resolution term.
Mixing in near-random Luna votes pulls the share down toward accuracy (a smaller gap) without ranking items better.
Writes research/v3/f13_dilution.md; intervals: 95% item bootstrap, 2,000 draws, seed 0. $0.

Usage: python -m analysis.f13_dilution
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.evidence_phase1 import ROOT, bbeh_items, ids, read_calls
from analysis.pruning_phase3a import md
from autoagentnet.evidence import calibration as C
from autoagentnet.evidence.inference import cluster_draws
from autoagentnet.tasks import load_tasks

OUT = ROOT / "research/v3/f13_dilution.md"
SETS = {"Haiku x5": "haiku5", "mixed 5 (3H+2L)": "mix1", "mixed 5 (2H+3L)": "mix2", "Luna x5": "luna5"}


def measures(t: pd.DataFrame, idx: np.ndarray) -> dict:
    out = {}
    for name, key in SETS.items():
        c, y = t[f"{key}_share"].to_numpy(dtype=float)[idx], t[f"{key}_right"].to_numpy(dtype=float)[idx]
        out[f"gap:{name}"] = 100 * C.calibration_gap(c, y)
        out[f"auroc:{name}"] = C.auroc(c, y)
        out[f"res:{name}"] = C.murphy(c, y)["resolution"]
    out["gap diff (Haiku x5 - mixed 3H+2L)"] = out["gap:Haiku x5"] - out["gap:mixed 5 (3H+2L)"]
    out["auroc diff (Haiku x5 - mixed 3H+2L)"] = out["auroc:Haiku x5"] - out["auroc:mixed 5 (3H+2L)"]
    return out


def table(t: pd.DataFrame, n_boot: int = 2000) -> pd.DataFrame:
    point = measures(t, np.arange(len(t)))
    boot = pd.DataFrame([measures(t, d) for d in cluster_draws(np.arange(len(t)), n_boot, 0)])
    return pd.DataFrame([{"quantity": k, "estimate": v, "low": float(np.nanpercentile(boot[k], 2.5)),
                          "high": float(np.nanpercentile(boot[k], 97.5))} for k, v in point.items()])


def main() -> str:
    tasks = {t.id: t.meta["task"] for t in load_tasks(ROOT / "data/external/evidence/bbeh.jsonl")}
    calls = read_calls(ROOT / "results", ["e13_bbeh_anth", "e13_bbeh_open"])
    items = [i for i in ids("bbeh_sealed") if i in set(calls["item"])]
    _, t = bbeh_items(calls, items, tasks)
    text = "\n".join(["# F13: calibration by dilution (post hoc, exploratory)", "",
                      f"Written by `python -m analysis.f13_dilution` ({len(t)} sealed Phase 1 BBEH items, read at G2a); "
                      "definitions in its docstring. Gap in points; AUROC and resolution of the vote share against "
                      "\"the plurality answer is right\".", "", md(table(t), 3), ""])
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    main()
