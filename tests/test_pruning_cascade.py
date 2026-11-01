"""Cascades (autoagentnet/pruning/cascade.py): the cached 5-Haiku baseline, the weighted vote, replay and
Learn-then-Test; offline (cached pilot calls and simulated panels, no API)."""

import numpy as np
import pandas as pd
import pytest

from analysis.pruning_phase3a import flat_calls
from autoagentnet.pruning import cascade as C
from autoagentnet.pruning.replay import Panel

HAIKU = [f"haiku:{k}" for k in range(5)]


@pytest.mark.parametrize("grader, expected", [
    # Kevin's figures (session E4 prompt): agreement = the same answer string after normalization
    ("exact", {1.0: (16, 2), 0.8: (35, 8), 0.6: (54, 16)}),
    # the replay library's classes: answers the BBEH grader calls equal agree, so more items reach k
    ("bbeh", {1.0: (23, 3), 0.8: (42, 10), 0.6: (58, 18)}),
])
def test_cached_five_haiku_baseline(grader, expected):
    """5 Haiku calls on the 80 cached items, accept when k of 5 agree (share k / 5): accepted and
    accepted-wrong counts. Exact strings give 67.5% / 20.0%, 43.8% / 10.0% and 20.0% / 2.5% for k >= 3, 4, 5."""
    panel = Panel.from_calls(flat_calls(), grader=grader)
    assert panel.n == 80
    first = C.first_round(panel, HAIKU, C.search_accuracy(panel, HAIKU))
    table = C.threshold_table(first["share"], first["correct"], list(expected)).set_index("t")
    for t, (accepted, wrong) in expected.items():
        assert (table.loc[t, "accepted"], table.loc[t, "wrong"]) == (accepted, wrong)


def test_label_free_check_is_stricter_than_the_labels():
    """At k >= 3 (exact strings), 20.0% of items are accepted with a wrong answer but 33.8% are accepted with an
    answer that differs from Sonnet's: the label-free stand-in also counts items where both are wrong."""
    panel = Panel.from_calls(flat_calls(), grader="exact")
    first = C.first_round(panel, HAIKU, C.search_accuracy(panel, HAIKU))
    assert C.differs_rate(panel, first, "sonnet:0", 0.6) == pytest.approx(27 / 80)
    assert C.summary(C.replay(first, C.escalation(panel, "sonnet:0"), 0.6))["accepted_wrong"] == pytest.approx(16 / 80)


def test_cascade_costs_and_rounds_add_up():
    panel = Panel.from_calls(flat_calls(), grader="bbeh")
    first = C.first_round(panel, HAIKU, C.search_accuracy(panel, HAIKU))
    esc = C.escalation(panel, "sonnet:0")
    never = C.replay(first, esc, None)
    assert not never["accepted"].any() and (never["rounds"] == 2).all()
    assert never["dollars"].sum() == pytest.approx(panel.cost.sum())
    assert never["correct"].mean() == pytest.approx(esc["correct"].mean())
    always = C.replay(first, esc, 0.0)
    assert always["accepted"].all() and always["dollars"].sum() == pytest.approx(panel.cost[:, :5].sum())


def simulated(n=400, seed=0, acc=(0.7, 0.6, 0.3)):
    """A panel of three sources (one call each plus an escalation call), answers from 4 classes."""
    rng = np.random.default_rng(seed)
    m = len(acc)
    right = rng.random((n, m + 1)) < np.r_[acc, 0.8]
    answers = np.where(right, 0, rng.integers(1, 4, (n, m + 1)))
    return Panel.from_arrays(answers, (answers == 0).astype(float), np.full((n, m + 1), 0.001),
                             sources=["a", "b", "c", "esc"], calls=[0] * (m + 1))


def test_weights_are_k_class_log_odds_of_accuracy_with_a_floor():
    w = C.source_weights(pd.Series({"good": 0.8, "coin": 0.5, "low": 0.2, "below_chance": 0.05}))
    assert w["good"] == pytest.approx(np.log(9 * 4)) and w["coin"] == pytest.approx(np.log(9))
    assert w["low"] == pytest.approx(np.log(9 / 4)) and w["below_chance"] == C.W_MIN  # under 1 / K: the floor
    assert C.source_weights(pd.Series({"good": 0.8}), k=2)["good"] == pytest.approx(np.log(4))  # K2 as written


