"""Offline recovery tests. No benchmark runs or vendor API calls are made."""
import asyncio
import json
from pathlib import Path

import numpy as np
import pytest
from pydantic import ValidationError

from autoagentnet.cache import CallCache
from autoagentnet.market.caller import MarketCaller
from autoagentnet.phoenix.checkpoint import create_checkpoint, read_checkpoint
from autoagentnet.phoenix.data import from_arrays, load_search, save_search
from autoagentnet.phoenix.engine import RecoveryEngine
from autoagentnet.phoenix.planner import CapabilityTable, closure, compile_plan, select
from autoagentnet.phoenix.run import PhoenixConfig, registry_for
from autoagentnet.phoenix.store import ArtifactStore
from autoagentnet.phoenix.types import Budget, Graph, Operation, PipelineSpec, Plan, Proposal, Resources, Status, WorkTask
from autoagentnet.phoenix.worker import execute
from autoagentnet.phoenix.workflow import add_ensemble, add_pipeline, compile_proposal
from autoagentnet.pricing import PriceBook
from autoagentnet.runtime.local import LocalRuntime


class InlineTool:
    """Fast test-only runner executing the same trusted tool code without spawning."""
    def __init__(self, data, store, work, timeout=30):
        self.data, self.store = str(data), str(store)

    def run(self, graph, step, **kwargs):
        return execute({"data": self.data, "store": self.store, "graph": graph.model_dump(),
                        "operation": step.operation, "verify": step.mode == "verify",
                        "stage_only": kwargs.get("stage_only", False)})


@pytest.fixture
def checkpoint(tmp_path):
    rng = np.random.default_rng(2026)
    x = rng.normal(size=(100, 6))
    y = np.tile([0, 1], 50)
    rng.shuffle(y)
    data = from_arrays(x[:70], y[:70], x[70:], y[70:])
    datafile = tmp_path / "fixture.npz"
    save_search(datafile, data)
    root = tmp_path / "checkpoint"
    create_checkpoint(datafile, root, seed=101, template="T2", tool_factory=InlineTool)
    return root


def caller_for(cfg):
    registry = registry_for(cfg)
    return MarketCaller(LocalRuntime(registry), registry, pricebook=PriceBook.from_yaml(cfg.pricing),
                        cache=CallCache(), governor=None, run_id="offline-test", market="phoenix", condition=cfg.policy)


def test_strict_dsl_rejects_authority_and_nonfinite():
    with pytest.raises(ValidationError):
        Proposal(action="REROUTE", pipelines=[{}], predicted_score=1)
    with pytest.raises(ValidationError):
        Budget(api_limit=float("nan"))
    with pytest.raises(ValidationError):
        PipelineSpec(classifier="shell")
    with pytest.raises(ValidationError):
        Proposal(action="SPLIT", pipelines=[{}])


def test_split_data_roundtrip_and_no_test_access(tmp_path):
    data = from_arrays(np.zeros((10, 2)), np.tile([0, 1], 5), np.ones((4, 2)), [0, 1, 0, 1])
    save_search(tmp_path / "search.npz", data)
    assert load_search(tmp_path / "search.npz").signature == data.signature
    assert not hasattr(data, "y_test")
    np.savez(tmp_path / "bad.npz", x_test=np.zeros((1, 2)), y_test=[1])
    with pytest.raises(ValueError):
        load_search(tmp_path / "bad.npz")


def test_real_checkpoint_pending_prediction_and_shutdown(checkpoint):
    raw = read_checkpoint(checkpoint)
    graph = Graph.model_validate(raw["graph"])
    store = ArtifactStore(checkpoint / "artifacts")
    target = graph.tasks["unfinished"].target
    pred = graph.operations[target].parents[0]
    assert store.status(graph.operations[pred], graph) == Status.UNVERIFIED
    before = graph.incumbent
    assert graph.shutdown("A") == ["unfinished"]
    assert graph.tasks["unfinished"].owner is None
    assert store.status(graph.operations[before], graph) == Status.VALID
    version = graph.claim("unfinished", "B", 1)
    graph.shutdown("B")
    with pytest.raises(ValueError, match="late"):
        graph.check_owner("unfinished", "B", version)


def test_immutable_context_and_minimal_suffix():
    graph = Graph(context="context")
    original = add_pipeline(graph, PipelineSpec(c=1.0), 101)
    changed_model = add_pipeline(graph, PipelineSpec(c=10.0), 101)
    changed_features = add_pipeline(graph, PipelineSpec(c=10.0, scaler="minmax"), 101)
    def feature(target):
        prediction = graph.operations[target].parents[0]
        fit = graph.operations[prediction].parents[0]
        return graph.operations[fit].parents[0]
    assert feature(original) == feature(changed_model)
    assert feature(original) != feature(changed_features)
    graph.audit()
    with pytest.raises(ValueError, match="context"):
        graph.add(Operation(kind="prepare", context="different"))


