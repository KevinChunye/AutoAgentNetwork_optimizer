"""Searches over pruned agent networks, static and dynamic, and their baselines (Phase 3 of the evidence plan).

Everything is replayed from cached calls (replay.py), so a search costs nothing; the question is which
search finds good cheap networks, judged on items it did not see.

Terms (plain words first):
  direction    a (search rows, eval rows) pair of item sets: a search chooses networks and fits their
               aggregators on the search rows; the chosen networks are scored on the eval rows. Two folds give
               two directions; "cross-fitted" numbers average them.
  path         the sequence of networks a pruning method passes through, from the full network down to one
               group (or one call), one row per step: the kept units, dollars per item and scores.
  one-shot     rank the groups once, on the full network, and remove them in that order.
  iterative    re-rank the remaining groups after every removal (and refit).
  refit        the aggregator after pruning (replay.py): Kevin's plurality-plus-logistic aggregator refitted
               with a ridge ("ridge", the default) or without ("plain"), or the dense aggregator restricted to the
               kept calls ("restrict"); for comparison the plain vote ("none", AMC's "no fine-tuning") and the
               weighted vote ("weights").
  source       one model at one setting with one prompt (replay.py's units table, column "source"); calls
               within a source are exchangeable, so a source keeps its first k calls.
  frontier     the networks no other evaluated network beats on both cost and score (Pareto): for each cost,
               the best score at that cost or less. The exhaustive frontier is an oracle: it picks the best
               network after seeing the eval rows.
  regret       of a network: frontier score at its cost minus its score (0 = on the frontier).

Searches:
  S1  sensitivity       Kevin's version (`s1_curves`, `s1_sensitivity`): prune one source at a time down to 0
                        calls, the others at full, and record the search-half score: one curve per source. A
                        threshold T then keeps, per source, the fewest calls whose loss against the full network
                        is at most T; sweeping T gives a path. Its two flaws: it ignores interactions (two
                        sources that are each dispensable alone may not be dispensable together), and it ignores
                        cost (a loss of T points is treated the same for a $0.0007 call and a $0.0144 one).
                        `sensitivity_vote` is the one-group-at-a-time ranking used as a pruning criterion.
  S2  NetAdapt          (Yang et al. 2018) start from the full network; each step must cut the resource by at
                        least `step` (dollars per item by default: $0.0005); for every layer (a source) propose
                        removing its fewest calls (the last call indices first: calls within a source are
                        exchangeable) that meet the cut, refit each proposal on the search rows, keep the
                        best-scoring one; repeat until one call is left. The resource can be dollars or seconds
                        (the slowest kept call); a static flat panel always takes one round, so "rounds" applies
                        only to dynamic policies and staged networks (`grid_netadapt`).
  S3  controller        AMC-style (He et al. 2018): sources are visited in a fixed order and an action is a keep
                        fraction per source (keep the first round(fraction x width) calls); the budget is
                        enforced by clipping each action to what the dollars left allow (AMC's
                        resource-constrained mode), and the reward is the search-half score (-error). A
                        cross-entropy-method controller (a Gaussian over fractions, refitted to the best quarter
                        of each population) maximizes it; with reward "log" it maximizes score - lam *
                        log2(dollars / full dollars) instead. The reward uses the plain vote (AMC's proxy:
                        accuracy without fine-tuning) unless told otherwise; `proxy_spearman` tests that proxy
                        against refit scores. DDPG, AMC's own agent, is not built: with a handful of sources CEM
                        searches the same space (its state features, price, accuracy, correlation and budget,
                        would only matter to a learned policy).
  S4  exhaustive        `s4_counts`: every call-count vector (each source keeps 0 to all of its calls, the first
                        k), its frontier and each method's regret; `s4_exhaustive` enumerates every subset of
                        groups instead (an oracle that may also pick which exchangeable calls to keep).

Dynamic policies (per item, calls in sequence): call units in an order; after each call the aggregator of
that prefix (fitted on the search rows) gives an answer and a confidence; stop when the confidence reaches
tau, else call the next unit. `gain_order` builds the order greedily on the search rows: the next unit is
the one with the largest expected accuracy gain per dollar on the items still unsure (confidence < tau)
after the current prefix. Each prefix's aggregator is fitted on all search rows, not only on the items that
reach it.

Baselines: random subsets at matched cost, cheapest-first, top-k accurate (by the calls' own accuracy on
the search rows), the H7 cascade (cheap vote, escalate to one expensive call when fewer than k agree),
single sources, and the full network refitted ("dense refit").
"""

