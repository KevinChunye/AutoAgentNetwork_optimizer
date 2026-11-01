# RUN_GPU: the open-weight testbed on a Lightning AI Studio

This runbook takes the testbed from an empty Studio to committed response tables and the T1–T5 reads. Kevin or a
Claude Code session started inside the Studio can run it from top to bottom. Every step is resumable: finished
Parquet shards and cached calls are skipped, so after a crash you rerun the same command.

Revised after audit T1-1 (`research/audit_log.md`).

## Rules that hold throughout

- **Repo rules.** `CLAUDE.md` and `docs/RESEARCH_PROTOCOL.md` apply.
  - No API calls: every generation goes to the local vLLM server through autoagentnet's executor.
  - Never set `ANTHROPIC_API_KEY`, and never read or print a key.
  - Never edit `configs/budget.yaml`, `configs/pricing.yaml` or `state/`.
- **Money.** The whole testbed has $100 of Lightning credit, metered in `research/v4/testbed/gpu_ledger.csv`.
  - Every GPU step runs through `step` (`scripts/testbed_env.sh`), which:
    - checks the stop rule for the most the step may cost, 1.5 × its estimate, before it starts (exit 3: that could
      cross a limit);
    - interrupts the step at 1.5 × its estimate (exit 5);
    - bills the wall-clock time afterwards, idle time included.
  - Limits: pilot ≤ $10; stage 1 ≤ $55; stage 2 only while ≥ $30 remains; hard stop at $90 in total.
  - On exit 3, 5 or 7 (a stage's kill line): stop, push, write what happened in `research/log.md`, call the
    `auditor` and hand back to Kevin.
    Never lower an estimate to get past the rule.
- **What runs on the GPU.** Only sampling, checkers, quantization and the kernel run use a GPU machine.
  - Installs, data downloads, code grading and the analysis run on a CPU machine of the same Studio (Lightning keeps
    the disk when the machine changes).
  - Switch with the Studio's machine selector. After every switch, restart the clock at the new rate:
    `$TB ledger tick ...` and then `$TB ledger start ...`.
- **Idle.** Stop the Studio whenever no step is running.
  - Set the Studio's idle auto-sleep to 15 minutes (Studio settings).
  - Run `start_watchdog <stage>` at every GPU boot (the watchdog does not survive a restart). It bills idle time to
    that stage and stops vLLM and the Studio after 20 idle minutes. A `step` whose shell died leaves a stale lock,
    which the watchdog ignores.
  - Kevin turns off Lightning's automatic credit top-up, so the $100 is a hard ceiling.
- **Git.** Work on `ow_testbed_runs`. Never push to `main` and never force-push. `step` commits and pushes after
  every step.
- **Order.** One step at a time. Read each step's output before running the next. If a check fails, stop and log it.

Terms: a *checkpoint* is one set of weights served by one vLLM server, e.g. `qwen3.5-4b-w4`. A *config* is a
checkpoint plus a thinking budget, e.g. `qwen3.5-4b:w4:budget:1024` (`autoagentnet/testbed/grid.py`).

## 0. Before booting (Kevin)

1. **Machine.** Open Lightning's live rate card and record the rate. On 2026-10-26 it read:

   | machine | $/h | stage 1, all 36 configs (prior) | stage 1 after the drop rule | stage 2 | pilot |
   |---|---|---|---|---|---|
   | H100 | 5.45 | ~11.9 h, ~$65 (over the cap) | ~$46 (no W3, no kernel run) | ~$41 | ~$5.0 |
   | H200 | 4.50 | ~11.2 h, ~$50 | ~$37 (no W3) | ~$31 | ~$4.1 |
   | A100 80GB | 1.85 | ~28 h, ~$53 | ~$40 (no W3) | ~$35 | ~$1.8 |

   - The estimates come from `python -m autoagentnet.testbed estimate --stage stage1 --machine <m>` and use
     conservative priors (decoding at about 256 requests in flight is closer to compute-bound than to
     bandwidth-bound).
   - The pilot replaces throughput, tokens per call and overhead with measurements.
   - **Recommendation: an H200.** It has the lowest prior cost; the A100's ~28 hours means many sessions.
   - On an H100, the judge step's 1.5× guard leaves about $2 under the $55 cap, so a small overrun in sampling would
     cost T4 (audit T1-3).
2. **Disk:** at least 250 GB. Fake-quantized checkpoints are stored in BF16, so each size has up to four copies, and
   step 5 deletes a size's copies once all its steps have succeeded.
3. **GitHub push access from the Studio:** a fine-grained token with `contents: write` on this repository only,
   entered once through git's credential helper. It must never appear in a file or a log.
4. **Hugging Face:** the repositories are public. An `HF_TOKEN` only raises download limits.
5. **Lightning:** auto top-up off; Studio idle auto-sleep at 15 minutes.

## 1. Environments, on a CPU machine (no GPU time)

```bash
cd ~ && git clone https://github.com/KevinChunye/AutoAgentNetwork.git && cd AutoAgentNetwork
git checkout ow_testbed            # or main, once the T1 PR is merged
git checkout -b ow_testbed_runs

# Studio Python is 3.10; vLLM needs >= 3.11. uv makes self-contained 3.12 environments in $HOME.
curl -LsSf https://astral.sh/uv/install.sh | sh && source ~/.local/bin/env
uv venv --python 3.12 ~/.venvs/aan-serve && uv venv --python 3.12 ~/.venvs/aan-quant
( source ~/.venvs/aan-quant/bin/activate && uv pip install llmcompressor datasets safetensors huggingface_hub \
    && uv pip install -e ".[dev]" )
source ~/.venvs/aan-serve/bin/activate
uv pip install "vllm==0.32.0" safetensors huggingface_hub && uv pip install -e ".[dev]"
python -m pytest -q tests/test_testbed_*.py tests/test_atlas_schema.py      # offline; all must pass
source scripts/testbed_env.sh
```

- If `uv venv` is refused, use `conda create -y -p ~/.venvs/aan-serve python=3.12` instead.
- llm-compressor lives in its own environment because its pinned torch and transformers may clash with vLLM's.

**Data** (still on the CPU machine):

```bash
$TB fetch-tasks          # BBEH (all items, no filters; canary: stays out of git), AIME 2026 + HMMT Feb 2026 (63),
                         # LiveCodeBench v6 (150 newest)
python -c "from autoagentnet.testbed.tasks import load_testbed_tasks as L; import collections; \
print(collections.Counter(t.meta['benchmark'] for t in L()))"   # expect bbeh 200 (E5's reserved t1_bbeh ids), math 63, code 100
$TB download --size 4                                         # pinned commit; repeat per size later
```

- Add the three sources to `research/data_cards.md`: source, licence, revision, counts and contest dates.
- None of these data go into git; `data/external/` is ignored.
- Contamination: LiveCodeBench v6 (to April 2025) and AIME/HMMT (February 2026) predate Qwen3.5's release
  (2026-03-02), and the Qwen3.5 card reports LCB v6 and HMMT scores. Record them as "possibly seen".

**Switch to the GPU machine**, then start the clock with the live rate and the watchdog:

```bash
source ~/.venvs/aan-serve/bin/activate && source scripts/testbed_env.sh
$TB check-node                                   # python 3.12, the GPU, vllm 0.32.0, huggingface.co 200
$TB ledger start --machine "<studio name>" --gpu-type "<H200|H100|A100-80GB>" --rate <live $/h>
start_watchdog pilot          # at every GPU boot, with the stage being run (pilot, stage1, stage2)
```

## 2. Pilot (≤ $10): 4B, BF16 and W4, thinking off and 1k, 50 items, k = 6

The pilot's 50 items are 20 BBEH, 15 math and 15 code (`tasks.pilot_items`). Its kill line (research/log.md,
preregistered) is 1.5 × its estimate in dollars: about $6.2 on an H200, $7.5 on an H100, $2.7 on an A100. Set it
once, and `step` stops the pilot when the ledger passes it (exit 7); read `$TB ledger show` after every step:

