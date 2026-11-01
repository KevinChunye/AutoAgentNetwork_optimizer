"""A network is a stack of stages (layers); each stage has `width` agents (channels).
Every agent reads the outputs of the stage before it, like a dense feed-forward net.

PruneConfig picks the sub-network to run, using the model-pruning analogies:
  keep    -> structured pruning (remove agents, like removing channels); keep 0 skips a
             middle stage entirely (its upstream outputs pass straight through)
  fan_in  -> unstructured pruning (remove message edges, like removing weights)
  models  -> per-stage model tier (like quantization: a cheaper model for a stage)

Building blocks (StageSpec):
  kind: llm    agents that each make one model call (the default)
  kind: vote   a free, deterministic majority vote over the previous stage's answers
               (no model call); the committee decision
  exit_if_agreement   before the stage runs: if the previous stage's plurality share is
               at least this, stop and answer with the plurality ("management by
               exception": only contested tasks pay for the later stages)
  escalate_to / escalate_below   run the stage on a stronger model ref when the previous
               stage's plurality share is below the threshold (consult a specialist only
               on contested tasks)
  kind: debate `width` agents answer over `rounds` rounds. Round 1 is an llm stage (each agent
               reads the task and the previous stage's outputs, if any, with `instruction`).
               In each later round every agent reads the task, then its peers' answers from
               the round before (shared task prefix first), and answers again with
               `debate_instruction`. `edges` prunes the debate: edges[i] lists the agents
               whose previous answers agent i reads (None = all agents, itself included, so
               every agent reads the same text and the prefix can be cached). The stage's
               output is its last round; earlier rounds stay in the trace, so stopping after
               round r or a consensus exit between rounds can be replayed offline exactly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, model_validator

from ..agents.spec import AgentSpec


class StageSpec(BaseModel):
    name: str
    width: int  # number of agents in the dense stage
    kind: Literal["llm", "vote", "debate"] = "llm"
    system: str = ""  # shared by all agents in the stage (llm stages)
    instruction: str = ""  # may contain {perspective} (llm stages)
    perspectives: list[str] = [""]  # agent i gets perspectives[i % len]
    model: str | None = None  # model ref; None = network default
    agent_models: list[str] | None = None  # mixed team: agent i uses agent_models[i % len] (wins over `model`)
    max_tokens: int | None = None
    temperature: float | None = None
    exit_if_agreement: float | None = None  # see the module docstring
    escalate_to: str | None = None
    escalate_below: float = 0.5
    rounds: int = 1  # debate stages: number of rounds (at least 2)
    debate_instruction: str = ""  # debate stages: the instruction of rounds 2 and later
    edges: list[list[int]] | None = None  # debate stages: edges[i] = agents whose last answers agent i reads

    @model_validator(mode="after")
    def _block_is_complete(self) -> "StageSpec":
        if self.kind in ("llm", "debate") and not (self.system.strip() and self.instruction.strip()):
            raise ValueError(f"{self.kind} stage {self.name!r} needs a system prompt and an instruction")
        if self.kind == "debate":
            if self.rounds < 2 or not self.debate_instruction.strip():
                raise ValueError(f"debate stage {self.name!r} needs rounds >= 2 and a debate_instruction")
            if self.edges is not None and (len(self.edges) != self.width
                                           or any(not 0 <= j < self.width for row in self.edges for j in row)):
                raise ValueError(f"debate stage {self.name!r}: edges must list, for each of its {self.width} agents, "
                                 "indices of agents in the stage")
        if self.kind == "vote" and self.width != 1:
            raise ValueError(f"vote stage {self.name!r} must have width 1")
        return self


class NetworkSpec(BaseModel):
    name: str
    description: str = ""
    default_model: str = "haiku"
    default_max_tokens: int = 800
    default_temperature: float | None = 0.0
    stages: list[StageSpec]

    @model_validator(mode="after")
    def _first_stage_has_no_upstream(self) -> "NetworkSpec":
        first = self.stages[0]
        if first.kind not in ("llm", "debate") or first.exit_if_agreement is not None or first.escalate_to:
            raise ValueError("the first stage must be an llm stage without exit or escalation rules")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "NetworkSpec":
        return cls(**yaml.safe_load(Path(path).read_text()))

    @property
    def widths(self) -> list[int]:
        return [s.width for s in self.stages]

    def agent_spec(self, stage_index: int, index: int, model: str | None = None, round: int = 1) -> AgentSpec:
        """Spec of agent `index` in stage `stage_index` (debate stages: in round `round`, named "<stage>.r<round>";
        round 1 keeps the plain names). `model` overrides the stage's model ref."""
        stage = self.stages[stage_index]
        perspective = stage.perspectives[index % len(stage.perspectives)]
        name = stage.name if round == 1 else f"{stage.name}.r{round}"
        instruction = stage.instruction if round == 1 else stage.debate_instruction
        return AgentSpec(
            agent_id=f"{name}.{index}",
            stage=name,
            index=index,
            model=model
            or (stage.agent_models[index % len(stage.agent_models)] if stage.agent_models else None)
            or stage.model
            or self.default_model,
            system=stage.system.strip(),
            instruction=instruction.format(perspective=perspective).strip(),
            max_tokens=stage.max_tokens or self.default_max_tokens,
            temperature=stage.temperature if stage.temperature is not None else self.default_temperature,
        )

    def all_agents(self) -> list[AgentSpec]:
        """Every model-calling agent (vote stages make no calls and have no agents)."""
        return [
            self.agent_spec(s, i, round=r) for s, st in enumerate(self.stages) if st.kind in ("llm", "debate")
            for r in range(1, (st.rounds if st.kind == "debate" else 1) + 1) for i in range(st.width)
        ]

    def find_agent(self, agent_id: str) -> AgentSpec:
        for spec in self.all_agents():
            if spec.agent_id == agent_id:
                return spec
        raise KeyError(f"no agent {agent_id!r} in network {self.name!r}")