from __future__ import annotations

import itertools
import math

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from autoagentnet.evidence.decisions import cascade

from .criteria import live
from .replay import Grid, Panel, cross_fit, fit, predict, replay, score_of


def directions(folds: np.ndarray) -> list[tuple[np.ndarray, np.ndarray]]:
    """(search rows, eval rows) for each fold as the eval set."""
    return [(np.flatnonzero(folds != k), np.flatnonzero(folds == k)) for k in np.unique(folds)]


def held_out(panel: Panel, kept, search_rows, eval_rows, refit: str = "ridge") -> dict:
    """Fit on the search rows, score on the eval rows: score, accuracy, dollars, seconds per item."""
    kept = np.asarray(kept, dtype=bool)
    frame = replay(panel, kept, eval_rows, fit(panel, kept, search_rows, refit))
    out = {"score": score_of(frame, panel.kind), "accuracy": float(frame["correct"].mean()),
           "dollars": float(frame["dollars"].mean()), "tokens": float(frame["tokens"].mean()),
           "seconds": float(frame["seconds"].mean())}
    if panel.kind == "prob":
        out["brier"] = float(frame["brier"].mean())
    return out


def in_sample(panel: Panel, kept, rows, refit: str = "ridge") -> float:
    kept = np.asarray(kept, dtype=bool)
    if not kept.any():
        return -np.inf
    return score_of(replay(panel, kept, rows, fit(panel, kept, rows, refit)), panel.kind)


def units_of(grp: dict) -> np.ndarray:
    return np.unique(np.concatenate(list(grp.values())))


def mask_of(panel: Panel, units) -> np.ndarray:
    kept = np.zeros(panel.m, dtype=bool)
    kept[np.asarray(units, dtype=int)] = True
    return kept


def kept_names(panel: Panel, kept) -> str:
    return "+".join(panel.units.loc[np.flatnonzero(kept), "unit"])


def step_row(panel, kept, search_rows, eval_rows, refit, **extra) -> dict:
    row = {**extra, "kept": kept_names(panel, kept), "n_units": int(kept.sum()),
           "search_score": in_sample(panel, kept, search_rows, refit)}
    if eval_rows is not None:
        row.update(held_out(panel, kept, search_rows, eval_rows, refit))
    else:
        row["dollars"] = float(panel.mean_cost(search_rows)[kept].sum())
    return row


# ---------------------------------------------------------------------------------------------------------
# criterion-ordered pruning (S1 and the C1-C7 paths)

def sensitivity_vote(panel: Panel, kept, grp: dict, rows=None) -> pd.Series:
    """S1's score: the vote's score loss on `rows` when the group alone is removed (no refit)."""
    kept = np.asarray(kept, dtype=bool)
    base = score_of(predict(panel, kept, rows), panel.kind)
    out = {}
    for name, u in live(kept, grp).items():
        less = kept.copy()
        less[u] = False
        out[name] = base - score_of(predict(panel, less, rows), panel.kind) if less.any() else np.inf
    return pd.Series(out)


def removal_order(scores: pd.Series, dollars: pd.Series) -> list[str]:
    """Lowest score first; ties: the more expensive group first."""
    frame = pd.DataFrame({"score": scores, "dollars": dollars.reindex(scores.index)})
    return frame.sort_values(["score", "dollars"], ascending=[True, False], kind="stable").index.tolist()


