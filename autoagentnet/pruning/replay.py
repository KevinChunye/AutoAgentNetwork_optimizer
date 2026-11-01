"""Exact replay of agent networks from calls already made ($0, no API): Phase 3 of the evidence plan.

A flat panel's calls are independent of each other, so any sub-network of a panel that was run in full
can be scored exactly from the cached calls: drop the pruned calls, aggregate the rest. A staged network
(propose -> critique -> refine -> aggregate) cannot: its later stages read the earlier stages' text, so a
pruned design is only known where it was run (the pilot's 27 grid points, class `Grid`).

Terms (plain words first):
  call row    one model call on one item (columns item, source, call, answer, parsed, correct, cost_usd,
              seconds; forecasts carry prob and outcome instead of answer and correct).
  unit        one call slot of a panel, e.g. "haiku:0" = the first Haiku call on every item. A network is a
              set of kept units; pruning removes units.
  group       a set of units removed together, the pruning granularity: one call ("unit"), one source
              ("source": all its calls), one vendor-tier pattern ("pattern", e.g. all cheap Anthropic
              calls), or one stage of a staged network (on the grid).
  class       on a choice task, one distinct answer of an item: answers the task's grader calls equal share
              a class (an answer joins the first class whose first member it matches). A class is correct
              when its first member is. Unparsed answers belong to no class.
  candidate   a class that at least one kept unit answered, plus a "none of these" slot for "the gold
              answer is not among the kept answers".
  aggregator  turns the kept units' answers on an item into one answer and a confidence. Kevin's aggregator
              (the Phase 3 brief, research/v3/pruning/kevin_brief.md) is the default; refitting it after
              pruning plays the role of fine-tuning:
                ridge    the plurality answer, and P(it is right) from a logistic model on agreement features:
                         for each feature group (by default each source) the share of the group's kept calls
                         that agree with the plurality answer (0 when none is kept), plus an intercept, with a
                         ridge penalty. The model is fitted on every tied top class of each item (weight 1 / the
                         number tied), and a plurality tie goes to the tied class it rates most likely right, so
                         neither the fit nor the answer depends on the order calls are listed in (only a tie
                         between classes with equal features, e.g. two calls of one source splitting, falls back
                         to the class met first). Forecasts: P(yes) = sigmoid(a x mean log-odds of the kept
                         calls), a the fitted extremizing factor.
                plain    the same, refitted without the ridge penalty (in practice L2 = 1e-4).
                restrict the dense aggregator (fitted once on every unit of the panel) applied to the kept calls,
                         without refitting.
              Two more aggregators, for comparison:
                none     the plain vote: plurality class, ties to the class met first in unit order; confidence
                         = plurality size / number of kept units. Forecasts: the mean of the kept probabilities.
                weights  a weighted vote, one weight per kept unit: candidate a's score is the sum of w_g over
                         kept units g that answered a, a "none of these" slot scores a learned intercept b, the
                         answer is the top-scoring class and its confidence is softmax(scores) over the
                         candidates. Forecasts: score = b + sum_g w_g logit(p_g) for "yes" and 0 for "no", a
                         logistic regression on the kept units' log-odds.
              Fitting minimizes the training items' negative log-likelihood plus 0.5 * L2 * |coefficients|^2 (a
              standard normal prior on each coefficient in log-odds units, which keeps a coefficient finite when
              one feature separates the training items); intercepts are not penalized.
  dollars     per item, the sum of the kept calls' costs (list price, cache-aware, as billed).
  seconds     per item, the slowest kept call (a static panel calls in parallel); a dynamic policy calls one
              unit at a time, so its seconds are the sum.
  rounds      sequential call rounds: 1 for a static panel, the number of calls made for a dynamic policy.
  score       the metric searches maximize: accuracy on choice tasks, minus the Brier score on forecasts.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

L2 = 1.0
TIERS = {"haiku": ("anthropic", "cheap"), "sonnet": ("anthropic", "mid"), "opus": ("anthropic", "top"),
         "luna": ("openai", "cheap"), "sol": ("openai", "mid"), "astra": ("openai", "top")}


def vendor_tier(source: str) -> tuple[str, str]:
    """(vendor, tier) of a source label such as "haiku_nothink:base" or "sol61_low"; unknown -> ("other", source)."""
    name = source.lower()
    for family, vt in TIERS.items():
        if name.startswith(family):
            return vt
    return "other", source


def unit_table(sources: list[str], calls: list[int]) -> pd.DataFrame:
    rows = []
    for s, c in zip(sources, calls):
        vendor, tier = vendor_tier(s)
        rows.append({"unit": f"{s}:{c}", "source": s, "call": int(c), "vendor": vendor, "tier": tier,
                     "pattern": f"{vendor}-{tier}"})
    return pd.DataFrame(rows)


@dataclass
class Panel:
    """A flat panel's calls as arrays (items x units), ready to replay any subset of units.

    kind           "choice" (answers grouped into classes) or "prob" (probability forecasts of a 0/1 outcome).
    votes          choice: the class index of each call's answer (-1 = unparsed); prob: the probability.
    class_correct  choice: items x classes, 1 when the class is correct (padded with 0).
    labels         choice: per item, the answer text of each class (for reports).
    outcome        prob: the resolved 0/1 outcome of each item.
    cost, seconds  items x units, as billed and as timed.
    tokens         items x units, the call's total tokens (input, cached and output), when known.
    """

    kind: str
    items: list[str]
    units: pd.DataFrame
    votes: np.ndarray
    cost: np.ndarray
    seconds: np.ndarray
    class_correct: np.ndarray = field(default_factory=lambda: np.zeros((0, 0)))
    labels: list = field(default_factory=list)
    outcome: np.ndarray = field(default_factory=lambda: np.zeros(0))
    dropped: list = field(default_factory=list)
    tokens: np.ndarray | None = None  # items x units, total tokens billed per call (when the call rows carry them)

    @property
    def n(self) -> int:
        return len(self.items)

    @property
    def m(self) -> int:
        return len(self.units)

    def all_units(self) -> np.ndarray:
        return np.ones(self.m, dtype=bool)

    def mask(self, names) -> np.ndarray:
        """Boolean kept-mask from unit names."""
        names = set(names)
        return self.units["unit"].isin(names).to_numpy()

    def correct_matrix(self) -> np.ndarray:
        """items x units: 1 when the call is right (choice) or minus its squared error (prob)."""
        if self.kind == "prob":
            return -(self.votes - self.outcome[:, None]) ** 2
        rows = np.arange(self.n)[:, None]
        return np.where(self.votes >= 0, self.class_correct[rows, np.maximum(self.votes, 0)], 0.0)

    def mean_cost(self, rows=None) -> np.ndarray:
        rows = np.arange(self.n) if rows is None else rows
        return self.cost[rows].mean(axis=0)

    @classmethod
    def from_arrays(cls, answers, correct, cost, seconds=None, sources=None, calls=None, items=None) -> "Panel":
        """A choice panel from items x units arrays of integer answers (-1 = unparsed; equal integers are
        one class) and 0/1 correctness."""
        A = np.asarray(answers, dtype=int)
        Z = np.asarray(correct, dtype=float)
        n, m = A.shape
        sources = sources or [f"s{g}" for g in range(m)]
        calls = calls if calls is not None else [0] * m
        votes = np.full((n, m), -1)
        labels, flags = [], []
        for i in range(n):
            seen: list[int] = []
            right: list[float] = []
            for g in range(m):
                if A[i, g] < 0:
                    continue
                if A[i, g] not in seen:
                    seen.append(int(A[i, g]))
                    right.append(Z[i, g])
                votes[i, g] = seen.index(A[i, g])
            labels.append([str(a) for a in seen])
            flags.append(right)
        return cls._finish("choice", items or [f"i{i}" for i in range(n)], unit_table(sources, calls), votes, flags,
                           labels, np.asarray(cost, dtype=float), seconds)

    @classmethod
    def from_probs(cls, probs, outcome, cost, seconds=None, sources=None, calls=None, items=None) -> "Panel":
        P = np.clip(np.asarray(probs, dtype=float), 0.01, 0.99)
        n, m = P.shape
        sources = sources or [f"s{g}" for g in range(m)]
        calls = calls if calls is not None else [0] * m
        seconds = np.zeros((n, m)) if seconds is None else np.asarray(seconds, dtype=float)
        return cls("prob", items or [f"i{i}" for i in range(n)], unit_table(sources, calls), P,
                   np.asarray(cost, dtype=float), seconds, outcome=np.asarray(outcome, dtype=float))

    @classmethod
    def from_calls(cls, calls: pd.DataFrame, kind: str = "choice", grader: str = "bbeh") -> "Panel":
        """From a long table of call rows (one per item, source and call). Items missing any unit are dropped
        (listed in `dropped`): a replay needs every kept call of every item."""
        from ..tasks import answers_match

        calls = calls.assign(unit=calls["source"].astype(str) + ":" + calls["call"].astype(int).astype(str))
        order = calls.drop_duplicates("unit")[["unit", "source", "call"]]
        units = order["unit"].tolist()
        value = "prob" if kind == "prob" else "answer"
        if kind == "choice":
            calls = calls.assign(answer=calls["answer"].where(calls["parsed"].astype(bool)))
        every = calls["item"].drop_duplicates().tolist()
        cols = ["correct", "cost_usd", "seconds", value] if kind == "choice" else ["cost_usd", "seconds", value]
        if "tokens" in calls:
            cols.append("tokens")
        wide = {col: calls.pivot_table(index="item", columns="unit", values=col, aggfunc="first")
                .reindex(index=every, columns=units) for col in cols}
        complete = wide["cost_usd"].notna().all(axis=1)
        items = [i for i in every if complete[i]]
        dropped = [i for i in every if not complete[i]]
        cost = wide["cost_usd"].loc[items].to_numpy(dtype=float)
        seconds = wide["seconds"].loc[items].fillna(0).to_numpy(dtype=float)
        tokens = wide["tokens"].loc[items].fillna(0).to_numpy(dtype=float) if "tokens" in wide else None
        table = unit_table(order["source"].tolist(), order["call"].tolist())
        if kind == "prob":
            outcome = calls.drop_duplicates("item").set_index("item").loc[items, "outcome"].to_numpy(dtype=float)
            P = np.clip(wide["prob"].loc[items].to_numpy(dtype=float), 0.01, 0.99)
            if np.isnan(P).any():
                raise ValueError("a forecast panel needs a parsed probability for every call (fill unparsed ones first)")
            return cls("prob", items, table, P, cost, seconds, outcome=outcome, dropped=dropped, tokens=tokens)
        answers = wide["answer"].loc[items]
        right = wide["correct"].loc[items].to_numpy(dtype=float)
        votes = np.full((len(items), len(units)), -1)
        labels, flags = [], []
        for i, item in enumerate(items):
            reps: list[str] = []
            first_right: list[float] = []
            for g, a in enumerate(answers.loc[item].tolist()):
                if not isinstance(a, str):
                    continue
                home = next((k for k, r in enumerate(reps) if answers_match(r, a, grader)), None)
                if home is None:
                    reps.append(a)
                    first_right.append(right[i, g])
                    home = len(reps) - 1
                votes[i, g] = home
            labels.append(reps)
            flags.append(first_right)
        panel = cls._finish("choice", items, table, votes, flags, labels, cost, seconds)
        panel.dropped = dropped
        panel.tokens = tokens
        return panel

    @classmethod
    def _finish(cls, kind, items, units, votes, flags, labels, cost, seconds) -> "Panel":
        n, m = votes.shape
        width = max([len(f) for f in flags] + [1])
        class_correct = np.zeros((n, width))
        for i, f in enumerate(flags):
            class_correct[i, :len(f)] = f
        seconds = np.zeros((n, m)) if seconds is None else np.asarray(seconds, dtype=float)
        return cls(kind, list(items), units, votes, cost, seconds, class_correct=class_correct, labels=labels)

    def subset(self, rows) -> "Panel":
        """The same panel on a subset of items (rows: integer positions)."""
        rows = np.asarray(rows)
        return Panel(self.kind, [self.items[r] for r in rows], self.units, self.votes[rows], self.cost[rows],
                     self.seconds[rows], self.class_correct[rows] if self.kind == "choice" else self.class_correct,
                     [self.labels[r] for r in rows] if self.labels else [],
                     self.outcome[rows] if self.kind == "prob" else self.outcome,
                     tokens=None if self.tokens is None else self.tokens[rows])


def groups(panel: Panel, by: str = "unit") -> dict[str, np.ndarray]:
    """Group name -> unit positions, for a granularity: "unit" (one call), "source", "pattern" (vendor-tier)
    or any other column of panel.units."""
    out = {}
    for name, part in panel.units.groupby(by, sort=False):
        out[str(name)] = part.index.to_numpy()
    return out


# ---------------------------------------------------------------------------------------------------------
# the aggregator as a conditional logit over candidates

def design(panel: Panel, kept: np.ndarray, rows=None):
    """(X, valid, gold) for items `rows`: X[i, a, f] is feature f of candidate slot a (units first, the
    intercept last), valid marks real candidates, gold is the slot of the right answer."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    n, m = len(rows), panel.m
    kept = np.asarray(kept, dtype=bool)
    if panel.kind == "prob":
        X = np.zeros((n, 2, m + 1))
        logit = np.log(panel.votes[rows] / (1 - panel.votes[rows]))
        X[:, 0, :m] = logit * kept
        X[:, 0, m] = 1.0
        valid = np.ones((n, 2), dtype=bool)
        gold = np.where(panel.outcome[rows] > 0.5, 0, 1)
    else:
        K = panel.class_correct.shape[1]
        V = panel.votes[rows]
        X = np.zeros((n, K + 1, m + 1))
        for a in range(K):
            X[:, a, :m] = (V == a) & kept
        X[:, K, m] = 1.0
        valid = np.concatenate([X[:, :K, :m].any(axis=2), np.ones((n, 1), dtype=bool)], axis=1)
        cc = panel.class_correct[rows]
        has = cc.max(axis=1) > 0
        gold_class = cc.argmax(axis=1)
        gold = np.where(has & valid[np.arange(n), gold_class], gold_class, K)
    return X, valid, gold