```bash
export KILL_USD=$(python -c "from autoagentnet.testbed import grid; print(round(1.5 * grid.stage_estimate('pilot', 50)['usd'], 2))")
```
 The pilot, smoke and scan stages have
their own seeds (`grid.SEED_SALT`), so stage 1 draws fresh samples even on the pilot's items.

```bash
# W4 = AWQ group 128 through llm-compressor (llm-awq cannot load Qwen3.5). If AWQ fails on the hybrid layers, set
# METHODS["w4"] = ("gptq", 4, 128) in autoagentnet/testbed/quantize.py, commit it with a line in research/log.md
# ("deviation: W4 is GPTQ"), and rerun.
step pilot $($TB step-hours --stage pilot --quantize w4 --size 4) "quantize 4B w4" \
    scripts/testbed_in_quant.sh $TB quantize --size 4 --precision w4
cat runs/testbed/models/qwen3.5-4b-w4/quantization.json          # quantized_tensors > 0, calibration recorded

serve qwen3.5-4b-bf16
# session M1: confirm the metric names the GPU trace reads (vLLM 0.32.0) and the per-request timing flag
curl -s localhost:8000/metrics | grep -E '^vllm:(kv_cache_usage_perc|num_requests_(running|waiting)|cache_config_info)'
curl -s localhost:8000/metrics | grep -cE '^vllm:(time_to_first_token|inter_token_latency|request_(prefill|decode|queue)_time)_seconds_count'   # expect 5
# live smoke test: 2 items x 2 samples, one budget-forcing config, before anything larger
step pilot 0.1 "smoke 4B bf16" $TB sample --stage smoke --checkpoint qwen3.5-4b-bf16 --task-limit 2 --k 2 --budgets 1024
$TB pilot-report --stage smoke                   # parsed, thinking <= 1024, an ANSWER line; read one reply in
                                                 # results/testbed/smoke/**/*.texts.parquet before going on
                                                 # timing table: ttft and tpot present, joules > 0, kv usage > 0;
                                                 # serve_card-qwen3.5-4b-bf16.json: vllm 0.32.0, enable_prefix_caching
step pilot $($TB step-hours --stage pilot --checkpoint qwen3.5-4b-bf16 --items 50) "pilot sample 4B bf16" \
    $TB sample --stage pilot --checkpoint qwen3.5-4b-bf16
step pilot 0.1 "pilot self-check 4B bf16" $TB self-check --stage pilot --checkpoint qwen3.5-4b-bf16
# the math scan: 4B BF16 at a 4k budget on 30 math items (math band; tokens per call at 4k)
step pilot 0.25 "math scan" $TB sample --stage scan --checkpoint qwen3.5-4b-bf16 --parts math --task-limit 30

serve qwen3.5-4b-w4
step pilot $($TB step-hours --stage pilot --checkpoint qwen3.5-4b-w4 --items 50) "pilot sample 4B w4" \
    $TB sample --stage pilot --checkpoint qwen3.5-4b-w4
step pilot 0.1 "pilot self-check 4B w4" $TB self-check --stage pilot --checkpoint qwen3.5-4b-w4
stop_server
$TB ledger tick --stage pilot --step "pilot GPU done"
```

