import asyncio
import json

import httpx
import pytest

from autoagentnet.pricing import PriceBook, Price, UnknownPrice
from autoagentnet.providers.anthropic_provider import AnthropicClient
from autoagentnet.providers.base import Block, LLMRequest, Usage
from autoagentnet.providers.fake import FakeClient
from autoagentnet.providers.openai_compat import OpenAICompatClient

def anthropic_uses_httpx2() -> bool:
    import importlib.metadata

    requires = importlib.metadata.requires("anthropic") or []
    return any(r.startswith("httpx2") for r in requires)


REQUEST = LLMRequest(
    model="m",
    system="You are a solver.",
    blocks=[Block(text="TASK: 2+2", cache=True), Block(text="Your approach: be brief.")],
    max_tokens=50,
)


def mock_client(response_json: dict, captured: dict, http=httpx):
    """An HTTP client that records the request and returns a canned reply.
    `http` is the httpx module the SDK expects (the anthropic SDK 1.x uses httpx2)."""

    def handler(request):
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return http.Response(200, json=response_json)

    return http.AsyncClient(transport=http.MockTransport(handler))


def test_anthropic_marks_cache_breakpoints_and_normalizes_usage():
    captured: dict = {}
    reply = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "4\nANSWER: 4"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5,
                  "cache_creation_input_tokens": 700, "cache_read_input_tokens": 0},
    }
    http = pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx
    client = AnthropicClient(api_key="test", http_client=mock_client(reply, captured, http))
    response = asyncio.run(client.complete(REQUEST.model_copy(update={"model": "claude-haiku-5-5"})))

    body = captured["body"]
    assert captured["url"].endswith("/v1/messages")
    assert body["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert body["messages"][0]["content"][0]["cache_control"] == {"type": "ephemeral"}
    assert "cache_control" not in body["messages"][0]["content"][1]
    assert response.text == "4\nANSWER: 4"
    assert response.usage == Usage(input_tokens=10, cache_write_tokens=700, output_tokens=5)


def test_openai_compat_payload_and_cached_tokens():
    captured: dict = {}
    reply = {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-6-luna",
        "choices": [{"index": 0, "finish_reason": "stop",
                     "message": {"role": "assistant", "content": "ANSWER: 4"}}],
        "usage": {"prompt_tokens": 1200, "completion_tokens": 5, "total_tokens": 1205,
                  "prompt_tokens_details": {"cached_tokens": 1024}},
    }
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1",
                                http_client=mock_client(reply, captured))
    response = asyncio.run(client.complete(REQUEST))

    body = captured["body"]
    assert captured["url"] == "https://example.test/v1/chat/completions"
    assert body["max_completion_tokens"] == 50
    assert body["messages"][0] == {"role": "system", "content": "You are a solver."}
    assert response.usage == Usage(input_tokens=176, cache_read_tokens=1024, output_tokens=5)


def test_fake_is_deterministic_and_simulates_prompt_cache():
    fake = FakeClient()
    request = REQUEST.model_copy(update={"blocks": [Block(text="x" * 4000, cache=True), Block(text="go")]})
    first = asyncio.run(fake.complete(request))
    second = asyncio.run(fake.complete(request))
    assert first.text == second.text
    assert first.usage.cache_write_tokens > 0 and first.usage.cache_read_tokens == 0
    assert second.usage.cache_read_tokens == first.usage.cache_write_tokens


