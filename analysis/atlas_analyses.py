"""The Atlas analyses A1-A7 and the SWE-bench findings F17/F18 (session E5, section 4.4). $0, from the committed
response tables in research/v4/atlas/data/. Exploratory throughout: public leaderboard data, one fit per benchmark,
nothing here is a test. Writes research/v4/atlas/atlas.md.

Plain words for what each part computes (the factor model's terms are defined in autoagentnet/atlas/factor.py):
  A1  systematic failure share per benchmark and task family: var(b) / (var(b) + pi^2/3) from the L0 fit (item
      difficulties on the logit scale), and the median over systems of the L1 share beta_s^2 / (beta_s^2 + pi^2/3)
      (L1 scales b to variance 1); with held-out log loss of L0 and L1 against the base rate.
  A2  the tail: the share of items every system of a random k-set gets wrong, observed against independence, the
      L0, L1 and L2 models, and a one-factor Gaussian copula (in-sample fits on the same rows).
  A3  vote vs selection, for systems with repeats: vote@k (plurality of k calls of one system, ties split), pass@k
      (any of k calls of one system right), coverage@k (any of k different systems right, one call each) and the
      best single accuracy within those k-sets.
  A4  selection efficiency eta = (policy - best single) / (coverage - best single), as a ratio of means over random
      k-sets, for label-free policies: plurality vote, Dawid-Skene (plain; with repeats also pooled), shortest
      output, and on SWE-bench fewest steps and lowest cost; and whether Dawid-Skene rates the best system below
      others when many calls share wrong answers.
  A5  compositional prediction: half the systems fit item difficulties (L1); each held-out system's ability and
      beta are fitted on a random half of the items; the model then predicts the coverage of every sampled k-set
      (k <= 5) of held-out systems on the other half of the items, and (with repeats) each held-out system's
      3-vote accuracy. Mean absolute error with an item-bootstrap interval; independence as the baseline.
  A6  depth from public data: pairs of one model at two reasoning settings in one scaffold; the change in ability
      a and in failure beta from the benchmark's L1 fit, with item-bootstrap intervals (b frozen).
  A7  price frontier: per system, accuracy and mean dollars per item; the systems no cheaper system matches.
  F17/F18  the 39 SWE-bench Verified submissions with per-instance details (mini-SWE-agent): pairwise failure
      correlation explained by difficulty alone, same-company excess, systematic share, the all-wrong tail, prices,
      coverage, step-count AUROC and a two-system cascade on steps.

Usage: python -m analysis.atlas_analyses [--resume]   # --resume reuses research/v4/atlas/tables/*.csv
"""

from __future__ import annotations

from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.pruning_phase3a import md
from autoagentnet.atlas import factor as F
from autoagentnet.atlas import schema
from autoagentnet.evidence.calibration import auroc
from autoagentnet.evidence.labelfree import dawid_skene, dawid_skene_pooled

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "research/v4/atlas/data"
OUT = ROOT / "research/v4/atlas/atlas.md"
SEED, N_BOOT, N_SETS = 0, 200, 200
# MathArena sets with the most systems answering every item (used where a complete items x systems matrix is needed)
MATH_SETS = ["matharena/aime_2025", "matharena/hmmt_feb_2025", "matharena/smt_2025", "matharena/apex_shortlist",
             "matharena/arxivmath-0626", "matharena/hmmt_feb_2026"]
SAME = lambda a, b: a == b  # answer classes are already grouped by the grader

# A6: (benchmark, label, low system, high system); one scaffold and one model per pair
DEPTH_PAIRS = [
    ("swebench_verified", "gpt-5.2 default vs high", "20251211_mini-v1.17.2_gpt-5.2-2025-12-11",
     "20251211_mini-v1.17.2_gpt-5.2-2025-12-11-high"),
    ("matharena", "gpt-5.2 low vs high", "openai/gpt-52-low", "openai/gpt-52-high"),
    ("matharena", "gpt-5.2 low vs default", "openai/gpt-52-low", "openai/gpt-52"),
    ("matharena", "o3-mini low vs medium", "openai/o3-mini--low", "openai/o3-mini--medium"),
    ("matharena", "o4-mini low vs high", "openai/o4-mini--low", "openai/o4-mini--high"),
    ("matharena", "gpt-5-nano low vs default", "openai/gpt-5-nano-low", "openai/gpt-5-nano"),
    ("matharena", "grok-3-mini low vs high", "xai/grok-3-mini-low", "xai/grok-3-mini-high"),
    ("matharena", "gemini-3.1-pro low vs default", "gemini/gemini-31-pro-low", "gemini/gemini-31-pro"),
    ("matharena", "fable 5.1 low vs max", "anthropic/fable_51_low", "anthropic/fable_51_max"),
    ("matharena", "opus 5.5 high vs max", "anthropic/opus_55_high", "anthropic/opus_55_max"),
    ("matharena", "gpt-6 astra low vs default", "openai/gpt-6-astra-low", "openai/gpt-6-astra"),
]


