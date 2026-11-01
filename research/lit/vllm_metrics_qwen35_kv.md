# vLLM 0.32.0 Prometheus metrics, per-request timing, and Qwen3.5 KV bytes per token

Read 2026-10-27 by lit-scout. Version checked: the tag **v0.32.0 exists** (GitHub release page: published on "18 Oct", year not printed; same finding as `ow_testbed_sources.md` 5.1), so everything below is read at that tag unless stated. Qwen3.5 config.json files were read at the revisions pinned in `configs/testbed/models.yaml` (`Qwen/Qwen3.5-2B` @ 15852e8c, `Qwen/Qwen3.5-4B` @ 851bf6e8, `Qwen/Qwen3.5-9B` @ c2022362). The size table lives in `configs/testbed/models.yaml` (families.qwen3.5.repos); `autoagentnet/testbed/grid.py` reads it.

Reading method and its limit: WebFetch returns a small-model summary of each page, not raw bytes. Names and values below are what that read quoted back; the metric table and config values were each cross-checked against a second source (docs page, another tag, or the unpinned `main` config of the 4B repo). A one-line `curl` of the live `/metrics` on the Studio is still the final check (see "So what").

## 1. Prometheus metric names at v0.32.0

### vLLM `vllm/v1/metrics/loggers.py` (tag v0.32.0)
- Link: https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/v1/metrics/loggers.py (human view: https://github.com/vllm-project/vllm/blob/v0.32.0/vllm/v1/metrics/loggers.py)
- What it does: `PrometheusStatLogger` defines every metric the OpenAI server exposes at `/metrics`.
- Key numbers (quoted):
  - Labels: `labelnames = ["model_name", "engine"]`. So **`model_name` is present** on all base metrics, together with `engine` (the engine index as a string, e.g. "0"). `model_name = vllm_config.model_config.served_model_name`, so in this testbed it is the `--served-model-name` value from `autoagentnet/testbed/__main__.py` (for example `qwen3.5-4b-w4`). Exceptions: `vllm:admission_rejections` has only `model_name` and `reason`; some metrics add `reason`, `source`, `stage`, `finished_reason`, `status`.
  - Python names are written without `_total`; prometheus_client adds `_total` when a Counter is exposed. Design doc (https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/docs/design/metrics.md): "When exposing the time series for counter, a `_total` suffix will be added." The v0.32.0 release notes use the exposed form: `vllm:prompt_tokens_cached_by_source_total`. So scrape `vllm:prompt_tokens_total`, `vllm:generation_tokens_total`, `vllm:prefix_cache_hits_total`, `vllm:prefix_cache_queries_total`. Histograms expose `_bucket`, `_sum`, `_count`.
  - Table (code name -> type -> exposed series):

| What you want | Code `name=` | Type | Notes (quoted documentation string) |
|---|---|---|---|
| KV-cache usage fraction | `vllm:kv_cache_usage_perc` | Gauge | "KV-cache usage. 1 means 100 percent usage." (a fraction 0 to 1 despite `perc`); `multiprocess_mode="mostrecent"` |
| Running requests | `vllm:num_requests_running` | Gauge | "Number of requests in model execution batches." |
| Waiting requests | `vllm:num_requests_waiting` | Gauge | "Number of requests waiting to be processed." |
| Waiting by reason (new) | `vllm:num_requests_waiting_by_reason` | Gauge | label `reason` in {`capacity`, `deferred`}; the sum over reasons equals `vllm:num_requests_waiting` |
| TTFT | `vllm:time_to_first_token_seconds` | Histogram | "Histogram of time to first token in seconds." |
| Inter-token latency | `vllm:inter_token_latency_seconds` | Histogram | "Histogram of inter-token latency in seconds." One sample per streamed output event (design doc). |
| Mean time per output token, per request | `vllm:request_time_per_output_token_seconds` | Histogram | "Histogram of time_per_output_token_seconds per request." Design doc: "computed as `(end-to-end latency - TTFT) / (number of output tokens - 1)`", "recorded as zero for requests that generate no more than one token" |
| Prefill time | `vllm:request_prefill_time_seconds` | Histogram | "Histogram of time spent in PREFILL phase for request." |
| Decode time | `vllm:request_decode_time_seconds` | Histogram | "Histogram of time spent in DECODE phase for request." |
| Inference time (prefill + decode) | `vllm:request_inference_time_seconds` | Histogram | |
| Queue time | `vllm:request_queue_time_seconds` | Histogram | "Histogram of time spent in WAITING phase for request." |
| End-to-end latency | `vllm:e2e_request_latency_seconds` | Histogram | "Histogram of e2e request latency in seconds." |
| Prompt tokens | `vllm:prompt_tokens` (exposed `_total`) | Counter | also `vllm:prompt_tokens_by_source` (label `source`), `vllm:prompt_tokens_cached` ("Number of cached prompt tokens (local + external).") and `vllm:prompt_tokens_cached_by_source` |
| Generation tokens | `vllm:generation_tokens` (exposed `_total`) | Counter | |
| Prefix-cache queries / hits | `vllm:prefix_cache_queries`, `vllm:prefix_cache_hits` (exposed `_total`) | Counter | "Prefix cache hits, in terms of number of cached tokens." Hit rate = delta hits / delta queries. Also `vllm:external_prefix_cache_*`, `vllm:mm_cache_*` |
| Per-request token histograms | `vllm:request_prompt_tokens`, `vllm:request_generation_tokens` | Histogram | |
| Request outcomes | `vllm:request_success` (exposed `_total`) | Counter | label `finished_reason` |
| Preemptions | `vllm:num_preemptions` (counter), `vllm:request_num_preemptions` (histogram) | | |
| Cache config info | `vllm:cache_config_info` | Gauge (always 1) | labels are `CacheConfig.metrics_info()` = every attribute as a string, so `block_size` and `num_gpu_blocks` are label values (`vllm/config/cache.py`); gives KV capacity in blocks |

  - Histogram bucket defaults (https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/v1/metrics/buckets.py): TTFT "0.001, 0.005, 0.01, 0.02, 0.04, 0.06, 0.08, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 7.5, 10.0, 20.0, 40.0, 80.0, 160.0, 640.0, 2560.0"; inter-token "0.01, 0.025, 0.05, 0.075, 0.1, ... 80.0"; request latency (queue, prefill, decode, inference, e2e) starts "0.3, 0.5, 0.8, 1.0, 1.5, ..." and ends "... 1920.0, 7680.0". So prefill and queue times under 0.3 s all land in the first bucket; quantiles from those histograms are coarse for short prompts. The metrics doc mentions `--custom-histogram-buckets` to change this (v0.32.0 release notes list that flag).
- Renamed or deprecated (all quoted from code comments, tags v0.10.2, v0.11.0, v0.13.0 and v0.32.0):
  - `vllm:gpu_cache_usage_perc` -> `vllm:kv_cache_usage_perc`. v0.10.2 comment: "Deprecated in 0.9 - Renamed as vllm:kv_cache_usage_perc"; v0.11.0 comment: "Deprecated in 0.9.2 - Renamed as vllm:kv_cache_usage_perc / With 0.11.x you can enable with --show-hidden-metrics-for-version=0.10 / TODO: remove in 0.12.0" (the two tags give 0.9 and 0.9.2; I could not tell which is right). Not present in v0.13.0 or v0.32.0. Same for `vllm:gpu_prefix_cache_queries/hits` -> `vllm:prefix_cache_queries/hits`.
  - `vllm:time_per_output_token_seconds` -> `vllm:inter_token_latency_seconds`. v0.10.2/v0.11.0 comment: "Deprecated in 0.11 - Renamed as vllm:inter_token_latency_seconds"; help string "DEPRECATED: Use vllm:inter_token_latency_seconds instead."; still defined in the v0.13.0 file (behind `if self.show_hidden_metrics:`), **not present in v0.32.0**. The per-request histogram `vllm:request_time_per_output_token_seconds` is a different, live metric (present in v0.13.0 and v0.32.0) and is not the old name.
  - `vllm:num_requests_swapped` and `vllm:cpu_cache_usage_perc`: described in the design doc as legacy "swapped" preemption metrics; absent from the v0.32.0 file.
  - Deprecation policy (docs v0.13.0 https://docs.vllm.ai/en/v0.13.0/usage/metrics/ and v0.32.0 `docs/usage/metrics.md`): "when metrics are deprecated in version `X.Y`, they are hidden in version `X.Y+1` but can be re-enabled using the `--show-hidden-metrics-for-version=X.Y` escape hatch, and are then removed in version `X.Y+2`." In v0.32.0 `show_hidden_metrics` is assigned but no `if` uses it: nothing is hidden now.
  - New in v0.32.0 per the release notes (https://github.com/vllm-project/vllm/releases/tag/v0.32.0, Observability section): `vllm:prompt_tokens_cached_by_source_total`, `vllm:num_requests_kv_fetch_by_stage`, `vllm:admission_rejections_total`, `vllm:watermark_requests`; no renamed metrics were listed in Breaking Changes (the page's last 3,466 characters were not read).
- Relevance to AutoAgentNetwork: cost / measurement. These are the exact series the sidecar should scrape. The old names a script written from memory would use (`vllm:gpu_cache_usage_perc`, `vllm:time_per_output_token_seconds`, `vllm:gpu_prefix_cache_*`) return nothing on 0.32.0.
- Resources: Apache-2.0 (vLLM).
- Open questions: prefix-cache counters count tokens, and the testbed serve command passes `--enable-prefix-caching`; whether `vllm:prefix_cache_*` behaves sensibly when a hybrid (Gated DeltaNet) model uses the "align" Mamba cache mode was not checked.

## 2. Per-request timing in `/v1/completions` at v0.32.0: yes, behind a server flag

### vLLM docs "Per-Request Metrics" (v0.32.0) and protocol source
- Link: https://docs.vllm.ai/en/v0.32.0/features/per_request_metrics/ ; source https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/entrypoints/openai/completion/protocol.py , https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/entrypoints/generate/base/protocol.py , https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/entrypoints/openai/completion/serving.py , https://raw.githubusercontent.com/vllm-project/vllm/v0.32.0/vllm/entrypoints/generate/base/serving.py
- What it does: adds a `metrics` object to the response body.
- Key numbers (quoted):
  - Flag: "`--enable-per-request-metrics`" (docs example: `vllm serve meta-llama/Llama-3.1-8B-Instruct --enable-per-request-metrics`). Server side only; there is no per-request request field. Code: `enable_per_request_metrics: bool = False` in the serving class and `if self.enable_per_request_metrics:` before `build_per_request_timing_metrics(`. The flag needs stats logging: "vLLM rejects it when `--disable-log-stats` is also set."
  - Response schema: `CompletionResponse.metrics: PerRequestMetrics | None = None` and `CompletionStreamResponse.metrics: PerRequestMetrics | None = None`. `PerRequestMetrics` fields, all `float | None`: `time_to_first_token_ms`, `generation_time_ms`, `queue_time_ms`, `mean_itl_ms`, `tokens_per_second` (plus an experimental `speculative_decoding` field, enabled by `--per-request-spec-decode-metrics`).
  - Definitions (docs and `build_per_request_timing_metrics`): `queue_time_ms` = queued to scheduled; `time_to_first_token_ms` = "from scheduling to the first output token" (so it **excludes queue wait**, unlike the Prometheus TTFT, which I take to include it but did not verify in code); `generation_time_ms` = first to last output token ("excluding queue wait and prefill"); `mean_itl_ms` = decode interval / (generated tokens - 1), null for single-token responses; `tokens_per_second` = output tokens / (scheduling to last token), so it includes prefill. Prefill time is therefore `time_to_first_token_ms`; decode time is `generation_time_ms`; end-to-end server time is about `queue_time_ms + time_to_first_token_ms + generation_time_ms`.
  - Non-streaming: `metrics` is on the top-level response. Streaming: "Metrics attach to the final usage chunk... Clients must set `stream_options.include_usage: true`, unless the server forces usage with `--enable-force-include-usage`."
  - Null cases: "For `n > 1`, the `metrics` object is `null`"; omitted for requests with multiple prompts; any field is null if its timestamps are unavailable. Caveat: "At high concurrency, the metrics computation may add non-negligible CPU overhead, so benchmark first."
  - Other per-request fields in the v0.32.0 `CompletionRequest`: `return_token_ids`, `return_tokens_as_token_ids`, `request_id`, `priority`, `stream_options`. None of them is a timing flag. `CompletionResponse.usage` is the normal token count.
- Relevance to AutoAgentNetwork: cost. Gives per-call queue, prefill and decode times for the GPU-hour accounting without parsing logs, one `metrics` dict per call; `vllm_local` already uses `/v1/completions`. Currently `cmd_serve_cmd` in `autoagentnet/testbed/__main__.py` does not pass the flag, so the field will be absent until it is added to the serve command.
- Resources: Apache-2.0.
- Open questions: CPU overhead at about 256 requests in flight (the docs warn about it); whether `autoagentnet`'s `vllm_local` response parser would pass an unknown `metrics` key through to the cache.

## 3. Qwen3.5 config.json and KV bytes per token

### Hugging Face config.json, pinned revisions
- Links:
  - https://huggingface.co/Qwen/Qwen3.5-2B/raw/15852e8c16360a2fea060d615a32b45270f8a8fc/config.json
  - https://huggingface.co/Qwen/Qwen3.5-4B/raw/851bf6e806efd8d0a36b00ddf55e13ccb7b8cd0a/config.json
  - https://huggingface.co/Qwen/Qwen3.5-9B/raw/c202236235762e1c871ad0ccb60c8ee5ba337b9a/config.json
  - (4B at `main` was also read: https://huggingface.co/Qwen/Qwen3.5-4B/raw/main/config.json; same values)
- What it does: all three are `architectures: ["Qwen3_5ForConditionalGeneration"]`, `model_type: "qwen3_5"`; the language-model fields are nested under `text_config`. There is **no top-level `torch_dtype` or `dtype`**; `text_config.dtype` is `"bfloat16"` (key is `dtype`, not `torch_dtype`).
- Key numbers (as quoted from `text_config`):

| Repo | num_hidden_layers | full_attention_interval | layer_types | full-attention layers | linear (Gated DeltaNet) layers | num_attention_heads | num_key_value_heads | head_dim | hidden_size | dtype |
|---|---|---|---|---|---|---|---|---|---|---|
| Qwen/Qwen3.5-2B | 24 | 4 | 24 entries, "full_attention" at 1-based positions 4, 8, 12, 16, 20, 24 | 6 | 18 | 8 | 2 | 256 | 2048 | bfloat16 |
| Qwen/Qwen3.5-4B | 32 | 4 | 32 entries, "full_attention" at positions 4, 8, ..., 32 | 8 | 24 | 16 | 4 | 256 | 2560 | bfloat16 |
| Qwen/Qwen3.5-9B | 32 | 4 | 32 entries, "full_attention" at positions 4, 8, ..., 32 | 8 | 24 | 16 | 4 | 256 | 4096 | bfloat16 |

  All three: `layer_types` is the pattern `linear_attention` x3 then `full_attention`, repeated (0-based full-attention indices 3, 7, 11, ...); `attn_output_gate: true`; `mtp_num_hidden_layers: 1`; `max_position_embeddings: 262144`; `linear_conv_kernel_dim: 4`, `linear_key_head_dim: 128`, `linear_value_head_dim: 128`, `linear_num_key_heads: 16`; `linear_num_value_heads`: 16 (2B), 32 (4B and 9B).
- Computation. KV bytes per token = (full-attention layers) x 2 (K and V) x kv_heads x head_dim x 2 bytes (BF16). Per full-attention layer: 2 x kv_heads x 256 x 2.
  - **2B: 6 x 2 x 2 x 256 x 2 = 12,288 bytes/token (12 KiB)** (2,048 B per layer)
  - **4B: 8 x 2 x 4 x 256 x 2 = 32,768 bytes/token (32 KiB)** (4,096 B per layer)
  - **9B: 8 x 2 x 4 x 256 x 2 = 32,768 bytes/token (32 KiB)**
  - Sanity: a pure-attention model with all 32 layers would need 131,072 B/token; the 3:1 hybrid is 4x smaller. A 4k-token sequence holds 4,096 x 32,768 B = 128 MiB (4B and 9B) or 48 MiB (2B) of attention KV.
  - Not included: the MTP layer (`mtp_num_hidden_layers: 1`; unknown whether vLLM allocates KV for it when not serving speculative decoding, not checked) and the vision tower (the testbed serves with `--language-model-only`).
- Linear-attention layers are not free: they hold a fixed per-sequence state, independent of length. From `vllm/model_executor/layers/mamba/mamba_utils.py` (v0.32.0, `gated_delta_net_state_shape`): "conv_dim = head_k_dim * num_k_heads * 2 + head_v_dim * num_v_heads", conv state of `conv_kernel_size - 1` columns, temporal state shape `(num_v_heads, head_v_dim, head_k_dim)`. State dtype follows `mamba_cache_dtype` / `mamba_ssm_cache_dtype`, default "auto" which reuses the conv dtype, itself from the model dtype (`vllm/config/cache.py`). My arithmetic, assuming BF16 state and the config values above (not read from a running server): per linear layer, 4B/9B: temporal 32 x 128 x 128 x 2 B = 1,048,576 B, conv (128 x 16 x 2 + 128 x 32) = 8,192 channels x 3 x 2 B = 49,152 B, total about 1.05 MB; times 24 layers about 26.3 MB per sequence. 2B: temporal 16 x 128 x 128 x 2 = 524,288 B, conv (4,096 + 2,048 = 6,144) x 3 x 2 = 36,864 B; about 0.56 MB per layer, times 18 about 10.1 MB per sequence. At 4k tokens, 4B attention KV (128 MiB) is about 5x that state, so the per-token figure is the right main term for long contexts, but it understates cost for short calls.
- Relevance to AutoAgentNetwork: cost. The 12/32/32 KiB per token figures are the KV-bytes-per-token calculator inputs; the hybrid design makes 4B and 9B identical per token (same 8 layers x 4 KV heads x 256), so KV capacity does not distinguish them, only weights do.
- Resources: Apache-2.0 (per `configs/testbed/models.yaml`); repos public.
- Open questions: vLLM's hybrid KV-cache manager may round the attention block size up to match the Mamba page (config has `mamba_block_size`, "Value must be a multiple of 8", and `mamba_cache_mode` "align" is the default when prefix caching is on), so the real bytes per token that `num_gpu_blocks x block_size` implies can differ from the 32 KiB figure; compare against `vllm:cache_config_info` and the "GPU KV cache size" line in the server log on the first boot. `--kv-cache-dtype` (default auto, so BF16 here) was not checked in the docs.

## So what

Nothing in `research/plan.md` was read for this task, so these are changes for the sidecar and runbook rather than plan sections.
1. Scrape `vllm:kv_cache_usage_perc`, `vllm:num_requests_running`, `vllm:num_requests_waiting`, `vllm:time_to_first_token_seconds`, `vllm:inter_token_latency_seconds` (not `time_per_output_token_seconds`), `vllm:request_{queue,prefill,decode}_time_seconds`, `vllm:e2e_request_latency_seconds`, and the `_total` counters. Filter on `model_name="<checkpoint>"`.
2. Add `--enable-per-request-metrics` to `cmd_serve_cmd` if per-call queue/prefill/decode times are wanted; set `stream_options.include_usage` if any call streams. Budget for the CPU overhead warning.
3. Keep `--custom-histogram-buckets` in mind: the 0.3 s lowest bucket on request-phase histograms hides short prefill times; per-request `metrics` is the finer source.
4. KV calculator constants: 2B 12,288 B/token, 4B and 9B 32,768 B/token, plus a per-sequence recurrent state of about 10 MB (2B) or 26 MB (4B, 9B) under the BF16 assumption. Check against `vllm:cache_config_info` (`block_size`, `num_gpu_blocks`) on the first live boot, because hybrid block rounding was not verified.
5. Run `curl localhost:8000/metrics | grep -E '^# TYPE vllm:(kv_cache|num_requests|time_to_first|inter_token|request_.*_time|e2e|prompt_tokens|generation_tokens|prefix_cache)'` once on the Studio to confirm the names; this was a read of source, not of a running 0.32.0 server.
