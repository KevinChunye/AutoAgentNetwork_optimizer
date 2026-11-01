"""Offline tests of the analysis scripts on synthetic landscapes and on a fake-model dry run."""

import asyncio
import itertools

import numpy as np
import pandas as pd
import pytest

import analysis.common as common
from analysis import gate, landscape, search
from autoagentnet.experiment import ExperimentConfig, run_experiment
from conftest import ROOT


def synthetic_rows(n_tasks: int = 40, prefix: str = "t") -> pd.DataFrame:
    """A 216-config landscape with a known structure: accuracy rises with the propose stage
    (6 points per agent) and a little with refine; critique does nothing but cost."""
    u = (np.arange(n_tasks) + 0.5) / n_tasks  # task difficulty, shared by all configs
    rows = []
    for k1, k2, k3 in itertools.product(range(1, 7), repeat=3):
        p = 0.3 + 0.06 * (k1 - 1) + 0.01 * (k3 - 1)
        for t in range(n_tasks):
            rows.append({"config_id": f"k{k1}-{k2}-{k3}-1", "task_id": f"{prefix}{t:02d}", "replicate": 0,
                         "agents": k1 + k2 + k3 + 1, "correct": float(u[t] < p), "parsed": 1.0,
                         "calls": k1 + k2 + k3 + 1, "truncated_calls": 0,
                         "cost_usd": 1e-4 * (k1 + 1.5 * k2 + k3 + 1), "total_tokens": 1000 * (k1 + k2 + k3 + 1),
                         "input_tokens": 100, "cache_write_tokens": 500, "cache_read_tokens": 300, "output_tokens": 400})
    df = pd.DataFrame(rows)
    dense = df[df["config_id"] == "k6-6-6-1"].set_index("task_id")["correct"]
    df["agrees_with_dense"] = (df["correct"] == df["task_id"].map(dense)).astype(float)
    return df


@pytest.fixture
def folders(tmp_path):
    rows = synthetic_rows()
    tasks = sorted(rows["task_id"].unique())
    a, b = tmp_path / "land_a", tmp_path / "land_b"
    for folder, half in [(a, tasks[0::2]), (b, tasks[1::2])]:
        folder.mkdir()
        rows[rows["task_id"].isin(half)].to_csv(folder / "results.csv", index=False)
    return [a, b]


def test_landscape_basics(folders):
    L = landscape.load_landscape(folders)
    assert len(L.configs) == 216 and L.dense_id == "k6-6-6-1" and len(L.tasks) == 40
    s = landscape.summarize(L)
    front = landscape.pareto_front(s)
    assert front["cost_usd"].is_monotonic_increasing and front["error"].is_monotonic_decreasing
    assert set(front["k_critique"]) == {1}  # critique only adds cost, so the frontier never keeps more
    inter = landscape.interaction(s, len(L.tasks))
    assert inter["residual_share"] < 0.1  # the synthetic landscape is (nearly) additive
    assert inter["main_effect_range"]["propose"] > inter["main_effect_range"]["critique"] == 0


def test_sensitivity_and_search_methods(folders):
    L = landscape.load_landscape(folders)
    s = landscape.summarize(L)
    r = landscape.reward(s, L.dense_id, lam=0.05)
    pick, evaluated = landscape.sensitivity_pick(s, r)
    assert landscape.keep_of(pick)[1] == 1 and len(evaluated) <= 17
    assert search.greedy_order(s, r, L.dense_id)[0] == L.dense_id
    order = search.reinforce_order(r, np.random.default_rng(0), episodes=300)
    assert len(order) == len(set(order)) and set(order) <= set(r.index)
    curves = search.regret_curves(L, L.tasks, L.tasks, seeds=5)
    exhaustive = curves[curves["method"] == "exhaustive"]["regret"].iloc[0]
    assert exhaustive == pytest.approx(0)  # same tasks for search and scoring: exhaustive finds the best
    last_random = curves[curves["method"] == "random"].sort_values("evaluations").iloc[-1]
    assert last_random["evaluations"] == 216 and last_random["regret"] == pytest.approx(0)
    assert (curves["regret"] >= -1e-12).all()


