"""Session M1's analysis scripts on made-up data (offline, $0): the latency backfill's median regression and stage
profile, the configuration map's winners, held-out regret and cascades, the stage-balance ratios and the patching
numbers."""

import numpy as np
import pandas as pd
import pytest

from analysis import latency_backfill as LB
from analysis import latency_map as LM
from analysis import patch_context as PC
from analysis import stage_balance as SB
from autoagentnet.pruning.replay import Panel


def test_median_regression_recovers_overhead_and_decode_speed_despite_a_slow_tail():
    rng = np.random.default_rng(0)
    x = rng.integers(50, 3000, 400).astype(float)
    y = 0.8 + x / 200 + rng.normal(0, 0.05, 400)
    y[:40] += 60  # a slow tail (queueing, retries) that a mean fit would follow
    fit = LB.arm_fit(pd.DataFrame({"output_tokens": x, "seconds": y}), b=30)
    assert fit["overhead_s"] == pytest.approx(0.8, abs=0.1) and fit["decode_tok_s"] == pytest.approx(200, rel=0.03)
    assert fit["decode_lo"] <= fit["decode_tok_s"] <= fit["decode_hi"]


def test_per_call_backfill_and_arm_table():
    calls = pd.DataFrame({"run": "r", "arm": ["a"] * 30 + ["b"] * 30, "model": "m",
                          "input_tokens": 100, "cache_write_tokens": 50, "cache_read_tokens": 10,
                          "output_tokens": np.tile(np.arange(100, 400, 10), 2), "thinking_tokens": 0,
                          "cost_usd": 0.001, "from_cache": ["False"] * 59 + ["True"]})
    calls["seconds"] = 1.0 + calls["output_tokens"] / np.where(calls["arm"] == "a", 200, 20)
    out = LB.per_call(calls)
    assert (out["context_tokens"] == 160).all() and out["timing_source"].iloc[0] == "estimated"
    assert pd.isna(out["timing_source"].iloc[-1]) and out["e2e_tok_s"].iloc[0] == pytest.approx(100 / 1.5)
    table = LB.by_arm(out, b=20).set_index("arm")
    assert table.loc["a", "calls"] == 30 and table.loc["b", "calls"] == 29  # the cached row is left out
    assert table.loc["a", "decode_tok_s"] == pytest.approx(200, rel=0.01) and table.loc["b", "flag"].startswith("slow")


def test_stage_profile_ratios():
    rows = []
    for task in ("t1", "t2"):
        for stage, ctx, sec, usd in (("propose", 100, 8.0, 0.004), ("critique", 900, 5.0, 0.004), ("aggregate", 500, 2.0, 0.001)):
            rows.append({"run": "r", "config_id": "k", "item": task, "replicate": 0, "stage": stage,
                         "context_tokens": ctx, "seconds": sec, "cost_usd": usd})
    prof = LB.stage_profile(pd.DataFrame(rows)).iloc[0]
    assert prof["imbalance_peak_context"] == pytest.approx(900 / 500) and prof["max_stage_peak_context"] == "critique"
    assert prof["imbalance_latency_s"] == pytest.approx(8 / 5) and prof["max_stage_latency_s"] == "propose"


def toy_panel():
    """Two arms: a cheap fast one (3 calls) and a dear slow one (1 call) that is always right."""
    rng = np.random.default_rng(1)
    n = 60
    cheap = rng.integers(0, 3, (n, 3))  # answer 0 is right
    strong = np.zeros((n, 1), int)
    answers = np.hstack([cheap, strong])
    correct = (answers == 0).astype(float)
    cost = np.hstack([np.full((n, 3), 0.001), np.full((n, 1), 0.01)])
    seconds = np.hstack([np.full((n, 3), 2.0), np.full((n, 1), 20.0)])
    panel = Panel.from_arrays(answers, correct, cost, seconds, sources=["cheap:base"] * 3 + ["strong:base"],
                              calls=[0, 1, 2, 0])
    arms = {"cheap": [f"cheap:base:{c}" for c in range(3)], "strong": ["strong:base:0"]}
    return panel, arms