def test_weighted_vote_does_not_depend_on_unit_order():
    panel = simulated()
    units = ["a:0", "b:0", "c:0"]
    acc = C.search_accuracy(panel, units)
    one = C.first_round(panel, units, acc)
    two = C.first_round(panel, units[::-1], acc)
    assert (one["correct"].to_numpy() == two["correct"].to_numpy()).all()
    assert np.allclose(one["share"], two["share"])


def test_tie_goes_to_the_more_accurate_source():
    # two sources disagree, one call each: the share ties only when weights are equal; with unequal accuracy the
    # heavier source wins outright, and with equal weights (both floored) the more accurate one wins the tie
    answers = np.array([[0, 1, 0]] * 4)
    panel = Panel.from_arrays(answers, (answers == 0).astype(float), np.zeros((4, 3)), sources=["x", "y", "e"])
    acc = pd.Series({"x": 0.40, "y": 0.45})  # with K = 2 both sit under a coin flip: equal (floored) weights
    first = C.first_round(panel, ["x:0", "y:0"], acc, k=2)
    assert (first["top"] == 1).all() and first["share"].eq(0.5).all()


def test_single_source_share_is_the_agreeing_fraction():
    answers = np.array([[0, 0, 1, -1, 0], [2, 2, 2, 2, 2]])
    panel = Panel.from_arrays(answers, (answers == 0).astype(float), np.zeros((2, 5)), sources=["h"] * 5,
                              calls=list(range(5)))
    first = C.first_round(panel, [f"h:{k}" for k in range(5)], pd.Series({"h": 0.6}))
    assert first["share"].tolist() == pytest.approx([3 / 5, 1.0])


def test_ltt_is_stricter_for_smaller_alpha_and_none_when_nothing_certifies():
    panel = simulated(n=300)
    units = ["a:0", "b:0", "c:0"]
    first = C.first_round(panel, units, C.search_accuracy(panel, units))
    picks = [C.ltt(first["share"], first["correct"], a) for a in (0.02, 0.10, 0.30)]
    as_number = [np.inf if p is None else p for p in picks]
    assert as_number[0] >= as_number[1] >= as_number[2]
    assert C.ltt(first["share"], np.zeros(len(first)), 0.10) is None  # every accepted answer wrong


def test_ltt_guarantee_holds_by_simulation():
    """Over many calibration draws, the fresh accepted-wrong rate at the chosen threshold exceeds alpha in at
    most about delta of the draws (plus Monte Carlo slack)."""
    units = ["a:0", "b:0", "c:0"]
    big = simulated(n=20000, seed=99)
    truth = C.first_round(big, units, pd.Series({"a": 0.7, "b": 0.6, "c": 0.3}))
    risk = C.threshold_table(truth["share"], truth["correct"]).set_index("t")["accepted_wrong"]
    alpha, misses, draws = 0.10, 0, 300
    for seed in range(draws):
        cal = simulated(n=200, seed=seed)
        first = C.first_round(cal, units, pd.Series({"a": 0.7, "b": 0.6, "c": 0.3}))
        t = C.ltt(first["share"], first["correct"], alpha)
        misses += t is not None and risk.loc[t] > alpha
    assert misses / draws <= C.DELTA + 0.03


def test_cross_fit_uses_the_other_fold():
    panel = simulated(n=200)
    folds = np.arange(panel.n) % 2
    frame, chosen = C.cross_fit(panel, ["a:0", "b:0", "c:0"], "esc:0", folds, alpha=0.10)
    assert len(frame) == panel.n and set(chosen) == {0, 1}
    assert frame["confidence"].between(0, 1).all()
    s = C.summary(frame)
    assert 0 <= s["accepted_wrong"] <= s["acceptance"] <= 1 and s["rounds"] == pytest.approx(2 - s["acceptance"])


def test_forecast_cascade_escalates_on_spread():
    probs = np.array([[0.2, 0.8, 0.9], [0.5, 0.55, 0.1]])
    panel = Panel.from_probs(probs, np.array([1.0, 0.0]), np.full((2, 3), 0.01), sources=["l", "l", "s"], calls=[0, 1, 0])
    none = C.forecast_replay(panel, ["l:0", "l:1"], "s:0", None)
    assert not none["escalated"].any()
    some = C.forecast_replay(panel, ["l:0", "l:1"], "s:0", 1.0)
    assert some["escalated"].tolist() == [True, False]
    assert some["prob"].iloc[0] == pytest.approx(0.9) and some["dollars"].tolist() == pytest.approx([0.03, 0.02])