def softmax_scores(w, X, valid) -> np.ndarray:
    s = np.where(valid, X @ w, -np.inf)
    s = s - s.max(axis=1, keepdims=True)
    e = np.where(valid, np.exp(s), 0.0)
    return e / e.sum(axis=1, keepdims=True)


def objective(w, X, valid, gold, l2: float = L2, penalized=None, hessian: bool = True):
    """(value, gradient, Hessian) of the negative log-likelihood plus 0.5 * l2 * |w_penalized|^2 (Hessian None
    unless asked for)."""
    n = len(gold)
    pen = np.ones(len(w), dtype=bool) if penalized is None else penalized
    P = softmax_scores(w, X, valid)
    idx = np.arange(n)
    value = -np.log(np.maximum(P[idx, gold], 1e-300)).sum() + 0.5 * l2 * (w[pen] ** 2).sum()
    mean_x = np.einsum("na,naf->nf", P, X)
    grad = -(X[idx, gold] - mean_x).sum(axis=0) + l2 * w * pen
    if not hessian:
        return value, grad, None
    second = np.einsum("na,naf,nag->fg", P, X, X) - np.einsum("nf,ng->fg", mean_x, mean_x)
    hess = second + l2 * np.diag(pen.astype(float))
    return value, grad, hess


def newton(X, valid, gold, l2: float = L2, penalized=None, w0=None, iters: int = 50) -> np.ndarray:
    w = np.zeros(X.shape[2]) if w0 is None else np.asarray(w0, dtype=float).copy()
    value, grad, hess = objective(w, X, valid, gold, l2, penalized)
    for _ in range(iters):
        step = np.linalg.lstsq(hess + 1e-9 * np.eye(len(w)), grad, rcond=None)[0]
        t = 1.0
        while t > 1e-6:
            new = w - t * step
            v_new, g_new, h_new = objective(new, X, valid, gold, l2, penalized)
            if v_new <= value + 1e-12:
                break
            t /= 2
        if t <= 1e-6:
            break
        done = value - v_new < 1e-10
        w, value, grad, hess = new, v_new, g_new, h_new
        if done:
            break
    return w


