"""Wire types for one agent call. The same JSON goes to a local agent or to a
Maritime container, which is what makes local and Maritime runs interchangeable."""

from __future__ import annotations

from pydantic import BaseModel

from ..providers.base import Usage


class AgentSpec(BaseModel):
    """Everything that defines one agent.

    agent_id:    "<stage>.<index>", e.g. "propose.3"
    model:       a model ref from configs/providers.yaml, e.g. "haiku" (not a vendor ID)
    system:      system prompt, identical for every agent in a stage
    instruction: agent-specific text placed after the shared context
    """

    agent_id: str
    stage: str
    index: int
    model: str
    system: str
    instruction: str
    max_tokens: int = 800
    temperature: float | None = 0.0


class Upstream(BaseModel):
    agent_id: str
    content: str


class AgentInput(BaseModel):
    """What the agent reads: the task and the outputs it receives from the stage before.

    shared_prefix: True when every agent in the stage reads the same upstream
    outputs, so the task + upstream text is one shared prefix worth caching.
    False when edge pruning gives agents different inputs (no cache benefit).
    """

    task_id: str
    task: str
    upstream: list[Upstream] = []
    shared_prefix: bool = True


class AgentOutput(BaseModel):
    agent_id: str
    content: str
    usage: Usage
    provider: str
    model: str  # vendor model ID actually used
    latency_s: float
    stop_reason: str | None = None  # "max_tokens" / "length" = cut off before finishing
    from_cache: bool = False  # served by the call cache (free) rather than a live call
    cost_usd: float = 0.0  # filled in by the executor from the price book
    flops: float | None = None
    extra: dict = {}  # provider measurements passed through from LLMResponse.extra (empty for API providers)


class AgentRequest(BaseModel):
    """The message sent to a runtime: which agent to be, and what to read."""

    spec: AgentSpec
    input: AgentInput
