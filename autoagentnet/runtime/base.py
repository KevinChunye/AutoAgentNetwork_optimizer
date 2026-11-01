"""Where agents run. The executor only talks to this interface, so the same
experiment runs in-process (LocalRuntime) or against agents deployed on
Maritime (MaritimeRuntime) by changing one config line."""

from __future__ import annotations

from typing import Protocol

from ..agents.spec import AgentOutput, AgentRequest


class AgentRuntime(Protocol):
    async def call(self, request: AgentRequest) -> AgentOutput: ...

    async def aclose(self) -> None: ...
