"""Independent decision examples for the two ablations and report arithmetic."""
import json

import numpy as np
import pandas as pd
import pytest

from autoagentnet.phoenix.planner import CapabilityTable, Observation, select
from autoagentnet.phoenix.report import aggregate
from autoagentnet.phoenix.store import ArtifactStore
from autoagentnet.phoenix.types import Budget, Graph, PipelineSpec, Plan, Resources, Status
from autoagentnet.phoenix.workflow import add_pipeline


def test_cost_and_dependency_terms_change_decisions_but_not_feasibility(tmp_path):
    graph = Graph(context="selection_fixture", score=0.5)
    lr = add_pipeline(graph, PipelineSpec(classifier="logistic"), 1)
    rf = add_pipeline(graph, PipelineSpec(classifier="forest"), 1)
    store = ArtifactStore(tmp_path)
    prefix = next(op for op in graph.operations.values() if op.kind == "prepare")
    store.put(prefix, graph, {"transformer": None, "x_train": np.zeros((10, 2)),
                             "x_val": np.zeros((5, 2))}, 30, 30, Status.VALID)
    rows = []
    for kind, category, cpu, quality in [
        ("prepare", "generic", 30, None), ("fit", "logistic", 2, None),
        ("fit", "forest", 20, None), ("predict", "generic", .1, None),
        ("validate", "generic", .1, None), ("pipeline", "logistic", 0, .8),
        ("pipeline", "forest", 0, 1.0)]:
        for _ in range(3):
            rows.append(Observation(kind=kind, category=category, dataset="fixture", partition="calibration",
                                    completed=True, quality=quality, api_usd=0, cpu_s=cpu))
    table = CapabilityTable(records=rows, synthetic=True)
    plans = [Plan(action="REROUTE", target=lr), Plan(action="REROUTE", target=rf)]
    args = (plans, graph, store, Resources(), Budget(api_limit=1, cpu_limit=60), table, "fixture")
    assert select(*args, policy="full").plan.target == lr
    assert select(*args, policy="no_cost").plan.target == rf
    assert select(*args, policy="no_dependency").plan.target == rf
    tight = (plans, graph, store, Resources(), Budget(api_limit=1, cpu_limit=10), table, "fixture")
    assert select(*tight, policy="no_cost").plan.target == lr  # no-cost still obeys hard constraints


def test_report_pairs_and_recovery_interaction_without_scientific_runs(tmp_path):
    branches, scores = [], []
    for experiment, fault, policy, quality in [
        ("E1", "F1", "fixed", .75), ("E1", "F1", "full", .80), ("E1", "F1", "llm", .77),
        ("E2", "F0", "fixed", .89), ("E2", "F0", "full", .88),
        ("E3", "healthy", "fixed", .90), ("E3", "healthy", "full", .89)]:
        name = f"{experiment}_{policy}"
        root = tmp_path / name
        root.mkdir()
        (root / "status.json").write_text(json.dumps({"status": "completed", "offline_fixture": True,
            "budget": {"api_spent": .01, "cpu_spent": 1}, "validation_score": .8, "new_api_bill_usd": 0}))
        branches.append({"name": name, "case_id": "fixture_T1_101", "experiment": experiment,
                         "fault": fault, "policy": policy, "budget": .2, "frozen": str(root / "frozen.json")})
        scores.append({"name": name, "test_balanced_accuracy": quality})
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps({"branches": branches}))
    evaluation = tmp_path / "evaluation.csv"
    pd.DataFrame(scores).to_csv(evaluation, index=False)
    aggregate(manifest, evaluation, tmp_path / "report")
    paired = pd.read_csv(tmp_path / "report" / "paired.csv")
    assert paired.loc[paired.experiment.eq("E1"), "full_minus_fixed"].iloc[0] == pytest.approx(.05)
    interaction = pd.read_csv(tmp_path / "report" / "recovery_specific.csv")
    assert interaction.loc[interaction.loss_condition.eq("quality_loss_F1"), "recovery_specific_benefit"].iloc[0] == pytest.approx(.06)
    assert (tmp_path / "report" / "cost_quality.png").stat().st_size > 1000
