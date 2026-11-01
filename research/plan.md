# Plan v4: width, depth and verification

Living document (since session E5, 2026-10-26). Predictions and kill criteria are written **before** the run they
describe and committed; git history is the proof of order. `research/STEERING.md` overrides this file;
`docs/RESEARCH_PROTOCOL.md` (v2.1) is binding.

## Root question (Kevin's K1)

How should an agent system split a fixed budget between **width** (more agents or more samples of one agent),
**depth** (more reasoning tokens, or a stronger tier: the analogue of weight precision) and **verification**
(checking answers: self-check, a cross-model judge, execution)?

Terms, in plain words:
- *systematic failure share*: the part of failures shared by every system on an item (item difficulty), as a share
  of all variation on the logit scale. Width cannot fix it; only depth or a better selector can.
- *vote ceiling*: the accuracy of infinitely many repeats of one system (the share of items whose most common answer
  is right). *Selection ceiling*: the share of items at least one of k systems gets right (coverage@k).
- *selection efficiency eta*: (policy accuracy - best single accuracy) / (coverage - best single accuracy): how much
  of the gap to a perfect selector a label-free signal closes.

## Why: Phases 1-3 as the case study

On BBEH and ForecastBench, one Sol 6.1 call at reasoning low beat every panel and cascade we built from cheaper
calls (`research/v3/findings.md`). Two things limited width: the errors were mostly systematic, and label-free
aggregation misjudged the sources (Dawid-Skene put Sol at 62.5% against a true 97.3%). In simulation two things cause
that: correlated repeats outvoting one strong call, and a label space limited to the observed answers; only fixing
both removes inversions (research/v3/evidence/consensus_inversion.md; audit 68). Phase 1 cannot say which dominated
there, since BBEH answers have no fixed label space. One confound is
left open: Sol differs from Sonnet both in vendor and in reasoning (Sol reasons at "low"; Sonnet ran with thinking
off). The API anchor resolves it (AH1). Outline: `research/v3/paper_case_study.md`.

## Tracks

| track | what | money | where |
|---|---|---|---|
| Ledger | every Phase 1-3 finding with interval, n, status and caveat | $0 | `research/v3/findings.md` |
| Atlas | public per-item results (SWE-bench Verified, MathArena, LiveBench, our panels) in one response table; a factor model (ability, difficulty, failure beta, family shocks, call luck); A1-A7 | $0 | `autoagentnet/atlas/`, `research/v4/atlas/` |
| API anchor | the reasoning axis for both vendors on fresh items with headroom; cross-vendor judges; AH1-AH4 | Anthropic <= $48 (all calls by Oct 31), OpenAI <= $34 | `research/v4/anchor/`, configs `e51_*` |
| Testbed (T1) | open weights: precision, size, thinking budget, width and checkers on one GPU path; T1-T5 | Lightning GPU <= $100 | branch `ow_testbed`, `research/v4/testbed/` |
| Scale-up | Gemini credit (about $1k, sponsored), only after the paper's design is frozen (K6) | none planned | - |

## Anchor hypotheses (Holm over the tests that keep power >= 0.70: AH2 and AH3 after power.md; AH1 and AH4 are exploratory)

Arms are named by effort, not by a thinking budget: Claude 5.5 models reject budget_tokens, so "Haiku 4k" is Haiku at
effort low (ceiling 12,288) and "Haiku 16k" is Haiku at effort high (ceilings 18,432 on BBEH, 36,864 on math); Sonnet
the same way (audits 69-70). Ceilings are generous so that truncation is not part of an arm; arms are matched on
measured dollars.

- **AH1** reasoning explains the vendor gap: (Sonnet effort low - Sonnet off) / (Sol low - Sonnet off) > 0.5; void if
  Sol low - Sonnet off < 5 points.
- **AH2** depth beats width at equal dollars: one Haiku effort-low call beats the Haiku-off vote with the nearest
  dollars; the same for Luna low vs Luna none.
- **AH3** compositional prediction: the factor model, cross-fitted on single calls of each half of the items, predicts
  every 3-call arm's 3-vote accuracy on the other half; its error limits come from the noise floor a true model leaves
  at the anchor's size (audit 70; power.md), not from the first design's 3 and 5 points.
- **AH4** verifier coupling: the cross-vendor judge's selection efficiency is lower on hard items than on easy ones,
  with difficulty fitted from the arms outside the judged pools.

Full text, power and the sealed item lists: `research/v4/anchor/prereg.md` (written before the first anchor call).

## Order of work and decision points (session E5)

1. Patches 2.1-2.5, then one audit.
2. Landscape scan (K2, about $2): choose 4 BBEH tasks with Sol low < 90% and Haiku off > 15% ->
   `research/v4/anchor/tasks.json`; re-estimate costs from measured tokens.
3. Seal the anchor items; write the prereg with power; then Anthropic tier 1, tier 2 if K3 leaves room,
   verification; then OpenAI. One paid run at a time, an audit after each.
4. Ledger and Atlas in the gaps ($0). Freeze `research/v4/atlas/frozen_model.json` and the anchor predictions,
   audit, then read the anchor once per block.

## Status (2026-10-26, end of session E5)

Kevin's K1-K6 are recorded in `research/log.md`. Patches 2.1-2.5 are done and audited; the findings ledger
(`research/v3/findings.md`, F1-F18) and the Atlas (`research/v4/atlas/atlas.md`, frozen model) are written. The API
anchor ran in full except Astra (tier 2 OpenAI, left to Kevin): tier 1 for Haiku, Sonnet, Luna and Sol on 440 BBEH and
93 arXivMath items, Anthropic tier 2, and the four verification configs per vendor. Blocks 1 and 2 are read
(`research/v4/anchor/read.md`, frozen code, once each); block 3 (tier 2) is held until Kevin decides on Astra and its
writer is fixed blind (audits 95-96). Wording below is audit 96's.

- **AH2 (confirmatory, passes Holm at 5%, p = 0.001).** Raising a cheap model's reasoning one step beat repeating its
  no-reasoning call at the nearest measured dollars: Haiku effort low +3.7 points (1.3 to 6.2) over the Haiku-off
  2-vote, Luna low +10.7 (7.1 to 14.2) over the Luna-none 3-vote. For Haiku the 2-vote equals one call in expectation,
  so this shows effort low beats effort off at about 1.2x the dollars, not that depth beats a wider vote; against the
  3-vote, +1.8 (-0.7 to 4.3), not tested. P1 (+8) missed. The budget rule (first effort step before width for cheap
  models) covers these items only, not higher effort steps or other tasks.
- **AH3 (confirmatory, passes).** The factor model predicted the six 3-call arms' 3-vote accuracy with mean absolute
  error 0.8 points (largest 1.5; upper bound 2.4) and their gain over one call with 0.7 (upper 1.3). Gains were small,
  and a zero-gain predictor also meets the limits (auditor post-read), so this shows accuracy when vote gains are
  small, not that the model captures composition; it missed Sol low's math gain (+7.9 observed, +0.4 predicted). The
  Atlas may price same-arm votes of up to 3 calls; mixed panels stay untested.
- **Exploratory:** AH1 (R = 0.02, -0.32 to 0.26; the vendor-versus-reasoning confound stays open), AH4 (Sol judge eta
  0.85 easy vs 0.14 hard), width (a 3-vote adds at most 2.6 points on BBEH; one Sol low call beats every cheaper arm
  and vote), verification (the Sol judge beats the best cheap pool arm by 13.3 on BBEH but is 8.3 below one Sol low
  call at 1.6x the dollars), label-free (pooled Dawid-Skene put Sonnet at 0.79 against a true 0.45).
- **Next ($0 first):** on the Atlas's public repeated-run data, test the vote rule against the zero-gain predictor with
  abstentions as non-votes; then test AH2 across task families on T1's open-weight testbed before any new API spend.
  Any later judge test includes the judge model's own answer at matched dollars.

---

# Archive: pilot plan v2 and earlier statuses (superseded by v4)

Living document. Predictions and kill criteria are written here **before** the run they describe and committed; git history is the proof of order. `research/STEERING.md` overrides this file.

## Root question

**Protocol v2 (since session 2).** Where does a multi-agent LLM pipeline's accuracy come from, and how should a fixed budget of agent calls be allocated across stages (static allocation) and across tasks (dynamic allocation), with cost in cache-aware dollars? Session 1's root question (can an AMC-style controller learn per-stage keep ratios that match dense accuracy at a fraction of the cost) is in git history; it is now part of H1 and H2.

The pilot does not test H1 to H6. It estimates effect sizes with intervals, checks that the setup *can* test them, measures what a full study would cost, and gives Kevin the evidence to decide whether to scale up. Budget: at most $20 (governor stops at about $17.40 of estimated spend).

Hypotheses (pre-registered, protocol v2 section 1):
- **H1** joint search over per-stage keep levels beats stage-by-stage sensitivity analysis at matched cost.
- **H2** stages differ in accuracy gained per dollar (production function).
- **H3** the label-free reward (agreement with dense) lands near the labeled reward (pilot: estimate the gap and its CI only).
- **H4** every gain survives matched random pruning, the single agent, a free vote over the six proposers and one Sonnet 5.5 call at roughly matched cost.
- **H5** a consensus policy reaches dense accuracy at no more than half its cost (pilot margin: amendment 4, rule 24).
- **H6** the propose stage's effective team size is at most 3.

Terms used below:
- *single*: one Haiku 5.5 call per task (`configs/networks/single.yaml`).
- *dense*: the 3x6+1 network, 19 calls per task (`configs/networks/dense_3x6.yaml`).
- *gap*: dense accuracy minus single accuracy on the same tasks (paired), in percentage points.
- *config*: a keep vector `[k_propose, k_critique, k_refine, 1]`; the v2 grid keeps 1, 3 or 6 agents per stage (27 configs, 105 distinct calls per task).
- *vote6*: the plurality answer of the dense run's six proposers (no extra call).

## Status (2026-10-22, end of session E4)

The pilot below is closed, and its root question was carried into the evidence plan (`research/v3/evidence/plan.md`)
and Phase 3C (`research/v3/pruning/`). Lifetime spend is $26.56 (Anthropic $22.05, OpenAI $4.50). After session E4:
- On both benchmarks, a dense panel did not beat the best single call. One Sol 6.1 call scores 97.3% on BBEH at
  0.45x Sonnet's dollars, and it ties the best forecaster on ForecastBench (Brier 0.128).
