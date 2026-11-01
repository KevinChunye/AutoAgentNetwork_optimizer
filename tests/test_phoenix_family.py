"""PHOENIX family arms: the configs follow the settings and the main study's cases (offline; nothing runs)."""
from pathlib import Path

import pandas as pd
import yaml

from autoagentnet.phoenix.run import PhoenixConfig
from test_phoenix_core import checkpoint  # noqa: F401  (pytest fixture)
from autoagentnet.phoenix.study import (GATE_TASKS, family_calibration_configs, family_matrix, science_cases,
                                        withdrawn_models)

ROOT = Path(__file__).resolve().parents[1]
SETTINGS = yaml.safe_load((ROOT / "configs/experiments/phoenix_science/family/settings.yaml").read_text())


def test_main_study_withdrawal_rule_is_unchanged():
    cases, _, _ = science_cases("cp", ["luna_low_ev", "sol61_low", "sonnet_low"])
    assert {c["id"]: c["withdrawn_model"] for c in cases} == withdrawn_models(cases, ["luna_low_ev", "sol61_low",
                                                                                     "sonnet_low"])
    t1 = [c["withdrawn_model"] for c in cases if c["template"] == "T1"]
    assert t1[0] == "sonnet_low" and t1.count("sonnet_low") in (4, 5)


def test_family_matrix_per_arm(tmp_path):
    for name, arm in SETTINGS["arms"].items():
        manifest = family_matrix(tmp_path / name, "data", "cp", "table.json", arm, SETTINGS["limits"])
        frame = pd.DataFrame(manifest["branches"])
        assert len(frame) == 54 * len(arm["draws"]) and set(frame["policy"]) == {"fixed", "llm", "full"}
        assert frame.groupby(["case_id", "policy"])["draw"].nunique().eq(len(arm["draws"])).all()
        assert set(frame["planner_model"]) == {arm["planner_model"]}
        assert arm["planner_model"] not in set(frame["withdrawn_model"])
        counts = frame.drop_duplicates("case_id").groupby(["template", "withdrawn_model"]).size()
        assert counts.between(4, 5).all() and len(counts) == 4          # each template loses each model 4-5 times
        _, _, first = science_cases("cp", arm["models"], arm["withdraw"])
        assert sorted(frame.loc[frame["gate"], "case_id"].unique()) == sorted(first)
        assert set(frame.loc[frame["gate"], "draw"]) == {arm["draws"][0]}
        gate = yaml.safe_load(Path(manifest["batch_manifests"]["gate"]).read_text())
        rest = yaml.safe_load(Path(manifest["batch_manifests"]["rest"]).read_text())
        assert len(gate["branches"]) == 9 and len(rest["branches"]) == 54 * len(arm["draws"]) - 9
        cfg = PhoenixConfig.from_yaml(gate["branches"][0])
        assert cfg.max_tokens == arm["max_tokens"] and cfg.api_budget_usd == arm["budget_usd"]
        assert cfg.models == arm["models"] and cfg.max_calls == SETTINGS["limits"]["max_calls"]
        assert cfg.draw == arm["draws"][0]


def test_family_calibration_slices_gate_first(tmp_path):
    arm = SETTINGS["arms"]["claude"]
    batches = family_calibration_configs(tmp_path, "data", arm)
    assert [Path(b).stem for b in batches] == ["batch_g1", "batch_g2", "batch_g3"] + [f"batch_s{i}" for i in range(1, 7)]
    tasks = {}
    for path in batches:
        for branch in yaml.safe_load(Path(path).read_text())["branches"]:
            cfg = PhoenixConfig.from_yaml(branch)
            assert cfg.mode == "calibrate" and cfg.max_tokens == arm["max_tokens"]
            assert cfg.name == f"{arm['prefix']}_cal_{cfg.calibration_model}"   # slices share one results directory
            covered = range(cfg.task_offset, cfg.task_offset + cfg.task_limit)
            if cfg.calibration_model not in tasks:
                tasks[cfg.calibration_model] = []
            tasks[cfg.calibration_model].extend(covered)
    assert set(tasks) == set(arm["models"])
    for model, covered in tasks.items():
        assert covered[:3] == list(GATE_TASKS) and set(covered) == set(range(30))


