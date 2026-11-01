"""Offline tests for autoagentnet.insurance (synthetic data; no model calls, no downloads)."""

from __future__ import annotations

import json

import numpy as np
import pandas as pd

from autoagentnet.insurance import actuarial as ac
from autoagentnet.insurance import contagion as cg
from autoagentnet.insurance import events as ev
from autoagentnet.insurance import portfolio as pf


def test_write_exposure_rules():
    order = {"items": [{"item_id": "a", "price": 10.0}, {"item_id": "b", "price": 30.0}],
             "payment_history": [{"transaction_type": "payment", "amount": 40.0},
                                 {"transaction_type": "refund", "amount": 5.0}]}
    assert ev.write_exposure({"amount": 150}, None) == 150.0
    assert ev.write_exposure({"order_id": "#1", "item_ids": ["b"]}, json.dumps(order)) == 30.0
    assert ev.write_exposure({"order_id": "#1"}, json.dumps(order)) == 40.0
    assert ev.write_exposure({"user_id": "u"}, "not json") == 0.0


def _sim(task, trial, reward, db_match, calls):
    msgs = []
    for i, (name, args, result) in enumerate(calls):
        msgs.append({"role": "assistant", "tool_calls": [{"id": f"c{i}", "name": name, "arguments": args}]})
        msgs.append({"role": "tool", "id": f"c{i}", "content": json.dumps(result)})
    return {"task_id": task, "trial": trial, "agent_cost": 0.01, "messages": msgs,
            "reward_info": {"reward": reward, "db_check": {"db_match": db_match}}}


def test_tau2_episodes_kinds_and_dedup(tmp_path):
    res = {"payment_history": [{"transaction_type": "payment", "amount": 100.0}]}
    sims = [
        _sim("1", 0, 1.0, True, [("cancel_reservation", {"reservation_id": "R"}, res)]),
        # two writes to the same reservation count its value once
        _sim("1", 1, 0.0, False, [("cancel_reservation", {"reservation_id": "R"}, res),
                                  ("update_reservation_baggages", {"reservation_id": "R"}, res)]),
        _sim("2", 0, 0.0, False, [("get_reservation_details", {"reservation_id": "R"}, res)]),
        _sim("2", 1, 0.0, True, [("transfer_to_human_agents", {}, {})]),
    ]
    path = tmp_path / "m1_airline_default_u_4trials.json"
    path.write_text(json.dumps({"simulations": sims, "tasks": []}))
    t = ev.tau2_episodes(path)
    assert list(t["kind"]) == ["ok", "commission", "omission", "communication"]
    assert t.loc[1, "exposure_usd"] == 100.0 and t.loc[1, "n_writes"] == 2
    assert t.loc[3, "escalated"] == 1
    assert set(t["model"]) == {"m1"} and set(t["context"]) == {"airline"}


def _episodes(rates: dict, tasks: int = 60, trials: int = 4, clustered: bool = False, seed: int = 0):
    rng = np.random.default_rng(seed)
    rows = []
    for (model, ctx), p in rates.items():
        for t in range(tasks):
            hard = rng.random() < p
            for k in range(trials):
                d = int(hard) if clustered else int(rng.random() < p)
                rows.append({"model": model, "context": ctx, "task_id": str(t), "trial": k, "default": d,
                             "kind": "commission" if d else "ok", "exposure_usd": 100.0 * d})
    return pd.DataFrame(rows)


def test_icc_extremes():
    clustered = ac.task_counts(_episodes({("a", "x"): 0.4}, clustered=True))
    independent = ac.task_counts(_episodes({("a", "x"): 0.4}, tasks=400, clustered=False))
    assert ac.icc_beta_binomial(clustered) > 0.95
    assert ac.icc_beta_binomial(independent) < 0.1


def test_pass_hat_k_matches_definition():
    e = pd.DataFrame({"model": "a", "context": "x", "task_id": ["1"] * 4 + ["2"] * 4,
                      "default": [0, 0, 0, 1, 0, 0, 0, 0]})
    p2 = ac.pass_hat_k(e, 2)["pass_k"].iloc[0]
    # task 1: C(3,2)/C(4,2) = 0.5; task 2: 1.0
    assert abs(p2 - 0.75) < 1e-12


def test_frequency_table_credibility_bounds():
    e = _episodes({("a", "x"): 0.1, ("b", "x"): 0.3, ("c", "x"): 0.5})
    f = ac.frequency_table(e, "default", n_boot=200)
    assert f["Z"].between(0, 1).all()
    lo = np.minimum(f["raw_rate"], f["pool_rate"])
    hi = np.maximum(f["raw_rate"], f["pool_rate"])
    assert ((f["credible_rate"] >= lo - 1e-12) & (f["credible_rate"] <= hi + 1e-12)).all()
    assert (f["ci_lo"] <= f["raw_rate"]).all() and (f["raw_rate"] <= f["ci_hi"]).all()


