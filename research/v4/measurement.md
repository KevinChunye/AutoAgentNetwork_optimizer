# Measurement layer (session M1, 2026-10-27)

What is now recorded for every call, stage, run and GPU shard, with every quantity defined in plain words first. Code
holds the same definitions in its docstrings:
- `autoagentnet/providers/timing.py`
- `autoagentnet/latency.py`
- `autoagentnet/providers/vllm_local.py`
- `autoagentnet/testbed/kv.py`
- `autoagentnet/testbed/sidecar.py`

Analyses are in `research/v4/measurement/`.

## 1. Definitions

**Context**
- **Context tokens of a call.** Everything the model reads: input + cache-write + cache-read tokens.
- **Peak context.** The largest context of a call. Per stage, the largest in the stage; per network run, the largest
  in the run.

**Time stamps.** Each call has one UTC wall-clock stamp (`t_submit_utc`). Every interval comes from
`time.perf_counter`.

**Time to first token (TTFT, `ttft_s`).** Seconds from sending the request to the first streamed event that carries
model output of any kind, thinking included.
- Anthropic:
  - TTFT is the first content block or delta.
  - Claude 5.5 models stream thinking with display "omitted": the thinking block opens with empty text. So the
    first thinking stamp (`t_first_thinking_s`) is when that block opened.
- OpenAI reasoning models: the reasoning is hidden and never streamed.
  - The first chunk may arrive only after reasoning ends.
  - `ttft_kind` says what was observed: "first_token" (output of some kind was seen) or "first_chunk" (only the
    first chunk of a hidden-reasoning stream; it may equal TTFAT).

**Time to first answer token (TTFAT, `ttfat_s`).** Seconds to the first non-empty piece of visible answer text.

**Decode speed (`decode_tok_s`).** Output tokens divided by the streaming window.
- Basis "all_output": every output token, thinking included, over the time from the first token to the last.
- Basis "visible_output": used where reasoning is hidden. The visible tokens (output - reasoning) over the time from
  the first answer token to the last.
- `decode_basis` says which.

**End-to-end rate (`e2e_tok_s`).** Output tokens / total seconds.

**Total latency (`total_s`).** Request sent to last byte, retries included. It equals the call's existing `seconds`
(panel) or `latency_s` (network).

**Retries.**
- `retries` is the number of HTTP attempts after the first, seen through httpx event hooks on the SDK's client
  (429s, 5xx and connection errors that the SDK retried).
- `retry_s` is the seconds from the first attempt's start to the last attempt's start: failed attempts plus back-off.

**Per call also:**
- `http_status`, `request_id`, `region` (when a header carries it);
- rate-limit remaining (`ratelimit_remaining_requests`, `ratelimit_remaining_tokens`);
- `model_version` (as the API reported it);
- `concurrency`: the executor's or panel caller's calls in flight when this one was sent, itself included;
- `streamed`.

**`timing_source`.**
- "measured": a live call timed in this run.
- "estimated": inferred later from totals (the backfill).
- Missing: a cache hit. A cache hit keeps `from_cache` true and carries no timing of this run, only its context
  tokens.

**Background-mode OpenAI calls** (D5, ceilings above 8,192 tokens) record total latency only. Each poll is a request
of its own, so the stream stamps and retries stay missing.

**Local GPU only (`vllm_local`, two phases when thinking is on).**
- **Prefill seconds (`prefill_s`).** Per phase, from sending the request to its first token, summed over phases
  (queueing included).
- **Decode seconds (`decode_s`).** Per phase, from its first token to its last, summed over phases.
- **Time per output token (`tpot_s`).** decode_s / (output tokens - phases).
- **Server timing.** `vllm_queue_s`, `vllm_prefill_s` and `vllm_decode_s` are the server's own per-request timing
  (`--enable-per-request-metrics`), summed over phases.
- **KV-cache usage.** The share of the engine's KV cache in use (`vllm:kv_cache_usage_perc`, from the GPU trace).
- **KV bytes per token per model** (config.json) = layers that hold a per-token cache × 2 × KV heads × head dimension
  × bytes per element.
  - In hybrid models (Qwen3.5: 3 Gated DeltaNet layers to 1 full-attention layer) only the full-attention layers hold
    a per-token cache.
  - Qwen3.5-2B: 12,288 bytes per token; 4B and 9B: 32,768. Plus a fixed recurrent state per sequence of about 10 MB
    (2B) or 26 MB (4B, 9B). Sources: `research/lit/vllm_metrics_qwen35_kv.md`.
