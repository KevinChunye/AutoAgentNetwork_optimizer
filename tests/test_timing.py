"""Session M1: per-call timing (providers/timing.py), the appended columns (latency.py), stages.csv, run_card.json
and the schema's version-2 columns, offline with fake transports and the fake model."""

import asyncio
import json

import httpx
import pandas as pd
import pytest

from autoagentnet.latency import TIMING_COLUMNS, call_columns, imbalance, run_columns, stage_rows
from autoagentnet.network.spec import PruneConfig
from autoagentnet.providers.anthropic_provider import AnthropicClient
from autoagentnet.providers.base import Block, LLMRequest
from autoagentnet.providers.openai_compat import OpenAICompatClient
from autoagentnet.providers.timing import CallTimer, background_extra
from conftest import ROOT, make_executor
from test_providers import anthropic_uses_httpx2

REQUEST = LLMRequest(model="claude-haiku-5-5", system="You are a solver.",
                     blocks=[Block(text="TASK: 2+2", cache=True), Block(text="Be brief.")], max_tokens=50)


def http_module():
    return pytest.importorskip("httpx2") if anthropic_uses_httpx2() else httpx


def sse(events, gap_s=0.01):
    """An async SSE body that waits gap_s between events, so the stamps are spread out."""
    async def body():
        for name, data in events:
            await asyncio.sleep(gap_s)
            head = f"event: {name}\n" if name else ""
            yield (head + f"data: {data if isinstance(data, str) else json.dumps(data)}\n\n").encode()
    return body()


