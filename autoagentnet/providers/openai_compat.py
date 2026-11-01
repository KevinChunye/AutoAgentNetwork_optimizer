"""Any endpoint that speaks the OpenAI Chat Completions API.

One client covers OpenAI, Maritime's built-in LLM proxy, OpenRouter, vLLM,
LiteLLM and Ollama; only ``base_url`` and the API key change. These endpoints
cache shared prompt prefixes automatically, so ``Block.cache`` is ignored here.
"""

from __future__ import annotations

import asyncio
import inspect
import time
from typing import Any

from .base import LLMRequest, LLMResponse, Usage
from .timing import CURRENT, CallTimer, background_extra, install_hooks


INVALID_PROMPT = "invalid_prompt"
BLOCK_ATTEMPTS = 3  # a blocked prompt is tried up to 3 times in all (blocks are not billed)


def blocked_prompt(exc) -> bool:
    """True for OpenAI's 400 "invalid_prompt" (the prompt was flagged before any answer); False for other 400s."""
    body = getattr(exc, "body", None)
    code = getattr(exc, "code", None) or (body.get("code") if isinstance(body, dict) else None)
    if code is None and isinstance(body, dict) and isinstance(body.get("error"), dict):
        code = body["error"].get("code")
    return code == INVALID_PROMPT


REQUEST_TIMEOUT_S = 1800.0  # seconds a request may take (audit 82)
STREAM_ABOVE_TOKENS = 8192  # audit 86: a request with a longer ceiling streams. Transport only: the payload gains
# exactly "stream" and "stream_options", nothing in a cache key changes, and usage, model and finish reason are read
# from the stream as from a JSON reply. Audit 87: streaming does not make bytes flow while the model reasons (no
# response headers came before a long Sol medium request's 500), so it does not by itself prevent long-request failures.


# Timing (session M1, providers/timing.py): with `timing` on, every chat request streams (the same transport-only
# change as above) and each chunk's arrival is timed; background-mode calls record total latency only.


class StreamCut(RuntimeError):
    """A streamed reply that ended without a finish reason or a usage record: nothing usable came back."""


# D5 (Kevin, session E6): a long request (ceiling above STREAM_ABOVE_TOKENS) on an endpoint configured with
# long_requests="background" goes through the Responses API in background mode: submit the request
# (background: true), poll it by id every BACKGROUND_POLL_S seconds until it reaches a final status, then read the
# answer from the finished response. Each poll is a short request, so a dropped connection costs one poll (the SDK
# retries it), not the whole answer. Transport only: the cache key, the ledger and the pricing are those of any call
# (usage is read from the finished response). A job still running after BACKGROUND_TIMEOUT_S is cancelled and
# recorded as a cut call (stop reason "length") with the cancelled response's usage, or with the whole output ceiling
# when that response carries none, so the ledger never records less than OpenAI may bill (audit 106: at Sol's 24-37
# output tokens per second, E5's live rate, the old 1,800 s limit cut a call near 43,000-67,000 tokens and raised with
# nothing ledgered; 90 minutes covers 128,000 tokens at 24 per second).
# LAB-Bench note 15 (2026-11-01): OpenAI's queue twice held a short job (a 24,576-token ceiling, replies under 3
# minutes otherwise) for the whole 90 minutes. The limit now scales with the request's own ceiling: the time a reply
# of the whole ceiling takes at Sol's slowest measured rate (SLOWEST_TOKENS_PER_S), with 50% margin, at least
# BACKGROUND_MIN_S (the streamed-request limit) and at most BACKGROUND_TIMEOUT_S. A 128,000-token request keeps 90
# minutes; a 24,576-token one gets 30 (a full reply at 24 tokens/s takes 17).
BACKGROUND_POLL_S = 5.0
BACKGROUND_TIMEOUT_S = 5400.0
BACKGROUND_MIN_S = 1800.0
SLOWEST_TOKENS_PER_S = 24.0
BACKGROUND_REQUEST_S = 60.0  # audit 107: each poll and the cancel are short requests, so a hung one is cut after 60 s
# (with the client's retries) instead of the 1,800 s a whole answer may take
BACKGROUND_FINAL = {"completed", "incomplete", "failed", "cancelled"}
# Error codes of a failed background response that mean the provider's safety system blocked the content (a refusal),
# not a transport or server fault. Seen: "bio_policy" (LAB-Bench SeqQA, 2026-11-01).
SAFETY_BLOCK_CODES = {"bio_policy", "cyber_policy", "content_policy", "safety_policy"}