# ---------------------------------------------------------------------------------------------------------
# Kevin's aggregator: the plurality answer and a logistic model of P(it is right) on agreement features

REFITS = ("ridge", "plain", "restrict", "none", "weights")
PLAIN_L2 = 1e-4


@dataclass
class PluralityModel:
    """Kevin's aggregator (module docstring). groups: the unit positions of each feature group; beta: one
    coefficient per group, then the intercept (choice) or [a], the extremizing factor (forecasts)."""

    kind: str
    groups: list
    beta: np.ndarray


def source_groups(panel: Panel) -> list[np.ndarray]:
    return [part.index.to_numpy() for _, part in panel.units.groupby("source", sort=False)]


def class_shares(panel: Panel, kept, rows, feature_groups: list) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """(shares, counts, first, valid) over the class slots of items `rows`: shares[i, a, j] is the share of
    feature group j's kept calls that answered class a, counts[i, a] the number of kept calls that did, first[i, a]
    the unit position where class a is first met, valid[i, a] whether any kept call answered it."""
    kept = np.asarray(kept, dtype=bool)
    X, valid, _ = design(panel, kept, rows)
    K = panel.class_correct.shape[1]
    member = X[:, :K, :panel.m]
    M = np.zeros((panel.m, len(feature_groups)))
    for j, units in enumerate(feature_groups):
        live = units[kept[units]]
        if len(live):
            M[live, j] = 1.0 / len(live)
    first = np.where(member > 0, np.arange(panel.m), panel.m).min(axis=2)
    return member @ M, member.sum(axis=2), first, valid[:, :K]


