"""analysis/designs.py: the designs scoreboard on a synthetic grid, offline."""

import numpy as np
import pandas as pd
import pytest

from analysis.designs import PLANNED, main, scoreboard, to_markdown
from tests_helpers_grid import grid_landscape


def proposer_agents(tasks, rng, p_correct=0.5) -> pd.DataFrame:
    """Six proposers per task answering "42" (the gold) or a wrong number."""
    rows = []
    for task in tasks:
        for i in range(6):
            right = rng.random() < p_correct
            rows.append({"task_id": task, "stage": "propose", "agent_id": f"propose.{i}", "answer": "42" if right else str(i),
                         "grader": "exact", "correct": float(right), "cost_usd": 0.001, "replicate": 0})
    return pd.DataFrame(rows)


def test_scoreboard_rows_and_pairing():
    L = grid_landscape(n_tasks=40)
    search, held = L.tasks[:20], L.tasks[20:]
    agents = proposer_agents(L.tasks, np.random.default_rng(0))
    single = pd.DataFrame({"correct": 0.0, "cost_usd": 0.0003}, index=held)  # always wrong
    table = scoreboard(L, search, held, agents, single=single).set_index("design")
    assert list(table.index) == [d for d, _, _ in PLANNED]
    assert table.loc["judge_cascade", "status"] == "not run" and table.loc["single Sonnet (senior control)", "status"] == "not run"
    assert table.loc["dense 6-6-6-1", "vs_dense_points"] == 0.0 and table.loc["dense 6-6-6-1", "n"] == 20
    dense_acc = L.correct.loc["k6-6-6-1", held].mean()
    assert table.loc["single Haiku", "vs_dense_points"] == pytest.approx(-100 * dense_acc)
    assert table.loc["vote6", "cost_usd"] == pytest.approx(0.006)  # six proposer calls, always exits
    gated = table.loc["gated_3x6"]
    assert 0.006 <= gated["cost_usd"] <= 0.006 + L.cost.loc["k6-6-6-1", held].mean()
    for _, row in table[table["status"] != "not run"].iterrows():
        assert row["error_lo"] <= row["error"] <= row["error_hi"]
    assert "| judge_cascade |" in to_markdown(table.reset_index(), "note")
    # amendment 4: one pre-chosen design per trigger; rule 24 = within 3 points of dense at <= half its cost
    assert (table["role"] != "descriptive").sum() == 3 and table.loc["best consensus policy", "role"] == "trigger: H5"
    assert table.loc["dense 6-6-6-1", "meets_rule_24"] is False  # full dense cost
    assert table.loc["single Haiku", "meets_rule_24"] is False  # cheap but always wrong
    assert table.loc["judge_cascade", "meets_rule_24"] is None  # not run


def test_scoreboard_without_p4_data_lists_the_plan(tmp_path):
    out = tmp_path / "designs.md"
    table = main([], [], results_dir=tmp_path, out=out)
    assert (table["status"] == "not run").all() and "No P4 data yet" in out.read_text()
