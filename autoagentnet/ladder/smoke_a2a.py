"""W4 protocol ladder, rung 1 smoke test: two agents over A2A, one with an MCP tool, offline.

Run inside the A2A virtual environment (autoagentnet/ladder/software.py builds it):

    <venv>/bin/python -I autoagentnet/ladder/smoke_a2a.py <repo root>

  - The seller is an A2A server (official a2a-sdk, JSON-RPC over HTTP on 127.0.0.1) with an
    Agent Card. On each message it decides through our caller (MarketCaller: call cache, then the
    runtime, with the fake provider, so nothing is spent) and reserves the item with its own MCP
    tool `reserve` (official MCP SDK, an MCPServer connected in-process) before it answers.
  - The buyer is an A2A client: it fetches the seller's Agent Card and sends one message.
The script prints one JSON line; the smoke test passes when the buyer reads a reply that carries
both the caller's text and the wallet tool's result.
"""

from __future__ import annotations

import asyncio
import json
import socket
import sys
from pathlib import Path

sys.path.insert(0, sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[2]))

import uvicorn  # noqa: E402
from a2a.client import ClientConfig, create_client  # noqa: E402
from a2a.helpers.proto_helpers import get_message_text, new_text_message  # noqa: E402
from a2a.server.agent_execution import AgentExecutor, RequestContext  # noqa: E402
from a2a.server.events import EventQueue  # noqa: E402
from a2a.server.request_handlers import DefaultRequestHandler  # noqa: E402
from a2a.server.routes import create_agent_card_routes, create_jsonrpc_routes  # noqa: E402
from a2a.server.tasks import InMemoryTaskStore  # noqa: E402
from a2a.types import (AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Message, Part,  # noqa: E402
                       Role, SendMessageRequest)
from mcp import Client as MCPClient  # noqa: E402
from mcp.server.mcpserver import MCPServer  # noqa: E402
from starlette.applications import Starlette  # noqa: E402

from autoagentnet.agents.spec import AgentInput, AgentRequest, AgentSpec  # noqa: E402
from autoagentnet.cache import CallCache  # noqa: E402
from autoagentnet.market.caller import MarketCaller  # noqa: E402
from autoagentnet.providers.fake import FakeClient  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402
from autoagentnet.runtime.local import LocalRuntime  # noqa: E402

ROOT = Path(sys.path[0])

wallet = MCPServer("seller-wallet")
holdings = {"cash_cents": 0, "reserved": []}


@wallet.tool()
def reserve(item: str, price_cents: int) -> str:
    """Reserve one unit of `item` for a buyer at `price_cents`."""
    holdings["reserved"].append(item)
    return f"reserved {item} at {price_cents} cents ({len(holdings['reserved'])} reserved)"


class SellerExecutor(AgentExecutor):
    def __init__(self, caller: MarketCaller):
        self.caller = caller

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        spec = AgentSpec(agent_id="seller", stage="offer", index=0, model="fake",
                         system="You sell one item. Answer the buyer in one sentence.",
                         instruction=context.get_user_input(), max_tokens=200)
        output = await self.caller.call(AgentRequest(spec=spec, input=AgentInput(task_id="a2a-smoke", task="market")),
                                        replicate=0)
        async with MCPClient(wallet) as tools:
            result = await tools.call_tool("reserve", {"item": "widget", "price_cents": 150})
        tool_text = result.content[0].text
        await event_queue.enqueue_event(new_text_message(f"{output.content}\nWALLET: {tool_text}",
                                                         context_id=context.context_id, task_id=context.task_id))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def main() -> dict:
    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    registry.set_client("fake", FakeClient())
    caller = MarketCaller(LocalRuntime(registry), registry, pricebook=None, cache=CallCache(), governor=None,
                          run_id="smoke", market="a2a-smoke", condition="fake")
    port = free_port()
    url = f"http://127.0.0.1:{port}"
    card = AgentCard(name="seller", description="Sells widgets", version="0.1",
                     supported_interfaces=[AgentInterface(url=f"{url}/", protocol_binding="JSONRPC", protocol_version="1.0")],
                     capabilities=AgentCapabilities(streaming=False), default_input_modes=["text/plain"],
                     default_output_modes=["text/plain"],
                     skills=[AgentSkill(id="sell", name="sell", description="quote and reserve a widget", tags=["market"])])
    handler = DefaultRequestHandler(agent_executor=SellerExecutor(caller), task_store=InMemoryTaskStore(), agent_card=card)
    app = Starlette(routes=create_agent_card_routes(card) + create_jsonrpc_routes(handler, rpc_url="/"))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    serving = asyncio.create_task(server.serve())
    while not server.started:
        await asyncio.sleep(0.05)
    try:
        buyer = await create_client(url, client_config=ClientConfig(streaming=False))
        request = SendMessageRequest(message=Message(message_id="m1", role=Role.ROLE_USER,
                                                     parts=[Part(text="I want one widget. What is your price?")]))
        replies = []
        async for response in buyer.send_message(request):
            if response.HasField("message"):
                replies.append(get_message_text(response.message))
            elif response.HasField("task"):
                replies += [get_message_text(m) for m in response.task.history if m.role == Role.ROLE_AGENT]
        await buyer.close()
    finally:
        server.should_exit = True
        await serving
    reply = "\n".join(replies)
    return {"card": card.name, "reply_has_caller_text": bool(reply.split("\nWALLET:")[0].strip()),
            "reply_has_tool_result": "WALLET: reserved widget" in reply, "caller_live_calls": caller.live_calls,
            "reply": reply[:200]}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main())))
