"""Read-only accounting of real operations. Verification is not redundant work."""
from __future__ import annotations

import json
from pathlib import Path

from .types import Graph


def branch_metrics(run_dir):
    root = Path(run_dir)
    state = json.loads((root / "state.json").read_text())
    recovery = json.loads((root / "recovery_plan.json").read_text())
    graph = Graph.model_validate(state["graph"])
    events = state["events"]
    operations = [e for e in events if e["event"] == "operation_completed"]
    original = set(state["checkpoint_operations"])
    redundant = [e for e in operations if e["mode"] == "compute" and e.get("prior_status") == "VALID"
                 and not e.get("recovered_from_receipt")]
    necessary = [e for e in operations if e["mode"] == "compute" and e["operation"] in original
                 and e.get("prior_status") in ("MISSING", "STALE", "RUNNING")]
    verified = [e for e in operations if e["mode"] == "verify"]
    eligible = graph.ancestors(graph.incumbent) & set(state["checkpoint_valid_artifacts"])
    reused = set(recovery["reused_for_final_delivery"]) & eligible
    result = {"redundant_compute_cpu_s": sum(e["cpu_s"] for e in redundant),
              "required_suffix_cpu_s": sum(e["cpu_s"] for e in necessary),
              "verification_cpu_s": sum(e["cpu_s"] for e in verified),
              "redundant_operations": len(redundant), "verification_operations": len(verified),
              "eligible_valid_old_artifacts": len(eligible), "reused_valid_old_artifacts": len(reused),
              "valid_reuse_rate": len(reused)/len(eligible) if eligible else None,
              "duplicate_proposals": sum(e["event"] == "duplicate_proposal" for e in events),
              "invalid_model_outputs": sum(e["event"] == "invalid_model_output" for e in events),
              "rejected_proposals": sum(e["event"] == "proposal_rejected" for e in events),
              "validation_improvement": graph.score-state["checkpoint_score"],
              "logical_total_api_usd": state["budget"]["api_spent"],
              "logical_total_cpu_s": state["budget"]["cpu_spent"]+state["checkpoint_cpu_s"],
              "planning_api_usd": sum(c["logical_cost_usd"] for c in state["calls"]
                                      if c["purpose"] in ("propose", "recover", "select"))}
    result["planning_cost_fraction"] = (result["planning_api_usd"]/state["budget"]["api_spent"]
                                        if state["budget"]["api_spent"] else None)
    completions = [e for e in events if e["event"] == "plan_completed"]
    for label, rows in (("first_delivery", completions),
                        ("first_original_task", [e for e in completions if e["target"] in state["checkpoint_targets"]]),
                        ("first_improvement", [e for e in events if e["event"] == "incumbent_improved"])):
        first = rows[0] if rows else None
        for suffix, field in (("usd", "api_usd"), ("cpu_s", "cpu_total_s"),
                              ("wall_s", "wall_total_s"), ("calls", "calls")):
            result[label+"_"+suffix] = first.get(field) if first else None
        result[label+"_reached"] = first is not None
    result["terminal_gain_prediction_mae"] = (sum(abs(e["predicted_gain"]-e["actual_gain"]) for e in completions)
                                               /len(completions) if completions else None)
    return result
