"""Offline tests of the conviction desk (W2-A): events with known truth, prompts, parsing, the four
structures, the measures and a full fake-provider run."""

from __future__ import annotations

import asyncio
import math
import re

import numpy as np
import pandas as pd
import pytest

from autoagentnet.desk import prompts
from autoagentnet.desk.desk import DeskSettings, decisions, mechanical, pool, trader_request
from autoagentnet.desk.events import kelly_signed, logit, make_event, make_sequence, sigmoid
from autoagentnet.desk.fake import FakeDeskClient
from autoagentnet.desk.metrics import (TUNE_CHECKS, anchoring, ece, enrich, growth_factor, kelly_share, oracle_table,
                                       salience_table, structure_table, tune_checks, twin_details, twin_table, versus_solo)
from autoagentnet.desk.run import DeskConfig, estimate_desk, expectation_misses, run_desk
from autoagentnet.desk.desk import Call
from conftest import ROOT


def test_events_are_reproducible_and_carry_the_bayesian_probability():
    a, b = make_event(7, 3), make_event(7, 3)
    assert a == b and make_event(8, 3) != a
    x = logit(a.prior) + sum((1 if c.side == "YES" else -1) * logit(c.accuracy) for c in a.clues)
    assert math.isclose(a.true_p, sigmoid(x))
    assert 0.03 <= a.price <= 0.97 and round(a.price, 2) == a.price
    assert math.isclose(a.true_kelly, kelly_signed(a.true_p, a.price))
    assert (a.story != "") == a.salient and a.story_side in ("YES", "NO")


def test_a_sequence_is_balanced_and_its_story_carries_no_information():
    events = make_sequence(101, 200)
    salient = np.array([e.salient for e in events])
    assert 70 < salient.sum() < 130
    agree = np.mean([(e.story_side == "YES") == bool(e.outcome) for e in events])
    assert 0.35 < agree < 0.65  # a fair coin, independent of the outcome
    calibrated = np.mean([e.outcome for e in events]) - np.mean([e.true_p for e in events])
    assert abs(calibrated) < 0.1


def test_kelly_stake_maximizes_expected_log_growth():
    for p, q in [(0.7, 0.5), (0.2, 0.45), (0.55, 0.53)]:
        k = kelly_signed(p, q)
        side = "YES" if k > 0 else "NO"
        grid = np.linspace(0, 0.99, 991)
        value = [p * math.log(growth_factor(side, f, q, 1)) + (1 - p) * math.log(growth_factor(side, f, q, 0)) for f in grid]
        assert abs(grid[int(np.argmax(value))] - abs(k)) < 0.002


def test_prompts_carry_placeholders_and_no_example_values():
    for name in ("RULES", "TRADER_SYSTEM", "RISK_SYSTEM", "MEMBER_SYSTEM"):
        text = getattr(prompts, name)
        assert not re.search(r"\d\.\d|\d%", text), name  # "$1" is the contract's payout, not an example value
    assert "<your probability" in prompts.TRADER_SYSTEM and "<fraction" in prompts.RISK_SYSTEM
    # audit 40: the rules say what the evidence is and how the price is formed
    assert "the only evidence" in prompts.RULES and "plus random noise; it knows nothing more" in prompts.RULES
    assert set(prompts.TEMPLATE_HASHES) >= {"rules", "trader", "risk", "member"}
    request = trader_request(make_event(1, 0), DeskSettings())
    assert request.input.task == prompts.RULES  # the shared, cacheable block


def test_parsing_reads_the_formats_and_rejects_percent_or_out_of_range():
    ok = prompts.parse_trader("REASON: x\nPROBABILITY: 0.72\nSIDE: yes\nSTAKE: .15")
    assert (ok.p, ok.side, ok.stake, ok.parsed) == (0.72, "YES", 0.15, True)
    assert not prompts.parse_trader("PROBABILITY: 72%\nSIDE: YES\nSTAKE: 0.1").parsed
    assert not prompts.parse_trader("PROBABILITY: 0.7\nSIDE: YES\nSTAKE: 1.5").parsed
    assert prompts.parse_trader("**PROBABILITY:** 0.4\n**SIDE:** NONE").stake == 0.0
    assert prompts.parse_member("REASON: y\nPROBABILITY: 0.3") == 0.3 and prompts.parse_risk("STAKE: 0") == 0.0