def test_pure_premium_scales_with_lgd():
    e = _episodes({("a", "x"): 0.2, ("b", "x"): 0.2})
    low = ac.pure_premium_table(e, ac.LossAssumptions(lgd=0.1), n_boot=100)
    high = ac.pure_premium_table(e, ac.LossAssumptions(lgd=0.5), n_boot=100)
    assert (high["pure_premium"].to_numpy() > low["pure_premium"].to_numpy()).all()


def _book(models, n=12, p=0.01):
    return [pf.Insured(f"i{i}", models[i % len(models)], "x", 10000, p) for i in range(n)]


def test_portfolio_zero_rate_zero_loss():
    r = pf.simulate(_book(["m"], p=0.0), {"x": np.array([100.0])}, ac.LossAssumptions(),
                    pf.SimConfig(n_sims=500))
    assert r["mean"] == 0.0 and r["capital"] == 0.0


def test_portfolio_concentration_needs_more_capital():
    ex = {"x": np.array([50.0, 200.0, 1000.0])}
    cfg = pf.SimConfig(n_sims=4000, shocks=pf.ShockModel(rate_per_year=1.0, multiplier=8.0, months=2))
    one = pf.simulate(_book(["m"]), ex, ac.LossAssumptions(), cfg)
    four = pf.simulate(_book(["m1", "m2", "m3", "m4"]), ex, ac.LossAssumptions(), cfg)
    assert abs(one["mean"] / four["mean"] - 1) < 0.1
    assert one["capital"] > 1.3 * four["capital"]


def test_approval_gate_cuts_large_claims():
    ex = {"x": np.array([50.0, 5000.0])}
    base = pf.simulate(_book(["m"]), ex, ac.LossAssumptions(), pf.SimConfig(n_sims=2000))
    gated = pf.simulate(_book(["m"]), ex, ac.LossAssumptions(),
                        pf.SimConfig(n_sims=2000, controls=pf.Controls(approval_usd=1000, approval_catch=1.0)))
    assert gated["mean"] < 0.1 * base["mean"]


def test_adoption_and_monoculture():
    rows = []
    for t in range(40):
        all_wrong = t % 4 == 0
        for a in range(6):
            rows.append({"task_id": f"f-{t}", "family": "f", "replicate": 0, "stage": "propose",
                         "agent_id": f"p{a}", "correct": 0 if all_wrong else int(a > 0)})
        rows.append({"task_id": f"f-{t}", "family": "f", "replicate": 0, "stage": "refine",
                     "agent_id": "r0", "correct": 0 if all_wrong else 1})
    agents = pd.DataFrame(rows)
    curve = cg.adoption_curve(agents)
    six = curve[(curve["stage"].eq("refine")) & (curve["bucket"].astype(str).eq("6/6"))]
    assert float(six["p_wrong"].iloc[0]) == 1.0
    m = cg.monoculture(agents)
    assert m["all_wrong_observed"] == 0.25 and m["monoculture_factor"] > 1


def test_market_actions_breach_overshoot(tmp_path):
    run = tmp_path / "m9_test"
    run.mkdir()
    pd.DataFrame([
        {"seed": 1, "period": 1, "trader": "B1", "role": "buyer", "model": "h", "action": "BID", "price": 2.2,
         "limit": 2.0, "outcome": "rejected:budget", "best_bid_before": None, "best_ask_before": None},
        {"seed": 1, "period": 1, "trader": "S1", "role": "seller", "model": "h", "action": "ACCEPT", "price": None,
         "limit": 1.5, "outcome": "rejected:budget", "best_bid_before": 1.2, "best_ask_before": None},
        {"seed": 1, "period": 1, "trader": "S2", "role": "seller", "model": "h", "action": "ASK", "price": 1.9,
         "limit": 1.5, "outcome": "posted", "best_bid_before": None, "best_ask_before": None},
        {"seed": 1, "period": 1, "trader": "S2", "role": "seller", "model": "h", "action": "PASS", "price": None,
         "limit": 1.5, "outcome": "pass", "best_bid_before": None, "best_ask_before": None},
    ]).to_csv(run / "turns.csv", index=False)
    a = ev.market_actions(tmp_path)
    assert len(a) == 3 and a["breach"].sum() == 2
    assert np.allclose(np.sort(a["overshoot_usd"].to_numpy()), [0.0, 0.2, 0.3])