Switch to the CPU machine (`ledger start` with its rate) and grade the code:

```bash
$TB grade-code --stage pilot && $TB grade-code --stage scan
$TB pilot-report --stage scan | head -20             # math accuracy at 4k (20-80% band?)
$TB pilot-report --stage pilot --machine <the pilot's GPU type> --rate <its $/h>   # writes throughput.json:
                                     # measured throughput, cost per call, overhead, stage-1 re-estimate, drop rule
                                     # (without --machine it takes the GPU type of the pilot's ledger rows)
git add research/v4/testbed/throughput.json results/testbed && git commit -qm "testbed pilot: measurements" && git push -q
```

**GPU trace (session M1).** Every `sample` run starts a sidecar per shard (`autoagentnet/testbed/sidecar.py`; turn
it off with `--no-trace`). It polls `localhost:8000/metrics` every 2 s (KV-cache usage, running and waiting requests,
the TTFT, inter-token, prefill, decode and queue histograms) and `nvidia-smi` every 1 s (power, memory, utilization),
and writes `<shard>.gpu_trace.parquet` next to each shard. Each shard row gains ttft_s, ttfat_s, prefill_s,
decode_s, tpot_s, the server's own vllm_queue_s / vllm_prefill_s / vllm_decode_s (from `--enable-per-request-metrics`,
which `serve-cmd` now passes), context_tokens, kv_bytes_est (from the checkpoint's config.json: 32,768 bytes per token
for 4B and 9B, 12,288 for 2B) and energy_j (the shard's measured joules shared out by decode-token units: an
apportionment, not a measurement). `sample` also writes `serve_card-<checkpoint>.json` (vLLM version and the cache
configuration the server reports: block size, GPU blocks, prefix caching on or off). The trace files are committed
with the shards. `pilot-report` prints, and writes into `throughput.json` under `timing_by_config`, TTFT p50/p95,
TPOT p50/p95, KV-cache usage p95, peak GPU memory and joules per 1,000 output tokens per configuration.
Cost: the sidecar adds one HTTP scrape every 2 s and one `nvidia-smi` call every 1 s; the docs warn that per-request
metrics add CPU overhead at high concurrency, so compare the pilot's measured throughput with the prior as before.

