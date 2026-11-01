# Session M1 hand-back: the measurement layer

Branch `metrics` (from `depth_review`, with E6's latest commits merged). PR KevinChunye/AutoAgentNetwork#18.
Audit M1-1: ADJUST. All five required items are fixed at $0 (research/audit_log.md).

**Spend: $0.** No paid call was made. The optional timing probe is prepared but has not run, because E6's paid
work had not ended (section 4).

Definitions are in `research/v4/measurement.md`.

## 1. What is now recorded

**Per call** (appended to `calls.csv` and `agents.csv`; existing columns unchanged):
- time to first token (TTFT) and time to first answer token (TTFAT);
- the first thinking event;
- decode speed, with its basis;
- end-to-end rate and total seconds;
- retries and the seconds lost to them;
- HTTP status, request id, rate-limit remaining, model version and region;
- concurrency at submit;
- streamed (true or false), context tokens and timing_source.

How it works:
- `timing: true` in a config streams every Anthropic and OpenAI request. This is transport only: only the stream
  fields join the payload, and cache keys, prompts, hashes, graders and usage are unchanged.
- **Deviation from the brief.** The brief asked for timing to be the default for new configs. Every config M1
  writes sets `timing: true`, but the field's default is `false` (audit M1-1). On the stream path, a reply cut
  mid-stream (StreamCut) is neither retried nor ledgered, so old configs keep their transport until the probe shows
  no stream failure.
- OpenAI background-mode calls record total latency only.
- Cache hits carry no timing.

**Per stage** (new `stages.csv` for network runs):
- calls, peak context, slowest live call, TTFAT from the stage's start, dollars and output tokens.

**Per run:**
- results.csv gains the critical-path TTFAT and imbalance ratios (max / mean over stages) for context, latency and
  dollars;
- a new `run_card.json` records date, network path (agent proxy), SDK versions, concurrency limit, models and versions,
  and timing on or off.

**Schema.** Version 2 adds the optional timing, context and GPU columns. Version-1 tables are unchanged and still
validate (test).

**On the GPU** (open-weight testbed; nothing run yet). `vllm_local` streams and times each phase:
- TTFT, TTFAT, prefill, decode and TPOT;
- the server's own queue, prefill and decode times (`serve-cmd` now passes `--enable-per-request-metrics`).

Each shard also gets:
- a GPU trace, from a sidecar that polls vLLM's `/metrics` every 2 s (KV-cache usage, running and waiting requests,
  latency histograms) and `nvidia-smi` every 1 s (power, memory, utilization);
- per-call energy, apportioned by decode-token units (an apportionment, not a measurement);
- KV bytes per call from config.json: Qwen3.5 2B 12,288 B per token, 4B and 9B 32,768, full-attention layers only;
- KV per configuration with prefix caching: the shared prefix once;
- `serve_card-<checkpoint>.json`, with vLLM's version and prefix caching on or off.

The pilot report adds TTFT p50/p95, TPOT, KV-cache usage p95, peak memory and joules per 1,000 output tokens per
configuration. `RUN_GPU.md` has the steps. The metric names were verified for vLLM 0.32.0
(`research/lit/vllm_metrics_qwen35_kv.md`).

**Tests** (all offline): `tests/test_timing.py`, `tests/test_testbed_timing.py` and
`tests/test_measurement_analyses.py`, using fake transports and the fake vLLM server.

## 2. Backfill: the latency card (estimates from totals)

Scope: 35,456 calls in 123 runs (26,500 live). Method: median regression of total seconds on output tokens, with
bootstrap intervals (`measurement/backfill.md`, `measurement/latency_card.md`).

Decode speed, in tokens per second:

| model | decode speed |
|---|---|
| Haiku | 214-240 |
| Sonnet | 122-140 |
| Opus | 102-112 |
| Luna | 92-116 |
| Sol | 33-34 (flagged: confirm by streaming) |

These are ranges of the arms' point estimates (each arm's 95% interval is in backfill.md). The OpenAI rates count
hidden reasoning as output.

- **Overheads** (TTFT plus network and queue): 0.4-2.2 s.
- **p95 totals:** 7.3 s for Haiku off, 558 s for Haiku max, 929 s for Sonnet max.
- **Dense 6-6-6-1 stage profile:** imbalance 1.55-1.74 in context (at critique), 1.46-1.72 in latency (at propose)
  and 1.28-1.44 in dollars (at propose).
- All of this reproduces the first pass.

## 3. Configuration map

Data: the anchor's tier-1 arms, 440 BBEH and 93 math items, exact replay; exploratory (`measurement/config_map.md`).
Grid: dollar budget × latency budget (p95 total, estimated TTFAT p95, and mean total for the prototype).