def test_landscape_main_writes_tables_and_figures(folders, tmp_path, monkeypatch):
    monkeypatch.setattr(common, "FIGURES", tmp_path / "fig")
    monkeypatch.setattr(common, "TABLES", tmp_path / "tab")
    summary = landscape.main([str(folders[0])], [str(folders[1])])
    assert summary["n_search"] == summary["n_held"] == 20
    for name in ["b_landscape", "c_interactions", "d_regret", "e_cost_breakdown"]:
        assert (tmp_path / "fig" / f"{name}.pdf").exists() and (tmp_path / "fig" / f"{name}.png").exists()
    picks = pd.read_csv(tmp_path / "tab" / "p4_picks.csv")
    assert {"dense", "stage-by-stage sensitivity", "joint (exhaustive, labeled)"} <= set(picks["method"])


def test_gate_table_pairs_tasks(tmp_path, monkeypatch):
    rows = synthetic_rows(n_tasks=20)
    results = tmp_path / "results"
    for name, config in [("p2_x_single", "k1-1-1-1"), ("p2_x_dense", "k6-6-6-1")]:
        (results / name).mkdir(parents=True)
        rows[rows["config_id"] == config].to_csv(results / name / "results.csv", index=False)
    pairs = gate.find_pairs("p2", results)
    table = gate.gate_table(pairs)
    row = table.iloc[0]
    assert row["candidate"] == "x" and row["n"] == 20
    assert row["single_acc"] == pytest.approx(0.3) and row["dense_acc"] == pytest.approx(0.65)
    assert row["gap"] == pytest.approx(0.35) and row["gap_lo"] <= row["gap"] <= row["gap_hi"]
    assert row["dense_only_right"] == 7 and row["single_only_right"] == 0 and row["passes"]


def test_agreement_and_vote_baseline_on_a_fake_dry_run(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml").model_copy(
        update={"out_dir": str(tmp_path), "configs": [], "task_limit": 4})
    asyncio.run(run_experiment(cfg))
    agents_csv = tmp_path / "smoke" / "agents.csv"
    agreement = landscape.within_stage_agreement(agents_csv)
    assert list(agreement.index) == ["propose", "critique", "refine", "aggregate"]
    multi = agreement.drop(index="aggregate")  # one agent: no pairs to agree
    assert multi["pairwise_agreement"].between(0, 1).all() and multi["pairwise_agreement"].min() < 1
    vote = landscape.propose_vote_baseline(agents_csv)
    assert list(vote["k"]) == [1, 2, 3, 4, 5, 6] and vote["cost_usd"].is_monotonic_increasing
    check = gate.voting_check(agents_csv, ["t01", "t02", "t03", "t04"])
    assert set(check) == {"propose_mean_acc", "vote6_acc", "vote6_tiesplit_acc", "pass6", "vote_gain"} and 0 <= check["pass6"] <= 1
    dense = pd.Series({"t01": 1.0, "t02": 1.0, "t03": 0.0, "t04": 1.0})
    check = gate.voting_check(agents_csv, ["t01", "t02", "t03", "t04"], dense)
    assert check["dense_minus_vote6"] == pytest.approx(0.75 - check["vote6_acc"])
    assert check["dense_minus_vote6_lo"] <= check["dense_minus_vote6"] <= check["dense_minus_vote6_hi"]


def test_answer_classes_use_the_grader():
    assert landscape.answer_classes(["\\frac{1}{2}", "0.5", "1/2", "2", None], "math") == [[0, 1, 2], [3], [4]]
    assert landscape.answer_classes(["(B)", "b", "C"], "choice") == [[0, 1], [2]]


