"""Provider-neutral request and response types.

Every LLM backend implements one async method, ``complete(request) -> response``.
Nothing outside ``autoagentnet/providers`` imports a vendor SDK, so changing the
provider is a config change, not a code change.
"""

from __future__ import annotations

import math
from typing import Protocol, runtime_checkable

from pydantic import BaseModel


CHARS_PER_TOKEN = 3.0  # conservative: Claude Haiku 5.5's tokenizer gives ~30% more tokens than 4 chars/token


def estimate_tokens(text: str, chars_per_token: float = CHARS_PER_TOKEN) -> int:
    """Rough token count for planning and for the governor's worst case. Errs high on
    purpose (3 characters per token); billing always uses the counts the provider returns.
    The ledger keeps this estimate next to the real count so P0 can check the ratio."""
    return math.ceil(len(text) / chars_per_token)


class Block(BaseModel):
    """One piece of the user message.

    text:  the content.
    cache: True marks the end of a prefix that many calls share (for example the
           task plus every upstream output that all agents in a stage read).
           Providers with explicit prompt caching put a cache breakpoint here;
           providers with automatic prefix caching ignore the flag.
    """

    text: str
    cache: bool = False


class LLMRequest(BaseModel):
    model: str  # vendor model ID, e.g. "claude-haiku-5-5"
    system: str = ""
    blocks: list[Block]
    max_tokens: int = 800  # caps all generated tokens, hidden reasoning included
    temperature: float | None = 0.0  # None = let the provider use its default
    cache_system: bool = True  # cache the system prompt (shared by a whole stage)
    options: dict = {}  # extra API fields from the model config, e.g. {"thinking": {"type": "disabled"}}


class Usage(BaseModel):
    """Token counts for one call, normalized across providers.

    input_tokens:       prompt tokens billed at the full input rate
    cache_write_tokens: prompt tokens written into the prompt cache (premium rate on Anthropic)
    cache_read_tokens:  prompt tokens served from the prompt cache (discounted rate)
    output_tokens:      generated tokens, including any hidden reasoning tokens
    thinking_tokens:    the part of output_tokens the model spent thinking (reasoning), as the API reports it
                        (Anthropic usage.output_tokens_details.thinking_tokens; OpenAI reasoning_tokens); 0 when
                        the API reports none. Billed inside output_tokens, never on top (session E6, study CD)
    """

    input_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    output_tokens: int = 0
    thinking_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        return self.input_tokens + self.cache_write_tokens + self.cache_read_tokens

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.output_tokens

    def __add__(self, other: "Usage") -> "Usage":
        return Usage(
            input_tokens=self.input_tokens + other.input_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            thinking_tokens=self.thinking_tokens + other.thinking_tokens,
        )


class LLMResponse(BaseModel):
    text: str
    usage: Usage
    model: str
    provider: str
    latency_s: float  # wall-clock seconds for the API call
    stop_reason: str | None = None  # "max_tokens" / "length" means the output was cut off
    extra: dict = {}  # provider-specific measurements, e.g. vllm_local's thinking tokens and log-prob signals


TRUNCATED_STOP_REASONS = {"max_tokens", "length"}

# Providers whose calls cost no money: the offline fake model, and open-weight models served on a GPU the
# project rents by the hour (vLLM). GPU time is metered separately (research/v4/testbed/gpu_ledger.csv), so these
# calls need no entry in the price table and never enter the spend ledger.
FREE_PROVIDERS = {"fake", "vllm_local"}


@runtime_checkable
class LLMClient(Protocol):
    provider: str

    async def complete(self, request: LLMRequest) -> LLMResponse: ...
