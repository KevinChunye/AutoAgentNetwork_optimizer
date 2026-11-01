"""PHOENIX family-arm gates (scripts/phoenix_family_gate.py) on synthetic result directories (offline)."""
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("phoenix_family_gate", ROOT / "scripts" / "phoenix_family_gate.py")
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)


def write(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data)


def test_calibration_gate(tmp_path):
    for model in ("a", "b"):
        write(tmp_path / f"fam_x_cal_{model}/status.json", {"status": "running"})
        write(tmp_path / f"fam_x_cal_{model}/calibration_state.json",
              {"done": ["0", "10", "20"], "pending": None, "spent": 0.1,
               "outputs": {"k": {"stop_reason": "end_turn"}, "r": {"stop_reason": "refusal"}}})
    for label in ("g1", "g2", "g3"):
        write(tmp_path / f"fam_x_cal_batch_{label}/batch_status.json",
              {"branches": [{"state_sync": "committed and pushed"}] * 2})
    out = gate.calibration_gate(tmp_path, "fam_x", ["a", "b"])
    assert out["go"] and [m["refused"] for m in out["models"]] == [1, 1]   # reported, not a gate rule
    write(tmp_path / "fam_x_cal_b/status.json", {"status": "error", "error_type": "ValueError"})
    assert not gate.calibration_gate(tmp_path, "fam_x", ["a", "b"])["go"]


def call(stop="end_turn"):
    return json.dumps({"model_ref": "m", "purpose": "plan", "output": {"stop_reason": stop}})


def test_matrix_gate(tmp_path):
    branches = [{"name": f"fam_x_E1_c{i}_full", "policy": "full", "budget": 1.0, "gate": True} for i in range(3)]
    branches.append({"name": "fam_x_E1_c9_full", "policy": "full", "budget": 1.0, "gate": False})
    manifest = {"arm": "fam_x", "branches": branches}
    for b in branches[:3]:
        run = tmp_path / b["name"]
        write(run / "status.json", {"status": "no_positive_feasible_plan", "new_api_bill_usd": 0.2})
        write(run / "events.jsonl", json.dumps({"event": "plan_selected"}) + "\n")
        write(run / "calls.jsonl", "\n".join([call()] * 4) + "\n")
        write(run / "frozen.json", {})
    write(tmp_path / "fam_x_batch_gate/batch_status.json", {"branches": [{"state_sync": "committed and pushed"}] * 3})
    assert gate.matrix_gate(manifest, tmp_path)["go"]
    write(tmp_path / branches[0]["name"] / "calls.jsonl", "\n".join([call("max_tokens")] * 2 + [call()] * 2) + "\n")
    out = gate.matrix_gate(manifest, tmp_path)
    assert not out["go"] and out["bad_calls"] == 2 and out["calls"] == 12      # 2 of 12 = 16.7% > 10%
    write(tmp_path / branches[2]["name"] / "calls.jsonl", "\n".join([call("refusal")] + [call()] * 3) + "\n")
    assert sum(r["refused"] for r in gate.matrix_gate(manifest, tmp_path)["calls_by_model"]) == 1
    write(tmp_path / branches[0]["name"] / "calls.jsonl", "\n".join([call()] * 4) + "\n")
    write(tmp_path / branches[1]["name"] / "status.json", {"status": "no_positive_feasible_plan", "new_api_bill_usd": 1.5})
    assert not gate.matrix_gate(manifest, tmp_path)["checks"]["within_budget"]
