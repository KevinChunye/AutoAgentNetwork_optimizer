"""Calls agents deployed on Maritime through its REST API.

Each request is ``POST {base_url}/api/agents/{maritime_id}/chat`` with body
``{"message": <AgentRequest JSON>}`` and ``Authorization: Bearer $MARITIME_API_KEY``.
The container (autoagentnet/serve/app.py) answers ``{"response": <AgentOutput JSON>}``.

Two ways to place agents on machines:
  agent_map: one Maritime agent per network agent ("propose.3" -> Maritime id).
             Faithful to "one agent, one machine"; uses one machine per agent.
  pool:      a few generic workers. Any container can play any agent because the
             request carries the full AgentSpec. Agents missing from agent_map
             go to pool[stable hash of agent_id]. Saves machines (the Growth plan
             allows 25 awake at once).
"""

from __future__ import annotations

import asyncio
import hashlib
import os
from pathlib import Path

import httpx
import yaml

from ..agents.spec import AgentOutput, AgentRequest

DEFAULT_BASE_URL = "https://api.maritime.sh"


class MaritimeRuntime:
    def __init__(
        self,
        agent_map: dict[str, str] | None = None,
        pool: list[str] | None = None,
        api_key: str | None = None,
        base_url: str = DEFAULT_BASE_URL,
        timeout_s: float = 60.0,
        max_retries: int = 5,
        retry_wait_s: float = 15.0,  # Maritime suggests 15 s when the awake-machine cap is hit (429)
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.agent_map = agent_map or {}
        self.pool = pool or []
        if not self.agent_map and not self.pool:
            raise ValueError("MaritimeRuntime needs agent_map, pool, or both")
        self.max_retries = max_retries
        self.retry_wait_s = retry_wait_s
        api_key = api_key or os.getenv("MARITIME_API_KEY", "")
        self._http = httpx.AsyncClient(
            base_url=base_url,
            timeout=timeout_s,
            headers={"Authorization": f"Bearer {api_key}"},
            transport=transport,
        )

    @classmethod
    def from_yaml(cls, path: str | Path, **kwargs) -> "MaritimeRuntime":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls(
            agent_map=raw.get("agent_map") or {},
            pool=raw.get("pool") or [],
            api_key=os.getenv(raw.get("api_key_env", "MARITIME_API_KEY")),
            base_url=raw.get("base_url", DEFAULT_BASE_URL),
            **kwargs,
        )

    def target(self, agent_id: str) -> str:
        if agent_id in self.agent_map:
            return self.agent_map[agent_id]
        if not self.pool:
            raise KeyError(f"{agent_id!r} is not in agent_map and there is no pool")
        stable_hash = int(hashlib.sha256(agent_id.encode()).hexdigest()[:8], 16)
        return self.pool[stable_hash % len(self.pool)]

    async def call(self, request: AgentRequest) -> AgentOutput:
        url = f"/api/agents/{self.target(request.spec.agent_id)}/chat"
        body = {"message": request.model_dump_json()}
        for attempt in range(self.max_retries + 1):
            response = await self._http.post(url, json=body)
            retryable = response.status_code == 429 or response.status_code >= 500
            if retryable and attempt < self.max_retries:
                await asyncio.sleep(self._wait_seconds(response, attempt))
                continue
            response.raise_for_status()
            return AgentOutput.model_validate_json(self._reply_text(response))
        raise RuntimeError("unreachable")

    def _wait_seconds(self, response: httpx.Response, attempt: int) -> float:
        try:
            return float(response.headers["retry-after"])
        except (KeyError, ValueError):
            return self.retry_wait_s * (attempt + 1)

    @staticmethod
    def _reply_text(response: httpx.Response) -> str:
        try:
            payload = response.json()
        except ValueError:
            return response.text
        if isinstance(payload, dict) and "response" in payload:
            return payload["response"]
        return response.text

    async def aclose(self) -> None:
        await self._http.aclose()
