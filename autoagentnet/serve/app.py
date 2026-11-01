"""Agent server for a Maritime custom container.

Maritime contract:
  1. listen on 0.0.0.0:$PORT (see start.py; never hardcode the port)
  2. GET  /health -> any 2xx
  3. POST /chat   {"message": "...", "source": "..."} -> {"response": "..."} within 30 s

`message` is either
  - an AgentRequest JSON (sent by MaritimeRuntime): the reply is AgentOutput JSON, or
  - plain text (a person chatting in the Maritime UI): the reply is the agent's text,
    answered by the agent this container is pinned to (AAN_NETWORK + AAN_AGENT_ID).

Environment variables:
  AAN_PROVIDERS       providers config (default configs/providers.yaml)
  AAN_NETWORK         network YAML that defines this container's own agent (optional)
  AAN_AGENT_ID        which agent of that network this container is, e.g. "propose.3" (optional)
  AAN_MODEL_OVERRIDE  model ref that replaces every agent's model, e.g. "maritime_proxy" (optional)
  AAN_CHAT_TIMEOUT_S  stop waiting before Maritime's 30 s limit (default 28)
  plus the API-key variables named in the providers config (AAN_* only, e.g. AAN_ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import asyncio
import os

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ConfigDict, ValidationError

from ..agents.agent import run_agent
from ..agents.spec import AgentInput, AgentRequest, AgentSpec
from ..network.spec import NetworkSpec
from ..providers.registry import ProviderRegistry


class ChatBody(BaseModel):
    model_config = ConfigDict(extra="allow")
    message: str
    source: str | None = None


def create_app(
    registry: ProviderRegistry | None = None,
    pinned_spec: AgentSpec | None = None,
    timeout_s: float | None = None,
) -> FastAPI:
    registry = registry or ProviderRegistry.from_yaml(os.getenv("AAN_PROVIDERS", "configs/providers.yaml"))
    if pinned_spec is None and os.getenv("AAN_NETWORK") and os.getenv("AAN_AGENT_ID"):
        network = NetworkSpec.from_yaml(os.environ["AAN_NETWORK"])
        pinned_spec = network.find_agent(os.environ["AAN_AGENT_ID"])
    model_override = os.getenv("AAN_MODEL_OVERRIDE")
    timeout_s = timeout_s or float(os.getenv("AAN_CHAT_TIMEOUT_S", "28"))

    app = FastAPI(title="autoagentnet agent")

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "agent_id": pinned_spec.agent_id if pinned_spec else None}

    @app.post("/chat")
    async def chat(body: ChatBody) -> dict:
        try:
            request = AgentRequest.model_validate_json(body.message)
            structured = True
        except ValidationError:
            if pinned_spec is None:
                raise HTTPException(400, "send AgentRequest JSON, or set AAN_NETWORK and AAN_AGENT_ID")
            request = AgentRequest(spec=pinned_spec, input=AgentInput(task_id="chat", task=body.message))
            structured = False
        spec = request.spec.model_copy(update={"model": model_override}) if model_override else request.spec
        try:
            output = await asyncio.wait_for(run_agent(spec, request.input, registry), timeout_s)
        except asyncio.TimeoutError:
            raise HTTPException(504, f"agent did not finish within {timeout_s} s")
        return {"response": output.model_dump_json() if structured else output.content}

    return app
