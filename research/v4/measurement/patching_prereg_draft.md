# Draft prereg: patched, compressed and redistributed agent networks (session M1, addendum 2, 8.6)

**Status: a design. Not committed as a prereg, not run, no money spent.** It becomes a prereg only after the
following, in order:
1. Kevin agrees to it.
2. The block code in "Code needed" exists and has its fake-model tests.
3. The GPU testbed's stage 1 is done (this would run as a T1 stage-2 addendum).
4. The auditor says GO.

The theory and the $0 context numbers are in `patching.md`.

## Question

At a fixed network (propose 6, critique 6, refine 6, aggregate 1), does reading fewer upstream messages (patching),
shorter ones (compression), or both at different stages (redistribution) keep the dense network's accuracy at a
smaller peak context, a shorter time to the final answer, and fewer dollars or GPU-seconds?

## Variants

Same tasks, same proposers. Stage 1 is identical in every variant, so all five share the propose calls through the
call cache.

| id | critique reads | refine reads | aggregate reads | what it tests |
|---|---|---|---|---|
| V0 full | all 6, full | all 6, full | all 6, full | the pilot's dense network (control) |
| V1 critique fan-in 2 | 2 (circular window), full | all 6, full | all 6, full | patching one stage |
| V2 critique + refine fan-in 2 | 2, full | 2, full | all 6, full | patching two stages (reach 3 of 6 before the aggregator, all 6 after) |
| V3 compressed | all 6, compressed | all 6, compressed | all 6, compressed | compression everywhere |
| V4 redistributed | 2, full | all 6, compressed | all 6, compressed | local detail early, a global view late |

"Compressed" uses a fixed rule, so the network stays reproducible and cacheable: an upstream message is cut to its
last two paragraphs (its concluding statement and its ANSWER line, as `analysis/patch_context.py` measures it). No
model call does the compressing.

## Measures

Per item and variant:

- **Accuracy** of the final answer (BBEH grader; math with the math grader).
- **Peak context per stage** (`stages.csv`: peak_context_tokens).
- **Critical-path TTFAT**: time until the final stage's first answer token, if each stage runs its agents in
  parallel (results.csv: critical_path_ttfat_s).
