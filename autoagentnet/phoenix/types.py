"""Validated recovery DSL. Model outputs cannot supply measured costs or scores."""
from __future__ import annotations

import hashlib
import json
import math
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


def canonical(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", validate_assignment=True, allow_inf_nan=False)


class Status(StrEnum):
    VALID = "VALID"
    UNVERIFIED = "UNVERIFIED"
    STALE = "STALE"
    MISSING = "MISSING"
    RUNNING = "RUNNING"


class PipelineSpec(Strict):
    scaler: Literal["none", "standard", "minmax"] = "standard"
    pca: Literal["none", "0.90", "0.95", "0.99"] = "none"
    classifier: Literal["logistic", "forest", "knn"] = "logistic"
    c: Literal[0.1, 1.0, 10.0] = 1.0
    trees: Literal[50, 100] = 50
    depth: Literal["none", "5", "10"] = "none"
    neighbors: Literal[3, 5, 11] = 5

    def parameters(self) -> dict:
        # Irrelevant classifier parameters must not create false cache misses.
        out = {"classifier": self.classifier}
        if self.classifier == "logistic":
            out["c"] = self.c
        elif self.classifier == "forest":
            out.update(trees=self.trees, depth=self.depth)
        else:
            out["neighbors"] = self.neighbors
        return out


class Operation(Strict):
    """One typed operation and its immutable semantic inputs, not its receipt."""
    kind: Literal["prepare", "fit", "predict", "ensemble", "validate", "design"]
    parents: list[str] = Field(default_factory=list)
    params: dict = Field(default_factory=dict)
    context: str
    model: str | None = None

    @property
    def id(self) -> str:
        return digest(self.model_dump())


class Receipt(Strict):
    operation_id: str
    payload_sha256: str
    parent_payloads: dict[str, str]
    context: str
    status: Status = Status.UNVERIFIED
    cpu_s: float = Field(ge=0)
    elapsed_s: float = Field(ge=0)
    api_usd: float = Field(default=0, ge=0)
    executor: str = "cpu"


class WorkTask(Strict):
    id: str
    target: str
    owner: str | None = None
    version: int = 0
    abandoned: bool = False


class Graph(Strict):
    context: str
    operations: dict[str, Operation] = Field(default_factory=dict)
    tasks: dict[str, WorkTask] = Field(default_factory=dict)
    evidence_links: dict[str, list[str]] = Field(default_factory=dict)
    incumbent: str | None = None
    score: float = Field(default=0, ge=0, le=1)

    def add(self, op: Operation) -> str:
        if op.context != self.context:
            raise ValueError("operation belongs to another dataset/split/code context")
        if any(p not in self.operations for p in op.parents):
            raise ValueError("unknown parent")
        self.operations[op.id] = op
        return op.id

    def audit(self) -> None:
        visiting, done = set(), set()

        def visit(key):
            if key in visiting:
                raise ValueError("cycle")
            if key in done:
                return
            if key not in self.operations:
                raise ValueError("missing dependency")
            op = self.operations[key]
            if op.id != key or op.context != self.context:
                raise ValueError("tampered operation identity/context")
            visiting.add(key)
            for p in op.parents:
                visit(p)
            visiting.remove(key)
            done.add(key)

        for key in self.operations:
            visit(key)
        if self.incumbent and self.incumbent not in self.operations:
            raise ValueError("unknown incumbent")

    def shutdown(self, member: str) -> list[str]:
        released = []
        for task in self.tasks.values():
            if task.owner == member:
                task.owner = None
                task.version += 1
                released.append(task.id)
        return released

    def ancestors(self, target: str) -> set[str]:
        self.audit()
        required = set()
        def walk(key):
            if key not in required:
                required.add(key)
                for parent in self.operations[key].parents:
                    walk(parent)
        walk(target)
        return required

    def claim(self, task_id: str, member: str, version: int) -> int:
        task = self.tasks[task_id]
        if task.version != version or task.owner not in (None, member) or task.abandoned:
            raise ValueError("ownership version mismatch or unavailable task")
        task.owner = member
        task.version += 1
        return task.version

    def check_owner(self, task_id: str, member: str, version: int) -> None:
        task = self.tasks[task_id]
        if task.owner != member or task.version != version:
            raise ValueError("late submission rejected")


class Proposal(Strict):
    """Bounded high-level DSL, compiled into trusted operations by the application."""
    action: Literal["INHERIT", "VERIFY", "RECOMPUTE", "REROUTE", "SPLIT", "ABANDON"]
    target: str | None = None
    pipelines: list[PipelineSpec] = Field(default_factory=list, max_length=2)
    weight: Literal[0.25, 0.5, 0.75] = 0.5
    model: str | None = None
    reason: str = Field(default="", max_length=500)

    @model_validator(mode="after")
    def contract(self):
        if self.action in ("INHERIT", "VERIFY", "RECOMPUTE", "ABANDON") and not self.target:
            raise ValueError("action requires an existing target")
        if self.action == "REROUTE" and not (len(self.pipelines) == 1 or (not self.pipelines and self.model)):
            raise ValueError("reroute requires a pipeline or an explicit deferred design model")
        if self.action == "SPLIT" and len(self.pipelines) != 2:
            raise ValueError("split requires two pipelines and a defined merge")
        return self


class Plan(Strict):
    action: str
    target: str | None
    reason: str = ""

    @property
    def id(self):
        return digest({"action": self.action, "target": self.target})


class Resources(Strict):
    workers: list[str] = Field(default_factory=lambda: ["A", "B", "C"])
    models: list[str] = Field(default_factory=lambda: ["luna_low_ev", "sol61_low", "sonnet_low"])
    tools: list[str] = Field(default_factory=lambda: ["prepare", "fit", "predict", "validate", "ensemble"])

    def fault(self, member: str, withdraw: str | None = None) -> None:
        self.workers = [w for w in self.workers if w != member]
        if withdraw:
            self.models = [m for m in self.models if m != withdraw]


class Budget(Strict):
    api_limit: float = Field(gt=0)
    cpu_limit: float = Field(default=120, gt=0)
    call_limit: int = Field(default=8, gt=0)
    tool_limit: int = Field(default=24, gt=0)
    api_spent: float = Field(default=0, ge=0)
    cpu_spent: float = Field(default=0, ge=0)
    calls: int = Field(default=0, ge=0)
    tools: int = Field(default=0, ge=0)

    @property
    def api_left(self):
        return max(0.0, self.api_limit - self.api_spent)

    @property
    def cpu_left(self):
        return max(0.0, self.cpu_limit - self.cpu_spent)

    def allows(self, api=0.0, cpu=0.0, calls=0, tools=0):
        return all(math.isfinite(x) and x >= 0 for x in (api, cpu)) and calls >= 0 and tools >= 0 and (
            api <= self.api_left + 1e-12 and cpu <= self.cpu_left + 1e-12
            and self.calls + calls <= self.call_limit and self.tools + tools <= self.tool_limit)