def test_registry_resolves_refs_and_env_overrides(registry, monkeypatch):
    assert registry.provider_of("haiku") == "anthropic"
    assert registry.model_id("haiku") == "claude-haiku-5-5"
    monkeypatch.setenv("AAN_OPENAI_MODEL", "gpt-6.1-sol")
    assert registry.model_id("gpt_small") == "gpt-6.1-sol"
    assert registry.account_of("haiku") == "anthropic" and registry.account_of("gpt_small") == "openai"
    with pytest.raises(KeyError):
        registry.config("no_such_ref")
    monkeypatch.delenv("AAN_ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "claude-code-key")  # must never be borrowed
    with pytest.raises(RuntimeError, match="AAN_ANTHROPIC_API_KEY"):
        registry.client("haiku")


def test_pricing_is_cache_aware_and_refuses_unknown_models(pricebook):
    usage = Usage(input_tokens=1_000_000, cache_write_tokens=1_000_000,
                  cache_read_tokens=1_000_000, output_tokens=1_000_000)
    assert pricebook.cost_usd("claude-haiku-5-5", "anthropic", usage) == pytest.approx(0.10 + 0.125 + 0.01 + 0.50)
    assert pricebook.cost_usd("anything", "fake", usage) == 0
    with pytest.raises(UnknownPrice):
        pricebook.cost_usd("unpriced-model", "openai_compat", usage)
    flop_book = PriceBook({"oss": Price(input=0, output=0, active_params_b=5.1)})
    assert flop_book.flops("oss", "openai_compat", Usage(output_tokens=1)) == pytest.approx(2 * 5.1e9)


def get_client(response_json: dict, captured: dict, http=httpx):
    """An HTTP client for GET endpoints: records the method and URL, returns a canned reply."""

    def handler(request):
        captured["method"], captured["url"] = request.method, str(request.url)
        return http.Response(200, json=response_json)

    return http.AsyncClient(transport=http.MockTransport(handler))


def test_list_models_is_a_get_on_v1_models():
    captured: dict = {}
    page = {"data": [{"id": "claude-haiku-5-5", "type": "model", "display_name": "Claude Haiku 5.5",
                      "created_at": "2026-01-01T00:00:00Z"}],
            "has_more": False, "first_id": "claude-haiku-5-5", "last_id": "claude-haiku-5-5"}
    http = pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx
    client = AnthropicClient(api_key="test", http_client=get_client(page, captured, http))
    assert asyncio.run(client.list_models()) == ["claude-haiku-5-5"]
    assert captured["method"] == "GET" and "/v1/models" in captured["url"]

    captured = {}
    page = {"object": "list", "data": [{"id": "gpt-6-luna", "object": "model", "created": 0, "owned_by": "openai"}]}
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", http_client=get_client(page, captured))
    assert asyncio.run(client.list_models()) == ["gpt-6-luna"]
    assert captured["method"] == "GET" and captured["url"].startswith("https://example.test/v1/models")


def test_rate_limit_headers_are_recorded():
    reply = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "ANSWER: 4"}], "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    http = pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx
    headers = {"anthropic-ratelimit-requests-limit": "4000", "anthropic-ratelimit-output-tokens-limit": "80000"}
    transport = http.MockTransport(lambda request: http.Response(200, json=reply, headers=headers))
    client = AnthropicClient(api_key="test", http_client=http.AsyncClient(transport=transport))
    asyncio.run(client.complete(REQUEST))
    assert client.rate_limits == {"requests-limit": "4000", "output-tokens-limit": "80000"}

    completion = {
        "id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-6-luna",
        "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "ANSWER: 4"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 5, "total_tokens": 17},
    }
    transport = httpx.MockTransport(lambda request: httpx.Response(200, json=completion, headers={"x-ratelimit-limit-requests": "500"}))
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", http_client=httpx.AsyncClient(transport=transport))
    asyncio.run(client.complete(REQUEST))
    assert client.rate_limits == {"limit-requests": "500"}


def test_workspace_header_is_sent_only_when_configured(monkeypatch):
    # session 3: a key not scoped to a workspace gets "must include the anthropic-workspace-id header" (400)
    from autoagentnet.providers.registry import ModelConfig

    reply = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "ANSWER: 4"}], "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    http = pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx
    seen: list = []

    def transport():
        return http.MockTransport(lambda request: (seen.append(request.headers.get("anthropic-workspace-id")),
                                                   http.Response(200, json=reply))[1])

    for workspace in ["wrkspc_test", None]:
        client = AnthropicClient(api_key="test", http_client=http.AsyncClient(transport=transport()), workspace_id=workspace)
        asyncio.run(client.complete(REQUEST))
    assert seen == ["wrkspc_test", None]

    cfg = ModelConfig(provider="anthropic", model="m", api_key_env="AAN_K", workspace_id_env="W")
    monkeypatch.delenv("W", raising=False)
    assert cfg.resolved_workspace_id() is None
    monkeypatch.setenv("W", "wrkspc_1")
    assert cfg.resolved_workspace_id() == "wrkspc_1"


