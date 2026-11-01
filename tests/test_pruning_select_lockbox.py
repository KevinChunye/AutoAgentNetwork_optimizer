"""Phase 3B's selection rule (analysis/pruning_select.py), the lockbox read (analysis/pruning_lockbox.py) and the
power simulation's panel (analysis/pruning_power.py) on simulated 18-call panels; offline, $0."""

import json

import numpy as np
import pandas as pd
import pytest

from analysis import pruning_lockbox as L
from analysis import pruning_power as W
from analysis import pruning_select as P
from autoagentnet.pruning import search as S
from autoagentnet.pruning.replay import Panel, fit, replay


def long_calls(panel: Panel) -> pd.DataFrame:
    """A simulated choice panel as call rows shaped like calls.csv."""
    rows = []
    for i, item in enumerate(panel.items):
        for g, unit in enumerate(panel.units["unit"]):
            source, call = unit.rsplit(":", 1)
            v = panel.votes[i, g]
            rows.append({"item": item, "source": source, "call": int(call), "answer": None if v < 0 else panel.labels[i][v],
                         "parsed": v >= 0, "correct": float(v >= 0 and panel.class_correct[i, v] > 0),
                         "cost_usd": panel.cost[i, g], "seconds": 1.0})
    return pd.DataFrame(rows)


@pytest.fixture(scope="module")
def search():
    return W.simulate(200, 0.6, 0.85, np.random.default_rng(11))


@pytest.fixture(scope="module")
def selection(search):
    return P.select(search, "bbeh")


def test_the_lockbox_panel_has_18_units_in_ten_sources(search):
    assert len(P.lockbox_units()) == 18 and search.units["unit"].tolist() == P.lockbox_units()
    lay = P.layers(search)
    assert len(lay) == 10 and {k: len(v) for k, v in lay.items() if len(v) > 1} == {"haiku_nothink:base": 5,
                                                                                    "luna_none:base": 5}
    assert "luna_none:contrarian" in lay and "sonnet_nothink:base" in lay


def test_build_panel_reads_call_rows_into_the_same_panel(search):
    calls = long_calls(search)
    calls = pd.concat([calls, calls.assign(source="sonnet_nothink:base", call=1).iloc[:5]])  # a second Sonnet call: ignored
    panel = P.build_panel(calls.sample(frac=1, random_state=0), "bbeh")
    assert panel.units["unit"].tolist() == P.lockbox_units()
    order = [panel.items.index(i) for i in search.items]
    assert np.array_equal(panel.correct_matrix()[order], search.correct_matrix())


def test_selection_follows_the_rule_and_frozen_networks_replay_exactly(search, selection):
    sel = selection
    na = pd.DataFrame(sel["tables"]["netadapt"])
    floor = sel["sonnet_score"] - P.MARGIN["bbeh"]
    ok = na[na["score"] >= floor - 1e-12]
    if len(ok):
        expected = ok.sort_values(["dollars", "score"], ascending=[True, False]).iloc[0]
        assert sel["static"]["cross_fitted_score"] == pytest.approx(expected["score"])
        assert set(sel["static"]["units"]) <= set(P.lockbox_units())
        assert ("P1" in sel["void"]) == (sel["static"]["units"] == [P.SONNET])
    else:
        assert sel["static"] is None and {"P1", "P2", "P3"} <= set(sel["void"])  # no fallback network
    # each half's network at a budget costs at most that budget on its search half
    dyn = pd.DataFrame(sel["tables"]["dynamic"])
    assert set(dyn["order"]) == {"cheapest-first", "gain per $"} and len(dyn) == 2 * len(P.TAUS)
    if sel["dynamic"] is not None:
        fits = dyn[dyn["score"] >= (sel["static"]["cross_fitted_score"] if sel["static"] else floor) - 1e-12]
        assert sel["dynamic"]["cross_fitted_dollars"] == pytest.approx(fits["dollars"].min())
    # frozen on the search items = fitted on all of them
    table = P.apply_frozen(search, json.loads(json.dumps(sel, default=float)))
    every = np.arange(search.n)
    dense = replay(search, search.all_units(), every, fit(search, search.all_units(), every))
    assert np.array_equal(table["dense_score"], dense["correct"])
    assert sel["dense"]["weights"]["aggregator"] == "plurality"  # Kevin's aggregator is what is frozen
    names = search.units["unit"].tolist()
    if sel["dynamic"] is not None:
        order = [names.index(u) for u in sel["dynamic"]["order"]]
        dyn_fit = S.dynamic_replay(search, order, sel["dynamic"]["tau"], every, every)
        assert np.array_equal(table["dynamic_score"], dyn_fit["correct"])
        assert np.allclose(table["dynamic_dollars"], dyn_fit["dollars"])
    assert np.allclose(table["sonnet_dollars"], 0.0144)


