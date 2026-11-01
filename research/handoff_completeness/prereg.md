# Handoff completeness: how much of a strong model's accuracy can a cheaper architecture complete from its partial reasoning? (preregistration, ScienceClaw, 2026-11-01)

Written and committed before any call of this study. Kevin's Batch 3. Kevin decided the order: prereg and code before
12:00 ET, and the paid run after it.

**Question.** A strong model can become unavailable mid-task, through a budget cap, an outage or a withdrawal. How
much of its accuracy can a cheaper architecture complete from the strong model's partial reasoning? This links the
lever study (what a dollar buys) to PHOENIX (recovery after losing a member).

## Items (frozen)

`research/handoff_completeness/items.txt` holds 442 items, sha256
`04e66e21a7232425f785f7a25d92c27584021627f7610cfb25f0f68c3b58f882`:
- **BBEH:** the 200 self-or-social BBEH dev items (`research/self_or_social/sealed/dev.txt`), 50 each of linguini, NYCC,
  word sorting and causal understanding.
- **LAB-Bench:** the 242 of the 288 SeqQA/ProtocolQA dev and test items that no model refused in any stored call
  (`results/sos_lab_*`).
  - The other 46 are excluded entirely. A refusal is terminal and never handed off.
  - The LAB-Bench test items were already read in the Self-or-Social study. This study asks a different question, and
    nothing here is fitted on them.

## Strong traces (stored; no new strong calls except the stop-early control)

- **BBEH:** call 0 of `sonnet_nothink` (Sonnet 5.5, thinking off; `results/e51_sonnet_bbeh/calls.csv`).
- **LAB-Bench:** the first answer of `sonnet_med` (Sonnet 5.5, effort medium; member C of
  `results/sos_lab_claude2_{dev,test}/calls.csv`). Only its visible reply is used; hidden thinking is not stored.

## Cuts (`autoagentnet/handoff/build.py`; `scripts/build_handoff.py` writes `data/handoff/`)

- **Trace.** The stored visible reply with its final ANSWER line removed.
- **Token.** A whitespace-separated piece of the trace.
- **f.** The share of tokens kept before the cut: f ∈ {0, 0.25, 0.5, 0.75, 1}. The prefix is the first
  round(f × tokens) tokens, and f = 0 is the item alone.
- **Handoff prompt.** The item's own prompt, then "Partial solution by another solver:", the prefix, and: "Above is a
  partial solution by another solver that stopped early. Continue from where it stops and finish. End with ANSWER:
  <answer>."
- **Leak flags**, computed before any call (`data/handoff/leaks.csv`):
  - *leaked*: the task's own grader, reading the prefix alone, finds the key answer.
  - *mentions*: the prefix names the key answer in prose. For MCQ that is the gold letter written as an option; for
    other kinds, the normalized key of 3 or more characters appears in the text.
  - At f = 1, *mentions* flags 29% of BBEH and 43% of LAB-Bench prefixes; *leaked* flags 3.5% and 0%.
  - Flagged rows are run like the others and reported separately (below).

## Architectures (weak: `haiku_nothink`, Haiku 5.5, thinking off, max_tokens 4,000)

- **(a) One completion.** Haiku completion number 0.
- **(b) Vote of three.** Three independent Haiku completions (replicates 0, 1 and 2), majority vote over parsed
  answers. Ties go to replicate 0's answer.
- **(c) Complete, then check once.** Completion 0, then one self-check call (the runner's reflect revision: it re-reads
  its own answer and revises). The answer is the self-check's.

All calls go through the governed self-or-social runner (`kind: self_or_social`, `first_answers_only` for the
completions; one member with `branches: true` and `reuse_first` for the self-check), with one config per set and
condition in `configs/experiments/handoff/`.

## Controls

