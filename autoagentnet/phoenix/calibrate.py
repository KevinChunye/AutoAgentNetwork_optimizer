"""Explicit training-internal calibration jobs. Nothing runs on import.

Schema/execution failures are observations. Transport failures stop the job and are
not mislabeled as a model's task-solving failure. Call outputs are durable before tools.
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

from ..agents.agent import prompt_text
from ..agents.spec import AgentOutput, AgentRequest
from ..budget import BudgetExceeded
from ..providers.base import TRUNCATED_STOP_REASONS, estimate_tokens
from .data import context, load_search
from .planner import CapabilityTable, Observation, Step, closure, terminal_category
from .prompts import parse_json, request_for
from .store import ArtifactStore, atomic_json
from .tools import ToolFailure, ToolRunner
from .types import Graph, PipelineSpec, Proposal, Resources, digest
from .engine import check_action_shape
from .workflow import add_pipeline, compile_proposal


class CalibrationBudgetStop(RuntimeError):
    pass


class MeteredTools:
    """Count calibration's real CPU work as well as its model work."""
    def __init__(self, runner, cfg, state, state_path, clock, dataset):
        self.runner, self.cfg, self.state, self.path, self.clock = runner, cfg, state, state_path, clock
        self.dataset = dataset

    def run(self, graph, step):
        s = self.state
        elapsed = self.clock()
        if (s["cpu_spent"] >= self.cfg.cpu_budget_s or s["tools"] >= self.cfg.max_tools or elapsed >= self.cfg.wall_s):
            s["status"] = "budget_stopped"
            atomic_json(self.path, s)
            raise CalibrationBudgetStop("calibration tool/CPU/wall budget reached")
        s["tools"] += 1
        stage_prediction = step.mode == "compute" and graph.operations[step.operation].kind == "predict"
        try:
            row = self.runner.run(graph, step, cpu_left=self.cfg.cpu_budget_s-s["cpu_spent"],
                                  wall_left=self.cfg.wall_s-elapsed, stage_only=stage_prediction)
            s["cpu_spent"] += row["cpu_s"]
            if step.mode == "verify":
                s["observations"].append(Observation(kind=graph.operations[step.operation].kind,
                    dataset=self.dataset, partition="calibration", mode="verify", completed=True,
                    api_usd=0, cpu_s=row["cpu_s"]).model_dump())
        except ToolFailure as exc:
            s["cpu_spent"] += exc.cpu_s
            s["observations"].append(Observation(kind=graph.operations[step.operation].kind,
                category=graph.operations[step.operation].params.get("classifier", "generic"),
                dataset=self.dataset, partition="calibration", mode=step.mode, completed=False,
                api_usd=0, cpu_s=exc.cpu_s).model_dump())
            raise
        finally:
            s["elapsed_s"] = self.clock()
            atomic_json(self.path, s)
        if stage_prediction:
            self.run(graph, Step(operation=step.operation, mode="verify"))
        return row


