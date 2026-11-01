"""Claude through the Anthropic Messages API, with explicit prompt caching.

Timing (session M1, providers/timing.py): with `timing` on (set from the run's config through the registry) every
request streams, and the time of each stream event is recorded in LLMResponse.extra. Transport only, as audit 86
established for OpenAI: the payload gains only `stream: true`, and usage, model and stop reason are read from the
final message as from a JSON reply; nothing in a cache key changes."""

from __future__ import annotations

import inspect
import time
from typing import Any

from .base import LLMRequest, LLMResponse, Usage
from .timing import CURRENT, CallTimer, install_hooks

EPHEMERAL = {"type": "ephemeral"}
MAX_CACHE_BREAKPOINTS = 4  # Anthropic API limit per request
STREAM_ABOVE_TOKENS = 16000  # a longer ceiling streams the reply: the SDK refuses a non-streaming request that may take
# over 10 minutes (seen at 36,864 for Haiku, session E5); the final message is the same object either way



def is_output_block(exc: BaseException) -> bool:
    """True for the API's output safety block: a 400 bad request whose message says the output was blocked by the
    content filtering policy."""
    return type(exc).__name__ == "BadRequestError" and "content filtering" in str(exc).lower()

class AnthropicClient:
    provider = "anthropic"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: Any = None,
        max_retries: int = 3,
        workspace_id: str | None = None,
        timing: bool = False,
    ):
        from anthropic import AsyncAnthropic, DefaultAsyncHttpxClient  # lazy: the SDK is an optional extra

        if not api_key:  # key hygiene (patch 2.1): the SDK would otherwise read ANTHROPIC_API_KEY from the environment
            raise ValueError("an explicit api_key is required; ANTHROPIC_API_KEY is never used")

        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": max_retries}
        if base_url:
            kwargs["base_url"] = base_url
        if workspace_id:  # a key not scoped to a workspace must name one on every request (API error 400 otherwise)
            kwargs["default_headers"] = {"anthropic-workspace-id": workspace_id}
        # the SDK's own default client, made here so the timing hooks (retries, status, headers) can be added to it
        http_client = http_client if http_client is not None else DefaultAsyncHttpxClient()
        install_hooks(http_client)
        kwargs["http_client"] = http_client
        self._client = AsyncAnthropic(**kwargs)
        self.rate_limits: dict[str, str] = {}  # last anthropic-ratelimit-* headers seen (limits, remaining, reset)
        self.timing = timing  # stream every request and record its event times (session M1)

    @staticmethod
    def build_payload(request: LLMRequest) -> dict[str, Any]:
        """Translate the neutral request into Messages API arguments."""
        payload: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [{"role": "user", "content": []}],
        }
        breakpoints = 0
        if request.system:
            system_block: dict[str, Any] = {"type": "text", "text": request.system}
            if request.cache_system:
                system_block["cache_control"] = EPHEMERAL
                breakpoints += 1
            payload["system"] = [system_block]
        for block in request.blocks:
            item: dict[str, Any] = {"type": "text", "text": block.text}
            if block.cache:
                item["cache_control"] = EPHEMERAL
                breakpoints += 1
            payload["messages"][0]["content"].append(item)
        if breakpoints > MAX_CACHE_BREAKPOINTS:
            raise ValueError(f"{breakpoints} cache breakpoints; the API allows {MAX_CACHE_BREAKPOINTS}")
        # request.temperature is not sent: the current Messages API (SDK 1.x) has no
        # sampling parameters. Repeatability comes from the call cache instead.
        payload.update(request.options)
        return payload

    async def list_models(self) -> list[str]:
        """Model IDs this key can use (GET /v1/models; free, no tokens billed)."""
        return [m.id async for m in self._client.models.list()]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        start = time.perf_counter()
        payload = self.build_payload(request)
        timer = CallTimer(streamed=self.timing or request.max_tokens > STREAM_ABOVE_TOKENS, t_submit=start)
        token = CURRENT.set(timer)
        try:
            message, headers = await self._send(payload, timer)
        except Exception as exc:  # noqa: BLE001 - only an output safety block is turned into a reply; anything else re-raises
            if not is_output_block(exc):
                raise
            # The API blocked the output (HTTP 400 "Output blocked by content filtering policy", seen 2026-11-01 on a
            # handoff wrong-trace prompt): the same outcome as stop_reason "refusal", returned as a refused reply (empty
            # text; graded wrong, no vote, counted by the stop rules), booked at $0 because no usage is returned.
            return LLMResponse(text="", usage=Usage(), model=str(payload.get("model", "")), provider=self.provider,
                               latency_s=time.perf_counter() - start, stop_reason="refusal",
                               extra={"safety_block": "output_content_filter"})
        finally:
            CURRENT.reset(token)
        end = time.perf_counter()
        latency_s = end - start
        self.rate_limits = {k.removeprefix("anthropic-ratelimit-"): v for k, v in headers.items()
                            if k.startswith("anthropic-ratelimit-")}
        text = "".join(part.text for part in message.content if part.type == "text")
        usage = Usage(
            input_tokens=message.usage.input_tokens,
            cache_write_tokens=message.usage.cache_creation_input_tokens or 0,
            cache_read_tokens=message.usage.cache_read_input_tokens or 0,
            output_tokens=message.usage.output_tokens,
            thinking_tokens=thinking_tokens(message.usage),
        )
        extra = timer.extra(usage.output_tokens, usage.thinking_tokens, message.model, end=end)
        return LLMResponse(
            text=text,
            usage=usage,
            model=message.model,
            provider=self.provider,
            latency_s=latency_s,
            stop_reason=message.stop_reason,
            extra=extra,
        )

    async def _send(self, payload: dict[str, Any], timer: CallTimer):
        """(final message, response headers): streamed with every event timed when timer.streamed, else one JSON
        reply."""
        if timer.streamed:
            async with self._client.messages.stream(**payload) as stream:
                async for event in stream:
                    mark(timer, event)
                message = await stream.get_final_message()
                headers = getattr(getattr(stream, "response", None), "headers", {}) or {}
        else:
            raw = await self._client.messages.with_raw_response.create(**payload)
            message = raw.parse()
            if inspect.isawaitable(message):
                message = await message
            headers = raw.headers
        return message, headers


