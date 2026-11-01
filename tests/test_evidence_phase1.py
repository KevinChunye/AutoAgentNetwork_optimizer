"""The Phase 1 G2a analysis (analysis/evidence_phase1.py --block bbeh) on calls simulated from the power model,
whose truth is known: repeat correlations come back, the H1 sanity check passes when cross-vendor errors are less
tied than repeats, the cascade frontier is consistent, and the report renders every section. Offline; a reduced
bootstrap keeps it fast."""

import numpy as np
import pandas as pd
import pytest

from analysis import evidence_phase1 as P1
from analysis import evidence_power as E

ANSWERS = {0: "yes", 1: "no", 2: "maybe", 3: "unknown", 4: "both"}


def simulated_calls(n: int, r_cross: float, seed: int = 0, items=None, second=None) -> tuple[pd.DataFrame, dict]:
    """Calls of the Phase 1 panel; Sonnet's and Sol's second calls come from the same item chances as their first
    (audit 48: drawing them independently made their repeat correlation, and so H2, meaningless)."""
    rng = np.random.default_rng(seed)
    items = items if items is not None else P1.ids("bbeh_sealed")[:n]
    second = set(second if second is not None else P1.ids("bbeh_second_call"))
    calls = dict(E.CALLS)
    E.CALLS.update({"sonnet": 2, "sol": 2})
    try:
        sim = E.simulate_panel(len(items), r_cross, rng)
    finally:
        E.CALLS.clear()
        E.CALLS.update(calls)
    labels = {"haiku": "haiku_nothink:base", "luna": "luna_none:base", "sonnet": "sonnet_nothink:base", "sol": "sol61_low:base"}
    rows = []
    for s, label in labels.items():
        for i, item in enumerate(items):
            n_calls = E.CALLS[s] + (1 if s in ("sonnet", "sol") and item in second else 0)
            for c in range(n_calls):
                rows.append({"item": item, "source": label, "prompt": "base", "call": c, "parsed": True,
                             "answer": ANSWERS[int(sim[s]["A"][i, c])], "correct": float(sim[s]["Z"][i, c]),
                             "cost_usd": E.USD[s]})
    tasks = {item: ["boolean expressions", "dyck languages", "geometric shapes", "web of lies"][k % 4]
             for k, item in enumerate(items)}
    return pd.DataFrame(rows), tasks


@pytest.fixture(scope="module")
def result():
    P1.N_BOOT = 200
    calls, tasks = simulated_calls(300, r_cross=0.3)
    return P1.bbeh_analysis(calls, tasks)


def test_known_inputs_come_back(result):
    pt = result["point"]
    assert pt["rho_H"] == pytest.approx(0.48, abs=0.08) and pt["rho_L"] == pytest.approx(0.48, abs=0.08)
    assert pt["acc_H"] == pytest.approx(0.48, abs=0.06) and pt["acc_S"] == pytest.approx(0.71, abs=0.07)
    assert pt["neff_H10"] == pytest.approx(10 / (1 + 9 * pt["rho_H"]))
    assert pt["neff_H5"] < pt["neff_mix1"] < pt["neff_mix10"]  # cross-vendor calls are worth more


def test_h1_passes_when_cross_vendor_errors_are_less_tied(result):
    assert result["point"]["d_H"] > 0 and result["point"]["d_L"] > 0
    assert result["sanity"]["H1"] < 0.01
    assert result["point"]["H6"] > 0  # the whole panel's agreement carries information beyond Haiku's
    assert set(result["p"]) == {"H5", "H6", "H7"}  # the Holm family after session E2's power re-run
    assert "H4" in result["sanity"]  # H4 is reported, outside Holm


def test_cascade_frontier_is_consistent(result):
    pt = result["point"]
    esc = [pt[f"casc_esc:3H+3L, {k} of 6" + (" (H7)" if k == 4 else "")] for k in (3, 4, 5)]
    ratio = [pt[f"casc_ratio:3H+3L, {k} of 6" + (" (H7)" if k == 4 else "")] for k in (3, 4, 5)]
    assert esc == sorted(esc) and ratio == sorted(ratio)  # a stricter k escalates more and costs more
    assert pt["H7"] == pytest.approx(pt["casc_acc:3H+3L, 4 of 6 (H7)"] - pt["acc_sonnet0"])