def call(role: str, text: str) -> Call:
    return Call(role, text, False, 0.0, False)


def test_structures_turn_replies_into_stakes():
    event = make_event(1, 5)
    q = event.price
    p = min(0.95, q + 0.2)
    calls = {"trader": call("trader", f"REASON: r\nPROBABILITY: {p:.2f}\nSIDE: YES\nSTAKE: 0.9"),
             "risk": call("risk", "REASON: r\nSTAKE: 0.05"),
             **{f"member{k}": call(f"member{k}", f"REASON: r\nPROBABILITY: {p:.2f}") for k in (2, 3, 4, 5, 6)}}
    rows = {r["structure"]: r for r in decisions(event, calls, DeskSettings())}
    assert rows["S1"]["stake"] == 0.9 and rows["S1"]["signed_stake"] == 0.9
    assert rows["S2"]["stake"] == 0.05 and rows["S2"]["side"] == "YES"
    half = 0.5 * kelly_signed(round(p, 2), q)
    assert math.isclose(rows["S3"]["stake"], half) and math.isclose(rows["S4"]["stake"], half)
    assert rows["S4"]["members_parsed"] == 6


def test_unparsed_trader_means_staying_out_and_pooling_skips_missing_members():
    event = make_event(1, 6)
    calls = {"trader": call("trader", "I cannot say."), "member2": call("member2", "PROBABILITY: 0.8"),
             "member3": call("member3", "nonsense")}
    rows = {r["structure"]: r for r in decisions(event, calls, DeskSettings())}
    assert not rows["S1"]["parsed"] and rows["S1"]["stake"] == 0 and math.isnan(rows["S1"]["p"])
    assert not rows["S2"]["parsed"] and not rows["S3"]["parsed"]
    assert rows["S4"]["members_parsed"] == 1 and math.isclose(rows["S4"]["p"], 0.8)
    assert math.isclose(pool([0.9, 0.1], 0.01), 0.5) and mechanical(0.5, 0.5, 0.5) == ("NONE", 0.0)


def test_measures_on_known_numbers():
    assert math.isclose(ece(pd.Series([0.05, 0.05, 0.95, 0.95]), pd.Series([0, 0, 1, 1])), 0.05)
    assert math.isclose(growth_factor("YES", 0.5, 0.25, 1), 0.5 + 0.5 * 4)
    assert growth_factor("NO", 1.0, 0.25, 1) == 0.0 and growth_factor("NONE", 0.3, 0.5, 1) == 1.0


def fake_config(tmp_path, **kw) -> DeskConfig:
    base = dict(kind="desk", name="desk_test", seeds=[1, 2], events=30, model_override="fake", out_dir=str(tmp_path),
                providers=str(ROOT / "configs/providers.yaml"), pricing=str(ROOT / "configs/pricing.yaml"),
                budget=str(ROOT / "configs/budget.yaml"), chunk_events=10, git_checkpoint=False,
                expect={"max_unparsed_rate": 0.2})  # the fake's 2% unreadable replies can reach 5% on a few dozen calls
    return DeskConfig(**{**base, **kw})


