"""Offline test of the W0 control-resample analysis (plan amendment 7) on synthetic results files."""

import json

import matplotlib

matplotlib.use("Agg")
import pandas as pd  # noqa: E402

from analysis import w0  # noqa: E402


def write_rows(folder, rows):
    folder.mkdir(parents=True)
    pd.DataFrame(rows).to_csv(folder / "results.csv", index=False)


def fake_results(tmp_path):
    ids = [f"bbeh-task-{i:04d}" for i in range(120)]
    gate = tmp_path / "gate.jsonl"
    gate.write_text("\n".join(json.dumps({"id": i}) for i in ids) + "\n")
    results = tmp_path / "results"
    validation = ids[20:120]
    # team right on every item; Sonnet right on even positions; Haiku right on 2 of 5 samples, draw 0 always right
    write_rows(results / "p3_bbeh_dense", [{"config_id": "k6-6-6-1", "task_id": t, "replicate": 0, "agents": 19,
                                            "correct": 1.0, "cost_usd": 0.01} for t in validation])
    write_rows(results / "p3_bbeh_single_sonnet", [{"config_id": "k1", "task_id": t, "replicate": 0, "agents": 1,
                                                    "correct": float(i % 2 == 0), "cost_usd": 0.015}
                                                   for i, t in enumerate(validation)])
    write_rows(results / "w0_haiku5", [{"task_id": t, "replicate": r, "correct": float(r in (0, 3)), "cost_usd": 0.0008,
                                        "answer": "yes" if r in (0, 3) else ("no" if r < 3 else "maybe")}
                                       for t in validation for r in range(5)])
    return results, gate


def test_w0_table_measures_team_minus_haiku5_and_the_draw(tmp_path):
    results, gate = fake_results(tmp_path)
    table = w0.w0_table(results, gate)
    held = table[table["items"] == "held-out (60-99)"].set_index("comparison")
    assert held.loc["team minus Haiku5", "n"] == 40
    assert abs(held.loc["team minus Haiku5", "diff_points"] - 60) < 1e-9  # 1 - 0.4
    assert abs(held.loc["team minus Haiku4", "diff_points"] - 75) < 1e-9  # 1 - 0.25: replicate 3 only
    assert abs(held.loc["draw 0 minus Haiku4", "diff_points"] - 75) < 1e-9
    assert abs(held.loc["team minus Haiku5", "cost_a"] - 0.01) < 1e-12 and abs(held.loc["team minus Haiku5", "cost_b"] - 0.0008) < 1e-12
    assert held.loc["team minus draw 0", "diff_points"] == 0
    assert abs(held.loc["Sonnet minus team", "diff_points"] + 50) < 1e-9
    # answers yes, no, no, yes, maybe: "no" and "yes" tie at 2, so the split vote is right half the time
    assert abs(held.loc["team minus vote5", "diff_points"] - 50) < 1e-9
    assert abs(held.loc["team minus vote5", "cost_b"] - 0.004) < 1e-12
    everything = table[table["items"] == "all (20-119)"].set_index("comparison")
    assert everything.loc["team minus Haiku5", "n"] == 100
    assert "control's draw" in w0.decision(table) and "FLAG" not in w0.decision(table)


def test_decision_flags_a_branch_that_haiku4_would_change(tmp_path):
    results, gate = fake_results(tmp_path)
    ids = [f"bbeh-task-{i:04d}" for i in range(20, 120)]
    # team right on 60% of items; draw 0 always right; replicates 1-4 right half the time (Haiku4 0.5, Haiku5 0.6)
    write = lambda name, rows: pd.DataFrame(rows).to_csv(results / name / "results.csv", index=False)
    write("p3_bbeh_dense", [{"config_id": "k", "task_id": t, "replicate": 0, "agents": 19, "correct": float(i % 5 < 3),
                             "cost_usd": 0.01} for i, t in enumerate(ids)])
    write("w0_haiku5", [{"task_id": t, "replicate": r, "correct": float(r == 0 or r % 2 == 1), "cost_usd": 0.0008,
                         "answer": "yes" if (r == 0 or r % 2 == 1) else "no"} for t in ids for r in range(5)])
    text = w0.decision(w0.w0_table(results, gate))
    assert "+0.0 points" in text and "small edge" in text
    assert "FLAG" in text and "+10.0" in text and "control's draw" in text


def test_replicate_table_and_figure(tmp_path):
    results, gate = fake_results(tmp_path)
    reps = w0.replicate_table(results, gate)
    assert len(reps) == 5 * 5
    held = reps[reps["items"] == "held-out (60-99)"].set_index("replicate")["accuracy"]
    assert held[0] == 1.0 and held[1] == 0.0
    fig = w0.figure(w0.w0_table(results, gate), reps)
    assert fig.axes[0].get_ylim() == (0, 100)