DROP_BENCHMARKS = {"matharena/arxivmath-training": "one system answers its 2,605 items, so their difficulty is not identified"}


def load() -> dict[str, pd.DataFrame]:
    ma = schema.read(DATA / "matharena.parquet")
    return {"swebench_verified": schema.read(DATA / "swebench_verified.parquet"),
            "matharena": ma[~ma["benchmark"].isin(DROP_BENCHMARKS)],
            "livebench": schema.read(DATA / "livebench.parquet"),
            "bbeh_phase1": schema.read(DATA / "panels_phase1_bbeh.parquet")}


def pooled(table: pd.DataFrame) -> pd.DataFrame:
    """Item ids made unique across a source's benchmarks (MathArena problem numbers repeat across sets)."""
    t = table.copy()
    t["item"] = t["benchmark"].astype(str) + ":" + t["item"].astype(str)
    return t


def single(table: pd.DataFrame) -> pd.DataFrame:
    return pooled(table[table["call"] == 0])


def complete(Y: pd.DataFrame, min_share: float = 0.95) -> pd.DataFrame:
    """Keep systems that answered at least min_share of the items, then the items all of them answered."""
    keep = Y.columns[Y.notna().mean() >= min_share]
    return Y[keep].dropna()


def long(Y: pd.DataFrame, family: dict | None = None) -> pd.DataFrame:
    t = Y.stack().rename("correct").reset_index()
    t.columns = ["item", "system", "correct"]
    t["family"] = t["system"].map(family or {}).fillna("unknown")
    t["call"] = 0
    return t


def families(table: pd.DataFrame) -> dict:
    return table.drop_duplicates("system").set_index("system")["family"].astype(str).to_dict()


# ---------------------------------------------------------------------------------------------------------
# A1