def test_receipt_detects_corruption_and_missing_parent(checkpoint):
    raw = read_checkpoint(checkpoint)
    graph = Graph.model_validate(raw["graph"])
    store = ArtifactStore(checkpoint / "artifacts")
    root = graph.incumbent
    assert store.status(graph.operations[root], graph) == Status.VALID
    parent = graph.operations[root].parents[0]
    store.path(parent).write_bytes(b"corrupt")
    assert store.status(graph.operations[parent], graph) == Status.STALE
    assert store.status(graph.operations[root], graph) == Status.STALE
    store.path(parent).unlink()
    assert store.status(graph.operations[parent], graph) == Status.MISSING


def test_whole_closure_and_no_duplicate_shared_prefix(tmp_path):
    graph = Graph(context="x", score=0.2)
    a = add_pipeline(graph, PipelineSpec(c=1.0), 1)
    b = add_pipeline(graph, PipelineSpec(c=10.0), 1)
    target = add_ensemble(graph, [a, b])
    store = ArtifactStore(tmp_path)
    steps, _ = closure(graph, target, store)
    assert len(steps) == 7  # one shared transformer, two fits/predicts, merge, report
    assert len({x.operation for x in steps}) == 7
    # A split may add at most four new dependency levels; the shared prefix is inherited.
    feature = next(op for op in graph.operations.values() if op.kind == "prepare")
    store.put(feature, graph, {"transformer": None, "x_train": np.zeros((2, 1)),
                              "x_val": np.zeros((2, 1))}, 0, 0, Status.VALID)
    table = CapabilityTable.fake()
    plan = Plan(action="SPLIT", target=target)
    assert compile_plan(plan, graph, store, Resources(), Budget(api_limit=1, tool_limit=2), table, "fixture") is None
    value = compile_plan(plan, graph, store, Resources(), Budget(api_limit=1), table, "fixture")
    assert value.tools == 6
    assert value.gain == pytest.approx((0.8**6)*0.8)


def test_withdrawn_model_not_selectable(tmp_path):
    g = Graph(context="x", score=0.1)
    op = Operation(kind="design", context="x", model="fake")
    target = g.add(op)
    plan = Plan(action="REROUTE", target=target)
    resources = Resources(models=["fake"])
    assert compile_plan(plan, g, ArtifactStore(tmp_path), resources, Budget(api_limit=1),
                        CapabilityTable.fake(), "fixture") is not None
    resources.fault("A", "fake")
    assert compile_plan(plan, g, ArtifactStore(tmp_path), resources, Budget(api_limit=1),
                        CapabilityTable.fake(), "fixture") is None


def test_proposal_rejection_does_not_mutate_graph():
    g = Graph(context="x")
    with pytest.raises(ValueError):
        compile_proposal(g, Proposal(action="REROUTE", model="withdrawn"), Resources(), 101)
    assert not g.operations


@pytest.mark.parametrize("policy", ["fixed", "static", "full", "llm", "no_dependency", "no_cost"])
def test_offline_end_to_end(checkpoint, tmp_path, policy):
    cfg = PhoenixConfig(name="test_"+policy, checkpoint=str(checkpoint), model_override="fake", policy=policy,
                        proposal_rounds=1, max_calls=3, max_tools=12, cpu_budget_s=30)
    caller = caller_for(cfg)
    out = tmp_path / ("run_"+policy)
    engine = RecoveryEngine.open(cfg, caller, out, free=True, tool_factory=InlineTool)
    status = asyncio.run(engine.run())
    assert status["status"] != "error", status
    assert (out / "frozen.json").is_file()
    assert all(row["worker"] != "A" for row in engine.state.calls)
    assert "sonnet_low" not in engine.state.resources.models
    assert engine.state.budget.calls <= cfg.max_calls
    assert engine.state.budget.tools <= cfg.max_tools
    for call in engine.state.calls:
        text = json.dumps(call)
        assert '"y_test"' not in text and "sealed_test" not in text
    # Re-opening a completed run must perform no extra calls or tool work.
    count = caller.live_calls
    resumed = RecoveryEngine.open(cfg, caller, out, free=True, tool_factory=InlineTool)
    asyncio.run(resumed.run())
    assert caller.live_calls == count


def test_f0_preserves_model_pool(checkpoint, tmp_path):
    cfg = PhoenixConfig(name="f0", checkpoint=str(checkpoint), model_override="fake", fault="F0")
    engine = RecoveryEngine.open(cfg, caller_for(cfg), tmp_path / "f0", free=True, tool_factory=InlineTool)
    assert "A" not in engine.state.resources.workers
    assert engine.state.resources.models == cfg.models


def test_calibration_rejects_search_labels():
    from autoagentnet.phoenix.planner import Observation
    with pytest.raises(ValidationError):
        Observation(kind="fit", dataset="digits", partition="search", completed=True, api_usd=0, cpu_s=1)