def test_budget_tables_match_ledger_to_estimates(tmp_path, monkeypatch):
    from analysis import budget
    from autoagentnet.budget import BudgetRules, Phase
    from autoagentnet.meter import CallRecord, Ledger

    ledger = Ledger()
    for run_id, cost in [("p2_omni_dense-100", 0.30), ("p2_omni_dense-100", 0.20), ("p0_calib_haiku-50", 0.01)]:
        ledger.record(CallRecord(run_id=run_id, account="anthropic", provider="anthropic", model="claude-haiku-5-5",
                                 input_tokens=1, cache_write_tokens=0, cache_read_tokens=0, output_tokens=1,
                                 cost_usd=cost, latency_s=1.0))
    est = tmp_path / "estimates.csv"
    pd.DataFrame([
        {"account": "anthropic", "model": "claude-haiku-5-5", "calls": 10, "worst_case_usd": 0.5, "worst_case_x_safety": 0.575,
         "date": "2026-10-18 01:00", "experiment": "p2_omni_dense"},
        {"account": "anthropic", "model": "claude-haiku-5-5", "calls": 10, "worst_case_usd": 0.8, "worst_case_x_safety": 0.92,
         "date": "2026-10-18 02:00", "experiment": "p2_omni_dense"},
        {"account": "fake", "model": "fake-model", "calls": 10, "worst_case_usd": 0, "worst_case_x_safety": 0,
         "date": "2026-10-18 03:00", "experiment": "p2_omni_dense"},
    ]).to_csv(est, index=False)
    rules = BudgetRules(hard_caps_usd={"anthropic": 100, "openai": 100}, phase="pilot",
                        phases={"pilot": Phase(total_usd=20, max_run_usd=4)})
    tables = budget.budget_tables(ledger, est, rules)
    run = tables["by_run"].set_index("experiment").loc["p2_omni_dense"]
    assert run["actual_usd"] == pytest.approx(0.5) and run["estimate_usd"] == pytest.approx(0.92)
    step = tables["by_step"].set_index("step")
    assert step.loc["p2", "actual_usd"] == pytest.approx(0.5) and step.loc["p0", "actual_usd"] == pytest.approx(0.01)
    assert tables["by_account"].set_index("account").loc["anthropic", "spent_usd"] == pytest.approx(0.51)
    monkeypatch.setattr(common, "FIGURES", tmp_path / "fig")
    common.save_figure(budget.plot_burn(tables["by_step"], 20, 1.15), "f")
    assert (tmp_path / "fig" / "f.pdf").exists()


def test_calibration_table_from_ledger(tmp_path):
    from analysis.calibration import calibration_table
    from autoagentnet.meter import CallRecord, Ledger

    ledger = Ledger()
    for i, (stop, out) in enumerate([("end_turn", 300), ("max_tokens", 800), ("end_turn", 100)]):
        ledger.record(CallRecord(run_id="p0_calib_haiku-1", account="anthropic", provider="anthropic",
                                 model="claude-haiku-5-5", input_tokens=130, cache_write_tokens=0, cache_read_tokens=0,
                                 output_tokens=out, cost_usd=0.0001, latency_s=2.0 + i, stop_reason=stop,
                                 estimated_prompt_tokens=100))
    (tmp_path / "p0_calib_haiku").mkdir()
    pd.DataFrame({"replicate": [0, 0, 0], "visible_output_tokens": [100, 0, 100], "answer": ["1", None, "3"],
                  "output_tokens": [300, 800, 100], "stop_reason": ["end_turn", "max_tokens", "end_turn"]}).to_csv(
        tmp_path / "p0_calib_haiku" / "agents.csv", index=False)
    row = calibration_table(ledger, tmp_path).iloc[0]
    assert row["calls"] == 3 and row["prompt_ratio"] == pytest.approx(1.3) and row["prompt_ratio_rule17"] == pytest.approx(1.3 / 0.75)
    assert row["truncated_share"] == pytest.approx(1 / 3) and row["hidden_ratio"] == pytest.approx(1200 / 3 / (200 / 3))
    # audit 5: the per-call ratio over finished calls is not inflated by the cut-off call with nothing visible
    assert row["hidden_ratio_completed_min"] == pytest.approx(1.0) and row["hidden_ratio_completed_max"] == pytest.approx(3.0)
    assert "max_tokens:1" in row["stop_reasons"]


