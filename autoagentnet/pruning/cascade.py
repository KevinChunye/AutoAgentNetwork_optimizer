"""Cascades: answer from a cheap first round when it agrees enough, else call one escalation model.

Phase 3C as rebuilt in session E4 (Kevin's K2 and K3). Everything replays calls already made ($0): a flat panel's
calls are independent, so a cascade's answer, cost and time on an item follow exactly from the cached calls.

Terms (plain words first):
  first round      a fixed set of cheap call slots (units, e.g. "haiku_nothink:base:0") asked in parallel on every
                   item: 3 Haiku calls, 5 Luna calls, 3 Haiku + 3 Luna calls, and so on.
  search accuracy  a source's accuracy on the search items: the share of its first-round calls that are right
                   (an unparsed call is wrong). A source is a unit's `source` label (model ref and prompt).
  source weight    (K2, in its K-class form; audit 52) w = log((K - 1) a / (1 - a)), a the source's search accuracy
                   clipped to [0.01, 0.99] and K = K_CLASSES the rough number of possible answers. It is the log-odds
                   that a call's answer is right against its being one particular wrong answer, when wrong answers
                   spread evenly over the K - 1 others (the symmetric Dawid-Skene weight). With K = 2 it is K2's plain
                   log-odds, which turns negative below 50% accuracy, so agreeing with a call of a 48%-accurate source
                   would count against an answer; on BBEH, with many possible answers, agreement is rare by chance and
                   any source above 1 / K carries positive weight. K_CLASSES = 10 sits between the tasks' answer
                   spaces (5 and about 10 options; 27 yes/no/unknown triples; open numbers). Weights are floored at
                   W_MIN (only a source below 1 / K reaches it). Deviation 21 (deviations.md); Kevin to confirm.
  weighted vote    each answer class scores the summed weights of the calls that gave it; the top-scoring class is
                   the answer. A tie goes to the tied class answered by the source with the higher search accuracy
                   (then to the class met first), so the answer never depends on the order calls are listed in.
  agreement share  the weight behind the top answer divided by the weight of all first-round calls (unparsed calls
                   count in the divisor), in [0, 1]. With one source it is k / m: k of the m calls agree.
  confidence       (K2) P(the top answer is right) from a one-feature logistic regression on the agreement share,
                   cross-fitted: each item's confidence comes from a fit on the other fold. It is increasing in the
                   share, so a threshold on the confidence is a threshold on the share; thresholds are on the share.
  cascade policy   (first round, threshold t, escalation model): accept the top answer when the share is at least
                   t, else call the escalation model once and use its answer (an unparsed escalation is wrong).
  acceptance rate  the share of items the first round answers.
  accepted-wrong   the share of ALL items that are accepted with a wrong answer: the risk a threshold controls.
  dollars          per item, the first round's cost plus the escalation call's cost when escalated.
  seconds          per item, the slowest first-round call, plus the escalation call's seconds when escalated.
  rounds           1 when accepted, 2 when escalated.
  Learn-then-Test  (Angelopoulos et al., arXiv 2110.01052) picks t on calibration items with a guarantee. The
                   thresholds THRESHOLDS run from strict (1.0) to loose (0.05). At each t, test the hypothesis "the
                   accepted-wrong rate at t is above alpha" with the one-sided exact binomial test: X = the number of
                   calibration items accepted with a wrong answer out of n, p = P(Binomial(n, alpha) <= X); reject
                   when p <= delta. Walk down while hypotheses are rejected and keep the loosest threshold before the
                   first failure (fixed-sequence testing needs no multiplicity correction). Then with probability at
                   least 1 - delta over the calibration items, the chosen threshold's accepted-wrong rate is at most
                   alpha. When even t = 1.0 is not rejected, no threshold is certified and the policy escalates every
                   item (t = None). The guarantee needs labels; a label-free stand-in ("the top answer differs from
                   the escalation model's") is stricter, since an item where both are wrong counts against it.
  forecast cascade (ForecastBench, exploratory) the first round's forecast is the mean of its calls' log-odds; when
                   the spread of those log-odds (largest minus smallest) is above s, the escalation model's forecast
                   is used instead. Scored by the Brier score.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import binom

from .replay import L2, Panel, logistic_newton

W_MIN = 0.05
K_CLASSES = 10
THRESHOLDS = np.round(np.arange(1.0, 0.0, -0.05), 2)  # strict to loose: 1.00, 0.95, ..., 0.05
ALPHAS = (0.05, 0.10, 0.20)
DELTA = 0.05


def unit_positions(panel: Panel, units) -> np.ndarray:
    """Positions of the named units (in the order given)."""
    index = {u: k for k, u in enumerate(panel.units["unit"])}
    missing = [u for u in units if u not in index]
    if missing:
        raise KeyError(f"units not in the panel: {missing}")
    return np.array([index[u] for u in units], dtype=int)


def search_accuracy(panel: Panel, units, rows=None) -> pd.Series:
    """Per source of the given units: the share of its calls on `rows` that are right (unparsed = wrong)."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    pos = unit_positions(panel, units)
    right = panel.correct_matrix()[np.ix_(rows, pos)]
    long = pd.DataFrame({"source": np.repeat(panel.units["source"].to_numpy()[pos][None, :], len(rows), axis=0).ravel(),
                         "right": right.ravel()})
    return long.groupby("source", sort=False)["right"].mean()