**Pilot checks.** Write every line below into `research/log.md` with its value.

1. **Parsing.** `parsed` ≥ 0.9 on BBEH and math in every config. `truncated` ≤ 0.05; if higher, raise
   `answer_max_tokens` in `configs/testbed/models.yaml`.
2. **Budget forcing.** At 1k, thinking ≤ 1024 always and `forced` > 0. At budget 0, thinking = 0.
   - If `forced` is 1.0 and the answers are nonsense, the end marker may be a special token that vLLM strips; check
     one reply.
3. **Quantization is real.** The answers of `qwen3.5-4b:w4:*` differ from BF16's, and `quantization.json` lists
   the quantized tensors.
4. **Code.** At least one program passes its hidden tests. Record `can_unshare()`:
   `python -c "from autoagentnet.testbed.checkers import can_unshare; print(can_unshare())"`.
5. **Floors.** 4B BF16 accuracy on the hard third of the pilot items. If it is near 0, T1 and T4 cannot work on hard
   items; report it.
   - Math at 4k is inside 20–80%, or noted. All 63 items stay either way.
6. **Cost.** Measured throughput, tokens per call by budget, overhead, the stage-1 re-estimate and the drop rule's
   scope, all from `throughput.json`.
7. **Timing (session M1).** Per configuration: TTFT p50/p95, TPOT, KV-cache usage p95, peak memory and joules per
   1,000 output tokens (`timing_by_config`). Check KV bytes per token against the server: the log's "GPU KV cache
   size" line and `num_gpu_blocks x block_size` in the serve card (hybrid layers may round blocks).

**Pilot decision rule** (prereg section 7):

1. If stage 1 fits $45, keep the full scope.
2. Otherwise drop W3, and if still needed the kernel run: set `configs/testbed/scope.yaml` exactly as the report's
   `recommended_scope` says, and commit it with a log line.
3. If it is still above $55 after both drops, stop and hand back.
4. Otherwise: recalibrate the power simulation to the pilot (prereg section 5), call the `auditor`, and continue
   only on GO.

## 3. Freeze before stage 1