def test_thinking_off_options_per_model():
    # session 4: Sonnet 5.5 answers 400 to {"type": "disabled"} and asks for {"type": "between_tools"};
    # Haiku 5.5 accepts disabled (P0, session 4)
    from autoagentnet.providers.registry import ProviderRegistry

    registry = ProviderRegistry.from_yaml("configs/providers.yaml")
    assert registry.options_of("haiku_nothink") == {"thinking": {"type": "disabled"}}
    assert registry.options_of("sonnet_nothink") == {"thinking": {"type": "between_tools"}}
    payload = AnthropicClient.build_payload(REQUEST.model_copy(update={"options": registry.options_of("sonnet_nothink")}))
    assert payload["thinking"] == {"type": "between_tools"}


def test_anthropic_keeps_only_text_blocks():
    reply = {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-sonnet-5-5",
        "content": [{"type": "thinking", "thinking": "scratch", "signature": "s"},
                    {"type": "text", "text": "ANSWER: 4"}],
        "stop_reason": "end_turn", "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    http = pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx
    client = AnthropicClient(api_key="test", http_client=mock_client(reply, {}, http=http))
    assert asyncio.run(client.complete(REQUEST)).text == "ANSWER: 4"


def test_anthropic_streams_a_long_ceiling_and_reads_the_same_fields():
    """A request with max_tokens above STREAM_ABOVE_TOKENS streams (the SDK refuses a long non-streaming request) and
    gives the same text, usage and stop reason."""
    from autoagentnet.providers.anthropic_provider import STREAM_ABOVE_TOKENS

    http = pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx
    events = [
        ("message_start", {"type": "message_start", "message": {
            "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": [],
            "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 1, "cache_creation_input_tokens": 0, "cache_read_input_tokens": 3}}}),
        ("content_block_start", {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}}),
        ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "ANSWER: 4"}}),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                           "usage": {"output_tokens": 7}}),
        ("message_stop", {"type": "message_stop"}),
    ]
    body = "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)
    captured: dict = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return http.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    client = AnthropicClient(api_key="test", http_client=http.AsyncClient(transport=http.MockTransport(handler)))
    long = REQUEST.model_copy(update={"model": "claude-haiku-5-5", "max_tokens": STREAM_ABOVE_TOKENS + 1})
    response = asyncio.run(client.complete(long))
    assert captured["body"]["stream"] is True and captured["body"]["max_tokens"] == STREAM_ABOVE_TOKENS + 1
    assert response.text == "ANSWER: 4" and response.stop_reason == "end_turn"
    assert response.usage.output_tokens == 7 and response.usage.cache_read_tokens == 3


def test_openai_compat_waits_long_enough_for_a_long_reasoning_reply():
    """Audit 82: the client's read timeout is 30 minutes (a 24,576-token Sol reply at about 32 tokens/s takes about 13),
    with a short connect timeout."""
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1")
    assert client._client.timeout.read == 1800.0 and client._client.timeout.connect == 10.0