def source_weights(accuracy: pd.Series, floor: float = W_MIN, k: int = K_CLASSES) -> pd.Series:
    """K2 in its K-class form: log((k - 1) a / (1 - a)) per source, a its search accuracy clipped to [0.01, 0.99],
    floored at `floor`."""
    a = accuracy.clip(0.01, 0.99)
    return np.log((k - 1) * a / (1 - a)).clip(lower=floor)


def first_round(panel: Panel, units, accuracy: pd.Series, rows=None, floor: float = W_MIN,
                k: int = K_CLASSES) -> pd.DataFrame:
    """The weighted vote of the first-round units on each item of `rows`.

    Columns: top (class index, -1 when no call parsed), correct (0/1), share (agreement share), dollars, seconds
    (slowest call), tokens (summed, 0 when unknown)."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    pos = unit_positions(panel, units)
    src = panel.units["source"].to_numpy()[pos]
    w = source_weights(accuracy, floor, k).reindex(src).to_numpy(dtype=float)
    rank = accuracy.reindex(src).to_numpy(dtype=float)  # tie-break: the higher search accuracy wins
    V = panel.votes[np.ix_(rows, pos)]
    width = panel.class_correct.shape[1]
    tops, shares, right = [], [], []
    for i, r in enumerate(rows):
        valid = V[i] >= 0
        if not valid.any():
            tops.append(-1)
            shares.append(0.0)
            right.append(0.0)
            continue
        score = np.zeros(width)
        best = np.full(width, -np.inf)
        np.add.at(score, V[i][valid], w[valid])
        np.maximum.at(best, V[i][valid], rank[valid])
        tied = np.flatnonzero(np.isclose(score, score.max()) & (score > 0))
        top = int(tied[np.argmax(best[tied])])  # argmax keeps the first class among equal accuracies
        tops.append(top)
        shares.append(float(score[top] / w.sum()))
        right.append(float(panel.class_correct[r, top]))
    tokens = (panel.tokens[np.ix_(rows, pos)].sum(axis=1) if panel.tokens is not None else np.zeros(len(rows)))
    return pd.DataFrame({"item": [panel.items[r] for r in rows], "top": tops, "correct": right, "share": shares,
                         "dollars": panel.cost[np.ix_(rows, pos)].sum(axis=1),
                         "seconds": panel.seconds[np.ix_(rows, pos)].max(axis=1), "tokens": tokens})


def escalation(panel: Panel, unit: str, rows=None) -> pd.DataFrame:
    """The escalation call on each item: correct (an unparsed call is wrong), dollars, seconds, tokens."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    g = unit_positions(panel, [unit])[0]
    tokens = panel.tokens[rows, g] if panel.tokens is not None else np.zeros(len(rows))
    return pd.DataFrame({"item": [panel.items[r] for r in rows], "correct": panel.correct_matrix()[rows, g],
                         "dollars": panel.cost[rows, g], "seconds": panel.seconds[rows, g], "tokens": tokens})