```bash
# configs/testbed/tasks.yaml has `source: anchor`: the BBEH items are the 200 ids E5 reserved for T1
# (research/v4/anchor/tasks.json, taken from atlas_anchor @ 81da6e1; hashes in research/v4/anchor/sealed/MANIFEST.md).
$TB seal                       # 70/30 split with a fresh random key; writes research/v4/testbed/sealed/
git add research/v4/testbed/sealed configs/testbed && git commit -qm "testbed: seal the T5 split" && git push -q
```

`prereg.md` was committed before the pilot. Only dated addenda may follow it (the pilot recalibration, the scope),
and they must be committed before the first stage-1 sample.

## 4. Stage 1 (≤ $55): 3 sizes × 4 precisions (3 if W3 is dropped) × 3 budgets, 363 items, k = 6

Downloads for the next size can run on the CPU machine before switching back to the GPU. At every GPU boot:
`source ~/.venvs/aan-serve/bin/activate && source scripts/testbed_env.sh`, `$TB ledger start ...` with the live rate,
and `start_watchdog stage1`. Then run the block below with `S=2`, then `S=4`, then `S=9`:

```bash
S=2; ok=1
PRECS=$(python -c "from autoagentnet.testbed import grid; print(' '.join(p for p in grid.PRECISIONS if p not in grid.scope()['drop_precisions']))")
KREAL=$(python -c "from autoagentnet.testbed import grid; print('--real' if grid.scope()['kernel_run'] else '')")
[ -d runs/testbed/models/qwen3.5-${S}b-bf16 ] || step stage1 0.1 "download ${S}B" $TB download --size $S || ok=0
for P in $PRECS; do
  [ "$P" = bf16 ] && continue
  [ $ok = 1 ] && step stage1 $($TB step-hours --stage stage1 --quantize $P --size $S) "quantize ${S}B $P" \
      scripts/testbed_in_quant.sh $TB quantize --size $S --precision $P $KREAL || ok=0
done
for P in $PRECS; do
  [ $ok = 1 ] || break
  CK=qwen3.5-${S}b-$P
  serve $CK || { ok=0; break; }
  step stage1 $($TB step-hours --stage stage1 --checkpoint $CK) "sample $CK" $TB sample --stage stage1 --checkpoint $CK || { ok=0; break; }
  step stage1 $(python -c "print(round(0.25*$($TB step-hours --stage stage1 --checkpoint $CK)+0.05,2))") "self-check $CK" \
      $TB self-check --stage stage1 --checkpoint $CK || { ok=0; break; }
done
stop_server
# free disk only after every step of this size succeeded; keep the 9B BF16 (the judge) and the *-real checkpoints
[ $ok = 1 ] && [ "$S" != 9 ] && rm -rf runs/testbed/models/qwen3.5-${S}b-{bf16,w8,w4,w3}
echo "size $S ok=$ok"
```

If `ok=0`, read the last step's message:
- exit 3: the budget rule; stop and hand back;
- exit 5: past 1.5 × the estimate; investigate, log and audit;
- anything else: fix and rerun the block. Finished shards and cached calls are skipped.

**Judge** (the 9B BF16 at 4k). It reads 4 candidates for every config, and 2 for the W8 configs (T2):

```bash
serve qwen3.5-9b-bf16
step stage1 $($TB step-hours --stage stage1 --judge) "judge 9B bf16 4k" $TB judge --stage stage1 --judge qwen3.5-9b-bf16 --budget 4096
stop_server
```

**Real-kernel run.** This runs only if `scope.yaml` keeps it, and only after its own prereg addendum and an audit
GO (audit T1-1). For each size, serve the compressed checkpoints and BF16, 300 calls each:

```bash
for S in 2 4 9; do for P in $PRECS; do
  CK=qwen3.5-${S}b-$P; [ "$P" != bf16 ] && CK=$CK-real
  serve $CK || { echo "$CK does not load on real kernels (W3 may not): noted, skipped"; continue; }
  grep -iE "model (weights|loading).*(GiB|GB)" runs/testbed/vllm-$CK.log | tail -1 | sed "s/^/$CK: /" >> research/v4/testbed/kernel_weights.log
  step stage1 0.12 "kernel $CK" $TB kernel --size $S --precision $P || break
done; done
stop_server
```