ANTHROPIC_EVENTS = [
    ("message_start", {"type": "message_start", "message": {
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-haiku-5-5", "content": [],
        "stop_reason": None, "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 1, "cache_creation_input_tokens": 700, "cache_read_input_tokens": 0}}}),
    ("content_block_start", {"type": "content_block_start", "index": 0,
                             "content_block": {"type": "thinking", "thinking": "", "signature": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {"type": "signature_delta", "signature": "s"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 0}),
    ("content_block_start", {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "4\n"}}),
    ("content_block_delta", {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "ANSWER: 4"}}),
    ("content_block_stop", {"type": "content_block_stop", "index": 1}),
    ("message_delta", {"type": "message_delta", "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                       "usage": {"output_tokens": 40}}),
    ("message_stop", {"type": "message_stop"}),
]


def test_anthropic_timing_streams_and_stamps_every_event_without_changing_the_payload():
    http = http_module()
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return http.Response(200, headers={"content-type": "text/event-stream", "request-id": "req_1",
                                           "anthropic-ratelimit-requests-remaining": "99"},
                             content=sse(ANTHROPIC_EVENTS))

    client = AnthropicClient(api_key="test", http_client=http.AsyncClient(transport=http.MockTransport(handler)),
                             timing=True)
    response = asyncio.run(client.complete(REQUEST))
    body = dict(captured["body"])
    assert body.pop("stream") is True and body == AnthropicClient.build_payload(REQUEST)  # transport only
    assert response.text == "4\nANSWER: 4" and response.usage.output_tokens == 40
    x = response.extra
    assert x["streamed"] is True and x["ttft_kind"] == "first_token"
    assert x["ttft_s"] == pytest.approx(x["t_first_thinking_s"])
    assert 0 < x["ttft_s"] < x["ttfat_s"] < x["total_s"]
    assert x["total_s"] == pytest.approx(response.latency_s)
    assert x["decode_basis"] == "all_output" and x["decode_tok_s"] > 0
    assert x["e2e_tok_s"] == pytest.approx(40 / response.latency_s)
    assert x["retries"] == 0 and x["http_status"] == 200 and x["request_id"] == "req_1"
    assert x["ratelimit_remaining_requests"] == "99" and x["model_version"] == "claude-haiku-5-5"


def test_anthropic_without_timing_sends_one_json_request_and_records_totals():
    http = http_module()
    reply = {"id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
             "content": [{"type": "text", "text": "ANSWER: 4"}], "stop_reason": "end_turn", "stop_sequence": None,
             "usage": {"input_tokens": 10, "output_tokens": 5}}
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return http.Response(200, json=reply)

    client = AnthropicClient(api_key="test", http_client=http.AsyncClient(transport=http.MockTransport(handler)))
    x = asyncio.run(client.complete(REQUEST)).extra
    assert "stream" not in captured["body"]
    assert x["streamed"] is False and x["ttft_s"] is None and x["ttfat_s"] is None and x["decode_tok_s"] is None
    assert x["e2e_tok_s"] > 0 and x["retries"] == 0


def test_retries_and_the_seconds_lost_to_them_are_counted():
    http = http_module()
    reply = {"id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
             "content": [{"type": "text", "text": "ANSWER: 4"}], "stop_reason": "end_turn", "stop_sequence": None,
             "usage": {"input_tokens": 10, "output_tokens": 5}}
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return http.Response(529, headers={"retry-after-ms": "20"}, json={"type": "error", "error": {"type": "overloaded_error", "message": "busy"}})
        return http.Response(200, json=reply)

    client = AnthropicClient(api_key="test", http_client=http.AsyncClient(transport=http.MockTransport(handler)))
    x = asyncio.run(client.complete(REQUEST)).extra
    assert len(attempts) == 2 and x["retries"] == 1 and x["retry_s"] > 0 and x["http_status"] == 200


def openai_chunks(reasoning_tokens=0, reasoning_text=False):
    base = {"id": "c", "object": "chat.completion.chunk", "created": 0, "model": "gpt-6-luna"}
    chunks = [{**base, "choices": [{"index": 0, "delta": {"role": "assistant", "content": ""}, "finish_reason": None}]}]
    if reasoning_text:
        chunks.append({**base, "choices": [{"index": 0, "delta": {"reasoning_content": "hmm"}, "finish_reason": None}]})
    chunks += [{**base, "choices": [{"index": 0, "delta": {"content": "ANSWER"}, "finish_reason": None}]},
               {**base, "choices": [{"index": 0, "delta": {"content": ": 4"}, "finish_reason": "stop"}]},
               {**base, "choices": [], "usage": {"prompt_tokens": 20, "completion_tokens": 30, "total_tokens": 50,
                                                 "completion_tokens_details": {"reasoning_tokens": reasoning_tokens}}}]
    return [(None, c) for c in chunks] + [(None, "[DONE]")]


def openai_client(chunks, captured, timing=True):
    http = http_module()

    def handler(request):
        captured["body"] = json.loads(request.content)
        return http.Response(200, headers={"content-type": "text/event-stream", "x-request-id": "req_o"},
                             content=sse(chunks))

    return OpenAICompatClient(api_key="test", base_url="https://example.test/v1", timing=timing,
                              http_client=http.AsyncClient(transport=http.MockTransport(handler)))


def test_openai_hidden_reasoning_reports_the_first_chunk_and_a_visible_decode_speed():
    captured = {}
    client = openai_client(openai_chunks(reasoning_tokens=20), captured)
    response = asyncio.run(client.complete(REQUEST.model_copy(update={"model": "gpt-6-luna"})))
    body = dict(captured["body"])
    assert body.pop("stream") is True and body.pop("stream_options") == {"include_usage": True}
    assert body == client.build_payload(REQUEST.model_copy(update={"model": "gpt-6-luna"}))
    x = response.extra
    assert response.text == "ANSWER: 4" and response.usage.thinking_tokens == 20
    assert x["ttft_kind"] == "first_chunk" and x["t_first_thinking_s"] is None
    assert x["ttft_s"] < x["ttfat_s"] and x["decode_basis"] == "visible_output" and x["decode_tok_s"] > 0
    assert x["request_id"] == "req_o"


def test_openai_streamed_reasoning_text_is_a_thinking_token():
    client = openai_client(openai_chunks(reasoning_tokens=5, reasoning_text=True), {})
    x = asyncio.run(client.complete(REQUEST)).extra
    assert x["ttft_kind"] == "first_token" and x["t_first_thinking_s"] is not None
    assert x["decode_basis"] == "all_output"


def test_background_calls_record_total_latency_only():
    timer = CallTimer()
    x = background_extra(timer, 100, "gpt-6-sol")
    assert x["total_s"] >= 0 and x["e2e_tok_s"] is not None and x["background"] is True
    assert all(x[k] is None for k in ("ttft_s", "ttfat_s", "t_first_thinking_s", "decode_tok_s", "retries"))


def test_cache_hits_carry_context_but_no_timing(network, registry, fake, tasks):
    from autoagentnet.cache import CallCache

    fake.timing = True
    executor = make_executor(network, registry, cache=CallCache())
    first = asyncio.run(executor.run(tasks[0]))
    live = call_columns(first.calls[0])
    assert live["timing_source"] == "measured" and live["streamed"] is True and live["concurrency"] >= 1
    assert live["context_tokens"] == first.calls[0].usage.prompt_tokens and live["total_s"] == first.calls[0].latency_s
    pruned = asyncio.run(executor.run(tasks[0], PruneConfig(keep=[1, 1, 1, 1])))  # every call a cache hit
    hit = call_columns(pruned.calls[0])
    assert pruned.calls[0].from_cache and hit["context_tokens"] > 0
    assert all(hit[c] is None for c in TIMING_COLUMNS if c != "context_tokens")


def test_concurrency_at_submit_is_the_number_in_flight(network, registry, fake, tasks):
    executor = make_executor(network, registry, warm_cache_first=False, max_concurrency=4)
    result = asyncio.run(executor.run(tasks[0]))
    seen = [o.extra["concurrency"] for o in result.stages[0].outputs]
    assert max(seen) <= 4 and seen[0] == 1


def test_stage_rows_and_run_columns(network, registry, fake, tasks):
    fake.timing = True
    result = asyncio.run(make_executor(network, registry).run(tasks[0]))
    rows = stage_rows(result)
    assert [r["stage"] for r in rows] == ["propose", "critique", "refine", "aggregate"]
    assert [r["calls"] for r in rows] == [6, 6, 6, 1] and all(r["live_calls"] == r["calls"] for r in rows)
    critique = rows[1]
    assert critique["peak_context_tokens"] == max(o.usage.prompt_tokens for o in result.stages[1].outputs)
    assert critique["stage_latency_s"] == max(o.latency_s for o in result.stages[1].outputs)
    first = result.stages[1].outputs[0]
    assert critique["stage_ttfat_s"] == pytest.approx(first.extra["ttfat_s"])  # warm-first: the first call answers first
    run = run_columns(result)
    earlier = sum(s.critical_path_s for s in result.stages[:-1])
    assert run["critical_path_ttfat_s"] == pytest.approx(earlier + rows[-1]["stage_ttfat_s"])
    assert run["imbalance_context"] == pytest.approx(imbalance([r["peak_context_tokens"] for r in rows])) and run["imbalance_context"] > 1
    assert imbalance([2.0, 2.0]) == 1.0 and imbalance([]) != imbalance([])  # NaN


def test_experiment_writes_stages_csv_run_card_and_appended_columns(tmp_path, monkeypatch):
    from autoagentnet.experiment import ExperimentConfig, run_experiment

    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml").model_copy(
        update={"out_dir": str(tmp_path), "task_limit": 2, "timing": True})
    rows, _, status = asyncio.run(run_experiment(cfg))
    out = tmp_path / "smoke"
    agents = pd.read_csv(out / "agents.csv")
    old = ["config_id", "task_id", "replicate", "stage", "agent_id", "answer", "grader", "correct", "input_tokens",
           "cache_write_tokens", "cache_read_tokens", "output_tokens", "thinking_tokens", "visible_output_tokens",
           "recall_cue", "cost_usd", "stop_reason", "latency_s", "from_cache"]
    assert list(agents.columns) == old + TIMING_COLUMNS  # existing columns first, unchanged; new ones appended
    live = agents[~agents["from_cache"]]
    assert (live["timing_source"] == "measured").all() and live["ttfat_s"].notna().all()
    assert agents.loc[agents["from_cache"], "timing_source"].isna().all()
    stages = pd.read_csv(out / "stages.csv")
    assert {"stage", "calls", "peak_context_tokens", "stage_latency_s", "stage_ttfat_s", "usd", "output_tokens"} <= set(stages.columns)
    assert {"critical_path_ttfat_s", "imbalance_context", "imbalance_latency", "imbalance_usd"} <= set(rows.columns)
    card = json.loads((out / "run_card.json").read_text())
    assert card["timing"] is True and card["max_concurrency"] == cfg.max_concurrency
    assert card["network_path"] in ("agent proxy", "direct") and "anthropic" in card["packages"]
    assert card["date_utc"].endswith("+00:00")


def test_panel_appends_columns_and_writes_a_run_card(tmp_path):
    from test_evidence_panel import config, write_items
    from autoagentnet.evidence.panel import run_panel

    write_items(tmp_path)
    assert config(tmp_path).timing is False  # audit M1-1: off unless a config turns it on
    rows, _ = asyncio.run(run_panel(config(tmp_path, timing=True)))
    on_disk = pd.read_csv(tmp_path / "out/t/calls.csv")
    assert list(on_disk.columns)[-len(TIMING_COLUMNS):] == TIMING_COLUMNS
    assert list(on_disk.columns).index("reply") == len(on_disk.columns) - len(TIMING_COLUMNS) - 1
    assert (on_disk["total_s"] == on_disk["seconds"]).all() and (on_disk["timing_source"] == "measured").all()
    assert on_disk["streamed"].all() and on_disk["ttfat_s"].notna().all()  # the dry run's fake model takes timing
    assert (on_disk["context_tokens"] == on_disk[["input_tokens", "cache_write_tokens", "cache_read_tokens"]].sum(axis=1)).all()
    assert json.loads((tmp_path / "out/t/run_card.json").read_text())["timing"] is True


def test_schema_v2_columns_are_optional_and_v1_tables_are_unchanged(tmp_path):
    from autoagentnet.atlas import schema

    v1 = pd.DataFrame([{"benchmark": "bbeh/x", "item": "i", "system": "s", "family": "anthropic", "model": "m",
                        "precision": "api", "reasoning": "off", "scaffold": "direct", "call": 0, "answer": "a",
                        "correct": 1.0, "source": "t", "licence": "internal"}])
    path = schema.write(v1, tmp_path / "v1.parquet")
    back = pd.read_parquet(path)
    assert not set(schema.OPTIONAL) & set(back.columns) and schema.problems(back) == []
    v2 = v1.assign(ttft_s=0.4, ttfat_s=1.2, context_tokens=900, streamed=True, timing_source="measured", energy_j=3.0)
    assert schema.problems(v2) == []
    assert "ttft_s" in pd.read_parquet(schema.write(v2, tmp_path / "v2.parquet")).columns
    assert any("timing_source" in p for p in schema.problems(v2.assign(timing_source="guessed")))
    assert any("ttft_s" in p for p in schema.problems(v2.assign(ttft_s=-1.0)))
    assert schema.SCHEMA_VERSION == 2
