"""Per-call timing for API and local providers (session M1; research/v4/measurement.md has the full definitions).

Plain words first. A call is one request to a model, from the moment we send it to the moment the last byte of the
reply arrives. When the reply is streamed, the model's output arrives as a series of events, and the time each event
arrives tells us how long the model waited before it started to write and how fast it wrote.

Clock: time.perf_counter (monotonic, sub-millisecond) for every interval, plus one UTC wall-clock stamp per call
(t_submit_utc) so a call can be placed in the day (latency varies with time of day and provider load).

Stamps of one call (seconds on the perf_counter clock):
  t_submit          the request is handed to the SDK (retries included in everything after it)
  t_first_event     the first streamed event of any kind (Anthropic: message_start; OpenAI: the first chunk)
  t_first_token     the first event that carries model output of any kind, thinking included (Anthropic: the first
                    content block or delta; OpenAI: the first chunk with a content or reasoning delta, else the first
                    chunk with a choice)
  t_first_thinking  the first thinking event (Anthropic thinking block or delta; reasoning deltas on hosts that stream
                    them). Claude 5.5 models default to thinking display "omitted": the thinking block streams with
                    empty text, so this is when the thinking block opened, not when visible thinking text arrived
  t_first_answer    the first non-empty piece of visible answer text
  t_last            the last event of the stream (or the end of the reply when not streamed)

Derived numbers (what the CSV columns hold):
  ttft_s            time to first token = t_first_token - t_submit, thinking included. Where the provider hides its
                    reasoning (OpenAI reasoning models) the first chunk may only arrive once reasoning has ended, so
                    ttft_kind says what was observed: "first_token" (output of any kind was seen), "first_chunk" (only
                    the first chunk of a hidden-reasoning stream: it may equal TTFAT)
  ttfat_s           time to first answer token = t_first_answer - t_submit
  t_first_thinking_s  t_first_thinking - t_submit
  decode_tok_s      decode speed = tokens written in the streaming window / (t_last - start of the window). Basis
                    "all_output": every output token (thinking included) over t_last - t_first_token; basis
                    "visible_output": hidden reasoning (counted but never streamed) is left out, so the visible
                    tokens (output - thinking) over t_last - t_first_answer. decode_basis says which
  e2e_tok_s         end-to-end rate = output tokens / total seconds
  total_s           t_last - t_submit (retries included); equal to the call's latency_s
  retries, retry_s  HTTP attempts after the first, and the seconds lost to them (from the first attempt's start to the
                    last attempt's start: failed attempts plus the SDK's back-off), seen through httpx event hooks
  http_status       status of the last attempt; request_id, model_version, region as the provider returned them
  ratelimit_remaining_requests / _tokens  the rate-limit headers of the last attempt
"""

from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

CURRENT: contextvars.ContextVar["CallTimer | None"] = contextvars.ContextVar("aan_call_timer", default=None)

# header names, lower case; the first one present wins
REQUEST_ID_HEADERS = ("request-id", "x-request-id")
REGION_HEADERS = ("anthropic-region", "x-region", "openai-region", "cf-ray")
REMAINING_REQUESTS = ("anthropic-ratelimit-requests-remaining", "x-ratelimit-remaining-requests")
REMAINING_TOKENS = ("anthropic-ratelimit-tokens-remaining", "anthropic-ratelimit-output-tokens-remaining",
                    "x-ratelimit-remaining-tokens")


