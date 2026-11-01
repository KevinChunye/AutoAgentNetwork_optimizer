"""The automatic gates of a PHOENIX family arm (research/phoenix_science/prereg.md, "Family arms"), read-only.

Kevin (2026-11-01): no separate pilot; the first slice of the real run is checked and, if it passes, the arm continues.
Prints a JSON verdict; exit 0 = GO, 1 = NO-GO.

calibration: after slices g1-g3 (tasks 0, 10, 20 of every model). GO if, for every model, status.json has no
  error_type and a status of running or completed, calibration_state.json has no pending task, and the gate batches
  report every branch's state as committed and pushed. Truncated and refused replies (stop_reason "refusal", an
  empty reply that the engine scores as an invalid output; audit SC-10) are counted and reported per model.
matrix: after the gate batch (first case per dataset x 3 methods). GO if every gate branch has a terminal status
  (FINISHED) without error_type or unknown model charge, spent at most its budget, has frozen.json, invalid model
  outputs plus truncated calls are at most 10% of the gate's model calls, and the batch reports every branch's state
  as committed and pushed. Refusals are reported per model (they are also invalid outputs, so they count).

Usage: python scripts/phoenix_family_gate.py calibration --prefix fam_claude --models haiku_low sonnet_low opus_med
       python scripts/phoenix_family_gate.py matrix --manifest configs/experiments/phoenix_science/family/claude/study_manifest.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

FINISHED = {"completed", "validation_ceiling", "no_positive_feasible_plan", "limits_reached", "budget_stopped"}
TRUNCATED = ("max_tokens", "length")
REFUSED = ("refusal", "content_filter")
PUSHED = ("committed and pushed", "nothing new to checkpoint")
MAX_BAD_SHARE = 0.10


def read_json(path: Path):
    return json.loads(path.read_text()) if path.exists() else None


def calibration_gate(results: Path, prefix: str, models: list[str], gate_labels=("g1", "g2", "g3")) -> dict:
    rows = []
    for model in models:
        run = results / f"{prefix}_cal_{model}"
        status, state = read_json(run / "status.json") or {}, read_json(run / "calibration_state.json") or {}
        outputs = list((state.get("outputs") or {}).values())
        truncated = sum(o.get("stop_reason") in TRUNCATED for o in outputs)
        refused = sum(o.get("stop_reason") in REFUSED for o in outputs)
        rows.append({"model": model, "status": status.get("status"), "error_type": status.get("error_type"),
                     "done": len(state.get("done", [])), "pending": state.get("pending"), "calls": len(outputs),
                     "truncated": truncated, "refused": refused, "spent": round(state.get("spent", 0.0), 4)})
    frame = pd.DataFrame(rows)
    syncs = []
    for label in gate_labels:
        batch = read_json(results / f"{prefix}_cal_batch_{label}" / "batch_status.json") or {"branches": []}
        syncs += [b.get("state_sync") for b in batch["branches"]]
    ok_models = (frame["error_type"].isna() & frame["pending"].isna() & frame["status"].isin(["running", "completed"]))
    pushed = bool(syncs) and all(s in PUSHED for s in syncs)
    return {"gate": "calibration", "models": frame.to_dict("records"), "state_pushed": pushed,
            "go": bool(ok_models.all()) and pushed}


def matrix_gate(manifest: dict, results: Path) -> dict:
    gate = [b for b in manifest["branches"] if b.get("gate")]
    rows, calls = [], []
    for b in gate:
        run = results / b["name"]
        status = read_json(run / "status.json") or {}
        events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines() if x] \
            if (run / "events.jsonl").exists() else []
        branch_calls = [json.loads(x) for x in (run / "calls.jsonl").read_text().splitlines() if x] \
            if (run / "calls.jsonl").exists() else []
        calls += [{"branch": b["name"], "model": c["model_ref"], "purpose": c["purpose"],
                   "truncated": c["output"]["stop_reason"] in TRUNCATED,
                   "refused": c["output"]["stop_reason"] in REFUSED} for c in branch_calls]
        rows.append({"branch": b["name"], "policy": b["policy"], "status": status.get("status"),
                     "error_type": status.get("error_type"), "unknown_cost": bool(status.get("unknown_model_cost")),
                     "spent": status.get("new_api_bill_usd", 0.0), "budget": b["budget"],
                     "frozen": (run / "frozen.json").exists(), "calls": len(branch_calls),
                     "invalid": sum(e.get("event") == "invalid_model_output" for e in events)})
    frame = pd.DataFrame(rows)
    call_frame = pd.DataFrame(calls, columns=["branch", "model", "purpose", "truncated", "refused"])
    n_calls = len(call_frame)
    bad = int(frame["invalid"].sum() + call_frame["truncated"].sum()) if len(frame) else 0
    batch = read_json(results / f"{manifest['arm']}_batch_gate" / "batch_status.json") or {"branches": []}
    pushed = bool(batch["branches"]) and all(r.get("state_sync") in PUSHED for r in batch["branches"])
    checks = {"terminal_status": bool(len(frame)) and bool(frame["status"].isin(FINISHED).all()),
              "no_error": bool(frame["error_type"].isna().all()) if len(frame) else False,
              "no_unknown_charge": not bool(frame["unknown_cost"].any()) if len(frame) else False,
              "within_budget": bool((frame["spent"] <= frame["budget"] + 1e-9).all()) if len(frame) else False,
              "frozen": bool(frame["frozen"].all()) if len(frame) else False,
              "bad_share_ok": (bad / n_calls if n_calls else 0.0) <= MAX_BAD_SHARE,
              "state_pushed": pushed}
    by_model = (call_frame.groupby(["model", "purpose"]).agg(calls=("truncated", "size"), truncated=("truncated", "sum"),
                                                              refused=("refused", "sum"))
                .reset_index().to_dict("records"))
    return {"gate": "matrix", "branches": frame.to_dict("records"), "calls_by_model": by_model,
            "bad_calls": bad, "calls": n_calls, "checks": checks, "go": all(checks.values())}


def main() -> int:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="mode", required=True)
    c = sub.add_parser("calibration")
    c.add_argument("--prefix", required=True)
    c.add_argument("--models", nargs="+", required=True)
    c.add_argument("--results", default="results")
    m = sub.add_parser("matrix")
    m.add_argument("--manifest", required=True)
    m.add_argument("--results", default="results")
    args = p.parse_args()
    if args.mode == "calibration":
        out = calibration_gate(Path(args.results), args.prefix, args.models)
    else:
        out = matrix_gate(json.loads(Path(args.manifest).read_text()), Path(args.results))
    print(json.dumps(out, indent=2, default=str))
    return 0 if out["go"] else 1


if __name__ == "__main__":
    sys.exit(main())
