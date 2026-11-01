"""The Phase 2 independence-per-dollar analysis (H11, analysis/evidence_phase2.py) on simulated calls with
non-zero costs (audit 47): when the other vendor's calls are less correlated with the base call than a
persona call of the same model, at the same price, H11's statistic is positive and its p-value small."""

import numpy as np
import pytest
import pandas as pd

from analysis import evidence_phase2 as P2


def simulated(n=200, seed=0):
    rng = np.random.default_rng(seed)
    bbeh_items = [f"b{i}" for i in range(n)]
    fc_items = [f"q{i}" for i in range(n)]
    chance_h = rng.beta(1, 1, n)  # Haiku's per-item chance; personas and resamples share it (same model)
    chance_l = np.clip(0.2 * chance_h + 0.8 * rng.beta(1, 1, n), 0, 1)  # Luna: mostly its own difficulty
    truth = rng.normal(0, 1, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-truth))).astype(float)
    shared_h = rng.normal(0, 1, n)
    rows = []

    def add(item, source, prompt, call, correct=None, prob=None, outcome=None, usd=0.0007):
        rows.append({"item": item, "source": f"{source}:{prompt}", "prompt": prompt, "call": call, "parsed": True,
                     "correct": correct, "prob": prob, "outcome": outcome, "cost_usd": usd, "answer": "x"})

    for i, item in enumerate(bbeh_items):
        for c in range(2):
            add(item, "haiku_nothink", "base", c, correct=float(rng.random() < chance_h[i]))
        add(item, "luna_none", "base", 0, correct=float(rng.random() < chance_l[i]))
        add(item, "haiku", "base", 0, correct=float(rng.random() < chance_h[i]), usd=0.003)
        for p in P2.PERSONAS:
            add(item, "haiku_nothink", p, 0, correct=float(rng.random() < chance_h[i]))
    for i, item in enumerate(fc_items):
        h = lambda: 1 / (1 + np.exp(-(truth[i] + shared_h[i] + rng.normal(0, 0.5))))
        for c in range(2):
            add(item, "haiku_nothink", "base", c, prob=h(), outcome=y[i])
        add(item, "luna_none", "base", 0, prob=1 / (1 + np.exp(-(truth[i] + rng.normal(0, 1.1)))), outcome=y[i])
        add(item, "haiku", "base", 0, prob=h(), outcome=y[i], usd=0.003)
        for p in P2.PERSONAS:
            add(item, "haiku_nothink", p, 0, prob=h(), outcome=y[i])
    return pd.DataFrame(rows), {"bbeh": bbeh_items, "forecast": fc_items}


def test_h11_is_positive_when_the_other_vendor_is_less_correlated():
    P2.N_BOOT = 300
    calls, items = simulated()
    out = P2.independence(calls, items)
    pt = out["point"]
    assert np.isfinite(pt["H11"]) and pt["H11"] > 0
    assert pt["bbeh:vendor"] > pt["bbeh:prompt"] and pt["forecast:vendor"] > pt["forecast:prompt"]
    assert pt["bbeh:reasoning"] < pt["bbeh:resample"]  # same correlation, four times the price
    assert out["p"] < 0.05


def sol_panel(n=120, seed=1):
    """Every Phase 2 system on n BBEH items and n questions: Sol always right (and sharp), Haiku with thinking on
    right 60% of the time against 40% off; aggregators answer like Sonnet."""
    rng = np.random.default_rng(seed)
    rows = []

    def add(item, source, call, correct=None, prob=None, outcome=None, usd=0.001):
        rows.append({"item": item, "source": source, "prompt": source.split(":")[1], "call": call, "parsed": True,
                     "correct": correct, "prob": prob, "outcome": outcome, "cost_usd": usd, "answer": "x"})

    calls = {"haiku_nothink:base": 5, "luna_none:base": 5, "sonnet_nothink:base": 1, P2.SOL: 1, "haiku:base": 2,
             "luna_med:base": 2, "haiku_nothink:aggregator": 1, "luna_none:aggregator": 1}
    right = {"haiku:base": 0.6, "haiku_nothink:base": 0.4, P2.SOL: 1.0}
    for i in range(n):
        y = float(rng.random() < 0.5)
        for source, k in calls.items():
            for c in range(k):
                usd = 0.006 if source == P2.SOL else 0.001
                add(f"b{i}", source, c, correct=float(rng.random() < right.get(source, 0.5)), usd=usd)
                sharp = 0.95 if source == P2.SOL else 0.6
                add(f"q{i}", source, c, prob=sharp if y else 1 - sharp, outcome=y, usd=usd)
    return pd.DataFrame(rows), [f"b{i}" for i in range(n)], [f"q{i}" for i in range(n)]


def test_sol_rows_compare_every_system_with_sol_alone():
    P2.N_BOOT = 200
    frame, items_b, items_f = sol_panel()
    calls = frame
    out = P2.sol_rows(calls[calls["item"].str.startswith("b")], calls[calls["item"].str.startswith("q")], items_b, items_f)
    by = out.set_index(["task", "system", "minus"])
    on_off = by.loc[("bbeh", "Haiku thinking on, one call", "Haiku thinking off, one call")]
    assert 0.1 < on_off["difference"] < 0.3 and on_off["low"] < on_off["difference"] < on_off["high"]
    assert by.loc[("bbeh", "Haiku thinking on, one call", "Sol alone"), "difference"] < -0.3
    # BBEH: one call's accuracy at one call's dollars (audit 61); ForecastBench: 2 pooled calls at their summed dollars
    assert by.loc[("bbeh", "Haiku thinking on, one call", "Sol alone"), "dollar ratio"] == pytest.approx(0.001 / 0.006)
    assert by.loc[("forecast", "Haiku thinking on, 2 calls pooled", "Sol alone"), "dollar ratio"] == pytest.approx(2 * 0.001 / 0.006)
    agg = by.loc[("bbeh", "aggregator (haiku)", "Sol alone")]
    assert agg["dollar ratio"] == pytest.approx((0.001 + 11 * 0.001 + 0.006) / 0.006)  # the 12 panel calls it reads
    assert by.loc[("forecast", "aggregator (luna)", "Sol alone"), "difference"] > 0  # Sol is sharper and right
    assert ("forecast", "aggregator (luna)", "the 12-call panel's pooled forecast") in by.index
    assert set(out["system"]) == {"Haiku thinking on, one call", "Luna thinking on, one call", "aggregator (haiku)",
                                  "aggregator (luna)", "Haiku thinking on, 2 calls pooled", "Luna thinking on, 2 calls pooled"}


def test_sol_rows_and_h12_pair_a_partial_arm():
    """Audit 65: when the thinking-on arm has calls on only some items, H12 and the Sol rows use only the items where
    both arms have calls, report n, and compute the dollar ratio on those items."""
    P2.N_BOOT = 200
    frame, items_b, items_f = sol_panel()
    calls = frame[frame["item"].str.startswith("b")]
    partial = calls[~((calls["source"] == "haiku:base") & ~calls["item"].isin(items_b[:20]))]
    out = P2.sol_rows(partial, frame.iloc[0:0], items_b, items_f).set_index(["task", "system", "minus"])
    row = out.loc[("bbeh", "Haiku thinking on, one call", "Haiku thinking off, one call")]
    assert row["n"] == 20 and row["dollar ratio"] == pytest.approx(1.0)
    assert out.loc[("bbeh", "aggregator (haiku)", "Sol alone"), "n"] == len(items_b)
    h12 = P2.reasoning(partial.assign(correct=partial["correct"].astype(float)), items_b)
    assert h12["n"] == 20
