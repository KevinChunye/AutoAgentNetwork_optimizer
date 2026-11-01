# PHOENIX on science tables: preregistration (session SC, 2026-10-31)

Status: written before any calibration or study call on the science tables. Frozen at the commit that also freezes
the study configs (`configs/experiments/phoenix_science/`); later changes are dated amendments at the bottom.
Method, policies, prompts and selection rule are the teammate's (docs/PHOENIX.md, docs/PHOENIX_PLAN.md); only the
testbed changed (docs/PHOENIX_SCIENCE_ADDENDUM.md).

## Question
After a team member is shut down mid-workflow and one model is withdrawn (F1), does PHOENIX's dependency-aware,
budget-normalised recovery ("full") deliver a better held-out result at the same future budget ($0.20 per branch)
than ordinary fixed takeover ("fixed") and than letting the planner LLM choose each recovery step ("llm"), and at
what dollar cost?

## Testbed
Three science tables, each one fixed stratified subsample of N rows, split 60/20/20 (sealed test untouched until the
single evaluation): forest covertype (7 classes), MiniBooNE (electron vs muon neutrinos; 468 sentinel rows dropped),
HIGGS (OpenML 98,050-row version; 1 row with missing values dropped). From the A3 ceiling check
(reports/phoenix_science/ceiling.md): N = 60,000 per dataset; tool timeout 90 s, CPU 600 s and wall 3600 s per
branch (configs/experiments/phoenix_science/settings.yaml). Spread of the configuration space at N = 60,000:
covtype 25.6, HIGGS 11.2, MiniBooNE 5.0 points (all GO).
Cases: 3 datasets x 2 templates (T1 chain, T2 shared prefix + staged predictions) x run seeds 101-103 = 18,
in a fixed random order (seed 2026). Pilot: the first case of each dataset in that order (3 cases); pilot cases
are never evidence. Evidence: the other 15 cases (5 per dataset).
Model pool: luna_low_ev (planner), sol61_low, sonnet_low, unless the one-call sonnet_low smoke fails (then
OpenAI-only: luna_low_ev, sol61_low; F1 withdraws sol61_low; recorded as an amendment before any study call).
F1 withdraws sonnet_low or sol61_low, balanced within template (T1 5/4, T2 4/5; 3/3 per dataset).

## Arms (all $0.20 future budget, plan limits: 8 calls, 24 tools; CPU, wall and tool timeout per settings.yaml)
- E1 (main, F1): fixed, llm, full x 15 cases = 45 branches.
- E2 (negative control, F0 = identity shutdown only): fixed, full x 15 = 30 branches.
- E1b (only if the pilot passes and room allows): no_dependency, no_cost x 15 = 30 branches.
- Pilot: fixed, llm, full under F1 on the 3 pilot cases = 9 branches.

## Outcomes
- Primary: test balanced accuracy of the branch's frozen final predictor (sealed test, scored once, after every
  branch is frozen), in points.
- Secondary: logical API dollars per branch; redundant recompute CPU; planning share of dollars; CPU seconds;
  status counts; full - fixed by withdrawn model; F0 - F1 per policy.

## Primary contrasts and decision rule
full - fixed and full - llm in test points and in dollars, paired by case, pooled over the 15 evidence cases and
per dataset (5 cases), with 95% paired bootstrap intervals over cases (10,000 resamples, seed 2026;
analysis/phoenix_science.py). Decision, test points, pooled:
- lower bound > 0: "PHOENIX full beats X on these tables at $0.20";
- upper bound < 0: "PHOENIX full is worse than X";
- otherwise: "not resolved" (ordinary failover may be enough). Per-dataset rows are descriptive.

## Predictions (stated before any study call)
- P1: full - fixed, test points, pooled: mean between 0 and +2, interval including 0 ("not resolved"), because fixed
  also finishes the original pending work first and the incumbent improvements available at $0.20 are small.