def test_a_fake_run_plays_every_structure_and_the_measures_compute(tmp_path):
    decisions_df, calls_df, status = asyncio.run(run_desk(fake_config(tmp_path, twin=True)))
    assert status["state"] == "completed", status["reason"]
    salient = sum(e.salient for seed in (1, 2) for e in make_sequence(seed, 30))
    assert set(decisions_df["structure"]) == {"S1", "S2", "S3", "S4", "S1_twin"}
    assert (decisions_df["structure"] != "S1_twin").sum() == 2 * 30 * 4 and (decisions_df["structure"] == "S1_twin").sum() == salient
    assert (calls_df["role"] == "twin").sum() == salient
    assert status["template_hashes"] == prompts.TEMPLATE_HASHES
    out = tmp_path / "desk_test"
    events = pd.read_csv(out / "events.csv")
    assert len(events) == 60 and len(pd.read_csv(out / "decisions.csv")) == 240 + salient
    df = enrich(pd.read_csv(out / "decisions.csv"), events)
    table = structure_table(df).set_index("structure")
    assert table.loc["S1", "parsed"] > 0.9
    s3 = df[(df["structure"] == "S3") & df["parsed"]]
    assert math.isclose(table.loc["S3", "size_err_own"], (0.5 * s3["kelly_own"].abs()).mean())  # half Kelly at its own p...
    assert table.loc["S3", "overbet_own"] == 0  # ...so it never overbets against its own p
    assert {"ratio_lo", "diff_hi"} <= set(versus_solo(df).columns)
    assert {"stake", "stake_pull", "stake, item opposes the Kelly side"} <= set(salience_table(df)["measure"])
    paired = twin_table(df).set_index("measure")
    assert paired.loc["stake", "pairs"] > 0.9 * salient
    assert list(oracle_table(events)["benchmark"]) == ["stay out", "1 Kelly at true p", "0.5 Kelly at true p"]
    assert set(tune_checks(df)["check"]) == set(TUNE_CHECKS)


def test_slices_add_up_and_reuse_cached_trader_calls(tmp_path):
    cfg = fake_config(tmp_path, seeds=[3], events=20)
    asyncio.run(run_desk(cfg.model_copy(update={"event_offset": 0, "event_limit": 10})))
    asyncio.run(run_desk(cfg.model_copy(update={"event_offset": 10, "event_limit": 10})))
    decisions_df = pd.read_csv(tmp_path / "desk_test" / "decisions.csv")
    assert sorted(decisions_df["index"].unique()) == list(range(20))
    assert len(decisions_df) == 20 * 4


def test_unreadable_replies_stop_the_run(tmp_path, monkeypatch):
    async def mumble(self, request):
        response = await super(FakeDeskClient, self).complete(request)
        return response.model_copy(update={"text": "Hmm."})

    monkeypatch.setattr(FakeDeskClient, "complete", mumble)
    _, _, status = asyncio.run(run_desk(fake_config(tmp_path, seeds=[4], structures=["S1"])))
    assert status["state"] == "stopped" and "trader replies unparsed" in status["reason"]


def test_spend_kill_line_and_estimate_counts_calls(tmp_path):
    calls = pd.DataFrame({"role": ["trader"] * 30, "parsed": [True] * 30, "truncated": [False] * 30})
    from autoagentnet.desk.run import DeskExpect
    assert expectation_misses(calls, 0.5, DeskExpect(max_spend_usd=0.4))
    assert not expectation_misses(calls, 0.3, DeskExpect(max_spend_usd=0.4))
    one_in_twenty = pd.DataFrame({"role": ["trader"] * 20, "parsed": [False] + [True] * 19, "truncated": [False] * 20})
    assert not expectation_misses(one_in_twenty, 0.0, DeskExpect(min_calls=10))  # exactly 5% is within the limit
    cfg = fake_config(tmp_path, seeds=[101], events=20, model_override=None, model="haiku_nothink")
    assert int(estimate_desk(cfg.model_copy(update={"structures": ["S1"]}))["calls"].sum()) == 20
    assert int(estimate_desk(cfg)["calls"].sum()) == 20 * 7  # trader, 5 members, risk