def test_p3_gate_is_judged_on_fresh_validation_items_only(tmp_path, monkeypatch):
    # audit 1, finding 4: P3 runs positions 0-59, but 0-19 chose the candidate;
    # audit 3, finding 2: P3w (100-119) never touches the P4 held-out half (60-99)
    import json as _json

    monkeypatch.setattr(common, "FIGURES", tmp_path / "fig")
    monkeypatch.setattr(common, "TABLES", tmp_path / "tab")
    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text("".join(_json.dumps({"id": f"t{i:02d}", "prompt": "p", "answer": "1"}) + "\n" for i in range(120)))
    configs, results = tmp_path / "configs", tmp_path / "results"
    configs.mkdir()
    (configs / "p3_x_dense.yaml").write_text(f"tasks: {task_file}\n")
    rows = synthetic_rows(n_tasks=120)
    for name, config, ids in [("p3_x_single", "k1-1-1-1", range(60)), ("p3_x_dense", "k6-6-6-1", range(60)),
                              ("p3_x_single_sonnet", "k3-3-3-1", range(20, 60)),
                              ("p3w_x_single", "k1-1-1-1", range(100, 120)), ("p3w_x_dense", "k6-6-6-1", range(100, 120))]:
        part = rows[(rows["config_id"] == config) & rows["task_id"].isin([f"t{i:02d}" for i in ids])]
        (results / name).mkdir(parents=True)
        part.to_csv(results / name / "results.csv", index=False)
    table = gate.main("p3", results_dir=results, configs_dir=configs)
    row = table.iloc[0]
    assert row["n"] == 60 and row["judged_positions"] == "20-59,100-119"
    assert row["sonnet_n"] == 40 and row["dense_minus_sonnet_lo"] <= row["dense_minus_sonnet"] <= row["dense_minus_sonnet_hi"]
    assert "futile" in table.columns and not row["futile"]  # the synthetic gap is large
    for name in ["p3w_x_single", "p3w_x_dense"]:
        (results / name / "results.csv").unlink()
        (results / name).rmdir()
    table = gate.main("p3", results_dir=results, configs_dir=configs)
    assert table.iloc[0]["n"] == 40 and table.iloc[0]["judged_positions"] == "20-59"


def test_controls_have_intervals_and_baselines(folders, tmp_path, monkeypatch):
    # audit 1, finding 8: H4 needs a CI; P4 needs single-agent and vote baselines and budgeted picks
    monkeypatch.setattr(common, "FIGURES", tmp_path / "fig")
    monkeypatch.setattr(common, "TABLES", tmp_path / "tab")
    single_dir = tmp_path / "p3_x_single"
    single_dir.mkdir()
    rows = synthetic_rows()
    rows[rows["config_id"] == "k1-1-1-1"].to_csv(single_dir / "results.csv", index=False)
    landscape.main([str(folders[0])], [str(folders[1])], single_results=[str(single_dir / "results.csv")])
    control = pd.read_csv(tmp_path / "tab" / "p4_random_control.csv")
    assert {"advantage", "advantage_lo", "advantage_hi"} <= set(control.columns)
    assert (control["advantage_lo"] <= control["advantage"]).all() and (control["advantage"] <= control["advantage_hi"]).all()
    picks = pd.read_csv(tmp_path / "tab" / "p4_picks.csv")
    assert "budgeted, <= 50% of dense cost" in set(picks["method"])
    budgeted = picks.set_index("method").loc["budgeted, <= 50% of dense cost", "cost_compression"]
    assert budgeted >= 1.9  # held-out cost tracks search cost in the synthetic landscape
    baselines = pd.read_csv(tmp_path / "tab" / "p4_baselines.csv")
    single = baselines.set_index("baseline").loc["single agent"]
    assert single["n"] == 20 and single["minus_dense_acc"] < 0  # 1-1-1-1 is the weakest synthetic config


def test_gate_reports_accuracy_by_source(tmp_path, monkeypatch):
    import json as _json

    monkeypatch.setattr(common, "FIGURES", tmp_path / "fig")
    monkeypatch.setattr(common, "TABLES", tmp_path / "tab")
    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text("".join(_json.dumps({"id": f"t{i:02d}", "prompt": "p", "answer": "1",
                                              "meta": {"source": "HMMT_2" if i % 2 else "imo"}}) + "\n" for i in range(20)))
    configs, results = tmp_path / "configs", tmp_path / "results"
    configs.mkdir()
    (configs / "p2_x_dense.yaml").write_text(f"tasks: {task_file}\n")
    rows = synthetic_rows(n_tasks=20)
    for name, config in [("p2_x_single", "k1-1-1-1"), ("p2_x_dense", "k6-6-6-1")]:
        (results / name).mkdir(parents=True)
        rows[rows["config_id"] == config].to_csv(results / name / "results.csv", index=False)
    gate.main("p2", results_dir=results, configs_dir=configs)
    table = pd.read_csv(tmp_path / "tab" / "gate_p2_by_source.csv").set_index("group")
    assert table.loc["HMMT", "n"] == 10 and table.loc["other", "n"] == 10


