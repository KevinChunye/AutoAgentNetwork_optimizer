"""Regression test for step 0.9: the cached findings the evidence plan rests on, recomputed from
results/*/results.csv (tracked in git) with autoagentnet/evidence/, to two decimals."""

import pytest

from analysis.evidence_cached import findings


@pytest.fixture(scope="module")
def f():
    return findings()


def test_finding_1_and_2_repeat_correlation_and_all_or_nothing_items(f):
    assert round(f["rho"]["estimate"], 2) == 0.48 and round(f["rho_anova"], 2) == 0.48
    assert round(f["n_eff_5"], 2) == 1.71
    a = f["all_or_nothing"]
    assert (a["zero_of_5"], a["five_of_5"]) == (22, 24)
    assert round(a["zero_if_independent"], 1) == 3.7 and round(a["five_if_independent"], 1) == 2.6


def test_finding_3_shared_errors(f):
    assert round(f["haiku_pairs"]["ser"], 2) == 1.48 and round(f["haiku_pairs"]["phi"], 2) == 0.44
    assert round(f["design_pairs"]["ser"], 2) == 1.80 and round(f["design_pairs"]["phi"], 2) == 0.65
    assert round(f["haiku_sonnet"]["ser"], 2) == 1.14 and round(f["haiku_sonnet"]["phi"], 2) == 0.08


def test_finding_4_and_5_confidence(f):
    c = f["calibration"]
    assert round(c["naive_gap_points"], 1) == 14.2 and round(c["naive_brier"], 3) == 0.207
    assert round(c["one_feature_brier"], 3) == 0.191 and round(c["one_feature_gap_points"], 1) == 0.6
    assert round(c["two_feature_brier"], 3) == 0.161 and round(c["brier_gain"], 3) == 0.031
    s = f["sonnet_agreement"]
    assert (s["n_agrees"], s["n_not"]) == (42, 38)
    assert round(s["right_when_agrees"], 2) == 0.81 and round(s["right_when_not"], 2) == 0.29


def test_finding_8_cheap_cascade(f):
    c = f["cascade"]
    assert c["n"] == 40 and round(c["accuracy"], 3) == 0.725 and round(c["sonnet"], 3) == 0.725
    assert round(c["cost_ratio"], 2) == 0.52
