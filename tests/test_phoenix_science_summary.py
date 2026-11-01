"""analysis/phoenix_science.py on a synthetic branches table (offline; the numbers are fixtures, not results)."""
import json
import sys

import numpy as np
import pandas as pd

from conftest import ROOT

sys.path.insert(0, str(ROOT / "analysis"))
import phoenix_science as S  # noqa: E402


def fixture(tmp_path):
    rows, manifest = [], []
    for c in range(6):
        case = f"{'covtype' if c < 3 else 'higgs'}_T1_{101 + c}"
        for experiment, policy, fault, acc in [("E1", "fixed", "F1", 0.80), ("E1", "llm", "F1", 0.81),
                                               ("E1", "full", "F1", 0.83 + 0.001 * c), ("E2", "fixed", "F0", 0.82),
                                               ("E2", "full", "F0", 0.84)]:
            name = f"{experiment}_{case}_{policy}"
            rows.append({"name": name, "case_id": case, "experiment": experiment, "policy": policy, "fault": fault,
                         "budget": 0.2, "status": "completed", "logical_api_usd": 0.01 if policy != "fixed" else 0.0,
                         "cpu_s": 10.0, "redundant_compute_cpu_s": 0.0, "planning_cost_fraction": 0.5,
                         "test_balanced_accuracy": acc})
            manifest.append({"name": name, "dataset": case.split("_")[0], "template": "T1",
                             "withdrawn_model": "sol61_low" if c % 2 else "sonnet_low"})
    (tmp_path / "report").mkdir()
    pd.DataFrame(rows).to_csv(tmp_path / "report" / "branches.csv", index=False)
    (tmp_path / "m.json").write_text(json.dumps({"branches": manifest}))
    return S.load(tmp_path / "report", tmp_path / "m.json")


def test_bootstrap_interval_and_verdicts():
    mean, lo, hi, n = S.bootstrap([1.0, 2.0, 3.0, 2.0])
    assert n == 4 and mean == 2.0 and lo >= 1.0 and hi <= 3.0
    assert S.verdict(0.1, 0.5) == "positive" and S.verdict(-0.2, 0.3) == "not resolved" and S.verdict(np.nan, 1) == "no data"


def test_paired_contrasts_and_summary(tmp_path):
    frame = fixture(tmp_path)
    rows = pd.DataFrame(S.contrast_rows(frame, "E1", "fixed", "test_points", by="dataset"))
    pooled = rows[rows.group == "all"].iloc[0]
    assert pooled.cases == 6 and pooled.verdict == "positive" and pooled.wins == 6 and abs(pooled["mean"] - 3.25) < 1e-9
    # two datasets and two withdrawn models: only the 6 real cases are counted, never empty combinations
    assert pooled.nonzero == 6 and (rows.nonzero <= rows.cases).all()
    assert set(rows.group) == {"all", "covtype", "higgs"}
    fault = S.fault_contrast(frame).set_index("policy")
    assert abs(fault.loc["fixed", "mean"] - 2.0) < 1e-9
    text = S.summary_markdown(frame)
    assert "## Paired contrasts" in text and "not evidence" in text


def test_exploration_counts_copies_and_new_pipelines(tmp_path):
    run = tmp_path / "run"
    run.mkdir()
    (run / "state.json").write_text(json.dumps({"checkpoint_operations": ["inc", "pend"]}))
    events = [{"event": "call_intent", "purpose": "design", "model": "luna_low_ev", "api_usd": 0.0},
              {"event": "design_completed", "target": "inc", "api_usd": 0.0005},          # copy of the incumbent
              {"event": "call_intent", "purpose": "design", "model": "luna_low_ev", "api_usd": 0.0005},
              {"event": "design_completed", "target": "new1", "api_usd": 0.001},
              {"event": "plan_completed", "target": "pend"}, {"event": "plan_completed", "target": "new1"}]
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    out = S.exploration(run)
    assert out["design_calls_luna_low_ev"] == 2 and out["copied_designs"] == 1
    assert abs(out["copied_design_usd"] - 0.0005) < 1e-12 and out["new_pipelines_completed"] == 1
    assert not any(k.startswith("refused_calls_") for k in out)
    calls = [{"model_ref": "opus_med", "output": {"stop_reason": "refusal"}},
             {"model_ref": "opus_med", "output": {"stop_reason": "end_turn"}}]
    (run / "calls.jsonl").write_text("".join(json.dumps(c) + "\n" for c in calls))
    assert S.exploration(run)["refused_calls_opus_med"] == 1


