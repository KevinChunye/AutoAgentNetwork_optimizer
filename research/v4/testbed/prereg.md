# Preregistration: open-weight testbed, "width, depth and verification" (T1–T5)

Written in session T1 on 2026-10-26, before any GPU run, and revised the same day after audit T1-1 (ADJUST; recorded
verbatim in `research/audit_log.md`). It is committed before the pilot.

- **Changes after the pilot** are dated addenda in section 9, committed before the first stage-1 sample, and only of
  two kinds: the pilot recalibration (section 5) and the scope (section 7). Nothing above section 9 changes after the
  pilot.
- **Layer** (protocol section 3): every quantity, test, threshold and item rule below is a *parameter*, fixed before
  data.
- **Code:** `autoagentnet/testbed/analysis.py` computes each test exactly as written here.
- **Power:** `research/v4/testbed/power.csv` (`python -m autoagentnet.testbed.power`).

## 1. Design (stage 1)

| Factor | Levels |
|---|---|
| Model | Qwen3.5 dense small series, Apache-2.0. 2B, 4B and 9B at pinned commits (`configs/testbed/models.yaml`; sources in `research/lit/ow_testbed_sources.md`). Hybrid Gated DeltaNet + gated attention; served text-only |
| Precision | BF16 (reference); W8 = round-to-nearest, symmetric, per output channel; W4 = AWQ group 128 (GPTQ group 128 if llm-compressor has no AWQ mapping for Qwen3.5; recorded as a deviation); W3 = GPTQ group 128 (dropped first under the cost rule, section 7) |
| Quantized layers | Full-attention and MLP projections. Embeddings, lm_head, the `linear_attn` (DeltaNet) blocks, norms and vision stay in BF16 (Red Hat's published Qwen3.5 recipe) |
| Quantization method | Fake quantization (quantize, then store in BF16): every precision runs on the same vLLM path. Calibration: 256 × 2048 tokens of ultrachat_200k, seed 0 |
| Thinking budget | Off, 1,024 and 4,096 tokens, with budget forcing: at the cap the end-of-thinking marker is appended and the model answers. Answer cap 2,048 tokens (with thinking off, all reasoning is in the answer) |
| Width | k = 6 samples per item per config. Sampling for every config: temperature 1.0, top-p 0.95, top-k 20, presence penalty 1.5 (the card's thinking row). Seeds: `grid.seed_of`, distinct per config and sample; the pilot uses its own seeds |
| Items | 363 (section 2) |
| Checkers | Self-check (the config re-reads samples 0–2). Judge: the 9B BF16 at 4k reads samples 0–3 of every config, and samples 0–1 of the W8 configs. White-box signals (mean log-prob, entropy, answer margin). Execution: code only, public tests in a sandbox; hidden tests are the grade |

There are 36 configs (27 without W3) × 363 items × 6 samples, plus checkers. Stage 2 (gpt-oss-20b, the W4 GPTQ
contrast, 16k math) and the real-kernel run are not preregistered here: each needs its own dated addendum and an
audit GO before it runs.

## 2. Items and their use

- **BBEH:** E5's four anchor tasks (linguini, nycc, word sorting, causal understanding), 50 items each: the 200 ids E5
  reserved for T1 (`research/v4/anchor/tasks.json` "t1_bbeh", taken from atlas_anchor @ 81da6e1; sha256 in
  `research/v4/anchor/sealed/MANIFEST.md`). They are disjoint from E5's 440 sealed anchor items and from every E5 scan
  list. E5 dropped two kinds of item before reserving: linguini "fill the blanks (1-N)" items with a one-blank gold,
  and word-sorting items whose first thought respells a list word.
  - Grading: the ANSWER line and the repo's bbeh grader (`autoagentnet/tasks.py`). E5's anchor uses a versioned
    parser v2 (a bare last line accepted; a qualifier after a dash, a semicolon or a trailing parenthetical stripped).
    A v2 regrade of T1's texts is exploratory, for comparison with the anchor only.
- **Math:** all 63 final-answer items of AIME 2026 and HMMT Feb 2026 (MathArena).
- **Code:** 100 of the 150 newest LiveCodeBench release_v6 problems (contests up to April 2025), in the same hash
  order. Correct means every hidden test passes.
- **T1–T4** use all 363 items: they fit nothing, and their rules are fixed here.
- **T5** fits on a 70% fit split and is scored once on the sealed 30% held-out split (109 items).
  - `seal.py` draws the split with a fresh random key before stage 1 and commits sha256 hashes of both lists.
  - `seal.heldout` logs the single read.
- Any analysis choice this file does not fix is made on the fit items only.
- The pilot's 50 items are among the 363. The pilot uses separate seeds, so stage 1's samples on them are fresh. The
  pilot reads only aggregate accuracy, cost and parse rates, and no T-quantity.

## 3. Shared definitions

Code: `analysis.py`, `compose.py`, `checkers.py`.

- **single:** the mean correctness of one sample. An unparsed answer is wrong.
- **k-vote:** the plurality answer of k samples, scored by expected credit.
  - The winning class scores the mean correctness of the composition's own samples in it. (For code, programs with
    the same public-test behaviour can differ on hidden tests.)
  - A tie scores the mean over the tied classes.
  - The score is averaged over all C(6, k) subsets of the drawn samples.
  - A 2-vote therefore equals one sample in expectation, so 2-sample arms are scored by a selector, never by a vote.
- **Answer classes:**
  - BBEH: the bbeh grader's normalization.
  - Math: math-verify equivalence.
  - Code: identical outputs on the public tests.
- **Terciles (T1–T3)** for an analysis at size s: items ranked by 1 − the mean correctness of every BF16 sample of the
  *other* sizes, cut into thirds, ties by item id.
- **Terciles (T4):** from samples that were never checker candidates (calls 4–5 of every config), cut within each
  benchmark family (BBEH, math, code).
- **Paired bootstrap:** resample items (seed 0). An item carries all its cells together. The interval is the
  2.5th–97.5th percentile (T4: 0.5th–99.5th, section 4). Draws: 1,000 for T1, 2,000 for T2–T4.
- **eta** (E5's atlas definition): (accuracy of the checker's pick − single accuracy of the candidates) /
  (coverage − single accuracy), summed over units. Coverage is the share with at least one right candidate.
- **Cost:**
  - `cost_tokens` = output + 0.1 × input tokens per call. Within one checkpoint, GPU time is about proportional to
    it, and it does not depend on which calls came from the cache.
  - Comparisons across precisions use real-kernel seconds: cost tokens / the kernel run's tokens per second.
  - Measured `gpu_seconds` is used only to measure throughput, from shards with no cached call.

## 4. Hypotheses, tests and decisions

"Supported" means the 95% interval lies on the predicted side of 0 (for T5, the stated criterion). Each primary is
computed once on the frozen data.

A test whose simulated power is below 0.70 is **exploratory** (Kevin's rule): it is reported but decides nothing.
Audit T1-1's stricter bar (power ≥ 0.80, false-positive rate ≤ 0.05, 95% half-width ≤ 3 points) is checked too.
Section 5 flags every test that misses it.

### T1. Does quantization error diversify?

- **Question:** do copies of a W4 model make errors that are their own (a fixed perturbation of the weights that
  every copy shares), or does W4 only lower every item's chance of success?
- **Primary (descriptive): the W4 deficit survives 6 votes on the hard third** (gap_persists).
  - Quantity: on the hard tercile, pooled over the 9 cells (3 sizes × 3 budgets), 6-vote(BF16) − 6-vote(W4).
  - Prediction: > 0, i.e. "k W4 copies do not recover BF16 accuracy on the hardest third", read at equal k.
  - What it does not show: it holds whenever W4 loses accuracy on hard items, whether or not the loss is shared by
    its copies (it was supported in the pure-shift world too; audit T1-2, finding 3). It says nothing about the
    mechanism; shared_shock below does.
  - Decision (narrow): if supported, the accuracy cost of W4 on hard items is not removed by voting at equal width.
    W4 is also cheaper per sample, so whether it is worth it is T2's question (equal memory) and T2's
    equal-GPU-seconds arm, not this one's. If not supported, at equal width W4 copies are not detectably behind on
    hard items.
  - Why primary: the shared-shock test has power 0.37 at the default world's shock (section 5). This was decided on
    simulation only, before any data.
- **Exploratory** (each reported with its interval, decides nothing alone):
  - *shared_shock:* S = 1 − r, averaged over cells, all items. r is the disattenuated error correlation:
    - the mean correlation of a W4 sample's and a BF16 sample's errors across items (different sample numbers);
    - divided by √(within-W4 × within-BF16 correlation).
    - Reading: S > 0 means copies of W4 share an error component BF16 lacks, i.e. quantization error does not
      diversify. A pure loss of ability, even one larger on hard items, leaves S ≈ 0 (finding 4).
    - If S > 0 with its interval above 0, the Atlas factor model is advised to treat each quantized checkpoint as its
      own family with a shared shock.
  - *concentration:* (single BF16 − single W4) on hard items minus on easy items. Above 0 means quantization lowers
    ability mainly on hard items.
  - *gap_change:* the hard-tercile precision gap at 6 votes minus at 1 sample. Below 0 means width narrows the gap.
  - *literal:* on hard items, 6-vote(W4) − single(BF16), the brief's literal comparison.
    - It counts only when the primary is supported. Otherwise it measures BF16's own vote gain (finding 3).
    - Prior: at 1–4 point W4 losses it is ≥ 0. Losses as large as Red Hat's 9B W4A16 AIME drop (85.4 → 68.8)
      could make it < 0.
- **Reported per cell, no test:**
  - correlations within W4, within BF16, across, and r;
  - 6-vote gains;
  - single accuracy on the hard and easy terciles for each precision.
  - The same rows are reported for W8 and W3 (exploratory).

### T2. Width vs precision at equal weight memory

- **Arms in each cell:**
  - 4 × W4: the 4-vote, and the judge's pick among the 4;
  - 2 × W8: the judge's pick among the 2, plus single W8 (the 2-vote equals it);
  - 1 × BF16.
- **Memory:** equal only nominally on the quantized layers (4 × 4 = 2 × 8 = 1 × 16 bits). The BF16 DeltaNet blocks
  and embeddings break exact equality. If the kernel run happens, its measured weight memory (vLLM's load log) is
  reported next to each row.
- **Primary.**
  - Quantity: D2 = 4-vote(W4) − single(BF16), pooled over cells, two-sided.
  - Prediction: D2 > 0, i.e. width wins at equal nominal memory.
  - Decision: if D2 > 0, a memory-bound deployment runs several W4 copies rather than one BF16; if D2 < 0, quantized
    width is a false economy; otherwise undecided.
- **At equal GPU-seconds** (exploratory, only with the kernel run): each precision's k-vote at the k whose
  real-kernel seconds come closest to one BF16 sample's (k ≤ 6; capped cells are flagged).

### T3. Depth vs width at equal cost

- **Comparison:** per size, BF16 only.
  - One sample at the deep budget is compared with a cost-matched vote at the shallow budget.
  - r = the ratio of their mean `cost_tokens` per sample. The wide arm is the mixture of the two neighbouring odd
    vote sizes k_lo ≤ r ≤ k_hi (from 1, 3, 5), weighted so the expected number of samples is r. Odd sizes only,
    because a 2-vote equals one sample and would bias T3 toward depth (audit T1-2, finding 4).
  - Pairs: (4096 vs 1024) and (1024 vs off).
  - A pair with r > 5 or r < 1 is "capped": it is reported but left out of the primary.
- **Primary.**
  - Quantity: D3 = deep single − cost-matched wide vote, pooled over the uncapped cells, two-sided.
  - Prediction: D3 > 0, i.e. thinking beats sampling at equal cost.
  - Decision: whether a fixed GPU budget should go to thinking tokens or to samples, by size.
- Per benchmark and per size: exploratory.

### T4. Verifier coupling

- **eta** per checker, per tercile (candidate-free terciles) and per number of right candidates m, pooled over configs.
  Checkers: self-check, the judge, white-box (margin, mean log-prob, entropy) and execution (code).
- **Primary.**
  - Quantity: for the judge, within each stratum (config × benchmark family × m = 1, 2, 3 right candidates out of
    4), eta(easy) − eta(hard). Strata are averaged with weights min(units easy, units hard).
  - Test: supported when the item-bootstrap **99%** interval lies above 0. The 99% level was set on the simulation
    before any data: at 95% the one-sided false-positive rates in the three null worlds were 0.03, 0.05 and 0.03
    (constant, config-dependent and benchmark-dependent judge), the config judge at twice the nominal 0.025; at 99%
    they are 0.00, 0.02 and 0.00 (the same 100 draws per null that informed the choice).
  - Limits:
    - At 99% the gap detectable with 80% power is about 0.17 eta points (0.14 at 95%), against a planted 0.28.
    - Within BBEH, "hard" largely means "hard sub-task". A judge whose skill varies by BBEH sub-task would read as
      coupling. The pricing decision below survives this; a claim about mechanism would not, and none is made.
  - Why stratify:
    - Within m: even a judge of constant skill has a higher eta when more candidates are right, and easy items have
      more right candidates (audit T1-1, finding 1).
    - Within config: easy units come mostly from weak configs and hard units from strong ones, and the judge's skill
      may depend on whose candidates it reads (audit T1-2, finding 2).
    - Within benchmark, for both the terciles and the strata: benchmarks differ in difficulty and the judge may
      differ by benchmark, so otherwise "hard" could mean "math" (audit T1-3, finding 1).
  - Prediction: > 0. The judge tells right from wrong less well on hard items (coupling), so selection buys least
    where it is most needed.
  - Decision: if supported, a checker's value must be priced per difficulty band, and cascades should not rely on the
    judge on the hardest third.
- The same gap for every other checker: exploratory.

### T5. Compositional prediction

- **Model** (`factor.py`):
  - logit P(item i right under config c) = alpha_c + beta_i + U_i · V_c, with rank 2 and ridge 1 on the config
    traits.
  - Wrong answers come from the item's pooled wrong-answer distribution; singletons are treated as unique.
- **Fit (no circularity, finding 2):**
  - alpha and V are fitted on the 70% fit items, all calls.
  - On the 109 held-out items, beta_i, U_i and the wrong-answer distribution come from **call 0 only**. The prior is
    empirical Bayes: the fit items' mean and spread of beta and U.
  - Every composition is then predicted by Monte Carlo (400 draws per item) and compared with its exact replay on
    **calls 1–5**, which the predictions never saw.
- **Compositions:**
  - k-votes, k = 1..5, of every config;
  - mixed-precision pairs at one size and budget (n = 2, 4, 6);
  - mixed-size pairs at one precision and budget;
  - cascades: a 3-vote of any config, escalating to one sample of the 9B BF16 4k when not unanimous (t = 1) or when
    fewer than 2 of 3 agree (t = 2/3).
- **Test (exploratory: power 0.65, section 5).**
  - Criterion: MAE(factor model) < 0.887 × MAE(baseline).
    - The baseline is the same model with the same unique-answer mass, but its shared wrong answers are spread evenly
      over the item's wrong classes seen at least twice. This adapts to each item's answer space (audit T1-2,
      finding 1).
    - The bar is the largest that keeps false positives at or below 0.05 in each misspecified world (10 and 5
      answer classes, 100 draws each; with 2 classes the baseline equals the model). It was set on the simulation
      before any data (section 5).
  - Decision: if supported, the Atlas can price compositions from single calls, including which wrong answers
    coincide, without running them. Otherwise, report which kinds fail and how far.
- **Reported, not tested:** the brief's "every composition within 3 points" and "≥ 90% within 3 points".
  - At this n they cannot be the test. Predicting with the synthetic world's *true* probabilities met the 90% bar in
    only 5 of 8 draws, with a mean absolute error of 1.5 points: the replay itself is that noisy. The fitted model
    met it in 0 of 40 (section 5).

### Multiplicity

- There are four confirmatory primaries (T1–T4; T5 is exploratory, section 5). T1–T3 are judged on their 95%
  intervals, T4 on its 99% interval.
- A primary that also holds with 98.75% intervals is called *robust* (Bonferroni for four tests at 0.05). T4's 99%
  is stricter than that, so a supported T4 is also robust.
- No primary is replaced or added after the freeze.

## 5. Power (simulation at the stage-1 design, 363 items, 36 configs)

Simulated on the synthetic world (`world.py`; worlds described in `power.py`) at the stage-1 design: 363 items, 36
configs, k = 6, 100 draws per world (T5 under the true model: 40 per answer-space size, since each takes about a
minute). Power is the share of alternative-world draws in which the test is supported; the false-positive rate is
the same share in a null world. The effect sizes are priors from the literature, not estimates:
- W4 costs 1–4 points, more on small models and hard items;
- the item-specific W4 shock has spread 0.3;
- T4's planted coupling gives an eta gap of about 0.28. The pilot cannot measure it (it has no judge); a smaller
  real gap lowers T4's power.

After the pilot, `power --calibrate` refits ability, thinking gain and W4 shift to the pilot's accuracies and reruns
this table (an addendum, before stage 1).

| test | role | world | draws | rate | mean estimate | mean half-width (T4: 99%; T5: MAE) |
|---|---|---|---|---|---|---|
| T1 primary: the W4 deficit survives 6 votes on the hard third | power | default | 100 | 0.94 | +0.046 | 0.027 |
| T1 primary: the W4 deficit survives 6 votes on the hard third | false positive | no_w4_loss | 100 | 0.04 | -0.000 | 0.026 |
| T1 secondary: shared W4 shock (1 - disattenuated r) > 0 | power | default | 100 | 0.37 | +0.019 | 0.022 |
| T1 secondary: shared W4 shock (1 - disattenuated r) > 0 | false positive | pure_shift | 100 | 0.01 | +0.000 | 0.021 |
| T1 secondary: shared W4 shock (1 - disattenuated r) > 0 | false positive | diversify | 100 | 0.03 | +0.000 | 0.022 |
| T1 secondary: W4 loss concentrated on the hard third | power | default | 100 | 0.34 | +0.015 | 0.019 |
| T1 secondary: W4 loss concentrated on the hard third | false positive | flat_shift | 100 | 0.05 | +0.003 | 0.018 |
| T1 literal: 6 x W4 vote < 1 x BF16, hard third (counts if gap persists) | power | strong | 100 | 1.00 | -0.107 | 0.023 |
| T1 literal: 6 x W4 vote < 1 x BF16, hard third (counts if gap persists) | false positive | default | 100 | 0.00 | +0.032 | 0.025 |
| T2 primary: 4 x W4 vote vs 1 x BF16 (two-sided) | power | default | 100 | 1.00 | +0.055 | 0.011 |
| T2 primary: 4 x W4 vote vs 1 x BF16 (two-sided) | false positive | no_w4_loss | 100 | 1.00 | +0.088 | 0.010 |
| T3 primary: deep single vs cost-matched wide vote (two-sided) | power | default | 100 | 1.00 | +0.057 | 0.009 |
| T4 primary: judge eta easy - hard within config, benchmark and right candidates > 0 (99%) | power | default | 100 | 1.00 | +0.276 | 0.123 |
| T4 primary: judge eta easy - hard within config, benchmark and right candidates > 0 (99%) | false positive | flat_judge | 100 | 0.00 | +0.001 | 0.071 |
| T4 primary: judge eta easy - hard within config, benchmark and right candidates > 0 (99%) | false positive | config_judge | 100 | 0.02 | -0.000 | 0.099 |
| T4 primary: judge eta easy - hard within config, benchmark and right candidates > 0 (99%) | false positive | bench_judge | 100 | 0.00 | +0.000 | 0.070 |
| T5 primary: factor MAE < bar x baseline MAE | power | default | 40 | 0.65 | +0.879 | 0.019 |
| T5 primary: factor MAE < bar x baseline MAE | false positive | misspecified | 100 | 0.00 | +0.938 | 0.025 |
| T5 primary: factor MAE < bar x baseline MAE | false positive | misspecified_k5 | 100 | 0.04 | +0.923 | 0.020 |
| T5 primary (5 answer classes) | power | default_k5 | 40 | 0.57 | +0.891 | 0.019 |

Reading against the rules. Kevin's: power ≥ 0.70 to be confirmatory. Audit T1-1's: power ≥ 0.80, false positives
≤ 0.05, 95% half-width ≤ 3 points.

| test | status | why |
|---|---|---|
| T1 primary: the W4 deficit survives 6 votes (hard third) | **confirmatory** (descriptive) | power 0.94, false positives 0.04, half-width 2.7 points; it does not identify the mechanism (section 4) |
| T1 shared shock | exploratory | power 0.37 at the default shock (0.99 in the strong world: spread 0.5 and a larger shift) |
| T1 concentration on the hard third | exploratory | power 0.34 |
| T1 literal | exploratory, counts only if the T1 primary holds | detects a large W4 loss (strong world: 1.00); no false positives in the default world |
| T2 primary | **confirmatory** | power 1.00, half-width 1.1 points. Its "no W4 loss" row is not a null: without a loss, 4 W4 copies beat 1 BF16 by their vote gain, which T2 correctly reports |
| T3 primary (odd-vote mixture) | **confirmatory** | power 1.00, half-width 0.9 points (no natural null world) |
| T4 primary (within config × benchmark × m, 99%) | **confirmatory** | power 1.00. False positives: 0.00 (constant judge), 0.02 (config-dependent judge), 0.00 (benchmark-dependent judge, benchmarks far apart in difficulty). 99% half-width 12 eta points, above the audit's 3, against a planted gap of 28 |
| T5 primary (MAE < 0.887 × baseline) | exploratory | power 0.65 (10 answer classes) and 0.58 (5), under 0.70. The bar 0.887 keeps false positives at 0.00 and 0.04 in the two misspecified worlds (100 draws each). With the answer-space-adapted baseline, the factor model's edge is small (mean ratio 0.88 under the true model, against 0.92–0.94 misspecified) |

T5 context: the brief's absolute criteria were met in no draw. "≥ 90% of compositions within 3 points" had a mean
share of 0.79 under the true model, and "every composition within 3 points" was never met. At 109 held-out items the
replay is too noisy for an absolute 3-point bar.

## 6. Deviations from the brief (decided before data)

1. **Items: 363, not 400.**
   - MathArena has no final-answer set after the models' release (2026-03-02). AIME 2026 (30) and HMMT Feb 2026 (33)
     are all there is, and both predate the release by days to weeks.
   - The 30-item pilot scan measures the 20–80% band; it no longer selects items.
2. **LiveCodeBench release_v6** is the newest release (to April 2025), before Qwen3.5's release. Contamination is
   possible, and the Qwen3.5 card reports LCB v6.
3. **Weight memory is not size × bits.** The DeltaNet blocks stay BF16 (section 1), so T2's equal memory is nominal.
4. **Sampling:** the card's thinking row is used for the non-thinking mode too, so sampling does not confound the
   budget axis.
5. **GPU.**
   - The brief's $4.50/h is Lightning's H200 price; the H100 is $5.45/h.
   - Under conservative priors, stage 1 with W3 does not fit $45 on any machine (H200 ~$48, H100 ~$62), hence the
     drop rule in section 7.
6. **T1's primary** is gap_persists (equal-width reading of the brief's hypothesis), not the brief's literal
   comparison (audit T1-1, finding 3). The mechanism test (shared shock) is exploratory for lack of power.
7. **T4 and T5** are redefined as in sections 4 and 5 (audit T1-1, findings 1 and 2).
8. **T5's 3-point criteria** are reported but not tested (section 4, T5), and T5 itself is exploratory: under 0.70
   power once its baseline adapts to each item's answer space (audit T1-2).

## 7. Cost rule for stage 1 (applied once, after the pilot)

1. `pilot-report` re-estimates stage 1 from the pilot's measured throughput, tokens per call and overhead (ledger
   hours / estimated pure hours, at least 1.5).
2. If the estimate is above $45, drop W3 (all sizes and budgets). If it is still above $45, also drop the
   real-kernel run. The judge step is never dropped (T4 and T2's judge arms need it; audit T1-2's direction).
3. If it is still above $55, stop and hand back to Kevin.
4. The result is committed in `configs/testbed/scope.yaml` with a line in `research/log.md`.
5. A dropped precision is not tested (T1–T5 do not depend on W3); T2's equal-GPU-seconds arm needs the kernel run.

## 8. Stop rules during stage 1

- **Steps:**
  - every step runs under the GPU ledger's guard (stage cap $55, total $90);
  - a step is interrupted at 1.5 × its estimate;
  - either stop ends the run until the auditor has looked.
- **Floor:** if BF16 accuracy on the hard tercile is below 10% for every size (read on the first size completed), T1's
  hard-third secondaries and T4's hard stratum cannot work. Report this and continue only on Kevin's call.

## 9. Addenda (dated, append-only)

(none)
