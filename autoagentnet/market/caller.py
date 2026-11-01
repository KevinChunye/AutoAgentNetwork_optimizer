"""The governed path for trader calls: call cache, then the spend governor, then the runtime.

It follows NetworkExecutor._call step by step (every model call goes through the
registry and the SpendGovernor), without a network spec:
  1. key = the trader's AgentRequest (spec, model ID, API options, input) plus the replicate, which
     is the session seed; a hit is free and marked from_cache;
  2. worst case = every prompt token at the dearest input rate plus the full max_tokens of output;
     the governor reserves it and refuses if any cap could break;
  3. the runtime (local or Maritime) makes the call; the price book prices it; the cache stores it;
     the governor records it in the ledger and releases the reservation.
Turns in a session are sequential (each one changes the book), so there is no single-flight
de-duplication here.
"""

from __future__ import annotations

from ..agents.agent import prompt_text
from ..agents.spec import AgentOutput, AgentRequest
from ..budget import SpendGovernor
from ..cache import CallCache, make_key
from ..meter import CallRecord
from ..pricing import PriceBook
from ..providers.base import estimate_tokens
from ..providers.registry import ProviderRegistry
from ..runtime.base import AgentRuntime


def cache_key(registry: ProviderRegistry, request: AgentRequest, replicate: int) -> str:
    """The call cache's key of a request (step 1 above): its spec, the model ID and API options of the ref it calls,
    its input and the replicate number."""
    ref = request.spec.model
    return make_key(request.spec.model_dump(), registry.model_id(ref), registry.options_of(ref),
                    request.input.model_dump(), replicate)


class MarketCaller:
    def __init__(self, runtime: AgentRuntime, registry: ProviderRegistry, *, pricebook: PriceBook | None,
                 cache: CallCache | None, governor: SpendGovernor | None, run_id: str, market: str,
                 condition: str, purpose: str = "market"):
        """market names the run in the ledger's `network` column; condition fills `config_id`; purpose
        fills the ledger's `purpose` column ("desk" for the conviction desk, which reuses this path)."""
        self.runtime = runtime
        self.registry = registry
        self.pricebook = pricebook
        self.cache = cache
        self.governor = governor
        self.run_id = run_id
        self.market = market
        self.condition = condition
        self.purpose = purpose
        self.live_calls = 0
        self.running = 0  # live calls in flight right now; each call records the count at its submit (session M1)

    async def call(self, request: AgentRequest, replicate: int) -> AgentOutput:
        ref = request.spec.model
        model_id = self.registry.model_id(ref)
        key = cache_key(self.registry, request, replicate)
        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return AgentOutput.model_validate_json(hit).model_copy(update={"from_cache": True})

        provider = self.registry.provider_of(ref)
        account = self.registry.account_of(ref)
        prompt_tokens = estimate_tokens(prompt_text(request.spec, request.input))
        worst_case = 0.0
        if self.pricebook is not None:  # fails before spending if the model is unpriced
            worst_case = self.pricebook.worst_case_usd(model_id, provider, prompt_tokens, request.spec.max_tokens)
        elif provider != "fake":
            raise RuntimeError("paid models need a price book and a spend governor")
        if worst_case > 0 and self.governor is None:
            raise RuntimeError(f"paid call to {model_id} without a spend governor")
        reservation = self.governor.reserve(account, worst_case) if self.governor is not None else None
        try:
            self.running += 1
            concurrency = self.running
            try:
                output = await self.runtime.call(request)
            finally:
                self.running -= 1
            output.extra = {**output.extra, "concurrency": concurrency}
            self.live_calls += 1
            if self.pricebook is not None:
                output.cost_usd = self.pricebook.cost_usd(model_id, output.provider, output.usage)
            if self.cache is not None:
                self.cache.put(key, output.model_dump_json())
            if self.governor is not None:
                self.governor.settle(reservation, CallRecord(
                    run_id=self.run_id, purpose=self.purpose, network=self.market, config_id=self.condition,
                    task_id=request.input.task_id, stage=request.spec.stage, agent_id=request.spec.agent_id,
                    account=account, provider=output.provider, model=model_id, cost_usd=output.cost_usd,
                    latency_s=output.latency_s, stop_reason=output.stop_reason,
                    estimated_prompt_tokens=prompt_tokens, **output.usage.model_dump()))
                reservation = None
            return output
        finally:
            if reservation is not None:
                self.governor.release(reservation)
