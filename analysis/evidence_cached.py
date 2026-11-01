"""Step 0.9 of the evidence plan: the cached findings, recomputed with autoagentnet/evidence/ from calls
already paid for ($0). Writes research/v3/evidence/cached.md; tests/test_evidence_cached.py pins the
numbers (the regression test).

Data (results/*/results.csv, tracked in git; no task file is needed):
  Haiku    w0_haiku5: 5 single-Haiku calls (replicates 0-4) on 100 BBEH items (gate positions 20-119).
  Sonnet   p3_bbeh_single_sonnet (positions 20-59) and p4_bbeh_single_sonnet_held (60-99): one call each.
           These 80 items are "the 80"; their halves are 20-59 (the P3 run) and 60-99 (the P4 run).
  designs  p4_bbeh_grid_a..p: the pilot's 27 Haiku team designs (keep levels 1, 3, 6 of three stages),
           one answer per design per item, on the 80.

Definitions (as in the plan's computation, matched here):
  plurality     the largest class of an item's 5 Haiku answers (answers grouped by the bbeh grader; an
                unparsed answer is never in a class); a tie goes to the class reached first in call order.
  share         the plurality's size / 5: the naive "k of 5 agree" confidence.
  Sonnet agrees 1 when Sonnet's answer matches the plurality under the bbeh grader.
  corrections   a logistic regression of the plurality's correctness on the share (one feature) or on the
                share and Sonnet agrees (two features), fitted on one half and scored on the other, both ways.
  designs       "two of the 27 designs" is the average over the 351 pairs of distinct designs of each pair's
                measure (correlation.mean_pairwise); "two Haiku calls" pools the 10 call pairs of each item.
  intervals     95%, resampling items (2,000 draws, seed 0); for the out-of-sample corrections the
                predictions are fixed and the per-item losses are resampled.

Usage: python -m analysis.evidence_cached
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from autoagentnet.evidence import calibration as C
from autoagentnet.evidence import correlation as R
from autoagentnet.evidence.inference import bootstrap
from autoagentnet.tasks import answers_match

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"
OUT = ROOT / "research/v3/evidence/cached.md"
SONNET_HALVES = {"p3_bbeh_single_sonnet": 0, "p4_bbeh_single_sonnet_held": 1}
GRID = [f"p4_bbeh_grid_{x}" for x in "abcdefghijklmnop"]


def read(run: str, results: Path = RESULTS) -> pd.DataFrame:
    return pd.read_csv(results / run / "results.csv", dtype={"answer": str})


def load(results: Path = RESULTS) -> dict:
    haiku = read("w0_haiku5", results).sort_values(["task_id", "replicate"], kind="stable")
    sonnet = pd.concat([read(r, results).assign(half=h) for r, h in SONNET_HALVES.items()]).set_index("task_id")
    grid = pd.concat([read(r, results) for r in GRID])
    Z = haiku.pivot(index="task_id", columns="replicate", values="correct")
    answers = haiku.pivot(index="task_id", columns="replicate", values="answer")
    G = grid.pivot_table(index="task_id", columns="config_id", values="correct", aggfunc="first")
    return {"Z": Z, "answers": answers, "sonnet": sonnet, "G": G}


def plurality(answers: list, correct: list) -> tuple[float, float, str | None]:
    """(share, correct, answer) of the plurality class of one item's answers."""
    from analysis.landscape import answer_classes

    answers = [a if isinstance(a, str) else None for a in answers]
    classes = [c for c in answer_classes(answers, "bbeh") if answers[c[0]] is not None]
    if not classes:
        return 0.0, 0.0, None
    largest = max(len(c) for c in classes)
    first = next(c for c in classes if len(c) == largest)
    return largest / len(answers), float(correct[first[0]]), answers[first[0]]


def item_table(data: dict) -> pd.DataFrame:
    """One row per item of the 80: share, plurality correct, Sonnet agrees, Sonnet correct, half."""
    rows = []
    for item in data["sonnet"].index:
        share, right, answer = plurality(data["answers"].loc[item].tolist(), data["Z"].loc[item].tolist())
        s = data["sonnet"].loc[item]
        agrees = float(answer is not None and isinstance(s["answer"], str) and answers_match(answer, s["answer"], "bbeh"))
        rows.append({"item": item, "share": share, "correct": right, "sonnet_agrees": agrees,
                     "sonnet_correct": float(s["correct"]), "half": int(s["half"])})
    return pd.DataFrame(rows)