- P2: full - llm, dollars: negative (full makes fewer planning calls than llm, which calls the planner every step).
- P3: full - fixed, dollars: positive (fixed's continuation design calls are cheaper than full's proposals).
- P4: F0 - F1 per policy: near 0 for fixed (it designs with luna_low_ev, which F1 never withdraws).
These are expectations, not hypotheses tested with a family-wise error rate; all contrasts are reported.

## Kill rules
Stop the study and audit on: any test-label exposure or provenance/hash violation; an unknown model charge; a
governor refusal; a pilot go/no-go failure (then fix, amend, re-pilot on the next cases in the run order and do not
use the failed pilot cases as evidence).

## Go/no-go after each pilot (calibration pilot: tasks 0, 10, 20 per model; study pilot: 9 branches)
GO only if all hold, and the auditor agrees (verdict in research/audit_log.md, decision in research/log.md):
1. Unparsed or truncated model outputs <= 10% per model and phase; no governor refusal; no unknown model charge.
2. Actual cost per branch (or per calibration task) <= 2x its estimate. Estimate = for each call made, the median
   cost of that model's calibration calls (for the calibration pilot: the measured smoke cost of that model,
   or for sonnet_low its smoke call).
3. The pipeline completed end to end: for full and llm at least one model proposal compiled, at least one
   operation executed and validated, and frozen.json written with a VALID validated target; for fixed the same
   without the proposal.
4. state/ pushed; every status.json in a finished, non-error state (completed, validation_ceiling,
   no_positive_feasible_plan, limits_reached or budget_stopped).
5. Projected full cost = pilot actual x (full size / pilot size) x 1.3 fits the remaining phase and account room.
If 1-4 fail: fix, amend, re-pilot on the next cases. If only 5 fails: cut scope in the order E1b, then E2.

## Amendments
(none yet)

### Amendment 1 (2026-10-31, after the pre-run audit's ADJUST; written and committed before any calibration output was read)
The calibration pilot (tasks 0, 10, 20 per model) ran while the audit was open; its outputs were not opened before this
amendment was committed. From this commit the prereg is frozen; the model pool is the three-model pool (sonnet_low
smoke passed, audit GO).
1. Calibration-pilot go/no-go, per model over its three pilot tasks (replaces rules 1, 2 and 4 for calibration):
   - Rule 1: unparsed or schema-invalid replies are calibration observations (they count as failed completions in the
     table). NO-GO only if all three of a model's pilot replies are unparsed or truncated, or any call is refused by
     the governor or has an unknown charge.
   - Rule 2: actual cost per call <= 2 x expected + $0.01, where expected = list price at the request's estimated input
     tokens and 1,000 output tokens. The governor's worst-case reservation stays the hard bound.
   - Rule 4: a one-task slice ends with status "running" by design; it passes when status.json has no error_type,
     calibration_state.json has no pending call and exactly that task added to `done`, and the state commit reached
     origin.
   - Rules 3 and 5 unchanged (rule 3 for calibration: the reply's pipeline was executed and validated, or recorded as
     a failed completion).
2. Study-pilot rule 2: expected cost per call = list price at that call's estimated input tokens and the median output
   tokens of that model's calibration calls; actual cost per branch <= 2 x the sum over its calls + $0.01.
3. Missing outcomes: every finished branch, including one with status error, exports frozen.json with its valid
   incumbent and is scored like any other (deployment would deliver that incumbent). A branch with no frozen.json is
   "not run": it is left out of the sealed evaluation, listed by name in the summary, and its pairs are dropped from
   the paired contrasts, with the number of dropped pairs reported per contrast.
4. Re-pilot: if the study pilot fails rules 1-4, the next case of each dataset in the frozen run order becomes the
   re-pilot and is also excluded from evidence (evidence then 12 cases per experiment).
5. Withdrawn-model balance on the 15 evidence cases (pilot cases covtype_T2_103, miniboone_T2_103, higgs_T1_102
   removed): T1 5 sonnet_low / 3 sol61_low, T2 3 / 4; per dataset 3/2 or 2/3. (The 5/4 and 4/5 in the addendum are
   for all 18 cases.)
