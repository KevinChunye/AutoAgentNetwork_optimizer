"""Offline test for analysis/paper_diagrams.py: the walkthrough figures' charts and HTML panels build from a numbers
dict and small synthetic tables. No model call, no repository results and no browser (printing to PDF needs Chromium
and is checked only when the figures are rebuilt)."""
import pandas as pd

from analysis import paper_diagrams as D
from tests.test_paper_figs_teams import numbers


def full_numbers():
    n = numbers()
    n.update({"lab.claude.reflectminus": 0.049, "lab.claude.reflectminus.lo": 0.0,
              "lab.claude.reflectminus.hi": 0.104, "lab.claude.reflect.usd": 0.0438,
              "lab.claude.single.usd": 0.0100, "pilot.sonnet.acc": 0.7125, "pilot.neff": 1.9,
              "phx.recoveries": 330, "phx.cases": 18})
    return n


def grid():
    rows = [("k1-1-1-1", 0.45, 0.0027, 4), ("k3-3-3-1", 0.55, 0.0060, 10), ("k3-6-3-1", 0.6125, 0.0076, 13),
            ("k6-3-1-1", 0.5375, 0.0076, 11), ("k6-6-6-1", 0.625, 0.0115, 19)]
    g = pd.DataFrame(rows, columns=["config_id", "acc", "usd", "calls"])
    return g.assign(cp=32.5, peak=8899.0, n=80)


def teams():
    def team(scale):
        idx = ["single_A", "single_B", "single_C", "vote", "all_reflect", "fixed_peer", "full_review", "policy"]
        return pd.DataFrame({"accuracy": [0.70, 0.78 * scale, 0.78, 0.80, 0.83, 0.85, 0.85, 0.82],
                             "usd_per_item": [0.001, 0.009, 0.010, 0.02, 0.044, 0.043, 0.044, 0.022]}, index=idx)
    panel = pd.Series({"accuracy": 0.868, "usd_per_item": 0.0227})
    return {"Claude": team(1.0), "GPT": team(1.1)}, panel, {"seqqa": 90, "protocolqa": 54}


def test_rounding_is_half_away_from_zero():
    assert D.r1(6.25) == "6.3" and D.r1(-6.25) == "-6.3"
    assert D.signed(-0.7) == "−0.7" and D.signed(4.9) == "+4.9"


def test_frontier_keeps_teams_nothing_beats_on_cost_and_accuracy():
    f = D.frontier(grid())
    assert list(f["config_id"]) == ["k1-1-1-1", "k3-3-3-1", "k3-6-3-1", "k6-6-6-1"]


def test_column_fractions_and_widths():
    fr = D.fr("1fr 1fr 2fr")
    assert fr == [1.0, 1.0, 2.0]
    assert D.col_width(fr, 2) > D.col_width(fr, 0) > 0


def test_walkthrough_pages_build():
    N, g = full_numbers(), grid()
    t, panel, subsets = teams()
    overview = D.html_overview(N, D.chart_overview_forest(N, 2.8))
    assert "Three ways to spend" in overview and "533 sealed questions" in overview and "<svg" in overview
    pilot = D.html_pilot(N, g, D.chart_pilot_scatter(N, g, 2.5), "<svg></svg>")
    assert "62.5%" in pilot and "5 teams of 4 to 19 calls" in pilot
    lab = D.html_lab(N, t, panel, subsets, D.chart_lab(N, t, panel, 2.6))
    assert "90 DNA-sequence" in lab and "Claude + GPT panel" in lab
    case = {p: {"pts": [(2.0, 0.61), (5.0, 0.695), (40.0, 0.7)], "usd": 0.1, "caps": {}} for p in ("fixed", "llm", "full")}
    caps = {"main_usd": 0.2, "arm_usd": 1.0, "calls": 8, "tools": 24, "cpu": 600.0}
    phx = D.html_phoenix(N, caps, D.chart_trajectory(case, 2.6), D.chart_phx_forest(N, 2.6))
    assert "$0.20" in phx and "330 recoveries" in phx and "member B lost" in phx