def test_p4_halves_follow_configured_parts(tmp_path):
    from analysis.build_report import p4_halves

    results, configs = tmp_path / "results", tmp_path / "configs"
    configs.mkdir()
    for part in "abcdefgh":  # v2: eight factorial grid parts
        (configs / f"p4_x_grid_{part}.yaml").write_text("")
    for part in "abcde":  # P4 partly done: four search parts and one held-out part
        (results / f"p4_x_grid_{part}").mkdir(parents=True)
    search, held = p4_halves(results, configs)
    assert [d.name[-1] for d in search] == ["a", "b", "c", "d"] and [d.name[-1] for d in held] == ["e"]


def test_search_methods_on_the_factorial_grid():
    # protocol v2, section 5.11: greedy and REINFORCE step between evaluated levels (1/3/6)
    from tests_helpers_grid import grid_landscape

    L = grid_landscape()
    s = landscape.summarize(L)
    r = landscape.reward(s, L.dense_id, lam=0.05)
    assert search.stage_levels(r.index) == [[1, 3, 6]] * 3
    order = search.greedy_order(s, r, L.dense_id)
    assert order[0] == "k6-6-6-1" and {"k3-6-6-1", "k6-3-6-1", "k6-6-3-1"} <= set(order)  # 6 -> 3, never 6 -> 5
    assert all(c in r.index for c in order)
    sampled = search.reinforce_order(r, np.random.default_rng(0), episodes=300)
    assert set(sampled) <= set(r.index) and len(sampled) == len(set(sampled))
    curves = search.regret_curves(L, L.tasks, L.tasks, seeds=5)
    assert curves[curves["method"] == "exhaustive"]["evaluations"].iloc[0] == 27
    assert curves[curves["method"] == "exhaustive"]["regret"].iloc[0] == pytest.approx(0)


def test_futility_fires_when_dense_does_not_beat_single(tmp_path):
    # audit 4, finding 6: the futile=True path (rule 19: upper 95% CI of dense minus single below +5)
    rows = synthetic_rows(n_tasks=20)
    single = rows[rows["config_id"] == "k1-1-1-1"]
    dense = single.assign(config_id="k6-6-6-1", agents=19)  # same answers: a gap of exactly 0
    for name, part in [("single", single), ("dense", dense)]:
        (tmp_path / name).mkdir()
        part.to_csv(tmp_path / name / "results.csv", index=False)
    row = gate.gate_row("x", tmp_path / "single" / "results.csv", tmp_path / "dense" / "results.csv")
    assert row["gap"] == 0 and row["gap_hi"] < 0.05 and row["futile"] and not row["passes"]


def test_gate_reports_accuracy_by_recall_cue(tmp_path):
    # plan amendment 6, rule 41: single calls and dense proposers split by recall_cue (descriptive)
    singles, denses = tmp_path / "single", tmp_path / "dense"
    singles.mkdir()
    denses.mkdir()
    ids = [f"t{i}" for i in range(4)]
    pd.DataFrame({"task_id": ids, "replicate": 0, "stage": "solve", "correct": [1.0, 1.0, 0.0, 0.0],
                  "recall_cue": [0.0, 0.0, 1.0, 0.0]}).to_csv(singles / "agents.csv", index=False)
    pd.DataFrame({"task_id": ids * 2, "replicate": 0, "stage": ["propose"] * 4 + ["critique"] * 4,
                  "correct": [1.0, 0.0, 1.0, 1.0] * 2, "recall_cue": [0.0, 1.0, 0.0, 0.0] * 2}
                 ).to_csv(denses / "agents.csv", index=False)
    table = gate.by_recall("x", singles / "results.csv", denses / "results.csv", ids).set_index(["system", "recall_cue"])
    assert table.loc[("single", 1.0), "calls"] == 1 and table.loc[("single", 0.0), "accuracy"] == pytest.approx(2 / 3)
    assert table.loc[("dense proposers", 1.0), "accuracy"] == 0 and table["calls"].sum() == 8  # critiques left out


