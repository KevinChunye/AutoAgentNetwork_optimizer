"""The trimmed science matrix: counts, pilot cases kept out of the evidence, balanced withdrawal (offline)."""
import pandas as pd
import yaml

from autoagentnet.phoenix.run import PhoenixConfig
from autoagentnet.phoenix.study import science_calibration_configs, science_matrix

PREREG = {"question": "q", "prediction": "p", "kill": "k", "decision": "d"}
LIMITS = {"cpu_budget_s": 300, "max_calls": 8, "max_tools": 24, "wall_s": 1800, "tool_timeout_s": 60}
POOL = ["luna_low_ev", "sol61_low", "sonnet_low"]


def test_trimmed_matrix_counts_pilot_and_balance(tmp_path):
    m = science_matrix(tmp_path / "cfg", "data", "ckpt", "table.json", POOL, LIMITS, PREREG, str(tmp_path / "res"))
    b = pd.DataFrame(m["branches"])
    assert b.groupby("experiment").size().to_dict() == {"pilot": 9, "E1": 45, "E2": 30, "E1b": 30}
    # one pilot case per dataset, the first of that dataset in the fixed run order, never in the evidence
    assert sorted(c.split("_")[0] for c in m["pilot_cases"]) == ["covtype", "higgs", "miniboone"]
    assert not set(b[b.experiment != "pilot"].case_id) & set(m["pilot_cases"])
    for d in ("covtype", "miniboone", "higgs"):
        assert next(c for c in m["run_order"] if c.startswith(d)) in m["pilot_cases"]
    # every evidence case has the same 7 branches: 3 E1, 2 E2, 2 E1b
    assert set(b[b.experiment != "pilot"].groupby("case_id").size()) == {7}
    cases = pd.DataFrame(m["cases"])
    counts = cases.groupby(["template", "withdrawn_model"]).size().to_dict()
    assert counts == {("T1", "sol61_low"): 4, ("T1", "sonnet_low"): 5, ("T2", "sol61_low"): 5, ("T2", "sonnet_low"): 4}
    assert set(cases.groupby(["dataset", "withdrawn_model"]).size()) == {3}
    for row in b.itertuples():
        cfg = PhoenixConfig.model_validate(yaml.safe_load(open(row.config)))
        assert cfg.api_budget_usd == 0.20 and cfg.tool_timeout_s == 60 and cfg.prereg is not None
    batches = {k: yaml.safe_load(open(v)) for k, v in m["batch_manifests"].items()}
    assert batches["pilot"]["kind"] == "phoenix_batch" and len(batches["pilot"]["branches"]) == 9


def test_openai_only_pool_always_withdraws_sol(tmp_path):
    m = science_matrix(tmp_path / "cfg", "data", "ckpt", "t.json", ["luna_low_ev", "sol61_low"], LIMITS, PREREG,
                       experiments=("E1",))
    assert {c["withdrawn_model"] for c in m["cases"]} == {"sol61_low"} and len(m["branches"]) == 54


def test_science_calibration_configs_cover_nine_folds_per_model(tmp_path):
    paths = science_calibration_configs(tmp_path, "data", POOL, LIMITS, PREREG)
    cfgs = [PhoenixConfig.model_validate(yaml.safe_load(open(p))) for p in paths]
    assert [c.calibration_model for c in cfgs] == POOL and all(len(c.calibration_data) == 9 for c in cfgs)


def test_estimates_are_rounded_only_in_the_request():
    from autoagentnet.phoenix.engine import compact_estimate
    raw = {"success": 0.123456789, "api_usd": 0.0012345678, "cpu_s": 12.3456, "qualities": [0.712345678], "samples": 3}
    assert compact_estimate(raw) == {"success": 0.1235, "api_usd": 0.001235, "cpu_s": 12.35, "qualities": [0.7123],
                                     "samples": 3}


def test_pipelines_on_target_actions_are_rejected_not_dropped():
    import pytest
    from autoagentnet.phoenix.engine import check_action_shape
    from autoagentnet.phoenix.types import PipelineSpec, Proposal
    with pytest.raises(ValueError):
        check_action_shape(Proposal(action="RECOMPUTE", target="abc", pipelines=[PipelineSpec(classifier="forest")]))
    check_action_shape(Proposal(action="REROUTE", pipelines=[PipelineSpec(classifier="forest")]))
    check_action_shape(Proposal(action="RECOMPUTE", target="abc"))


