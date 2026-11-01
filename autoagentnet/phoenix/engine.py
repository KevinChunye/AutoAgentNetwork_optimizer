"""Transactional, bounded recovery loop. A single state snapshot is authoritative.

Model-call intent is committed before calling. Exact cached requests recover a crash
between a billed response and state commit without paying for that response twice.
"""
from __future__ import annotations

import asyncio
import json
import shutil
import time
from pathlib import Path

from pydantic import Field

from ..agents.agent import prompt_text
from ..agents.spec import AgentOutput, AgentRequest
from ..budget import BudgetExceeded
from ..providers.base import TRUNCATED_STOP_REASONS, estimate_tokens
from .checkpoint import branch_checkpoint
from .data import load_search
from .planner import CapabilityTable, Step, closure, rank_plans, select
from .prompts import parse_json, request_for
from .store import ArtifactStore, atomic_json, file_sha
from .tools import ToolFailure, ToolRunner
from .types import Budget, Graph, Operation, PipelineSpec, Plan, Proposal, Resources, Status, Strict, WorkTask, digest
from .workflow import add_pipeline, compile_proposal


class RecoveryState(Strict):
    fingerprint: str
    case_id: str
    graph: Graph
    resources: Resources
    budget: Budget
    checkpoint_targets: list[str]
    checkpoint_artifacts: list[str]
    checkpoint_operations: list[str] = Field(default_factory=list)
    checkpoint_valid_artifacts: list[str] = Field(default_factory=list)
    checkpoint_payload_hashes: dict[str, str] = Field(default_factory=dict)
    checkpoint_score: float = 0
    checkpoint_cpu_s: float = 0
    plans: list[Plan] = Field(default_factory=list)
    events: list[dict] = Field(default_factory=list)
    calls: list[dict] = Field(default_factory=list)
    trajectory: list[dict] = Field(default_factory=list)
    pending_call: dict | None = None
    pending_tool: dict | None = None
    choice: str | None = None
    need_proposal: bool = True
    proposal_rounds: int = 0
    turn: int = 0
    elapsed_s: float = 0
    status: str = "ready"
    unknown_cost: bool = False


def check_action_shape(proposal) -> None:
    """Reject a proposal whose pipelines its action would ignore. INHERIT, VERIFY, RECOMPUTE and ABANDON act on an
    existing target and take no pipeline (compile_proposal would silently drop one); a new pipeline belongs in
    REROUTE (one) or SPLIT (two). Rejected proposals are recorded as such; nothing is dropped silently."""
    if proposal.pipelines and proposal.action in ("INHERIT", "VERIFY", "RECOMPUTE", "ABANDON"):
        raise ValueError(f"{proposal.action} takes an existing target and no pipelines; "
                         "a new pipeline needs REROUTE (one) or SPLIT (two)")


def compact_estimate(estimate: dict) -> dict:
    """An Estimate as shown in a model request, with its numbers rounded: success probability and quality samples
    to 4 decimals, dollars to 6, CPU seconds to 2. The planner itself always uses the unrounded table; rounding
    only keeps the request under the input-token cap on the science tables (docs/PHOENIX_SCIENCE_ADDENDUM.md)."""
    return {**estimate, "success": round(estimate["success"], 4), "api_usd": round(estimate["api_usd"], 6),
            "cpu_s": round(estimate["cpu_s"], 2), "qualities": [round(q, 4) for q in estimate["qualities"]]}


class ScientificBudgetExceeded(RuntimeError):
    pass