- **Estimated KV memory of a call** = (prompt + output tokens) × bytes per token.
  - Per configuration with prefix caching: the shared prefix once + the sum over calls of (unshared prompt + output),
    × bytes per token.
  - Without prefix caching: the sum of every call's prompt + output (addendum 2, 8.1).
- **Peak GPU memory, utilization, power.** From `nvidia-smi` every 1 s.
- **Energy.** Joules = the integral of power over the shard's window.
  - Per-call energy is the shard's energy shared out by each call's decode-token units (output + 0.1 × input).
  - **That is an apportionment, not a measurement.**

**Percentiles.** Every latency summary reports p50 and p95, never a mean alone.

## 2. What is recorded, where

| level | file | columns or fields | code |
|---|---|---|---|
| call (panel) | `results/<run>/calls.csv` | appended: ttft_s, ttfat_s, t_first_thinking_s, decode_tok_s, e2e_tok_s, total_s, retries, retry_s, concurrency, streamed, context_tokens, timing_source, ttft_kind, decode_basis, http_status, request_id, region, ratelimit_remaining_requests, ratelimit_remaining_tokens, t_submit_utc | `latency.call_columns` |
| call (network) | `results/<run>/agents.csv` | the same appended columns | `metrics.agent_rows` |
| stage | `results/<run>/stages.csv` (new) | per run and model-call stage: calls, live_calls, peak_context_tokens, stage_latency_s (slowest live call), stage_critical_path_s, stage_ttfat_s, usd, output_tokens | `latency.stage_rows` |
| run (network) | `results/<run>/results.csv` | appended: critical_path_ttfat_s; imbalance_context, imbalance_latency, imbalance_usd (max / mean over stages) | `latency.run_columns` |
| run | `results/<run>/run_card.json` (new) | UTC date, host, container, network path (agent proxy or direct; the proxy address is not stored), Python and SDK versions, concurrency limit, model ids and versions seen, timing on or off, runtime | `latency.run_card` |
| GPU shard | `results/testbed/<stage>/<config>/<offset>.parquet` | schema v2 optional columns: ttft_s, ttfat_s, t_first_thinking_s, prefill_s, decode_s, tpot_s, decode_tok_s, e2e_tok_s, streamed, vllm_queue_s, vllm_prefill_s, vllm_decode_s, context_tokens, timing_source, kv_bytes_est, energy_j | `testbed/sample.py` |
| GPU trace | `<offset>.gpu_trace.parquet` next to each shard | vLLM every 2 s (kv_cache_usage, running, waiting, token counters, TTFT / inter-token / prefill / decode / queue histogram sums and counts); nvidia-smi every 1 s (power_w, memory_mib, util_pct per GPU) | `testbed/sidecar.py` |
| GPU server | `results/testbed/<stage>/serve_card-<checkpoint>.json` | vLLM version, cache configuration (block size, GPU blocks, prefix caching), chunked prefill (not reported by the server) | `testbed/__main__.serve_card` |
| pilot report | `research/v4/testbed/throughput.json` → `timing_by_config` | TTFT p50/p95, TPOT p50/p95, KV-cache usage p95, peak memory, joules per 1,000 output tokens per configuration | `sidecar.config_timing` |

Schema (`autoagentnet/atlas/schema.py`) is now version 2.
- The timing, context and GPU columns are optional and nullable.
- They are cast when present and never added, so a version-1 table validates and round-trips unchanged (test).

**Switch.** `timing: true` in an experiment or panel config streams every Anthropic and OpenAI request. Every new
config M1 writes sets it. The field's default stays `false` (audit M1-1): on the stream path a reply cut mid-stream
raises StreamCut, which the SDK does not retry and the ledger does not record. So old configs keep their transport
until the timing probe has run with no stream failure.
- It is transport only, as audit 86 established. The payload gains only `stream` (and, on OpenAI,
  `stream_options.include_usage`).
- Cache keys, prompts, templates (TEMPLATE_HASH, CODE_HASH), graders and usage accounting are unchanged (tests
  compare the streamed payload with the JSON one).
- `timing: false` (the default) keeps one JSON reply per request below the stream thresholds.
- `vllm_local` streams by default.
- A Maritime agent's own client decides its timing (the wire format already carries `AgentOutput.extra`).

Existing columns keep their names and meaning; the new ones come after them.

## 3. Results so far ($0)

