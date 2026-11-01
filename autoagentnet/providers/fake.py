"""Deterministic offline provider: no key, no network, no cost.

Use it for tests, smoke runs and dry runs of new experiments before spending
credit. Behaviour:

- The reply depends only on the request, so repeated runs are identical.
- Agents with upstream outputs mostly repeat the majority upstream answer and
  sometimes deviate, so pruned networks disagree with the dense one now and
  then, which keeps reconstruction-error numbers non-trivial.
- Prompt caching is simulated the way Anthropic does it: a shared prefix of at
  least ``min_cache_tokens`` is a cache write on first use and a cache read
  afterwards, and the cache entry only becomes readable once the writing call
  has finished.
- Latency is simulated from the output length; nothing actually sleeps.
- With `timing` on (session M1), the reply carries simulated stream stamps in `extra` (first token after
  base_latency_s, then one token every seconds_per_output_token), so every timing column is exercised offline.
"""

from __future__ import annotations

import asyncio
import hashlib
import re
from collections import Counter

from .base import LLMRequest, LLMResponse, Usage, estimate_tokens

ANSWER_LINE = re.compile(r"ANSWER:\s*(\S+)")


class FakeClient:
    provider = "fake"

    def __init__(
        self,
        n_choices: int = 3,
        deviate_percent: int = 20,
        output_fraction: float = 0.4,
        min_cache_tokens: int = 512,
        base_latency_s: float = 0.3,
        seconds_per_output_token: float = 0.005,
    ):
        self.n_choices = n_choices
        self.deviate_percent = deviate_percent
        self.output_fraction = output_fraction
        self.min_cache_tokens = min_cache_tokens
        self.base_latency_s = base_latency_s
        self.seconds_per_output_token = seconds_per_output_token
        self._ready_prefixes: set[str] = set()
        self.calls = 0
        self.timing = False

    def _answer(self, request: LLMRequest, digest: str) -> str:
        upstream_answers = ANSWER_LINE.findall(request.blocks[0].text) if request.blocks else []
        roll = int(digest[:8], 16)
        if upstream_answers and roll % 100 >= self.deviate_percent:
            return Counter(upstream_answers).most_common(1)[0][0]
        return str(roll % self.n_choices)

    def _cached_prefix(self, request: LLMRequest) -> str | None:
        parts = [request.system] if request.cache_system else []
        last_cached = max((i for i, b in enumerate(request.blocks) if b.cache), default=-1)
        parts += [b.text for b in request.blocks[: last_cached + 1]]
        if last_cached < 0 and not request.cache_system:
            return None
        prefix = "".join(parts)
        return prefix if estimate_tokens(prefix) >= self.min_cache_tokens else None

    async def list_models(self) -> list[str]:
        return ["fake-model"]

    async def complete(self, request: LLMRequest) -> LLMResponse:
        self.calls += 1
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        answer = self._answer(request, digest)
        target_tokens = max(16, int(request.max_tokens * self.output_fraction))
        body = ("lorem " * target_tokens)[: target_tokens * 4]
        text = f"[fake:{request.model}:{digest[:12]}] {body}\nANSWER: {answer}"

        prompt_tokens = estimate_tokens(request.system + "".join(b.text for b in request.blocks))
        prefix = self._cached_prefix(request)
        cache_write = cache_read = 0
        prefix_key = None
        if prefix is not None:
            prefix_key = hashlib.sha256((request.model + prefix).encode()).hexdigest()
            if prefix_key in self._ready_prefixes:
                cache_read = estimate_tokens(prefix)
            else:
                cache_write = estimate_tokens(prefix)
        await asyncio.sleep(0)  # let concurrent calls start before this one "finishes"
        if prefix_key is not None:
            self._ready_prefixes.add(prefix_key)

        output_tokens = estimate_tokens(text)
        usage = Usage(
            input_tokens=prompt_tokens - cache_write - cache_read,
            cache_write_tokens=cache_write,
            cache_read_tokens=cache_read,
            output_tokens=output_tokens,
        )
        latency_s = self.base_latency_s + self.seconds_per_output_token * output_tokens
        return LLMResponse(
            text=text,
            usage=usage,
            model=request.model,
            provider=self.provider,
            latency_s=latency_s,
            stop_reason="end_turn",
            extra=self.stamps(output_tokens, latency_s) if self.timing else {},
        )

    def stamps(self, output_tokens: int, latency_s: float) -> dict:
        """Simulated stream stamps, in the providers' timing fields (providers/timing.py)."""
        return {"t_submit_utc": "2026-01-01T00:00:00.000+00:00", "streamed": True, "ttft_s": self.base_latency_s,
                "ttft_kind": "first_token", "ttfat_s": self.base_latency_s, "t_first_thinking_s": None,
                "decode_tok_s": 1 / self.seconds_per_output_token, "decode_basis": "all_output",
                "e2e_tok_s": output_tokens / latency_s, "total_s": latency_s, "retries": 0, "retry_s": 0.0,
                "http_status": 200, "request_id": "fake", "model_version": None, "region": None,
                "ratelimit_remaining_requests": None, "ratelimit_remaining_tokens": None}