def plurality_slots(counts, first, valid, score=None) -> np.ndarray:
    """The plurality class per item; ties go to the higher score (when given), then to the class met first."""
    big = int(first.max()) + 1
    key = np.where(valid, counts, -1.0)
    tied = key == key.max(axis=1, keepdims=True)
    if score is not None:
        s = np.round(np.where(tied, score, -np.inf), 10)
        tied = tied & (s == s.max(axis=1, keepdims=True))
    return np.where(tied, first, big).argmin(axis=1)


def logistic_newton(F: np.ndarray, y: np.ndarray, l2: float, weights=None, iters: int = 50) -> np.ndarray:
    """Coefficients (features, then an unpenalized intercept) of a ridge logistic regression of y on F, each row
    weighted (default 1)."""
    A = np.column_stack([F, np.ones(len(y))])
    wt = np.ones(len(y)) if weights is None else np.asarray(weights, dtype=float)
    pen = np.r_[np.ones(F.shape[1]), 0.0]
    beta = np.zeros(A.shape[1])

    def value(b):
        z = A @ b
        return float(np.sum(wt * (np.logaddexp(0, z) - y * z)) + 0.5 * l2 * np.sum(pen * b * b))

    v = value(beta)
    for _ in range(iters):
        p = 1 / (1 + np.exp(-(A @ beta)))
        grad = A.T @ (wt * (p - y)) + l2 * pen * beta
        hess = (A * (wt * p * (1 - p))[:, None]).T @ A + np.diag(l2 * pen) + 1e-9 * np.eye(len(beta))
        step = np.linalg.solve(hess, grad)
        t = 1.0
        while t > 1e-6 and value(beta - t * step) > v + 1e-12:
            t /= 2
        if t <= 1e-6:
            break
        new = beta - t * step
        v_new = value(new)
        done = v - v_new < 1e-10
        beta, v = new, v_new
        if done:
            break
    return beta