If the BF16 weights of a size were deleted, `$TB download --size S` brings them back (about 0.1 h).

## 5. Grade and read stage 1 (CPU machine)

```bash
$TB ledger tick --stage stage1 --step "stage 1 GPU done"   # then switch to CPU and `ledger start` at its rate
$TB grade-code --stage stage1
$TB analyze --stage stage1 --out research/v4/testbed/results                       # T1-T4
$TB analyze --stage stage1 --out research/v4/testbed/results --unseal --reason "stage 1 complete"   # T5, once
git add results/testbed research/v4/testbed && git commit -qm "testbed stage 1: graded and read" && git push -q
```

Then:
- call the `auditor` and paste its verdict into `research/audit_log.md`;
- write the reads against `prereg.md` in `research/log.md`, each labelled confirmatory or exploratory as the prereg
  says;
- open a PR from `ow_testbed_runs`.

## 6. Stage 2 (only with ≥ $30 left, its own prereg addendum and an audit GO)

Stage 2 is not preregistered beyond its design. Before any stage-2 step:
- write a dated addendum to `prereg.md` (question, prediction, decision);
- get an audit GO.

The guard refuses it when less than $30 remains.

```bash
$TB ledger guard --stage stage2 --hours 0.1 || exit 3
step stage2 0.15 "download gpt-oss" bash -c "$TB download --family gpt-oss --size 20 --precision mxfp4 && \
    $TB download --family gpt-oss --size 20 --precision bf16"
# dry run first: --task-limit 2 checks how the effort is passed and how thinking is counted for gpt-oss
for P in mxfp4 bf16; do
  CK=gpt-oss-20b-$P; serve $CK
  step stage2 $($TB step-hours --stage stage2 --checkpoint $CK) "sample $CK" $TB sample --stage stage2 --checkpoint $CK || break
  step stage2 0.15 "self-check $CK" $TB self-check --stage stage2 --checkpoint $CK || break
done
step stage2 $($TB step-hours --stage stage2 --quantize w4gptq --size 9) "quantize 9B w4gptq" \
    scripts/testbed_in_quant.sh $TB quantize --size 9 --precision w4gptq
serve qwen3.5-9b-w4gptq && step stage2 $($TB step-hours --stage stage2 --checkpoint qwen3.5-9b-w4gptq) "sample 9B w4gptq" \
    $TB sample --stage stage2 --checkpoint qwen3.5-9b-w4gptq
for P in bf16 w4; do
  serve qwen3.5-9b-$P --max-model-len 24576
  step stage2 0.6 "sample 9B $P 16k math" $TB sample --stage stage2 --checkpoint qwen3.5-9b-$P --budgets 16384 --parts math
done
serve gpt-oss-20b-mxfp4      # cross-family judge on stage 1's candidates
step stage2 1.0 "judge gpt-oss" $TB judge --stage stage1 --judge gpt-oss-20b-mxfp4 --budget 0 --effort medium
stop_server
```

Unverified until the dry run:
- how gpt-oss takes its effort (the provider sends `chat_template_kwargs: {reasoning_effort}`; the card says a
  "Reasoning: <effort>" system line);
- gpt-oss's thinking and answer tokens are counted together.

## 7. Hand back

- Run `$TB ledger tick --stage <stage> --step final` and `$TB ledger show`, then **stop the Studio**.
- **In git:** the response tables, checks, `kernel.csv`, `throughput.json`, the ledger, the sealed lists and the
  reads.
- **On the Studio's disk:** the answer texts (`*.texts.parquet`), the call cache and the checkpoints.
  - They are too large for git, and the texts may quote benchmark items.
  - To keep the texts, `tar czf runs/testbed/texts.tgz results/testbed/**/*.texts.parquet` and attach the archive
    to the results PR.
- The results PR lists:
  - spend by stage;
  - the pilot checks;
  - the reads, labelled as in the prereg;
  - what remains.