- **Strong stops early.** The strong model answers at once from its own prefix ("Above is your own partial solution,
  cut short. Answer now from it. End with ANSWER: <answer>.") at f ∈ {0.25, 0.5, 0.75}.
  - It runs on a 60-item subset stratified over the six families (`data/handoff/stop_subset.txt`).
  - The model is `sonnet_nothink` on BBEH and `sonnet_med` on LAB-Bench.
  - It separates the weak model's contribution from a strong model that was already done.
- **Wrong trace.** For architecture (a) at f = 0.5, the prefix comes from a different item of the same family: the next
  item in sorted order.

## Measures

- **Accuracy.** The share of items right under the task's grader. An unparsed, cut-off or refused reply is wrong.
- **acc_weak(arch).** The architecture's accuracy at f = 0.
- **acc_strong.** The stored strong trace's own accuracy on the same items.
- **R(f) = (acc(f) − acc_weak) ÷ (acc_strong − acc_weak).** The share of the gap the handoff closes. It is computed per
  architecture, per set (BBEH, LAB-Bench) and per family.
- **Fidelity(f).** The share of completed answers equal to the strong trace's own final answer, under the grader's
  equivalence.
- **Cost.** Dollars per item of each architecture at each f: recorded call dollars, replays at their recorded
  dollars.
- **f80.** Where R reaches 0.8, by linear interpolation between grid points. "Not reached" if R(1) < 0.8.
- **Intervals.** 95% bootstrap over items (2,000 draws, seed 2026), paired across f and architectures.
- **Families.** These are descriptive: about 50 items each.

## Predictions (written before any call)

- **P1.** R rises with f for every architecture. The pooled point estimates are non-decreasing in f, and
  acc(1) − acc(0) has a 95% lower bound above 0.
- **P2.** The vote (b) beats one call (a) only at mid-range f: acc_b − acc_a has a lower bound above 0 at f ∈ {0.25,
  0.5}, and its interval includes 0 at f ∈ {0, 0.75, 1}.
- **P3.** On step-by-step families the curve rises earlier. For (a), f80 is smaller on word sorting than on causal
  understanding and on NYCC (point estimates).
- **P4.** The wrong-trace control scores at or below the weak model alone. For (a), acc(wrong, f = 0.5) − acc(f = 0)
  has a point estimate ≤ 0 and is not resolved above 0.

## Reporting

- **Primary.** R(f), fidelity and cost on all rows.
- **Secondary.** The same with rows flagged *leaked* or *mentions* at that f excluded. Flag counts are reported per set
  and f.
- **Refusals.** A short descriptive note on the provider refusal patterns; refused items are excluded by design.
- **Deliverables.**
  - `reports/handoff_completeness/summary.md`, with one figure: R(f) per architecture with bootstrap bands, faceted by
    set.
  - An auditor verdict in `research/audit_log.md`.

## Kill rules and process

- **Kill rules.** Per member and phase, after 20 live calls, stop if more than 10% of calls are unparsed or truncated,
  or the cost per call is above 2× its guard. Stop on a governor refusal, or on total spend above 2× the recorded `aan
  estimate`.
- **Pilot.** Before the rest, run the first 5% of each derived id list in order. That is 10 BBEH and 12 LAB-Bench items
  across all f.
  - The pilot passes if no kill rule trips and at least 90% of its calls are parsed.
  - The pilot items stay in the study. The pilot is a gate, not a separate result.
- **Run.** max_concurrency ≤ 8. One paid process at a time unless Kevin says otherwise.
- **Before any call.** This file, the item list, the derived tasks and the configs are committed. A fake dry run, `aan
  estimate` (recorded in `research/estimates.csv`) and `aan check` all pass.
- **Expected cost.** About $8: roughly 9,300 Haiku calls at about $0.0007, plus 180 Sonnet calls. The recorded `aan
  estimate` is the reference for the 2× kill rule.

## Note before the first call (2026-11-01, 10:19 ET; no rule change)

1. **Timing.** Kevin moved the run to start now (10:18 ET). It must finish before 11:00 ET, or it is dropped from
   the report page and the pitch. (Daylight saving time ended this morning, so ET = UTC−5.)
2. **Two processes.** To fit the window, BBEH and LAB-Bench run as two parallel pipelines, each at max_concurrency 8.
   Kevin allowed two paid processes at once earlier in the session. The ledger is shared and re-read before every
   call, and checkpoints use the shared lock.
3. **Order within each pipeline.**
   - The pilot slice comes first: the first 5% of the completions list. Any kill rule stops the pipeline.
   - Then the rest of the completions (architectures a and b).
   - Then the self-check (c), the wrong-trace control and the stop-early control.
   - The pilot slices of the self-check and the controls are not run separately. They run as part of each config's
     full run, under the same kill rules.
4. **Anything not finished by 11:00 ET is reported as not run.**
