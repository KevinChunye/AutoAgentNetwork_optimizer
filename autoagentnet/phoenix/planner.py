"""Complete-closure estimates and receding-horizon greedy recovery.

No gain is assigned to intermediate nodes. This is a heuristic, not an optimal scheduler.
"""
from __future__ import annotations

import itertools
import math
import statistics
from typing import Literal

from pydantic import Field

from .store import ArtifactStore
from .types import Budget, Graph, Plan, Resources, Status, Strict, digest


class Observation(Strict):
    kind: str
    model: str = "cpu"
    dataset: str
    partition: Literal["calibration"]
    category: str = "generic"
    task_family: Literal["design", "diagnose", "plan"] | None = None
    mode: Literal["compute", "verify"] = "compute"
    completed: bool
    quality: float | None = Field(default=None, ge=0, le=1)
    api_usd: float = Field(ge=0)
    cpu_s: float = Field(ge=0)


class Estimate(Strict):
    success: float = Field(ge=0, le=1)
    api_usd: float = Field(ge=0)
    cpu_s: float = Field(ge=0)
    qualities: list[float] = Field(default_factory=list)
    samples: int = Field(ge=0)


class CapabilityTable(Strict):
    records: list[Observation]
    synthetic: bool = False
    complete: bool = True

    @property
    def fingerprint(self):
        return digest(self.model_dump())

    def estimate(self, kind: str, model: str, dataset: str, category="generic", mode="compute") -> Estimate:
        rows = [r for r in self.records if r.kind == kind and r.model == model and r.dataset == dataset]
        matched = [r for r in rows if r.category == category]
        if matched:
            rows = matched
        if not rows:
            rows = [r for r in self.records if r.kind == kind and r.model == model]
        if not rows:
            rows = [r for r in self.records if r.kind == kind]
        if not rows:
            raise ValueError(f"no calibration support for {kind}/{model}; run calibration first")
        matching_mode = [r for r in rows if r.mode == mode]
        if matching_mode:
            rows = matching_mode
        completed = [r for r in rows if r.completed]
        return Estimate(success=(len(completed)+1)/(len(rows)+2),
                        api_usd=statistics.median(r.api_usd for r in rows),
                        cpu_s=statistics.median(r.cpu_s for r in rows), samples=len(rows),
                        qualities=[r.quality for r in completed if r.quality is not None])

    @classmethod
    def fake(cls):
        """Explicit test fixture. Production preflight rejects synthetic tables."""
        rows = []
        for kind in ("prepare", "fit", "predict", "validate", "ensemble", "pipeline", "design"):
            for model in (["fake"] if kind == "design" else ["cpu"]):
                for _ in range(3):
                    rows.append(Observation(kind=kind, model=model, dataset="fixture", partition="calibration",
                                            completed=True, quality=1.0 if kind in ("pipeline", "design") else None,
                                            api_usd=0, cpu_s=0.01))
        return cls(records=rows, synthetic=True)


class Step(Strict):
    operation: str
    mode: Literal["verify", "compute"]


class Compiled(Strict):
    plan: Plan
    steps: list[Step]
    inherit: list[str]
    api_usd: float
    cpu_s: float
    calls: int
    tools: int
    gain: float
    priority: float
    nominal_api_usd: float
    nominal_cpu_s: float


def closure(graph: Graph, target: str, store: ArtifactStore) -> tuple[list[Step], list[str]]:
    graph.audit()
    steps, inherited, seen = [], [], set()

    def walk(key):
        if key in seen:
            return
        seen.add(key)
        op = graph.operations[key]
        for parent in op.parents:
            walk(parent)
        status = store.status(op, graph)
        if status == Status.VALID:
            inherited.append(key)
        else:
            steps.append(Step(operation=key, mode="verify" if status == Status.UNVERIFIED else "compute"))

    walk(target)
    return steps, inherited


def compile_plan(plan: Plan, graph: Graph, store: ArtifactStore, resources: Resources,
                 budget: Budget, table: CapabilityTable, dataset: str,
                 policy="full") -> Compiled | None:
    if plan.action == "ABANDON" or plan.target is None or not resources.workers:
        return None
    if plan.target not in graph.operations:
        raise ValueError("unknown plan target")
    steps, inherited = closure(graph, plan.target, store)
    if not steps:
        return None
    pending = {s.operation for s in steps}
    depths = {}
    def depth(key):
        if key not in pending:
            return 0
        if key not in depths:
            depths[key] = 1 + max([depth(p) for p in graph.operations[key].parents] or [0])
        return depths[key]
    if depth(plan.target) > 4:
        return None  # local proposal depth, excluding already valid shared ancestors
    api = cpu = 0.0
    calls = tools = 0
    probability = 1.0
    for step in steps:
        op = graph.operations[step.operation]
        if op.kind == "design" and step.mode == "compute":
            if op.model not in resources.models:
                return None
            calls += 1
        elif op.kind not in resources.tools:
            return None
        else:
            tools += 1
        estimate = table.estimate(op.kind, op.model or "cpu", dataset,
                                  op.params.get("classifier", "generic"), step.mode)
        api += estimate.api_usd
        cpu += estimate.cpu_s
        probability *= estimate.success
    # Deferred model design needs its eventual executable suffix, not just a cheap prompt.
    terminal = graph.operations[plan.target]
    if terminal.kind == "design":
        for kind in ("prepare", "fit", "predict", "validate"):
            if kind not in resources.tools:
                return None
            estimate = table.estimate(kind, "cpu", dataset)
            api += estimate.api_usd
            cpu += estimate.cpu_s
            probability *= estimate.success
            tools += 1
    if not budget.allows(api, cpu, calls, tools):
        return None
    category = terminal_category(graph, plan.target)
    quality = table.estimate("design" if terminal.kind == "design" else "pipeline",
                             terminal.model or "cpu", dataset, category).qualities
    gain = probability * statistics.mean(max(0.0, q-graph.score) for q in quality) if quality else 0.0
    nominal_api, nominal_cpu = 0.0, 0.0

    def nominal(key):
        nonlocal nominal_api, nominal_cpu
        op = graph.operations[key]
        est = table.estimate(op.kind, op.model or "cpu", dataset)
        nominal_api += est.api_usd
        nominal_cpu += est.cpu_s
        for parent in op.parents:
            nominal(parent)  # ablation intentionally ignores sharing and existing valid prefixes

    nominal(plan.target)
    ranking_api, ranking_cpu = (nominal_api, nominal_cpu) if policy == "no_dependency" else (api, cpu)
    denominator = ranking_api/max(budget.api_left, 1e-12) + ranking_cpu/max(budget.cpu_left, 1e-12) + 1e-6
    priority = gain if policy == "no_cost" else gain/denominator
    return Compiled(plan=plan, steps=steps, inherit=inherited, api_usd=api, cpu_s=cpu,
                    calls=calls, tools=tools, gain=gain, priority=priority,
                    nominal_api_usd=nominal_api, nominal_cpu_s=nominal_cpu)