def prune_path(panel: Panel, grp: dict, criterion, search_rows, eval_rows=None, iterative: bool = True,
               refit: str = "ridge") -> pd.DataFrame:
    """Remove the lowest-scoring group until one is left; one row per network on the way (step 0 = full)."""
    kept = mask_of(panel, units_of(grp))
    cost = panel.mean_cost(search_rows)
    rows = [step_row(panel, kept, search_rows, eval_rows, refit, step=0, removed=None)]
    order = None
    for step in range(1, len(grp)):
        alive = live(kept, grp)
        if len(alive) <= 1:
            break
        if iterative or order is None:
            scores = criterion(panel, kept, grp, search_rows)
            dollars = pd.Series({k: float(cost[u].sum()) for k, u in alive.items()})
            order = removal_order(scores, dollars)
        name = next(k for k in order if k in alive)
        kept = kept.copy()
        kept[alive[name]] = False
        rows.append(step_row(panel, kept, search_rows, eval_rows, refit, step=step, removed=name))
    return pd.DataFrame(rows)


def s1_curves(panel: Panel, sources: dict, rows, refit: str = "ridge") -> pd.DataFrame:
    """One row per (source, kept calls): the in-sample score on `rows` with that source cut to its first k calls
    and every other source at full; loss = full score - score."""
    full = mask_of(panel, units_of(sources))
    base = in_sample(panel, full, rows, refit)
    out = []
    for name, units in sources.items():
        order = np.sort(units)
        for k in range(len(order), -1, -1):
            kept = full.copy()
            kept[order[k:]] = False
            score = in_sample(panel, kept, rows, refit) if kept.any() else 0.0
            out.append({"source": name, "kept_calls": k, "score": score, "loss": base - score,
                        "dollars": resource_of(panel, kept, rows, "dollars")})
    return pd.DataFrame(out)


def s1_keep(curves: pd.DataFrame, sources: dict, threshold: float) -> dict:
    """Per source, the fewest kept calls whose loss is at most `threshold` (the full count if none is)."""
    keep = {}
    for name, units in sources.items():
        part = curves[(curves["source"] == name) & (curves["loss"] <= threshold + 1e-12)]
        keep[name] = int(part["kept_calls"].min()) if len(part) else len(units)
    return keep


def s1_sensitivity(panel: Panel, sources: dict, search_rows, eval_rows=None, refit: str = "ridge",
                   thresholds=(0.0, 0.0125, 0.025, 0.05, 0.075, 0.1, 0.15, 0.2, 0.3, 1.0)) -> pd.DataFrame:
    """S1's path: one network per threshold T (distinct networks only), from the curves on the search rows."""
    curves = s1_curves(panel, sources, search_rows, refit)
    rows, seen = [], set()
    for t in thresholds:
        kept = keep_counts_to_mask(panel, sources, s1_keep(curves, sources, t))
        if not kept.any() or kept_names(panel, kept) in seen:
            continue
        seen.add(kept_names(panel, kept))
        rows.append(step_row(panel, kept, search_rows, eval_rows, refit, step=len(rows), threshold=t))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# S2: NetAdapt

def resource_of(panel: Panel, kept, rows, resource: str) -> float:
    kept = np.asarray(kept, dtype=bool)
    if not kept.any():
        return 0.0
    if resource == "dollars":
        return float(panel.cost[rows][:, kept].sum(axis=1).mean())
    if resource == "seconds":
        return float(panel.seconds[rows][:, kept].max(axis=1).mean())
    raise ValueError(f"unknown resource {resource}")