class PruneConfig(BaseModel):
    """Which sub-network to run.

    keep:   agents kept per stage; stage s runs its first keep[s] agents.
    fan_in: per stage, how many upstream outputs each agent reads (None = all).
            Agent i reads upstream outputs i, i+1, ... (wrapping around).
    models: per stage, a model ref replacing the stage's model (None = unchanged).
    """

    keep: list[int]
    fan_in: list[int | None] | None = None
    models: list[str | None] | None = None

    @model_validator(mode="after")
    def _lengths_match(self) -> "PruneConfig":
        for name in ("fan_in", "models"):
            value = getattr(self, name)
            if value is not None and len(value) != len(self.keep):
                raise ValueError(f"{name} has {len(value)} entries, keep has {len(self.keep)}")
        return self

    @classmethod
    def dense(cls, network: NetworkSpec) -> "PruneConfig":
        return cls(keep=network.widths)

    @property
    def config_id(self) -> str:
        parts = ["k" + "-".join(map(str, self.keep))]
        if self.fan_in is not None:
            parts.append("f" + "-".join("all" if f is None else str(f) for f in self.fan_in))
        if self.models is not None:
            parts.append("m" + "-".join(m or "default" for m in self.models))
        return "_".join(parts)

    def check(self, network: NetworkSpec) -> None:
        """Every stage keeps 1..width agents; a middle stage may keep 0 (skipped)."""
        if len(self.keep) != len(network.stages):
            raise ValueError(f"keep has {len(self.keep)} entries for {len(network.stages)} stages")
        last = len(network.stages) - 1
        for s, (k, width) in enumerate(zip(self.keep, network.widths)):
            low = 0 if 0 < s < last and network.stages[s].kind in ("llm", "debate") else 1
            if not low <= k <= width:
                raise ValueError(f"keep {self.keep}: stage {s} must keep {low}..{width}")


def upstream_indices(agent_index: int, n_upstream: int, fan_in: int | None) -> list[int]:
    """Which upstream outputs an agent reads under edge pruning."""
    if fan_in is None or fan_in >= n_upstream:
        return list(range(n_upstream))
    return sorted((agent_index + j) % n_upstream for j in range(fan_in))
