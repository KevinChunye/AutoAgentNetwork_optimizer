"""Turning confidence into decisions (step 0.8; plan step 2.8).

Terms (plain words first):
  coverage               the share of items the system answers itself (rather than escalating or abstaining).
  selective accuracy     accuracy on the items it answers.
  risk-coverage curve    for each confidence threshold, the coverage and the error rate on answered items.
  net dollars per item   value earned minus API dollars: a correct answer is worth V, a wrong one costs
                         lambda x V, an abstention is worth 0, and the dollars of every call made are
                         subtracted (the escalation call too, when it is made).
  cost per correct       total dollars divided by the number of correct answers.
  answer-escalate-abstain policy, with thresholds t_answer >= t_escalate on the cheap panel's confidence:
                         confidence >= t_answer: answer with the panel; t_escalate <= confidence < t_answer:
                         pay for the expensive model and answer with it; below t_escalate: abstain.
                         Thresholds are chosen on one fold of items and applied to the other (cross-fitting).
  cascade (H7)           a cheap panel answers when at least `k_agree` of its answers agree with its
                         plurality; otherwise the expensive model answers. Its cost is the cheap calls on
                         every item plus the expensive call on escalated items.
  Kelly stake            with belief p against a market price q (both in [0.01, 0.99]): bet YES with a share
                         (p - q) / (1 - q) of the bankroll when p > q, NO with (q - p) / q when p < q. Half
                         of it is used. One unit of bankroll per question, independently.
  return                 a YES stake f bought at q pays f (1 - q) / q if YES and loses f if NO; a NO stake f
                         bought at 1 - q pays f q / (1 - q) if NO and loses f if YES. No fees or spread.
  log growth             log(1 + return); the score is its mean over questions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .calibration import clip


def risk_coverage(conf, correct) -> pd.DataFrame:
    """One row per distinct threshold (answer when conf >= threshold): coverage and selective accuracy."""
    conf, correct = np.asarray(conf, dtype=float), np.asarray(correct, dtype=float)
    rows = []
    for t in np.unique(conf):
        answered = conf >= t
        rows.append({"threshold": t, "coverage": answered.mean(), "selective_accuracy": correct[answered].mean()})
    return pd.DataFrame(rows).sort_values("threshold").reset_index(drop=True)


def policy_value(conf, cheap_correct, expensive_correct, cheap_usd, expensive_usd, t_answer: float, t_escalate: float,
                 value: float = 0.10, lam: float = 3.0) -> np.ndarray:
    """Net dollars per item of the answer-escalate-abstain policy (see module docstring)."""
    conf = np.asarray(conf, dtype=float)
    cheap_correct, expensive_correct = np.asarray(cheap_correct, dtype=float), np.asarray(expensive_correct, dtype=float)
    answer = conf >= t_answer
    escalate = ~answer & (conf >= t_escalate)
    graded = np.where(answer, cheap_correct, np.where(escalate, expensive_correct, np.nan))
    earned = np.where(np.isnan(graded), 0.0, np.where(graded == 1, value, -lam * value))
    return earned - np.asarray(cheap_usd, dtype=float) - np.where(escalate, np.asarray(expensive_usd, dtype=float), 0.0)


def best_thresholds(conf, cheap_correct, expensive_correct, cheap_usd, expensive_usd, value=0.10, lam=3.0,
                    grid=None) -> tuple[float, float]:
    """The (t_answer, t_escalate) pair with the highest mean net dollars on these items; ties go to the
    first pair in the grid's order (higher thresholds first)."""
    grid = np.round(np.linspace(1.0, 0.0, 21), 2) if grid is None else np.asarray(grid)
    best, best_value = (1.0, 1.0), -np.inf
    for ta in grid:
        for te in grid[grid <= ta]:
            v = policy_value(conf, cheap_correct, expensive_correct, cheap_usd, expensive_usd, ta, te, value, lam).mean()
            if v > best_value + 1e-12:
                best, best_value = (float(ta), float(te)), v
    return best


def cross_fitted_policy(conf, cheap_correct, expensive_correct, cheap_usd, expensive_usd, folds, value=0.10,
                        lam=3.0) -> np.ndarray:
    """Net dollars per item, each fold scored with the thresholds chosen on the other folds."""
    arrays = [np.asarray(a, dtype=float) for a in (conf, cheap_correct, expensive_correct, cheap_usd, expensive_usd)]
    folds = np.asarray(folds)
    out = np.full(len(arrays[0]), np.nan)
    for f in np.unique(folds):
        test = folds == f
        ta, te = best_thresholds(*(a[~test] for a in arrays), value=value, lam=lam)
        out[test] = policy_value(*(a[test] for a in arrays), ta, te, value, lam)
    return out


def cascade(agree_count, cheap_correct, expensive_correct, cheap_usd, expensive_usd, k_agree: int) -> pd.DataFrame:
    """Per item: escalated (fewer than k_agree cheap answers agree with the plurality), correct, cost."""
    escalated = np.asarray(agree_count) < k_agree
    return pd.DataFrame({"escalated": escalated,
                         "correct": np.where(escalated, expensive_correct, cheap_correct).astype(float),
                         "cost_usd": np.asarray(cheap_usd, dtype=float) + np.where(escalated, np.asarray(expensive_usd, dtype=float), 0.0)})


def kelly_stake(p, q, fraction: float = 0.5) -> np.ndarray:
    """Signed stake as a share of a unit bankroll: positive = YES, negative = NO (fraction x Kelly)."""
    p, q = clip(p), clip(q)
    return fraction * np.where(p > q, (p - q) / (1 - q), -(q - p) / q)


def kelly_log_growth(p, q, y, fraction: float = 0.5) -> np.ndarray:
    """log(1 + return) per question of the independent fractional-Kelly bet at price q (no fees)."""
    q, y = clip(q), np.asarray(y, dtype=float)
    s = kelly_stake(p, q, fraction)
    yes, no = np.maximum(s, 0), np.maximum(-s, 0)
    ret = np.where(y == 1, yes * (1 - q) / q - no, no * q / (1 - q) - yes)
    return np.log1p(ret)