def plurality_data(panel: Panel, kept, rows, feature_groups) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(features, correct, weights) for fitting the aggregator: one row per tied top class of each item (the
    candidates a plurality could answer), weighted 1 / the number tied, so the fit does not depend on the order the
    calls are listed in (audit 50); an item with no parsed answer gives one row of zeros, never right."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    shares, counts, first, valid = class_shares(panel, kept, rows, feature_groups)
    key = np.where(valid, counts, -1.0)
    tied = valid & (key == key.max(axis=1, keepdims=True))
    n_tied = tied.sum(axis=1)
    item, slot = np.nonzero(tied)
    F = shares[item, slot]
    y = panel.class_correct[rows][item, slot]
    wt = 1.0 / n_tied[item]
    empty = np.flatnonzero(n_tied == 0)
    G = shares.shape[2]
    F = np.vstack([F, np.zeros((len(empty), G))])
    return F, np.r_[y, np.zeros(len(empty))], np.r_[wt, np.ones(len(empty))]


def mean_logit(panel: Panel, kept, rows) -> np.ndarray:
    kept = np.asarray(kept, dtype=bool)
    P = panel.votes[rows][:, kept]
    return np.log(P / (1 - P)).mean(axis=1) if kept.any() else np.zeros(len(rows))


def extremizing_factor(m: np.ndarray, y: np.ndarray, iters: int = 50) -> float:
    """The a minimizing the log loss of sigmoid(a x m) against y (one-dimensional Newton, no penalty)."""
    a = 1.0
    for _ in range(iters):
        p = 1 / (1 + np.exp(-a * m))
        g = float(np.sum((p - y) * m))
        h = float(np.sum(p * (1 - p) * m * m)) + 1e-9
        a_new = float(np.clip(a - g / h, 0.0, 20.0))
        if abs(a_new - a) < 1e-10:
            return a_new
        a = a_new
    return a