def s2_netadapt(panel: Panel, layers: dict, search_rows, eval_rows=None, step: float = 0.0005,
                resource: str = "dollars", refit: str = "ridge") -> pd.DataFrame:
    kept = mask_of(panel, units_of(layers))
    rows = [step_row(panel, kept, search_rows, eval_rows, refit, step=0, removed=None,
                     resource=resource_of(panel, kept, search_rows, resource))]
    k = 0
    while kept.sum() > 1:
        k += 1
        now = resource_of(panel, kept, search_rows, resource)
        target = now - step
        proposals = []
        for name, units in live(kept, layers).items():
            order = np.sort(units)[::-1]  # the last call indices first: calls within a source are exchangeable
            trial = kept.copy()
            removed = []
            for u in order:
                trial[u] = False
                removed.append(u)
                if resource_of(panel, trial, search_rows, resource) <= target + 1e-12:
                    break
            if not trial.any():
                continue
            meets = resource_of(panel, trial, search_rows, resource) <= target + 1e-12
            proposals.append({"layer": name, "trial": trial, "meets": meets,
                              "resource": resource_of(panel, trial, search_rows, resource),
                              "score": in_sample(panel, trial, search_rows, refit), "removed": len(removed)})
        if not proposals:
            break
        table = pd.DataFrame(proposals)
        if table["meets"].any():
            table = table[table["meets"]]
        best = table.sort_values(["score", "resource"], ascending=[False, True], kind="stable").iloc[0]
        kept = best["trial"]
        rows.append(step_row(panel, kept, search_rows, eval_rows, refit, step=k, removed=f"{best['layer']} x{best['removed']}",
                             resource=best["resource"]))
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# S3: AMC-style controller (cross-entropy method)

def keep_counts_to_mask(panel: Panel, layers: dict, counts: dict) -> np.ndarray:
    kept = np.zeros(panel.m, dtype=bool)
    for name, units in layers.items():
        kept[np.sort(units)[:counts[name]]] = True
    return kept


def clip_counts(panel: Panel, layers: dict, counts: tuple, budget: float | None, rows) -> tuple:
    """AMC's budget clipping: visit the sources in order and cut each one's count to what the dollars left
    allow (each call at its mean cost on `rows`)."""
    if budget is None:
        return counts
    cost = panel.mean_cost(rows)
    left, out = budget, []
    for (name, units), c in zip(layers.items(), counts):
        order = np.sort(units)
        k = 0
        while k < c and cost[order[k]] <= left + 1e-12:
            left -= cost[order[k]]
            k += 1
        out.append(k)
    return tuple(out)


def controller_reward(panel, kept, rows, reward: str, budget, lam, full_dollars, proxy: str) -> tuple[float, float, float]:
    """(reward, proxy score, dollars) on `rows`. With reward "budget" the counts were already clipped to the
    budget, so the reward is the score (-error, up to a constant); an empty network scores 0."""
    if not kept.any():
        return 0.0 if reward == "budget" else -1.0, 0.0, 0.0
    dollars = resource_of(panel, kept, rows, "dollars")
    s = score_of(predict(panel, kept, rows), panel.kind) if proxy == "vote" else in_sample(panel, kept, rows, proxy)
    if reward == "budget":
        return s, s, dollars
    return s - lam * math.log2(dollars / full_dollars), s, dollars


def s3_controller(panel: Panel, layers: dict, search_rows, reward: str = "budget", budget: float | None = None,
                  lam: float = 0.05, proxy: str = "vote", iters: int = 15, population: int = 32,
                  elite: float = 0.25, seed: int = 0) -> tuple[np.ndarray, pd.DataFrame]:
    """(best kept mask, history): one history row per distinct network evaluated."""
    rng = np.random.default_rng(seed)
    names = list(layers)
    widths = np.array([len(layers[k]) for k in names])
    full = mask_of(panel, units_of(layers))
    full_dollars = resource_of(panel, full, search_rows, "dollars")
    mu, sd = np.full(len(names), 0.5), np.full(len(names), 0.35)
    seen: dict = {}
    for it in range(iters):
        fractions = np.clip(rng.normal(mu, sd, (population, len(names))), 0, 1)
        rewards = []
        for f in fractions:
            counts = tuple(int(math.floor(x * w + 0.5)) for x, w in zip(f, widths))
            if reward == "budget":
                counts = clip_counts(panel, layers, counts, budget, search_rows)
            if counts not in seen:
                kept = keep_counts_to_mask(panel, layers, dict(zip(names, counts)))
                r, s, d = controller_reward(panel, kept, search_rows, reward, budget, lam, full_dollars, proxy)
                seen[counts] = {"iteration": it, "counts": counts, "reward": r, "proxy_score": s, "dollars": d}
            rewards.append(seen[counts]["reward"])
        top = np.argsort(-np.array(rewards), kind="stable")[: max(2, int(elite * population))]
        mu, sd = fractions[top].mean(axis=0), np.maximum(fractions[top].std(axis=0), 0.05)
    history = pd.DataFrame(seen.values())
    best = history.sort_values(["reward", "dollars"], ascending=[False, True], kind="stable").iloc[0]
    return keep_counts_to_mask(panel, layers, dict(zip(names, best["counts"]))), history


