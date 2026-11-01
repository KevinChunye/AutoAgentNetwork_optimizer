from __future__ import annotations

from ..agents.agent import run_agent
from ..agents.spec import AgentOutput, AgentRequest
from ..providers.registry import ProviderRegistry


class LocalRuntime:
    """Runs every agent in this process; LLM calls go straight to the provider."""

    def __init__(self, registry: ProviderRegistry):
        self.registry = registry

    async def call(self, request: AgentRequest) -> AgentOutput:
        return await run_agent(request.spec, request.input, self.registry)

    async def aclose(self) -> None:
        return None