- **Stage latency** (the slowest call per stage) and the **imbalance ratios**.
- **Cost**:
  - on the GPU: GPU-seconds (the shard's measured wall-clock shared by tokens) and joules per 1,000 output tokens
    (apportioned);
  - on the API: cache-aware dollars.
- **Input and output tokens per stage.** Output tokens can change: a critic that reads less may write less.

## Gate, hypotheses and kill (revised after audit M1-1)

**G0, the gate (first, on the same items).** Patching a network only matters if the network adds something.

- V0 must beat one call of the same model (Qwen3.5-4B, thinking off) by at least 5 points, with the lower end of
  the paired 95% interval above 0.
- If it does not, stop: report the dense network's value on this model and run nothing else.

**Checks, not hypotheses.** These follow from the definitions; they are measured and reported, not tested:

- V1's critique peak context is about half of V0's;
- V3's context is lower than V1's.

**Tests.** All are non-inferiority against V0, with margin delta = 7 points, paired over items. A variant is
non-inferior when the one-sided lower bound of (variant - V0) is above -7 points. Holm's correction runs over the
four variants (V1-V4) at a 5% family level.

- **H-P1 (patching):** V1 is non-inferior to V0.
- **H-P2 (compression):** V3 is non-inferior to V0. Separately, V3 against V1 is reported with its interval
  (descriptive).
- **H-P3 (redistribution)** and V2 are tested in the same Holm family. A failure there is reported, not acted on.

**Kill.** Stop this line if, for both V1 and V3, the one-sided 95% upper bound of (variant - V0) is below -5 points,
i.e. a loss of more than 5 points is established. Report it as a negative result. A point estimate alone never kills.

**Decision.**

- If H-P1 or H-P2 holds, the variant that holds with the lower peak context becomes the testbed's network for KV-bound
  local serving. On a cached API only compression saves input dollars: as the executor bills it, every fan-in costs
  more than full reading (patching.md section 3).
- If H-P2 holds, a Haiku follow-up of V0 against V3 is proposed (about 22% of the critique input dollars).
- If neither holds and the kill does not fire, the result is "not resolved at delta = 7"; no follow-up.

## Where it runs

1. **First, the GPU testbed** ($0 API; Lightning credit), as a T1 stage-2 addendum.
   - Setup:
     - Qwen3.5-4B in BF16, thinking off;
     - 400 BBEH items (power, below) that are in no sealed list and not used by stage 1: check them against
       `research/v4/anchor/sealed/`, `research/v4/cd/sealed/`, `research/v3/evidence/sealed/` and the testbed's seal
       (`python -m autoagentnet.testbed seal`) before the prereg is committed, and commit the id list;
     - each variant twice: vLLM prefix caching on, then off (`serve-cmd --no-prefix-caching`).
   - Why on and off: KV per configuration and TTFT depend on whether the shared prefix is stored once
     (`kv.configuration_kv_bytes`).
   - The GPU trace sidecar records KV-cache usage, peak memory and energy per shard.
   - Cost estimate before the addendum:
     - the dense network is 19 calls per item, about 7.6k calls per variant at 400 items;
     - V1-V4 reuse V0's 6 propose calls per item, so 13 new calls per item each;
     - the single-call gate (G0) reuses one propose call;
     - about 28k calls per caching setting, 56k with prefix caching on and off, at roughly 1.5k tokens each;
     - about an hour or two on an H200 by the testbed's throughput prior.
   - Run `python -m autoagentnet.testbed estimate` with the pilot's measured throughput before preregistering.
2. **Then, optionally, Haiku** (thinking off), on 50 BBEH items, only if Kevin raises the phase room.
   - Cost: the pilot's dense network costs about $0.0117 per item, so about $0.6 per variant per 50 items. V1-V4
     reuse V0's propose calls, so the five variants cost about $2.4 in all.
   - Run V0 and the variant the GPU result favours first.

## Power (say it before running)

The first draft's 2-point equivalence margin was not achievable, so the margin is now 7 points.

**Why 2 points fails** (audit M1-1). With about 20% of items discordant between two variants (the pilot's
single-versus-dense discordance), the paired difference's standard error at n items is about sqrt(0.2/n).

- A 2-point TOST at 80% power needs about 4,300 items.
- That is more than the 3,696-item BBEH pool.

**What 7 points needs.** Non-inferiority at delta = 7 points, one-sided, 80% power, with the true difference 0:

- At Holm's strictest level (0.05 / 4 = 0.0125 one-sided, z = 2.24): n ≈ 0.2 × (2.24 + 0.84)² / 0.07² ≈ 390.
- So n = 400.
- At n = 400 the standard error is about 2.2 points.

**Before fixing n.** Simulate with the pilot's measured discordance and accuracy, in the style of
`analysis/pruning_power.py`. If the testbed's discordance is higher than 20%, raise n, or the margin, before the
prereg.

**Context, latency and dollars.** These effects are large and mechanical, and are reported at any n.

## Code needed (not written in session M1)

1. **Network stage fields.**
   - `read: full | conclusion`: a fixed rule that passes upstream messages whole or cut to their last two
     paragraphs. It lives in `autoagentnet/network/`.
   - Fan-in already exists (`PruneConfig.fan_in`). A stage-level default in the network YAML would let V1-V4 be
     plain network files.
2. **A fake-model test** for `read: conclusion` (the cut is deterministic and the cache keys differ from full
   reading).
3. **A row in protocol section 8** (design library): "Compressed reading: `read: conclusion`. Agents read upstream
   conclusions only. Economic reading: cheaper and shorter contexts if the reasons are not where the value is."
4. **A testbed stage** `patching` in `autoagentnet/testbed/grid.py`, with the five networks and prefix caching
   on/off as its configs.
