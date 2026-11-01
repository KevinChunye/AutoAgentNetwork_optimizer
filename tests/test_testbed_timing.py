"""Session M1, open-weight side: vllm_local's streamed timing, the GPU trace sidecar, KV-cache estimates and the
pilot report's timing table, offline against the fake vLLM server."""

import asyncio

import httpx
import pandas as pd
import pytest

from autoagentnet.providers.base import Block, LLMRequest
from autoagentnet.providers.vllm_local import VLLMLocalClient
from autoagentnet.testbed import grid, kv, sample, sidecar
from autoagentnet.testbed.fake_server import FakeVLLM
from autoagentnet.testbed.table import validate
from autoagentnet.testbed.tasks import world_tasks
from autoagentnet.testbed.world import World

QWEN35_4B = {"architectures": ["Qwen3_5ForConditionalGeneration"], "text_config": {
    "num_hidden_layers": 32, "full_attention_interval": 4,
    "layer_types": (["linear_attention"] * 3 + ["full_attention"]) * 8, "num_attention_heads": 16,
    "num_key_value_heads": 4, "head_dim": 256, "hidden_size": 2560, "dtype": "bfloat16", "linear_key_head_dim": 128,
    "linear_value_head_dim": 128, "linear_num_key_heads": 16, "linear_num_value_heads": 32, "linear_conv_kernel_dim": 4}}
QWEN35_2B = {"text_config": {**QWEN35_4B["text_config"], "num_hidden_layers": 24,
                             "layer_types": (["linear_attention"] * 3 + ["full_attention"]) * 6, "num_attention_heads": 8,
                             "num_key_value_heads": 2, "hidden_size": 2048, "linear_num_value_heads": 16}}


def request(world, budget):
    item = world.items["item"].iloc[0]
    return LLMRequest(model="qwen3.5-4b-bf16", system="s", blocks=[Block(text=f"[item:{item}] solve")], max_tokens=64,
                      temperature=1.0, options={"thinking_budget": budget, "seed": 3, "answer_max_tokens": 64})


def test_vllm_streams_and_times_each_phase_without_changing_the_reply():
    world = World(4, salt="timing")
    fake = FakeVLLM(world, token_delay_s=0.002)
    streamed = VLLMLocalClient(base_url="http://fake", transport=fake.transport())
    plain = VLLMLocalClient(base_url="http://fake", transport=fake.transport(), timing=False)
    a = asyncio.run(streamed.complete(request(world, 256)))
    b = asyncio.run(plain.complete(request(world, 256)))
    assert a.text == b.text and a.usage == b.usage and a.stop_reason == b.stop_reason
    for key in ("signal_logprob_mean", "signal_entropy", "signal_margin", "thinking_tokens", "forced"):
        assert a.extra[key] == pytest.approx(b.extra[key]) if a.extra[key] is not None else b.extra[key] is None
    x = a.extra
    assert x["streamed"] is True and b.extra["streamed"] is False and b.extra["ttft_s"] is None
    assert 0 < x["ttft_s"] == x["t_first_thinking_s"] < x["ttfat_s"] < x["total_s"]
    assert x["prefill_s"] > 0 and x["decode_s"] > 0 and x["tpot_s"] > 0 and x["decode_tok_s"] > 0
    assert x["vllm_queue_s"] == 0.0 and x["vllm_prefill_s"] > 0 and x["vllm_decode_s"] > 0  # two phases summed
    off = asyncio.run(streamed.complete(request(world, 0))).extra
    assert off["t_first_thinking_s"] is None and off["ttft_s"] == off["ttfat_s"]


def test_kv_bytes_per_token_counts_only_full_attention_layers():
    assert kv.cached_layers(QWEN35_4B) == 8 and kv.kv_bytes_per_token(QWEN35_4B) == 32_768
    assert kv.kv_bytes_per_token(QWEN35_2B) == 12_288
    assert kv.kv_bytes_per_token(QWEN35_4B, kv_dtype="fp8") == 16_384
    plain = {"num_hidden_layers": 4, "num_attention_heads": 8, "hidden_size": 512, "torch_dtype": "float16"}
    assert kv.cached_layers(plain) == 4 and kv.kv_bytes_per_token(plain) == 4 * 2 * 8 * 64 * 2 and kv.state_bytes(plain) == 0
    assert 25e6 < kv.state_bytes(QWEN35_4B) < 28e6 and 9e6 < kv.state_bytes(QWEN35_2B) < 11e6


def test_configuration_kv_stores_a_shared_prefix_once_with_prefix_caching():
    prompts, outputs = [1000] * 6, [200] * 6
    shared = kv.configuration_kv_bytes(prompts, outputs, 900, 10)
    assert shared == (900 + 6 * (100 + 200)) * 10
    assert kv.configuration_kv_bytes(prompts, outputs, 900, 10, prefix_caching=False) == 6 * 1200 * 10
    assert kv.call_kv_bytes(1000, 200, 10) == 12_000