def test_family_arm_draws_and_contrasts(tmp_path):
    """Two draws per case are averaged within a method; arm - main pairs by case; draw noise is reported."""
    rows, manifest = [], []
    for c in range(4):
        case = f"covtype_T1_{101 + c}"
        specs = [("E1", "full", 0, 0.80), ("E1", "fixed", 0, 0.80)]
        specs += [("fam_x", "full", 1, 0.82), ("fam_x", "full", 2, 0.84 if c == 0 else 0.82),
                  ("fam_x", "fixed", 1, 0.80), ("fam_x", "fixed", 2, 0.80)]
        for experiment, policy, draw, acc in specs:
            name = f"{experiment}_{case}_{policy}_d{draw}"
            rows.append({"name": name, "case_id": case, "experiment": experiment, "policy": policy, "fault": "F1",
                         "budget": 1.0, "status": "no_positive_feasible_plan", "calls": 8 if policy == "fixed" else 3,
                         "logical_api_usd": 0.1, "test_balanced_accuracy": acc})
            manifest.append({"name": name, "dataset": "covtype", "template": "T1", "withdrawn_model": "haiku_low",
                             "draw": draw})
    (tmp_path / "report").mkdir()
    pd.DataFrame(rows).to_csv(tmp_path / "report" / "branches.csv", index=False)
    (tmp_path / "m.json").write_text(json.dumps({"branches": manifest}))
    frame = S.load(tmp_path / "report", [tmp_path / "m.json"])
    contrast = pd.DataFrame(S.contrast_rows(frame, "fam_x", "fixed", "test_points"))
    assert np.isclose(contrast.loc[0, "mean"], (3.0 + 2.0 * 3) / 4)        # case 0: mean of 4 and 2 points
    assert contrast.loc[0, "nonzero"] == 4 and np.isclose(contrast.loc[0, "largest_case_share"], 3 / 9)
    versus = S.arm_vs_main(frame, "fam_x", policies=("full",))
    assert np.isclose(versus.loc[0, "mean"], 2.25) and versus.loc[0, "cases"] == 4
    noise = S.draw_noise(frame, "fam_x").set_index("policy")
    assert noise.loc["full", "cases_that_differ"] == 1 and noise.loc["fixed", "cases_that_differ"] == 0
    assert (S.reported_status(frame)[frame.policy == "fixed"] == "call limit reached").all()


def test_model_new_pipelines_counts_only_what_the_model_brought_in(tmp_path):
    """Audit SC-13 (P7): a completed pipeline counts if a model proposed it with REROUTE/SPLIT or a model's design that
    copied nothing produced it; finishing pending work (RECOMPUTE of the checkpoint's pending target) does not."""
    run = tmp_path / "run"
    run.mkdir()
    (run / "state.json").write_text(json.dumps({"checkpoint_operations": ["inc", "pend"]}))
    events = [{"event": "proposal", "plan_id": "p1", "plan": {"action": "RECOMPUTE", "target": "pend"}},
              {"event": "plan_selected", "plan_id": "p1", "target": "pend"}, {"event": "plan_completed", "target": "pend"},
              {"event": "proposal", "plan_id": "p2", "plan": {"action": "REROUTE", "target": "new_a"}},
              {"event": "plan_selected", "plan_id": "p2", "target": "new_a"}, {"event": "plan_completed", "target": "new_a"},
              {"event": "call_intent", "purpose": "design", "model": "opus_med", "api_usd": 0.0},
              {"event": "design_completed", "target": "new_b", "api_usd": 0.01},
              {"event": "plan_completed", "target": "new_b"},
              {"event": "call_intent", "purpose": "design", "model": "haiku_low", "api_usd": 0.01},
              {"event": "design_completed", "target": "inc", "api_usd": 0.011}]          # a copy: not counted
    (run / "events.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))
    out = S.exploration(run)
    assert out["model_new_pipelines"] == 2 and out["copied_designs"] == 1 and out["ran_model_pipeline"] == 1


def test_arm_vs_arm_pairs_by_case_over_draw_means():
    rows = []
    for c in range(3):
        for arm, base in (("fam_a", 0.80), ("fam_b", 0.78)):
            for draw in (1, 2):
                rows.append({"name": f"{arm}_{c}_{draw}", "case_id": f"c{c}", "experiment": arm, "policy": "full",
                             "draw": draw, "test_points": 100 * (base + 0.01 * (draw - 1)), "logical_api_usd": 0.1})
    out = S.arm_vs_arm(pd.DataFrame(rows), "fam_a", "fam_b", policies=("full",))
    assert out.loc[0, "cases"] == 3 and np.isclose(out.loc[0, "mean"], 2.0)


def test_load_counts_calls_from_state_when_the_report_has_none(tmp_path):
    """Audit SC-14: branches.csv has no calls column, so load() reads each branch's state.json; with 8 calls a fixed
    branch is reported as "call limit reached" (Amendment 7 item 1); a branch that never ran gets no count."""
    rows, manifest = [], []
    for name, policy, calls in (("b_fixed", "fixed", 8), ("b_full", "full", 3), ("b_none", "llm", None)):
        run = tmp_path / name
        run.mkdir()
        if calls is not None:
            (run / "state.json").write_text(json.dumps({"calls": [{}] * calls}))
        rows.append({"name": name, "case_id": "c1", "experiment": "fam_x", "policy": policy, "fault": "F1",
                     "budget": 1.0, "status": "no_positive_feasible_plan", "test_balanced_accuracy": 0.8})
        manifest.append({"name": name, "dataset": "covtype", "template": "T1", "withdrawn_model": "haiku_low",
                         "draw": 1, "frozen": str(run / "frozen.json")})
    (tmp_path / "report").mkdir()
    pd.DataFrame(rows).to_csv(tmp_path / "report" / "branches.csv", index=False)
    (tmp_path / "m.json").write_text(json.dumps({"branches": manifest}))
    frame = S.load(tmp_path / "report", tmp_path / "m.json").set_index("name")
    assert frame.loc["b_fixed", "calls"] == 8 and frame.loc["b_full", "calls"] == 3
    assert pd.isna(frame.loc["b_none", "calls"])
    assert S.reported_status(frame.reset_index()).tolist() == ["call limit reached", "no_positive_feasible_plan",
                                                               "no_positive_feasible_plan"]