def background_limit_s(max_tokens: int) -> float:
    """Seconds a background job with this output ceiling may run before it is cut (see BACKGROUND_MIN_S above)."""
    return min(BACKGROUND_TIMEOUT_S, max(BACKGROUND_MIN_S, 1.5 * max_tokens / SLOWEST_TOKENS_PER_S))


class BackgroundFailed(RuntimeError):
    """A background response that ended failed or was cancelled by someone else: nothing usable came back."""


def background_usage(u: Any) -> Usage:
    """A Responses API usage object as the ledger books it: uncached input apart from cache reads and cache writes (as
    the chat path reads them, audit 97), output tokens with the reasoning tokens among them."""
    details = getattr(u, "input_tokens_details", None)
    cache_read = getattr(details, "cached_tokens", 0) or 0
    cache_write = getattr(details, "cache_write_tokens", 0) or 0
    return Usage(input_tokens=max(u.input_tokens - cache_read - cache_write, 0), cache_write_tokens=cache_write,
                 cache_read_tokens=cache_read, output_tokens=u.output_tokens,
                 thinking_tokens=getattr(getattr(u, "output_tokens_details", None), "reasoning_tokens", 0) or 0)


class OpenAICompatClient:
    provider = "openai_compat"

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        http_client: Any = None,
        max_retries: int = 3,
        token_param: str = "max_completion_tokens",  # some hosts only accept "max_tokens"
        send_temperature: bool = True,  # some reasoning models reject a temperature
        long_requests: str = "stream",  # "stream" or "background" (D5; OpenAI's own API only) above the ceiling
        poll_s: float = BACKGROUND_POLL_S,
        timing: bool = False,
    ):
        from openai import AsyncOpenAI, DefaultAsyncHttpxClient  # lazy: the SDK is an optional extra

        if not api_key:  # key hygiene (patch 2.1): the SDK would otherwise read OPENAI_API_KEY from the environment
            raise ValueError("an explicit api_key is required; OPENAI_API_KEY is never used")

        import httpx  # the SDK's own HTTP library

        # a 30-minute read timeout (audit 82): at Sol's slowest measured speed (about 32 tokens/s) a 24,576-token reply
        # takes about 13 minutes, past the SDK's 10-minute default, and a timed-out call may be billed and then retried.
        # The timeout is transport only: it is not part of any cache key.
        kwargs: dict[str, Any] = {"api_key": api_key, "max_retries": max_retries,
                                  "timeout": httpx.Timeout(REQUEST_TIMEOUT_S, connect=10.0)}
        if base_url:
            kwargs["base_url"] = base_url
        # the SDK's own default client, made here so the timing hooks (retries, status, headers) can be added to it
        http_client = http_client if http_client is not None else DefaultAsyncHttpxClient()
        install_hooks(http_client)
        kwargs["http_client"] = http_client
        self._client = AsyncOpenAI(**kwargs)
        self.timing = timing  # stream every chat request and record its chunk times (session M1)
        self.token_param = token_param
        self.send_temperature = send_temperature
        if long_requests not in ("stream", "background"):
            raise ValueError(f"long_requests must be 'stream' or 'background', not {long_requests!r}")
        self.long_requests = long_requests
        self.poll_s = poll_s
        self.rate_limits: dict[str, str] = {}  # last x-ratelimit-* headers seen

    def build_payload(self, request: LLMRequest) -> dict[str, Any]:
        messages = []
        if request.system:
            messages.append({"role": "system", "content": request.system})
        messages.append({"role": "user", "content": "\n\n".join(b.text for b in request.blocks)})
        payload: dict[str, Any] = {
            "model": request.model,
            "messages": messages,
            self.token_param: request.max_tokens,
        }
        if self.send_temperature and request.temperature is not None:
            payload["temperature"] = request.temperature
        payload.update(request.options)  # e.g. {"reasoning_effort": "low"}
        return payload

    async def list_models(self) -> list[str]:
        """Model IDs this key can use (GET /v1/models; free, no tokens billed)."""
        return [m.id async for m in self._client.models.list()]

    def responses_payload(self, request: LLMRequest) -> dict[str, Any]:
        """D5: build_payload in the Responses API's form, for background mode. The same model, the same messages (as
        `input`), the same output ceiling (as `max_output_tokens`) and the same options; `reasoning_effort` becomes
        `reasoning: {effort}`. `background` and `store` (background mode needs a stored response) are added."""
        chat = self.build_payload(request)
        payload: dict[str, Any] = {"model": chat.pop("model"), "input": chat.pop("messages"),
                                   "max_output_tokens": chat.pop(self.token_param), "background": True, "store": True}
        effort = chat.pop("reasoning_effort", None)
        if effort is not None:
            payload["reasoning"] = {"effort": effort}
        payload.update(chat)  # temperature and any other option, as written
        return payload

    async def complete_background(self, request: LLMRequest) -> LLMResponse:
        """D5: submit, poll, fetch (see BACKGROUND_POLL_S). A prompt blocked on every attempt is recorded as in
        `complete`. Finish reasons map to the Chat Completions names the panel reads: "stop" when completed, "length"
        when the output ceiling cut it ("incomplete", reason max_output_tokens), "content_filter" when a filter did."""
        from openai import BadRequestError

        start = time.perf_counter()
        timer = CallTimer(t_submit=start)
        for attempt in range(BLOCK_ATTEMPTS):
            try:
                job = await self._client.responses.create(**self.responses_payload(request))
                break
            except BadRequestError as exc:
                if not blocked_prompt(exc):
                    raise
        else:
            return LLMResponse(text="", usage=Usage(), model=request.model, provider=self.provider,
                               latency_s=time.perf_counter() - start, stop_reason=INVALID_PROMPT)
        limit = background_limit_s(request.max_tokens)
        try:
            while job.status not in BACKGROUND_FINAL:
                if time.perf_counter() - start > limit:
                    return await self.cut_at_timeout(job, request, start)
                await asyncio.sleep(self.poll_s)
                job = await self._client.responses.retrieve(job.id, timeout=BACKGROUND_REQUEST_S)
        except BaseException:  # audit 97: a job left running bills tokens no ledger row records, so any failure while
            # polling (a timeout, a retrieve error, the run being stopped) cancels it, as far as the API allows
            await self.cancel_quietly(job.id)
            raise
        return self.finished(job, start, timer)

    def finished(self, job: Any, start: float, timer: CallTimer | None = None) -> LLMResponse:
        """The answer of a job in a final state (raises BackgroundFailed when it failed or someone else cancelled it).
        timer: the call's stamps (session M1); background calls record total latency only."""
        error = getattr(job, "error", None)
        code = str(getattr(error, "code", "") or "")
        if job.status == "failed" and code in SAFETY_BLOCK_CODES:
            # The provider's safety system blocked the answer (e.g. "bio_policy" on LAB-Bench, 2026-11-01): the same
            # outcome as Anthropic's stop_reason "refusal", so it is returned as a refused reply (empty text,
            # "content_filter"; graded wrong, no vote, counted by the stop rules) with whatever usage was billed.
            u = getattr(job, "usage", None)
            return LLMResponse(text="", usage=background_usage(u) if u is not None else Usage(), model=job.model,
                               provider=self.provider, latency_s=time.perf_counter() - start,
                               stop_reason="content_filter", extra={"safety_block": code})
        if job.status in ("failed", "cancelled"):
            raise BackgroundFailed(f"response {job.id} {job.status}: {error}")
        reason = getattr(getattr(job, "incomplete_details", None), "reason", None)
        finish = "stop" if job.status == "completed" else {"max_output_tokens": "length"}.get(reason, reason or "incomplete")
        usage = background_usage(job.usage)
        end = time.perf_counter()
        return LLMResponse(text=job.output_text or "", usage=usage, model=job.model, provider=self.provider,
                           latency_s=end - start, stop_reason=finish,
                           extra=background_extra(timer or CallTimer(t_submit=start), usage.output_tokens, job.model,
                                                  end=end))

    async def cut_at_timeout(self, job: Any, request: LLMRequest, start: float) -> LLMResponse:
        """A job past its limit (background_limit_s): cancel it and return a cut call ("length", graded wrong like any cut call)
        priced from the cancelled response's usage; without usage, the whole ceiling is booked as output tokens. A
        cancel the API refuses (the job finished inside the last poll's window) is settled by one retrieve: a finished
        job is read as usual (audit 107)."""
        try:
            done = await self._client.responses.cancel(job.id, timeout=BACKGROUND_REQUEST_S)
        except Exception:
            done = await self._client.responses.retrieve(job.id, timeout=BACKGROUND_REQUEST_S)
            if done.status in ("completed", "incomplete"):
                return self.finished(done, start)
        u = getattr(done, "usage", None) or getattr(job, "usage", None)
        usage = Usage(output_tokens=request.max_tokens) if u is None else background_usage(u)
        return LLMResponse(text=getattr(done, "output_text", None) or "", usage=usage, model=job.model,
                           provider=self.provider, latency_s=time.perf_counter() - start, stop_reason="length")

    async def cancel_quietly(self, job_id: str) -> None:
        """Best-effort cancel of a background job; a failure to cancel is not raised over the error that caused it."""
        try:
            await self._client.responses.cancel(job_id, timeout=BACKGROUND_REQUEST_S)
        except Exception:
            pass

    async def complete(self, request: LLMRequest) -> LLMResponse:
        from openai import BadRequestError

        if request.max_tokens > STREAM_ABOVE_TOKENS and self.long_requests == "background":
            return await self.complete_background(request)
        start = time.perf_counter()
        streamed = self.timing or request.max_tokens > STREAM_ABOVE_TOKENS
        timer = CallTimer(streamed=streamed, t_submit=start)
        token = CURRENT.set(timer)
        try:
            return await self._complete_chat(request, timer)
        finally:
            CURRENT.reset(token)

    async def _complete_chat(self, request: LLMRequest, timer: CallTimer) -> LLMResponse:
        from openai import BadRequestError

        start, streamed = timer.t_submit, timer.streamed
        for attempt in range(BLOCK_ATTEMPTS):
            try:
                if streamed:
                    payload = {**self.build_payload(request), "stream": True, "stream_options": {"include_usage": True}}
                else:
                    payload = self.build_payload(request)
                raw = await self._client.chat.completions.with_raw_response.create(**payload)
                break
            except BadRequestError as exc:
                if not blocked_prompt(exc):
                    raise
        else:
            # OpenAI's prompt filter rejected the prompt before any answer (400, code invalid_prompt; nothing billed)
            # on every attempt. The filter is intermittent (session E4, e13_bbeh_open: luna_none call 0 on
            # bbeh-geometric_shapes-1128 was blocked once while the same request passed six times; audit 54), so a
            # block is retried and only a block on every attempt is recorded: an empty reply with stop_reason
            # "invalid_prompt", which the panel counts as refused and unparsed.
            return LLMResponse(text="", usage=Usage(), model=request.model, provider=self.provider,
                               latency_s=time.perf_counter() - start, stop_reason=INVALID_PROMPT)
        completion = raw.parse()
        if inspect.isawaitable(completion):
            completion = await completion
        self.rate_limits = {k.removeprefix("x-ratelimit-"): v for k, v in raw.headers.items() if k.startswith("x-ratelimit-")}
        if streamed:
            text, raw, model, finish = await read_stream(completion, timer)
        else:
            text, raw = completion.choices[0].message.content or "", completion.usage
            model, finish = completion.model, completion.choices[0].finish_reason
        end = time.perf_counter()
        latency_s = end - start
        details = getattr(raw, "prompt_tokens_details", None)
        cache_read = (getattr(details, "cached_tokens", 0) or 0) if details else 0
        cache_write = (getattr(details, "cache_write_tokens", 0) or 0) if details else 0
        reasoning = getattr(getattr(raw, "completion_tokens_details", None), "reasoning_tokens", 0) or 0
        usage = Usage(
            input_tokens=max(raw.prompt_tokens - cache_read - cache_write, 0),
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            output_tokens=raw.completion_tokens,
            thinking_tokens=reasoning,
        )
        timer.hidden_reasoning = reasoning > 0
        return LLMResponse(
            text=text,
            usage=usage,
            model=model,
            provider=self.provider,
            latency_s=latency_s,
            stop_reason=finish,
            extra=timer.extra(usage.output_tokens, usage.thinking_tokens, model, end=end),
        )