def test_report_has_every_section_and_hypothesis(result):
    text = P1.bbeh_report(result)
    for h in ("H1", "H2", "H3", "H4", "H5", "H6", "H7"):
        assert f"| {h} |" in text
    for section in ("(1) Accuracy", "(2) Repeat", "(3) Pairs", "(4) Effective", "(5) Calibration", "(6) Cascade",
                    "(7) Hypotheses", "(8) Against the cached"):
        assert section in text


def true_latent_r(r_cross: float, n: int = 400_000) -> dict:
    """The correlation of two sources' per-item chances of being right in the power model (no call noise)."""
    from scipy.stats import norm

    z = np.random.default_rng(1).multivariate_normal(np.zeros(4), E.latent_corr(r_cross), size=n)
    chance = {s: norm.cdf(E.PARAMS[s][0] + E.PARAMS[s][1] * z[:, k]) for k, s in enumerate(E.SOURCES)}
    c = lambda a, b: np.corrcoef(chance[a], chance[b])[0, 1]
    return {"HS": c("haiku", "sonnet"), "LO": c("luna", "sol"), "HL": c("haiku", "luna"), "SO": c("sonnet", "sol")}


def test_h2_recovers_the_true_latent_r_difference():
    """Audit 48: H2 against a known answer, on 2,000 simulated items with second mid-size calls on all of them."""
    items = [f"x{i}" for i in range(2000)]
    calls, _ = simulated_calls(0, r_cross=0.6, seed=4, items=items, second=items)
    tasks = {i: "web of lies" for i in items}
    M, t = P1.bbeh_items(calls, items, tasks)
    t, _ = P1.add_cross_fits(t)
    pt = P1.bbeh_stats(M, t, np.arange(len(t)))
    truth = true_latent_r(0.6)
    assert pt["rho_S"] == pytest.approx(E.RHO["sonnet"], abs=0.06) and pt["rho_O"] == pytest.approx(E.RHO["sol"], abs=0.06)
    for pair in ("HS", "LO", "HL", "SO"):
        assert pt[f"r_{pair}"] == pytest.approx(truth[pair], abs=0.1)
    h2_true = (truth["HS"] + truth["LO"]) / 2 - (truth["HL"] + truth["SO"]) / 2
    assert pt["H2"] == pytest.approx(h2_true, abs=0.08)


def test_h2_is_undefined_not_silently_partial_when_a_repeat_correlation_is_not_positive():
    items = [f"y{i}" for i in range(200)]
    calls, _ = simulated_calls(0, r_cross=0.6, seed=5, items=items, second=items)
    sol = calls["source"] == "sol61_low:base"
    calls.loc[sol & (calls["call"] == 1), "correct"] = 1 - calls.loc[sol & (calls["call"] == 0), "correct"].to_numpy()
    M, t = P1.bbeh_items(calls, items, {i: "web of lies" for i in items})
    t, _ = P1.add_cross_fits(t)
    pt = P1.bbeh_stats(M, t, np.arange(len(t)))
    assert pt["rho_O"] < 0 and np.isnan(pt["r_LO"]) and np.isnan(pt["H2"])


def test_refused_sonnet_items_get_a_sensitivity_read():
    """Audit 51: refusals are tabulated and H5 / H7 recomputed without the items whose Sonnet call was refused."""
    calls, tasks = simulated_calls(120, 0.6, seed=4)
    refused = calls["item"].drop_duplicates().iloc[:5]
    hit = (calls["source"] == "sonnet_nothink:base") & (calls["call"] == 0) & calls["item"].isin(refused)
    calls = calls.assign(stop_reason=np.where(hit, "refusal", "end_turn"))
    calls.loc[hit, ["parsed", "correct", "answer"]] = [False, 0.0, None]
    b = P1.bbeh_analysis(calls, tasks)
    assert b["refused_items"] == 5 and b["without_refused"]["n"] == b["n"] - 5
    assert b["refused_items_by_vendor"] == {"Anthropic": 5}
    assert int(b["refusals"]["refused"].sum()) == 5
    assert "## (7b) Refusals" in P1.bbeh_report(b)