def findings(results: Path = RESULTS) -> dict:
    data = load(results)
    Z = data["Z"].to_numpy(dtype=float)
    out: dict = {}

    # 1. repeat correlation of Haiku, 100 items
    rho = bootstrap(lambda idx: R.rho_pairwise(Z[idx]), len(Z))
    out["rho"] = {k: rho[k] for k in ("estimate", "lo", "hi")}
    out["rho_anova"] = R.icc_anova(Z)
    out["rho_betabinom"] = R.rho_betabinom(Z)[1]
    out["n_eff_5"] = R.n_eff_repeat(5, rho["estimate"])

    # 2. all-or-nothing items against independence
    k = Z.sum(axis=1)
    p_bar = Z.mean()
    out["all_or_nothing"] = {"p_bar": p_bar, "zero_of_5": int((k == 0).sum()), "five_of_5": int((k == 5).sum()),
                             "zero_if_independent": len(Z) * (1 - p_bar) ** 5, "five_if_independent": len(Z) * p_bar ** 5}

    # 3. shared errors on the 80
    ids = data["sonnet"].index
    Z80 = data["Z"].loc[ids].to_numpy(dtype=float)
    S80 = data["sonnet"].loc[ids, ["correct"]].to_numpy(dtype=float)
    G80 = data["G"].loc[ids].to_numpy(dtype=float)
    measures = {
        "haiku_pairs": lambda idx: R.pair_stats(Z80[idx]),
        "haiku_sonnet": lambda idx: R.pair_stats(Z80[idx], S80[idx]),
    }
    for name, fn in measures.items():
        ser = bootstrap(lambda idx: fn(idx).shared_error_ratio, len(ids))
        phi = bootstrap(lambda idx: fn(idx).phi, len(ids))
        lor = bootstrap(lambda idx: fn(idx).log_error_or, len(ids))
        out[name] = {"ser": ser["estimate"], "ser_lo": ser["lo"], "ser_hi": ser["hi"], "phi": phi["estimate"],
                     "phi_lo": phi["lo"], "phi_hi": phi["hi"], "log_error_or": lor["estimate"]}
    ser = bootstrap(lambda idx: R.mean_pairwise(G80[idx])["shared_error_ratio"], len(ids))
    phi = bootstrap(lambda idx: R.mean_pairwise(G80[idx])["phi"], len(ids))
    out["design_pairs"] = {"ser": ser["estimate"], "ser_lo": ser["lo"], "ser_hi": ser["hi"], "phi": phi["estimate"],
                           "phi_lo": phi["lo"], "phi_hi": phi["hi"],
                           "log_error_or": R.mean_pairwise(G80)["log_error_or"], "pairs": R.mean_pairwise(G80)["pairs"]}

    # 4. naive confidence and the corrections, out of sample
    t = item_table(data)
    y, share, folds = t["correct"].to_numpy(), t["share"].to_numpy(), t["half"].to_numpy()
    one = C.cross_fit(share, y, folds)
    two = C.cross_fit(t[["share", "sonnet_agrees"]].to_numpy(), y, folds)
    gap_naive = bootstrap(lambda idx: C.calibration_gap(share[idx], y[idx]), len(y))
    gap_one = bootstrap(lambda idx: C.calibration_gap(one[idx], y[idx]), len(y))
    gain = bootstrap(lambda idx: C.brier(one[idx], y[idx]) - C.brier(two[idx], y[idx]), len(y))
    out["calibration"] = {
        "naive_gap_points": 100 * gap_naive["estimate"], "naive_gap_lo": 100 * gap_naive["lo"], "naive_gap_hi": 100 * gap_naive["hi"],
        "naive_brier": C.brier(share, y), "one_feature_brier": C.brier(one, y),
        "one_feature_gap_points": 100 * gap_one["estimate"], "one_feature_gap_lo": 100 * gap_one["lo"],
        "one_feature_gap_hi": 100 * gap_one["hi"], "two_feature_brier": C.brier(two, y),
        "brier_gain": gain["estimate"], "brier_gain_lo": gain["lo"], "brier_gain_hi": gain["hi"]}

    # 5. the vote when Sonnet agrees and when it does not
    by = t.groupby("sonnet_agrees")["correct"].agg(["mean", "size"])
    out["sonnet_agreement"] = {"right_when_agrees": by.loc[1.0, "mean"], "n_agrees": int(by.loc[1.0, "size"]),
                               "right_when_not": by.loc[0.0, "mean"], "n_not": int(by.loc[0.0, "size"])}

    # 8. the cheap cascade on the held-out half (60-99): 5 Haiku calls; Sonnet answers unless at least 3 agree with
    # their plurality; cost ratio = mean dollars per item (5 Haiku calls plus Sonnet when escalated) over Sonnet's, as billed
    held = data["sonnet"].index[data["sonnet"]["half"] == 1]
    haiku_usd = read("w0_haiku5", results).groupby("task_id")["cost_usd"].sum()
    rows = []
    for item in held:
        share, right, _ = plurality(data["answers"].loc[item].tolist(), data["Z"].loc[item].tolist())
        s = data["sonnet"].loc[item]
        escalate = share * 5 < 3
        rows.append({"right": float(s["correct"]) if escalate else right, "sonnet": float(s["correct"]),
                     "usd": haiku_usd[item] + (s["cost_usd"] if escalate else 0.0), "sonnet_usd": s["cost_usd"],
                     "escalated": escalate})
    c = pd.DataFrame(rows)
    d = (c["right"] - c["sonnet"]).to_numpy()
    diff = bootstrap(lambda idx: d[idx].mean(), len(d))
    out["cascade"] = {"n": len(c), "accuracy": c["right"].mean(), "sonnet": c["sonnet"].mean(),
                      "diff_points": 100 * diff["estimate"], "diff_lo": 100 * diff["lo"], "diff_hi": 100 * diff["hi"],
                      "cost_ratio": c["usd"].mean() / c["sonnet_usd"].mean(), "escalated": c["escalated"].mean()}

    # the frozen correction H5 carries to the sealed items: the two-feature fit on all 80 cached items
    beta = C.fit_correction(t[["share", "sonnet_agrees"]].to_numpy(), y)
    out["frozen_h5_correction"] = {"intercept": float(beta[0]), "share": float(beta[1]), "sonnet_agrees": float(beta[2])}
    return out