THINKING_BLOCKS = {"thinking", "redacted_thinking"}
THINKING_DELTAS = {"thinking_delta", "signature_delta"}


def mark(timer: CallTimer, event) -> None:
    """Record one stream event's time: any event (t_first_event, t_last), a content block or delta (first token),
    thinking (a thinking block opening or a thinking delta), visible answer text (a non-empty text delta). The SDK's
    helper events ("text", "thinking", ...) repeat a raw delta and are skipped so each arrival counts once."""
    kind = getattr(event, "type", None)
    if kind == "content_block_start":
        block = getattr(event, "content_block", None)
        if getattr(block, "type", None) in THINKING_BLOCKS:
            timer.thinking()
        else:
            timer.token()
    elif kind == "content_block_delta":
        delta = getattr(event, "delta", None)
        dtype = getattr(delta, "type", None)
        if dtype in THINKING_DELTAS:
            timer.thinking()
        elif dtype == "text_delta":
            timer.answer(getattr(delta, "text", "") or "")
        else:
            timer.token()
    elif kind in ("message_start", "message_delta", "message_stop", "content_block_stop", "ping"):
        timer.event()


def thinking_tokens(usage) -> int:
    """The thinking part of a reply's output tokens (usage.output_tokens_details.thinking_tokens); 0 when absent."""
    details = getattr(usage, "output_tokens_details", None)
    if isinstance(details, dict):
        return int(details.get("thinking_tokens") or 0)
    return int(getattr(details, "thinking_tokens", 0) or 0) if details is not None else 0
