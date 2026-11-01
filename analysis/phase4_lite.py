"""Phase 4 pulled into October (session E4, K5): the reads of 4C-lite (saturation, e41_saturation_bbeh_anth) and
4A-lite (debate, e42_debate_bbeh_anth). Exploratory throughout; preregs in the two configs
(configs/experiments/phase4/). Writes research/v3/pruning/phase4_lite.md.

Terms (plain words first):
  correctness matrix  items x calls, 1 when the call's answer is right (an unparsed call is wrong).
  repeat correlation  rho: the intra-class correlation of correctness among a set of calls on the same item (one-way
                      ANOVA, autoagentnet/evidence/correlation.icc_anova). 0 means the calls err independently given
                      the item's difficulty mix; 1 means they always agree on right or wrong.
  n_eff(m)            the number of independent calls m correlated calls are worth: m / (1 + (m - 1) rho), rho
                      measured on the first m calls of the set.
  plurality           the largest class of answers the BBEH grader calls equal (ties: the class met first); its
                      accuracy is the share of items where it is right.
  error floor         the share of items no call of the set gets right, and the share whose plurality is still wrong
                      with every call.
  error correlation   (debate) the mean over agent pairs of the phi coefficient of their correctness in a round.
  flip                (debate) an agent's answer changes between rounds: right to wrong, or wrong to right.
  stop after round r  answer with round r's plurality; pays for rounds 1..r.
  consensus exit      after round 1 (and again after round 2), stop when at least 5 of 6 agents agree; pays only for
                      the rounds run.
Intervals: 95% item bootstrap, N_BOOT draws, seed 0.

Usage: python -m analysis.phase4_lite      # after e41 and/or e42 have run; reads what exists
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from analysis.pruning_phase3a import md
from autoagentnet.consensus import plurality
from autoagentnet.evidence.correlation import icc_anova
from autoagentnet.tasks import answers_match

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v3/pruning/phase4_lite.md"
N_BOOT = 1000
PERSONAS = ("careful", "contrarian", "quick")
CONSENSUS = 5 / 6


def boot(stat, n: int, draws: int = N_BOOT, seed: int = 0) -> tuple[float, float, float]:
    """(estimate, 2.5%, 97.5%) of stat(item indices) over an item bootstrap."""
    rng = np.random.default_rng(seed)
    values = np.array([stat(rng.integers(0, n, n)) for _ in range(draws)], dtype=float)
    values = values[np.isfinite(values)]
    return float(stat(np.arange(n))), float(np.percentile(values, 2.5)), float(np.percentile(values, 97.5))


def plurality_right(answers: np.ndarray, gold: list[str]) -> np.ndarray:
    """Per item (row): 1 when the plurality of the row's answers (None = unparsed) is right."""
    out = []
    for row, g in zip(answers, gold):
        top, _ = plurality(list(row), "bbeh")
        out.append(float(answers_match(g, top, "bbeh")))
    return np.array(out)


def agreement(answers: np.ndarray) -> np.ndarray:
    """Per item: the plurality share of its answers."""
    return np.array([plurality(list(row), "bbeh")[1] for row in answers])


def mean_phi(Z: np.ndarray) -> float:
    """Mean pairwise phi of correctness across the columns (calls or agents); nan when a column never varies."""
    vals = []
    for a in range(Z.shape[1]):
        for b in range(a + 1, Z.shape[1]):
            x, y = Z[:, a], Z[:, b]
            if x.std() > 0 and y.std() > 0:
                vals.append(float(np.corrcoef(x, y)[0, 1]))
    return float(np.mean(vals)) if vals else float("nan")


def n_eff(Z: np.ndarray) -> float:
    m = Z.shape[1]
    rho = icc_anova(Z) if m > 1 else 0.0
    return float(m / (1 + (m - 1) * rho))


# ---------------------------------------------------------------------------------------------------------
# 4C-lite: saturation

def saturation_sets(calls: pd.DataFrame) -> dict[str, list[tuple[str, int]]]:
    """The call orders: default prompt calls 0-9, persona calls (careful 0, contrarian 0, quick 0, careful 1, ...),
    and mixed (default 0, careful 0, contrarian 0, quick 0, default 1, ...)."""
    default = [("haiku_nothink:base", c) for c in range(10)]
    persona = [(f"haiku_nothink:{p}", c) for c in range(10) for p in PERSONAS]
    mixed = [(f"haiku_nothink:{p}", c) for c in range(10) for p in ("base", *PERSONAS)]
    return {"default": default, "persona": persona, "mixed": mixed}