def fit_plurality(panel: Panel, kept, rows=None, l2: float = L2, feature_groups=None) -> PluralityModel:
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    if panel.kind == "prob":
        return PluralityModel("prob", [], np.array([extremizing_factor(mean_logit(panel, kept, rows), panel.outcome[rows])]))
    feature_groups = source_groups(panel) if feature_groups is None else list(feature_groups)
    F, y, wt = plurality_data(panel, kept, rows, feature_groups)
    return PluralityModel("choice", feature_groups, logistic_newton(F, y, l2, wt))


def fit(panel: Panel, kept, rows=None, refit: str = "ridge", l2: float = L2, feature_groups=None):
    """The aggregator for the kept units, fitted on `rows`: a PluralityModel ("ridge", "plain", "restrict"),
    weights over (units..., intercept) for the weighted vote ("weights"; pruned units get weight 0), or None
    for the plain vote ("none")."""
    if refit == "none":
        return None
    kept = np.asarray(kept, dtype=bool)
    if refit == "ridge":
        return fit_plurality(panel, kept, rows, l2, feature_groups)
    if refit == "plain":
        return fit_plurality(panel, kept, rows, PLAIN_L2, feature_groups)
    if refit == "restrict":
        return fit_plurality(panel, panel.all_units(), rows, l2, feature_groups)
    if refit != "weights":
        raise ValueError(f"unknown refit {refit!r}; known: {', '.join(REFITS)}")
    m = panel.m
    X, valid, gold = design(panel, kept, rows)
    pen = np.ones(X.shape[2], dtype=bool)
    pen[-1] = False
    w = newton(X, valid, gold, l2, pen)
    full = np.zeros(m + 1)
    full[m] = w[-1]
    full[:m] = w[:m] * kept
    return full