- **After audit M1-1:**
  - a single call's p95 is per call;
  - a vote answers at its slowest call;
  - OpenAI reasoning arms' TTFAT is their total seconds (their reasoning was hidden and not recorded).
- **Held-out regret** (100 halvings; over-budget picks left out; biased up):
  - BBEH: 0.9-1.6 points on average over cells (cell means up to 8);
  - math: 1.6-1.7 points (up to 13; 93 items).
- **Median winner stability:** 74-86%.
- **BBEH winners:**
  - from $0.0025 and a p95 of 30 s (mean 8 s), one Sol low call wins;
  - below that, Haiku calls or votes win;
  - nothing meets a 5-s p95;
  - under TTFAT budgets of 2-15 s, Haiku low or Sonnet low wins;
  - cascades win no p95 or mean-latency cell (2 TTFAT cells).
- **Math:** a Haiku-off 3-vote escalating to Sonnet off or Sol low wins the dearest cells.
- **Against the first pass's prototype:**
  - It is confirmed that one Sol low call wins from 8 s and $0.0025, and that cascades never win on BBEH.
  - Under 5 s (mean), single Haiku calls win here, not Haiku-off votes.
- **Stage balance** (P4 grid replayed): no imbalance ratio predicts accuracy at matched tokens; every interval
  includes 0. The grid cannot separate balance from width.

## 4. Optional probe: not run

The configs are ready:
- `configs/experiments/measurement/m1_probe_{anth,open}_{c1,c4,path}.yaml`;
- with a measurement prereg, dry-run on the fake model;
- `aan check` clears;
- worst case $1.79 (Anthropic) and $1.73 (OpenAI) per concurrency config, about $1.9 expected for all six.

They were not run because E6's paid work had not ended: E6's log showed the OpenAI bridge still running
(Sol medium and Luna to come; shared room $14.53). The GPU pilot will measure TTFT and TPOT locally at no API cost.

## 5. Patching (addendum 2)

`measurement/patching.md` covers theory, cached numbers, agent loops and batching.
`measurement/patching_prereg_draft.md` is a design only.

Critique stage numbers from the pilot's real messages:

| variant | peak context vs full | input dollars vs full (stylized) | as the executor bills |
|---|---|---|---|
| full | 8,853 tokens | (base) | (base) |
| fan-in 2 | -52% | +36% | +50% |
| fan-in 3 | -38% | +96% | +98% |
| fan-in 1 | -66% | -24% | +2% |
| compressed (measured answer-plus-reason, about 84 tokens per message) | -78% | -78% | -78% |

- In the stylized model, patching saves dollars only when f < 1.4 (Haiku, n = m = 6).
- As the executor bills it (a non-shared prefix uncached), every fan-in costs more than full reading: fan-in 1 +2%,
  fan-in 2 +50%. Only compression saves input dollars on a cached API.
- The prereg draft was revised after audit M1-1:
  - a dense-beats-single gate first;
  - 7-point non-inferiority with Holm over the 4 variants;
  - a kill on a bound;
  - n = 400 unsealed items.
- Output tokens and accuracy need new calls.

## 6. Caveats

- **Absolute API latency** includes the agent proxy path of these cloud sessions. It varies with time of day,
  provider load and run concurrency.
- **Cache hits carry no timing.**
- **Backfill and map latencies are estimates from totals.** Hidden reasoning makes OpenAI's TTFT a first-chunk time.
- **The map uses the anchor's arms only.** Study CD's grades belong to E6's read.

## 7. What Kevin must do

1. **Probe.** After E6 hands back, decide whether to spend about $1.9 expected of the shared room on the timing probe.
   - The worst cases summed over the six configs come to about $7. Each run is capped at $2.5 by the governor.
   - The prereg stops the probe at $3 in all, checked by hand before each config.
   - If yes, a session runs the six configs in order: path, then c1, then c4.
2. **GPU pilot.** Run the pilot with the new sidecar (RUN_GPU.md step 2). Confirm the vLLM metric names with the
   curl line, and check the KV bytes per token against the server's cache config.
3. **Patching.** Decide whether the patching experiment (draft prereg) joins the testbed's stage 2. It needs the
   `read: conclusion` block first.
4. **Timing default.** Decide whether `timing` should become the default (as the brief asked) once the probe has
   run with no stream failure. Until then, only configs that set `timing: true` stream.
5. **Merge order.** Merge PR #18 only after E6's PR #16 (audit M1-1). The branch will merge `depth_review` again
   then.
