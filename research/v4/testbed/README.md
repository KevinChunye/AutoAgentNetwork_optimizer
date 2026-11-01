# Open-weight testbed (session T1): width, depth and verification

This folder holds the T1 study: precision × size × thinking budget × k samples on Qwen3.5 2B/4B/9B served by vLLM
on a rented GPU. It costs $0 in API money and is metered in GPU dollars. Session T1 (2026-10-26) built and tested it
offline. Nothing has run on a GPU yet.

| File | What |
|---|---|
| `prereg.md` | T1–T5: questions, tests, margins, predictions, decisions, power by simulation, deviations from the brief |
| `RUN_GPU.md` | the resumable runbook for a Lightning Studio: environment, data, pilot, stage 1, stage 2, kernel run, hand-back; the GPU stop rule on every step |
| `power.csv` | power and false-positive rates of the preregistered tests, by simulation (`python -m autoagentnet.testbed.power`) |
| `gpu_ledger.csv` | (created by the runbook) GPU hours and dollars per step and stage |
| `throughput.json`, `kernel.csv`, `sealed/`, `results/` | (created by the runbook) measured throughput, real-kernel speed/memory/energy, the sealed T5 split, the reads |

## Code

Package: `autoagentnet/testbed/`. Each module has an offline test, `tests/test_testbed_*.py`.

- **`providers/vllm_local.py`**: a client for a local vLLM server.
  - Price $0. `vllm_local` is in `FREE_PROVIDERS`, so its calls need no price and stay out of the spend ledger.
  - Budget forcing over `/v1/completions`.
  - Log-prob signals: mean log-prob, entropy, answer margin.
- **Sampling:** `grid` (configs, seeds, estimates), `tasks`, `sample`. Every generation runs through
  NetworkExecutor → LocalRuntime → provider with a call cache.
- **Checking:** `checkers` (self-check, judge, white-box, sandboxed execution, eta), `compose` (exact replay of votes,
  mixes and cascades), `factor` (T5), `analysis` (T1–T5).
- **Fake backend:** `world` and `fake_server`.
  - The world has known item difficulty, precision-dependent ability and correlated errors.
  - The fake server is an httpx transport that answers like `vllm serve`.
  - `tests/test_testbed_pipeline.py` shows the real pipeline reproduces the world call for call.
  - `tests/test_testbed_recovery.py` shows the analysis recovers what the world puts in and tells planted
    alternatives apart.
- **GPU node:** `quantize` (fake-quantized checkpoints via RTN or llm-compressor), `kernel`, `seal`, `gpu_ledger`,
  CLI `python -m autoagentnet.testbed`.
- The response table follows E5's atlas schema (`autoagentnet/atlas/schema.py`, taken unchanged from branch
  `atlas_anchor`).

## GPU estimate (conservative priors; the pilot replaces throughput, tokens per call and overhead)

From `python -m autoagentnet.testbed estimate --stage <s> --machine <m>`. Each figure includes quantization, checkers,
set-up and an overhead of at least 1.5×. The drop rule (prereg section 7) cuts W3 first, then the kernel run, so that
stage 1 fits $45.

| machine ($/h on 2026-10-26) | pilot | stage 1, all 36 configs | stage 1 after the drop rule | stage 2 |
|---|---|---|---|---|
| H100 ($5.45) | ~$5.0 | ~$65 | ~$46 (no W3, no kernel run) | ~$41 |
| H200 ($4.50) | ~$4.1 | ~$50 | ~$37 (no W3) | ~$31 |
| A100 80GB ($1.85) | ~$1.8 | ~$53 (~28 h) | ~$40 (no W3) | ~$35 |

## What Kevin must provide

1. **A Lightning Studio** with an H200 (recommended) and about 250 GB of disk.
   - The same Studio switches to a CPU machine for installs, code grading and analysis.
   - Record the live rate in `RUN_GPU.md` step 1.
2. **Lightning settings:** auto top-up off, so the $100 is a hard ceiling; idle auto-sleep at 15 minutes.
3. **GitHub push access from the Studio:** a fine-grained token with `contents: write` on this repository only.
4. **Hugging Face:** nothing required (the repositories are public). An optional `HF_TOKEN` raises download limits.

The BBEH items are fixed: the 200 ids E5 reserved for T1 in `research/v4/anchor/tasks.json`.
