"""The whole sampling path (sampler -> executor -> call cache -> vllm_local -> fake vLLM server) reproduces the
synthetic world call for call, checkers included, and resumes from its shards."""

import asyncio

import pandas as pd
import pytest

from autoagentnet.cache import CallCache
from autoagentnet.providers.vllm_local import VLLMLocalClient
from autoagentnet.testbed import grid, sample
from autoagentnet.testbed.fake_server import FakeVLLM
from autoagentnet.testbed.tasks import world_tasks
from autoagentnet.testbed.table import validate
from autoagentnet.testbed.world import World

JUDGE = grid.Config(grid.QWEN, 9, "bf16", 4096)


@pytest.fixture(scope="module")
def setup():
    world = World(12, salt="pipeline")
    fake = FakeVLLM(world)
    client = VLLMLocalClient(base_url="http://fake", transport=fake.transport())
    configs = grid.pilot()
    registry = grid.registry_for(configs + [JUDGE], 6, "http://fake")
    for ref in registry.models:
        registry.set_client(ref, client)
    return world, fake, registry, configs, world_tasks(world)


def test_pipeline_matches_the_world_call_for_call(setup):
    world, _, registry, configs, tasks = setup
    got = pd.concat([asyncio.run(sample.sample_config(c, tasks, 6, registry)) for c in configs])
    want = world.table(configs, 6)
    m = got.merge(want, on=["item", "system", "call"], suffixes=("", "_w"))
    assert len(m) == len(want) == 12 * 4 * 6
    for col in ("answer", "correct", "signal_thinking_tokens", "signal_forced"):
        assert (m[col].astype(float) == m[f"{col}_w"].astype(float)).all(), col
    assert (m["seed"] == [grid.seed_of(sy, j) for sy, j in zip(m["system"], m["call"])]).all()
    assert validate(got.drop(columns=sample.SIDECAR)) is not None and validate(want) is not None
    assert (m["signal_logprob_mean"] - m["signal_logprob_mean_w"]).abs().max() < 1e-9
    assert (m["signal_margin"] - m["signal_margin_w"]).abs().max() < 1e-9
    assert got["cost_usd"].eq(0).all() and got["gpu_seconds"].gt(0).all()
    assert got["seed"].nunique() == 4 * 6  # one seed per (config, sample): no two configs share random numbers


def test_self_checks_and_judge_through_the_pipeline_match_the_world(setup):
    world, _, registry, configs, tasks = setup
    got = pd.concat([asyncio.run(sample.sample_config(c, tasks, 6, registry)) for c in configs])
    texts, table = got[["item", "system", "call", *sample.SIDECAR]], got.drop(columns=sample.SIDECAR)
    checks = pd.concat([asyncio.run(sample.self_checks(c, tasks, table, texts, registry)) for c in configs])
    picks = asyncio.run(sample.judge(JUDGE, [c.label for c in configs], tasks, table, texts, registry))
    w_checks, w_picks = world.checks(world.table(configs, 6), JUDGE)
    a = checks.merge(w_checks, on=["system", "item", "call"])
    b = picks.merge(w_picks[w_picks["candidates"] == 4], on=["system", "item", "judge", "candidates"])
    assert len(a) == 12 * 4 * 3 and (a["verdict_x"] == a["verdict_y"]).all()
    assert len(b) == 12 * 4 and (b["pick_x"] == b["pick_y"]).all()


def test_shards_resume_and_cached_calls_are_not_repeated(setup, tmp_path):
    world, fake, registry, configs, tasks = setup
    cache = CallCache(tmp_path / "cache")
    config = configs[0]
    before = fake.calls
    paths = asyncio.run(sample.run_shards(config, tasks, 6, registry, tmp_path / "out", cache, chunk=5))
    assert len(paths) == 3 and fake.calls - before == 12 * 6  # thinking off: one call per sample
    paths[1].unlink()  # a lost shard is redone from the call cache, with no new generation
    calls = fake.calls
    asyncio.run(sample.run_shards(config, tasks, 6, registry, tmp_path / "out", cache, chunk=5))
    assert fake.calls == calls
    table = sample.read_table(tmp_path / "out")
    assert len(table) == 12 * 6 and "text" not in table and len(sample.read_texts(tmp_path / "out")) == 12 * 6


def test_code_grading_can_be_deferred_off_the_gpu(tmp_path):
    from autoagentnet.tasks import Task

    task = Task(id="lcb-q", prompt="[item:bbeh-0000] double n", answer=None, meta={
        "benchmark": "code", "public_tests": [{"input": "2\n", "output": "4\n", "testtype": "stdin"}],
        "private_tests": [{"input": "3\n", "output": "6\n", "testtype": "stdin"}]})
    out = tmp_path / "out" / "x"
    out.mkdir(parents=True)
    frame = pd.DataFrame([{"benchmark": "code/lcb_v6", "item": "lcb-q", "system": "qwen3.5-4b:bf16:off", "family": "qwen3.5",
                           "model": "m", "size_b": 4.0, "precision": "bf16", "reasoning": "off", "scaffold": "direct",
                           "call": 0, "answer": None, "correct": None, "cost_usd": 0.0, "gpu_seconds": None,
                           "input_tokens": 10, "output_tokens": 20, "latency_s": 0.1, "signal_exec_visible": None,
                           "source": "testbed/pilot", "licence": "internal"}])
    validate(frame).to_parquet(out / "00000.parquet", index=False)
    pd.DataFrame([{"item": "lcb-q", "system": "qwen3.5-4b:bf16:off", "call": 0, "seed": 1, "stop_reason": "stop",
                   "text": "```python\nprint(int(input())*2)\n```\nANSWER: see code"}]).to_parquet(
        out / "00000.texts.parquet", index=False)
    assert sample.grade_shards(tmp_path / "out", [task]) == 1
    graded = sample.read_table(tmp_path / "out")
    assert graded["correct"].tolist() == [1.0] and graded["signal_exec_visible"].tolist() == [1.0]
    assert sample.grade_shards(tmp_path / "out", [task]) == 0  # nothing left to grade
    deferred = sample.grade(task, "```python\nprint(1)\n```", defer_code=True)
    assert deferred == {"answer": None, "correct": None, "signal_exec_visible": None}