def test_blind_hand_grade_sheet_and_unblind(tmp_path):
    # plan amendment 6, rule 46: blind sheet with the arm hidden; hand grades change the gate numbers
    import json as _json

    from analysis import hand_grade

    ids = [f"t{i:02d}" for i in range(20)]
    gold = {t: ("f(x) = \\frac{1}{x + a}" if t == "t00" else "5") for t in ids}
    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text("".join(_json.dumps({"id": t, "prompt": "p", "answer": gold[t]}) + "\n" for t in ids))
    configs, results, out = tmp_path / "configs", tmp_path / "results", tmp_path / "hand"
    configs.mkdir()
    (configs / "p2_x_dense.yaml").write_text(f"tasks: {task_file}\n")
    for arm, agents in [("single", 1), ("dense", 19)]:
        (results / f"p2_x_{arm}").mkdir(parents=True)
        right = 0.0 if arm == "single" else 1.0
        pd.DataFrame({"config_id": "k", "task_id": ids, "replicate": 0, "agents": agents,
                      "answer": ["f(x) = 1/(x+c)"] + ["5"] * 19, "parsed": [0.0] + [1.0] * 19,
                      "correct": [0.0] + [right] + [1.0] * 18}).to_csv(results / f"p2_x_{arm}" / "results.csv", index=False)
    prop = pd.DataFrame([{"task_id": t, "replicate": 0, "stage": "propose", "agent_id": f"propose.{k}", "grader": "math",
                          "answer": ("1/(x+c)" if k < 3 else "1/(x+k)") if t == "t00" else "5",
                          "correct": 0.0 if t == "t00" else 1.0} for t in ids for k in range(6)])
    prop.to_csv(results / "p2_x_dense" / "agents.csv", index=False)
    sheet = hand_grade.make_sheet("p2", "x", gold, results, configs, out)
    assert not (out / "p2_x_vote.csv").exists()  # the vote sheet comes after the blind sheet (audit 11)
    assert set(sheet.columns) == {"item", "task_id", "gold", "answer", "hand_correct"}  # no arm column
    assert len(sheet) == 2 and set(sheet["task_id"]) == {"t00"}  # both arms' unparsed answer on t00
    sheet["hand_correct"] = 1  # the renamed parameter is right by hand
    sheet.to_csv(out / "p2_x_sheet.csv", index=False)
    vote = hand_grade.make_vote_sheet("p2", "x", gold, results, configs, out)
    assert list(vote["hand_group"]) == ["A"] * 3 + ["B"] * 3  # prefilled with the automatic classes
    vote["hand_group"], vote["hand_correct"] = "A", 1  # all six are one answer up to the parameter name
    vote.to_csv(out / "p2_x_vote.csv", index=False)
    table = hand_grade.unblind("p2", "x", results, configs, out).set_index("grade")
    assert table.loc["automatic", "single_acc"] == pytest.approx(18 / 20)
    assert table.loc["hand", "single_acc"] == pytest.approx(19 / 20) and table.loc["hand", "dense_acc"] == 1
    assert table.loc["automatic", "vote6_acc"] == pytest.approx(19 / 20) and table.loc["hand", "vote6_acc"] == 1


def test_hand_vote_groups_and_grades():
    # audit 11: prefilled automatic classes keep "2^k" and "2^{k}" together; any member's hand grade counts
    from analysis.hand_grade import hand_vote

    vote = pd.DataFrame({"task_id": "t", "agent_id": [f"propose.{k}" for k in range(6)],
                         "answer": ["7", "2^k", "7", "2^{k}", "2^k", "2^{k}"], "correct": [0, 1, 0, 1, 1, 1],
                         "hand_group": ["A", "B", "A", "B", "B", "B"], "hand_correct": ["", "", "", "", "", ""]})
    assert hand_vote(vote)["t"] == 1
    vote["correct"] = 0
    vote["hand_correct"] = ["", "", "", "", "1", ""]  # graded on a later member only
    assert hand_vote(vote)["t"] == 1
    vote["hand_group"] = ["A", "B", "A", "C", "B", "C"]  # a 2-2-2 tie goes to the earliest agent's group
    assert hand_vote(vote)["t"] == 0


def test_wrong_answers_on_symbolic_golds_are_read_by_hand():
    from analysis.hand_grade import needs_hand

    assert needs_hand("(2n-1)!!", "t") and needs_hand("n = 2, 5, 13", "t") and needs_hand("\\frac{1}{12}", "t")
    assert needs_hand("5", "omni-4259")  # a free-parameter item
    assert not needs_hand("940", "t") and not needs_hand("-3.5", "t")