- **Backfill** (`measurement/backfill.md`, `tables/latency_by_arm.csv`, `tables/calls_backfill.csv.gz`).
  - Scope: 35,456 calls in 123 runs, 26,500 of them live. Per-call context and end-to-end rate, timing_source
    "estimated".
  - Decode speed estimated by median regression of total seconds on output tokens. The ranges below span the arms'
    point estimates; each arm's 95% bootstrap interval is in backfill.md:
    - Haiku 214-240 tokens/s;
    - Sonnet 122-140;
    - Opus 102-112;
    - Luna 92-116;
    - Sol 33-34 (flagged for confirmation by streaming).
    - The OpenAI rates count hidden reasoning as output: these runs did not record reasoning tokens.
  - Overheads (TTFT plus network and queue) 0.4-2.2 s.
  - p95 totals:
    - 7.3 s for Haiku off;
    - 558 s for Haiku max;
    - 929 s for Sonnet max.
  - This reproduces the first pass.
- **Stage profile of the staged runs.** Dense 6-6-6-1, Haiku off. Imbalance per run, as max / mean over stages:
  - context 1.55-1.74, the largest at critique (21 of 22 runs);
  - latency 1.46-1.72, at propose (21 of 22);
  - dollars 1.28-1.44, at propose (21 of 22).
  - This reproduces the first pass (about 1.67, 1.58, 1.38).
- **Latency card** (`measurement/latency_card.md`). Per arm, estimated TTFT, TTFAT, decode speed, p50/p95 total,
  thinking tokens, context and dollars per call. The measured columns fill in once timed runs exist.
- **Configuration map** (`measurement/config_map.md`). The anchor's tier-1 arms, 440 BBEH and 93 math items, exact
  replay. Dollar budget × latency budget, with three latency measures: p95 total, TTFAT p95 (estimated) and mean
  total.
  - A single call's p95 is over every call of the arm. A vote answers at its slowest call.
  - **Held-out regret** (choose on one half, score on the other; 100 random halvings; picks over a budget on the
    scoring half are left out and counted apart; biased up, since the scoring half's best is in-sample):
    - BBEH: 0.9-1.6 points on average over cells, by latency measure, with cell means up to 8 points;
    - math: 1.6-1.7 points, with cell means up to 13 points (93 items);
    - single splits reach about 22 points in the worst cell;
    - picks over a budget on the scoring half: 7-11% (BBEH), 2-3% (math).
  - **Median bootstrap stability of the winner** (non-empty cells): 74-86%.
  - **On BBEH:**
    - no configuration meets a p95 of 5 s (Haiku off's per-call p95 is about 5.7 s);
    - at 8 s, Haiku-off calls or votes win;
    - from $0.0025 and a 30-s p95 (or an 8-s mean), one Sol low call wins;
    - cascades win no p95 or mean cell, and 2 TTFAT cells.
  - **On math**, cascades win the dearest cells: Haiku-off 3-vote escalating to Sonnet off (accuracy 0.23) or Sol low
    (0.33 at 300 s).
  - **TTFAT**:
    - OpenAI reasoning arms' TTFAT is their total seconds (hidden and unrecorded reasoning), so they never win a
      short-TTFAT cell;
    - under a TTFAT budget of 2-15 s, Haiku low (cheap) or Sonnet low (dearer) wins on BBEH.
  - **Against the first pass's prototype (mean latency):**
    - Confirmed: from 8 s and $0.0025 one Sol low call wins, and cascades never win on BBEH.
    - Under 5 s, single Haiku calls win here, not Haiku-off votes.
- **Stage balance** (`measurement/stage_balance.md`). The pilot's 27-configuration grid replayed from the cache.
  - No imbalance ratio predicts accuracy at matched tokens. Every 95% interval includes 0.
  - The grid varies widths only, so balance and tokens move together. Testing balance at fixed tokens needs new
    calls (patching).
- **Patching** (`measurement/patching.md`, addendum 2): theory, $0 numbers from the pilot's real messages, agent loops
  and batching. The experiment is designed in `measurement/patching_prereg_draft.md` and has not been run.

## 4. Caveats

- **Absolute API latency.**
  - It includes the agent-proxy path of the cloud sessions.
  - It varies with time of day, provider load and the run's concurrency (usually 8).
  - The backfill's numbers describe these sessions' conditions, not a clean single request.
- **Cache hits carry no timing.** A run that replays the cache measures nothing about the provider.
- **Estimated vs measured.**
  - TTFT, TTFAT and decode speed in the backfill and the map are estimates from totals.
  - Hidden reasoning (OpenAI) makes the TTFT of a streamed reasoning call a first-chunk time; `ttft_kind` says so.
  - The earlier OpenAI runs recorded no reasoning tokens. So the map takes those reasoning arms' TTFAT as their total
    seconds (an upper bound), and the latency card leaves their thinking and TTFAT blank (audit M1-1).
- **Energy per call** is an apportionment of a whole-GPU measurement, idle draw included.