def wide(calls: pd.DataFrame, order: list[tuple[str, int]], items: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(correctness, answers) matrices, items x calls in `order`; a missing or unparsed call is wrong with no answer."""
    units = [f"{src}:{c}" for src, c in order]
    c = calls.assign(unit=calls["source"] + ":" + calls["call"].astype(int).astype(str),
                     answer=calls["answer"].where(calls["parsed"].astype(bool)))
    Z = c.pivot_table(index="item", columns="unit", values="correct", aggfunc="first").reindex(index=items, columns=units)
    A = c.pivot_table(index="item", columns="unit", values="answer", aggfunc="first").reindex(index=items, columns=units)
    return Z.fillna(0).to_numpy(dtype=float), A.astype(object).where(A.notna(), None).to_numpy(dtype=object)


def saturation(calls: pd.DataFrame, gold: dict[str, str], ms=(1, 2, 3, 5, 10, 20, 30, 40)) -> pd.DataFrame:
    items = sorted(set(calls["item"]))
    g = [gold[i] for i in items]
    rows = []
    for name, order in saturation_sets(calls).items():
        Z, A = wide(calls, order, items)
        for m in [m for m in ms if m <= len(order)]:
            ne = boot(lambda idx: n_eff(Z[idx, :m]), len(items))
            acc = boot(lambda idx: plurality_right(A[idx, :m], [g[i] for i in idx]).mean(), len(items), draws=200)
            rows.append({"set": name, "m": m, "n_eff": ne[0], "n_eff lo": ne[1], "n_eff hi": ne[2],
                         "plurality accuracy": acc[0], "acc lo": acc[1], "acc hi": acc[2],
                         "none right": float((Z[:, :m].sum(axis=1) == 0).mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# 4A-lite: debate

def debate_rounds(agents: pd.DataFrame) -> tuple[list[str], list[np.ndarray], list[np.ndarray], list[np.ndarray], list[np.ndarray]]:
    """Per round (stage "debate", "debate.r2", ...): items, and items x agents answers, correctness, dollars, seconds."""
    stages = sorted([s for s in agents["stage"].unique() if s.startswith("debate")], key=lambda s: (s != "debate", s))
    items = sorted(set(agents[agents["stage"] == "debate"]["task_id"]))
    A, Z, D, S = [], [], [], []
    for stage in stages:
        part = agents[agents["stage"] == stage].assign(agent=lambda d: d["agent_id"].str.rsplit(".", n=1).str[1].astype(int))
        piv = {col: part.pivot_table(index="task_id", columns="agent", values=col, aggfunc="first").reindex(items)
               for col in ("correct", "cost_usd", "latency_s")}
        ans = part.pivot_table(index="task_id", columns="agent", values="answer", aggfunc="first").reindex(items)
        A.append(ans.where(ans.notna(), None).to_numpy(dtype=object))
        Z.append(piv["correct"].fillna(0).to_numpy(dtype=float))
        D.append(piv["cost_usd"].fillna(0).to_numpy(dtype=float))
        S.append(piv["latency_s"].fillna(0).to_numpy(dtype=float))
    return items, A, Z, D, S


def debate(agents: pd.DataFrame, gold: dict[str, str]) -> dict:
    items, A, Z, D, S = debate_rounds(agents)
    g = [gold[i] for i in items]
    n, R = len(items), len(A)
    right = [plurality_right(a, g) for a in A]
    agree = [agreement(a) for a in A]
    by_round = []
    for r in range(R):
        row = {"round": r + 1}
        for key, stat in (("plurality accuracy", lambda idx, r=r: right[r][idx].mean()),
                          ("agent accuracy", lambda idx, r=r: Z[r][idx].mean()),
                          ("error correlation (phi)", lambda idx, r=r: mean_phi(Z[r][idx])),
                          ("rho (ICC)", lambda idx, r=r: icc_anova(Z[r][idx])),
                          ("all six agree", lambda idx, r=r: float((agree[r][idx] >= 1 - 1e-9).mean()))):
            est, lo, hi = boot(stat, n)
            row.update({key: est, f"{key} lo": lo, f"{key} hi": hi})
        if r:
            row["right to wrong"] = float(((Z[r - 1] == 1) & (Z[r] == 0)).mean())
            row["wrong to right"] = float(((Z[r - 1] == 0) & (Z[r] == 1)).mean())
        row["dollars to here"] = float(sum(D[k].sum(axis=1).mean() for k in range(r + 1)))
        row["seconds to here"] = float(sum(S[k].max(axis=1).mean() for k in range(r + 1)))
        by_round.append(row)
    # consensus exit: stop after a round when at least CONSENSUS of the agents agree (the last round always answers)
    stop = np.full(n, R - 1)
    for r in range(R - 2, -1, -1):
        stop = np.where(agree[r] >= CONSENSUS - 1e-9, r, stop)
    exit_right = np.array([right[stop[i]][i] for i in range(n)])
    exit_usd = np.array([sum(D[k][i].sum() for k in range(stop[i] + 1)) for i in range(n)])
    later_calls = sum(A[k].shape[1] for k in range(1, R)) * n
    skipped = sum(A[k].shape[1] for i in range(n) for k in range(stop[i] + 1, R))
    exit_row = {"accuracy": float(exit_right.mean()), "dollars": float(exit_usd.mean()),
                "later calls skipped": skipped / later_calls if later_calls else 0.0,
                "stopped after round 1": float((stop == 0).mean())}
    return {"n": n, "rounds": pd.DataFrame(by_round), "consensus exit": exit_row}


def main() -> None:
    from autoagentnet.tasks import load_tasks

    gold = {t.id: t.answer for t in load_tasks(ROOT / "data/external/evidence/bbeh.jsonl")}
    lines = ["# Phase 4 in October: 4C-lite (saturation) and 4A-lite (debate)", "",
             "Written by `python -m analysis.phase4_lite`. Exploratory; definitions in the script's docstring; preregs "
             "in configs/experiments/phase4/.", ""]
    sat = ROOT / "results/e41_saturation_bbeh_anth/calls.csv"
    if sat.exists():
        table = saturation(pd.read_csv(sat, dtype={"answer": str}), gold)
        lines += ["## 4C-lite: saturation (100 BBEH items, 40 Haiku calls each)", "", md(table), ""]
    deb = ROOT / "results/e42_debate_bbeh_anth/agents.csv"
    if deb.exists():
        agents = pd.read_csv(deb, dtype={"answer": str})
        d = debate(agents[agents["config_id"] == agents["config_id"].iloc[0]], gold)
        lines += [f"## 4A-lite: debate, 6 Haiku agents x 3 rounds ({d['n']} items)", "", md(d["rounds"]), "",
                  "Consensus exit (stop when at least 5 of 6 agree): " + ", ".join(f"{k} {v:.3f}" for k, v in d["consensus exit"].items()), ""]
    OUT.write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