async def _calibrate_tasks(cfg, caller, out, free=False):
    paths = cfg.calibration_data
    for path in paths:
        if load_search(path).partition != "calibration":
            raise ValueError("calibration is restricted to training-internal partitions")
    fingerprint = digest({"config": cfg.model_dump(exclude={"task_offset", "task_limit"}),
                          "data": [load_search(p).signature for p in paths]})
    state_path = out / "calibration_state.json"
    state = (json.loads(state_path.read_text()) if state_path.exists() else
             {"fingerprint": fingerprint, "outputs": {}, "observations": [], "done": [], "spent": 0.0,
              "pending": None, "status": "running", "cpu_spent": 0.0, "tools": 0, "elapsed_s": 0.0})
    if state["fingerprint"] != fingerprint:
        raise ValueError("calibration resume inputs changed")
    if state["status"] != "running":
        return {"status": state["status"], "logical_api_usd": state["spent"], "tasks": len(state["done"])}
    count = min(cfg.max_calls, 30)
    start, previous_elapsed = time.monotonic(), state["elapsed_s"]
    clock = lambda: previous_elapsed + time.monotonic()-start
    stop = count if cfg.task_limit is None else min(count, cfg.task_offset+cfg.task_limit)
    for index in range(cfg.task_offset, stop):
        if clock() >= cfg.wall_s:
            state["status"] = "wall_stopped"
            break
        key = str(index)
        if key in state["done"]:
            continue
        data_path = paths[index % len(paths)]
        data = load_search(data_path)
        family = ("design", "diagnose", "plan")[index // 10]
        graph = Graph(context=context(data))
        store = ArtifactStore(out / f"task_{index}" / "artifacts")
        tool = MeteredTools(ToolRunner(data_path, store.root, out / f"task_{index}" / "work", cfg.tool_timeout_s),
                            cfg, state, state_path, clock, data.dataset)
        # A genuine baseline run supplies observations for diagnosis; no invented failure.
        baseline_target = add_pipeline(graph, PipelineSpec(classifier="knn", neighbors=11), index)
        baseline_rows = []
        for step in closure(graph, baseline_target, store)[0]:
            result = tool.run(graph, step)
            baseline_rows.append(Observation(kind=graph.operations[step.operation].kind, dataset=data.dataset,
                category=graph.operations[step.operation].params.get("classifier", "generic"),
                partition="calibration", completed=True, api_usd=0, cpu_s=result["cpu_s"]).model_dump())
        baseline_score = store.load(graph.operations[baseline_target], graph)["score"]
        graph.incumbent, graph.score = baseline_target, baseline_score
        snapshot = {"case_id": f"calibration_{cfg.calibration_model}_{index}", "dataset": data.dataset,
                    "family": family, "task": {"design": "design a different classification pipeline",
                    "diagnose": "improve the observed baseline; do not assume the baseline failed",
                    "plan": "provide an executable alternative pipeline that can reuse standard preprocessing"}[family],
                    "baseline": {"pipeline": PipelineSpec(classifier="knn", neighbors=11).model_dump(),
                                 "validation_score": baseline_score},
                    "shape": {"rows": len(data.y_train), "features": data.x_train.shape[1]},
                    "partition": "calibration", "available_models": cfg.models,
                    "known_targets": [baseline_target]}
        request = request_for(snapshot, "propose" if family == "plan" else "calibrate",
                              cfg.calibration_model, "calibration", cfg.max_tokens,
                              cfg.max_input_tokens)
        if key not in state["outputs"]:
            if state["pending"] and state["pending"]["index"] != key:
                raise ValueError("a different calibration task has an unresolved call")
            worst = 0.0 if free else caller.pricebook.worst_case_usd(
                caller.registry.model_id(cfg.calibration_model), caller.registry.provider_of(cfg.calibration_model),
                estimate_tokens(prompt_text(request.spec, request.input)), request.spec.max_tokens)
            if state["spent"]+worst > cfg.api_budget_usd:
                state["status"] = "budget_stopped"
                break
            if state["pending"] is None:
                state["pending"] = {"index": key, "request": request.model_dump(), "worst": worst}
                atomic_json(state_path, state)
            try:
                request = AgentRequest.model_validate(state["pending"]["request"])
                output = await asyncio.wait_for(caller.call(request, index+1), timeout=max(0.01, cfg.wall_s-clock()))
            except BudgetExceeded:
                state["status"] = "budget_stopped"
                state["pending"] = None
                atomic_json(state_path, state)
                raise CalibrationBudgetStop("project governor refused calibration")
            except Exception:
                state["status"] = "error_unknown_model_cost"
                state["spent"] += worst
                atomic_json(state_path, state)
                raise
            state["outputs"][key] = output.model_dump()
            state["elapsed_s"] = clock()
            state["spent"] += output.cost_usd
            state["pending"] = None
            atomic_json(state_path, state)
        output = AgentOutput.model_validate(state["outputs"][key])
        completed, quality, tool_rows, cpu = False, None, list(baseline_rows), 0.0
        state["last_task_error"] = None  # per task (audit SC-4: it used to carry over from an earlier task)
        try:
            if output.stop_reason in TRUNCATED_STOP_REASONS:
                raise ValueError("truncated calibration reply")
            raw = parse_json(output.content)
            if family == "plan":
                if set(raw) != {"proposals"} or not 1 <= len(raw["proposals"]) <= 3:
                    raise ValueError("calibration requires one to three local proposals")
                # Score the first proposal that compiles to a NEW executable artifact, rejecting bad ones one at a
                # time as the study engine does (it considers every proposal); the reply fails only if none
                # qualifies (prereg Amendment 3). A proposal that compiles to an existing artifact (e.g. RECOMPUTE or
                # INHERIT of the valid baseline) proposes nothing new, so the baseline's score is never credited.
                target, rejected = None, []
                for item in raw["proposals"]:
                    try:
                        proposal = Proposal.model_validate(item)
                        check_action_shape(proposal)
                        if proposal.action == "ABANDON" or (proposal.model and not proposal.pipelines):
                            raise ValueError("not a complete executable alternative")
                        existing = set(graph.operations)
                        candidate = compile_proposal(graph, proposal, Resources(models=cfg.models), index).target
                        if candidate in existing:
                            raise ValueError("compiles to an existing artifact")
                        target = candidate
                        break
                    except (ValueError, KeyError, TypeError) as exc:
                        rejected.append(str(exc)[:160])
                if target is None:
                    raise ValueError("no proposal compiled to a new executable alternative: " + " | ".join(rejected))
            else:
                if set(raw) != {"pipeline"}:
                    raise ValueError("calibration requires one executable pipeline")
                spec = PipelineSpec.model_validate(raw["pipeline"])
                target = add_pipeline(graph, spec, index)
            for step in closure(graph, target, store)[0]:
                result = tool.run(graph, step)
                cpu += result["cpu_s"]
                tool_rows.append(Observation(kind=graph.operations[step.operation].kind, dataset=data.dataset,
                    category=graph.operations[step.operation].params.get("classifier", "generic"),
                    partition="calibration", completed=True, api_usd=0, cpu_s=result["cpu_s"]).model_dump())
            quality = store.load(graph.operations[target], graph)["score"]
            completed = True
        except (ValueError, KeyError, TypeError, ToolFailure) as exc:
            if isinstance(exc, ToolFailure):
                cpu += exc.cpu_s
            state["last_task_error"] = str(exc)[:500]
        state["observations"].extend(tool_rows)
        state["observations"].append(Observation(kind="design", model=cfg.calibration_model, dataset=data.dataset,
            task_family=family,
            partition="calibration", completed=completed, quality=quality,
            api_usd=output.cost_usd, cpu_s=0).model_dump())
        state["observations"].append(Observation(kind="pipeline", dataset=data.dataset, partition="calibration",
            category=terminal_category(graph, target) if completed else "generic",
            completed=completed, quality=quality, api_usd=0, cpu_s=cpu).model_dump())
        # Ensembles are deterministic tools; measure an actual merge, rather than invent a timing.
        if completed:
            from .workflow import add_ensemble
            merge_target = target
            if merge_target == baseline_target:
                merge_target = add_pipeline(graph, PipelineSpec(classifier="logistic", c=10.0), index)
                for step in closure(graph, merge_target, store)[0]:
                    result = tool.run(graph, step)
                    state["observations"].append(Observation(kind=graph.operations[step.operation].kind,
                        category=graph.operations[step.operation].params.get("classifier", "generic"),
                        dataset=data.dataset, partition="calibration", completed=True, api_usd=0,
                        cpu_s=result["cpu_s"]).model_dump())
            merged = add_ensemble(graph, [baseline_target, merge_target])
            merge_cpu = 0.0
            for step in closure(graph, merged, store)[0]:
                result = tool.run(graph, step)
                merge_cpu += result["cpu_s"]
                state["observations"].append(Observation(kind=graph.operations[step.operation].kind,
                    dataset=data.dataset, partition="calibration", completed=True, api_usd=0,
                    cpu_s=result["cpu_s"]).model_dump())
            state["observations"].append(Observation(kind="pipeline", category="ensemble",
                dataset=data.dataset, partition="calibration", completed=True,
                quality=store.load(graph.operations[merged], graph)["score"], api_usd=0,
                cpu_s=merge_cpu).model_dump())
        state["done"].append(key)
        atomic_json(state_path, state)
    if state["status"] == "running" and len(state["done"]) == count:
        state["status"] = "completed"
    atomic_json(state_path, state)
    table = CapabilityTable(records=[Observation.model_validate(r) for r in state["observations"]], synthetic=free,
                            complete=state["status"] == "completed")
    atomic_json(out / "capability_table.json", table.model_dump())
    atomic_json(out / "calls.json", state["outputs"])
    return {"status": state["status"], "tasks": len(state["done"]), "logical_api_usd": state["spent"],
            "offline_fixture": free}


async def run_calibration(cfg, caller, out, free=False):
    try:
        return await _calibrate_tasks(cfg, caller, out, free)
    except CalibrationBudgetStop:
        state = json.loads((out / "calibration_state.json").read_text())
        table = CapabilityTable(records=[Observation.model_validate(r) for r in state["observations"]], synthetic=free,
                                complete=False)
        atomic_json(out / "capability_table.json", table.model_dump())
        return {"status": state["status"], "tasks": len(state["done"]), "logical_api_usd": state["spent"],
                "cpu_s": state["cpu_spent"], "offline_fixture": free}


def combine_tables(paths, out):
    records, synthetic, complete = [], False, True
    for path in paths:
        table = CapabilityTable.model_validate_json(Path(path).read_text())
        records.extend(table.records)
        synthetic = synthetic or table.synthetic
        complete = complete and table.complete
    combined = CapabilityTable(records=records, synthetic=synthetic, complete=complete)
    atomic_json(out, combined.model_dump())
    return combined
