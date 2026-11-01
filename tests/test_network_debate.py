"""The debate block (autoagentnet/network/): rounds, shared prefix, edge pruning; on the fake model, offline."""

import asyncio

import pytest
import yaml

from autoagentnet.network.spec import NetworkSpec
from conftest import ROOT, make_executor


def debate(edges=None, rounds=3) -> NetworkSpec:
    spec = yaml.safe_load((ROOT / "configs/networks/debate6x3.yaml").read_text())
    spec["stages"][0]["rounds"] = rounds
    spec["stages"][0]["edges"] = edges
    return NetworkSpec(**spec)


def test_dense_debate_runs_every_round_and_votes_on_the_last(registry, fake, tasks):
    result = asyncio.run(make_executor(debate(), registry).run(tasks[0]))
    assert [s.stage for s in result.stages] == ["debate", "debate.r2", "debate.r3", "vote"]
    assert len(result.calls) == 18 and fake.calls == 18
    r2 = result.stages[1].outputs
    assert all(o.agent_id.startswith("debate.r2.") for o in r2)
    assert "ANSWER:" in result.final
    assert len(debate().all_agents()) == 18


def test_dense_rounds_share_the_prefix_and_read_every_answer(registry, fake, tasks):
    executor = make_executor(debate(), registry)
    seen = []
    original = executor._call

    async def spy(request, config_id, replicate=0):
        seen.append(request)
        return await original(request, config_id, replicate)

    executor._call = spy
    asyncio.run(executor.run(tasks[0]))
    later = [r for r in seen if r.spec.stage == "debate.r2"]
    assert len(later) == 6 and all(r.input.shared_prefix for r in later)
    assert all([u.agent_id for u in r.input.upstream] == [f"debate.{i}" for i in range(6)] for r in later)
    assert all("Above are the team's answers" in r.spec.instruction for r in later)
    first = [r for r in seen if r.spec.stage == "debate"]
    assert all(not r.input.upstream for r in first)  # round 1 reads only the task


def test_pruned_edges_limit_what_each_agent_reads(registry, fake, tasks):
    edges = [[0, 1], [1, 2], [2, 3], [3, 4], [4, 5], [5, 0]]
    executor = make_executor(debate(edges), registry)
    seen = []
    original = executor._call

    async def spy(request, config_id, replicate=0):
        seen.append(request)
        return await original(request, config_id, replicate)

    executor._call = spy
    asyncio.run(executor.run(tasks[0]))
    r3 = [r for r in seen if r.spec.stage == "debate.r3"]
    assert [len(r.input.upstream) for r in r3] == [2] * 6
    assert r3[5].input.upstream[0].agent_id == "debate.r2.5" and r3[5].input.upstream[1].agent_id == "debate.r2.0"
    assert not any(r.input.shared_prefix for r in r3)


def test_a_pruned_debate_pays_only_for_its_later_rounds(registry, fake, tasks):
    """Round 1 of a dense and of an edge-pruned debate are the same calls, so with the call cache the pruned
    network costs only its 12 later-round calls."""
    from autoagentnet.cache import CallCache

    cache = CallCache()
    asyncio.run(make_executor(debate(), registry, cache=cache).run(tasks[0]))
    before = fake.calls
    pruned = asyncio.run(make_executor(debate([[i, (i + 1) % 6] for i in range(6)]), registry, cache=cache).run(tasks[0]))
    assert fake.calls - before == 12
    assert sum(o.from_cache for o in pruned.stages[0].outputs) == 6


def test_debate_spec_is_validated():
    with pytest.raises(ValueError, match="rounds >= 2"):
        debate(rounds=1)
    with pytest.raises(ValueError, match="edges"):
        debate(edges=[[0]] * 5)