def proxy_spearman(panel: Panel, configs: list, folds, refit: str = "ridge", n_boot: int = 1000, seed: int = 0) -> dict:
    """Does the vote without refit (AMC's proxy) rank networks as the out-of-fold refit score does? Spearman
    correlation between the two per-network scores over `configs` (kept masks), with an item-bootstrap 95%
    interval and the one-sided bootstrap p-value of "correlation <= 0"."""
    def per_item(frame):
        return -frame["brier"].to_numpy() if panel.kind == "prob" else frame["correct"].to_numpy()
    vote = np.column_stack([per_item(predict(panel, k)) for k in configs])
    refitted = np.column_stack([per_item(cross_fit(panel, k, folds, refit)) for k in configs])
    rho = float(spearmanr(vote.mean(axis=0), refitted.mean(axis=0))[0])
    rng = np.random.default_rng(seed)
    draws = []
    for _ in range(n_boot):
        idx = rng.integers(0, panel.n, panel.n)
        draws.append(spearmanr(vote[idx].mean(axis=0), refitted[idx].mean(axis=0))[0])
    draws = np.array(draws, dtype=float)
    draws = draws[np.isfinite(draws)]
    same_top = int(np.argmax(vote.mean(axis=0)) == np.argmax(refitted.mean(axis=0)))
    return {"rho": rho, "lo": float(np.percentile(draws, 2.5)), "hi": float(np.percentile(draws, 97.5)),
            "p_not_positive": float((draws <= 0).mean()), "same_best": same_top, "n_configs": len(configs)}


# ---------------------------------------------------------------------------------------------------------
# S4: exhaustive search, frontier and regret

def subsets(grp: dict, max_groups: int = 14) -> list[tuple[str, ...]]:
    names = list(grp)
    if len(names) > max_groups:
        raise ValueError(f"{len(names)} groups: 2^{len(names)} subsets is too many for exhaustive search")
    return [c for r in range(1, len(names) + 1) for c in itertools.combinations(names, r)]


def s4_exhaustive(panel: Panel, grp: dict, search_rows, eval_rows, refit: str = "ridge") -> pd.DataFrame:
    out = []
    for combo in subsets(grp):
        kept = mask_of(panel, np.concatenate([grp[k] for k in combo]))
        out.append({"groups": "+".join(combo), "kept": kept_names(panel, kept), "n_units": int(kept.sum()),
                    "search_score": in_sample(panel, kept, search_rows, refit),
                    **held_out(panel, kept, search_rows, eval_rows, refit)})
    return pd.DataFrame(out)


def count_vectors(sources: dict, max_configs: int = 20000) -> list[dict]:
    """Every call-count vector (each source keeps 0 to all of its calls) except the empty network."""
    names = list(sources)
    sizes = [len(sources[k]) + 1 for k in names]
    if math.prod(sizes) > max_configs:
        raise ValueError(f"{math.prod(sizes)} count vectors: too many for exhaustive search")
    return [dict(zip(names, c)) for c in itertools.product(*[range(n) for n in sizes]) if sum(c) > 0]


def s4_counts(panel: Panel, sources: dict, search_rows, eval_rows, refit: str = "ridge") -> pd.DataFrame:
    out = []
    for counts in count_vectors(sources):
        kept = keep_counts_to_mask(panel, sources, counts)
        out.append({"counts": " ".join(f"{k}={v}" for k, v in counts.items()), "kept": kept_names(panel, kept),
                    "n_units": int(kept.sum()), "search_score": in_sample(panel, kept, search_rows, refit),
                    **held_out(panel, kept, search_rows, eval_rows, refit)})
    return pd.DataFrame(out)