- Cheap compression on forecasting (four cheap calls in place of Sol) was not supported by its preregistered lockbox
  read: inconclusive, point estimate +0.0061 Brier behind Sol at 0.26x its dollars (power about 0.56). That track ended
  as pre-logged.
- Phase 2 is all exploratory, and none of it changes direction (Kevin's no-p-hacking rule).
- No paid work is planned. Next is a $0 write-up of Phases 1-3 from the committed reads. The November Phase 4 budget
  (`research/v3/pruning/phase4_plan.md`) waits for Kevin, with the recommendation not to approve it as written. Any
  new question needs a fresh prereg, Sol as the comparator and new sealed items.
Details: `research/log.md` (session E4 entries) and `research/audit_log.md` (audits 51-67).

## Status (2026-10-18, end of session 2; superseded)

**Blocked on keys.** Neither session 1 nor session 2 had `AAN_ANTHROPIC_API_KEY` or `AAN_OPENAI_API_KEY`, so no paid step has run; spend is $0.00. Every paid config is pre-registered, estimated, dry-run and cleared by `aan check`. Anthropic credit expires on 2026-11-01 (STEERING), so the paid steps should run in the first session started with the keys set.

## Steps

Allocation from protocol v2, section 6; worst case from `research/estimates.csv` (x1.15, cache ignored).

| Step | Allocation | Worst case | State | What |
|---|---|---|---|---|
| P0 calibration | $0.10 | $0.10 | free part done; live part needs keys | 5 calls per model ref (3 Haiku variants, `sonnet_nothink`, `luna_low`, `gpt_small`); dense on 2 items; rate limits |
| P1 literature | $0 | $0 | done | novelty re-scoped; 3 gate candidates; prices verified (incl. Sonnet 5.5) |
| P2 gate probes | $0.50 | $0.51 | ready; needs keys | banding on 3 candidates; single vs dense on 20 calibration items |
| P3 gate confirm | $1.60 | $1.84 (+ P3w $0.37) | ready; needs keys | futility check at 40 items, then 0-59; single Sonnet on 20-59; noise on 20-29; P3w on 100-119 if triggered |
| P4 factorial grid | about $6 | $6.48 | ready; needs keys | 27 configs on 20-59 (search) and 60-99 (held out), parts a-h; single on 60-99 |
| P4b designs | under $1 | $1.01 | ready; needs keys | vote6, consensus policies, equimarginal path offline; `judge_cascade` live on 60-99 |
| P5 transfer smoke | $0.46 | $0.54 | conditional (amendment 4, rule 26) | dense + 3 picks on `luna_low`, 60-69 |
| reserve | $2.00 | | | reruns, replicates |

### P0 calibration: prediction and kill criterion (written 2026-10-18, before any live call)

Plan: `configs/experiments/pilot/p0_calib_*.yaml`, the single-agent network on calibration items 0-4 of `omni_d44_61` (amended after audit 1: the configs pointed at a file that no longer existed), once per model ref: `haiku` (API defaults: adaptive thinking, effort medium), `haiku_nothink` (`thinking: disabled`), `haiku_low` (effort low), and `gpt_small` only after its price is confirmed. Plus one dense run on 2 tasks with the chosen Haiku ref to see stop reasons at max_tokens 300 to 800. Worst case well under $0.50.

Prediction:
- With API defaults, `output_tokens` exceeds the visible text's token estimate by more than 1.5x on at least 3 of 5 calls (hidden thinking), and at least 1 of 5 single-agent calls (max_tokens 800) ends with `max_tokens`.
- With `thinking: disabled`, output tokens are within 1.3x of the visible estimate and no call is truncated.
- Actual input tokens are 1.0x to 1.4x `estimate_tokens` (newer tokenizer).
- Single-agent latency 2 to 15 s per call.

Kill / decision:
- Any model whose official price is unverified or above `configs/pricing.yaml`: no paid use (OpenAI until confirmed).
- If default thinking truncates more than 5% of calls or more than doubles output tokens, the network uses `haiku_nothink` (or `haiku_low` if disabled thinking is rejected), and the choice is recorded here before P2. max_tokens stays the cost ceiling.
- Actual cost of P0 above 1.5x its estimate: stop paid work and audit (protocol rule 7).

**P0 result and Haiku ref (session 4, 2026-10-19).** Worker ref: **`haiku_nothink`**. Truncations at max_tokens 800 in 5 calls: `haiku` 3 (two with no visible text: thinking used the whole budget), `haiku_low` 2, `haiku_nothink` 1 (a long visible derivation that ran out of room), `sonnet_nothink` 0. The `p0_calib` decision reads "haiku_nothink unless it truncates or is rejected, then haiku_low". `haiku_nothink` truncated once, but the fallback truncates more and writes more tokens per call, so it would fail the same test worse. `haiku_nothink` is kept as the least-truncating Haiku ref. P0 dense (38 calls) and the 5% truncation stop of every later run are the real check. Sonnet 5.5 rejects `thinking: disabled` (HTTP 400), so `sonnet_nothink` sends `thinking: between_tools`, which the API names as its thinking-off setting (commit 7ea4aef).

### P1 literature: kill criterion

A prior paper already learns per-stage keep ratios with a cost-aware reward: re-scope before spending (protocol section 5).

### P2 to P5: predictions and kill criteria (written 2026-10-18, before any paid call)

Configs: `configs/experiments/pilot/`, generated by `scripts/make_pilot_configs.py --candidate <file> --short <name> --ref <P0 choice>`. Task files: `scripts/prepare_tasks.py` (commands in `research/data_cards.md`). Worst cases (x1.15, cache ignored) are in `research/estimates.csv`.

**Gate candidates** (P1, `research/lit/gate_tasks.md`), in priority order:
1. `omni_d44_61`: Omni-MATH, difficulty 4.4 to 6.1, math-verify grader.
2. `bbeh_band`: BIG-Bench Extra Hard, 12 tasks with short gradable answers, `bbeh` grader; final task subset from banding.
3. `aime_p3_9`: AIME 1998-2024, problems 3 to 9, integer exact match.
Reserve: SuperGPQA calculation subset (letter grading).

**P2a banding** (single agent only, on each candidate's banding pool, never in any split). Worst case $0.14 for all three.
- Band rule, fixed now. Omni and AIME: keep the window if single accuracy on the pool is in [0.30, 0.50]. Above 0.50: move up once (Omni difficulty [6.1, 7.8); AIME problems 7 to 12). Below 0.30: move down once (Omni [3.55, 4.4); AIME problems 1 to 5). Still outside [0.25, 0.60] after one move: drop the candidate. BBEH: keep up to 4 tasks whose pool accuracy is in [0.20, 0.70] (about 10 items each), preferring computational tasks; fewer than 2 such tasks: drop BBEH.
- The window is chosen from single-agent data only, never from the dense-minus-single gap (winner's curse).
- Prediction: Omni [4.4, 6.1) lands at 30 to 55% with thinking off; AIME 3 to 9 at 35 to 65% (contamination can inflate it); at least 3 BBEH tasks fall in [0.20, 0.70].

**P2b gate probes** (calibration items 0-19, single and dense). Worst case about $0.32 per candidate (Omni); at most 2 candidates (Omni first, then whichever of BBEH and AIME banded closest to 40%).
- Prediction: on Omni, dense minus single is +5 to +15 points on 20 items; voting check (majority of the 6 propose answers minus mean propose accuracy) is at least 3 points.
- Kill: single outside 30 to 60%, or dense minus single under 5 points, on every probed candidate: STOP and report alternatives (weaker model, other task family, different topology). If the voting check is under 3 points and the gap under 10, skip P3 for that candidate (the critique/refine stages would have to supply the gain alone, which prior work makes unlikely).

**P3 gate confirm** (best candidate; items 0-59; the gate is judged on validation 20-59 only, 40 fresh items). Worst case $1.25.
- Prediction: gap at least 5 points as a point estimate; 95% paired-bootstrap CI about ±13 points (it will include 0 if the gap is under ~13). Dense final answers agree between replicates on at least 70% of the 10 noise items.
- Kill: point estimate under 5 points: STOP (premise fails at pilot scale), report.

**P4 mini-landscape** (216 configs, validation 20-39, four 5-task runs; a+b search half, c+d held-out half). Worst case $6.33 total, $1.59 per run.
- Predictions: (1) dense error within the P3 estimate ±15 points (early-stop block enforces a wider range); (2) (amended after audit 1: the original was a best-of-216 statement) the labeled joint pick, chosen on the search half, has held-out error within 5 points of the dense network's held-out error at no more than half its cost; (3) propose has the largest main effect, critique the smallest; (4) the interaction residual is not distinguishable from noise at 20 tasks (the pilot cannot resolve H1); (5) joint and sensitivity picks are within ±5 held-out reward points; (6) pick minus matched-cost random pruning has a CI that includes 0; (7) within-stage pairwise agreement 0.4 to 0.8 in propose and above 0.8 in critique and refine.
- Kill: dense error outside the gate range ±15 points, or cost per task above 1.5x estimate: stop and audit.

**P5 transfer smoke** (gpt_small, dense + 3 pruned configs, validation 30-39, the P4 held-out half; amended after audit 1, it was 20-29). Worst case $0.46. The three configs are placeholders until P4 picks them (joint pick, sensitivity pick, best uniform).
- Prediction: `gpt-6-luna` dense cost per task within 2x Haiku's actual; output tokens at most 2x visible tokens.
- Kill: hidden reasoning above 2x, a price or model-ID surprise from `aan models gpt_small`: stop OpenAI work.

**Budget check:** total worst case for P0 + P2 (3 bandings, 2 probes) + P3 + P4 + P5 is about $9.7, plus $0.94 if the gate widening P3w runs (amendment 1), against the governor's stop near $17.40.

### Amendment 1 (2026-10-18, after audit 1, before any paid call)

Rules the audit found open (finding 5) or missing (findings 4, 7, 9). They bind the next session.

1. **Order of gate probes.** Probe Omni first. Probe a second candidate only if Omni fails P2 (or banding drops it). The second is whichever of BBEH and AIME banded closest to 40% single accuracy (tie: BBEH, lower contamination); a third only if the second also fails. At most 3 probes (protocol).
2. **Which candidate goes to P3.** Among probed candidates that pass P2 (single in [30, 60]% and gap ≥ 5 points), the one with the largest gap. Within 2 points, the one with the larger voting-check gain; still tied, priority order.
3. **Band move that overshoots.** If one move crosses the band (for example above 50% → moved up → below 30%), use whichever of the two windows has banding accuracy closer to 40%, if it lies in [25, 60]%; otherwise drop the candidate. Never a second move.
4. **P3 judged items, in code.** `analysis/gate.py` judges P3 on positions 20-59 only (finding 4).
5. **Gate widening (P3w, worst case $0.94).** Run `p3w_<cand>_single/dense` (validation 60-119) if P3's gap is ≥ 5 points but its 95% CI includes 0, or if the vote over the 6 propose answers is within 2 points of dense accuracy (or above it). The gate is then judged on positions 20-119.
6. **Go to P4 only if** the judged gap (P3, or P3 + P3w) is ≥ 5 points and dense accuracy exceeds the propose vote. If the vote matches or beats dense, the critique and refine stages add nothing on this task. Report that as the main finding and do not spend the $6.33.
7. **P4 run size from measured limits (finding 7).** P0's `status.json` holds the account's rate limits. Expected minutes per P4 part = max(calls ÷ requests per minute, expected output tokens ÷ output tokens per minute). Expected output tokens use P0's measured mean output tokens per call, by stage, from the dense run. Use the smallest `--p4-parts` in {4, 10, 20} that keeps each part ≤ 20 minutes; `--p4-concurrency 16`, or 8 if the request limit is under 300 per minute. If 20 parts still exceed 20 minutes each, stop and ask Kevin (Batch API or a higher tier).
8. **P4 cost check.** After part a, compare its ledger spend with its estimate. Above 1.5× the estimate, stop and audit (protocol rule 7). The dense-error kill is checked on P3's data before P4: P4's dense calls come from the P3 cache.
9. **Contamination probe (free).** Report single and dense accuracy separately for HMMT and other sources on the judged items (85% of the Omni window is HMMT). A single-agent gap of more than 20 points in favour of HMMT is flagged as likely recall; it is not a kill.
10. **P5 on held-out tasks** (validation 30-39), so its picks were not selected on the tasks it runs (finding 9).

### Amendment 2 (2026-10-18, after audit 2, before any paid call)

11. **P4 go/no-go against voting (replaces rule 6).** P4 runs only if, on the judged items (P3, or P3 + P3w), both hold: (a) dense minus single is at least 5 points; (b) dense minus the majority vote over the 6 propose answers is at least 5 points. Report the paired 95% CI for each (`analysis/gate.py`: `gap`, `dense_minus_vote6`). If (b) fails, the finding is "voting explains the gap". Report it and save the $6.32. A one-item margin (2.5 points at n=40) no longer qualifies.
12. **P3w trigger (replaces rule 5).** Run the gate widening if P3's gap is at least 5 points but either CI (gap, or dense minus vote) includes 0, or if dense minus vote is between 0 and 5 points.
13. **Confirmation after P4 (replaces Option B's use of the test slice).** Score the P4 picks on fresh validation items 60-119. The dense and single calls there are already cached by P3w, so only the pruned configs cost money ($0.82 worst case for 6 picks; `reports/pilot/tables/scaleup_costs.csv`). The test slice (120-319) stays untouched for the full study.
14. **Contamination probe: limited power.** The judged items hold only about 6 non-HMMT items (18 with P3w), so the by-source table is reported for transparency and cannot show recall either way.
15. **Grader-format check.** A math answer that does not parse as LaTeX counts as unparsed, so the existing `max_unparsed_rate: 0.10` early stop also catches format trouble (audit 2, finding 1).

**Question for Kevin** (protocol-level, so not changed here). Protocol section 5's P2 kill (gap under 5 points on 20 items, on every candidate) rejects a true 10-point gap about one time in three. Should a P2 miss with a non-negative gap go to P3, which has 40 fresh items, instead of STOP? Until Kevin answers, the protocol rule stands. Rule 1 (up to 3 probes) lowers the chance of a false STOP.

### Amendment 3 (2026-10-18, session 2, protocol v2; before any paid call)

Protocol v2 (merged from `pilot_v2_design`, approved by Kevin) reframes the question: where does the pipeline's accuracy come from, and how should a budget of calls be spent across stages and tasks (H1–H6, protocol section 1). Haiku 5.5 is the only worker. Sonnet 5.5 (`sonnet_nothink`) appears only as the P3 matched-cost control and the `judge_cascade` judge. GPT-6 Luna (`luna_low`) appears only in P5. Rules added or replaced:

16. **Preregistration in the file.** Every paid config carries a `prereg:` block copied verbatim, by `scripts/make_pilot_configs.py`, from the YAML block below. Each config is committed and passes `aan check` before it runs. Changing a block means a new commit before the run.
17. **P0 adds** `sonnet_nothink` (for the P3 control and the cascade judge) and `luna_low` (for P5). Input-token predictions are judged against `estimated_prompt_tokens x 3/4`, because `estimate_tokens` now uses 3 characters per token.
18. **P3 adds** `p3_<cand>_single_sonnet`, one Sonnet call per task on validation 20-59, the "one senior" control at roughly matched cost. If it reaches dense accuracy or better (point estimate) on the judged items, stop before P4 and hand back with that as the headline control (H4). If it is below dense by less than 5 points, P4 runs when rule 11 passes and the report leads with the senior control; if it is below dense by 5 points or more, rule 11 alone decides. No case is left to judgement (audit 3).
19. **P3 futility (v2).** Run P3 single and dense first with `--task-limit 40` (calibration 0-19 from cache plus validation 20-39). If the upper end of the 95% paired-bootstrap CI of dense minus single on validation 20-39 is below +5 points (`analysis/gate.py`, column `futile`), STOP. Otherwise run the full configs (0-59).
20. **P4 is a factorial grid** (replaces amendment 1, rule 7's 216-config parts, and rule 13). `configs: {levels: [1, 3, 6]}` gives 27 configs and 105 calls per task, on validation 20-59 (search half) and 60-99 (held-out half). It runs as parts `p4_<cand>_grid_a..h` of 10 items each, worst case $0.81 per part and $6.46 in total. The part size can be changed with `--p4-part-size` from P0's rate limits (rule 7 arithmetic). The held-out half replaces rule 13's separate confirmation; the test slice stays untouched. The go/no-go of rule 11 still applies. Rule 13's claim that P3w caches dense on 60-99 no longer holds (rule 23 moves P3w to 100-119), so the held-out parts pay for their dense calls; the estimates ignore the cache anyway, so the worst case is unchanged.
21. **P4b.** `vote6`, the consensus policies (m, theta) and the equimarginal path are scored offline from P4's calls (`analysis/economics.py`). `gated_3x6` is the consensus policy m=6, theta=5/6, fallback dense, so it is also offline. `judge_cascade` runs live on the held-out half (validation 60-99): its proposers are the dense run's cached calls, so it pays only for aggregators. Its escalation ref is `sonnet_nothink`, a parameter set in session 2 so that both Sonnet roles use the P0-calibrated ref. The single Haiku agent also runs on 60-99 (`p4_<cand>_single_held`, about $0.02), so every held-out pick and design has its H4 control on the same items. Scoreboard: `research/designs.md`.
22. **P5 on `luna_low`**, held-out items 60-69, after P4's picks replace the placeholders.
23. **P3w on validation 100-119 (replaces the range of rules 5 and 12; audit 3).** Widening on 60-119 would put the P4 held-out half (60-99) into the gate decision that sends P4 forward, so the held-out half would no longer be untouched. P3w now runs single and dense on 100-119, and the gate is then judged on 20-59 + 100-119 (60 items; `analysis/gate.py`, `JUDGED_POSITIONS`).

### Amendment 4 (2026-10-18, session 2, after audit 4; before any paid call)

Audit 4 found the scale-up triggers too loose for n = 40 (the MDE is about 20 points) and open to multiple comparisons across about 8 designs. Rules added:

24. **H5 margin.** A design "matches dense" when its held-out accuracy minus dense's is at least −3 points (point estimate) and its cost per task is at most 50% of dense's, on the held-out half 60-99. The 95% paired CI is reported next to it. This replaces "within dense's 95% CI", which at n = 40 accepts a design about 15 points worse. At this n it is a screening rule, not a test; option B is the test.
25. **One pre-chosen design per trigger.** Each design is chosen on the search half and scored once on the held-out half. Every other scoreboard row is descriptive and triggers nothing.
    - H5 trigger: the "best consensus policy" of `analysis/designs.py`, the distinct (m, theta, fallback) policy with the highest search-half reward. It must meet rule 24.
    - Static-pruning trigger (H1/H4): the joint pick (exhaustive, labeled reward, search half). Its held-out accuracy must be at least vote6's, and its held-out reward above the matched-cost random control's mean (`p4_random_control`), as point estimates with CIs reported.
    - Senior trigger (H4): rule 18 (single Sonnet within 5 points of dense on P3).
    - `judge_cascade` is a descriptive row.

    A trigger makes option B a candidate for Kevin's decision; nothing scales up without his approval.
26. **P5 is conditional.** It runs only if P4 ran (it needs P4's picks) and P0's `luna_low` calibration passed its kill rule. It is reported as feasibility only: 10 items cannot order the picks.
27. **Consensus thresholds.** Policies use theta in {0, 1/2, 2/3, 5/6, 1} and are scored only when they need different numbers of agreeing proposers. theta = 0.67 would have excluded 4 of 6 (0.6667 < 0.67). `gated_3x6` is m = 6, theta = 5/6.
28. **Grader and data.**
    - A trailing unit after a number (`\text{ days}`, "30 degrees") is dropped before the prose check.
    - Thousands separators are removed only when the whole answer is one number, so "(2,100)" stays a tuple.
    - Yes/no golds written as `\text{No}`, and alternatives in any case ("OR"), are dropped. This removed 31 Omni golds, none in calibration or validation, whose hashes are unchanged. The test-slice hash changes, which affects only options B and C.

### Amendment 5 (2026-10-18, session 3; Kevin's answer to the amendment 1 question; before any paid call)

29. **P2 is a screen, P3 is the gate.** Kevin's answer (`research/STEERING.md`, 2026-10-18): a P2 miss with a gap of zero or more goes to P3 and does not STOP. P3 has 40 fresh items, with the futility rule on its first 20. A negative P2 gap still STOPs. This replaces the protocol's P2 kill on the gap (under 5 points). In amendment rules 1 and 2, a candidate now passes P2 with single in 30 to 60% and a gap of 0 points or more, and fails it otherwise. The single-agent band (30 to 60%) still applies. Only the `p2_probe` prereg changes, so only `p2_<cand>_single` and `p2_<cand>_dense` are regenerated.
    - It also replaces the older P2 rule above ("if the voting check is under 3 points and the gap under 10, skip P3 for that candidate"). A candidate with single in band and a gap of 0 or more goes to P3, whatever its voting check. P3 measures dense minus vote6 anyway (rule 11), on fresh items.
    - Protocol v2 section 6 still lists a P2 gap of at least 5 points. Kevin's answer is the more specific and the later instruction, so it governs this pilot (STEERING overrides the plan) (audit 5).

### Amendment 6 (2026-10-19, session 4; after the P0 dense kill and audit 6; Kevin's decision)

30. **New token caps (Kevin, STEERING 2026-10-19).** The Haiku and Sonnet 5.5 tokenizer gives about 2.1 to 2.4 characters per token on this math text, against the roughly 4 the caps assumed. At the old caps the P0 dense run truncated 11 of 12 critiques (500 tokens), 1 of 2 aggregators (300) and 1 of 12 proposers (800), so the P0 dense kill was met. Kevin chose option A2. Every max_tokens doubles: propose, refine, `single` and `single_sonnet` go from 800 to 1600, and critique from 500 to 1000. The aggregate cap equals refine's (300 to 1600), because the aggregator re-derives the solution (audit 6). The same caps apply to `gated_3x6`, `judge_cascade`, `vote6` and `mixed_vote6`, so their proposers stay identical to dense's and come from the cache. max_tokens remains the cost ceiling; unused tokens cost nothing.
31. **Per-stage truncation stop (audit 6, finding 3).** `expect.max_truncation_rate` (5%) now also applies within each stage of the dense network, not only to the pooled rate, which hid one aggregator in 19 calls. Fake-provider test: `test_one_truncating_stage_stops_the_run`.
32. **P0 dense rerun.** `p0_dense_haiku_nothink` reruns on calibration 0-1 at the new caps; every call is new because max_tokens is part of the cache key. It is a smoke test: zero truncations in 12 calls still allows a true rate up to about 26%. The real check is P2b dense on 20 items with the per-stage stop. P0 calibration is not rerun: it measured the ref, not the caps.
33. **Budget restated** (`aan estimate`, worst case x1.15, cache ignored): P2 $0.99, P3 $3.67, P3w $0.73, P4 $13.95, P4b $2.46. That sums to $21.80, against $10.20 at the old caps. The sum of worst cases exceeds the $20 phase cap, but each run is gated on its own worst case against what is left after actual spend. P0 dense spent 0.42x its worst case, so the projected actual is about $9 to $10. If the phase cap would stop a step, the steps run in plan order and the report says which step was not reached.
34. **P0 predictions that failed** (recorded, no decision changes): prompt tokens were 1.75x `estimated_prompt_tokens x 3/4` (predicted 1.0 to 1.4x); `haiku_nothink` truncated 1 of 5 (predicted none); its output-to-visible ratio was about 2.0 (predicted at most 1.3), from the tokenizer and not from thinking. Protocol section 5, item 7 ("the worst case errs high") holds for output, which is bounded by max_tokens, but not for prompts.

35. **Critique cap 1600 (Kevin, STEERING 2026-10-19, later).** The P0 dense rerun at the rule 30 caps (`p0_dense_haiku_nothink`, $0.0152) truncated 0 of 12 proposers, 0 of 12 refiners and 0 of 2 aggregators, but 1 of 12 critiques at 1000 tokens (8%, above the 5% stage kill). On the harder task, critiques ran 692 to 1000 tokens (mean 69% of the cap; predicted under 60%). Dense answered both tasks correctly. Every stage's cap is now 1600 (`dense_3x6`, `gated_3x6`). Worst case for P2 to P4b (x1.15, cache ignored): $24.70, with each run still gated against what is left of the $20. The rerun spent 0.25x its worst case, so the projected actual is about $6. P0 dense runs once more at these caps.

36. **Run caps (session parameter, not Kevin's decision).** Under the rule 30 and 35 caps, `max_usd` rises to $3 for `p3_<cand>_dense`, $1 for `p3_<cand>_noise` and $3 for `p4b_<cand>_judge_cascade`, so each run's worst case fits its own cap. All stay at or under the $4 phase run cap (bf972e4; audit 7, finding 4).
37. **What a truncation stop means (audit 7).** A run that stops on `max_truncation_rate` (pooled or per stage) is not retried at a higher cap. The session logs it and asks Kevin; no cap changes without him.
38. **AIME and BBEH banding deferred (audit 7).** Amendment rule 1 uses a second candidate only if Omni fails P2 or banding drops it. Until then those banding runs change no decision, so they wait.

39. **Uniform 3200 cap (Kevin, STEERING 2026-10-19, third).** `p2_omni_band_single` at 1600 stopped after its first 10 items (rule 37). 2 single calls were cut off mid-derivation (2,343 and 2,915 characters, hard geometry, no answer); the other 8 finished and were all correct. At 1600 the cap, not the model, would decide about a fifth of hard items, which confounds dense against single. Every stage's max_tokens is now 3200 in every network.
    - A refiner's prompt stays under about 40,000 tokens (task + 6 x 3200 + 6 x 3200), below Haiku's 100,000-token long-prompt tier.
    - Worst case P2 to P4b (x1.15, cache ignored): $49.03. Each run is gated alone against the $4 run cap and what is left of the $20. P0's runs spent 0.14 to 0.42x their worst case, so the projected actual is about $7 to $9.
    - Run caps (session parameter, as rule 36): p2 dense $2.5, p3 dense $4, p3 single Sonnet $2, p3w dense $2.5, p3 noise $2, p4b cascade $4.
    - Runs whose worst case exceeds $4 are split with `--task-offset/--task-limit`, the same configs and preregs: P3 dense as 0-39 (the futility step of rule 19) and then 40-59; `p4b_<cand>_judge_cascade` as 60-79 and then 80-99. A P4 part (10 items) has a worst case of $3.99 and is not split.
    - Omni banding reruns from item 0: max_tokens is in the cache key, so no call at 1600 is reused. P0 dense is not rerun; P2b dense (20 items, per-stage stop) is the check. A further truncation stop goes to Kevin (rule 37).

40. **Band move path for Omni (audit 8; written before the banding result).** The band rule (P2a, amendment rule 3) is applied unchanged to all 117 items of `omni_d44_61_banding`.
    - Above 50%: move up once to `omni_d61_78` (difficulty [6.1, 7.8); 232 items plus a 25-item banding pool; test slice 112 items; data card in `research/data_cards.md`; about 6% HMMT against 85% now).
    - Below 30%: move down once to `omni_d355_44` (difficulty [3.55, 4.4)), built and given a data card before any run.
    - The new window is banded on its own pool. For `omni_d61_78` that is only 25 items, so its banding CI is about ±19 points. Rule 3 (overshoot) applies unchanged.
    - Configs: `make_pilot_configs.py --candidate <file> --short <name>`, then estimate, dry run and check.
41. **Recall covariate (audit 8, descriptive).** Every agent call gets `recall_cue` = 1 when its output matches `RECALL_RE` in `autoagentnet/metrics.py`, case-insensitive: `known (?:answer|result)|\b(?:HMMT|AIME|AMC|IMO)\b|\brecall|\bremember|from memory|well[- ]known|standard result`.
    - `analysis/gate.py` reports single and dense-proposer accuracy split by it (`gate_<step>_by_recall`) for P2b and P3.
    - It triggers nothing. It qualifies the vote6 and H6 readings: shared recall can make agents agree.

42. **Grader frozen through P3 (audit 9).** `rewrite_answer` (`autoagentnet/tasks.py`) handles the formats of "find all" answers on both sides of a comparison: Unicode superscripts, ±, "x ∈ {...}", "$a$ and $b$" (never "or"), "for all" qualifiers, nested exponents, and spaces around + and - (math-verify cuts "a + b - c" short).
    - The task filter is unchanged, and so is every split hash.
    - A regrade of all 259 cached outputs flips 3 grades, all from wrong to right (log).
    - From here to the end of P3 the grader does not change. A misread found later goes to the hand check (rule 43) and the report, not into code.
43. **Hand check (audit 9), for banding, P2b and P3.**
    - **What is read:** every unparsed final answer, and every wrong final answer on a several-part gold (one with a comma, "=", "\\in", "\\{" or "\\pm"), in both arms (single and dense; for dense, also the propose answers that feed vote6).
    - **Who decides:** the automatic grade. The log lists each hand-check disagreement and flags any band or gate boundary (rules 3, 19, 11, 18, 29) that the hand grades would cross. A crossed boundary goes to the auditor before the next paid run.
44. **Prediction for the move-up banding** (`p2_band_move` prereg below; written before the run). `omni_d61_78` is olympiad "find all" work, about 6% HMMT, with 36% of its banding golds in several parts.
    - Prediction: single accuracy (automatic grade) 30 to 50% on the 25 pool items; at most 1 of 25 truncated at 3200; at most 10% unparsed.
    - Decision by rules 3 and 40:
      - in [30, 50]%: keep `omni_d61_78`;
      - in [25, 30)% or (50, 60]%: keep it as well, since the other window (69.2%) is outside [25, 60]%;
      - under 25% or over 60%: drop Omni and band AIME and BBEH (amendment rule 1).
    - One item moves the result 4 points, so the hand check (rule 43) is read before the decision.

45. **Unparsed limit 0.30 on `omni_d61_78` (Kevin, STEERING 2026-10-19, fourth).** Every d61 config, banding through P4b, stops early only if more than 30% of final answers cannot be read. That still catches a format collapse. The hand check (rule 43) and rule 46 do the grading. `make_pilot_configs.py --max-unparsed 0.30`; other candidates keep 0.10.
46. **Blind hand grade for gate decisions (audit 10).**
    - Each gate decision (rules 29, 19, 11 and 18) must hold under both the automatic grade and a blind hand grade.
    - The blind hand grade reads the final answers of both arms on the judged items: every unparsed answer, and every wrong answer on a several-part or free-parameter gold. Gold and answer pairs are shuffled, and the arm is hidden from the grader (`analysis/hand_grade.py` writes the sheet; the session fills it in before unblinding).
    - On those golds, vote6 is also grouped by hand: proposers whose answers are equal up to a renamed free parameter count as one answer. This matters because `answers_match` splits "1/(x+c)" from "1/(x+k)" (audit 10, finding 2), which inflates dense minus vote6.
    - If the two grades disagree on a decision, it goes to the auditor and to Kevin before the next paid run.
    - The d61 golds with a parameter the problem never defines are omni-4153, omni-4168, omni-3634 and omni-4259 (the last is in calibration).

47. **P2b order and the blind hand grade (audit 11).**
    - **Run `p2_omni61_single` first.** If its automatic grade is at least 13/20 (65%), Omni fails P2 under both grades, because the hand grade can only add right answers. Then dense is not run, and amendment rule 1 applies (band AIME and BBEH; probe the one nearer 40%). If it is 5/20 or less, the hand grade of the single arm decides the band before dense runs. Otherwise run `p2_omni61_dense`.
    - **Blinding order (amends rule 46).**
      1. Read gate aggregates only (`python -m analysis.gate p2`).
      2. Write the blind sheet (`python -m analysis.hand_grade sheet p2 omni61`), fill it in and commit it.
      3. Write and fill the vote sheet (`... vote p2 omni61`).
      4. Unblind (`... unblind p2 omni61`).
      5. Build the rule 43 list from the unblinded grades.
      - No per-item result is opened before step 4.
    - **What the blind sheet takes (amends rule 46, audit 11, finding 5):** every unparsed answer, and every wrong answer on a gold that is not a plain number (several-part, free-parameter or other symbolic).
    - **A stop on the dense cost limit** ($0.02 per task) goes to Kevin; it is not rerun with a new limit (audit 11, finding 6).
    - `hand_grade.py` gains the single-Sonnet arm, CIs and the p3w positions before P3 (audit 11, finding 4).

48. **BBEH band rule made exact (audit 12; before any BBEH output).** `analysis/banding.py` applies it to `p2_bbeh_band_single`, with a test.
    - Eligible tasks have at least 7 pool items and no truncated item (this excludes nycc, which has 3).
    - A truncated item counts as wrong.
    - A task is in band when its single accuracy is in [0.20, 0.70].
    - Computational tasks, in this fixed order: multistep arithmetic, time arithmetic, boolean expressions, dyck languages, word sorting, web of lies, geometric shapes. The rest (causal understanding, sarc triples, sportqa, movie recommendation, nycc) are not computational.
    - Kept: at most 4 eligible in-band tasks. Computational tasks come first, then the accuracy closest to 0.40, then the order above. Fewer than 2 kept tasks drop BBEH.
    - BBEH's number for amendment rule 1 is the pooled accuracy over the kept tasks' items.
    - Then the gate file `bbeh_gate` is rebuilt with the kept tasks (NEXT step 6) and the BBEH P2b configs are generated with `--max-dense-cost 0.06`.
49. **Amendment rule 1, amended (audit 12).** AIME is banded only if BBEH is dropped by rule 48 or fails P2b. AIME is the most contaminated candidate: Haiku reached 75 to 80% by hand on olympiad problems, with recall cues in most outputs. Its band would probably need a move, and an AIME probe could not separate recall from teamwork.
50. **BBEH stops (Kevin, STEERING 2026-10-19, fifth).** The BBEH banding run stops on truncation only above 25% (`--band-max-truncation 0.25`). The dense cost stop for BBEH is $0.06 per task. Every other stop is unchanged.
51. **BBEH grader (amends rule 42; before any BBEH output).** `bbeh_normalize` reads a Unicode minus as a minus, and one number with comma thousands separators ("35,036") as that number; tests in `test_bbeh_numbers`. The BBEH data card is unchanged. Every wrong BBEH and AIME banding answer is read by hand (rule 43), and the log flags any task whose band membership the hand grade would change.

52. **How the BBEH single band is read (audit 13; before any BBEH P2b output).** Single accuracy is pooled over the banding pool's kept tasks (20/50) plus calibration 0-19, 70 items, and must lie in [30, 60]%.
    - Rule 47's branches become: P2 fails on the single band only if calibration is 0/20 (20/70 = 28.6%). The hand grade of the single arm decides that case before dense runs. The 13/20 shortcut cannot fire (at most 40/70 = 57%).
    - Dense runs unless calibration is 0/20.
53. **Negative P2 gap on BBEH (Kevin, STEERING 2026-10-19, sixth).** For BBEH, P2b is the first 20 items of a 40-item measurement. A negative gap does not STOP; it goes to P3, whose futility step (rule 19, validation 20-39) decides. This replaces rule 29's negative-gap STOP for BBEH only.
54. **BBEH cost stops (Kevin, same entry).** Single Sonnet stops early above $0.04 per task and `judge_cascade` above $0.06 per task (`--sonnet-max-cost 0.04 --cascade-max-cost 0.06`).
55. **Descriptive, for BBEH (audit 13).**
    - `analysis/gate.py` adds a per-task table: single, dense and vote6 accuracy for each BBEH task. A gap that comes only from the chance-level boolean items (4/16 in banding; 7 of 20 calibration items) then shows up.
    - After P2b dense, P3, P4 and P4b are projected from its measured cost per task and recorded here before P3.
    - The stage prompts were written for math (for example, critique on "unit and rounding errors"), so a null result on BBEH qualifies the network as much as the task.

56. **No gate statistic pools items 0-19 (audit 14).** Rule 53's "40-item measurement" means that P2b's calls are reused by P3, not that P3's statistics include them.
    - P3's futility check reads validation 20-39 only (rule 19), and its gate reads 20-59 (plus 100-119 if P3w runs).
    - `p2_bbeh_dense` runs under the `p2_probe_bbeh` prereg. `p2_bbeh_single` ran under the older `p2_probe` text, with rules 52 and 53 governing.
    - After P2b, P3 runs single and dense on 20-39 first. Single Sonnet, noise and 40-59 wait until futility passes.

57. **Rule 55 projection (after P2b dense, before P3).** Measured: dense $0.0117 per BBEH task (no stage truncates; parsed 100%), single Haiku $0.0008. Single Sonnet is assumed at about 20x single Haiku, $0.016.
    - P3: single and dense on 20-59, Sonnet on 20-59, noise replicate on 20-29: about $1.3.
    - P3w, if triggered (100-119): about $0.25.
    - P4: worst case per task is 4.8x dense's, so about $0.056 per task over 80 items: about $4.5.
    - P4 single held-out: about $0.03. P4b cascade: about $0.4.
    - Remaining total about $6.5, about $7 for the pilot, under the governor's $17.40. Re-projected after P3 from P3's own costs.

58. **Rule 18 amended (audit 15; before any Sonnet output).** Single Sonnet stops P4 only if its accuracy on the judged items is at least dense's (point estimate) **and** its cost per task is at most dense's.
    - On BBEH, one Sonnet call costs about $0.016, 1.4x dense's $0.0117, so it is not the matched-cost senior rule 18 assumed (about half of dense).
    - If Sonnet matches dense at a higher cost, the report leads with it as a control, and P4 runs when rule 11 passes.
    - The other branches of rule 18 are unchanged.
59. **Split runs write separate results (audit 15).** A run overwrites results.csv with the slice it ran. So P3 dense runs as `p3_<cand>_dense` (0-39, the futility slice) and `p3_<cand>_dense_b` (40-59, after futility passes). `p4b_<cand>_judge_cascade` (60-79) and `_b` (80-99) work the same way. `analysis/gate.py`, `analysis/hand_grade.py` and `analysis/designs.py` combine a run's `_b` slice with it (`gate.slices`; fake-provider test `test_split_run_slices_are_combined`).
60. **Hand check and vote6, descriptive (audit 15).**
    - The blind sheet also takes every wrong answer that is not a bare number or "No", even on a numeric gold. For example, the P2b dyck-1103 aggregate "7 — completion: ]" against gold 7 is right by hand, so dense is really 18 of 20.
    - The gate table adds `vote6_tiesplit_acc`, the vote with ties split evenly. For P2b it is 51.7% (dense minus vote6 about +33, against +40 with ties to the earliest agent).
    - Decisions still use rule 11's vote6 as written.

61. **Grader fix after P3 (Kevin, STEERING 2026-10-19, eighth).** `bbeh_normalize` strips `<...>` when it encloses the whole answer (the format BBEH's own prompt shows), and drops a "— completion: …" tail after a leading number or "No". Tests: `test_bbeh_brackets_and_completion_tail`.
    - The BBEH data cards are unchanged.
    - Every BBEH run is replayed from the cache ($0) and regraded. `reports/pilot/tables/*_frozen.csv` keep the frozen-grader tables for side-by-side reporting.
    - The fixed grades equal the blind hand grades: P3, 60 items, dense 65.0%, gap +21.7, dense minus vote6 +20.0; Sonnet 70% on 20-59. The banding keeps the same four tasks.
62. **P4 run rules (audits 18 and 19; Kevin, seventh entry).**
    - **Dense-error kill, held-out only.** On parts a-h, dense comes from the P3 cache. On the held-out half, after 20 items (parts i-l) and after 40 (parts i-p), dense accuracy is compared with the P3 fixed-grade estimate of 65.0%. Outside 50 to 80% means stop and audit.
    - **Cost tripwire.** Part a or part i (the first part with uncached dense calls) costs more than $0.42, which is 1.5 x rule 57's $0.056 per task x 5 items: stop and audit.
    - **Audits:** after part a, after part h, after part l, after part p, and after any stop. Before part i, the search-half picks and the consensus policy are committed (`analysis/build_report` tables `p4_picks.csv` and `designs.md`).
    - The grid prereg (`p4_grid`) is updated to these readings before part a.
63. **Single Sonnet on held-out 60-99 (Kevin, eighth entry).** `p4_<cand>_single_sonnet_held` (prereg `p4_sonnet_held`) gives the senior control on the same items as P4's picks.
    - The "vote if the proposers agree, else single Sonnet" policy is scored offline from P4's dense proposers and this run.
    - Its agreement threshold (theta in {1/2, 2/3, 5/6, 1}) is chosen on 20-59 by the rule 25 reward, then scored once on 60-99.
    - It is a descriptive row of `research/designs.md` (rule 25) and triggers nothing.

64. **Vote-or-Sonnet theta fixed before any held-out item (rule 63).** Chosen on 20-59 by the rule 25 reward, from P3's dense proposers (the same cached calls as P4 parts a-h) and P3's Sonnet run (fixed grader). In-sample, by theta:

    | theta | accuracy | cost per task | vote settles |
    |---|---|---|---|
    | 0 | 50.0% | $0.0038 | 100% |
    | 1/2 | 60.0% | $0.0060 | 88% |
    | 2/3 | 70.0% | $0.0114 | 55% |
    | **5/6** | **72.5%** | **$0.0134** | **38%** |
    | 1 | 70.0% | $0.0155 | 20% |

    Dense on 20-59: 65.0% at $0.0111. **theta = 5/6** is scored once on held-out 60-99 with `p4_bbeh_single_sonnet_held` (`analysis/designs.py`, row "vote or Sonnet"; test `test_vote_or_sonnet_policy_and_theta_choice`). It is descriptive (rule 25).

65. **Before part i (audit 22).**
    - The production function, and with it `p4_grid` prediction (1) and the "critique and refine add under 2 points per doubling" decision, is judged on all 80 items (20-99). It is not a selection, so pooling adds power without a winner's curse.
    - Predictions (3) and (5) and rule 24 are judged on held-out 60-99 as point estimates. At n=40 their CIs are about ±15 points.
    - Held-out comparisons are also reported by task, because 60-99 holds 12 geometric-shapes items.
    - The $0.42 stop applies to every held-out part.
    - After part p, `git diff` against 13d5cfd must show the same picks (3-3-1-1 joint, 6-6-1-1 stage-by-stage), the same consensus policy (m=3, theta=5/6, else dense) and theta 5/6 for vote-or-Sonnet.
    - `judge_cascade` (P4b) runs only if H5 is still open after part p: no consensus or vote-or-Sonnet design meets rule 24 on held-out, so the cascade could still answer it.

### Amendment 7 (2026-10-20, v3 session S1: W0, the control resample; written before any W0 call)

66. **Why (W0 in `research/v3/program.md`).** The pilot sampled its single-Haiku control once per item.
    - On held-out 60-99 that one draw scored 57.5%, 13.8 points above the average proposer.
    - Dense minus single fell from +21.7 points on the gate items to +2.5 on held-out.
    - W0 asks whether that drop came from the control's draw.
67. **Design.** Two runs, Haiku first.
    - **`w0_haiku5`:** the pilot's single network with `haiku_nothink` on BBEH validation 20-119, with replicates 0-4 (5 samples per item).
        - Replicate 0 is the pilot's own call, served from the cache. An offline check with no price book or governor, so a miss cannot spend, found 100 of 100.
        - Replicates 1-4 are 400 new calls.
    - **`w0_sonnet_100_119`:** one Sonnet call (`single_sonnet`) per item on 100-119, 20 new calls. With P3's run (20-59) and P4's (60-99), Sonnet then covers 20-119; 80 of those 100 calls are already in the cache.
    - **No team calls.** Dense comes from the pilot's results files: `p3_bbeh_dense`, `p3w_bbeh_dense` and `p4_bbeh_grid_i` to `p`.
    - **Grades.** Every arm uses the rule 61 grader. The grader does not change in W0.
68. **Measures, in plain words.**
    - *Haiku5* of an item: the share of its 5 single-Haiku samples graded correct (0, 0.2, ..., 1).
    - *Haiku4* of an item: the share of its 4 new samples (replicates 1-4) graded correct. It leaves out the pilot's suspect draw. Draw 0 minus Haiku5 equals 0.8 times (draw 0 minus Haiku4), so Haiku4 is the fair yardstick for how lucky that draw was (audit 38).
    - *Team minus Haiku5*: the mean over items of dense's grade (0 or 1) minus the item's Haiku5, in points. It comes with a paired 95% bootstrap interval over items (2,000 resamples, seed 0, `analysis.common.paired_bootstrap_diff`).
    - Reported on:
        - held-out 60-99, which carries the decision;
        - 20-59 and 100-119 (the gate items, chosen with selection, so biased upward; audit 25);
        - all 100.
    - Also reported:
        - the pilot's draw (replicate 0) minus Haiku4 on each set, which says how lucky that draw was, and team minus Haiku4;
        - accuracy of each replicate;
        - Sonnet minus team and Sonnet minus Haiku5 on 100-119 and 20-119;
        - a t-interval next to each bootstrap interval;
        - cost per item of each arm (rule 5): the team's from the pilot results, Haiku's per sample and Sonnet's per call, at list price, with cached calls at their original price;
        - prompt hashes (rule 6): `single` and `single_sonnet` use the same system and instruction text, sha256 prefix `336e3ebcbbb1b6ac` (only the model differs).
    - **Power (audit 38).** The smallest difference these items detect, with 80% power at the two-sided 5% level, is 2.8 times the SD of the per-item differences over the square root of n.
        - With the pilot's single draw it is 23.5 points on held-out 60-99 and 15.9 on all 100.
        - With Haiku5 it is about 20 points on 60-99 and about 12.5 on all 100. This uses the band run's split of variance (between items 0.141, within items 0.145) and the pilot's dense variance and dense-draw covariance on 60-99 (0.246 and 0.108).
        - W0 can therefore point one way but cannot settle a 10-point question on 40 items. The decision is worded accordingly (rule 69).
69. **Decision** (program.md W0). It is judged on the held-out 60-99 point estimate of team minus Haiku5. Each branch is worded as "estimate (interval), consistent with", never as settled, because at n = 40 the interval is about ±12 points and the smallest detectable difference about 20 (rule 68).
    - At least +10 points: "+x (lo to hi), consistent with the held-out drop being the control's draw".
    - +5 to under +10: "+x (lo to hi), unresolved".
    - Under +5: "+x (lo to hi), consistent with a small edge of the team over one Haiku".
    - The same branch is computed with Haiku4. If it differs from the Haiku5 branch, the report flags it; the decision stays on Haiku5.
70. **Run rules.**
    - Each run follows the same sequence:
        - estimate recorded in `research/estimates.csv`;
        - fake dry run;
        - commit;
        - `aan check` cleared;
        - run;
        - read `status.json`;
        - check that state is on origin;
        - auditor.
    - Stops:
        - more than 10% of answers unparsed;
        - more than 5% of calls truncated;
        - Sonnet above $0.04 per task (rule 54);
        - a run that spends more than 1.5 times its recorded estimate goes to audit before anything else.
    - If `w0_haiku5` makes more than 400 live calls, replicate 0 did not come from the cache. The run is then audited before analysis.
    - **Audit triggers (audit 38):** actual spend above $0.42 for `w0_haiku5` or above $0.45 for `w0_sonnet_100_119` goes to the auditor before any analysis. These are the measurable versions of the 1.5x rule, at 1.5 times the projected actual cost; the worst case can never trip that rule.
    - Order: `w0_haiku5` first; `w0_sonnet_100_119` last. It changes no decision (audit 38), so it is dropped if the money is needed for W2-A.
71. **Budget** (`aan estimate`, worst case x1.15, cache ignored):
    - `w0_haiku5` $0.98, or $0.79 for its 400 uncached calls;
    - `w0_sonnet_100_119` $0.79.
    - Projected actual is about $0.58: 400 Haiku calls at the band run's $0.0007, and 20 Sonnet calls at P4's $0.015.
    - The pilot phase has $10.62 left in actual spend, or about $8.01 of worst-case headroom.
72. **Where it is reported.**
    - Code: `analysis/w0.py`, with an offline test.
    - Table: `reports/pilot/tables/w0.csv`.
    - Write-up: a new section of `reports/pilot/report.md`, "W0: the control resample", which the v3 report repeats.
73. **W0 closed (audit 39).**
    - `w0_haiku5` ran: $0.2785, 400 new calls; replicate 0 came from the cache and matched the pilot on 100 of 100.
    - Result on held-out 60-99: team minus Haiku5 is +6.5 points (-8.0 to +20.0), rule 69's "unresolved". Haiku4 gives the same branch.
    - **`w0_sonnet_100_119` is dropped.** It changes no decision and adds Sonnet only on selected gate items (protocol section 3).
    - The free five-sample vote is reported as a control that was not preregistered (audit 39, finding 6). The write-up leads with held-out 60-99, not with all 100 items.
    - Miss: the predicted interval width of ±12 points came out ±14.
74. **W2-A has its own preregistration** (v3 session S1): `research/v3/plan_w2.md`. It was revised after audit 40, before any W2-A call. The configs are in `configs/experiments/desk/`.

<!-- prereg:begin (copied verbatim into the experiment files by scripts/make_pilot_configs.py) -->
```yaml
p0_calib:
  question: How does this model ref behave per call on calibration items 0-4 (hidden tokens, truncation, prompt-token estimate error, latency, rate limits)?
  prediction: "haiku (default thinking): output tokens above 1.5x the visible estimate on at least 3 of 5 calls and at least 1 of 5 truncated at 800. haiku_nothink: within 1.3x, none truncated. haiku_low: in between. Actual prompt tokens 1.0x to 1.4x of estimated_prompt_tokens x 3/4. sonnet_nothink: within 1.3x, none truncated, under $0.01 per call. luna_low and gpt_small: output tokens at most 2x visible for luna_low. Latency 2 to 15 s per call."
  kill: Any ref whose model ID is not listed by aan models, whose price differs from configs/pricing.yaml, or whose spend exceeds 1.5x its estimate is not used for paid work; stop and audit.
  decision: Choose the Haiku worker ref (haiku_nothink unless it truncates or is rejected, then haiku_low) and record it in plan.md; regenerate configs if it changes; size P4 parts from the rate limits in status.json.
p0_dense:
  question: Does the dense network truncate at the amendment 6 caps (1600 tokens in every stage, rules 30 and 35) with the chosen ref, and what are its per-stage output tokens and latency?
  prediction: No stage truncates more than 5% of calls; mean output tokens per call below 60% of max_tokens in every stage; one 19-call task finishes in under 90 s.
  kill: Truncation above 5% in any stage. Do not raise max_tokens; switch the ref or stop and ask Kevin.
  decision: Per-stage output tokens and the rate limits set the P4 part size and concurrency.
p2_band:
  question: Which difficulty window or task subset puts a single Haiku agent at 30 to 50% on this candidate?
  prediction: Omni difficulty 4.4-6.1 lands at 30 to 55% with thinking off; AIME problems 3-9 at 35 to 65%; at least 3 BBEH tasks fall in [0.20, 0.70].
  kill: The band rule in plan.md (P2a and amendment rule 3); a candidate outside [0.25, 0.60] after one move is dropped.
  decision: Keep, move once or drop the window; rebuild the task file with the chosen window before any probe.
p2_band_move:
  question: After one move up (plan rule 40), does omni_d61_78 put a single Haiku agent at 30 to 50% on its 25-item banding pool?
  prediction: Single accuracy 30 to 50% (automatic grade); at most 1 of 25 calls truncated at 3200 tokens; at most 10% unparsed.
  kill: Rules 3 and 40. Below 25% or above 60% drops Omni (the other window, 69.2%, is outside 25 to 60%); then band AIME and BBEH (amendment rule 1).
  decision: Keep omni_d61_78 for P2b and later if it lies in [25, 60]%; read the hand check (rule 43) first and flag a crossed boundary.
p2_probe_bbeh:
  question: On BBEH calibration items 0-19 (four kept tasks), how does the dense network compare with a single agent and with vote6, and what does it cost per task?
  prediction: Dense minus single between -5 and +15 points (CI about +-20 at n=20); vote6 at least 3 points above mean propose accuracy; dense cost $0.012 to $0.02 per task; no stage truncates; at most 10% unparsed.
  kill: None on the gap. The single band passed over 70 items (rule 52), and a negative gap goes to P3 futility (rule 53, Kevin). The run's own stops (truncation per stage, unparsed, cost $0.06 per task) end it and go to Kevin.
  decision: Descriptive. Read through the rule 55 per-task table. Its cost per task sets the rule 55 projection of P3 to P4b. P3 then runs single and dense on 20-39 first (rule 19); no gate statistic pools items 0-19 (rule 56).
p2_probe:
  question: On 20 calibration items, does the dense network beat a single agent by at least 5 points?
  prediction: Dense minus single is +5 to +15 points; the vote over 6 propose answers is at least 3 points above mean propose accuracy.
  kill: On every probed candidate, single outside 30 to 60% or dense minus single below 0 points; stop and report alternatives. A gap of 0 to under 5 points does not stop; that candidate goes to P3, the real gate (rule 29; Kevin, STEERING 2026-10-18).
  decision: Amendment rules 1 and 2 choose a second probe and the P3 candidate; under rule 29 the P3 candidate is the probed candidate with single in 30 to 60% and the largest non-negative gap.
p3_gate:
  question: On 40 fresh validation items (20-59), does dense beat the single agent and the 6-answer vote by at least 5 points each?
  prediction: "Dense minus single at least 5 points (95% paired CI about +-13 points). Dense minus vote6 between -3 and +5 points: voting explains most of the gap (2508.17536). Futility check on validation 20-39 passes."
  kill: "Futility (rule 19): upper 95% CI of dense minus single below +5 on validation 20-39. Gap point estimate under 5 points on 20-59: STOP and report alternatives."
  decision: Rules 11 and 12. Go to P4 only if dense beats single and vote6 by at least 5 points each; if dense minus vote6 is under 5, report that voting explains the gap and skip P4.
p3_single_sonnet:
  question: Does one Sonnet 5.5 call per task (the senior control) match the 19-call Haiku team on validation 20-59, and at what cost per task?
  prediction: Single Sonnet accuracy within 10 points of dense; its cost per task 1.0x to 2.0x dense's measured $0.0117 on BBEH (rule 58).
  kill: "Rule 18 as amended by rule 58: Sonnet stops P4 only if its accuracy is at least dense's (point estimate) and its cost per task is at most dense's, on validation 20-59 only (Sonnet never runs on 100-119, so P3w does not enter this rule)."
  decision: "Sonnet at least as accurate but dearer than dense: the report leads with it as a control, and P4 runs when rule 11 passes. Below dense by less than 5 points: P4 runs when rule 11 passes and the report leads with the senior control. Below dense by 5 points or more: rule 11 alone decides."
p3_noise:
  question: How often does the dense network's final answer change between two independent runs on the same items (validation 20-29)?
  prediction: Replicates agree on at least 70% of the 10 items.
  kill: Agreement under 50%. Stop and audit, because single-sample landscape cells would then be mostly noise.
  decision: Report replicate agreement next to every landscape comparison.
p3w_gate:
  question: Does the gate result hold on 20 more fresh validation items (100-119), keeping 60-99 clean for P4's held-out half?
  prediction: The gap and dense minus vote6 stay within 5 points of their P3 estimates.
  kill: The rule 11 go/no-go, judged on validation 20-59 + 100-119.
  decision: Go to P4 or report, per rule 11.
p4_grid:
  question: Where does the network's accuracy come from? Accuracy per doubling of each stage, stage interactions and value per dollar on a 3x3x3 factorial grid.
  prediction: "(1) Proposers add the most accuracy per doubling and critique the least. (2) No interaction term is resolved (CIs include 0). (3) The equimarginal path reaches within 5 points of dense held-out error at no more than half the dense cost. (4) Effective team size of the propose stage is at most 3 (H6). (5) The joint pick and the stage-by-stage pick are within 5 held-out reward points of each other."
  kill: "Rule 62: dense held-out accuracy outside 50-80% after 20 and after 40 held-out items (P3 fixed estimate 65.0% +-15), or part a or part i costing more than $0.42; stop and audit. Any in-run stop (truncation per stage over all configs, unparsed, cost) also stops and audits."
  decision: "If critique and refine add under 2 points per doubling, the vote and consensus designs are the main result and the scale-up option is a power-first test of them; otherwise static picks and H1 lead. Search-half picks and the consensus policy are committed before part i (rule 62)."
p4_single_held:
  question: How accurate is the single Haiku agent on the P4 held-out half (validation 60-99), the H4 control every held-out pick and design is compared with?
  prediction: Single accuracy within 10 points of its P3 estimate on validation 20-59.
  kill: More than 10% of answers unparsed (format trouble). Stop and audit before using it as a control.
  decision: It is the single-agent row of research/designs.md and of the P4 held-out comparisons.
p4_sonnet_held:
  question: How accurate is one Sonnet 5.5 call per task on the P4 held-out half (validation 60-99), the senior control for every held-out pick and design?
  prediction: Sonnet accuracy within 10 points of its P3 fixed-grade estimate (70% on 20-59); cost $0.012 to $0.017 per task.
  kill: More than 10% of answers unparsed, or the run's own cost stop ($0.04 per task); stop and audit.
  decision: It is the senior row of research/designs.md on held-out items, and it feeds the descriptive vote-or-Sonnet policy (rule 63). It triggers nothing by itself (rule 25).
p4b_cascade:
  question: Does escalating only contested tasks to Sonnet (judge_cascade) reach dense accuracy at no more than half its cost on the held-out half (H5)?
  prediction: Exit rate 40 to 70%, escalation rate 10 to 30%, held-out accuracy at least dense minus 3 points at no more than 50% of dense cost (rule 24).
  kill: Cost per task above dense's. Stop this design.
  decision: Record it in research/designs.md as a descriptive row; it triggers nothing by itself (rule 25).
p5_transfer:
  question: Do the P4 picks keep their order on GPT-6 Luna at low reasoning (luna_low), and does the cost model hold there?
  prediction: Dense cost per task within 2x Haiku's actual; output tokens at most 2x visible; the 3 picks keep their error order (weak evidence, 10 items).
  kill: Hidden reasoning above 2x, or a price or model-ID surprise (aan models). Stop OpenAI work.
  decision: Runs only if P4 ran and P0's luna_low calibration passed (rule 26). Transfer is reported as feasibility only; mixed teams stay a post-pilot option.
w0_haiku5:
  question: Was the single Haiku control's held-out score (57.5% on validation 60-99, one sample per item) a lucky draw, so that the team's held-out edge over one Haiku (+2.5 points) understates it?
  prediction: "Haiku5 (the share of 5 samples correct, averaged over items) is 45 to 55% on 60-99; the pilot's draw is 5 to 10 points above Haiku4 (its 4 new samples); team minus Haiku5 on 60-99 is about +10 points (between +5 and +15), 95% interval about +-12; on all 100 items about +14 (dense 63%, Haiku5 about 49%). At most 2% unparsed and no truncation. About $0.32 actual for 400 new calls (about $0.0008 per call), $0.0008 per Haiku sample per item against the team's $0.011."
  kill: "More than 10% unparsed or more than 5% truncated stops the run (format trouble). Actual spend above $0.42 (the audit 38 trigger: 1.5x the $0.28 projected at the band runs $0.0007 per call), or more than 400 live calls (replicate 0 not from the cache), goes to the auditor before any analysis."
  decision: "Rule 69 on the held-out 60-99 point estimate of team minus Haiku5, worded as estimate (interval): at least +10, consistent with the held-out drop being the control's draw; +5 to under +10, unresolved; under +5, consistent with a small team edge over one Haiku. The Haiku4 branch is reported and flagged if it differs. At n = 40 the smallest detectable difference is about 20 points (rule 68), so W0 points one way and does not settle the question; the pilot report gains a W0 section (rule 72)."
w0_sonnet:
  question: How accurate is one Sonnet 5.5 call per item on validation 100-119, so that the senior control covers all of 20-119?
  prediction: Sonnet 60 to 80% on 100-119 (70% on 20-59, 72.5% on 60-99); Sonnet minus team on 20-119 about +8 points; cost $0.012 to $0.017 per item.
  kill: "More than 10% of answers unparsed, or the run's own cost stop ($0.04 per item, rule 54); stop and audit. Actual spend above $0.45 goes to the auditor before any analysis."
  decision: Descriptive. It completes the senior row (Sonnet minus team, Sonnet minus Haiku5) on 20-119 in the W0 section; it changes no rule 69 branch, so it runs last and is dropped if W2-A needs the money.
```
<!-- prereg:end -->

**Budget check (v2, worst case x1.15, cache ignored, recorded with the 3-characters-per-token estimator in `research/estimates.csv`):** P0 $0.10, P2 $0.51, P3 $1.84 (+ P3w $0.37 if triggered, now 20 items on 100-119), P4 $6.48 (grid $6.46 + held-out single $0.02), P4b $1.01, P5 $0.54. That is about $10.8 in total, against the governor's stop near $17.40. Caching will make P3's calibration items, P4's dense calls and P4b's proposers free in practice.

## Evidence per dollar (2026-10-21)

Kevin's Phase 0-2 plan, operational copy: `research/v3/evidence/plan.md`. Preregs live in `configs/experiments/evidence/*.yaml`; status in `research/log.md` (evidence session E1).

## Question tree

- Q0 Can this setup test H1 to H6 for $20? **open** (every paid step needs keys)
  - Q1 Is there a task where dense beats single by at least 5 points (paired) with single at 30 to 60%? **open** (P2/P3)
    - Q1a Which candidate task sets meet the protocol's criteria? **answered on paper**: Omni-MATH, BBEH, AIME (`research/lit/gate_tasks.md`); difficulty for Haiku 5.5 unknown → P2a banding
    - Q1b Does Haiku 5.5's default adaptive thinking eat the max_tokens budget? **open** (P0 live part)
    - Q1c Does voting over the propose stage already explain the gap (dense minus vote6 under 5 points)? **open** (P2/P3, free from the dense runs; rule 11)
    - Q1d Does one Sonnet 5.5 call match the 19-call Haiku team (H4 senior control)? **open** (P3, rule 18)
  - Q2 Is the idea novel? **answered: only with re-scoping** (P1, `research/lit/prior_work.md`)
    - Q2a Do learned pruners beat random pruning at matched cost? **answered in prior work: often not** (2609.05933) → H4 is primary
  - Q3 Where does the accuracy come from: which stage adds the most per doubling and per dollar, and do stages interact (H1, H2)? **open** (P4, figure i)
  - Q4 How correlated are agents within a stage, i.e. what is the effective team size (H6)? **open** (P4, effective-team-size table)
  - Q5 Can a consensus policy or a cascade keep dense accuracy at half the cost (H5)? **open** (P4b, figure h, `research/designs.md`)
  - Q6 Does the cost picture transfer to GPT-6 Luna? **open** (P5, conditional; price verified)
- Q7 Operational: are `aan estimate` worst cases close to actual spend? **open** (every paid run)

## Novelty assessment (P1, 2026-10-18; evidence: `research/lit/prior_work.md`)

Verdict: **novel only with re-scoping.** The P1 kill criterion ("a prior paper already learns per-stage keep ratios with a cost-aware reward") is *partly* met:
- MaAS (arXiv 2502.04180) learns, per query, how many operators each of 4 layers activates, with a token-cost penalty `lambda * C`;
- AgentSlimming (2605.08813) removes agents greedily under a USD budget;
- AGP, DyLAN, SMoA, AgentDropout and AgentConductor learn or fix agent counts per query or per round.

Spot-checked by the main session on the arXiv abstract pages: MaAS "samples query-dependent agentic systems from the supernet" and needs "only 6~45% of the inference costs"; the September 2026 audit (2609.05933, Zhang et al.) says many reported gains occur where "a randomly pruned system can already preserve strong performance". The scout's figure that AgentPrune and AgentDropout land within about 0.2 points of matched random pruning comes from the paper body as read through WebFetch, not checked against the PDF table.

**Re-scoped claim** (replaces "learn per-stage keep ratios with a cost-aware reward"): for a fixed propose → critique → refine → aggregate network of identical agents, measure *which stage can be pruned and whether stages interact*, under cache-aware dollar cost, and test whether a joint search (AMC-style controller or exhaustive) beats stage-by-stage sensitivity at matched cost, with matched-cost random pruning, uniform keep, self-consistency voting and the single agent as controls. Gaps no opened paper covers: static per-stage ratios for identical agents; cache-aware dollars; joint vs stage-by-stage at matched cost (H1); agreement-with-dense as a label-free reward (H3); random-pruning control as the primary outcome (H4). We do not claim a better pruner than per-query methods.

Plan changes adopted from P1 (scout's list, items kept):
1. **H4 is the primary outcome**: report every pick minus matched-cost random pruning, with a bootstrap interval (`analysis/landscape.py: random_control`). At least one agent per stage is already enforced by the search space.
2. **Self-consistency control**: majority vote over the first k propose-stage answers of the dense run (`propose_vote_baseline`, free from the dense run). A cost-matched single-agent self-consistency run is a costed option for after the pilot, not pilot spend.
3. **Search baselines on the cached table** (free): random, uniform, stage-by-stage sensitivity, greedy, REINFORCE, exhaustive (`analysis/search.py`). A MaAS-style `lambda * C` scalarisation is the reward we already use (`error_plus_log_cost`).
4. **How cost enters**: reward = -error - lambda log2(cost / dense cost), lambda = 0.05 (each halving of cost is worth 5 points), plus the budgeted variant (AMC-style, cost <= B) as a check. Fixed before P4.
5. **H3 prior**: agreement-with-dense can at best track dense accuracy and cannot reward fixing the dense network's confident errors; expect H3 to hold best where dense accuracy is high.
6. **Gate prior**: Kim et al. (2512.08296) report negative returns from more agents when the single agent is already above about 45%, and losses on sequential tasks; voting explains most debate gains (2508.17536). Expect a gate pass to be likeliest where single accuracy is 30 to 45%, and expect much of any gap to be available to voting alone. The propose-stage vote baseline measures that for free.
7. **Prompt re-tuning after pruning: deferred** (no prior test exists; AMC re-tunes only the winner; too expensive for the pilot).


## Open-weight testbed (session T1, 2026-10-26; branch ow_testbed)

Question: width, depth and verification on open weights. Precision × size × thinking budget × k samples on Qwen3.5
2B/4B/9B served by vLLM on a rented GPU, at $0 API spend and up to $100 of GPU credit.
- Preregistration: `research/v4/testbed/prereg.md` (T1–T5; revised after audit T1-1).
- Runbook: `research/v4/testbed/RUN_GPU.md`.
- Code: `autoagentnet/testbed/`.

Status: built and tested offline; no GPU run yet. Next:
1. Kevin provides a Lightning Studio (an H200 is recommended).
2. The pilot (≤ $10) measures cost and floors.
3. The drop rule sets stage 1's scope.
4. The auditor gives GO.
5. Stage 1 (≤ $55).

Stage 2 and the kernel run each need their own prereg addendum and an audit first.

## Paper, record and Atlas extensions (session W1, 2026-10-27; branch paper_atlas)

$0. Kevin's W1 brief (research/STEERING.md, thirteenth note).
- Atlas extensions P1-P8: `analysis/atlas_extend.py` -> `research/v4/atlas/extend.md`. All post hoc on public data.
- Paper draft: `paper/` (NeurIPS style, compiled to `paper/main.pdf`). Every number is generated by
  `scripts/build_numbers.py` from committed files and carries its status.
- Project record: `reports/v4/story.html`, built from the same numbers; published as a private artifact.
- Roadmap: `research/v4/roadmap.md`.

Status: built; audited once at the end (audit W1-1, research/audit_log.md). Waiting on:
- E6's CD read and run review reaching main; `scripts/build_numbers.py` then fills the paper's placeholders.
- The testbed pilot.
- E6's fetch script, so the anchor's systematic shares can get intervals (P6).

The roadmap's order replaces nothing in the plan above. Its items still need their own preregistrations before any
spend.

### Prediction for E6's CD2, logged before CD2 is read (audit W1-1, item 5)

CD2 (E6's draft prereg on branch depth_review): one Haiku max call minus the dollar-matched odd-k vote of Haiku xhigh.
P3 (research/v4/atlas/extend.md, post hoc on public MathArena data) found that a reasoning step at the top of a model's
range buys about nothing over the nearest-dollar vote of the step below:
- Gemini 3.1 Pro medium to default: +1.1 points (-3.8 to +6.0; 23 items);
- Opus 5.5 high to max: -1.5 points (-8.7 to +5.3; 88 items, at 3.2x the dollars).

**W1's prediction for CD2: about 0, between -5 and +5 points**, with its interval including 0. Two public pairs on one
benchmark family make this a weak prior, not a test. E6's own prediction (P2 of its draft: -2 to +3) lies inside it.
The paper's working title "Depth before width" is withdrawn until CD2 is read.

## Measurement layer (session M1, 2026-10-27; branch metrics)

Question: what does each configuration cost in time, not only in dollars? TTFT, TTFAT, decode speed, peak context
per call, stage and run, and on the GPU KV-cache use, memory and energy.
- Definitions and inventory: `research/v4/measurement.md`.
- Analyses (exploratory, $0): `research/v4/measurement/`:
  - backfill of every run so far;
  - latency card;
  - configuration map with held-out regret;
  - stage balance;
  - patching note (addendum 2).
- Hand-back: `research/v4/measurement/handback_m1.md`. Audit M1-1: ADJUST, fixed at $0.

Next:
1. After E6 hands back, the optional timing probe (`configs/experiments/measurement/m1_probe_*`, about $1.9
   expected): measured TTFT and decode speed against the backfill's estimates.
2. The GPU pilot runs with the trace sidecar.
3. Patching: a draft prereg only (`research/v4/measurement/patching_prereg_draft.md`). It needs a `read: conclusion`
   block and Kevin's decision first.

## PHOENIX integration smoke (2026-10-31)

User-authorized, two serial OpenAI calls maximum; synthetic calibration-only fixture. Frozen configs: configs/experiments/phoenix_smoke/. Each run is capped at $0.08 including governor margin; no Anthropic or formal study. Check JSON, bounded tool execution, token usage, ledger and push. These calls provide no scientific evidence of recovery effectiveness.

## ScienceClaw studies (session SC, 2026-10-31; branch updated_fullrun_on_forest_electron_signal_data)

Kevin's brief (research/STEERING.md is to record it). Two preregistered studies with ~5% pilots:
- Study A, PHOENIX on science tables: research/phoenix_science/prereg.md (+ Amendment 1),
  docs/PHOENIX_SCIENCE_ADDENDUM.md, reports/phoenix_science/ceiling.md, configs/experiments/phoenix_science/.
- Study B, Self-or-Social shortlist: research/self_or_social_shortlist/prereg_arxivmath.md, prereg_labbench.md.
Priority if time or money runs short: PHOENIX E1, ArXivMath, PHOENIX E2, BBEH, LAB-Bench, E1b, ChemBench.
