"""analysis/phase1_posthoc.py on simulated tables (offline, no API, no sealed data)."""

import numpy as np
import pandas as pd
import pytest

from analysis import phase1_posthoc as P
from autoagentnet.evidence import calibration as C


def bbeh_table(n=200, seed=0):
    """y = the plurality is right; Sol agrees exactly when it is; the other sources are noise."""
    rng = np.random.default_rng(seed)
    y = (rng.random(n) < 0.6).astype(float)
    return pd.DataFrame({"item": [f"bbeh-t-{i}" for i in range(n)], "task": [f"t{i % 4}" for i in range(n)],
                         "panel12_right": y, "o_agree": y, "h_agree": rng.random(n), "l_agree": rng.random(n),
                         "s_agree": (rng.random(n) < 0.5).astype(float)})


def test_sol_only_matches_the_whole_panel_when_sol_is_an_oracle():
    b = P.sol_only(bbeh_table())
    assert b["brier"]["Sol-only"] < 0.01 and b["brier"]["Haiku-only"] > 0.2
    assert abs(b["diff"]) < 0.01 and b["ci"][0] <= b["diff"] <= b["ci"][1]
    assert b["right_when_sol_agrees"] == 1.0


def forecast_frame(n=200, seed=0):
    """Half market questions with a price; Sol forecasts close to the truth, Haiku and Luna are noisier."""
    rng = np.random.default_rng(seed)
    truth = rng.random(n)
    y = (rng.random(n) < truth).astype(int)
    noisy = lambda s: C.logit(C.clip(truth + rng.normal(0, s, n)))
    t = pd.DataFrame({"item": [f"fc-{i}" for i in range(n)], "outcome": y, "market": np.arange(n) % 2 == 0,
                      "price": C.clip(truth + rng.normal(0, 0.05, n)), "fb_source": np.where(np.arange(n) % 2 == 0, "m", "d"),
                      "resolution_date": pd.Timestamp("2026-08-01") + pd.to_timedelta(np.arange(n) % 30, unit="D"),
                      "split": "sealed", "logit_H": noisy(0.3), "logit_L": noisy(0.4), "logit_S": noisy(0.05),
                      "logit_O": noisy(0.02)})
    t["panel_logit"] = (5 * t["logit_H"] + 5 * t["logit_L"] + t["logit_S"] + t["logit_O"]) / 12
    return t


def test_paired_differences_favour_the_sharp_forecaster():
    f = P.forecast_posthoc(forecast_frame())
    sealed = f["sealed"].set_index("a minus b")
    assert sealed.loc["panel minus Sol", "Brier diff"] > 0  # the noisy panel is worse than Sol
    assert sealed.loc["Haiku minus Sonnet", "Brier diff"] > 0
    row = sealed.loc["panel minus Sol"]
    assert row["low"] <= row["Brier diff"] <= row["high"] and row["primary"] in ("question", "source x week")
    assert len(f["market"]) == len(P.MARKET_PAIRS)


def test_within_outcome_correlation_removes_the_shared_outcome():
    """Two forecasters with independent noise around a constant 0.5 have errors f - y correlated by y alone; their
    forecasts within an outcome are uncorrelated."""
    rng = np.random.default_rng(1)
    n = 400
    y = (rng.random(n) < 0.5).astype(int)
    t = pd.DataFrame({"outcome": y, "market": True, "price": 0.5,
                      **{f"logit_{k}": rng.normal(0, 0.1, n) for k in "HLSO"}})
    t["panel_logit"] = 0.0
    err = np.corrcoef(C.sigmoid(t["logit_H"]) - y, C.sigmoid(t["logit_L"]) - y)[0, 1]
    within = P.within_outcome(t).set_index("pair")["r"]
    assert err > 0.9 and abs(within["Haiku-Luna"]) < 0.2
    assert P.within_outcome(t, minus_price=True).set_index("pair")["r"]["Haiku-Luna"] == pytest.approx(within["Haiku-Luna"])


def test_report_renders():
    text = P.report(P.sol_only(bbeh_table()), P.forecast_posthoc(forecast_frame()))
    assert "Sol-only" in text and "panel minus Sol" in text and "forecast minus price" in text