def pareto(frame: pd.DataFrame, cost: str = "dollars", score: str = "score") -> pd.DataFrame:
    """The frontier: rows sorted by cost whose score beats every cheaper row's."""
    ordered = frame.sort_values([cost, score], ascending=[True, False], kind="stable")
    keep = ordered[score] > ordered[score].cummax().shift(1, fill_value=-np.inf)
    return ordered[keep].reset_index(drop=True)


def frontier_at(frontier: pd.DataFrame, costs, cost: str = "dollars", score: str = "score", tol: float = 1e-9) -> np.ndarray:
    """The frontier's best score at each cost or less (-inf below its cheapest point)."""
    c = frontier[cost].to_numpy()
    s = frontier[score].to_numpy()
    idx = np.searchsorted(c, np.asarray(costs, dtype=float) + tol, side="right") - 1
    return np.where(idx >= 0, s[np.maximum(idx, 0)], -np.inf)


def regret(points: pd.DataFrame, frontier: pd.DataFrame, cost: str = "dollars", score: str = "score") -> np.ndarray:
    return frontier_at(frontier, points[cost], cost, score) - points[score].to_numpy()


# ---------------------------------------------------------------------------------------------------------
# dynamic policies

class Prefixes:
    """Aggregators of the prefixes of a call order, fitted once on the fit rows and cached."""

    def __init__(self, panel: Panel, fit_rows, refit: str = "ridge"):
        self.panel, self.fit_rows, self.refit, self.cache = panel, fit_rows, refit, {}

    def predict(self, order: tuple, rows) -> pd.DataFrame:
        if order not in self.cache:
            kept = mask_of(self.panel, list(order))
            self.cache[order] = (kept, fit(self.panel, kept, self.fit_rows, self.refit))
        kept, w = self.cache[order]
        return predict(self.panel, kept, rows, w)


def dynamic_replay(panel: Panel, order: list, tau: float, fit_rows, eval_rows, refit: str = "ridge",
                   prefixes: Prefixes | None = None) -> pd.DataFrame:
    """Per eval item: the policy's answer (correct, brier), dollars, tokens, rounds (calls made) and seconds (their
    sum), calling `order` one unit at a time until the prefix aggregator's confidence reaches tau."""
    prefixes = prefixes or Prefixes(panel, fit_rows, refit)
    eval_rows = np.asarray(eval_rows)
    n = len(eval_rows)
    done = np.zeros(n, dtype=bool)
    out = pd.DataFrame({"item": [panel.items[r] for r in eval_rows], "correct": 0.0, "brier": np.nan,
                        "dollars": 0.0, "tokens": 0.0 if panel.tokens is not None else np.nan, "rounds": 0, "seconds": 0.0})
    for k in range(1, len(order) + 1):
        pred = prefixes.predict(tuple(order[:k]), eval_rows)
        active = ~done
        u = order[k - 1]
        out.loc[active, "dollars"] += panel.cost[eval_rows[active], u]
        out.loc[active, "seconds"] += panel.seconds[eval_rows[active], u]
        if panel.tokens is not None:
            out.loc[active, "tokens"] += panel.tokens[eval_rows[active], u]
        out.loc[active, "rounds"] += 1
        out.loc[active, "correct"] = pred.loc[active, "correct"].to_numpy()
        if panel.kind == "prob":
            out.loc[active, "brier"] = pred.loc[active, "brier"].to_numpy()
        done |= active & (pred["confidence"].to_numpy() >= tau)
        if done.all():
            break
    return out


