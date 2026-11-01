import asyncio

import pytest

from autoagentnet.cache import CallCache
from autoagentnet.network.spec import PruneConfig, upstream_indices
from autoagentnet.pricing import UnknownPrice
from autoagentnet.pruning.space import PruneSpace
from conftest import make_executor


def run(executor, task, prune=None):
    return asyncio.run(executor.run(task, prune))


def test_dense_and_pruned_call_counts(network, registry, fake, tasks):
    executor = make_executor(network, registry)
    dense = run(executor, tasks[0])
    pruned = run(executor, tasks[0], PruneConfig(keep=[2, 2, 2, 1]))
    assert len(dense.calls) == 19 and dense.config_id == "k6-6-6-1"
    assert len(pruned.calls) == 7
    assert "ANSWER:" in dense.final
    assert dense.peak_context_tokens > pruned.peak_context_tokens


def test_warm_first_turns_cache_writes_into_reads(network, registry, fake, tasks):
    warm = run(make_executor(network, registry), tasks[0])
    critique = warm.stages[1].outputs
    assert sum(o.usage.cache_write_tokens > 0 for o in critique) == 1
    assert sum(o.usage.cache_read_tokens > 0 for o in critique) == 5
    first, rest = critique[0], critique[1:]
    assert warm.stages[1].critical_path_s == pytest.approx(first.latency_s + max(o.latency_s for o in rest))

    registry.set_client("fake", type(fake)())  # fresh simulated cache
    cold = run(make_executor(network, registry, warm_cache_first=False), tasks[0])
    assert sum(o.usage.cache_write_tokens > 0 for o in cold.stages[1].outputs) == 6


def test_edge_pruning_limits_reads_and_drops_shared_prefix(network, registry, fake, tasks):
    prune = PruneConfig(keep=[6, 6, 6, 1], fan_in=[None, 2, 2, 2])
    result = run(make_executor(network, registry), tasks[0], prune)
    assert upstream_indices(5, 6, 2) == [0, 5]
    assert all(o.usage.cache_read_tokens == 0 for o in result.stages[1].outputs)


def test_landscape_enumeration_costs_474_calls_per_task(network, registry, fake, tasks):
    executor = make_executor(network, registry, cache=CallCache())
    configs = PruneSpace(network).configs()
    assert len(configs) == 216

    async def all_configs():
        return await asyncio.gather(*(executor.run(tasks[0], c) for c in configs))

    results = asyncio.run(all_configs())
    assert fake.calls == 474  # 6 + 36 + 216 + 216 unique calls, not 216 x up to 19
    assert sum(r.live_calls for r in results) == 474
    asyncio.run(all_configs())
    assert fake.calls == 474  # second pass is free


def test_unknown_price_stops_before_spending(network, registry, fake, tasks, pricebook):
    registry.models["unpriced"] = registry.config("gpt_small").model_copy(update={"model": "no-price-model"})
    unpriced = make_executor(network, registry, pricebook=pricebook, model_override="unpriced")
    with pytest.raises(UnknownPrice):
        run(unpriced, tasks[0])


def test_replicates_draw_new_samples_but_reuse_their_own_cache(network, registry, fake, tasks):
    executor = make_executor(network, registry, cache=CallCache())
    run(executor, tasks[0])
    asyncio.run(executor.run(tasks[0], replicate=1))
    assert fake.calls == 38  # replicate 1 re-asks all 19 calls
    asyncio.run(executor.run(tasks[0], replicate=1))
    assert fake.calls == 38  # and caches them under its own number