class RecoveryEngine:
    def __init__(self, cfg, caller, out, state, table, free=False, tool_factory=ToolRunner):
        self.cfg, self.caller, self.out, self.state = cfg, caller, Path(out), state
        self.table, self.free = table, free
        self.data = load_search(self.out / "search.npz")
        self.store = ArtifactStore(self.out / "artifacts")
        self.tool = tool_factory(self.out / "search.npz", self.store.root, self.out / "tool_work", cfg.tool_timeout_s)
        self.session_start = time.monotonic()
        self.saved_elapsed = state.elapsed_s

    @classmethod
    def open(cls, cfg, caller, out, free=False, tool_factory=ToolRunner):
        from .run import frozen_inputs
        out = Path(out)
        source_hashes = {p.name: file_sha(p) for p in Path(__file__).parent.glob("*.py")}
        fingerprint = digest({"config": cfg.model_dump(), "inputs": frozen_inputs(cfg), "code": source_hashes})
        state_path = out / "state.json"
        table = (CapabilityTable.model_validate_json(Path(cfg.capability_table).read_text())
                 if cfg.capability_table else CapabilityTable.fake())
        if table.synthetic and not free:
            raise ValueError("synthetic calibration cannot drive a paid recovery")
        if state_path.exists():
            state = RecoveryState.model_validate_json(state_path.read_text())
            if state.fingerprint != fingerprint:
                raise ValueError("resume configuration, inputs, or code changed; use a new run name")
        else:
            raw = branch_checkpoint(cfg.checkpoint, out)
            graph = Graph.model_validate(raw["graph"])
            resources = Resources(models=cfg.models)
            state = RecoveryState(fingerprint=fingerprint,
                                  case_id=f'{raw["dataset"]}_{raw["template"]}_{raw["seed"]}',
                                  graph=graph, resources=resources,
                                  budget=Budget(api_limit=cfg.api_budget_usd, cpu_limit=cfg.cpu_budget_s,
                                                call_limit=cfg.max_calls, tool_limit=cfg.max_tools),
                                  checkpoint_targets=[t.target for t in graph.tasks.values()],
                                  checkpoint_artifacts=[name[:-7] for name in raw["inventory"] if name.endswith(".joblib")],
                                  checkpoint_operations=list(raw["graph"]["operations"]),
                                  checkpoint_payload_hashes={name[:-7]: sha for name, sha in raw["inventory"].items()
                                                             if name.endswith(".joblib")},
                                  checkpoint_valid_artifacts=[key for key in graph.operations
                                      if ArtifactStore(out / "artifacts").status(graph.operations[key], graph) == Status.VALID],
                                  checkpoint_score=graph.score, checkpoint_cpu_s=raw["checkpoint_cpu_s"])
            if cfg.fault != "healthy":
                released = graph.shutdown(cfg.shutdown_member)
                withdrawn = cfg.withdrawn_model if cfg.fault == "F1" else None
                resources.fault(cfg.shutdown_member, withdrawn)
                state.events.append({"event": "shutdown", "member": cfg.shutdown_member,
                                     "fault": cfg.fault, "withdrawn_model": withdrawn, "released": released})
            state.plans = cls.deterministic_plans(graph, state.checkpoint_targets, cfg.seed)
        engine = cls(cfg, caller, out, state, table, free, tool_factory)
        engine.save()
        return engine

    @staticmethod
    def deterministic_plans(graph, targets, seed):
        plans = [Plan(action="RECOMPUTE", target=t, reason="original minimal suffix") for t in targets]
        # Same executable alternative is available to every method, not privileged to PHOENIX.
        alternative = add_pipeline(graph, PipelineSpec(classifier="knn", neighbors=5), seed)
        plans.append(Plan(action="REROUTE", target=alternative, reason="deterministic alternative"))
        if targets:
            plans.append(Plan(action="VERIFY", target=targets[0], reason="validate committed intermediate"))
        return plans[:3]

    def event(self, name, **fields):
        self.state.events.append({"event": name, "index": len(self.state.events),
                                  "worker": self.worker(), "api_usd": self.state.budget.api_spent,
                                  "cpu_total_s": self.state.budget.cpu_spent,
                                  "calls": self.state.budget.calls, "tools": self.state.budget.tools,
                                  "wall_total_s": self.saved_elapsed+time.monotonic()-self.session_start,
                                  **fields})

    def worker(self):
        return self.state.resources.workers[self.state.turn % len(self.state.resources.workers)]

    def save(self):
        self.state.elapsed_s = self.saved_elapsed + time.monotonic()-self.session_start
        atomic_json(self.out / "state.json", self.state.model_dump())

    def snapshot(self, candidates=None):
        s, g = self.state, self.state.graph
        rows = []
        for key, op in g.operations.items():
            status = self.store.status(op, g)
            row = [key[:12], op.kind, [p[:12] for p in op.parents], status.value, op.params]
            if op.kind == "validate" and status == Status.VALID:
                row.append(self.store.load(op, g)["score"])
            rows.append(row)
        return {"case_id": s.case_id, "dataset": self.data.dataset,
                "shape": {"train_rows": len(self.data.y_train), "validation_rows": len(self.data.y_val),
                          "features": self.data.x_train.shape[1]},
                "incumbent": {"target": g.incumbent[:12], "score": g.score},
                "available_models": s.resources.models, "available_tools": s.resources.tools,
                "budget": s.budget.model_dump(), "nodes": rows,
                "pending_targets": [t[:12] for t in s.checkpoint_targets
                                    if self.store.status(g.operations[t], g) != Status.VALID],
                "capability_estimates": [{"kind": kind, "model": model, "category": category, "mode": mode,
                    **compact_estimate(self.table.estimate(kind, model, self.data.dataset, category, mode).model_dump())}
                    for kind, model, category, mode in dict.fromkeys(
                        (r.kind, r.model, r.category, r.mode) for r in self.table.records)],
                "candidates": candidates or [], "recent_events": s.events[-6:], "extra_artifacts": []}

    def resolve_target(self, value):
        if value in self.state.graph.operations:
            return value
        matches = [k for k in self.state.graph.operations if value and k.startswith(value)]
        if len(matches) != 1:
            raise ValueError("unknown or ambiguous artifact reference")
        return matches[0]

    def accept(self, raw):
        proposal = Proposal.model_validate(raw)
        check_action_shape(proposal)
        if proposal.target:
            proposal.target = self.resolve_target(proposal.target)
        if proposal.action == "ABANDON":
            if proposal.target in self.state.graph.ancestors(self.state.graph.incumbent):
                raise ValueError("incumbent and required dependencies cannot be abandoned")
            self.state.plans = [p for p in self.state.plans if p.target != proposal.target]
            for task in self.state.graph.tasks.values():
                if task.target == proposal.target:
                    task.abandoned = True
            self.event("abandon", target=proposal.target, reason=proposal.reason)
            return None
        plan = compile_proposal(self.state.graph, proposal, self.state.resources, self.cfg.seed)
        if any(p.id == plan.id for p in self.state.plans) or self.store.status(
                self.state.graph.operations[plan.target], self.state.graph) == Status.VALID:
            self.event("duplicate_proposal", target=plan.target)
        if not any(p.id == plan.id for p in self.state.plans):
            self.state.plans.append(plan)
        return plan

    def worst_cost(self, request):
        registry = self.caller.registry
        ref = request.spec.model
        if registry.provider_of(ref) == "fake":
            return 0.0
        return self.caller.pricebook.worst_case_usd(registry.model_id(ref), registry.provider_of(ref),
                                                   estimate_tokens(prompt_text(request.spec, request.input)),
                                                   request.spec.max_tokens)

    async def ask(self, purpose, model=None, candidates=None, operation=None):
        s = self.state
        if s.pending_call is None:
            model = model or self.cfg.planner_model
            if model not in s.resources.models:
                raise ValueError("execution model withdrawn")
            snapshot = self.snapshot(candidates)
            if operation:
                snapshot["design_task"] = s.graph.operations[operation].params
            request = request_for(snapshot, purpose, model, self.worker(), self.cfg.max_tokens,
                                  self.cfg.max_input_tokens)
            worst = self.worst_cost(request)
            if not s.budget.allows(api=worst, calls=1):
                raise ScientificBudgetExceeded("model's worst-case reservation exceeds remaining scientific budget")
            s.budget.calls += 1
            s.pending_call = {"request": request.model_dump(), "purpose": purpose, "operation": operation,
                              "worst_usd": worst, "output": None, "charged": False}
            self.event("call_intent", model=model, purpose=purpose)
            self.save()
        await self.finish_call()

    async def finish_call(self):
        s, pending = self.state, self.state.pending_call
        if pending is None:
            return
        req = AgentRequest.model_validate(pending["request"])
        if req.spec.agent_id not in s.resources.workers or req.spec.model not in s.resources.models:
            raise ValueError("pending call belongs to a withdrawn worker/model")
        if pending["output"] is None:
            try:
                output = await asyncio.wait_for(self.caller.call(req, self.cfg.seed + 1000 * self.cfg.draw),
                                                timeout=max(0.01, self.cfg.wall_s-s.elapsed_s))
            except BudgetExceeded:
                s.budget.calls -= 1
                s.pending_call = None
                self.event("governor_refused")
                self.save()
                raise
            except asyncio.CancelledError:
                s.budget.api_spent += pending["worst_usd"]
                s.pending_call = None
                s.unknown_cost = True
                s.status = "error_unknown_model_cost"
                self.event("model_cancelled", reserved_unknown_usd=pending["worst_usd"])
                self.save()
                raise
            except Exception:
                # A transport error can hide a billed request. Do not silently retry.
                s.budget.api_spent += pending["worst_usd"]
                s.pending_call = None
                s.unknown_cost = True
                s.status = "error_unknown_model_cost"
                self.event("model_error", reserved_unknown_usd=pending["worst_usd"])
                self.save()
                raise
            pending["output"] = output.model_dump()
            s.budget.api_spent += output.cost_usd
            pending["charged"] = True
            s.calls.append({"purpose": pending["purpose"], "request_hash": digest(pending["request"]),
                            "worker": req.spec.agent_id, "model_ref": req.spec.model,
                            "output": output.model_dump(), "logical_cost_usd": output.cost_usd})
            self.save()  # durably save output/charge BEFORE parsing and applying its action
            if s.budget.api_spent > s.budget.api_limit + 1e-12:
                raise ScientificBudgetExceeded("actual usage exceeded its conservative reservation; stop and audit")
        self.apply_call(pending)
        s.pending_call = None
        self.save()

    def apply_call(self, pending):
        output = AgentOutput.model_validate(pending["output"])
        purpose = pending["purpose"]
        try:
            if output.stop_reason in TRUNCATED_STOP_REASONS:
                raise ValueError("truncated reply")
            raw = parse_json(output.content)
            if purpose == "propose":
                if set(raw) != {"proposals"} or not isinstance(raw["proposals"], list) or len(raw["proposals"]) > 3:
                    raise ValueError("at most three proposals are permitted")
                for item in raw["proposals"]:
                    try:
                        plan = self.accept(item)
                        if plan:
                            self.event("proposal", plan=plan.model_dump(), plan_id=plan.id)
                    except (ValueError, KeyError) as exc:
                        self.event("proposal_rejected", reason=str(exc)[:300])
            elif purpose == "select":
                if raw == {"stop": True}:
                    self.state.choice = "STOP"
                elif set(raw) == {"plan_id"} and any(p.id == raw["plan_id"] for p in self.state.plans):
                    self.state.choice = raw["plan_id"]
                else:
                    raise ValueError("selector returned an unknown plan")
            elif purpose == "recover":
                if raw == {"stop": True}:
                    self.state.choice = "STOP"
                else:
                    plan = self.accept(raw)
                    if plan and plan.action == "INHERIT" and self.store.status(
                            self.state.graph.operations[plan.target], self.state.graph) == Status.VALID:
                        self.update_incumbent()
                        self.state.choice = "STOP"
                    else:
                        self.state.choice = plan.id if plan else None
            elif purpose == "design":
                if set(raw) != {"pipeline"}:
                    raise ValueError("design must return only pipeline")
                spec = PipelineSpec.model_validate(raw["pipeline"])
                op = self.state.graph.operations[pending["operation"]]
                self.store.put(op, self.state.graph, {"pipeline": spec.model_dump()}, 0, output.latency_s,
                               Status.VALID, output.cost_usd, op.model)
                target = add_pipeline(self.state.graph, spec, self.cfg.seed)
                self.state.graph.evidence_links[target] = [op.id]
                self.state.plans = [p for p in self.state.plans if p.target != op.id]
                self.state.plans.append(Plan(action="REROUTE", target=target, reason="completed deferred design"))
                self.event("design_completed", operation=op.id, target=target)
            self.event("call_applied", purpose=purpose)
        except (ValueError, TypeError, KeyError) as exc:
            self.event("invalid_model_output", purpose=purpose, reason=str(exc)[:300])
            if purpose == "design":
                self.state.plans = [p for p in self.state.plans if p.target != pending["operation"]]
                self.state.need_proposal = True

    def update_incumbent(self):
        g = self.state.graph
        for key, op in g.operations.items():
            if op.kind == "validate" and self.store.status(op, g) == Status.VALID:
                score = self.store.load(op, g)["score"]
                if score > g.score:
                    g.incumbent, g.score = key, score
                    self.event("incumbent_improved", target=key, validation_score=score)

    def execute_tool(self, compiled):
        s, g = self.state, self.state.graph
        step = compiled.steps[0]
        task_id = next((t.id for t in g.tasks.values() if t.target == compiled.plan.target and not t.abandoned),
                       compiled.plan.target)
        if task_id not in g.tasks:
            g.tasks[task_id] = WorkTask(id=task_id, target=task_id)
        task = g.tasks[task_id]
        if task.owner not in (None, self.worker()):
            self.event("task_waiting_for_owner", target=task.target)
            return
        version = g.claim(task_id, self.worker(), task.version)
        s.budget.tools += 1
        s.pending_tool = {"task": task_id, "worker": self.worker(), "version": version,
                          "operation": step.operation, "mode": step.mode, "plan": compiled.plan.model_dump(),
                          "prior_status": self.store.status(g.operations[step.operation], g).value,
                          "predicted_gain": compiled.gain, "incumbent_before": g.score}
        self.save()
        self.finish_tool()

    def finish_tool(self):
        s, pending = self.state, self.state.pending_tool
        if pending is None:
            return
        g = s.graph
        op = g.operations[pending["operation"]]
        g.check_owner(pending["task"], pending["worker"], pending["version"])
        acknowledged = False
        try:
            if self.store.status(op, g) == Status.VALID:
                # Crash after tool commit but before state commit: never redo the fit.
                receipt = self.store.receipt(op.id)
                result = {"cpu_s": receipt.cpu_s, "elapsed_s": receipt.elapsed_s,
                          "recovered_from_receipt": True}
            else:
                result = self.tool.run(g, Step(operation=op.id, mode=pending["mode"]),
                                       cpu_left=s.budget.cpu_left,
                                       wall_left=max(0.0, self.cfg.wall_s-s.elapsed_s))
            s.budget.cpu_spent += result["cpu_s"]
            self.event("operation_completed", operation=op.id, kind=op.kind,
                       mode=pending["mode"], prior_status=pending["prior_status"],
                       **{k: v for k, v in result.items() if k != "receipt"})
            self.update_incumbent()
            if self.store.status(g.operations[pending["plan"]["target"]], g) == Status.VALID:
                s.need_proposal = True
                terminal_score = self.store.load(g.operations[pending["plan"]["target"]], g)["score"]
                self.event("plan_completed", target=pending["plan"]["target"],
                           predicted_gain=pending["predicted_gain"],
                           actual_gain=max(0.0, terminal_score-pending["incumbent_before"]))
            acknowledged = True
        except ToolFailure as exc:
            s.budget.cpu_spent += exc.cpu_s
            self.event("operation_failed", operation=op.id, reason=str(exc), cpu_s=exc.cpu_s,
                       elapsed_s=exc.elapsed_s)
            s.plans = [p for p in s.plans if p.target != pending["plan"]["target"]]
            s.need_proposal = True
            acknowledged = True
        finally:
            if acknowledged:
                g.tasks[pending["task"]].owner = None
                s.pending_tool = None
                self.record_trajectory()
                self.save()

    def record_trajectory(self):
        s = self.state
        s.trajectory.append({"step": len(s.trajectory), "api_usd": s.budget.api_spent,
                             "cpu_s": s.budget.cpu_spent, "calls": s.budget.calls,
                             "tools": s.budget.tools, "validation_score": s.graph.score,
                             "target": s.graph.incumbent})

    async def run(self):
        s = self.state
        if s.status not in ("ready", "running"):
            return self.export()
        s.status = "running"
        try:
            if s.pending_call:
                await self.finish_call()
            if s.pending_tool:
                self.finish_tool()
            if self.cfg.fixed_proposals and not any(e["event"] == "fixed_proposals_loaded" for e in s.events):
                raw = json.loads(Path(self.cfg.fixed_proposals).read_text())
                if len(raw["proposals"]) > 3:
                    raise ValueError("fixed proposal pool exceeds three")
                accepted = 0
                for item in raw["proposals"]:
                    try:
                        accepted += self.accept(item) is not None
                    except (ValueError, KeyError, TypeError) as exc:
                        self.event("proposal_rejected", reason=str(exc)[:300])
                # Its independent deployment cost is charged to every replay arm.
                source_cost = float(raw["logical_proposal_cost_usd"])
                source_calls = int(raw["proposal_calls"])
                if not s.budget.allows(api=source_cost, calls=source_calls):
                    raise ScientificBudgetExceeded("frozen proposal cost does not fit")
                s.budget.api_spent += source_cost
                s.budget.calls += source_calls
                s.need_proposal = False
                s.proposal_rounds = self.cfg.proposal_rounds
                self.event("fixed_proposals_loaded", logical_cost_usd=source_cost)
                self.save()
                if raw.get("unavailable") or accepted == 0:
                    s.status = "selector_pool_unavailable"
                    self.save()
                    return self.export()
            while s.elapsed_s < self.cfg.wall_s and s.budget.cpu_left > 0:
                own_cpu = time.thread_time()  # this branch's thread only (a batch runs branches in threads)
                try:
                    self.update_incumbent()
                    if s.graph.score >= 1.0:
                        s.status = "validation_ceiling"
                        break
                    if self.cfg.policy == "fixed":
                        unfinished = [p for p in s.plans if p.target and
                                      self.store.status(s.graph.operations[p.target], s.graph) != Status.VALID]
                        if not unfinished and s.budget.calls < s.budget.call_limit:
                            # Ordinary failover also keeps doing useful work; it is not
                            # deliberately stopped after inheriting its original jobs.
                            model = next((m for m in self.cfg.models if m in s.resources.models), None)
                            if model:
                                op = Operation(kind="design", context=s.graph.context, model=model,
                                               params={"attempt": s.budget.calls, "seed": self.cfg.seed,
                                                       "reason": "fixed-order continuation of incumbent"})
                                key = s.graph.add(op)
                                s.plans.append(Plan(action="REROUTE", target=key))
                    if self.cfg.policy == "llm" and not self.cfg.fixed_proposals:
                        if s.budget.calls >= s.budget.call_limit:
                            break
                        await self.ask("recover")
                    elif (self.cfg.policy not in ("fixed", "static") and s.need_proposal
                          and s.proposal_rounds < self.cfg.proposal_rounds):
                        s.need_proposal = False
                        s.proposal_rounds += 1
                        await self.ask("propose")
                    policy = self.cfg.policy if self.cfg.policy in ("no_dependency", "no_cost", "static") else "full"
                    ranked = rank_plans(s.plans, s.graph, self.store, s.resources, s.budget,
                                        self.table, self.data.dataset, policy)
                    if self.cfg.policy == "llm":
                        if self.cfg.fixed_proposals:
                            await self.ask("select", candidates=[{"id": c.plan.id, "target": c.plan.target,
                                                                 "gain": c.gain, "api_usd": c.api_usd,
                                                                 "cpu_s": c.cpu_s} for c in ranked])
                        if s.choice == "STOP":
                            break
                        chosen = next((c for c in ranked if c.plan.id == s.choice), None)
                        s.choice = None
                        if chosen is None:
                            self.event("no_executable_llm_choice")
                            continue
                    elif self.cfg.policy == "fixed":
                        chosen = next((c for target in s.checkpoint_targets for c in ranked if c.plan.target == target), None)
                        if chosen is None:
                            # Normal failover continues from the incumbent after original jobs.
                            chosen = min(ranked, key=lambda c: (c.api_usd, c.cpu_s, c.plan.id)) if ranked else None
                    else:
                        chosen = select(s.plans, s.graph, self.store, s.resources, s.budget,
                                        self.table, self.data.dataset, policy)
                    if chosen is None:
                        s.status = "no_positive_feasible_plan"
                        break
                    step = chosen.steps[0]
                    op = s.graph.operations[step.operation]
                    self.event("plan_selected", plan_id=chosen.plan.id, target=chosen.plan.target,
                               action=chosen.plan.action, estimated_gain=chosen.gain,
                               estimated_api_usd=chosen.api_usd, estimated_cpu_s=chosen.cpu_s,
                               inherit=chosen.inherit, closure=[x.model_dump() for x in chosen.steps])
                    if op.kind == "design":
                        try:
                            await self.ask("design", model=op.model, operation=op.id)
                        except ScientificBudgetExceeded:
                            # A model may be too expensive even when its median looked feasible.
                            s.plans = [p for p in s.plans if p.id != chosen.plan.id]
                            self.event("plan_reservation_rejected", plan_id=chosen.plan.id)
                            continue
                    else:
                        self.execute_tool(chosen)
                finally:
                    s.budget.cpu_spent += max(0.0, time.thread_time()-own_cpu)
                    s.turn += 1
                    self.save()
            if s.status == "running":
                s.status = "limits_reached" if (s.budget.calls >= s.budget.call_limit or
                                                s.budget.tools >= s.budget.tool_limit or
                                                s.elapsed_s >= self.cfg.wall_s or s.budget.cpu_left <= 0) else "completed"
        except (ScientificBudgetExceeded, BudgetExceeded) as exc:
            s.status = "budget_stopped"
            self.event("budget_stopped", reason=str(exc))
        except Exception as exc:
            if not s.unknown_cost:
                s.status = "error"
            self.event("run_error", error_type=type(exc).__name__, reason=str(exc)[:600])
        self.save()
        return self.export()

    def export(self):
        s = self.state
        needed = s.graph.ancestors(s.graph.incumbent)
        if s.status in ("no_positive_feasible_plan", "limits_reached", "budget_stopped", "validation_ceiling"):
            for task in s.graph.tasks.values():
                if task.target not in needed and not task.abandoned and self.store.status(
                        s.graph.operations[task.target], s.graph) != Status.VALID:
                    task.abandoned = True
                    self.event("abandon_at_stop", target=task.target, reason=s.status)
            self.save()
        atomic_json(self.out / "recovery_plan.json", {
            "final_target": s.graph.incumbent,
            "reused_for_final_delivery": [key for key in needed if key in s.checkpoint_payload_hashes
                and self.store.path(key).is_file() and file_sha(self.store.path(key)) == s.checkpoint_payload_hashes[key]],
            "abandoned": [t.target for t in s.graph.tasks.values() if t.abandoned],
            "deferred": [p.target for p in s.plans if p.target not in needed and
                         self.store.status(s.graph.operations[p.target], s.graph) != Status.VALID],
            "execution_order": [e["operation"] for e in s.events if e["event"] == "operation_completed"],
            "model_assignments": [{"worker": c["worker"], "model_ref": c["model_ref"],
                                   "purpose": c["purpose"]} for c in s.calls]})
        atomic_json(self.out / "frozen.json", {"schema": 1, "fingerprint": s.fingerprint,
                    "case_id": s.case_id, "target": s.graph.incumbent, "validation_score": s.graph.score,
                    "graph": s.graph.model_dump(), "graph_hash": digest(s.graph.model_dump()),
                    "search_signature": self.data.signature, "offline_fixture": self.free,
                    "artifact_inventory": {p.name: file_sha(p) for p in self.store.root.iterdir() if p.is_file()}})
        for name, rows in (("events.jsonl", s.events), ("calls.jsonl", s.calls)):
            temporary = self.out / (name+".pending")
            temporary.write_text("".join(json.dumps(r, sort_keys=True, allow_nan=False)+"\n" for r in rows))
            temporary.replace(self.out / name)
        atomic_json(self.out / "trajectory.json", s.trajectory)
        status = {"status": s.status, "case_id": s.case_id, "policy": self.cfg.policy,
                  "fault": self.cfg.fault, "budget": s.budget.model_dump(), "elapsed_s": s.elapsed_s,
                  "validation_score": s.graph.score, "incumbent": s.graph.incumbent,
                  "unknown_model_cost": s.unknown_cost, "offline_fixture": self.free,
                  "cpu_accounting_incomplete": any(e.get("recovered_from_receipt") for e in s.events),
                  "capability_hash": self.table.fingerprint, "fingerprint": s.fingerprint}
        atomic_json(self.out / "status.json", status)
        return status
