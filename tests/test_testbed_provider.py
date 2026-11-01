"""The vllm_local provider and budget forcing, against the fake vLLM server (no GPU, no network)."""

import asyncio
import re

import httpx
import numpy as np
import pytest

from autoagentnet.budget import BudgetRules, SpendGovernor
from autoagentnet.meter import Ledger
from autoagentnet.pricing import PriceBook
from autoagentnet.providers.base import Block, LLMRequest
from autoagentnet.providers.registry import ModelConfig, ProviderRegistry
from autoagentnet.providers.vllm_local import VLLMLocalClient, logprob_signals
from autoagentnet.testbed import budget_forcing as bf
from autoagentnet.testbed.fake_server import FakeVLLM
from autoagentnet.testbed.world import World

from conftest import ROOT


def test_answer_prompt_appends_the_end_marker_once_and_keeps_the_cut_thinking():
    assert bf.answer_prompt("P<|assistant|>", "<think>\nabc def") == "P<|assistant|><think>\nabc def\n</think>\n\n"
    # Qwen3.5's template already opens the thinking block in the prompt
    assert bf.answer_prompt("P<think>\n", "abc") == "P<think>\nabc\n</think>\n\n"
    assert bf.split_reply("<think>x y</think> ANSWER: 3") == ("x y", "ANSWER: 3")
    assert bf.split_reply("ANSWER: 3") == ("", "ANSWER: 3")


def test_logprob_signals_read_mean_entropy_and_answer_margin():
    text = "so\nANSWER: 7"
    lp = {"tokens": ["so\n", "ANSWER:", " 7"], "token_logprobs": [-0.1, -0.2, -0.3], "text_offset": [0, 3, 10],
          "top_logprobs": [{"a": -0.1, "b": -3.0}, {"a": -0.2, "b": -2.0}, {"a": -0.3, "b": -0.9}]}
    s = logprob_signals(lp, text)
    assert s["signal_logprob_mean"] == pytest.approx(-0.2)
    assert s["signal_margin"] == pytest.approx(0.6)  # only the token after "ANSWER:" counts
    assert 0 < s["signal_entropy"] < np.log(2)
    assert logprob_signals(None, text)["signal_margin"] is None


def request(budget, item="bbeh-0003", model="qwen3.5-4b-bf16", seed=11):
    return LLMRequest(model=model, system="sys", blocks=[Block(text=f"TASK:\n[item:{item}] q"), Block(text="go")],
                      max_tokens=256, temperature=1.0,
                      options={"thinking_budget": budget, "seed": seed, "top_p": 0.95, "logprobs": 5})


def test_budget_forcing_cuts_thinking_at_the_budget_and_still_answers():
    world = World(20)
    fake = FakeVLLM(world)
    client = VLLMLocalClient(base_url="http://fake", transport=fake.transport())
    idx = world.index["bbeh-0003"]
    need = float(world.need_draw(idx, 11))
    small = asyncio.run(client.complete(request(budget=int(need // 2))))
    large = asyncio.run(client.complete(request(budget=int(need * 3))))
    off = asyncio.run(client.complete(request(budget=0)))
    assert small.extra["forced"] and small.extra["thinking_tokens"] == int(need // 2)
    assert not large.extra["forced"] and large.extra["thinking_tokens"] == round(need)
    assert off.extra["thinking_tokens"] == 0 and not off.extra["forced"]
    for r in (small, large, off):
        assert re.search(r"ANSWER: \d", r.text) and r.provider == "vllm_local"
        assert r.usage.output_tokens == r.extra["thinking_tokens"] + r.extra["answer_tokens"]
    assert fake.calls == 2 + 2 + 1  # two phases with a budget, one without


def test_vllm_local_is_free_and_stays_out_of_the_spend_ledger():
    from autoagentnet.meter import CallRecord

    book = PriceBook({})
    assert book.worst_case_usd("qwen3.5-4b-bf16", "vllm_local", 10_000, 10_000) == 0.0
    ledger = Ledger()
    governor = SpendGovernor(ledger, BudgetRules(hard_caps_usd={"anthropic": 100}))
    reservation = governor.reserve("gpu", 0.0)  # an account with no hard cap: free calls still pass
    governor.settle(reservation, CallRecord(run_id="r", account="gpu", provider="vllm_local", model="m",
                                            input_tokens=10, cache_write_tokens=0, cache_read_tokens=0,
                                            output_tokens=10, cost_usd=0.0, latency_s=0.1))
    assert ledger.records == []


def test_registry_builds_a_vllm_local_client_billed_to_the_gpu_account():
    reg = ProviderRegistry({"q": ModelConfig(provider="vllm_local", model="qwen3.5-4b-bf16", base_url="http://x:1")})
    assert reg.account_of("q") == "gpu"
    assert isinstance(reg.client("q"), VLLMLocalClient)


def test_inference_engines_are_imported_only_in_providers():
    pattern = re.compile(r"^\s*(import|from)\s+(vllm|sglang|llama_cpp|tensorrt_llm|exllamav2)\b", re.MULTILINE)
    offenders = [str(p.relative_to(ROOT)) for folder in ("autoagentnet", "scripts", "analysis")
                 for p in (ROOT / folder).rglob("*.py") if "providers" not in p.parts and pattern.search(p.read_text())]
    assert offenders == []


def test_http_errors_from_the_server_surface():
    client = VLLMLocalClient(base_url="http://fake", transport=httpx.MockTransport(lambda r: httpx.Response(500)))
    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(client.complete(request(0)))