def test_desk_analysis_writes_tables_figures_and_decision_lines(tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    from analysis import desk as analysis_desk

    asyncio.run(run_desk(fake_config(tmp_path / "results", name="tune_run", seeds=[1], events=30)))
    asyncio.run(run_desk(fake_config(tmp_path / "results", name="judge_run", seeds=[101, 102], events=30, twin=True)))
    tables = analysis_desk.build(["tune_run", "judge_run"], "judge", tmp_path / "results", tmp_path / "report")
    assert set(tables["structures"]["structure"]) == {"S1", "S2", "S3", "S4"}
    assert tables["structures"]["events"].eq(60).all()  # the tuning sequence and the twins are left out
    assert (tmp_path / "report/figures/desk_judge_wealth.png").exists()
    assert (tmp_path / "report/tables/desk_judge_salience.csv").exists()
    assert tables["anchoring"]["slope_on_price_noise"].notna().all()
    lines = analysis_desk.decision_lines(tables)
    assert sum("sizing error" in line for line in lines) == 3
    assert sum("S1 paired, stake:" in line for line in lines) == 1 and sum("S1 paired, stake_pull:" in line for line in lines) == 1
    assert all("of the gap to half Kelly" in line for line in lines if "x S1's (" in line)


def test_overbets_split_into_wrong_side_and_oversized():
    events = pd.DataFrame({"event_id": ["a", "b", "c"], "prior": 0.5, "outcome": [1, 0, 1], "true_p": [0.7, 0.3, 0.6],
                           "price": [0.5, 0.5, 0.5], "fair_price": 0.5, "true_kelly": [0.4, -0.4, 0.2], "salient": [True, False, False],
                           "story_side": ["YES", "NO", "YES"]})
    decisions_df = pd.DataFrame({"event_id": ["a", "b", "c"], "seed": 1, "index": [0, 1, 2], "model": "m", "structure": "S1",
                                 "parsed": True, "p": [0.9, 0.6, 0.6], "side": ["YES", "YES", "YES"],
                                 "stake": [0.6, 0.1, 0.1], "signed_stake": [0.6, 0.1, 0.1]})
    df = enrich(decisions_df, events)
    assert df["wrong_side"].tolist() == [False, True, False]  # event b: the true p gives YES no edge
    assert df["oversized"].tolist() == [True, False, False]  # event a: 0.6 is above its Kelly stake of 0.4
    row = structure_table(df).iloc[0]
    assert math.isclose(row["bias"], (0.2 + 0.3 + 0.0) / 3) and math.isclose(row["overbet_true"], 2 / 3)


def toy(events_rows: list[dict], decision_rows: list[dict]) -> pd.DataFrame:
    base_e = {"prior": 0.5, "outcome": 1, "true_p": 0.6, "price": 0.5, "fair_price": 0.5, "true_kelly": 0.2,
              "salient": False, "story_side": "YES"}
    base_d = {"seed": 1, "model": "m", "structure": "S1", "parsed": True, "p": 0.6, "side": "YES", "stake": 0.2,
              "signed_stake": 0.2}
    events = pd.DataFrame([{**base_e, **r} for r in events_rows])
    return enrich(pd.DataFrame([{**base_d, **r} for r in decision_rows]), events)


def test_an_all_in_loss_is_floored_not_minus_infinity():
    df = toy([{"event_id": "a", "outcome": 0}, {"event_id": "b"}],
             [{"event_id": "a", "index": 0, "stake": 1.0, "signed_stake": 1.0}, {"event_id": "b", "index": 1}])
    assert math.isclose(df["log_growth"].iloc[0], math.log(0.01))
    row = structure_table(df).iloc[0]
    assert np.isfinite(row["log_growth"]) and row["sequences_ruined"] == 1


def test_zero_stakes_are_never_wrong_side_bets():
    df = toy([{"event_id": "a", "true_kelly": -0.2}], [{"event_id": "a", "index": 0, "stake": 0.0, "signed_stake": 0.0}])
    assert not df["wrong_side"].iloc[0]


def test_twin_pairs_the_same_event_and_anchoring_reads_only_the_price_noise():
    rows_e = [{"event_id": f"e{i}", "salient": True, "story_side": "YES" if i % 2 else "NO",
               "price": 0.5 + 0.01 * (i % 5), "fair_price": 0.5} for i in range(40)]
    with_item = [{"event_id": f"e{i}", "index": i, "stake": 0.3, "signed_stake": 0.3,
                  "p": 0.6 + 0.5 * 0.01 * (i % 5)} for i in range(40)]
    twins = [{"event_id": f"e{i}", "index": i, "structure": "S1_twin", "stake": 0.2, "signed_stake": 0.2} for i in range(40)]
    df = toy(rows_e, with_item + twins)
    paired = twin_table(df).set_index("measure")
    assert math.isclose(paired.loc["stake", "effect"], 0.1) and paired.loc["stake", "pairs"] == 40
    assert math.isclose(paired.loc["stake", "lo"], 0.1)  # every pair differs by the same 0.1
    slope = anchoring(df).set_index("structure").loc["S1", "slope_on_price_noise"]
    assert math.isclose(slope, 0.5, abs_tol=1e-9)  # p moves half as much as the price's noise


def test_twin_confidence_means_cover_only_the_pairs_where_both_bet():
    rows_e = [{"event_id": f"e{i}", "salient": True} for i in range(4)]
    with_item = [{"event_id": f"e{i}", "index": i, "p": 0.6 + 0.1 * i} for i in range(4)]
    twins = [{"event_id": f"e{i}", "index": i, "structure": "S1_twin", "p": 0.6 + 0.1 * i,
              "side": "YES" if i < 2 else "NONE", "stake": 0.2 if i < 2 else 0.0} for i in range(4)]
    row = twin_table(toy(rows_e, with_item + twins)).set_index("measure").loc["confidence"]
    assert row["pairs"] == 2 and math.isclose(row["with_item"], row["without_item"])  # e2, e3: the twin stays out
    assert math.isclose(row["effect"], row["with_item"] - row["without_item"], abs_tol=1e-12)


def test_twin_details_split_the_drop_into_staying_out_and_smaller_stakes():
    # e0-e3: the item agrees with the Kelly side (YES); e4-e7: it opposes it (NO). The call with the item stakes
    # 0.1 less than its twin everywhere, and stays out on e0 where the twin bets.
    rows_e = [{"event_id": f"e{i}", "salient": True, "story_side": "YES" if i < 4 else "NO"} for i in range(8)]
    with_item = [{"event_id": f"e{i}", "index": i, "stake": 0.1, "signed_stake": 0.1} for i in range(1, 8)]
    with_item.append({"event_id": "e0", "index": 0, "side": "NONE", "stake": 0.0, "signed_stake": 0.0})
    twins = [{"event_id": f"e{i}", "index": i, "structure": "S1_twin", "stake": 0.2, "signed_stake": 0.2} for i in range(8)]
    twins[0].update(stake=0.1, signed_stake=0.1)
    details = twin_details(toy(rows_e, with_item + twins)).set_index("measure")
    assert math.isclose(details.loc["bet rate", "effect"], -1 / 8)
    assert details.loc["bet rate", "only_item_out"] == 1 and details.loc["bet rate", "only_twin_out"] == 0
    assert details.loc["stake when both bet", "pairs"] == 7
    assert math.isclose(details.loc["stake when both bet", "effect"], -0.1)
    assert math.isclose(details.loc["agrees minus opposes", "effect"], 0.0, abs_tol=1e-12)  # -0.1 in both groups
    assert math.isclose(details.loc["belief error", "effect"], 0.0, abs_tol=1e-12)


def test_kelly_share_reads_the_fraction_of_kelly_staked():
    rows_e = [{"event_id": f"e{i}", "true_kelly": 0.1 * (i + 1)} for i in range(5)]
    calls = [{"event_id": f"e{i}", "index": i, "stake": 0.025 * (i + 1), "signed_stake": 0.025 * (i + 1)} for i in range(5)]
    row = kelly_share(toy(rows_e, calls)).iloc[0]
    assert math.isclose(row["median_stake_over_kelly"], 0.25) and math.isclose(row["slope_on_kelly"], 0.25)


def test_one_failing_committee_member_stops_the_run_on_its_own():
    from autoagentnet.desk.run import DeskExpect
    calls = pd.DataFrame({"role": ["member2"] * 30 + ["member3"] * 30, "parsed": [True] * 30 + [True] * 26 + [False] * 4,
                          "truncated": [False] * 60})
    misses = expectation_misses(calls, 0.0, DeskExpect())
    assert misses and "member3" in misses[0]  # 4/30 = 13% alone; pooled with member2 it would be 6.7%


def test_working_before_the_answer_lines_is_allowed_and_a_cut_off_reply_is_unparsed():
    reply = "Prior odds 1.5. PROBABILITY: 0.9 at first sight.\nREASON: r\nPROBABILITY: 0.65\nSIDE: NO\nSTAKE: 0.1"
    assert prompts.parse_trader(reply).p == 0.65  # the last field counts
    event = make_event(1, 0)
    rows = {r["structure"]: r for r in decisions(event, {"trader": Call("trader", reply, True, 0.0, False)}, DeskSettings(),
                                                 ("S1", "S3"))}
    assert not rows["S1"]["parsed"] and rows["S1"]["stake"] == 0 and not rows["S3"]["parsed"]
    from autoagentnet.desk.run import reply_parsed
    assert not reply_parsed(Call("trader", reply, True, 0.0, False)) and reply_parsed(Call("trader", reply, False, 0.0, False))


def test_flipped_probabilities_are_counted_per_role():
    from autoagentnet.desk.metrics import flip_rates

    events = pd.DataFrame({"event_id": ["a", "b", "c"], "true_p": [0.647, 0.3, 0.5]})
    calls = pd.DataFrame({"event_id": ["a", "b", "c", "a"], "role": ["trader", "trader", "trader", "member2"], "model": "m",
                          "truncated": False,
                          "reply": ["PROBABILITY: 0.35\nSIDE: NO\nSTAKE: 0.1", "PROBABILITY: 0.3\nSIDE: NO\nSTAKE: 0.1",
                                    "PROBABILITY: 0.5\nSIDE: NONE\nSTAKE: 0", "PROBABILITY: 0.65"]})
    rows = flip_rates(calls, events).set_index("role")
    assert rows.loc["trader", "flipped"] == 1 and not rows.loc["trader", "passes"]  # 0.35 = 1 - 0.65; 0.5 is not a flip
    assert rows.loc["member2", "flipped"] == 0 and rows.loc["member2", "passes"]


def test_a_structure_on_fewer_events_is_paired_on_its_own_events_and_marked_descriptive(tmp_path):
    import matplotlib

    matplotlib.use("Agg")
    from analysis import desk as analysis_desk

    asyncio.run(run_desk(fake_config(tmp_path / "results", name="j1", seeds=[101], events=30, twin=True)))
    asyncio.run(run_desk(fake_config(tmp_path / "results", name="j2", seeds=[102, 103], events=30, twin=True,
                                     structures=["S1", "S2", "S3"])))
    tables = analysis_desk.build(["j1", "j2"], "judge", tmp_path / "results", tmp_path / "report")
    vs = tables["versus_solo"].set_index("structure")
    assert vs.loc["S4", "events"] == 30 and vs.loc["S3", "events"] == 90 and np.isfinite(vs.loc["S4", "size_err_ratio"])
    lines = analysis_desk.decision_lines(tables)
    assert any("S4: descriptive on 30 events" in line for line in lines)
    assert sum("sizing error" in line and "x S1's (" in line for line in lines) == 2  # S2 and S3 judged


def test_salience_readings_cover_intervals_below_zero():
    from analysis.desk import decision_lines

    tables = {"versus_solo": pd.DataFrame(columns=["model", "structure", "events"]), "structures": pd.DataFrame(
        columns=["model", "structure"]), "oracle": pd.DataFrame({"benchmark": ["stay out"], "size_err_true": [0.2]}),
        "twin": pd.DataFrame({"model": "m", "measure": ["stake", "stake_pull"], "pairs": 500, "effect": [-0.007, 0.004],
                              "lo": [-0.011, 0.001], "hi": [-0.003, 0.007]})}
    lines = decision_lines(tables)
    assert "lowering conviction (a prediction 7 miss)" in lines[0] and "pulling the stake toward its side" in lines[1]