def predict(panel: Panel, kept, rows=None, w=None) -> pd.DataFrame:
    """Per item: answer slot, label, confidence, correct (and prob, brier for forecasts) of the kept units'
    aggregate; `w` from fit(), None = the vote."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    kept = np.asarray(kept, dtype=bool)
    n_kept = int(kept.sum())
    if panel.kind == "prob":
        if w is None:
            p = panel.votes[rows][:, kept].mean(axis=1) if n_kept else np.full(len(rows), 0.5)
        elif isinstance(w, PluralityModel):
            p = 1 / (1 + np.exp(-w.beta[0] * mean_logit(panel, kept, rows)))
        else:
            X, valid, _ = design(panel, kept, rows)
            p = softmax_scores(w, X, valid)[:, 0]
        y = panel.outcome[rows]
        return pd.DataFrame({"item": [panel.items[r] for r in rows], "prob": p, "outcome": y,
                             "confidence": np.maximum(p, 1 - p), "correct": ((p > 0.5) == (y > 0.5)).astype(float),
                             "brier": (p - y) ** 2})
    if isinstance(w, PluralityModel):
        shares, counts, first, valid = class_shares(panel, kept, rows, w.groups)
        score = shares @ w.beta[:-1] + w.beta[-1]
        slot = plurality_slots(counts, first, valid, score)
        idx = np.arange(len(rows))
        has_class = valid.any(axis=1)
        conf = np.where(has_class, 1 / (1 + np.exp(-score[idx, slot])), 0.0)
        correct = np.where(has_class, panel.class_correct[rows][idx, slot], 0.0)
        label = [panel.labels[r][s] if h and panel.labels else None for r, s, h in zip(rows, slot, has_class)]
        return pd.DataFrame({"item": [panel.items[r] for r in rows], "slot": np.where(has_class, slot, -1),
                             "answer": label, "confidence": conf, "correct": correct})
    X, valid, _ = design(panel, kept, rows)
    K = panel.class_correct.shape[1]
    has_class = valid[:, :K].any(axis=1)
    pos = np.arange(panel.m)
    first = np.where(X[:, :K, :panel.m] > 0, pos, panel.m).min(axis=2)  # where each class is first met
    if w is None:
        counts = X[:, :K, :panel.m].sum(axis=2)
        key = np.where(valid[:, :K], counts * (panel.m + 1) - first, -np.inf)
        slot = key.argmax(axis=1)
        conf = np.where(has_class, counts[np.arange(len(rows)), slot] / max(n_kept, 1), 0.0)
    else:
        P = softmax_scores(w, X, valid)
        top = np.round(np.where(valid[:, :K], P[:, :K], -1.0), 10)  # ties (to rounding) go to the class met first
        tied = top == top.max(axis=1, keepdims=True)
        slot = np.where(tied, first, panel.m + 1).argmin(axis=1)
        conf = np.where(has_class, P[np.arange(len(rows)), slot], 0.0)
    cc = panel.class_correct[rows]
    correct = np.where(has_class, cc[np.arange(len(rows)), slot], 0.0)
    label = [panel.labels[r][s] if h and panel.labels else None for r, s, h in zip(rows, slot, has_class)]
    return pd.DataFrame({"item": [panel.items[r] for r in rows], "slot": np.where(has_class, slot, -1),
                         "answer": label, "confidence": conf, "correct": correct})


def replay(panel: Panel, kept, rows=None, w=None) -> pd.DataFrame:
    """predict() plus the kept calls' dollars, tokens (when known), seconds (slowest call) and rounds (1) per item."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    kept = np.asarray(kept, dtype=bool)
    out = predict(panel, kept, rows, w)
    out["dollars"] = panel.cost[rows][:, kept].sum(axis=1)
    out["tokens"] = panel.tokens[rows][:, kept].sum(axis=1) if panel.tokens is not None else np.nan
    out["seconds"] = panel.seconds[rows][:, kept].max(axis=1) if kept.any() else 0.0
    out["rounds"] = int(kept.any())
    return out


