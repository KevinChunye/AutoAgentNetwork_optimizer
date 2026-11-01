"""Runs a (pruned) network on one task, stage by stage.

Within a stage the agents run concurrently. When they share a prefix long
enough to cache, the first agent runs alone to write the prompt cache and the
others follow and read it (a cache entry is only readable once the first
response has started).

Every call goes through the call cache and single-flight de-duplication, so
identical calls made by different pruned configs are paid for once. Live calls
are priced, checked against the budget and written to the ledger.

Vote stages, early exits and escalations (see network/spec.py) are decided here
from the previous stage's answers, by fixed rules: the same inputs always take
the same path, so dynamic networks stay reproducible and cacheable.
"""

from __future__ import annotations

import asyncio
import time

from pydantic import BaseModel

from ..agents.agent import prompt_text, render_shared_context
from ..agents.spec import AgentInput, AgentOutput, AgentRequest, Upstream
from ..budget import SpendGovernor
from ..cache import CallCache, make_key
from ..meter import CallRecord
from ..pricing import PriceBook
from ..providers.base import FREE_PROVIDERS, TRUNCATED_STOP_REASONS, Usage, estimate_tokens
from ..providers.registry import ProviderRegistry
from ..consensus import plurality
from ..runtime.base import AgentRuntime
from ..tasks import Task, extract_answer
from .spec import NetworkSpec, PruneConfig, upstream_indices

NO_CALL = "none"  # provider of outputs made by rules (vote, early exit), not by a model call


class StageTrace(BaseModel):
    stage: str
    outputs: list[AgentOutput]
    critical_path_s: float  # seconds this stage takes if its agents run in parallel
    warmed: bool = False  # the first call ran alone to write the prompt cache, the others after it (session M1)


class NetworkResult(BaseModel):
    network: str
    config_id: str
    task_id: str
    keep: list[int]
    replicate: int = 0
    final: str  # output of the first kept agent in the last stage
    stages: list[StageTrace]
    wall_s: float  # measured wall-clock time of this run (near zero when cached)
    exit_stage: str | None = None  # stage before which the network stopped on consensus
    escalated: list[str] = []  # stages that ran on their escalation model

    @property
    def calls(self) -> list[AgentOutput]:
        """Model calls only; rule outputs (votes, early exits) cost nothing and are left out."""
        return [o for s in self.stages for o in s.outputs if o.provider != NO_CALL]

    @property
    def usage(self) -> Usage:
        total = Usage()
        for o in self.calls:
            total = total + o.usage
        return total

    @property
    def cost_usd(self) -> float:
        """What this config costs to run on its own, cached calls included at their original price."""
        return sum(o.cost_usd for o in self.calls)

    @property
    def flops(self) -> float | None:
        values = [o.flops for o in self.calls]
        return None if any(v is None for v in values) else sum(values)

    @property
    def critical_path_s(self) -> float:
        """End-to-end latency if each stage runs its agents in parallel."""
        return sum(s.critical_path_s for s in self.stages)

    @property
    def peak_context_tokens(self) -> int:
        """Largest prompt any single agent read (the memory analog)."""
        return max(o.usage.prompt_tokens for o in self.calls)

    @property
    def live_calls(self) -> int:
        return sum(not o.from_cache for o in self.calls)

    @property
    def truncated_calls(self) -> int:
        """Calls cut off by max_tokens; their answers may be missing or wrong."""
        return sum(o.stop_reason in TRUNCATED_STOP_REASONS for o in self.calls)


def rule_output(agent_id: str, answer: str | None) -> AgentOutput:
    """An answer produced by a rule (majority vote, consensus exit): no call, no cost."""
    content = f"ANSWER: {answer}" if answer is not None else "(no agent gave an answer)"
    return AgentOutput(agent_id=agent_id, content=content, usage=Usage(), provider=NO_CALL,
                       model=NO_CALL, latency_s=0.0, stop_reason="end_turn")