REASONING_DELTAS = ("reasoning_content", "reasoning")  # hosts that stream reasoning text (vLLM, OpenRouter); OpenAI does not


async def read_stream(stream, timer: CallTimer | None = None) -> tuple[str, Any, str, str]:
    """(text, usage, model, finish reason) of a streamed chat completion: the text deltas joined, the finish reason of
    the last chunk that has one, and the usage of the final usage-only chunk (stream_options.include_usage). A stream
    that ends without a finish reason or a usage record raises StreamCut, so nothing is cached or ledgered for it.
    With a timer, each chunk's arrival is recorded: a chunk with a choice is a token (reasoning text a thinking token,
    non-empty content an answer token), a chunk without one (the usage record) an event."""
    parts: list[str] = []
    usage = model = finish = None
    timer = timer or CallTimer(streamed=True)
    async for chunk in stream:
        model = chunk.model or model
        if chunk.usage is not None:
            usage = chunk.usage
        if not chunk.choices:
            timer.event()
        for choice in chunk.choices:
            delta = choice.delta
            if delta is not None and any(getattr(delta, k, None) for k in REASONING_DELTAS):
                timer.thinking()
            if delta is not None and delta.content:
                parts.append(delta.content)
                timer.answer(delta.content)
            else:
                timer.token()
            if choice.finish_reason is not None:
                finish = choice.finish_reason
    if finish is None or usage is None:
        raise StreamCut(f"stream ended without {'a finish reason' if finish is None else 'a usage record'}")
    return "".join(parts), usage, model, finish