def test_bbeh_band_rule():
    # plan amendment 6, rule 48: eligibility, truncation, computational first, closest to 0.40, at most 4
    from analysis.banding import bbeh_band

    spec = {"word sorting": (10, 4, 0), "boolean expressions": (10, 5, 0), "dyck languages": (10, 3, 1),
            "causal understanding": (10, 4, 0), "nycc": (3, 1, 0), "time arithmetic": (10, 9, 0),
            "web of lies": (8, 2, 0), "multistep arithmetic": (10, 6, 0), "geometric shapes": (10, 4, 0)}
    rows, calls, task_of = [], [], {}
    for task, (n, right, cut) in spec.items():
        for i in range(n):
            tid = f"{task}-{i}"
            task_of[tid] = task
            rows.append({"task_id": tid, "correct": float(i < right)})
            calls.append({"task_id": tid, "stop_reason": "max_tokens" if i >= n - cut else "end_turn"})
    table, pooled = bbeh_band(pd.DataFrame(rows), pd.DataFrame(calls), task_of)
    kept = set(table.index[table["kept"]])
    assert kept == {"word sorting", "geometric shapes", "boolean expressions", "web of lies"}
    assert not table.loc["dyck languages", "eligible"]  # a truncated item: not kept
    assert not table.loc["nycc", "eligible"] and not table.loc["time arithmetic", "in_band"]
    assert pooled == pytest.approx((4 + 4 + 5 + 2) / 38)


def test_gate_reports_accuracy_by_task_family(tmp_path, monkeypatch):
    # plan amendment 6, rule 55: per-task single, dense and vote6 accuracy (descriptive)
    import json as _json

    monkeypatch.setattr(common, "FIGURES", tmp_path / "fig")
    monkeypatch.setattr(common, "TABLES", tmp_path / "tab")
    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text("".join(_json.dumps({"id": f"t{i:02d}", "prompt": "p", "answer": "1",
                                              "meta": {"task": "boolean" if i < 8 else "dyck"}}) + "\n" for i in range(20)))
    configs, results = tmp_path / "configs", tmp_path / "results"
    configs.mkdir()
    (configs / "p2_x_dense.yaml").write_text(f"tasks: {task_file}\n")
    rows = synthetic_rows(n_tasks=20)
    for name, config in [("p2_x_single", "k1-1-1-1"), ("p2_x_dense", "k6-6-6-1")]:
        (results / name).mkdir(parents=True)
        rows[rows["config_id"] == config].to_csv(results / name / "results.csv", index=False)
    gate.main("p2", results_dir=results, configs_dir=configs)
    table = pd.read_csv(tmp_path / "tab" / "gate_p2_by_task.csv").set_index("task")
    assert table.loc["boolean", "n"] == 8 and table.loc["dyck", "n"] == 12


def test_hand_grade_covers_sonnet_and_p3w(tmp_path):
    # audit 11, finding 4: the single-Sonnet arm, CIs, and P3 judged on 20-59 + 100-119 once p3w exists
    import json as _json

    from analysis import hand_grade

    ids = [f"t{i:03d}" for i in range(120)]
    gold = {t: "5" for t in ids}
    task_file = tmp_path / "tasks.jsonl"
    task_file.write_text("".join(_json.dumps({"id": t, "prompt": "p", "answer": "5"}) + "\n" for t in ids))
    configs, results, out = tmp_path / "configs", tmp_path / "results", tmp_path / "hand"
    configs.mkdir()
    (configs / "p3_x_dense.yaml").write_text(f"tasks: {task_file}\n")
    runs = {"p3_x_single": (ids[:60], 1), "p3_x_dense": (ids[:60], 19), "p3_x_single_sonnet": (ids[20:60], 1),
            "p3w_x_single": (ids[100:], 1), "p3w_x_dense": (ids[100:], 19)}
    for name, (tasks, agents) in runs.items():
        (results / name).mkdir(parents=True)
        right = [float(i % 2 == 0) for i in range(len(tasks))] if "single" in name else [1.0] * len(tasks)
        pd.DataFrame({"config_id": "k", "task_id": tasks, "replicate": 0, "agents": agents, "answer": "5",
                      "parsed": 1.0, "correct": right}).to_csv(results / name / "results.csv", index=False)
    pd.DataFrame([{"task_id": t, "replicate": 0, "stage": "propose", "agent_id": f"propose.{k}", "grader": "exact",
                   "answer": "5", "correct": 1.0} for t in ids for k in range(6)]).to_csv(results / "p3_x_dense" / "agents.csv", index=False)
    hand_grade.make_sheet("p3", "x", gold, results, configs, out)
    table = hand_grade.unblind("p3", "x", results, configs, out).set_index("grade")
    row = table.loc["automatic"]
    assert row["n"] == 60  # 20-59 and 100-119
    assert row["gap_lo"] <= row["gap"] <= row["gap_hi"] and row["sonnet_n"] == 40


