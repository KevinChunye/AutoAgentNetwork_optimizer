"""The anchor's AH1-AH4 tests (analysis/anchor_read.py) and the power simulator (analysis/anchor_power.py) on
simulated anchors. Offline."""

import numpy as np
import pandas as pd
import pytest

from analysis import anchor_power as P
from analysis import anchor_read as R

ARMS = {"haiku_off": {"a": -0.3, "beta": 1.0, "calls": 3, "attract": 0.6, "usd": 0.0007},
        "haiku_low": {"a": 0.8, "beta": 1.0, "calls": 3, "attract": 0.6, "usd": 0.002},
        "luna_none": {"a": -1.2, "beta": 1.0, "calls": 3, "attract": 0.5, "usd": 0.0001},
        "luna_low": {"a": 0.0, "beta": 1.0, "calls": 3, "attract": 0.5, "usd": 0.0006},
        "sonnet_off": {"a": 0.6, "beta": 1.0, "calls": 1, "attract": 0.6, "usd": 0.014},
        "sonnet_low": {"a": 1.6, "beta": 1.0, "calls": 1, "attract": 0.6, "usd": 0.02},
        "sol_low": {"a": 2.2, "beta": 1.0, "calls": 3, "attract": 0.6, "usd": 0.006}}
JUDGE = {"pools": ["haiku_off", "luna_low"], "j0": 2.0, "j1": 1.0, "usd": 0.006}


@pytest.fixture(scope="module")
def anchor():
    return P.simulate(300, ARMS, JUDGE, np.random.default_rng(0))


def test_vote_and_accuracy_helpers(anchor):
    panel, units, _ = anchor
    acc = R.per_call_accuracy(panel, units["sol_low"])
    assert acc.shape == (300,) and 0.75 < acc.mean() < 0.95
    vote = R.vote_expected(panel, units["haiku_low"])
    assert 0 <= vote.min() and vote.max() <= 1
    assert R.nearest_k(panel, units["haiku_low"], units["haiku_off"]) == 3  # one deep call costs about 3 shallow ones


def test_ah1_ratio_matches_the_arms(anchor):
    panel, units, _ = anchor
    r = R.ah1(panel, units["sonnet_off"], units["sonnet_low"], units["sol_low"])
    a = {k: R.per_call_accuracy(panel, units[k]).mean() for k in ("sonnet_off", "sonnet_low", "sol_low")}
    assert r["estimate"] == pytest.approx((a["sonnet_low"] - a["sonnet_off"]) / (a["sol_low"] - a["sonnet_off"]))
    assert not r["void"] and 0 <= r["p"] <= 1


def test_ah2_takes_the_weaker_part(anchor):
    panel, units, _ = anchor
    r = R.ah2(panel, units["haiku_low"], units["haiku_off"], units["luna_low"], units["luna_none"])
    assert r["p"] == max(r["haiku"]["p"], r["luna"]["p"]) and r["haiku"]["difference"] > 0


def test_ah3_predicts_votes_of_a_factor_world(anchor):
    panel, units, _ = anchor
    r = R.ah3(panel, units)
    assert set(r["table"]["arm"]) == {k for k, v in ARMS.items() if v["calls"] >= 3}
    assert r["estimate"] < 0.05  # the world is the model's own: errors are sampling noise


def test_ah4_detects_coupling(anchor):
    panel, units, b = anchor
    r = R.ah4(panel, "judge:base:0", {"haiku_off": units["haiku_off"], "luna_low": units["luna_low"]}, b)
    assert r["eta_easy"] > r["eta_hard"]


def test_power_table_shape():
    t = P.power(150, ARMS, JUDGE, reps=3)
    assert set(t["test"]) == {"AH1", "AH2", "AH3", "AH4"} and t["pass_rate"].between(0, 1).all()
    assert abs(P.a_for(0.5)) < 0.05