SSE_CHUNKS = [  # a streamed reply split into deltas, then a usage-only final chunk (stream_options.include_usage)
    {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-6.1-sol",
     "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]},
    {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-6.1-sol",
     "choices": [{"index": 0, "delta": {"content": "work\n\\boxed{4"}, "finish_reason": None}]},
    {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-6.1-sol",
     "choices": [{"index": 0, "delta": {"content": "}"}, "finish_reason": "stop"}]},
    {"id": "c1", "object": "chat.completion.chunk", "created": 0, "model": "gpt-6.1-sol", "choices": [],
     "usage": {"prompt_tokens": 1200, "completion_tokens": 900, "total_tokens": 2100,
               "prompt_tokens_details": {"cached_tokens": 1024, "cache_write_tokens": 0}}},
]
JSON_REPLY = {"id": "c1", "object": "chat.completion", "created": 0, "model": "gpt-6.1-sol",
              "choices": [{"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "work\n\\boxed{4}"}}],
              "usage": {"prompt_tokens": 1200, "completion_tokens": 900, "total_tokens": 2100,
                        "prompt_tokens_details": {"cached_tokens": 1024, "cache_write_tokens": 0}}}


def sse_client(chunks, captured: dict):
    body = "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_openai_compat_payload_is_unchanged_at_or_below_the_streaming_ceiling():
    """Audit 86 (a): up to STREAM_ABOVE_TOKENS the request body is exactly build_payload's."""
    from autoagentnet.providers.openai_compat import STREAM_ABOVE_TOKENS

    captured: dict = {}
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", http_client=mock_client(JSON_REPLY, captured))
    at = REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": STREAM_ABOVE_TOKENS})
    asyncio.run(client.complete(at))
    assert captured["body"] == client.build_payload(at) and "stream" not in captured["body"]


def test_openai_compat_streams_a_long_ceiling_and_reads_the_same_fields():
    """Audit 86 (b): above the ceiling the request streams (exactly stream and stream_options added) and gives the same
    text, usage, model and finish reason as the equivalent JSON reply, so the same cost."""
    from autoagentnet.providers.openai_compat import STREAM_ABOVE_TOKENS

    long = REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": STREAM_ABOVE_TOKENS + 1})
    captured: dict = {}
    streamed = asyncio.run(OpenAICompatClient(api_key="test", base_url="https://example.test/v1",
                                              http_client=sse_client(SSE_CHUNKS, captured)).complete(long))
    plain_client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", http_client=mock_client(JSON_REPLY, {}))
    plain = asyncio.run(plain_client.complete(REQUEST.model_copy(update={"model": "gpt-6.1-sol"})))
    expected = {**plain_client.build_payload(long), "stream": True, "stream_options": {"include_usage": True}}
    assert captured["body"] == expected
    assert (streamed.text, streamed.usage, streamed.model, streamed.stop_reason) == \
        (plain.text, plain.usage, plain.model, plain.stop_reason)
    assert streamed.usage == Usage(input_tokens=176, cache_read_tokens=1024, output_tokens=900)


def test_a_cut_stream_raises_and_leaves_no_cache_entry_and_no_ledger_row():
    """Audit 86 (c): a stream that ends before its finish reason and usage raises; the caller then caches nothing and the
    governor records nothing (its reservation is released)."""
    from pathlib import Path

    from autoagentnet.agents.spec import AgentInput, AgentRequest, AgentSpec
    from autoagentnet.budget import BudgetRules, SpendGovernor
    from autoagentnet.cache import CallCache
    from autoagentnet.market.caller import MarketCaller
    from autoagentnet.meter import Ledger
    from autoagentnet.providers.openai_compat import StreamCut
    from autoagentnet.providers.registry import ProviderRegistry
    from autoagentnet.runtime.local import LocalRuntime

    root = Path(__file__).resolve().parents[1]
    registry = ProviderRegistry.from_yaml(root / "configs/providers.yaml")
    registry.set_client("sol61_med", OpenAICompatClient(api_key="test", base_url="https://example.test/v1",
                                                        http_client=sse_client(SSE_CHUNKS[:2], {})))
    cache, ledger = CallCache(), Ledger()
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(root / "configs/budget.yaml"), run_cap_usd=4.0)
    caller = MarketCaller(LocalRuntime(registry), registry, pricebook=PriceBook.from_yaml(root / "configs/pricing.yaml"),
                          cache=cache, governor=governor, run_id="t", market="t", condition="math", purpose="panel")
    request = AgentRequest(spec=AgentSpec(agent_id="sol61_med.base", stage="panel_math", index=0, model="sol61_med",
                                          system="s", instruction="i", max_tokens=24576, temperature=None),
                           input=AgentInput(task_id="t", task="2+2", shared_prefix=True))
    with pytest.raises(StreamCut):
        asyncio.run(caller.call(request, replicate=0))
    assert len(cache._data) == 0 and ledger.to_frame().empty


def test_a_sol_medium_cache_key_is_unchanged_by_streaming():
    """Audit 86 (d): the key of a fixed sol61_med request (MarketCaller's formula) is what it was before streaming."""
    from pathlib import Path

    from autoagentnet.agents.spec import AgentInput, AgentRequest, AgentSpec
    from autoagentnet.cache import make_key
    from autoagentnet.providers.registry import ProviderRegistry

    registry = ProviderRegistry.from_yaml(Path(__file__).resolve().parents[1] / "configs/providers.yaml")
    request = AgentRequest(spec=AgentSpec(agent_id="sol61_med.base", stage="panel_math", index=0, model="sol61_med",
                                          system="s", instruction="i", max_tokens=24576, temperature=None),
                           input=AgentInput(task_id="t", task="2+2", shared_prefix=True))
    key = make_key(request.spec.model_dump(), registry.model_id("sol61_med"), registry.options_of("sol61_med"),
                   request.input.model_dump(), 0)
    assert key == "136ce7af390e8b9888dffe77a758359cf995e60a6b6372889521d95b82d0e127"


def response_json(status: str, reason: str | None = None, text: str = "work\n\\boxed{4}") -> dict:
    """A Responses API object (D5's background mode) with usage like JSON_REPLY's: 1,200 input tokens of which 1,024
    cached, 900 output tokens of which 600 reasoning."""
    done = status in ("completed", "incomplete")
    return {"id": "resp_1", "object": "response", "created_at": 0, "model": "gpt-6.1-sol", "status": status,
            "background": True, "error": None,
            "incomplete_details": {"reason": reason} if reason else None,
            "output": [{"id": "msg_1", "type": "message", "role": "assistant", "status": "completed",
                        "content": [{"type": "output_text", "text": text, "annotations": []}]}] if done else [],
            "usage": {"input_tokens": 1200, "input_tokens_details": {"cached_tokens": 1024}, "output_tokens": 900,
                      "output_tokens_details": {"reasoning_tokens": 600}, "total_tokens": 2100} if done else None}


def background_client(finals: list[dict], seen: list, cancelled: dict | None = None):
    """A fake OpenAI transport for background mode: POST /responses queues the job; each GET /responses/resp_1 returns
    the next object of `finals` (in progress, then a final status); POST .../cancel cancels (returning `cancelled`,
    by default a cancelled response without usage; a `cancelled` with an "error" key is refused with a 400)."""
    queue = list(finals)

    def handler(request):
        path = request.url.path
        seen.append((request.method, path, json.loads(request.content) if request.content else None))
        if request.method == "POST" and path.endswith("/responses"):
            return httpx.Response(200, json=response_json("queued"))
        if path.endswith("/cancel"):
            if cancelled and cancelled.get("error") and "status" not in cancelled:
                return httpx.Response(400, json=cancelled)
            return httpx.Response(200, json=cancelled or response_json("cancelled"))
        return httpx.Response(200, json=queue.pop(0) if queue else response_json("in_progress"))

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_background_mode_submits_polls_and_reads_the_finished_response():
    """D5: above the ceiling, an endpoint set to long_requests="background" submits the Responses API form of the
    payload (background and store added), polls until a final status, and reads text, usage (cached and reasoning
    tokens apart) and finish reason. At or below the ceiling it is the plain Chat Completions request."""
    from autoagentnet.providers.openai_compat import STREAM_ABOVE_TOKENS

    seen: list = []
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client(
                                    [response_json("in_progress"), response_json("completed")], seen))
    long = REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": STREAM_ABOVE_TOKENS + 1,
                                      "options": {"reasoning_effort": "medium"}})
    out = asyncio.run(client.complete(long))
    assert seen[0][:2] == ("POST", "/v1/responses") and seen[0][2] == client.responses_payload(long)
    assert seen[0][2]["background"] is True and seen[0][2]["store"] is True
    assert seen[0][2]["reasoning"] == {"effort": "medium"} and seen[0][2]["max_output_tokens"] == STREAM_ABOVE_TOKENS + 1
    assert seen[0][2]["input"] == client.build_payload(long)["messages"]
    assert [m for m, _, _ in seen[1:]] == ["GET", "GET"]  # polled until completed
    assert out.text == "work\n\\boxed{4}" and out.stop_reason == "stop" and out.model == "gpt-6.1-sol"
    assert out.usage == Usage(input_tokens=176, cache_read_tokens=1024, output_tokens=900, thinking_tokens=600)
    captured: dict = {}
    short = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                               http_client=mock_client(JSON_REPLY, captured))
    asyncio.run(short.complete(long.model_copy(update={"max_tokens": STREAM_ABOVE_TOKENS})))
    assert captured["url"].endswith("/chat/completions")


