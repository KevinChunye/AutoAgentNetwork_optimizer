"""Crash recovery, semantic budgets, model parsing, and executable delivery tests."""
import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest
import yaml

from test_phoenix_core import InlineTool, caller_for, checkpoint
from autoagentnet.phoenix.engine import RecoveryEngine, ScientificBudgetExceeded
from autoagentnet.phoenix.evaluate import evaluate_frozen, seal_evaluation, evaluate_manifest
from autoagentnet.phoenix.fake import FakePhoenixClient
from autoagentnet.phoenix.planner import CapabilityTable, closure, enumerate_estimated
from autoagentnet.phoenix.report import replay
from autoagentnet.phoenix.run import PhoenixConfig, estimate_phoenix, preflight_phoenix
from autoagentnet.phoenix.store import ArtifactStore
from autoagentnet.phoenix.study import matrix
from autoagentnet.phoenix.tools import ToolRunner, ToolFailure
from autoagentnet.phoenix.types import Budget, Graph, PipelineSpec, Plan, Resources
from autoagentnet.phoenix.workflow import add_pipeline


def make_engine(checkpoint, tmp_path, **kwargs):
    cfg = PhoenixConfig(name="boundary", checkpoint=str(checkpoint), model_override="fake",
                        max_calls=3, proposal_rounds=1, **kwargs)
    caller = caller_for(cfg)
    engine = RecoveryEngine.open(cfg, caller, tmp_path / "run", free=True, tool_factory=InlineTool)
    return cfg, caller, engine


def test_model_reservation_rejected_before_call(checkpoint, tmp_path):
    _, caller, engine = make_engine(checkpoint, tmp_path)
    engine.worst_cost = lambda request: 10.0
    with pytest.raises(ScientificBudgetExceeded):
        asyncio.run(engine.ask("recover"))
    assert caller.live_calls == 0
    assert engine.state.budget.calls == 0


def test_invalid_reply_is_counted_without_free_retry(checkpoint, tmp_path):
    _, caller, engine = make_engine(checkpoint, tmp_path, policy="llm")
    caller.registry.set_client("luna_low_ev", FakePhoenixClient(["not json", '{"stop":true}']))
    result = asyncio.run(engine.run())
    assert result["status"] != "error"
    assert engine.state.budget.calls == 2
    assert sum(e["event"] == "invalid_model_output" for e in engine.state.events) == 1


def test_cached_response_recovers_crash_before_state_commit(checkpoint, tmp_path):
    cfg, caller, engine = make_engine(checkpoint, tmp_path, policy="llm")
    original = engine.save
    def crash():
        if engine.state.pending_call and engine.state.pending_call.get("output"):
            raise SystemExit("injected crash after provider/cache commit")
        original()
    engine.save = crash
    with pytest.raises(SystemExit):
        asyncio.run(engine.ask("recover"))
    assert caller.live_calls == 1
    resumed = RecoveryEngine.open(cfg, caller, engine.out, free=True, tool_factory=InlineTool)
    asyncio.run(resumed.finish_call())
    assert caller.live_calls == 1
    assert resumed.state.budget.calls == 1
    assert len(resumed.state.calls) == 1
    assert resumed.state.calls[0]["output"]["from_cache"] is True


def test_tool_commit_recovers_without_repeating_compute(checkpoint, tmp_path):
    cfg, caller, engine = make_engine(checkpoint, tmp_path, policy="fixed")
    from autoagentnet.phoenix.planner import rank_plans
    ranked = rank_plans(engine.state.plans, engine.state.graph, engine.store, engine.state.resources,
                        engine.state.budget, engine.table, engine.data.dataset)
    chosen = next(c for c in ranked if c.plan.target == engine.state.checkpoint_targets[0])
    real = engine.tool.run
    def crash(*args, **kwargs):
        real(*args, **kwargs)
        raise SystemExit("injected crash after payload/receipt commit")
    engine.tool.run = crash
    with pytest.raises(SystemExit):
        engine.execute_tool(chosen)
    resumed = RecoveryEngine.open(cfg, caller, engine.out, free=True, tool_factory=InlineTool)
    resumed.tool.run = lambda *a, **k: pytest.fail("tool was recomputed")
    resumed.finish_tool()
    assert resumed.state.budget.tools == 1
    assert any(e.get("recovered_from_receipt") for e in resumed.state.events)