def replay(first: pd.DataFrame, esc: pd.DataFrame, t: float | None) -> pd.DataFrame:
    """Per item: accepted, correct, dollars, seconds, tokens and rounds of the policy (first round, t, escalation).
    t None accepts nothing."""
    share = first["share"].to_numpy()
    accepted = np.zeros(len(first), dtype=bool) if t is None else share >= t - 1e-9
    e = esc.set_index("item").loc[first["item"]]
    return pd.DataFrame({
        "item": first["item"].to_numpy(), "share": share, "accepted": accepted,
        "correct": np.where(accepted, first["correct"].to_numpy(), e["correct"].to_numpy()),
        "accepted_wrong": accepted & (first["correct"].to_numpy() < 1),
        "dollars": first["dollars"].to_numpy() + np.where(accepted, 0.0, e["dollars"].to_numpy()),
        "seconds": first["seconds"].to_numpy() + np.where(accepted, 0.0, e["seconds"].to_numpy()),
        "tokens": first["tokens"].to_numpy() + np.where(accepted, 0.0, e["tokens"].to_numpy()),
        "rounds": np.where(accepted, 1, 2)})


def differs_rate(panel: Panel, first: pd.DataFrame, esc_unit: str, t: float | None) -> float:
    """The label-free stand-in for the accepted-wrong rate: the share of all items accepted whose top answer is
    not the escalation call's answer (an unparsed escalation call counts as different)."""
    if t is None:
        return 0.0
    rows = np.array([panel.items.index(item) for item in first["item"]])
    esc = panel.votes[rows, unit_positions(panel, [esc_unit])[0]]
    accepted = first["share"].to_numpy() >= t - 1e-9
    return float((accepted & ((esc < 0) | (esc != first["top"].to_numpy()))).mean())


def summary(frame: pd.DataFrame) -> dict:
    """Acceptance rate, accepted-wrong rate, accuracy and mean dollars, seconds, tokens and rounds per item."""
    return {"n": len(frame), "acceptance": float(frame["accepted"].mean()),
            "accepted_wrong": float(frame["accepted_wrong"].mean()), "accuracy": float(frame["correct"].mean()),
            "dollars": float(frame["dollars"].mean()), "seconds": float(frame["seconds"].mean()),
            "tokens": float(frame["tokens"].mean()), "rounds": float(frame["rounds"].mean())}


def threshold_table(share, correct, thresholds=THRESHOLDS) -> pd.DataFrame:
    """For each threshold (strict to loose): the number of items accepted, the number accepted with a wrong
    answer (X), and both as shares of all items."""
    share, correct = np.asarray(share, dtype=float), np.asarray(correct, dtype=float)
    rows = []
    for t in thresholds:
        acc = share >= t - 1e-9
        rows.append({"t": float(t), "accepted": int(acc.sum()), "wrong": int((acc & (correct < 1)).sum()),
                     "acceptance": float(acc.mean()), "accepted_wrong": float((acc & (correct < 1)).mean())})
    return pd.DataFrame(rows)


def ltt(share, correct, alpha: float, delta: float = DELTA, thresholds=THRESHOLDS) -> float | None:
    """Learn-then-Test fixed-sequence choice of the loosest threshold whose accepted-wrong rate is certified at
    most alpha (probability >= 1 - delta). None when the strictest threshold already fails."""
    table = threshold_table(share, correct, thresholds)
    n = len(np.asarray(share))
    chosen = None
    for r in table.itertuples():
        p = binom.cdf(r.wrong, n, alpha)  # P(Bin(n, alpha) <= X): small when X is far below n * alpha
        if p > delta:
            break
        chosen = r.t
    return chosen


