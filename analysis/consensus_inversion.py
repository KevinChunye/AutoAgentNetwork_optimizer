"""Consensus inversion (session E5, patch 2.4): when does plain Dawid-Skene rate the best source below a worse one,
and does pooling each source's repeats (one soft-voting witness per source) fix it? $0. Writes
research/v3/evidence/consensus_inversion.md. Exploratory: the simulation is a mechanism check, and the Phase 1 rows
are post hoc on data read at G2a (plain Dawid-Skene's 62.5% for Sol is Phase 2's H17).

The simulated panel, in plain words: a weak source answers each item m times; its calls share the item's
difficulty (dependence sigma: the spread of its per-item log-odds of being right; 0 = independent calls) and, when
wrong, pile on one attractive wrong answer with probability 0.8 (else a random one of 8 others). A strong source
answers once, right with its own accuracy, independently of item difficulty; when wrong it picks at random. A third,
medium source (accuracy 0.65, one independent call, random when wrong) keeps the one-coin model identified: with only
two witnesses per item, Dawid-Skene cannot tell which of them is better. An inversion is an estimated strong accuracy
below the estimated weak accuracy (the truth is the reverse).

Methods: plain (every call a witness) and pooled (one soft vote per source), each with the label space of the
observed candidates (the default) and with the simulation's 10 labels (A to J; audit 68 finding 5: the default
misranks even independent sources). The Phase 1 rows use the default only: BBEH answers have no fixed label space,
and choosing one after the read would be a post-hoc analysis choice.

Usage: python -m analysis.consensus_inversion
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.evidence_phase1 import ROOT, SOURCES, ids, read_calls
from analysis.pruning_phase3a import md
from autoagentnet.evidence.labelfree import dawid_skene, dawid_skene_pooled
from autoagentnet.tasks import answers_match

OUT = ROOT / "research/v3/evidence/consensus_inversion.md"
SAME = lambda a, b: a == b  # simulated answers are plain labels
MEDIUM = 0.65


def simulate(n: int, m: int, sigma: float, acc_weak: float, acc_strong: float, rng) -> pd.DataFrame:
    """Rows (item, source, answer, correct) of one simulated panel; the true answer is "A"."""
    base = np.log(acc_weak / (1 - acc_weak))
    rows = []
    for i in range(n):
        p = 1 / (1 + np.exp(-(base + sigma * rng.standard_normal())))
        for k in range(m):
            ok = rng.random() < p
            wrong = "B" if rng.random() < 0.8 else "CDEFGHIJ"[rng.integers(0, 8)]
            rows.append((f"i{i}", "weak", "A" if ok else wrong, float(ok)))
        ok = rng.random() < acc_strong
        rows.append((f"i{i}", "strong", "A" if ok else "BCDEFGHIJ"[rng.integers(0, 9)], float(ok)))
        ok = rng.random() < MEDIUM
        rows.append((f"i{i}", "medium", "A" if ok else "BCDEFGHIJ"[rng.integers(0, 9)], float(ok)))
    return pd.DataFrame(rows, columns=["item", "source", "answer", "correct"])


def grid(reps: int = 10, n: int = 300, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out = []
    for m in (1, 3, 5, 10):
        for sigma in (0.0, 1.5, 3.0):
            for acc_strong in (0.75, 0.97):
                for _ in range(reps):
                    rows = simulate(n, m, sigma, 0.45, acc_strong, rng)
                    for name, fit, labels in (("plain", dawid_skene, None), ("pooled", dawid_skene_pooled, None),
                                              ("plain, 10 labels", dawid_skene, 10),
                                              ("pooled, 10 labels", dawid_skene_pooled, 10)):
                        est, _ = fit(rows[["item", "source", "answer"]], SAME, labels=labels)
                        out.append({"weak calls": m, "dependence sigma": sigma, "strong accuracy": acc_strong,
                                    "method": name, "strong estimate": est["strong"], "weak estimate": est["weak"],
                                    "medium estimate": est["medium"],
                                    "inverted": float(est["strong"] < est["weak"])})
    frame = pd.DataFrame(out)
    return (frame.groupby(["weak calls", "dependence sigma", "strong accuracy", "method"])
            [["strong estimate", "weak estimate", "medium estimate", "inverted"]].mean().reset_index())


def phase1(results=ROOT / "results") -> pd.DataFrame:
    """Plain vs pooled Dawid-Skene on the Phase 1 BBEH panel (Haiku x5, Luna x5, Sonnet x1, Sol x1; 300 items)."""
    calls = read_calls(results, ["e13_bbeh_anth", "e13_bbeh_open"])
    rows = calls[calls["item"].isin(ids("bbeh_sealed")) & (calls["prompt"] == "base")]
    rows = rows[((rows["source"].isin([SOURCES["H"], SOURCES["L"]])) & (rows["call"] < 5))
                | ((rows["source"].isin([SOURCES["S"], SOURCES["O"]])) & (rows["call"] == 0))]
    rows = rows.assign(answer=rows["answer"].where(rows["parsed"].astype(bool)))
    same = lambda a, b: answers_match(a, b, "bbeh")
    plain, _ = dawid_skene(rows[["item", "source", "answer"]], same)
    pooled, _ = dawid_skene_pooled(rows[["item", "source", "answer"]], same)
    truth = rows.groupby("source")["correct"].mean()
    t = pd.DataFrame({"true accuracy": truth, "plain Dawid-Skene": plain, "pooled Dawid-Skene": pooled}).reset_index()
    return t.rename(columns={"index": "source"}).sort_values("true accuracy", ascending=False)


def main() -> str:
    g = grid()
    p = phase1()
    text = "\n".join([
        "# Consensus inversion: plain vs pooled Dawid-Skene (session E5, patch 2.4; exploratory)", "",
        "Written by `python -m analysis.consensus_inversion`; definitions in its docstring.", "",
        "## Phase 1 BBEH, 300 sealed items (post hoc; plain Dawid-Skene is Phase 2's H17)", "",
        md(p, 3), "",
        "## Simulation: weak source (accuracy 0.45) with m correlated calls, one strong call, one medium call (0.65); 10 panels of 300 items",
        "", "Inverted = the share of panels where the strong source's estimate is below the weak source's.", "",
        md(g, 3), ""])
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    main()