def test_small_graph_oracle_accounts_for_shared_dependencies(tmp_path):
    graph = Graph(context="fixture", score=0.1)
    targets = [add_pipeline(graph, PipelineSpec(c=c), 1) for c in (0.1, 10.0)]
    plans = [Plan(action="REROUTE", target=t) for t in targets]
    result = enumerate_estimated(plans, graph, ArtifactStore(tmp_path), Resources(),
                                 Budget(api_limit=1), CapabilityTable.fake(), "fixture")
    assert len(result["plans"]) == 2
    assert result["estimated_gain"] > (0.8**4)*0.9
    assert result["cpu_s"] == pytest.approx(0.07)  # seven operations, shared prepare once


def test_frozen_predictor_scores_only_separately(checkpoint, tmp_path):
    _, _, engine = make_engine(checkpoint, tmp_path, policy="static")
    asyncio.run(engine.run())
    rng = np.random.default_rng(17)
    sealed = tmp_path / "sealed.npz"
    np.savez(sealed, x_test=rng.normal(size=(20, 6)), y_test=np.tile([0, 1], 10),
             search_signature=engine.data.signature)
    manifest = tmp_path / "evaluation.json"
    branch = {"name": "fixture", "frozen": str(engine.out / "frozen.json"), "sealed_test": str(sealed)}
    seal_evaluation([branch], manifest)
    frame = evaluate_manifest(manifest, tmp_path / "evaluation.csv")
    assert 0 <= frame.test_balanced_accuracy.iloc[0] <= 1
    frozen = engine.out / "frozen.json"
    frozen.write_text(frozen.read_text()+" ")
    with pytest.raises(ValueError, match="changed"):
        evaluate_manifest(manifest, tmp_path / "should_not_exist.csv")
    assert not (tmp_path / "should_not_exist.csv").exists()


def test_replay_escapes_model_html(checkpoint, tmp_path):
    _, _, engine = make_engine(checkpoint, tmp_path, policy="static")
    engine.event("test", reason="</script><script>alert(1)</script>")
    asyncio.run(engine.run())
    page = tmp_path / "replay.html"
    replay(engine.out, page)
    text = page.read_text()
    assert "</script><script>alert(1)" not in text
    assert "Replay" in text and "离线协议测试" in text


def test_matrix_is_configuration_only(tmp_path):
    manifest = matrix(tmp_path / "configs", "not_prepared_data", "not_prepared_checkpoints", "not_calibrated.json")
    assert len(manifest["cases"]) == 18 and len(manifest["branches"]) == 360
    counts = {}
    for b in manifest["branches"]:
        counts[b["experiment"]] = counts.get(b["experiment"], 0)+1
        PhoenixConfig.from_yaml(b["config"])
    assert counts == {"E1": 216, "E2": 36, "E3": 36, "E4": 72}
    assert manifest["status"] == "draft_not_frozen"
    assert not Path("not_prepared_data").exists()


def test_real_isolated_worker_on_fixture(checkpoint, tmp_path):
    from autoagentnet.phoenix.checkpoint import branch_checkpoint
    raw = branch_checkpoint(checkpoint, tmp_path / "branch")
    graph = Graph.model_validate(raw["graph"])
    store = ArtifactStore(tmp_path / "branch" / "artifacts")
    target = graph.tasks["unfinished"].target
    step = closure(graph, target, store)[0][0]
    tool = ToolRunner(tmp_path / "branch" / "search.npz", store.root, tmp_path / "work", timeout_s=20)
    result = tool.run(graph, step, cpu_left=30, wall_left=20)
    assert result["verified"] is True


def test_cli_estimate_and_gate_offline(checkpoint, tmp_path):
    cfg = PhoenixConfig(name="cli", checkpoint=str(checkpoint), model_override="fake", out_dir=str(tmp_path / "out"))
    path = tmp_path / "config.yaml"
    path.write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True)))
    env = {**os.environ, "PATH": str(Path(sys.executable).parent)+os.pathsep+os.environ["PATH"]}
    for command in ("estimate", "check"):
        r = subprocess.run([sys.executable, "-m", "autoagentnet.cli", command, str(path)],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr+r.stdout
    assert estimate_phoenix(cfg).worst_case_usd.sum() == 0
    assert not (tmp_path / "out").exists()