@dataclass
class CallTimer:
    """Stamps of one call; providers fill it in, `extra` turns it into the per-call fields of LLMResponse.extra."""

    streamed: bool = False
    t_submit: float = field(default_factory=time.perf_counter)
    t_submit_utc: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="milliseconds"))
    t_first_event: float | None = None
    t_first_token: float | None = None
    t_first_thinking: float | None = None
    t_first_answer: float | None = None
    t_last: float | None = None
    attempts: list[float] = field(default_factory=list)  # perf_counter at the start of each HTTP attempt
    statuses: list[int] = field(default_factory=list)
    headers: dict = field(default_factory=dict)  # of the last response, lower-case names
    hidden_reasoning: bool = False  # the provider counts reasoning tokens it never streams

    def event(self, now: float | None = None) -> float:
        now = time.perf_counter() if now is None else now
        if self.t_first_event is None:
            self.t_first_event = now
        self.t_last = now
        return now

    def token(self, now: float | None = None) -> None:
        now = self.event(now)
        if self.t_first_token is None:
            self.t_first_token = now

    def thinking(self, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        self.token(now)
        if self.t_first_thinking is None:
            self.t_first_thinking = now

    def answer(self, text: str, now: float | None = None) -> None:
        now = time.perf_counter() if now is None else now
        self.token(now)
        if text and self.t_first_answer is None:
            self.t_first_answer = now

    def finish(self) -> None:
        """The reply is complete: t_last is now when nothing was streamed, else the last event."""
        if not self.streamed or self.t_last is None:
            self.t_last = time.perf_counter()

    def extra(self, output_tokens: int, thinking_tokens: int = 0, model_version: str | None = None,
              end: float | None = None) -> dict:
        """The per-call fields (see the module docstring); None where a stamp was not observed. `end` is when the
        provider finished with the call (its latency_s ends there); default t_last."""
        self.finish()

        def since(t):
            return None if t is None else t - self.t_submit

        total = (self.t_last if end is None else end) - self.t_submit
        ttft_kind = None
        if self.streamed:
            ttft_kind = "first_chunk" if self.hidden_reasoning and self.t_first_thinking is None else "first_token"
        decode, basis = None, None
        if self.streamed and self.hidden_reasoning and self.t_first_thinking is None:
            window = None if self.t_first_answer is None else self.t_last - self.t_first_answer
            tokens, basis = max(output_tokens - thinking_tokens, 0), "visible_output"
        else:
            window = None if self.t_first_token is None else self.t_last - self.t_first_token
            tokens, basis = output_tokens, "all_output"
        if self.streamed and window and window > 0 and tokens > 0:
            decode = tokens / window
        else:
            basis = None
        retries = max(len(self.attempts) - 1, 0)
        return {
            "t_submit_utc": self.t_submit_utc,
            "streamed": self.streamed,
            "ttft_s": since(self.t_first_token) if self.streamed else None,
            "ttft_kind": ttft_kind,
            "ttfat_s": since(self.t_first_answer) if self.streamed else None,
            "t_first_thinking_s": since(self.t_first_thinking) if self.streamed else None,
            "decode_tok_s": decode,
            "decode_basis": basis,
            "e2e_tok_s": output_tokens / total if total > 0 else None,
            "total_s": total,
            "retries": retries,
            "retry_s": (self.attempts[-1] - self.attempts[0]) if retries else 0.0,
            "http_status": self.statuses[-1] if self.statuses else None,
            "request_id": first_header(self.headers, REQUEST_ID_HEADERS),
            "model_version": model_version,
            "region": first_header(self.headers, REGION_HEADERS),
            "ratelimit_remaining_requests": first_header(self.headers, REMAINING_REQUESTS),
            "ratelimit_remaining_tokens": first_header(self.headers, REMAINING_TOKENS),
        }


def first_header(headers: dict, names: tuple[str, ...]) -> str | None:
    for name in names:
        if name in headers:
            return headers[name]
    return None


def background_extra(timer: CallTimer, output_tokens: int, model_version: str | None = None,
                     end: float | None = None) -> dict:
    """D5 background calls: total latency only (each poll is a request of its own, so neither stream stamps nor
    retries mean anything there); every other timing field stays None."""
    timer.finish()
    total = (timer.t_last if end is None else end) - timer.t_submit
    return {"t_submit_utc": timer.t_submit_utc, "streamed": False, "ttft_s": None, "ttft_kind": None, "ttfat_s": None,
            "t_first_thinking_s": None, "decode_tok_s": None, "decode_basis": None,
            "e2e_tok_s": output_tokens / total if total > 0 else None, "total_s": total, "retries": None,
            "retry_s": None, "http_status": None, "request_id": None, "model_version": model_version, "region": None,
            "ratelimit_remaining_requests": None, "ratelimit_remaining_tokens": None, "background": True}


async def on_request(request) -> None:
    """httpx event hook: an HTTP attempt starts (the SDK's retries call it again)."""
    timer = CURRENT.get()
    if timer is not None:
        timer.attempts.append(time.perf_counter())


async def on_response(response) -> None:
    """httpx event hook: an attempt's status and headers arrived (before the body when streaming)."""
    timer = CURRENT.get()
    if timer is not None:
        timer.statuses.append(response.status_code)
        timer.headers = {k.lower(): v for k, v in response.headers.items()}


def install_hooks(http_client) -> None:
    """Add the two hooks to an httpx (or httpx2) client once. The hooks read the call's timer from a context variable,
    so concurrent calls on one client each see their own attempts."""
    hooks = http_client.event_hooks
    if on_request not in hooks["request"]:
        hooks["request"].append(on_request)
    if on_response not in hooks["response"]:
        hooks["response"].append(on_response)