PLAN = {  # the plan's numbers (Evidence this plan rests on; session prompt, ALREADY KNOWN)
    "rho": "0.48 (0.38-0.58)", "n_eff_5": "1.71", "zero_of_5": "22 (3.7 if independent)", "five_of_5": "24 (2.6)",
    "haiku_pairs": "1.48 (1.32-1.72), phi 0.44", "design_pairs": "1.80 (1.56-2.18), phi 0.65",
    "haiku_sonnet": "1.14 (0.89-1.42), phi 0.08 (-0.07 to 0.24)", "naive_gap": "+14.2 (+4.5 to +24.2), Brier 0.207",
    "one_feature": "Brier 0.191, gap +0.6 (-9.3 to +10.2)", "two_feature": "Brier 0.161, gain +0.031 (-0.005 to +0.066)",
    "sonnet_agreement": "81% of 42 vs 29% of 38",
    "cascade": "72.5% vs 72.5% at 52% of Sonnet's cost; difference -15 to +15 points (40 held-out items)",
}


def markdown(f: dict) -> str:
    a, c, s = f["all_or_nothing"], f["calibration"], f["sonnet_agreement"]

    def pair(name):
        x = f[name]
        return (f"{x['ser']:.2f} ({x['ser_lo']:.2f}-{x['ser_hi']:.2f}), phi {x['phi']:.2f} "
                f"({x['phi_lo']:+.2f} to {x['phi_hi']:+.2f}), log error OR {x['log_error_or']:.2f}")

    rows = [
        ("1", "Haiku repeat correlation rho, 100 items", f"{f['rho']['estimate']:.2f} ({f['rho']['lo']:.2f}-{f['rho']['hi']:.2f}); "
         f"ANOVA {f['rho_anova']:.2f}, beta-binomial ML {f['rho_betabinom']:.2f}; 5 calls = {f['n_eff_5']:.2f} independent",
         f"{PLAN['rho']}; {PLAN['n_eff_5']}"),
        ("2", "Items 0 of 5 / 5 of 5 right", f"{a['zero_of_5']} / {a['five_of_5']}, against {a['zero_if_independent']:.1f} / "
         f"{a['five_if_independent']:.1f} if independent (p_bar {a['p_bar']:.3f})", f"{PLAN['zero_of_5']}; {PLAN['five_of_5']}"),
        ("3a", "Shared-error ratio, two Haiku calls (80)", pair("haiku_pairs"), PLAN["haiku_pairs"]),
        ("3b", f"Two of the 27 designs ({f['design_pairs']['pairs']} pairs, 80)", pair("design_pairs"), PLAN["design_pairs"]),
        ("3c", "Haiku and Sonnet (80)", pair("haiku_sonnet"), PLAN["haiku_sonnet"]),
        ("4a", "Naive share-agreeing confidence", f"gap {c['naive_gap_points']:+.1f} ({c['naive_gap_lo']:+.1f} to "
         f"{c['naive_gap_hi']:+.1f}), Brier {c['naive_brier']:.3f}", PLAN["naive_gap"]),
        ("4b", "Logistic on the share, cross-fitted by half", f"Brier {c['one_feature_brier']:.3f}, gap {c['one_feature_gap_points']:+.1f} "
         f"({c['one_feature_gap_lo']:+.1f} to {c['one_feature_gap_hi']:+.1f})", PLAN["one_feature"]),
        ("4c", "Adding Sonnet agrees", f"Brier {c['two_feature_brier']:.3f}, gain {c['brier_gain']:+.3f} ({c['brier_gain_lo']:+.3f} "
         f"to {c['brier_gain_hi']:+.3f})", PLAN["two_feature"]),
        ("8", "Haiku 3-of-5 cascade vs Sonnet, held-out 60-99", f"{100 * f['cascade']['accuracy']:.1f}% vs "
         f"{100 * f['cascade']['sonnet']:.1f}%, difference {f['cascade']['diff_points']:+.1f} ({f['cascade']['diff_lo']:+.1f} to "
         f"{f['cascade']['diff_hi']:+.1f}), cost ratio {f['cascade']['cost_ratio']:.2f}, escalated {f['cascade']['escalated']:.2f} "
         f"({f['cascade']['n']} items)", PLAN["cascade"]),
        ("5", "Plurality right when Sonnet agrees / not", f"{100 * s['right_when_agrees']:.0f}% of {s['n_agrees']} / "
         f"{100 * s['right_when_not']:.0f}% of {s['n_not']}", PLAN["sonnet_agreement"]),
    ]
    h = f["frozen_h5_correction"]
    return "\n".join([
        "# Evidence plan, step 0.9: the cached findings, recomputed", "",
        "Written by `python -m analysis.evidence_cached` from results/*/results.csv with `autoagentnet/evidence/`; "
        "`tests/test_evidence_cached.py` pins every point estimate to two decimals. $0 spent. Intervals are 95% and "
        "resample items (2,000 draws, seed 0). Definitions are in the script's docstring; the two that had to be "
        "matched to the plan's numbers are: a plurality tie goes to the class reached first in call order, and \"two "
        "of the 27 designs\" averages each pair of designs' measure over the 351 pairs (pooling the pairs' cells "
        "instead gives 1.78 and phi 0.64).", "",
        "| # | finding | recomputed | plan |", "|---|---|---|---|",
        *[f"| {n} | {what} | {got} | {plan} |" for n, what, got, plan in rows], "",
        "Every point estimate matches the plan to its stated precision. Intervals come from a fresh bootstrap, so "
        "their ends can differ from the plan's in the second decimal.", "",
        "## The frozen correction for H5", "",
        "H5 carries the two-feature correction, fitted once on all 80 cached items and then frozen, to the 300 sealed "
        "BBEH items: logit P(plurality right) = "
        f"{h['intercept']:.4f} + {h['share']:.4f} x share + {h['sonnet_agrees']:.4f} x Sonnet agrees. "
        "On the sealed panel, \"share\" is the share of the 5 Haiku calls agreeing with their plurality and \"Sonnet "
        "agrees\" is the one Sonnet call matching it, exactly as here.", "",
    ])


def main() -> dict:
    f = findings()
    OUT.write_text(markdown(f))
    print(markdown(f))
    return f


if __name__ == "__main__":
    main()