def rank_plans(plans, graph, store, resources, budget, table, dataset, policy="full"):
    compiled = []
    for plan in plans:
        value = compile_plan(plan, graph, store, resources, budget, table, dataset, policy)
        if value is not None:
            compiled.append(value)
    # Stable and explicitly specified ties; only terminal outcomes contribute gain.
    compiled.sort(key=lambda c: (-c.priority, c.api_usd, c.cpu_s, c.plan.id))
    return compiled


def terminal_category(graph, target):
    op = graph.operations[target]
    if op.kind == "design":
        return "generic"
    pred = graph.operations[op.parents[0]]
    return "ensemble" if pred.kind == "ensemble" else graph.operations[pred.parents[0]].params["classifier"]


def select(plans, graph, store, resources, budget, table, dataset, policy="full"):
    ranked = rank_plans(plans, graph, store, resources, budget, table, dataset, policy)
    if policy == "static":
        ranked.sort(key=lambda c: (c.api_usd, c.cpu_s, c.plan.id))
        return ranked[0] if ranked else None
    return next((c for c in ranked if c.gain > 0), None)


def enumerate_estimated(plans, graph, store, resources, budget, table, dataset):
    """Exact subset enumeration under an explicit estimated model, not true outcomes.

    Missing completions are independent Bernoulli estimates, with shared ancestors
    sharing the SAME event. Quality samples use a common quantile (comonotonic
    coupling) rather than summing correlated gains. Both are declared heuristics.
    Deferred graphs that have not yet been generated are excluded.
    """
    if len(plans) > 8:
        raise ValueError("enumeration restricted to at most eight plans")
    values = [compile_plan(p, graph, store, resources, budget, table, dataset) for p in plans]
    values = [v for v in values if v is not None]
    if len({s.operation for v in values for s in v.steps}) > 8:
        raise ValueError("enumeration restricted to at most eight missing operations")
    best = {"plans": [], "estimated_gain": 0.0, "api_usd": 0.0, "cpu_s": 0.0}
    for n in range(1, len(values)+1):
        for subset in itertools.combinations(values, n):
            nodes = {s.operation for c in subset for s in c.steps}
            modes = {s.operation: s.mode for c in subset for s in c.steps}
            api = cpu = 0.0
            calls = tools = 0
            for key in nodes:
                op = graph.operations[key]
                est = table.estimate(op.kind, op.model or "cpu", dataset,
                                      op.params.get("classifier", "generic"), modes[key])
                api += est.api_usd
                cpu += est.cpu_s
                calls += op.kind == "design"
                tools += op.kind != "design"
            # Deferred suffixes cannot be enumerated before their structure exists.
            if any(graph.operations[c.plan.target].kind == "design" for c in subset):
                continue
            if not budget.allows(api, cpu, calls, tools):
                continue
            nodes = list(nodes)
            probabilities = [table.estimate(graph.operations[k].kind,
                             graph.operations[k].model or "cpu", dataset,
                             graph.operations[k].params.get("classifier", "generic"), modes[k]).success for k in nodes]
            qualities = [sorted(table.estimate("pipeline", "cpu", dataset,
                        terminal_category(graph, c.plan.target)).qualities) for c in subset]
            cuts = sorted({0.0, 1.0} | {i/len(q) for q in qualities if q for i in range(len(q)+1)})
            gain = 0.0
            for mask in itertools.product((False, True), repeat=len(nodes)):
                mass = math.prod(p if yes else 1-p for p, yes in zip(probabilities, mask))
                success = {k for k, yes in zip(nodes, mask) if yes}
                active = [q for c, q in zip(subset, qualities) if q and
                          all(s.operation in success for s in c.steps)]
                for left, right in zip(cuts, cuts[1:]):
                    u = (left+right)/2
                    terminal = max([graph.score] + [q[min(len(q)-1, int(u*len(q)))] for q in active])
                    gain += mass * (right-left) * (terminal-graph.score)
            if (gain, -api, -cpu) > (best["estimated_gain"], -best["api_usd"], -best["cpu_s"]):
                best = {"plans": [c.plan.id for c in subset], "estimated_gain": gain,
                        "api_usd": api, "cpu_s": cpu}
    return best