def test_concat_keeps_items_classes_and_units():
    from analysis.anchor_read import concat
    from autoagentnet.pruning.replay import Panel

    A = np.array([[0, 1], [1, 1]])
    B = np.array([[0, 0], [2, 1], [0, 3]])
    pa = Panel.from_arrays(A, (A == 0).astype(float), np.ones(A.shape), sources=["x:base", "y:base"], calls=[0, 0],
                           items=["b1", "b2"])
    pb = Panel.from_arrays(B, (B == 0).astype(float), np.ones(B.shape), sources=["x:base", "y:base"], calls=[0, 0],
                           items=["m1", "m2", "m3"])
    p = concat(pa, pb)
    assert p.n == 5 and p.items == ["b1", "b2", "m1", "m2", "m3"]
    assert np.allclose(p.correct_matrix()[:2], pa.correct_matrix()) and np.allclose(p.correct_matrix()[2:], pb.correct_matrix())


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_regrade_bbeh_and_math_rows():
    import json
    from analysis.anchor_read import MATH_TASKS, regrade

    gold = next(json.loads(x)["answer"] for x in MATH_TASKS.read_text().splitlines() if '"arxivmath-0826-1"' in x)
    calls = pd.DataFrame({"item": ["bbeh-causal_understanding-0610", "arxivmath-0826-1"], "task_kind": ["bbeh", "math"],
                          "prompt": ["base", "base"], "reply": ["x\nANSWER: Ambiguous, since both", "\\boxed{" + gold + "}"],
                          "stop_reason": ["end_turn", "end_turn"], "answer": ["Ambiguous, since both", gold],
                          "parsed": [True, True], "correct": [0.0, 0.0]})
    out = regrade(calls)
    assert out.loc[0, "answer"] == "Ambiguous" and out.loc[0, "correct"] == 1.0  # the gold of 0610 is Ambiguous
    assert out.loc[1, "correct"] == 1.0  # math regraded from the reply against its gold


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_math_verify_timeouts_are_counted_per_row(monkeypatch):
    """Audit 90: a math-verify timeout reads as no match, so the read counts them per row (here a stand-in grader that
    logs one timeout warning the way math-verify does)."""
    import logging

    import autoagentnet.tasks as T
    from analysis.anchor_read import regrade_math

    def slow_match(reference, candidate, grader="exact"):
        logging.getLogger("math_verify.grader").warning("Timeout during comparison")
        return False

    monkeypatch.setattr(T, "answers_match", slow_match)
    calls = pd.DataFrame({"item": ["arxivmath-0826-1", "arxivmath-0826-1"], "task_kind": ["math", "math"],
                          "reply": ["\\boxed{7}", "no box"], "stop_reason": ["end_turn", "end_turn"],
                          "answer": [None, None], "parsed": [False, False], "correct": [0.0, 0.0]})
    out = regrade_math(calls)
    assert list(out["timeouts"]) == [1, 0] and list(out["correct"]) == [0.0, 0.0]
    assert not logging.getLogger("math_verify").handlers  # the counter is removed afterwards


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_math_read_normalization_keeps_golds_and_recovers_formats():
    """Audit 74: control spaces, ~, \\big sizes, \\tfrac/\\dfrac and a leading "name =" (when the gold has none) are
    normalized on both sides at read time; every sealed math gold still matches itself."""
    import json
    from analysis.anchor_read import MATH_TASKS, normalize_math_read
    from autoagentnet.tasks import answers_match

    assert normalize_math_read("(2,\\ 22,\\ -4)") == "(2, 22, -4)"
    assert normalize_math_read("\\tfrac12\\big[1+x\\big]") == "\\frac12[1+x]"
    assert normalize_math_read("tuple = (1, 2)", "(1,2)") == "(1, 2)"
    assert normalize_math_read("x = 5", "x = 5") == "x = 5"  # the gold has "=": kept
    ids = set((MATH_TASKS.parents[3] / "research/v3/evidence/sealed/math_all.txt").read_text().split())
    golds = [json.loads(x) for x in MATH_TASKS.read_text().splitlines() if x]
    for t in [g for g in golds if g["id"] in ids][:30]:
        assert answers_match(normalize_math_read(t["answer"]), normalize_math_read(t["answer"], t["answer"]), "math")


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_truncated_calls_count_as_wrong_and_fallback_runs_replace_their_config(tmp_path):
    """Audit 76: a truncated call is unparsed at the read whatever it carries; a config's `_t30` run, when it exists,
    is the one the read takes."""
    import json
    from analysis.anchor_read import MATH_TASKS, fallback, regrade

    gold = next(json.loads(x)["answer"] for x in MATH_TASKS.read_text().splitlines() if '"arxivmath-0826-1"' in x)
    calls = pd.DataFrame({"item": ["arxivmath-0826-1"] * 2, "task_kind": ["math"] * 2, "prompt": ["base"] * 2,
                          "reply": ["\\boxed{" + gold + "}"] * 2, "stop_reason": ["end_turn", "max_tokens"],
                          "truncated": [False, True], "answer": [gold] * 2, "parsed": [True] * 2, "correct": [1.0] * 2})
    out = regrade(calls)
    assert out.loc[0, "correct"] == 1.0 and out.loc[1, "correct"] == 0.0 and not out.loc[1, "parsed"]
    assert fallback("e51_x", tmp_path) == "e51_x"
    (tmp_path / "e51_x_t30").mkdir()
    (tmp_path / "e51_x_t30" / "calls.csv").write_text("item\n")
    assert fallback("e51_x", tmp_path) == "e51_x_t30"