def test_prometheus_parse_reads_vllm_0_32_names():
    world = World(2, salt="metrics")
    fake = FakeVLLM(world)
    asyncio.run(VLLMLocalClient(base_url="http://fake", transport=fake.transport()).complete(request(world, 0)))
    values = sidecar.parse_prometheus(fake.prometheus())
    row = sidecar.vllm_row(values)
    assert row["kv_cache_usage"] == 0 and row["running"] == 0 and row["generation_tokens"] > 0
    assert row["ttft_count"] == 1 and row["ttft_sum"] > 0 and row["itl_count"] > 0
    assert sidecar.parse_smi("0, 312.5, 40000, 97\n1, [N/A], 100, 0\n") == [
        {"gpu": 0, "power_w": 312.5, "memory_mib": 40000.0, "util_pct": 97.0},
        {"gpu": 1, "power_w": None, "memory_mib": 100.0, "util_pct": 0.0}]


def test_energy_is_the_integral_of_power_and_calls_get_shares():
    trace = pd.DataFrame({"t": [0.0, 1.0, 2.0, 0.0, 2.0], "source": "gpu", "gpu": [0, 0, 0, 1, 1],
                          "power_w": [100.0, 100.0, 100.0, 50.0, 50.0]})
    assert sidecar.energy_joules(trace) == pytest.approx(300.0)
    shares = sidecar.apportion_energy(pd.Series([1.0, 3.0]), 300.0)
    assert list(shares) == [75.0, 225.0]
    assert sidecar.energy_joules(trace.iloc[[0]]) is None


def test_shards_carry_timing_kv_and_energy_and_the_trace_is_kept_apart(tmp_path):
    world = World(6, salt="trace")
    fake = FakeVLLM(world, token_delay_s=0.001)
    client = VLLMLocalClient(base_url="http://fake", transport=fake.transport())
    config = grid.pilot()[1]  # thinking on
    registry = grid.registry_for([config], 2, "http://fake")
    for ref in registry.models:
        registry.set_client(ref, client)
    power = iter(range(1000))

    def smi():
        return f"0, {200 + next(power) % 7}, 30000, 90\n"

    def trace():
        return sidecar.Sidecar("http://fake/metrics", smi=smi, metrics_every_s=0.01, smi_every_s=0.01,
                               transport=fake.transport())

    paths = asyncio.run(sample.run_shards(config, world_tasks(world), 2, registry, tmp_path / "out", chunk=6,
                                          trace=trace, kv_per_token=32_768))
    table = sample.read_table(tmp_path / "out")
    assert len(paths) == 1 and len(table) == 12  # the trace file is not read as a shard
    validate(table)
    assert (table["timing_source"] == "measured").all() and table["ttft_s"].notna().all()
    assert (table["kv_bytes_est"] == (table["input_tokens"] + table["output_tokens"]) * 32_768).all()
    traces = sample.read_traces(tmp_path / "out")
    assert set(traces["source"]) == {"vllm", "gpu"} and (traces["system"] == config.label).all()
    energy = sidecar.energy_joules(traces)
    assert energy > 0 and table["energy_j"].astype(float).sum() == pytest.approx(energy)
    report = sidecar.config_timing(table, traces)
    row = report.iloc[0]
    assert row["timed_calls"] == 12 and row["ttft_p95_s"] >= row["ttft_p50_s"] > 0 and row["tpot_p50_s"] > 0
    assert row["joules_per_1k_output_tokens"] > 0 and row["peak_memory_mib"] == 30000 and row["kv_cache_usage_p95"] >= 0


def test_cached_calls_carry_no_timing(tmp_path):
    from autoagentnet.cache import CallCache

    world = World(3, salt="cached")
    fake = FakeVLLM(world)
    client = VLLMLocalClient(base_url="http://fake", transport=fake.transport())
    config = grid.pilot()[0]
    registry = grid.registry_for([config], 2, "http://fake")
    for ref in registry.models:
        registry.set_client(ref, client)
    cache = CallCache(tmp_path / "cache")
    asyncio.run(sample.sample_config(config, world_tasks(world), 2, registry, cache))
    again = asyncio.run(sample.sample_config(config, world_tasks(world), 2, registry, cache))
    assert again["timing_source"].isna().all() and again["ttft_s"].isna().all() and again["energy_j"].isna().all()
    assert again["context_tokens"].gt(0).all()


def test_serve_card_reads_version_and_cache_config():
    from autoagentnet.testbed.__main__ import serve_card

    def handler(request):
        if request.url.path == "/version":
            return httpx.Response(200, json={"version": "0.32.0"})
        return httpx.Response(200, text='vllm:cache_config_info{block_size="16",enable_prefix_caching="True",'
                                         'num_gpu_blocks="9000"} 1.0\n')

    card = serve_card("http://fake", transport=httpx.MockTransport(handler))
    assert card["vllm_version"] == "0.32.0"
    assert card["cache_config"] == {"block_size": "16", "enable_prefix_caching": "True", "num_gpu_blocks": "9000"}