def test_background_mode_maps_a_cut_reply_to_length_and_raises_on_failure():
    """D5: an incomplete response cut by the output ceiling is "length" (the panel's truncation); a failed one raises
    BackgroundFailed, so the caller caches nothing and the governor records nothing."""
    from autoagentnet.providers.openai_compat import STREAM_ABOVE_TOKENS, BackgroundFailed

    long = REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": STREAM_ABOVE_TOKENS + 1})
    cut = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background", poll_s=0.0,
                             http_client=background_client([response_json("incomplete", "max_output_tokens")], []))
    assert asyncio.run(cut.complete(long)).stop_reason == "length"
    failed = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background", poll_s=0.0,
                                http_client=background_client([response_json("failed")], []))
    with pytest.raises(BackgroundFailed):
        asyncio.run(failed.complete(long))


def test_background_mode_returns_a_safety_block_as_a_refusal():
    """A failed background response whose error code is a safety policy (OpenAI's "bio_policy") is the provider's
    refusal: an empty reply with stop_reason "content_filter" (graded wrong, no vote, counted by the stop rules), not
    an exception that stops the run. Any other failure still raises."""
    from autoagentnet.providers.openai_compat import STREAM_ABOVE_TOKENS, BackgroundFailed

    long = REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": STREAM_ABOVE_TOKENS + 1})
    blocked = response_json("failed")
    blocked["error"] = {"code": "bio_policy", "message": "This content was flagged for possible biological risk."}
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client([blocked], []))
    out = asyncio.run(client.complete(long))
    assert out.text == "" and out.stop_reason == "content_filter" and out.usage == Usage()
    assert out.extra["safety_block"] == "bio_policy"
    other = response_json("failed")
    other["error"] = {"code": "server_error", "message": "The server had an error."}
    failed = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client([other], []))
    with pytest.raises(BackgroundFailed):
        asyncio.run(failed.complete(long))