def test_split_run_slices_are_combined(tmp_path, monkeypatch):
    # audit 15: a run overwrites results.csv with the slice it ran, so each slice gets its own directory
    # and the analysis combines them (fake provider, nothing spent)
    from analysis.gate import load_dense_rows, slices

    monkeypatch.chdir(ROOT)
    base = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml")
    for name, offset in [("p3_x_dense", 0), ("p3_x_dense_b", 4)]:
        cfg = base.model_copy(update={"name": name, "out_dir": str(tmp_path), "configs": [], "task_offset": offset,
                                      "task_limit": 4, "chunk_size": 4})
        asyncio.run(run_experiment(cfg))
    parts = slices(tmp_path / "p3_x_dense" / "results.csv")
    assert [p.parent.name for p in parts] == ["p3_x_dense", "p3_x_dense_b"]
    assert len(load_dense_rows(parts)) == 8 and len(load_dense_rows(parts[0])) == 4


def test_vote_tiesplit_and_odd_answers(tmp_path):
    from analysis.hand_grade import odd_answer
    from analysis.landscape import vote_tiesplit_by_task

    rows = [{"task_id": "t", "replicate": 0, "stage": "propose", "agent_id": f"propose.{k}", "grader": "exact",
             "answer": a, "correct": float(a == "1")} for k, a in enumerate(["2", "1", "2", "1", "3", "4"])]
    pd.DataFrame(rows).to_csv(tmp_path / "agents.csv", index=False)
    assert vote_tiesplit_by_task(tmp_path / "agents.csv")["t"] == 0.5  # a 2-2 tie, one side right
    assert odd_answer("7 — completion: ]") and not odd_answer("7") and not odd_answer("No") and odd_answer("(A)")


def test_headline_pools_item_sets(tmp_path):
    # session 4 hand-back: dense vs single, vote6 and Sonnet on gate, held-out and pooled items
    from analysis.headline import headline

    def write(name, ids, agents, right):
        (tmp_path / name).mkdir(parents=True)
        pd.DataFrame({"config_id": "k", "task_id": ids, "replicate": 0, "agents": agents, "answer": "1",
                      "parsed": 1.0, "correct": right, "cost_usd": 0.01}).to_csv(tmp_path / name / "results.csv", index=False)

    ids = [f"t{i:03d}" for i in range(120)]
    write("p3_x_dense", ids[:40], 19, 1.0)
    write("p3_x_dense_b", ids[40:60], 19, 1.0)
    write("p3w_x_dense", ids[100:120], 19, 1.0)
    write("p4_x_grid_i", ids[60:100], 19, 0.0)
    write("p3_x_single", ids[:60], 1, 0.0)
    write("p3w_x_single", ids[100:120], 1, 0.0)
    write("p4_x_single_held", ids[60:100], 1, 0.0)
    write("p3_x_single_sonnet", ids[20:60], 1, 1.0)
    pd.DataFrame([{"task_id": t, "replicate": 0, "stage": "propose", "agent_id": f"propose.{k}", "grader": "exact",
                   "answer": "1", "correct": 0.0} for t in ids for k in range(6)]).to_csv(tmp_path / "p3_x_dense" / "agents.csv", index=False)
    table = headline("x", tmp_path).set_index(["comparison", "items"])
    gate = table.loc[("dense minus single Haiku", "gate (20-59, 100-119)")]
    assert gate["n"] == 60 and gate["diff_points"] == pytest.approx(100)  # calibration 0-19 left out
    assert table.loc[("dense minus single Haiku", "held-out (60-99)"), "diff_points"] == pytest.approx(0)
    assert table.loc[("dense minus single Haiku", "all validation (20-119)"), "n"] == 100
    assert table.loc[("single Sonnet minus dense", "P3 (20-59)"), "n"] == 40