def a1(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    for source, table in tables.items():
        t = single(table)
        m0, m1 = F.fit(t, "L0"), F.fit(t, "L1")
        bench_of = t.drop_duplicates("item").set_index("item")["benchmark"].astype(str)
        l1_share = float(np.median(m1["beta"] ** 2 / (m1["beta"] ** 2 + F.LOGISTIC_VAR)))
        h0, h1 = F.held_out(t, "L0", by="item"), F.held_out(t, "L1", by="item")
        rows.append({"source": source, "family": "(all)", "items": t["item"].nunique(),
                     "systems": t["system"].nunique(), "accuracy": float(t["correct"].mean()),
                     "share_L0": F.systematic_share(m0["b"]), "share_L1_median": l1_share,
                     "heldout_ll_base": h0["log_loss_base_rate"], "heldout_ll_L0": h0["log_loss"],
                     "heldout_ll_L1": h1["log_loss"]})
        for bench, items in bench_of.groupby(bench_of).groups.items():
            sub = t[t["benchmark"] == bench]
            rows.append({"source": source, "family": bench, "items": len(items), "systems": sub["system"].nunique(),
                         "accuracy": float(sub["correct"].mean()),
                         "share_L0": F.systematic_share(m0["b"].reindex(items))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# A2

def tail_table(Y: pd.DataFrame, fam: dict, k_max: int = 5) -> pd.DataFrame:
    t = long(Y, fam)
    m0, m1, m2 = F.fit(t, "L0"), F.fit(t, "L1"), F.fit(t, "L2")
    rho = F.fit_copula_rho(Y)
    out = F.coverage_table(Y, m0, k_max, max_sets=N_SETS, rho=rho).rename(columns={"model_all_wrong": "L0"})
    out["L1"] = F.coverage_table(Y, m1, k_max, max_sets=N_SETS)["model_all_wrong"]
    out["L2"] = F.coverage_table(Y, m2, k_max, max_sets=N_SETS)["model_all_wrong"]
    out = out.rename(columns={"all_wrong": "observed", "independent_all_wrong": "independent",
                              "copula_all_wrong": "copula"})
    return out.assign(rho=rho)[["k", "observed", "independent", "L0", "L1", "L2", "copula", "rho"]]


def matrices(tables: dict[str, pd.DataFrame]) -> dict[str, tuple[pd.DataFrame, dict]]:
    """Complete items x systems matrices (call 0) per benchmark used by A2, A5 and A7."""
    out = {}
    sw = tables["swebench_verified"]
    out["swebench_verified"] = (complete(F.outcome_matrix(sw)), families(sw))
    lb = tables["livebench"]
    for bench in sorted(lb["benchmark"].unique()):
        sub = lb[lb["benchmark"] == bench]
        out[str(bench)] = (complete(F.outcome_matrix(sub)), families(sub))
    ma = tables["matharena"]
    for bench in MATH_SETS:
        sub = ma[ma["benchmark"] == bench]
        out[bench] = (complete(F.outcome_matrix(sub)), families(sub))
    pn = tables["bbeh_phase1"]
    out["bbeh_phase1"] = (complete(F.outcome_matrix(pooled(pn))), families(pn))
    return out


def a2(mats) -> pd.DataFrame:
    rows = []
    for name, (Y, fam) in mats.items():
        k_max = min(5, Y.shape[1])
        rows.append(tail_table(Y, fam, k_max).assign(benchmark=name, items=len(Y), systems=Y.shape[1]))
    return pd.concat(rows, ignore_index=True)


# ---------------------------------------------------------------------------------------------------------
# A3

def plurality_right(answers: list, correct: list) -> float:
    """Expected correctness of the plurality answer (ties split at random; unparsed answers join no class)."""
    votes = [(a, c) for a, c in zip(answers, correct) if isinstance(a, str)]
    if not votes:
        return 0.0
    counts = pd.Series([a for a, _ in votes]).value_counts()
    top = counts[counts == counts.max()].index
    right = {a: c for a, c in votes}
    return float(np.mean([right[a] for a in top]))


def repeats(table: pd.DataFrame, calls: int) -> pd.DataFrame:
    """Rows of systems with at least `calls` calls on every item they answered (the first `calls` calls)."""
    t = table[table["call"] < calls]
    n = t.groupby(["system", "item"])["call"].nunique()
    full = n[n == calls].reset_index()[["system", "item"]]
    return t.merge(full, on=["system", "item"])


def vote_pass(rep: pd.DataFrame, k: int) -> pd.DataFrame:
    """Per (system, item): vote@k and pass@k of the first k calls."""
    t = rep[rep["call"] < k].sort_values("call")
    g = t.groupby(["system", "item"])
    return pd.DataFrame({"vote": g.apply(lambda x: plurality_right(list(x["answer"]), list(x["correct"]))),
                         "pass": g["correct"].max()}).reset_index()


def a3(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    rows = []
    groups = {bench: tables["matharena"][tables["matharena"]["benchmark"] == bench] for bench in MATH_SETS[:4]}
    groups["bbeh_phase1"] = tables["bbeh_phase1"]
    for name, table in groups.items():
        t = pooled(table)
        calls = 4 if name.startswith("matharena") else 5  # the 3-call MathArena systems are left out here
        rep = repeats(t, calls)
        if name == "bbeh_phase1":
            rep = rep[rep["system"].isin(["haiku_nothink", "luna_none"])]
        Y = complete(F.outcome_matrix(rep))
        rng = np.random.default_rng(SEED)
        systems = list(Y.columns)
        ceiling = vote_pass(rep, calls).groupby("system")["vote"].mean().mean()
        for k in range(1, calls + 1):
            vp = vote_pass(rep, k).groupby("system")[["vote", "pass"]].mean().mean()
            row = {"benchmark": name, "systems": len(systems), "items": len(Y), "k": k, "vote@k": vp["vote"],
                   "pass@k": vp["pass"], "vote ceiling (all calls)": ceiling}
            if k <= len(systems):
                sets = F.sample_sets(systems, k, N_SETS, rng)
                row["coverage@k"] = float(np.mean([(Y[list(s)].max(axis=1) > 0).mean() for s in sets]))
                row["best single in set"] = float(np.mean([Y[list(s)].mean().max() for s in sets]))
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# A4

def eta_sets(table: pd.DataFrame, k: int, with_repeats: int = 0, n_sets: int = 60) -> dict:
    """Mean over random k-sets of systems (one call each, plus repeats for the pooled fit) of best single, coverage
    and each policy's accuracy; eta per policy as a ratio of means."""
    t = pooled(table)
    rep = repeats(t, max(with_repeats, 1))
    first = rep[rep["call"] == 0]
    Y = complete(F.outcome_matrix(first))
    first = first[first["item"].isin(Y.index) & first["system"].isin(Y.columns)]
    rng = np.random.default_rng(SEED)
    systems = list(Y.columns)
    if len(systems) < k:
        return {"k": k, "sets": 0}
    sets = F.sample_sets(systems, k, n_sets, rng)
    has_tokens = first["output_tokens"].notna().all()
    has_answers = first["answer"].notna().any()
    totals = {}
    for s in sets:
        sub = first[first["system"].isin(s)]
        acc = {"best single": float(Y[list(s)].mean().max()), "coverage": float((Y[list(s)].max(axis=1) > 0).mean())}
        if has_answers:
            g = sub.sort_values("system").groupby("item")
            acc["plurality"] = float(g.apply(lambda x: plurality_right(list(x["answer"]), list(x["correct"]))).mean())
            right = sub.dropna(subset=["answer"]).groupby(["item", "answer"])["correct"].max()
            _, ds = dawid_skene(sub[["item", "system", "answer"]].rename(columns={"system": "source"}).dropna(), SAME)
            acc["Dawid-Skene"] = float(np.mean([right.get((r.item, r.answer), 0.0) if r.answer is not None else 0.0
                                                for r in ds.itertuples()]))
            if with_repeats:
                allc = rep[rep["system"].isin(s) & rep["item"].isin(Y.index)]
                right_all = allc.dropna(subset=["answer"]).groupby(["item", "answer"])["correct"].max()
                rows = allc[["item", "system", "answer"]].rename(columns={"system": "source"}).dropna()
                for name, fit in (("Dawid-Skene, all repeats", dawid_skene), ("pooled Dawid-Skene", dawid_skene_pooled)):
                    _, d = fit(rows, SAME)
                    acc[name] = float(np.mean([right_all.get((r.item, r.answer), 0.0) if r.answer is not None else 0.0
                                               for r in d.itertuples()]))
        if has_tokens:
            idx = sub.groupby("item")["output_tokens"].idxmin()
            acc["shortest output"] = float(sub.loc[idx, "correct"].mean())
        if "signal_steps" in sub and sub["signal_steps"].notna().all():
            acc["fewest steps"] = float(sub.loc[sub.groupby("item")["signal_steps"].idxmin(), "correct"].mean())
        if sub["cost_usd"].notna().all():
            acc["lowest cost"] = float(sub.loc[sub.groupby("item")["cost_usd"].idxmin(), "correct"].mean())
        for key, v in acc.items():
            totals[key] = totals.get(key, 0.0) + v / len(sets)
    best, cover = totals.pop("best single"), totals.pop("coverage")
    out = {"k": k, "sets": len(sets), "best single": best, "coverage": cover}
    for name, v in totals.items():
        out[f"{name} acc"] = v
        out[f"{name} gain"] = v - best  # over the best single system of the set (chosen with labels)
        out[f"{name} eta"] = F.eta(v, best, cover)
    return out


def modal_calls(table: pd.DataFrame) -> int:
    """The most common number of calls per system on a benchmark (MathArena sets use 4, a few use 3)."""
    return int(table.groupby("system")["call"].nunique().mode().iloc[0])


def ds_best_system(table: pd.DataFrame, calls: int) -> dict:
    """Dawid-Skene (plain over every call, and pooled) on all systems with `calls` repeats: the true best system's
    true accuracy, its estimates and their ranks among the systems (1 = rated best)."""
    rep = repeats(pooled(table), calls)
    rows = rep[["item", "system", "answer"]].rename(columns={"system": "source"}).dropna()
    truth = rep.groupby("system")["correct"].mean()
    best = truth.idxmax()
    out = {"systems": rep["system"].nunique(), "items": rep["item"].nunique(), "best system": best,
           "true accuracy": truth[best]}
    for name, fit in (("plain", dawid_skene), ("pooled", dawid_skene_pooled)):
        est, _ = fit(rows, SAME)
        out[f"{name} estimate"] = est[best]
        out[f"{name} rank"] = int(est.rank(ascending=False)[best])
        out[f"{name} rank corr"] = float(pd.Series(est).corr(truth.reindex(est.index), method="spearman"))
    return out


def a4_ds(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    ds = []
    for bench in ["matharena/aime_2025", "matharena/hmmt_feb_2025", "matharena/smt_2025", "matharena/arxivmath-0626"]:
        sub = tables["matharena"][tables["matharena"]["benchmark"] == bench]
        ds.append({"benchmark": bench, **ds_best_system(sub, modal_calls(sub))})
    return pd.DataFrame(ds)


def a5_votes_all(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    return pd.concat([a5_votes(tables["matharena"][tables["matharena"]["benchmark"] == bench]).assign(benchmark=bench)
                      for bench in MATH_SETS[:4]], ignore_index=True)  # sets with 4 repeats per system


def a4(tables: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    for bench in ["matharena/aime_2025", "matharena/hmmt_feb_2025", "matharena/arxivmath-0626"]:
        sub = tables["matharena"][tables["matharena"]["benchmark"] == bench]
        calls = modal_calls(sub)
        for k in (3, 5):
            rows.append({"benchmark": bench, "repeats": calls, **eta_sets(sub, k, with_repeats=calls)})
    sw = tables["swebench_verified"]
    per = pd.read_csv(DATA / "swebench_verified_systems.csv").set_index("system")["per_instance"]
    sw = sw[sw["system"].isin(per.index[per])]
    for k in (3, 5):
        rows.append({"benchmark": "swebench_verified (39 with details)", **eta_sets(sw, k)})
    pn = tables["bbeh_phase1"]
    rows.append({"benchmark": "bbeh_phase1", **eta_sets(pn, 3)})
    return pd.DataFrame(rows), None


# ---------------------------------------------------------------------------------------------------------
# A5

def fit_system(b: np.ndarray, y: np.ndarray, l2: float = 0.1) -> tuple[float, float]:
    """(a, beta) of one system on items with frozen difficulties b."""
    theta = F._newton_1d_groups(np.column_stack([np.ones(len(b)), -b]), y, np.zeros(len(b)), np.zeros(len(b), int), 1, l2)
    return float(theta[0, 0]), float(theta[0, 1])


def a5_matrix(Y: pd.DataFrame, fam: dict, seed: int = SEED) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    systems = list(rng.permutation(Y.columns))
    fit_s, held = systems[: len(systems) // 2], systems[len(systems) // 2:]
    items = list(rng.permutation(Y.index))
    cal, test = items[: len(items) // 2], items[len(items) // 2:]
    model = F.fit(long(Y[fit_s], fam), "L1")
    b = model["b"]
    P = {}
    for s in held:
        a, beta = fit_system(b[cal].to_numpy(), Y.loc[cal, s].to_numpy(float))
        P[s] = F.sigmoid(a - beta * b[test].to_numpy())
    P = pd.DataFrame(P, index=test)
    acc_cal = Y.loc[cal, held].mean()
    Yt = Y.loc[test, held]
    rows = []
    for k in range(1, min(5, len(held)) + 1):
        sets = F.sample_sets(held, k, N_SETS, rng)
        pred = np.column_stack([1 - np.prod(1 - P[list(s)].to_numpy(), axis=1) for s in sets])  # items x sets
        obs = np.column_stack([Yt[list(s)].max(axis=1).to_numpy() for s in sets])
        indep = np.array([1 - np.prod(1 - acc_cal[list(s)].to_numpy()) for s in sets])

        def mae(idx):
            return float(np.abs(pred[idx].mean(axis=0) - obs[idx].mean(axis=0)).mean())

        def mae_indep(idx):
            return float(np.abs(indep - obs[idx].mean(axis=0)).mean())

        draws = [rng.integers(0, len(test), len(test)) for _ in range(N_BOOT)]
        all_idx = np.arange(len(test))
        mb, ib = [mae(d) for d in draws], [mae_indep(d) for d in draws]
        rows.append({"k": k, "sets": len(sets), "observed coverage": float(obs.mean()),
                     "model bias": float((pred.mean(axis=0) - obs.mean(axis=0)).mean()), "model MAE": mae(all_idx), "model lo": float(np.percentile(mb, 2.5)),
                     "model hi": float(np.percentile(mb, 97.5)), "independent MAE": mae_indep(all_idx),
                     "independent lo": float(np.percentile(ib, 2.5)), "independent hi": float(np.percentile(ib, 97.5))})
    return pd.DataFrame(rows).assign(fit_systems=len(fit_s), held_systems=len(held), test_items=len(test))


def coincidence(rows: pd.DataFrame) -> float:
    """Share of pairs of wrong (parsed) calls on one item that give the same answer."""
    same = total = 0
    for _, g in rows[(rows["correct"] == 0) & rows["answer"].notna()].groupby("item"):
        a = list(g["answer"])
        for i in range(len(a)):
            for j in range(i + 1, len(a)):
                total += 1
                same += a[i] == a[j]
    return same / total if total else 0.5


def a5_votes(table: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Held-out systems' predicted vs observed 3-vote accuracy on test items (MathArena, 4 repeats)."""
    rng = np.random.default_rng(seed)
    rep = repeats(pooled(table), 4)
    Y = complete(F.outcome_matrix(rep))
    systems = list(rng.permutation(Y.columns))
    fit_s, held = systems[: len(systems) // 2], systems[len(systems) // 2:]
    items = list(rng.permutation(Y.index))
    cal, test = items[: len(items) // 2], items[len(items) // 2:]
    b = F.fit(long(Y[fit_s]), "L1")["b"]
    rows = []
    for s in held:
        a, beta = fit_system(b[cal].to_numpy(), Y.loc[cal, s].to_numpy(float))
        p = F.sigmoid(a - beta * b[test].to_numpy())
        mine = rep[rep["system"] == s]
        q = coincidence(mine[mine["item"].isin(cal)])
        observed = vote_pass(mine[mine["item"].isin(test)], 3)["vote"].mean()
        rows.append({"system": s, "q": q, "predicted 3-vote": float(F.vote_accuracy(p, 3, q).mean()),
                     "observed 3-vote": float(observed)})
    return pd.DataFrame(rows)


def a5(mats, tables) -> tuple[pd.DataFrame, None]:
    cov = pd.concat([a5_matrix(Y, fam).assign(benchmark=name) for name, (Y, fam) in mats.items()
                     if Y.shape[1] >= 8], ignore_index=True)
    return cov, None


# ---------------------------------------------------------------------------------------------------------
# A6

def a6(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    fits = {}
    rows = []
    rng = np.random.default_rng(SEED)
    for source, label, low, high in DEPTH_PAIRS:
        if source not in fits:
            fits[source] = (F.fit(single(tables[source]), "L1"), single(tables[source]))
        model, t = fits[source]
        if low not in model["a"].index or high not in model["a"].index:
            rows.append({"benchmark": source, "pair": label, "note": "a system is missing"})
            continue
        both = (t[t["system"].isin([low, high])].assign(correct=lambda x: x["correct"].astype(float))
                .pivot_table(index="item", columns="system", values="correct").dropna())
        if len(both) < 10 or low not in both or high not in both:
            rows.append({"benchmark": source, "pair": label, "items": len(both), "note": "fewer than 10 shared items"})
            continue
        bb = model["b"].reindex(both.index).to_numpy()
        da, dbeta = [], []
        for _ in range(N_BOOT):
            idx = rng.integers(0, len(both), len(both))
            (a0, b0), (a1, b1) = (fit_system(bb[idx], both[s].to_numpy(float)[idx]) for s in (low, high))
            da.append(a1 - a0)
            dbeta.append(b1 - b0)
        rows.append({"benchmark": source, "pair": label, "items": len(both),
                     "acc low": float(both[low].mean()), "acc high": float(both[high].mean()),
                     "a low": model["a"][low], "a high": model["a"][high],
                     "delta a": model["a"][high] - model["a"][low], "delta a lo": float(np.percentile(da, 2.5)),
                     "delta a hi": float(np.percentile(da, 97.5)),
                     "beta low": model["beta"][low], "beta high": model["beta"][high],
                     "delta beta": model["beta"][high] - model["beta"][low],
                     "delta beta lo": float(np.percentile(dbeta, 2.5)), "delta beta hi": float(np.percentile(dbeta, 97.5))})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# A7

def frontier(table: pd.DataFrame) -> pd.DataFrame:
    """Per system accuracy and mean dollars per item, over systems with a known positive cost on at least 90% of the
    benchmark's items; frontier = no cheaper system is at least as accurate."""
    n_items = table["item"].nunique()
    t = table[table["cost_usd"].notna() & (table["cost_usd"] > 0)]  # MathArena books 0 where the price is unknown
    per = t.groupby("system").agg(accuracy=("correct", "mean"), usd=("cost_usd", "mean"), items=("item", "nunique"))
    per = per[per["items"] >= 0.9 * n_items]
    per = per.sort_values(["usd", "accuracy"], ascending=[True, False]).reset_index()
    per["frontier"] = per["accuracy"] > per["accuracy"].cummax().shift(fill_value=-1.0)
    return per


def a7(tables: dict[str, pd.DataFrame]) -> pd.DataFrame:
    groups = {"swebench_verified": tables["swebench_verified"], "bbeh_phase1": tables["bbeh_phase1"]}
    for bench in ["matharena/hmmt_feb_2026", "matharena/arxivmath-0626", "matharena/aime_2025"]:
        groups[bench] = tables["matharena"][tables["matharena"]["benchmark"] == bench]
    rows = []
    for name, t in groups.items():
        f = frontier(t)
        rows.append(f[f["frontier"]].assign(benchmark=name, systems_with_cost=len(f)))
    return pd.concat(rows, ignore_index=True)[["benchmark", "systems_with_cost", "system", "accuracy", "usd", "items"]]


# ---------------------------------------------------------------------------------------------------------
# F17 / F18

def phi_matrix(Y: pd.DataFrame) -> np.ndarray:
    return np.corrcoef(1 - Y.to_numpy(float).T)


def implied_phi(P: np.ndarray) -> np.ndarray:
    """Failure correlations implied by a model with independent calls given the item: P is items x systems."""
    Q = 1 - P
    m = Q.mean(axis=0)
    cov = (Q.T @ Q) / len(Q) - np.outer(m, m)
    var = m * (1 - m)  # the variance of a 0/1 failure with mean m
    out = cov / np.sqrt(np.outer(var, var))
    np.fill_diagonal(out, 1.0)
    return out


def f17_f18(tables: dict[str, pd.DataFrame]) -> dict:
    sw = tables["swebench_verified"]
    systems = pd.read_csv(DATA / "swebench_verified_systems.csv").set_index("system")
    detailed = sw[sw["system"].isin(systems.index[systems["per_instance"]])]  # the 39 with per-instance details
    Y = F.outcome_matrix(detailed)
    org = systems["org"].str.lower().str.replace(r"[^a-z]", "", regex=True).replace({"zai": "zai", "deepseek": "deepseek"})
    t = long(Y, org.to_dict())
    m0, m1 = F.fit(t, "L0"), F.fit(t, "L1")
    P0 = np.column_stack([F.predict(m0, np.repeat(s, len(Y)), Y.index.to_numpy()) for s in Y.columns])
    obs, imp = phi_matrix(Y), implied_phi(P0)
    iu = np.triu_indices(len(Y.columns), 1)
    o = org.reindex(Y.columns).to_numpy()
    same = (o[:, None] == o[None, :])[iu]
    resid = (obs - imp)[iu]
    rho = F.fit_copula_rho(Y)
    acc = Y.mean()
    cost = detailed.groupby("system")["cost_usd"].mean()  # missing for a submission without per-instance costs
    steps = detailed.pivot_table(index="item", columns="system", values="signal_steps")
    au = {s: auroc(-steps[s].to_numpy(float), Y[s].to_numpy(float)) for s in Y.columns
          if 0 < Y[s].mean() < 1 and steps[s].notna().all()}
    pairs = [(s, u) for s, u in combinations(Y.columns, 2)]
    cov2 = max(((Y[s].values + Y[u].values) > 0).mean() for s, u in pairs)
    out = {
        "systems": Y.shape[1], "items": len(Y),
        "mean observed failure correlation": float(obs[iu].mean()),
        "mean L0-implied failure correlation": float(imp[iu].mean()),
        "share explained by difficulty alone": float(imp[iu].mean() / obs[iu].mean()),
        "same-company pairs": int(same.sum()), "other pairs": int((~same).sum()),
        "residual correlation, same company": float(resid[same].mean()),
        "residual correlation, other": float(resid[~same].mean()),
        "same-company excess": float(resid[same].mean() - resid[~same].mean()),
        "systematic share (L0)": F.systematic_share(m0["b"]),
        "all-wrong observed": float((Y.max(axis=1) == 0).mean()),
        "all-wrong independent": float(np.prod(1 - acc)),
        "all-wrong L0": F.all_wrong_implied(m0, Y.columns, Y.index),
        "all-wrong L1": F.all_wrong_implied(m1, Y.columns, Y.index),
        "all-wrong copula": F.copula_all_wrong(acc.to_numpy(), rho), "copula rho": rho,
        "coverage@2 (best pair)": float(cov2), "coverage@39": float((Y.max(axis=1) > 0).mean()),
        "best single": float(acc.max()), "best single system": acc.idxmax(),
        "step AUROC median": float(np.median(list(au.values()))), "step AUROC min": float(min(au.values())),
        "step AUROC max": float(max(au.values())), "step AUROC systems": len(au),
    }
    prices = pd.DataFrame({"accuracy": acc, "usd": cost}).sort_values("accuracy", ascending=False)
    cascade = cascade_table(Y, steps, cost_matrix=detailed.pivot_table(index="item", columns="system", values="cost_usd"))
    return {"numbers": out, "prices": prices, "cascade": cascade}


CASCADES = [("20260217_mini-v2.0.0_minimax-2-5-high", "20260217_mini-v2.0.0_claude-4-5-opus-high"),
            ("20260217_mini-v2.0.0_gemini-3-flash-high", "20260217_mini-v2.0.0_claude-4-5-opus-high")]


def cascade_table(Y: pd.DataFrame, steps: pd.DataFrame, cost_matrix: pd.DataFrame, seed: int = SEED) -> pd.DataFrame:
    """Cheap system first; escalate to the strong one when the cheap run took more steps than a threshold. The
    threshold is the step quantile (from 0.5 to 1.0) that maximises accuracy minus 1 point per $0.10 on a random half
    of the items; it is scored on the other half."""
    rng = np.random.default_rng(seed)
    items = rng.permutation(Y.index)
    fit_i, test_i = items[: len(items) // 2], items[len(items) // 2:]
    rows = []
    for cheap, strong in CASCADES:
        if cheap not in Y or strong not in Y:
            continue

        def run(idx, thr):
            esc = steps.loc[idx, cheap].to_numpy() > thr
            acc = np.where(esc, Y.loc[idx, strong], Y.loc[idx, cheap]).mean()
            usd = (cost_matrix.loc[idx, cheap].to_numpy() + esc * cost_matrix.loc[idx, strong].to_numpy()).mean()
            return float(acc), float(usd), float(esc.mean())

        grid = np.quantile(steps.loc[fit_i, cheap], np.linspace(0.5, 1.0, 11))
        best = max(grid, key=lambda thr: run(fit_i, thr)[0] - 0.1 * run(fit_i, thr)[1])
        acc, usd, esc = run(test_i, best)
        rows.append({"cheap": cheap, "strong": strong, "threshold steps": float(best), "escalated": esc,
                     "cascade acc": acc, "cascade usd": usd,
                     "cheap acc": float(Y.loc[test_i, cheap].mean()), "cheap usd": float(cost_matrix.loc[test_i, cheap].mean()),
                     "strong acc": float(Y.loc[test_i, strong].mean()),
                     "strong usd": float(cost_matrix.loc[test_i, strong].mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------

TABLES = ROOT / "research/v4/atlas/tables"


def section(name: str, fn, resume: bool) -> pd.DataFrame:
    """Compute one result table and save it to research/v4/atlas/tables/<name>.csv; with resume, reuse the saved
    one (the full run takes most of an hour)."""
    path = TABLES / f"{name}.csv"
    if resume and path.exists():
        return pd.read_csv(path)
    TABLES.mkdir(parents=True, exist_ok=True)
    frame = fn()
    frame.to_csv(path, index=False)
    return frame


def main(resume: bool = False) -> str:
    tables = load()
    mats = matrices(tables)
    r1 = section("a1_systematic_share", lambda: a1(tables), resume)
    r2 = section("a2_tail", lambda: a2(mats), resume)
    r3 = section("a3_vote_vs_selection", lambda: a3(tables), resume)
    r4 = section("a4_eta", lambda: a4(tables)[0], resume)
    r4ds = section("a4_dawid_skene", lambda: a4_ds(tables), resume)
    r5 = section("a5_coverage", lambda: a5(mats, tables)[0], resume)
    r5v = section("a5_votes", lambda: a5_votes_all(tables), resume)
    r6 = section("a6_depth", lambda: a6(tables), resume)
    r7 = section("a7_frontier", lambda: a7(tables), resume)
    once = {}

    def swe():  # F17/F18 computed once, whichever of its three tables is asked for first
        if not once:
            once.update(f17_f18(tables))
        return once

    f = {"numbers": section("f17_numbers", lambda: pd.DataFrame(
             [{"quantity": k, "value": v} for k, v in swe()["numbers"].items()]), resume),
         "prices": section("f18_prices", lambda: swe()["prices"].reset_index().rename(columns={"index": "system"}),
                           resume),
         "cascade": section("f18_cascade", lambda: swe()["cascade"], resume)}
    sizes = pd.DataFrame([{"benchmark": k, "items": len(Y), "systems": Y.shape[1]} for k, (Y, _) in mats.items()])
    text = "\n".join([
        "# The Atlas: why systems fail together, and what that leaves for votes, selection and depth", "",
        "Session E5, section 4.4. Written by `python -m analysis.atlas_analyses` from research/v4/atlas/data/ (sources "
        "and hashes in its MANIFEST.md); definitions in the script's docstring and in autoagentnet/atlas/factor.py. "
        "Exploratory throughout: public leaderboard data, one fit per benchmark, nothing here is a test. Fits use a "
        "ridge of 0.1 on every coefficient, so items every system gets right (or wrong) get large but finite "
        "difficulties; the L0 share depends on that ridge. Left out: " + "; ".join(f"{k} ({v})" for k, v in
        DROP_BENCHMARKS.items()) + ".", "",
        "Complete items x systems matrices used by A2, A5 and A7 (systems that answered at least 95% of the items, "
        "then the items all of them answered):", "", md(sizes, 0), "",
        "## A1. Systematic failure share", "", md(r1, 3), "",
        "## A2. The tail: all-wrong rate of random k-sets, observed vs models (in-sample)", "", md(r2, 4), "",
        "## A3. Vote vs selection, systems with repeats", "", md(r3, 3), "",
        "## A4. Selection efficiency of label-free policies (ratio of means over random k-sets)", "",
        "gain = policy accuracy minus the best single system of the set (that system is chosen with labels); eta "
        "divides the gain by the room above the best single system (coverage minus best), so it swings widely where "
        "that room is a few points.", "", md(r4, 3), "",
        "Dawid-Skene on every system with 4 repeats (plain: every call a witness; pooled: one soft vote per system):",
        "", md(r4ds, 3), "",
        "## A5. Compositional prediction on held-out systems and items", "",
        "Coverage of k-sets of held-out systems on held-out items: mean signed error (bias) and mean absolute error of "
        "the factor model (L1), and the MAE of independence, with 95% item-bootstrap intervals. An absolute error is "
        "biased upward under resampling, so an interval can sit above its estimate.", "", md(r5, 4), "",
        "3-vote accuracy of held-out MathArena systems (4 repeats) from one-call success and wrong-answer coincidence:",
        "", md(r5v.groupby("benchmark").apply(lambda g: pd.Series({
            "systems": len(g), "MAE": float((g["predicted 3-vote"] - g["observed 3-vote"]).abs().mean()),
            "mean predicted": g["predicted 3-vote"].mean(), "mean observed": g["observed 3-vote"].mean()})).reset_index(), 4), "",
        "## A6. Depth from public data: one model at two reasoning settings", "", md(r6, 3), "",
        "## A7. Price frontier (systems no cheaper system matches)", "", md(r7, 4), "",
        "## F17/F18. SWE-bench Verified, the 39 submissions with per-instance details", "",
        md(f["numbers"], 4), "",
        "Accuracy and mean dollars per instance:", "", md(f["prices"], 4), "",
        "Two-system cascades on step count (threshold fitted on half the items, scored on the other half; post hoc):", "",
        md(f["cascade"], 4), ""])
    OUT.write_text(text)
    print(text)
    return text


if __name__ == "__main__":
    import sys

    main(resume="--resume" in sys.argv)