def gain_order(panel: Panel, pool, fit_rows, tau: float, refit: str = "ridge", prefixes: Prefixes | None = None) -> list:
    """The call order chosen greedily on the fit rows: next = the unit with the largest gain in score per
    dollar on the fit items still unsure after the current prefix; stops when no unit gains."""
    prefixes = prefixes or Prefixes(panel, fit_rows, refit)
    fit_rows = np.asarray(fit_rows)
    order: list = []
    active = np.ones(len(fit_rows), dtype=bool)
    now = np.zeros(len(fit_rows)) if panel.kind == "choice" else -np.full(len(fit_rows), 0.25)
    left = list(pool)
    while left and active.any():
        best, best_value, best_pred = None, 0.0, None
        for u in left:
            pred = prefixes.predict(tuple(order + [u]), fit_rows)
            s = -pred["brier"].to_numpy() if panel.kind == "prob" else pred["correct"].to_numpy()
            gain = (s[active] - now[active]).mean()
            value = gain / max(panel.cost[fit_rows[active], u].mean(), 1e-12)
            if best is None or value > best_value:
                best, best_value, best_pred, best_s = u, value, pred, s
        if best_value <= 0 and order:
            break
        order.append(best)
        left.remove(best)
        now = best_s
        active &= best_pred["confidence"].to_numpy() < tau
    return order


def dynamic_frontier(panel: Panel, pool, search_rows, eval_rows, taus, refit: str = "ridge",
                     order: list | None = None) -> pd.DataFrame:
    """One row per tau: the held-out score, accuracy, dollars, rounds and seconds of the dynamic policy whose
    order (gain_order per tau unless `order` is fixed) and aggregators come from the search rows."""
    prefixes = Prefixes(panel, search_rows, refit)
    rows = []
    for tau in taus:
        o = order if order is not None else gain_order(panel, pool, search_rows, tau, refit, prefixes)
        frame = dynamic_replay(panel, o, tau, search_rows, eval_rows, refit, prefixes)
        rows.append({"tau": tau, "order": "+".join(panel.units.loc[o, "unit"]),
                     "score": float(-frame["brier"].mean()) if panel.kind == "prob" else float(frame["correct"].mean()),
                     "accuracy": float(frame["correct"].mean()), "dollars": float(frame["dollars"].mean()),
                     "tokens": float(frame["tokens"].mean()), "rounds": float(frame["rounds"].mean()),
                     "seconds": float(frame["seconds"].mean())})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------------------------------------
# baselines

def random_subsets(panel: Panel, pool, target: float, rows=None, n: int = 200, tol: float = 0.15, seed: int = 0,
                   tries: int = 200_000) -> list[np.ndarray]:
    """Up to n random non-empty subsets of `pool` whose dollars per item lie within +-tol (relative) of
    `target`; each unit is kept with a probability drawn uniformly per subset."""
    rng = np.random.default_rng(seed)
    pool = np.asarray(pool)
    cost = panel.mean_cost(rows)[pool]
    out = []
    for _ in range(tries):
        q = rng.random()
        pick = rng.random(len(pool)) < q
        if pick.any() and abs(cost[pick].sum() - target) <= tol * target:
            out.append(mask_of(panel, pool[pick]))
            if len(out) == n:
                break
    return out


def cheapest_first(panel: Panel, pool, budget: float, rows=None) -> np.ndarray:
    """Add units by increasing dollars per item (ties: unit order) while the total fits the budget."""
    cost = panel.mean_cost(rows)
    frame = pd.DataFrame({"unit": list(pool), "dollars": cost[list(pool)]}).sort_values("dollars", kind="stable")
    total, keep = 0.0, []
    for u, d in zip(frame["unit"], frame["dollars"]):
        if total + d <= budget + 1e-12:
            keep.append(u)
            total += d
    return mask_of(panel, keep)


def top_k_accurate(panel: Panel, pool, budget: float, rows=None) -> np.ndarray:
    """Add units by decreasing own accuracy on `rows` (ties: cheaper first) while the total fits the budget."""
    rows = np.arange(panel.n) if rows is None else rows
    cost = panel.mean_cost(rows)
    acc = panel.correct_matrix()[rows].mean(axis=0)
    frame = pd.DataFrame({"unit": list(pool), "accuracy": acc[list(pool)], "dollars": cost[list(pool)]})
    frame = frame.sort_values(["accuracy", "dollars"], ascending=[False, True], kind="stable")
    total, keep = 0.0, []
    for u, d in zip(frame["unit"], frame["dollars"]):
        if total + d <= budget + 1e-12:
            keep.append(u)
            total += d
    return mask_of(panel, keep)