def confidence(share_fit, correct_fit, share_new, l2: float = L2) -> np.ndarray:
    """K2's stopping-rule confidence: P(right) from a one-feature logistic regression on the agreement share,
    fitted on (share_fit, correct_fit) and applied to share_new."""
    slope, intercept = logistic_newton(np.asarray(share_fit, dtype=float)[:, None], np.asarray(correct_fit, dtype=float), l2)
    return 1.0 / (1.0 + np.exp(-(intercept + slope * np.asarray(share_new, dtype=float))))


def cross_fit_confidence(share, correct, folds) -> np.ndarray:
    """Each item's confidence from a fit on the items of the other folds."""
    share, correct, folds = np.asarray(share, dtype=float), np.asarray(correct, dtype=float), np.asarray(folds)
    out = np.zeros(len(share))
    for f in np.unique(folds):
        test = folds == f
        out[test] = confidence(share[~test], correct[~test], share[test])
    return out


def cross_fit(panel: Panel, units, esc_unit: str, folds, alpha: float, delta: float = DELTA,
              floor: float = W_MIN) -> tuple[pd.DataFrame, dict]:
    """A cascade scored out of fold: on each fold, source accuracies and the threshold come from the other folds
    (LTT at alpha) and the policy is replayed on the fold. Returns the per-item frame (with each item's fold, t
    and cross-fitted confidence) and the thresholds by fold."""
    folds = np.asarray(folds)
    parts, chosen = [], {}
    for f in np.unique(folds):
        fit, test = np.flatnonzero(folds != f), np.flatnonzero(folds == f)
        acc = search_accuracy(panel, units, fit)
        first_fit = first_round(panel, units, acc, fit, floor)
        t = ltt(first_fit["share"], first_fit["correct"], alpha, delta)
        first_test = first_round(panel, units, acc, test, floor)
        frame = replay(first_test, escalation(panel, esc_unit, test), t)
        frame["confidence"] = confidence(first_fit["share"], first_fit["correct"], first_test["share"])
        parts.append(frame.assign(fold=f, t=np.nan if t is None else t))
        chosen[int(f)] = t
    out = pd.concat(parts)
    order = {item: k for k, item in enumerate(panel.items)}
    return out.assign(pos=out["item"].map(order)).sort_values("pos").drop(columns="pos").reset_index(drop=True), chosen


def forecast_first_round(panel: Panel, units, rows=None) -> pd.DataFrame:
    """ForecastBench first round: the mean log-odds forecast of the units and the spread of their log-odds
    (largest minus smallest), with dollars and seconds."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    pos = unit_positions(panel, units)
    L = np.log(panel.votes[np.ix_(rows, pos)] / (1 - panel.votes[np.ix_(rows, pos)]))
    return pd.DataFrame({"item": [panel.items[r] for r in rows], "prob": 1 / (1 + np.exp(-L.mean(axis=1))),
                         "spread": L.max(axis=1) - L.min(axis=1), "outcome": panel.outcome[rows],
                         "dollars": panel.cost[np.ix_(rows, pos)].sum(axis=1),
                         "seconds": panel.seconds[np.ix_(rows, pos)].max(axis=1)})


def forecast_replay(panel: Panel, units, esc_unit: str, s: float | None, rows=None) -> pd.DataFrame:
    """Per item: escalated (spread above s; s None escalates nothing), prob, brier, dollars, seconds."""
    rows = np.arange(panel.n) if rows is None else np.asarray(rows)
    first = forecast_first_round(panel, units, rows)
    g = unit_positions(panel, [esc_unit])[0]
    up = np.zeros(len(rows), dtype=bool) if s is None else first["spread"].to_numpy() > s
    prob = np.where(up, panel.votes[rows, g], first["prob"].to_numpy())
    return first.assign(escalated=up, prob=prob, brier=(prob - first["outcome"].to_numpy()) ** 2,
                        dollars=first["dollars"].to_numpy() + np.where(up, panel.cost[rows, g], 0.0),
                        seconds=first["seconds"].to_numpy() + np.where(up, panel.seconds[rows, g], 0.0))
