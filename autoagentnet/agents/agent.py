"""Running one agent: build the prompt, call the model, return a typed output."""

from __future__ import annotations

from ..providers.base import Block, LLMRequest
from ..providers.registry import ProviderRegistry
from .spec import AgentInput, AgentOutput, AgentSpec


def render_shared_context(inp: AgentInput) -> str:
    """Task plus upstream outputs. Every agent in a dense stage sees exactly this text,
    so it sits before the agent-specific instruction and can be prompt-cached."""
    parts = [f"TASK:\n{inp.task}"]
    if inp.upstream:
        parts.append("OUTPUTS FROM THE PREVIOUS STAGE:")
        parts += [f"[{i}] ({u.agent_id})\n{u.content}" for i, u in enumerate(inp.upstream, 1)]
    return "\n\n".join(parts)


def build_request(spec: AgentSpec, inp: AgentInput, model_id: str, options: dict | None = None) -> LLMRequest:
    return LLMRequest(
        model=model_id,
        system=spec.system,
        blocks=[
            Block(text=render_shared_context(inp), cache=inp.shared_prefix),
            Block(text=spec.instruction),
        ],
        max_tokens=spec.max_tokens,
        temperature=spec.temperature,
        options=options or {},
    )


def prompt_text(spec: AgentSpec, inp: AgentInput) -> str:
    """Everything the agent reads, for token estimates before a call."""
    return spec.system + render_shared_context(inp) + spec.instruction


async def run_agent(spec: AgentSpec, inp: AgentInput, registry: ProviderRegistry) -> AgentOutput:
    client = registry.client(spec.model)
    request = build_request(spec, inp, registry.model_id(spec.model), registry.options_of(spec.model))
    response = await client.complete(request)
    return AgentOutput(
        agent_id=spec.agent_id,
        content=response.text,
        usage=response.usage,
        provider=response.provider,
        model=response.model,
        latency_s=response.latency_s,
        stop_reason=response.stop_reason,
        extra=response.extra,
    )