def h7_cascade(panel: Panel, cheap, expensive: int, k_agree: int, rows=None) -> pd.DataFrame:
    """An H7-style cascade. Per item: vote over the cheap units; when fewer than k_agree agree with the
    plurality, use the expensive unit's answer instead (paying for it). Columns escalated, correct, dollars.
    The plan's H7 is 3 Haiku + 3 Luna calls with k_agree 4; cached finding 8 is 5 Haiku calls with k_agree 3."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    cheap_mask = mask_of(panel, cheap)
    vote = predict(panel, cheap_mask, rows)
    agree = np.rint(vote["confidence"].to_numpy() * cheap_mask.sum())
    expensive_right = panel.correct_matrix()[rows, expensive]
    out = cascade(agree, vote["correct"].to_numpy(), expensive_right, panel.cost[rows][:, cheap_mask].sum(axis=1),
                  panel.cost[rows, expensive], k_agree)
    return out.rename(columns={"cost_usd": "dollars"})


# ---------------------------------------------------------------------------------------------------------
# staged networks on whole grid points

def grid_lower(levels_of_stage: list[int], level: int) -> list[int]:
    return sorted([v for v in levels_of_stage if v < level], reverse=True)


def grid_sensitivity(grid: Grid, items) -> pd.DataFrame:
    """Each stage moved alone from the full design to each lower level: accuracy and dollar changes."""
    pts = grid.points(items).set_index("design")
    top = [int(pts[s].max()) for s in grid.stages]
    full = pts.loc[grid.design_of(top)]
    rows = []
    for k, s in enumerate(grid.stages):
        for level in grid_lower(sorted(pts[s].unique()), top[k]):
            levels = list(top)
            levels[k] = level
            d = pts.loc[grid.design_of(levels)]
            rows.append({"stage": s, "level": level, "design": grid.design_of(levels), "accuracy": d["accuracy"],
                         "dollars": d["dollars"], "d_accuracy": d["accuracy"] - full["accuracy"],
                         "d_dollars": d["dollars"] - full["dollars"]})
    return pd.DataFrame(rows)


def grid_netadapt(grid: Grid, items, step: float = 0.0005, resource: str = "dollars") -> pd.DataFrame:
    """NetAdapt over stage levels: from the full design, each step proposes, for every stage, the smallest
    move to a lower level that cuts the resource by `step`, and keeps the best-accuracy proposal."""
    pts = grid.points(items).set_index("design")
    levels_by_stage = [sorted(pts[s].unique()) for s in grid.stages]
    now = [max(v) for v in levels_by_stage]
    design = grid.design_of(now)
    rows = [{"step": 0, "design": design, "moved": None, **pts.loc[design, ["accuracy", "dollars", "seconds"]].to_dict()}]
    k = 0
    while True:
        k += 1
        target = pts.loc[design, resource] - step
        proposals = []
        for i, s in enumerate(grid.stages):
            for level in grid_lower(levels_by_stage[i], now[i]):
                trial = list(now)
                trial[i] = level
                d = grid.design_of(trial)
                if pts.loc[d, resource] <= target or level == min(levels_by_stage[i]):
                    proposals.append({"stage": s, "levels": trial, "design": d, "meets": pts.loc[d, resource] <= target,
                                      "accuracy": pts.loc[d, "accuracy"], "resource": pts.loc[d, resource]})
                    break
        if not proposals:
            break
        table = pd.DataFrame(proposals)
        if table["meets"].any():
            table = table[table["meets"]]
        best = table.sort_values(["accuracy", "resource"], ascending=[False, True], kind="stable").iloc[0]
        now, design = list(best["levels"]), best["design"]
        rows.append({"step": k, "design": design, "moved": best["stage"],
                     **pts.loc[design, ["accuracy", "dollars", "seconds"]].to_dict()})
    return pd.DataFrame(rows)
