"""Post hoc, exploratory (session E5, patch 2.3): the call sets of G2a's n_eff table (research/v3/evidence/
phase1_bbeh.md, section 4) with the information their votes carry about the true answer beside n_eff. $0, from the
read Phase 1 calls (e13_bbeh_*); nothing here is a test. Writes research/v3/evidence/information_posthoc.md.

Plain words: n_eff counts how many independent calls a set is worth, whatever their accuracy; info_nats is the
predictive information the set's votes carry about "this candidate is right" over every candidate answer any of the
12 Phase 1 calls proposed: that 0/1 truth's entropy (h_nats, the same for every set) minus the held-out log loss of
a logistic regression of it on the set's votes, five folds by item (autoagentnet.pruning.criteria.set_information).
It is a lower bound on the mutual information and can never pass h_nats. Info per dollar divides it by the set's
mean dollars per item. A set of cheap, uncorrelated but often-wrong calls scores high on n_eff and low on
information. (Audit 68 finding 6: the first version reported a Gaussian-copula number, which reached 1.22 "nats",
above ln 2; it is replaced.)

Usage: python -m analysis.information_posthoc
"""

from __future__ import annotations

import pandas as pd

from analysis.evidence_phase1 import ROOT, ids
from analysis.pruning_cascade import build, read_runs
from analysis.pruning_phase3a import md
from autoagentnet.pruning import cascade as C
from autoagentnet.pruning.criteria import set_information
from autoagentnet.pruning.replay import Panel

OUT = ROOT / "research/v3/evidence/information_posthoc.md"
H = [f"haiku_nothink:base:{k}" for k in range(5)]
L = [f"luna_none:base:{k}" for k in range(5)]
S, O = "sonnet_nothink:base:0", "sol61_low:base:0"
SETS = {"Haiku x5": H, "Luna x5": L, "mixed 5 (3H+2L)": H[:3] + L[:2], "mixed 5 (2H+3L)": H[:2] + L[:3],
        "Haiku x5 + Luna x5": H + L, "12-call panel": H + L + [S, O], "Sonnet alone": [S], "Sol alone": [O]}


def table(panel: Panel, sets: dict[str, list[str]]) -> pd.DataFrame:
    """One row per set: n_eff, information (nats), mean dollars per item, information per dollar."""
    rows = [{"set": name, "calls": len(units), **set_information(panel, C.unit_positions(panel, units))}
            for name, units in sets.items()]
    return pd.DataFrame(rows).sort_values("info_nats", ascending=False)


def main() -> str:
    calls = read_runs(["e13_bbeh_anth", "e13_bbeh_open"])
    units = H + L + [S, O]
    panel = build(calls, "bbeh", units, ids("bbeh_sealed"))
    t = table(panel, SETS)
    text = "\n".join([
        "# Information beside n_eff (post hoc, exploratory; session E5 patch 2.3)", "",
        f"Written by `python -m analysis.information_posthoc` from the Phase 1 BBEH calls ({panel.n} sealed items, read "
        "at G2a). Definitions in the script's docstring. Nothing here is a test.", "",
        md(t[["set", "calls", "n_eff", "info_nats", "h_nats", "dollars", "info_per_dollar"]], 4), "",
        "Correction (audit 68, finding 6): an earlier version of this table reported Gaussian-copula numbers (up to "
        "1.22 for the 12-call panel and 1.21 for Sol alone), which are not information about a 0/1 truth (at most "
        "ln 2 = 0.693 nats). They are replaced by the predictive bound above.", ""])
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    main()