def test_actions_are_explained_in_propose_and_recover_requests():
    from autoagentnet.phoenix.prompts import ACTIONS, request_for
    for purpose in ("propose", "recover"):
        req = request_for({"case_id": "c"}, purpose, "luna_low_ev", "A")
        assert ACTIONS in req.spec.instruction
    assert ACTIONS not in request_for({"case_id": "c"}, "calibrate", "luna_low_ev", "A").spec.instruction


def test_calibration_error_status_is_not_overwritten(tmp_path, monkeypatch):
    import asyncio, json
    import autoagentnet.phoenix.calibrate as calibrate
    from autoagentnet.phoenix.run import PhoenixConfig, run_phoenix
    from autoagentnet.phoenix.data import from_arrays, save_search
    import numpy as np
    rng = np.random.default_rng(0)
    x, y = rng.normal(size=(40, 3)), np.tile([0, 1], 20)
    path = tmp_path / "cal.npz"
    save_search(path, from_arrays(x[:30], y[:30], x[30:], y[30:], "fixture", "calibration"))
    cfg = PhoenixConfig(name="err", mode="calibrate", calibration_model="luna_low_ev", calibration_data=[str(path)],
                        model_override="fake", out_dir=str(tmp_path / "res"), max_calls=1)
    out = tmp_path / "res" / "fake_err"
    out.mkdir(parents=True)
    (out / "calibration_state.json").write_text(json.dumps({"status": "running", "spent": 0.0}))

    async def boom(*args, **kwargs):
        raise ValueError("calibration resume inputs changed")
    monkeypatch.setattr(calibrate, "run_calibration", boom)
    _, _, status = asyncio.run(run_phoenix(cfg))
    assert status["status"] == "error" and status["calibration_status"] == "running"


def test_calibration_plan_scores_the_first_new_executable_proposal(tmp_path, monkeypatch):
    """An INHERIT of the baseline followed by a REROUTE is scored on the REROUTE (as the study engine would use it)."""
    import asyncio, json
    import numpy as np
    from autoagentnet.phoenix.data import from_arrays, save_search
    from autoagentnet.phoenix.run import PhoenixConfig, run_phoenix
    from autoagentnet.phoenix import fake as fake_module
    rng = np.random.default_rng(1)
    x, y = rng.normal(size=(60, 3)), np.tile([0, 1], 30)
    path = tmp_path / "cal.npz"
    save_search(path, from_arrays(x[:45], y[:45], x[45:], y[45:], "fixture", "calibration"))
    cfg = PhoenixConfig(name="plan", mode="calibrate", calibration_model="luna_low_ev", calibration_data=[str(path)],
                        model_override="fake", out_dir=str(tmp_path / "res"), max_calls=30, task_offset=20, task_limit=1)
    reply = json.dumps({"proposals": [{"action": "INHERIT", "target": "BASELINE"},
                                      {"action": "REROUTE", "pipelines": [{"classifier": "logistic", "c": 1.0}]}]})
    from autoagentnet.providers.base import LLMResponse, Usage

    async def scripted(self, request):
        payload = json.loads(request.blocks[0].text.split("PHOENIX_JSON\n", 1)[1])
        text = reply.replace("BASELINE", payload["state"]["known_targets"][0])
        return LLMResponse(text=text, usage=Usage(input_tokens=10, output_tokens=10), model=request.model,
                           provider="fake", latency_s=0)
    monkeypatch.setattr(fake_module.FakePhoenixClient, "complete", scripted)
    asyncio.run(run_phoenix(cfg))
    state = json.loads((tmp_path / "res" / "fake_plan" / "calibration_state.json").read_text())
    design = [o for o in state["observations"] if o["kind"] == "design"][-1]
    assert design["completed"] and design["quality"] is not None and state["last_task_error"] is None


def test_gate_sees_pipeline_qualities_in_any_category():
    """One failed 'generic' pipeline row must not hide the dataset's completed pipelines from the preflight check."""
    from autoagentnet.phoenix.planner import CapabilityTable, Observation
    rows = [Observation(kind="pipeline", dataset="covtype", partition="calibration", category="generic", completed=False,
                        api_usd=0, cpu_s=0),
            Observation(kind="pipeline", dataset="covtype", partition="calibration", category="forest", completed=True,
                        quality=0.7, api_usd=0, cpu_s=10)]
    table = CapabilityTable(records=rows)
    assert not table.estimate("pipeline", "cpu", "covtype").qualities          # the old check's lookup
    assert any(r.kind == "pipeline" and r.dataset == "covtype" and r.completed and r.quality is not None for r in rows)