6. Calibration after the pilot runs in slices of at most 5 tasks per model, one paid process at a time, each slice's
   state pushed and its outputs committed.
7. Known reporting bug (smoke audit): run_phoenix can overwrite a calibration error status with the saved status;
   until it is fixed (after calibration, before the study configs are frozen), every slice's status.json is checked
   for error_type.

### Amendment 2 (2026-10-31, after audit SC-3 ADJUST on the calibration pilot; before any further calibration call)
Timing of Amendment 1, stated plainly: it was committed at 21:23:59 UTC, 34 s after the last pilot call (21:23:25);
the session had not opened the pilot outputs then, but that cannot be verified from the repository. Its changes are
the ones audit SC-1 asked for before any output existed. Under the original rules the pilot would have failed rule 4
(every one-task slice ends "running") and luna task 20 rule 2 (2.13x the toy smoke's cost).
Defect found by SC-3 and fixed before any further call:
1. Plan replies: all 3 pilot plan replies misused the actions (luna and sol: RECOMPUTE without a target; sonnet:
   RECOMPUTE of the baseline with a new pipeline attached). compile_proposal ignores pipelines on INHERIT, VERIFY,
   RECOMPUTE and ABANDON, so sonnet's forest never ran and calibration credited the baseline's score to the reply.
   Fixes (code that is not the method's decision rule):
   - engine.check_action_shape: a proposal with pipelines on INHERIT, VERIFY, RECOMPUTE or ABANDON is rejected
     (recorded as proposal_rejected / a failed calibration completion), never silently dropped; used in the study
     engine's accept() and in calibration.
   - calibrate.py: a plan reply that compiles to an artifact that already existed is a failed completion.
   - prompts.py (FLAGGED TO KEVIN: a change to the teammate's prompt text): the propose and recover instructions now
     state what each action means (prompts.ACTIONS, from docs/PHOENIX.md "Recovery interfaces"). Without it the
     planner's proposals were unusable, which would make "full" and "llm" measure the prompt defect, not the method.
   - run.py / batch.py: an error status is no longer overwritten by the saved calibration status (SC-2).
2. Calibration restarts under new names (configs/experiments/phoenix_science/calibration_v2/, results/sci_cal2_*),
   frozen against the fixed code. Re-pilot: tasks 0, 10, 20 and 21 per model (12 calls; design and diagnose requests
   are unchanged, so tasks 0 and 10 replay from the call cache at $0), go/no-go per Amendment 1, auditor agreement;
   then tasks 1-9, 11-19, 22-29 in slices of at most 5 per model. The first pilot (results/sci_cal_*) is kept as a
   record and is not used in the capability table.
3. After every batch, every branch's status.json is read for error_type.

### Amendment 3 (2026-10-31, after audit SC-4 on the re-pilot; before calibration v3)
Audit SC-4 agreed the re-pilot passes rules 1-5 and asked for one plan-scoring decision. Chosen: option (a). A
calibration plan reply is scored on its FIRST proposal that compiles to a new executable artifact; proposals that fail
the shape check, are incomplete, or compile to an existing artifact are rejected one at a time (as the study engine,
which considers every proposal); the reply fails only if no proposal qualifies. Before, only the first proposal was
scored, so the same two proposals counted as a failure or a success depending on their order (sol vs sonnet, task 20).
last_task_error is now cleared per task. Calibration restarts as sci_cal3_* (calibration_v3/), frozen against this
code; batches p1-p4 replay the re-pilot's 12 requests from the call cache ($0), then s1-s6 run tasks 1-9, 11-19, 22-29
(at most 5 per model per batch), one process at a time, outputs committed after each batch.
Not changed (the teammate's method): planner.py pools plan and diagnose observations into each model's design
estimate (task_family is not used). Reported as a property of the method.

### Amendment 4 (2026-10-31, before any study call): preflight gate fix only
The gate in run.py (preflight_phoenix) asked for the pipeline estimate of category "generic"; on covtype that matched
a single failed generic row (sonnet's one failed design) and reported "no completed pipeline-quality observations",
refusing every covtype branch although covtype has 70 completed pipeline observations with quality. The gate now asks
whether the dataset has any completed pipeline observation with a quality, in any category. The planner's estimator
(the method) is unchanged. All 114 branch configs re-frozen at this commit.

### Amendment 5 (2026-10-31, after audit SC-5 on calibration v3; before any study call)
Facts from calibration v3 (results/sci_cal3_*; research/phoenix_science/capabilities.json, 1,313 observations), stated
before the study runs:
- Capability: sonnet_low - sol61_low, paired by task, -0.05 points [95% CI -0.22, +0.14] (21 of 29 identical);
  sol61_low or sonnet_low - luna_low_ev +3.9 points [1.2, 7.1], all from luna's depth-10 forests on covtype. The pool has
  two capability levels: luna_low_ev, and sol61_low ~ sonnet_low.
- About 90% of design replies are forests, so logistic and knn quality estimates fall back to the dataset pool.
- Design calls cost $0.0002-0.008, so the $0.20 API budget never binds; the 600 CPU s limit (and the 8-call, 24-tool
  limits) do. "Same budget" in this study means the same API, CPU, tool and call limits.
- fixed always designs with luna_low_ev (engine.py), which F1 never withdraws.
- One failed "generic" pipeline row on covtype (sonnet task 1: prose then fenced JSON, rejected by the strict parser)
  appears in covtype planner prompts as a pipeline/generic estimate with n=1; it is the method's estimator and is kept.
Predictions added before any study call:
- P5: F0 - F1 and full - fixed by withdrawn model are near 0 for every policy (withdrawing sol or sonnet leaves an
  equally capable model).
- P6: any full - fixed gain is concentrated on covtype (the only dataset where model and pipeline choice moved
  calibration quality).
- If full and fixed choose the same pipelines in the pilot, E1 is expected "not resolved" and E1b is cut first.

### Amendment 6 (2026-10-31, after audit SC-6 on the study pilot; before any E1 call)
Kevin reviewed the pilot and gave GO for the full run (E1, E2, E1b). Audit SC-6 agreed rules 1-5 pass and recorded:
- Under full and llm the planner (luna_low_ev) only proposed finishing the pending work (VERIFY/RECOMPUTE/INHERIT);
  the method's built-in candidates contain no design step, so sol61_low and sonnet_low are reached only if the planner
  proposes them, and it did not (higgs_T1_102: sonnet's design qualities 0.701-0.714 were shown above the incumbent
  0.6734; luna answered INHERIT). The request text leans towards stopping ("A valid incumbent is always an acceptable
  stopping point"; no objective in the propose instruction). This is the method as specified; it is not changed here.
  Rewording the planner or the fixed-design request would be a new, separately preregistered arm (Kevin's decision).
- fixed's continuation designs (luna, "fixed-order continuation of incumbent") reproduced an existing pipeline in all
  24 pilot replies (23 the incumbent): fixed stalls in practice, so P3's dollar contrast is driven by these copies.
- Pilot final scores sit at the grid maximum on covtype and MiniBooNE (reports/phoenix_science/ceiling.md); 10 of the
  15 evidence checkpoints have a no-depth-limit forest pending, 5 have depth 5/10 forests.
Predictions updated before E1: E1 full - fixed and full - llm in test points: "not resolved" (expected 0 on most
cases); P6 (gain concentrated on covtype) unlikely; the informative cases are the 5 with a depth-limited forest
pending. E2 is expected degenerate by construction (F1 withdraws only models no policy calls), so F0 - F1 = 0; it is
still run as preregistered (Kevin's GO) and reported as a confirmed-degenerate control. E1b is run; it can only differ
from full if full makes a real choice.
Analysis additions (descriptive, reported for every branch): design calls per model, copied designs (a design reply
that reproduces an existing pipeline), new pipelines executed, and fixed's copied-design dollars, separately.

### Amendment 7 (2026-11-01, after audit SC-8 on E1, E2 and E1b; before the sealed evaluation)
Reporting only; no run, method or contrast changes. Audit SC-8 (ADJUST) found the batches valid and asked that the
report says what they can and cannot show:
1. fixed's terminal status is reported as "call limit reached" when its 8 calls are used (30 of 30 E1 fixed branches),
   although the engine stamps no_positive_feasible_plan (the normal stop: no remaining plan with positive gain).
2. E2 (F0) is reported as a measure of run-to-run noise, not of the fault: F1 withdraws models no method calls, so
   F0 - F1 is the difference between two luna draws (full's F0 and F1 differ on 4 of 15 cases).
3. E1b - E1 full is split by where each pair first diverges: at a proposal (a fresh luna draw: planner noise) or at
   the ranking (the ablated rule), with counts per kind; only ranking divergences speak to the ablation.
4. Every contrast reports how many of the cases differ from 0 and the largest single-case share of the mean.

## Family arms (2026-11-01, Kevin's request after E1; written before any family-arm call)
Why: in the pilot and E1 the planner (luna_low_ev) only proposed finishing the pending work and the strong pool
models were never asked to design (Amendment 6). Kevin: "do Opus as the planner and then sonnet or haiku following
up", "Sol as the strong planner then using terra or luna", "anthropic family all 5.5 family and gpt all 6.1 family",
and no smoke-test pilots ("do the beginning of the actual run ... if the pilot run succeed then completing the rest").
Design (configs/experiments/phoenix_science/family/settings.yaml; autoagentnet/phoenix/study.py family_*):
- Claude arm `fam_claude`: pool haiku_low (Haiku 5.5, effort low), sonnet_low (Sonnet 5.5, low), opus_med (Opus 5.5,
  medium); planner opus_med; F1 withdraws haiku_low or sonnet_low.
- GPT arm `fam_gpt`: pool luna_low_ev (GPT-6 Luna, low; no 6.1 Luna exists), terra61_low (GPT-6.1 Terra, low),
  sol61_med (GPT-6.1 Sol, medium); planner sol61_med; F1 withdraws luna_low_ev or terra61_low. It needs Kevin's
  gpt-6.1-terra price row; until then only the Claude arm runs.
- Same 18 cases, checkpoints, run order (seed 2026), shutdown member, per-branch limits (8 calls, 24 tools, 600 s CPU,
  3,600 s wall) and E1 methods (fixed, llm, full under F1) as the main study. Withdrawn model alternated within
  template between the two non-planner models (each template loses each 4 or 5 times).
- Two draws per case and method (audit SC-8: in the main study the per-case differences came from which replies luna
  happened to draw). A draw is a fresh sample of every model call (PhoenixConfig.draw; cache replicate seed + 1000 x
  draw; draws 1 and 2), everything else identical: 18 cases x 3 methods x 2 draws = 108 branches per arm.
- Who designs: full and llm ask the planner (opus_med / sol61_med); fixed keeps the main study's ordinary-failover
  rule, designing with the first pool model still available (haiku_low, or sonnet_low when haiku_low is withdrawn;
  luna_low_ev, or terra61_low). So fixed - full also contrasts a cheap designer with the strong planner.
- Output ceiling 16,384 tokens per call (medium-effort thinking counts against it; 4,096 in the main study) and
  $1.00 per branch (the engine reserves each call's worst case, about $0.34 for Opus at 16,384, so $0.20 would block
  the planner). Prompts, actions, tools and the engine are unchanged (the method as specified; SC-6's note on the
  stopping-leaning request applies to both arms).
- Calibration per arm on its own pool (calibration prompts list the pool) and ceiling: 3 families x 10 tasks per model
  on the training-internal folds, $10 per model; tables combined into research/phoenix_science/capabilities_<arm>.json.
  The main study's v3 rows are not reused (different pool and ceiling).
Gate instead of a pilot (one continuous run per arm): calibration runs tasks 0, 10 and 20 of every model first
(slices g1-g3), then the rest (s1-s6) continues if no model has an error_type, a pending task or a status other
than running/completed and state was pushed. After the table is combined, the matrix is generated and frozen, a fake
dry run of the gate batch must finish, and the gate batch (the first case per dataset in run order x 3 methods,
draw 1 = 9 branches) runs first; the rest (99 branches) continues if every gate branch has a terminal status without
error, no
call is invalid or truncated above 10% of the gate's calls, no branch exceeds its budget, and state was pushed. A
failed gate stops the arm (no retry, no amendment without Kevin). Nothing changes after the gate, so all 18 cases are
evidence.
Contrasts (per arm, paired by case, 95% bootstrap over the 18 cases, 10,000 resamples, seed 2026; "not resolved" if
the interval includes 0): full - fixed, full - llm (test points and dollars); each case's value is the mean of its
two draws, and the draw-to-draw difference within method is reported as the noise level (as E2 is, Amendment 7).
Every contrast also reports how many cases differ from 0. Planner effect: arm full - main E1 full
and arm llm - main E1 llm on the main study's 15 evidence cases (different pool and budget as well as planner, so
this is the effect of the whole arm, not of the planner alone). Exploration per branch: design calls per model,
copied designs, model-proposed new pipelines executed, proposals per action.
Predictions: (P7) more branches run a model-proposed new pipeline than in main E1; (P8) full - fixed test points not
resolved in either arm (validation scores near the grid maximum), any gain on the 5 depth-limited cases; (P9) cost
per branch above main E1 and below $1.00; (P10) the arms do not differ from each other by more than 1 test point.
Kill: as the study (test-label exposure, provenance or hash violation, unknown model charge, governor refusal, failed
gate). Sealed evaluation: the arms' branches are sealed and scored together with the main study, once, after every
branch is frozen; no test label is read before then.
Family arms, change before any GPT-arm call (2026-11-01, Kevin's choice "Run now without Terra"): gpt-6.1-terra has no
price row, so the governor refuses it. The GPT arm's pool becomes luna_low_ev (GPT-6 Luna, low), sol61_low (GPT-6.1
Sol, low) and sol61_med (GPT-6.1 Sol, medium; planner); F1 withdraws luna_low_ev or sol61_low. This mirrors the Claude
arm (a cheap model plus the strong model's family at two efforts). Everything else in this section is unchanged.
The two arms are compared descriptively (provider difference, P10); the arms differ in pool and planner, so the
comparison is of the whole arm, not of one model.

### Amendment 8 (2026-11-01, after audit SC-13 on the Claude arm; before the sealed evaluation; reporting only)
1. P7 is measured by model_new_pipelines (analysis/phoenix_science.py exploration): completed pipelines a model
   brought in, from a REROUTE/SPLIT proposal or a design that copied nothing. The earlier new_pipelines_completed
   also counts finished pending work and cannot show exploration (main E1 full 14/15 against the arm's 32/36).
   Before any test read: main study full 6 of 18 branches, Claude arm full 27 of 36.
2. full - fixed is also reported by withdrawn model, because fixed's designer is the other cheap model (Haiku when
   Sonnet is withdrawn, Sonnet when Haiku is; Luna or Sol low in the GPT arm). On validation (not test) the Claude
   arm's full - fixed was +0.97 points [+0.40, +1.75] (Haiku designing +1.42, Sonnet +0.52); validation is what the
   methods select on, so it is optimistic.
3. Disclosed with the results: the disk incident (fitted-model scratch of finished calibration tasks deleted; branch
   predictors intact, 368 sampled hashes verified); invalid outputs per model (Claude arm: Haiku 0/144, Sonnet 5/144
   prose replies, Opus 6/388, 5 of them reasons over 500 characters; 29 non-executable llm choices by Opus; llm used
   its 8 calls in 25 of 36 branches); 14% of the arm's dollars were prompt-cache writes never read back (both price
   tables charge 1.25x, so no provider is favoured); one branch stamped dirty by a GPT config folder written during
   the run (not loaded).
Family arms, GPT rest batch (2026-11-01, 03:40 UTC; no design change): `aan check` refused the GPT arm's 99-branch rest
batch because its worst case ($99: 99 branches x the $1.00 branch budget) exceeds the OpenAI room (about $53); nothing
was spent. The same 99 frozen branch configs run as four batches (batch_rest_1..4, interleaved, about 25 branches and
$25 worst case each), one after another, each through `aan check`. Branch configs, frozen hashes and order of the
gate are unchanged.

### Amendment 9 (2026-11-01, after audit SC-14 on the GPT arm; before the sealed evaluation; reporting only)
No run, method, contrast or decision changes; no config is re-frozen. Numbers below are from events and statuses
only (no test label has been read).
1. P7 is reported as a rate: the share of branches that ran a model-brought pipeline (analysis/phoenix_science.py
   exploration, ran_model_pipeline = model_new_pipelines > 0), because the arms have 36 branches per method and the
   main study 15. Full: main E1 6 of 15 evidence branches (40%; 6 of 18 with the pilot cases), Claude arm 27 of 36
   (75%), GPT arm 13 of 36 (36%). llm: main 0 of 15, Claude 1 of 36, GPT 0 of 36. So P7 holds for the Claude arm
   and not for the GPT arm (same rate as the main study).
2. How llm ends, per arm (model calls used, out of 8): Claude 7.5 on average, 25 of 36 branches at the limit (Opus
   keeps proposing); GPT 3.7, none at the limit (Sol chooses INHERIT, keeping the current best, in 35 of 36 and
   stops explicitly in 1); main 6.0, 7 of 15 at the limit. The arms' different status counts (Claude 11 completed /
   25 limits / 72 no positive plan; GPT 36 / 0 / 72) are model behaviour: the 216 configs share implementation,
   template, provider and pricing hashes, limits, cases, ceiling and budget. Mean calls per method are in the
   method table, and Amendment 7's "call limit reached" label now reads each branch's call count from its state.json
   (branches.csv has no calls column; analysis/phoenix_science.py load, tested).
3. Disclosed differences between the arms: every GPT call ran through OpenAI's background mode (its ceiling, 16,384,
   is above the streaming limit); Sol barely reasons here (sol61_low 0 thinking tokens in 146 calls, sol61_med 12-40
   on average); matrix dollars $3.82 GPT against $14.81 Claude; prompt-cache writes are 88% of the GPT arm's dollars
   and 2% of written tokens were read back (the 1.25x write premium cost $0.70, 18%).
4. GPT full - fixed is reported by withdrawn model, as for Claude (fixed designs with Luna when Sol low is withdrawn
   and with Sol low when Luna is). On validation only (what the methods select on, so optimistic): full - fixed
   +0.69 [+0.13, +1.53] (Luna withdrawn +0.79, Sol low withdrawn +0.59); full - llm +0.70 [+0.47, +0.94].
5. autoagentnet/phoenix/report.py changed at 05:11 UTC (pairing within each draw; merge 854b8f4), after the last GPT
   call (05:04). No run used it. The sealed check does not hash report.py (phoenix/data.py context hashes types,
   data, workflow and worker; 216 of 216 family frozen.json files validate), but the implementation hash stored in
   the 454 frozen PHOENIX configs no longer matches the tree, so none of them can be preflighted again; none will be.
6. fixed's first requests differ between draws in 18 of 18 GPT cases, because the prompts carry CPU timings (as in
   the Claude arm, SC-13).
7. Two paid processes ran at once with Kevin's permission (2026-11-01); protocol section 5 and CLAUDE.md still say
   one, which is Kevin's to update.