def test_draw_changes_the_replicate_key_only(checkpoint, tmp_path):
    """draw 0 keeps the main study's replicate (the seed); draw k sends the same request as a fresh draw."""
    import asyncio

    from test_phoenix_core import InlineTool, caller_for
    from autoagentnet.phoenix.engine import RecoveryEngine

    seen = {}
    for draw in (0, 2):
        cfg = PhoenixConfig(name=f"draw{draw}", checkpoint=str(checkpoint), model_override="fake", max_calls=3,
                            proposal_rounds=1, policy="llm", draw=draw)
        caller = caller_for(cfg)
        original = caller.call
        replicates = []

        async def recording(request, replicate, original=original, replicates=replicates):
            replicates.append(replicate)
            return await original(request, replicate)

        caller.call = recording
        engine = RecoveryEngine.open(cfg, caller, tmp_path / f"run{draw}", free=True, tool_factory=InlineTool)
        asyncio.run(engine.ask("recover"))
        seen[draw] = replicates
    assert seen[0] == [101] and seen[2] == [2101]


def test_combined_manifest_concatenates_and_refuses_duplicates(tmp_path):
    import importlib.util
    import json

    import pytest

    spec = importlib.util.spec_from_file_location("combo", ROOT / "scripts" / "phoenix_combined_manifest.py")
    combo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(combo)
    row = {"case_id": "c", "experiment": "E1", "policy": "full", "fault": "F1", "budget": 0.2, "frozen": "f",
           "sealed_test": "s"}
    (tmp_path / "a.json").write_text(json.dumps({"branches": [{**row, "name": "a1"}]}))
    (tmp_path / "b.json").write_text(json.dumps({"branches": [{**row, "name": "b1", "draw": 2}]}))
    out = combo.combine([str(tmp_path / "a.json"), str(tmp_path / "b.json")])
    assert [b["name"] for b in out["branches"]] == ["a1", "b1"] and [b["draw"] for b in out["branches"]] == [0, 2]
    (tmp_path / "c.json").write_text(json.dumps({"branches": [{**row, "name": "a1"}]}))
    with pytest.raises(ValueError):
        combo.combine([str(tmp_path / "a.json"), str(tmp_path / "c.json")])


def test_report_pairs_within_each_draw(tmp_path):
    """Two draws of the same case and method must not collide in the paired table (family arms)."""
    import json

    from autoagentnet.phoenix.report import aggregate

    branches, scores = [], []
    for draw in (1, 2):
        for policy, acc in (("full", 0.8), ("fixed", 0.7 + 0.01 * draw)):
            name = f"fam_x_E1_c1_{policy}_d{draw}"
            branches.append({"name": name, "case_id": "covtype_T1_101", "experiment": "fam_x", "policy": policy,
                             "fault": "F1", "budget": 1.0, "draw": draw, "frozen": str(tmp_path / name / "frozen.json")})
            scores.append({"name": name, "test_balanced_accuracy": acc})
            (tmp_path / name).mkdir()
            (tmp_path / name / "status.json").write_text(json.dumps(
                {"status": "no_positive_feasible_plan", "budget": {"api_spent": 0.1, "cpu_spent": 1.0},
                 "new_api_bill_usd": 0.1, "validation_score": acc}))
    (tmp_path / "m.json").write_text(json.dumps({"branches": branches}))
    pd.DataFrame(scores).to_csv(tmp_path / "eval.csv", index=False)
    frame = aggregate(tmp_path / "m.json", tmp_path / "eval.csv", tmp_path / "report")
    assert sorted(frame["draw"].unique()) == [1, 2]
    paired = pd.read_csv(tmp_path / "report" / "paired.csv")
    assert sorted(paired["full_minus_fixed"].round(2)) == [0.08, 0.09]