def test_networks_are_matched_across_halves_by_budget_not_step():
    """Audit 49: a path read at budget B gives its largest network costing at most B."""
    path = pd.DataFrame({"kept": ["a+b+c", "a+b", "a"], "dollars": [0.03, 0.02, 0.001]})
    assert P.at_budget(path, 0.025) == "a+b" and P.at_budget(path, 0.02) == "a+b" and P.at_budget(path, 0.0005) is None
    table = pd.DataFrame({"budget": [0.001, 0.02, 0.03], "score": [0.5, 0.70, 0.72], "dollars": [0.001, 0.019, 0.03]})
    assert P.pick(table, 0.69)["budget"] == 0.02
    assert P.pick(table, 0.69, max_dollars=0.015) is None  # option (b): nothing cheap enough -> void, no fallback
    assert P.pick(table, 0.80) is None


def test_a_cost_bound_keeps_selected_networks_cheaper_than_sonnet(search):
    sel = P.select(search, "bbeh", orders=("cheapest-first",), cost_bound=0.8)
    if sel["static"] is not None:
        assert sel["static"]["cross_fitted_dollars"] <= 0.8 * sel["sonnet_dollars"] + 1e-12
    if sel["dynamic"] is not None:
        assert sel["dynamic"]["cross_fitted_dollars"] <= 0.8 * sel["sonnet_dollars"] + 1e-12


def test_lockbox_tests_have_the_right_direction_and_holm():
    rng = np.random.default_rng(0)
    n = 400
    sonnet = (rng.random(n) < 0.7).astype(float)
    table = pd.DataFrame({"sonnet_score": sonnet, "static_score": sonnet,  # P1: identical -> clears -5 easily
                          "dense_score": np.minimum(1, sonnet + (rng.random(n) < 0.3)),  # P2: static about 9 points worse
                          "dynamic_score": sonnet,  # P3: identical -> clears -3
                          "sonnet_dollars": 0.0144, "static_dollars": 0.0144, "dense_dollars": 0.04, "dynamic_dollars": 0.008})
    conf = {"P1": "conf", "P2": "conf", "P3": "conf"}
    out = L.tests(table, None, "bbeh", status=conf).set_index("test")
    assert out.loc["P1", "p"] < 0.001 and out.loc["P3", "p"] < 0.001 and out.loc["P2", "p"] > 0.5
    assert out.loc["P1", "passes"] and out.loc["P3", "passes"] and not out.loc["P2", "passes"]
    assert out.loc["P3", "cost ratio"] == pytest.approx(0.008 / 0.0144)
    expl = L.tests(table, None, "bbeh", status={"P1": "conf", "P2": "expl", "P3": "expl"}).set_index("test")
    assert expl.loc["P3", "status"] == "expl" and pd.isna(expl.loc["P3", "passes"])
    void = L.tests(table, None, "bbeh", status=conf, void=["P1"]).set_index("test")
    assert void.loc["P1", "status"] == "void" and pd.isna(void.loc["P1", "p"]) and pd.isna(void.loc["P1", "passes"])
    assert void.loc["P3", "passes"]  # Holm runs over P2 and P3 only
    assert L.STATUS == {"P1": "expl", "P2": "expl", "P3": "expl"}  # the power simulation's decision (session E3)


def test_forecast_panels_fill_unparsed_with_one_half_and_select_runs():
    rng = np.random.default_rng(2)
    n = 120
    truth = rng.normal(0, 1.5, n)
    y = (rng.random(n) < 1 / (1 + np.exp(-truth))).astype(float)
    rows = []
    for i in range(n):
        for unit in P.lockbox_units():
            source, call = unit.rsplit(":", 1)
            noise = 1.2 if source.startswith(("haiku", "luna")) else 0.6
            p = 1 / (1 + np.exp(-(truth[i] + rng.normal(0, noise))))
            parsed = not (i == 0 and unit == "haiku_nothink:base:0")
            rows.append({"item": f"q{i}", "source": source, "call": int(call), "prob": p if parsed else np.nan,
                         "parsed": parsed, "outcome": y[i], "cost_usd": 0.0004 if noise > 1 else 0.008, "seconds": 1.0})
    panel = P.build_panel(pd.DataFrame(rows), "forecast")
    assert panel.kind == "prob" and panel.votes[0, 0] == 0.5
    sel = P.select(panel, "forecast", orders=("cheapest-first",))
    table = P.apply_frozen(panel, sel)
    assert (table["dense_score"] <= 0).all() and table["dense_score"].mean() >= table["sonnet_score"].mean() - 0.05
    out = L.tests(table, None, "forecast", void=sel["void"])
    assert "p" not in out and len(out) == 3
    assert set(out.loc[out["status"] == "void", "test"]) >= set(sel["void"])


def test_selection_is_never_rewritten_and_never_frozen_from_partial_inputs(tmp_path, monkeypatch):
    frozen = tmp_path / "selected.json"
    frozen.write_text("{}")
    monkeypatch.setattr(P, "OUT", frozen)
    with pytest.raises(SystemExit):
        P.main()
    monkeypatch.setattr(P, "OUT", tmp_path / "new.json")
    monkeypatch.setattr(P, "RESULTS", tmp_path)  # no Phase 1-2 calls here
    with pytest.raises(SystemExit, match="missing"):
        P.main()
    assert not (tmp_path / "new.json").exists()