def test_configurations_winners_and_held_out_regret(monkeypatch):
    panel, arms = toy_panel()
    monkeypatch.setattr(LM, "STRONG", ["strong"])
    configs = LM.configurations(panel, arms, panel.seconds)
    names = {c["name"]: c for c in configs}
    assert {"cheap single", "cheap vote@2", "cheap vote@3", "strong single", "cheap vote@3 -> strong"} == set(names)
    cascade = names["cheap vote@3 -> strong"]
    assert (cascade["seconds"] >= 2.0).all() and cascade["seconds"].max() == 22.0
    assert names["cheap single"]["seconds"].shape == (panel.n, 3)  # a single call's p95 is per call
    assert (names["cheap vote@3"]["ttfat"] == panel.seconds[:, :3].max(axis=1)).all()  # a vote answers at its slowest
    rows = np.arange(panel.n)
    table = LM.summarize(configs, rows).set_index("name")
    assert table.loc["strong single", "accuracy"] == 1.0 and table.loc["cheap vote@3", "usd"] == pytest.approx(0.003)
    monkeypatch.setattr(LM, "USD_BUDGETS", [0.002, 0.02])
    cells = LM.winners(table.reset_index(), "p95_s", [5, 30]).set_index(["usd_budget", "latency_budget"])
    assert cells.loc[(0.02, 30), "winner"] == "strong single" and cells.loc[(0.02, 5), "winner"].startswith("cheap")
    assert cells.loc[(0.002, 30), "winner"] == "cheap vote@2"  # the strong arm is over $0.002
    regret = LM.held_out(configs, rows, "p95_s", [5, 30], splits=5)
    assert (regret["regret"].dropna() >= -1e-9).all() and {"regret_lo", "regret_hi", "violates"} <= set(regret)


def test_ttfat_estimate_subtracts_the_answer_at_the_arm_speed():
    panel, arms = toy_panel()
    out = np.full((panel.n, panel.m), 300.0)
    think = np.full((panel.n, panel.m), 100.0)
    t = LM.ttfat_matrix(panel, out, think, arms, {"cheap": 200.0, "strong": 20.0}, {"cheap": 0.5, "strong": 1.0})
    assert t[0, 0] == pytest.approx(2.0 - 200 / 200) and t[0, 3] == pytest.approx(max(20 - 200 / 20, 1.0))
    hidden = LM.ttfat_matrix(panel, out, think, arms, {"cheap": 200.0, "strong": 20.0}, {}, hidden={"strong"})
    assert hidden[0, 3] == 20.0  # hidden, unrecorded reasoning: TTFAT is the total
    assert {"sol61_low", "luna_med", "luna_low_ev"} <= LM.hidden_reasoning_refs() and "luna_none" not in LM.hidden_reasoning_refs()


def test_patch_variants_follow_the_note():
    msgs = []
    for s, stage in enumerate(["propose", "critique"]):
        for i in range(6):
            msgs.append({"task_id": "t", "stage_index": s, "stage": stage, "agent": i,
                         "context": 1000 + (600 if s == 1 else 0), "L": 100.0, "cL": 20.0})
    table = PC.stage_variants(pd.DataFrame(msgs), system={1: 100.0}).set_index("variant")
    assert table.loc["full", "peak_context"] == 1600 and table.loc["fan-in 2", "peak_context"] == 1200
    share = PC.W + 5 * PC.R
    assert table.loc["full", "input_usd"] == pytest.approx(1600 * share)
    assert table.loc["fan-in 2", "input_usd"] == pytest.approx(1000 * share + PC.W * 6 * 200)
    assert table.loc["compressed (measured)", "peak_context"] == 1120
    assert table.loc["fan-in 2", "input_usd_executor"] == pytest.approx(100 * share + PC.P_IN * (900 * 6 + 6 * 200))
    assert table.loc["full", "input_usd_executor"] == table.loc["full", "input_usd"]
    assert PC.n_eff(2, 0.43) == pytest.approx(2 / 1.43)
    text = "a\n\nbb\n\nANSWER: 1"
    assert PC.conclusion_share(text) == pytest.approx((len("bb") + len("ANSWER: 1")) / len(text))


def test_stage_balance_ratio_and_coefficients():
    assert SB.ratio([1, 1, 1]) == 1.0 and SB.ratio([2, 1, 0]) == 2.0
    configs = pd.DataFrame({"accuracy": [0.5, 0.6, 0.7, 0.55], "total_tokens": [1000, 2000, 4000, 1500],
                            "imbalance_context": [1.2, 1.4, 1.6, 1.1], "imbalance_latency": [1.5, 1.5, 1.6, 1.4],
                            "imbalance_usd": [1.3, 1.2, 1.1, 1.0]})
    coef = SB.coefficients(configs)
    assert set(coef) == {"imbalance_context", "imbalance_latency", "imbalance_usd"}
    assert SB.md_table(pd.DataFrame({"a": [1]})).startswith("| a |")
