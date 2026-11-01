"""Reads of Phase 4's October runs (analysis/phase4_lite.py) on simulated calls; offline."""

import numpy as np
import pandas as pd
import pytest

import analysis.phase4_lite as F

F.N_BOOT = 50


def saturation_calls(n=40, corr=0.0, seed=0):
    """Haiku calls under four prompts, 10 each. With corr = 1 every call on an item is right or wrong together."""
    rng = np.random.default_rng(seed)
    item_right = rng.random(n) < 0.5
    rows = []
    for i in range(n):
        for p in ("base", *F.PERSONAS):
            for c in range(10):
                ok = item_right[i] if rng.random() < corr else rng.random() < 0.5
                rows.append({"item": f"bbeh-x-{i:03d}", "source": f"haiku_nothink:{p}", "call": c, "parsed": True,
                             "answer": "0" if ok else str(rng.integers(1, 4)), "correct": float(ok)})
    return pd.DataFrame(rows), {f"bbeh-x-{i:03d}": "0" for i in range(n)}


def test_independent_calls_are_worth_their_number_and_identical_ones_are_worth_one():
    calls, gold = saturation_calls(corr=0.0)
    table = F.saturation(calls, gold, ms=(1, 5, 10)).set_index(["set", "m"])
    assert table.loc[("default", 10), "n_eff"] == pytest.approx(10, rel=0.35)
    same, gold = saturation_calls(corr=1.0)
    table = F.saturation(same, gold, ms=(1, 10, 40)).set_index(["set", "m"])
    assert table.loc[("mixed", 40), "n_eff"] == pytest.approx(1, abs=0.1)
    assert table.loc[("mixed", 40), "none right"] == pytest.approx(1 - table.loc[("mixed", 40), "plurality accuracy"])


def debate_agents(rounds):
    """rounds: list of items x 6 answer lists (gold "0")."""
    rows = []
    for r, answers in enumerate(rounds):
        stage = "debate" if r == 0 else f"debate.r{r + 1}"
        for i, row in enumerate(answers):
            for a, ans in enumerate(row):
                rows.append({"config_id": "k6-1", "task_id": f"t{i}", "stage": stage, "agent_id": f"{stage}.{a}",
                             "answer": ans, "correct": float(ans == "0"), "cost_usd": 0.001, "latency_s": 2.0})
    return pd.DataFrame(rows)


def test_debate_rounds_flips_and_consensus_exit():
    r1 = [["0"] * 6, ["0", "0", "1", "1", "1", "2"]]  # item 0 unanimous and right; item 1 split, plurality wrong
    r2 = [["0"] * 6, ["0", "0", "0", "1", "1", "1"]]
    r3 = [["0"] * 6, ["0", "0", "0", "0", "1", "1"]]
    d = F.debate(debate_agents([r1, r2, r3]), {"t0": "0", "t1": "0"})
    rounds = d["rounds"].set_index("round")
    assert rounds.loc[1, "plurality accuracy"] == 0.5 and rounds.loc[3, "plurality accuracy"] == 1.0
    assert rounds.loc[2, "wrong to right"] == pytest.approx(1 / 12) and rounds.loc[2, "right to wrong"] == 0
    assert rounds.loc[3, "dollars to here"] == pytest.approx(0.018)
    ex = d["consensus exit"]
    assert ex["stopped after round 1"] == 0.5  # item 0 stops (6 of 6 agree); item 1 runs every round
    assert ex["later calls skipped"] == pytest.approx(12 / 24) and ex["accuracy"] == 1.0
    assert ex["dollars"] == pytest.approx((0.006 + 0.018) / 2)
