"""The agent server honours the Maritime contract, and a network run through
MaritimeRuntime gives the same results as a local run."""

import asyncio

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from autoagentnet.agents.spec import AgentInput, AgentOutput, AgentRequest
from autoagentnet.runtime.maritime import MaritimeRuntime
from autoagentnet.serve.app import create_app
from conftest import make_executor


def test_health_and_chat(network, registry, fake):
    spec = network.agent_spec(0, 0, model="fake")
    client = TestClient(create_app(registry=registry, pinned_spec=spec))
    assert client.get("/health").json() == {"status": "ok", "agent_id": "propose.0"}

    request = AgentRequest(spec=spec, input=AgentInput(task_id="t", task="What is 2+2?"))
    reply = client.post("/chat", json={"message": request.model_dump_json(), "source": "test"})
    output = AgentOutput.model_validate_json(reply.json()["response"])
    assert output.agent_id == "propose.0" and "ANSWER:" in output.content

    plain = client.post("/chat", json={"message": "What is 2+2?", "source": "ui"})
    assert "ANSWER:" in plain.json()["response"]


def test_unpinned_worker_rejects_plain_text(registry, fake):
    client = TestClient(create_app(registry=registry))
    assert client.post("/chat", json={"message": "hello"}).status_code == 400


def fake_maritime_platform(agent_app: FastAPI, fail_first: int = 1) -> FastAPI:
    """Stands in for api.maritime.sh: relays /api/agents/{id}/chat to the container's /chat
    and answers the first `fail_first` requests with 429, like the awake-machine cap."""
    platform = FastAPI()
    state = {"seen": 0}

    @platform.post("/api/agents/{agent_id}/chat")
    async def relay(agent_id: str, body: dict):
        state["seen"] += 1
        if state["seen"] <= fail_first:
            from fastapi.responses import JSONResponse

            return JSONResponse({"error": "capacity"}, status_code=429, headers={"retry-after": "0"})
        transport = httpx.ASGITransport(app=agent_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://agent") as container:
            reply = await container.post("/chat", json={"message": body["message"], "source": "maritime"})
        return reply.json()

    return platform


def test_network_runs_the_same_through_maritime(network, registry, fake, tasks):
    agent_app = create_app(registry=registry)
    runtime = MaritimeRuntime(
        pool=["worker-0", "worker-1"],
        api_key="mk_test",
        transport=httpx.ASGITransport(app=fake_maritime_platform(agent_app)),
    )
    remote = asyncio.run(make_executor(network, registry, runtime=runtime).run(tasks[0]))
    local = asyncio.run(make_executor(network, registry).run(tasks[0]))
    assert len(remote.calls) == 19
    assert remote.final == local.final
