import asyncio

import pandas as pd

from autoagentnet.market.run import MarketConfig, run_market
from conftest import ROOT


def fake_study(tmp_path) -> None:
    """Every market condition on fake models that keep their ref names, plus a small ZI-C baseline."""
    (tmp_path / "providers.yaml").write_text(
        "models:\n  haiku_nothink: {provider: fake, model: fake-haiku}\n  sonnet_nothink: {provider: fake, model: fake-sonnet}\n")
    (tmp_path / "ledger.jsonl").touch()
    for name in ["m1_smoke", "m2_haiku", "m4_mixed_odd", "m4_mixed_even", "m3_sonnet"]:
        cfg = MarketConfig.from_yaml(ROOT / f"configs/experiments/market/{name}.yaml").model_copy(update={
            "providers": str(tmp_path / "providers.yaml"), "ledger": str(tmp_path / "ledger.jsonl"),
            "cache": str(tmp_path / "cache"), "out_dir": str(tmp_path / "results"), "git_checkpoint": False,
            "max_usd": 100.0})
        asyncio.run(run_market(cfg))
    zic = MarketConfig.from_yaml(ROOT / "configs/experiments/market/zic.yaml").model_copy(
        update={"session_limit": 20, "out_dir": str(tmp_path / "results")})
    asyncio.run(run_market(zic))


def test_market_analysis_builds_every_table_figure_and_decision(tmp_path, monkeypatch):
    import analysis.market as market

    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    fake_study(tmp_path)
    monkeypatch.setattr(market, "REPORT", tmp_path / "report")
    monkeypatch.setattr(market, "TABLES", tmp_path / "report" / "tables")
    monkeypatch.setattr(market, "FIGURES", tmp_path / "report" / "figures")
    values = market.build(tmp_path / "results")
    tables = tmp_path / "report" / "tables"
    conditions = pd.read_csv(tables / "conditions.csv").set_index("condition")
    assert list(conditions.index) == ["ZI-C", "M1 Haiku smoke", "M2 all Haiku", "M4 mixed", "M3 all Sonnet"]
    assert conditions.loc["M2 all Haiku", "sessions"] == 4 and conditions.loc["M4 mixed", "sessions"] == 4
    assert (conditions["eff_lo"] <= conditions["efficiency_pct"]).all()
    decisions = pd.read_csv(tables / "decisions.csv")
    assert set(decisions["run"]) == {"M1", "M2", "M3", "M4"}
    assert values["m4_placebo_n"] == 6 and values["m4_sessions"] == 4  # 6 splits of M2's 4 sessions
    profit = pd.read_csv(tables / "m4_profit.csv")
    assert set(profit["model"]) == {"Haiku", "Sonnet"} and set(profit["role"]) == {"buyer", "seller", "all"}
    # each rank is Sonnet in two sessions and Haiku in the other two, so the CE pools match
    pools = profit[profit["role"] == "all"].set_index("model")["ce_profit"]
    assert pools["Haiku"] == pools["Sonnet"] == 75.0
    figures = {p.stem for p in (tmp_path / "report" / "figures").glob("*.png")}
    assert figures == {"a_supply_demand", "b_price_paths", "c_efficiency", "d_m4_profit", "e_alpha"}
    from analysis.market_replay import TURN_COLUMNS, replay_data

    replay = replay_data(tmp_path / "results")
    assert len(replay["sessions"]) == 11 and replay["schedule"]["max_surplus"] == 7.5
    first = replay["sessions"][0]
    assert len(first["traders"]) == 22 and all(len(turn) == len(TURN_COLUMNS) for turn in first["turns"])
    mixed = next(s for s in replay["sessions"] if s["config"] == "m4_mixed_odd")
    assert mixed["traders"]["B1"]["model"] == "Sonnet" and mixed["traders"]["B2"]["model"] == "Haiku"


def test_decision_boundaries_are_the_preregistered_ones():
    # audit 27, finding 5: fixed thresholds, inclusive boundaries, no floating-point surprises
    from analysis.market import m2_rule, m3_holds, m4_verdict, price_within

    assert m2_rule(85.4) == "sane (>= ZI-C - 5)" and m2_rule(85.39) == "near ZI-C"
    assert m2_rule(80.4) == "near ZI-C" and m2_rule(80.39) == "worse than ZI-C (< ZI-C - 10)"
    assert price_within(1.85) and price_within(2.15) and not price_within(1.849)
    assert m3_holds(-7.0, -0.5) and not m3_holds(-6.99, -0.5) and not m3_holds(-9.0, 0.0)
    assert m4_verdict(20.0, 19.9, True) == "exploitation"
    assert m4_verdict(20.0, 21.0, True).startswith("meets the prediction")
    assert m4_verdict(25.0, 1.0, False).startswith("not interpreted")
    assert m4_verdict(9.9, 1.0, True) == "no exploitation found"
