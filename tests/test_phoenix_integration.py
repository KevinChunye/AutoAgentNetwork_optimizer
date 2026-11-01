"""Offline integration with the parent caller/governor, calibration and reporting."""
import asyncio
import json
from pathlib import Path

import numpy as np
import pytest

from test_phoenix_core import InlineTool, caller_for, checkpoint
from autoagentnet.phoenix import calibrate
from autoagentnet.phoenix.data import from_arrays, load_search, prepare_dataset, save_search
from autoagentnet.phoenix.engine import RecoveryEngine
from autoagentnet.phoenix.metrics import branch_metrics
from autoagentnet.phoenix.planner import CapabilityTable
from autoagentnet.phoenix.report import aggregate
from autoagentnet.phoenix.run import PhoenixConfig, run_phoenix, preflight_phoenix
from autoagentnet.phoenix.study import extract_proposal_pool


def test_governed_wrapper_is_offline_and_does_not_create_ledger(checkpoint, tmp_path, monkeypatch):
    import httpx
    async def no_network(*args, **kwargs):
        pytest.fail("offline wrapper attempted network access")
    monkeypatch.setattr(httpx.AsyncClient, "post", no_network)
    cfg = PhoenixConfig(name="wrapper", checkpoint=str(checkpoint), model_override="fake", policy="fixed",
                        out_dir=str(tmp_path / "results"), ledger=str(tmp_path / "never_create_ledger"),
                        max_calls=1, max_tools=2)
    _, _, status = asyncio.run(run_phoenix(cfg))
    assert status["status"] != "error", status
    assert status["offline_fixture"] and status["new_api_bill_usd"] == 0
    assert not Path(cfg.ledger).exists()


def test_prepare_split_indices_using_synthetic_loader_only(tmp_path, monkeypatch):
    from sklearn import datasets
    from types import SimpleNamespace
    x = np.column_stack([np.arange(120), np.arange(120)**2])
    y = np.tile([0, 1, 2], 40)
    monkeypatch.setattr(datasets, "load_wine", lambda: SimpleNamespace(data=x, target=y))
    manifest = prepare_dataset("wine", tmp_path)
    splits = manifest["indices"]
    assert not (set(splits["train"]) & set(splits["test"]))
    assert not (set(splits["validation"]) & set(splits["test"]))
    for seed in (1, 2, 3):
        fold = load_search(tmp_path / "wine" / f"calibration_{seed}.npz")
        assert fold.partition == "calibration"
        assert set(fold.x_train[:, 0]) | set(fold.x_val[:, 0]) == set(splits["train"])


def test_calibration_protocol_on_fixture_not_live_models(tmp_path, monkeypatch):
    rng = np.random.default_rng(5)
    data = from_arrays(rng.normal(size=(60, 4)), np.tile([0, 1], 30),
                       rng.normal(size=(20, 4)), np.tile([0, 1], 10), partition="calibration")
    path = tmp_path / "inner.npz"
    save_search(path, data)
    cfg = PhoenixConfig(name="cal_fixture", mode="calibrate", calibration_model="luna_low_ev",
                        calibration_data=[str(path)], model_override="fake", max_calls=1,
                        max_tools=30, cpu_budget_s=30)
    monkeypatch.setattr(calibrate, "ToolRunner", InlineTool)
    out = tmp_path / "calibration"
    out.mkdir()
    result = asyncio.run(calibrate.run_calibration(cfg, caller_for(cfg), out, free=True))
    table = CapabilityTable.model_validate_json((out / "capability_table.json").read_text())
    assert result["tasks"] == 1 and table.synthetic and table.complete
    assert {r.partition for r in table.records} == {"calibration"}
    assert any(r.mode == "verify" for r in table.records)
    assert table.estimate("prepare", "cpu", data.dataset).samples > 0
    assert table.estimate("ensemble", "cpu", data.dataset).samples > 0


def test_metrics_keep_verification_distinct_from_recomputation(checkpoint, tmp_path):
    cfg = PhoenixConfig(name="metrics", checkpoint=str(checkpoint), model_override="fake", policy="fixed",
                        max_calls=1, max_tools=2)
    engine = RecoveryEngine.open(cfg, caller_for(cfg), tmp_path / "run", free=True, tool_factory=InlineTool)
    asyncio.run(engine.run())
    values = branch_metrics(engine.out)
    assert values["verification_operations"] >= 1
    assert values["redundant_operations"] == 0
    assert values["redundant_compute_cpu_s"] == 0
    assert values["first_delivery_reached"]


def test_invalid_first_pool_is_unavailable_not_replaced(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    state = {"case_id": "fixture_T1_101", "calls": [
        {"purpose": "propose", "output": {"content": "invalid"}, "logical_cost_usd": 0.01,
         "request_hash": "first"},
        {"purpose": "propose", "output": {"content": '{"proposals":[]}'}, "logical_cost_usd": 0.01,
         "request_hash": "later"}]}
    (source / "state.json").write_text(json.dumps(state))
    pool = extract_proposal_pool(source, tmp_path / "pool.json")
    assert pool["unavailable"] and pool["source_request_hash"] == "first"
    assert pool["logical_proposal_cost_usd"] == 0.01


def test_report_preserves_not_run_rows(tmp_path):
    manifest = {"branches": [{"name": "missing", "case_id": "fixture_T1_101", "experiment": "E1",
                  "policy": "full", "fault": "F1", "budget": 0.05,
                  "frozen": str(tmp_path / "missing" / "frozen.json")} ]}
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    rows = aggregate(path, None, tmp_path / "report")
    assert len(rows) == 1 and rows.status.iloc[0] == "not_run"
    assert "not an effect estimate" in (tmp_path / "report" / "README.md").read_text()


def test_paid_preflight_refuses_missing_immutable_inputs_without_clients(checkpoint, tmp_path, monkeypatch):
    monkeypatch.delenv("AAN_OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AAN_ANTHROPIC_API_KEY", raising=False)
    cfg = PhoenixConfig(name="paid_not_ready", checkpoint=str(checkpoint), out_dir=str(tmp_path / "out"),
                        ledger=str(tmp_path / "missing_ledger"))
    problems, _ = preflight_phoenix(cfg, str(tmp_path / "uncommitted.yaml"))
    assert any("capability" in x for x in problems)
    assert any("missing environment" in x for x in problems)
    assert not Path(cfg.ledger).exists() and not Path(cfg.out_dir).exists()