class NetworkExecutor:
    def __init__(
        self,
        network: NetworkSpec,
        runtime: AgentRuntime,
        registry: ProviderRegistry,
        *,
        pricebook: PriceBook | None = None,
        cache: CallCache | None = None,
        governor: SpendGovernor | None = None,
        model_override: str | None = None,
        max_concurrency: int = 8,
        warm_cache_first: bool = True,
        cache_min_tokens: int = 512,
        run_id: str = "run",
        worst_case_paths: bool = False,
    ):
        """model_override routes every agent to one model ref (e.g. "fake").
        governor (with its ledger) is required for any paid call: without one,
        only zero-cost models (the fake model) may run.
        worst_case_paths (for estimates): early exits never fire and escalations always do."""
        self.network = network
        self.runtime = runtime
        self.registry = registry
        self.pricebook = pricebook
        self.cache = cache
        self.governor = governor
        self.model_override = model_override
        self.warm_cache_first = warm_cache_first
        self.cache_min_tokens = cache_min_tokens
        self.run_id = run_id
        self.worst_case_paths = worst_case_paths
        self.max_concurrency = max_concurrency
        self._semaphores: dict[int, asyncio.Semaphore] = {}  # one per event loop
        self._inflight: dict[str, asyncio.Future] = {}
        self.running = 0  # live calls in flight right now; each call records the count at its submit (session M1)

    def _semaphore(self) -> asyncio.Semaphore:
        loop_id = id(asyncio.get_running_loop())
        if loop_id not in self._semaphores:
            self._semaphores[loop_id] = asyncio.Semaphore(self.max_concurrency)
        return self._semaphores[loop_id]

    async def run(self, task: Task, prune: PruneConfig | None = None, replicate: int = 0) -> NetworkResult:
        """replicate numbers independent samples: replicate 1 re-asks every call
        instead of reusing replicate 0's cached outputs."""
        prune = prune or PruneConfig.dense(self.network)
        prune.check(self.network)
        start = time.perf_counter()
        previous: list[AgentOutput] = []
        traces: list[StageTrace] = []
        exit_stage: str | None = None
        escalated: list[str] = []

        for s, stage in enumerate(self.network.stages):
            if stage.kind == "vote":
                answer, _ = plurality([extract_answer(o.content) for o in previous], task.grader)
                vote = rule_output(f"{stage.name}.vote", answer)
                traces.append(StageTrace(stage=stage.name, outputs=[vote], critical_path_s=0.0))
                previous = [vote]
                continue
            if prune.keep[s] == 0:  # skipped stage: the previous stage's outputs pass straight through
                continue
            share = 0.0 if self.worst_case_paths else 1.0
            if previous and not self.worst_case_paths and (stage.exit_if_agreement is not None or stage.escalate_to):
                answer, share = plurality([extract_answer(o.content) for o in previous], task.grader)
                if stage.exit_if_agreement is not None and answer is not None and share >= stage.exit_if_agreement:
                    stop = rule_output(f"{stage.name}.exit", answer)
                    traces.append(StageTrace(stage=f"{stage.name}:exit", outputs=[stop], critical_path_s=0.0))
                    previous, exit_stage = [stop], stage.name
                    break
            fan_in = prune.fan_in[s] if prune.fan_in else None
            shared = fan_in is None or fan_in >= len(previous)
            model = self.model_override or (prune.models[s] if prune.models else None)
            if stage.escalate_to and share < stage.escalate_below:
                escalated.append(stage.name)
                if not self._override_is_fake():  # a dry run stays on the fake model throughout
                    model = stage.escalate_to
            requests = []
            for i in range(prune.keep[s]):
                upstream = [
                    Upstream(agent_id=previous[j].agent_id, content=previous[j].content)
                    for j in upstream_indices(i, len(previous), fan_in)
                ]
                inp = AgentInput(task_id=task.id, task=task.prompt, upstream=upstream, shared_prefix=shared)
                requests.append(AgentRequest(spec=self.network.agent_spec(s, i, model=model), input=inp))
            outputs = await self._stage(stage.name, requests, shared, prune.config_id, replicate, traces)
            for r in range(2, (stage.rounds if stage.kind == "debate" else 1) + 1):  # debate rounds 2..R
                kept = range(len(outputs))
                reads = [list(kept) if stage.edges is None else [j for j in stage.edges[i] if j in kept] for i in kept]
                same = all(row == list(kept) for row in reads)
                requests = [AgentRequest(spec=self.network.agent_spec(s, i, model=model, round=r),
                                         input=AgentInput(task_id=task.id, task=task.prompt, shared_prefix=same,
                                                          upstream=[Upstream(agent_id=outputs[j].agent_id,
                                                                             content=outputs[j].content) for j in reads[i]]))
                            for i in kept]
                outputs = await self._stage(f"{stage.name}.r{r}", requests, same, prune.config_id, replicate, traces)
            previous = outputs

        return NetworkResult(
            network=self.network.name,
            config_id=prune.config_id,
            task_id=task.id,
            keep=prune.keep,
            replicate=replicate,
            final=previous[0].content,
            stages=traces,
            wall_s=time.perf_counter() - start,
            exit_stage=exit_stage,
            escalated=escalated,
        )

    async def _stage(self, name: str, requests: list[AgentRequest], shared: bool, config_id: str, replicate: int,
                     traces: list[StageTrace]) -> list[AgentOutput]:
        """Run one stage's (or debate round's) calls concurrently, warming the prompt cache first when the
        agents share a long prefix; append its trace and return its outputs."""
        if self._should_warm(requests, shared):
            first = await self._call(requests[0], config_id, replicate)
            rest = list(await asyncio.gather(*(self._call(r, config_id, replicate) for r in requests[1:])))
            outputs = [first, *rest]
            critical_path = first.latency_s + max(o.latency_s for o in rest)
            traces.append(StageTrace(stage=name, outputs=outputs, critical_path_s=critical_path, warmed=True))
            return outputs
        else:
            outputs = list(await asyncio.gather(*(self._call(r, config_id, replicate) for r in requests)))
            critical_path = max(o.latency_s for o in outputs)
        traces.append(StageTrace(stage=name, outputs=outputs, critical_path_s=critical_path))
        return outputs

    def _override_is_fake(self) -> bool:
        return bool(self.model_override) and self.registry.provider_of(self.model_override) == "fake"

    def _should_warm(self, requests: list[AgentRequest], shared: bool) -> bool:
        if not (self.warm_cache_first and shared and len(requests) > 1):
            return False
        first = requests[0]
        prefix = first.spec.system + render_shared_context(first.input)
        return estimate_tokens(prefix) >= self.cache_min_tokens

    async def _call(self, request: AgentRequest, config_id: str, replicate: int = 0) -> AgentOutput:
        ref = request.spec.model
        model_id = self.registry.model_id(ref)
        key = make_key(request.spec.model_dump(), model_id, self.registry.options_of(ref),
                       request.input.model_dump(), replicate)

        if self.cache is not None:
            hit = self.cache.get(key)
            if hit is not None:
                return AgentOutput.model_validate_json(hit).model_copy(update={"from_cache": True})
        if key in self._inflight:  # the same call is already running for another config
            output = await self._inflight[key]
            return output.model_copy(update={"from_cache": True})

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._inflight[key] = future
        reservation = None
        try:
            provider = self.registry.provider_of(ref)
            account = self.registry.account_of(ref)
            worst_case = 0.0
            prompt_tokens = estimate_tokens(prompt_text(request.spec, request.input))
            if self.pricebook is not None:  # fails before spending if the model is unpriced
                worst_case = self.pricebook.worst_case_usd(model_id, provider, prompt_tokens, request.spec.max_tokens)
            elif provider not in FREE_PROVIDERS:
                raise RuntimeError("paid models need a price book and a spend governor")
            if worst_case > 0 and self.governor is None:
                raise RuntimeError(f"paid call to {model_id} without a spend governor")
            if self.governor is not None:
                reservation = self.governor.reserve(account, worst_case)
            async with self._semaphore():
                self.running += 1
                concurrency = self.running
                try:
                    output = await self.runtime.call(request)
                finally:
                    self.running -= 1
            output.extra = {**output.extra, "concurrency": concurrency}
            if self.pricebook is not None:
                output.cost_usd = self.pricebook.cost_usd(model_id, output.provider, output.usage)
                output.flops = self.pricebook.flops(model_id, output.provider, output.usage)
            if self.cache is not None:
                self.cache.put(key, output.model_dump_json())
            if self.governor is not None:
                self.governor.settle(
                    reservation,
                    CallRecord(
                        run_id=self.run_id,
                        network=self.network.name,
                        config_id=config_id,
                        task_id=request.input.task_id,
                        stage=request.spec.stage,
                        agent_id=request.spec.agent_id,
                        account=account,
                        provider=output.provider,
                        model=model_id,
                        cost_usd=output.cost_usd,
                        latency_s=output.latency_s,
                        stop_reason=output.stop_reason,
                        estimated_prompt_tokens=prompt_tokens,
                        **output.usage.model_dump(),
                    ),
                )
                reservation = None
            future.set_result(output)
            return output
        except BaseException as exc:
            if reservation is not None:
                self.governor.release(reservation)
            future.set_exception(exc)
            future.exception()  # mark retrieved so asyncio does not warn when nobody waits
            raise
        finally:
            del self._inflight[key]