def test_background_mode_cuts_a_job_past_the_timeout(monkeypatch):
    """Audit 106: a job still running after BACKGROUND_TIMEOUT_S is cancelled and returned as a cut call ("length", so
    it is ledgered and graded wrong), priced from the cancelled response's usage, or at the whole output ceiling when
    that response carries none."""
    import autoagentnet.providers.openai_compat as O

    monkeypatch.setattr(O, "BACKGROUND_TIMEOUT_S", 0.0)
    long = REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": O.STREAM_ABOVE_TOKENS + 1})
    seen: list = []
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client([], seen))
    out = asyncio.run(client.complete(long))
    assert seen[-1][1].endswith("/responses/resp_1/cancel")
    assert out.stop_reason == "length" and out.text == "" and out.usage == Usage(output_tokens=long.max_tokens)
    billed = {**response_json("cancelled"), "usage": response_json("completed")["usage"]}
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client([], [], cancelled=billed))
    out = asyncio.run(client.complete(long))
    assert out.stop_reason == "length"
    assert out.usage == Usage(input_tokens=176, cache_read_tokens=1024, output_tokens=900, thinking_tokens=600)
    # audit 107: a cancel the API refuses (the job finished meanwhile) is settled by one retrieve, read as usual
    refused = {"error": {"message": "Cannot cancel a completed response", "type": "invalid_request_error"}}
    seen = []
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client([response_json("completed")], seen, refused))
    out = asyncio.run(client.complete(long))
    assert [m for m, _, _ in seen[-2:]] == ["POST", "GET"] and seen[-2][1].endswith("/cancel")
    assert out.stop_reason == "stop" and out.text == "work\n\\boxed{4}" and out.usage.output_tokens == 900


def test_background_limit_scales_with_the_ceiling():
    """LAB-Bench note 15: 1.5 x the ceiling's time at 24 tokens/s, at least 30 and at most 90 minutes."""
    import autoagentnet.providers.openai_compat as O

    assert O.background_limit_s(24576) == 1800.0 and O.background_limit_s(16384) == 1800.0
    assert O.background_limit_s(40000) == 2500.0 and O.background_limit_s(128000) == 5400.0