def score_of(frame: pd.DataFrame, kind: str) -> float:
    """The searched metric of a replay frame: accuracy (choice) or minus the Brier score (prob)."""
    return float(-frame["brier"].mean()) if kind == "prob" else float(frame["correct"].mean())


def cross_fit(panel: Panel, kept, folds: np.ndarray, refit: str = "ridge", l2: float = L2) -> pd.DataFrame:
    """Out-of-fold replay: for each fold k, fit the aggregator on the other folds and replay fold k's items.
    One row per item, in item order; with refit "none" no fitting happens and folds do not matter."""
    parts = []
    for k in np.unique(folds):
        test = np.flatnonzero(folds == k)
        train = np.flatnonzero(folds != k)
        w = fit(panel, kept, train, refit, l2)
        parts.append(replay(panel, kept, test, w).assign(fold=k, row=test))
    return pd.concat(parts).sort_values("row", kind="stable").reset_index(drop=True)


def evaluate(panel: Panel, kept, folds=None, refit: str = "ridge", rows=None) -> dict:
    """Mean score, accuracy, dollars, seconds and rounds of one network: out-of-fold when `folds` is given,
    else fitted and scored on the same `rows` (in-sample)."""
    kept = np.asarray(kept, dtype=bool)
    if folds is not None:
        frame = cross_fit(panel, kept, folds, refit)
    else:
        frame = replay(panel, kept, rows, fit(panel, kept, rows, refit))
    out = {"score": score_of(frame, panel.kind), "accuracy": float(frame["correct"].mean()),
           "dollars": float(frame["dollars"].mean()), "tokens": float(frame["tokens"].mean()),
           "seconds": float(frame["seconds"].mean()), "rounds": float(frame["rounds"].mean()), "n_units": int(kept.sum())}
    if panel.kind == "prob":
        out["brier"] = float(frame["brier"].mean())
    return out


# ---------------------------------------------------------------------------------------------------------
# staged networks: whole grid points only

@dataclass
class Grid:
    """A staged network run at whole grid points (the pilot's 27 designs): no replay below a point, since a
    pruned stage changes what later stages read.

    table   one row per (design, item): design (config id such as "k6-3-1-1"), item, correct, dollars,
            seconds (the critical path: the slowest chain of calls), and one keep-level column per stage.
    stages  the stage names in order (the last, one-agent aggregate stage is left out: it is never pruned).
    """

    table: pd.DataFrame
    stages: list[str]

    @classmethod
    def from_results(cls, frame: pd.DataFrame, stages=("propose", "critique", "refine")) -> "Grid":
        levels = frame["config_id"].str[1:].str.split("-", expand=True).astype(int)
        table = pd.DataFrame({"design": frame["config_id"].to_numpy(), "item": frame["task_id"].to_numpy(),
                              "correct": frame["correct"].astype(float).to_numpy(),
                              "dollars": frame["cost_usd"].astype(float).to_numpy(),
                              "seconds": frame["critical_path_s"].astype(float).to_numpy()})
        for k, s in enumerate(stages):
            table[s] = levels[k].to_numpy()
        return cls(table.drop_duplicates(["design", "item"]), list(stages))

    @property
    def items(self) -> list[str]:
        return self.table["item"].drop_duplicates().tolist()

    def points(self, items=None) -> pd.DataFrame:
        """Per design: mean accuracy, dollars and seconds over `items`, with its stage levels."""
        t = self.table if items is None else self.table[self.table["item"].isin(set(items))]
        out = t.groupby("design").agg(accuracy=("correct", "mean"), dollars=("dollars", "mean"),
                                      seconds=("seconds", "mean"), **{s: (s, "first") for s in self.stages})
        return out.reset_index().sort_values("dollars", kind="stable").reset_index(drop=True)

    def design_of(self, levels) -> str:
        part = self.table.drop_duplicates("design")
        hit = part
        for s, v in zip(self.stages, levels):
            hit = hit[hit[s] == v]
        if hit.empty:
            raise KeyError(f"no grid design with levels {levels}")
        return str(hit["design"].iloc[0])