def test_background_mode_cancels_the_job_when_polling_fails():
    """Audit 97: an error while polling (here a retrieve the API rejects) cancels the job before the error is raised,
    so a job no ledger row records does not keep running and billing."""
    from openai import BadRequestError

    import autoagentnet.providers.openai_compat as O

    seen: list = []

    def handler(request):
        seen.append((request.method, request.url.path))
        if request.method == "POST" and request.url.path.endswith("/responses"):
            return httpx.Response(200, json=response_json("queued"))
        if request.url.path.endswith("/cancel"):
            return httpx.Response(200, json=response_json("cancelled"))
        return httpx.Response(400, json={"error": {"message": "bad id", "type": "invalid_request_error", "code": None}})

    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with pytest.raises(BadRequestError):
        asyncio.run(client.complete(REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": O.STREAM_ABOVE_TOKENS + 1})))
    assert seen[-1] == ("POST", "/v1/responses/resp_1/cancel")


def test_background_mode_reads_cache_writes():
    """Audit 97: the background path reads cache_write_tokens as the chat path does, so cache writes are priced at
    their own rate."""
    import autoagentnet.providers.openai_compat as O

    done = response_json("completed")
    done["usage"]["input_tokens_details"] = {"cached_tokens": 1024, "cache_write_tokens": 100}
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", long_requests="background",
                                poll_s=0.0, http_client=background_client([done], []))
    out = asyncio.run(client.complete(REQUEST.model_copy(update={"model": "gpt-6.1-sol", "max_tokens": O.STREAM_ABOVE_TOKENS + 1})))
    assert out.usage == Usage(input_tokens=76, cache_write_tokens=100, cache_read_tokens=1024, output_tokens=900,
                              thinking_tokens=600)


def test_background_mode_is_set_on_openai_refs_only_and_leaves_cache_keys_alone():
    """D5: OpenAI's own refs use background mode; other hosts and Anthropic refs do not; the option is provider
    configuration, not a request option, so no cache key changes."""
    from pathlib import Path

    from autoagentnet.providers.registry import ProviderRegistry

    registry = ProviderRegistry.from_yaml(Path(__file__).resolve().parents[1] / "configs/providers.yaml")
    assert registry.config("sol61_low").long_requests == "background" and registry.config("luna_med").long_requests == "background"
    assert registry.config("maritime_proxy").long_requests == "stream"
    assert "long_requests" not in registry.options_of("sol61_med")


def test_reasoning_and_thinking_tokens_are_read():
    """Session E6 (study CD): thinking tokens are recorded from both vendors' usage (Chat Completions
    completion_tokens_details.reasoning_tokens; Anthropic output_tokens_details.thinking_tokens)."""
    from autoagentnet.providers.anthropic_provider import thinking_tokens

    reply = {**JSON_REPLY, "usage": {**JSON_REPLY["usage"], "completion_tokens_details": {"reasoning_tokens": 700}}}
    client = OpenAICompatClient(api_key="test", base_url="https://example.test/v1", http_client=mock_client(reply, {}))
    assert asyncio.run(client.complete(REQUEST.model_copy(update={"model": "gpt-6.1-sol"}))).usage.thinking_tokens == 700

    class U:
        output_tokens_details = {"thinking_tokens": 321}

    assert thinking_tokens(U()) == 321 and thinking_tokens(object()) == 0
    assert (Usage(output_tokens=5, thinking_tokens=3) + Usage(output_tokens=2, thinking_tokens=1)).thinking_tokens == 4


def test_anthropic_output_block_is_recognised_only_for_the_content_filter_400():
    from autoagentnet.providers.anthropic_provider import is_output_block

    class BadRequestError(Exception):
        pass

    assert is_output_block(BadRequestError("Error code: 400 - Output blocked by content filtering policy"))
    assert not is_output_block(BadRequestError("Error code: 400 - max_tokens too large"))
    assert not is_output_block(RuntimeError("Output blocked by content filtering policy"))
