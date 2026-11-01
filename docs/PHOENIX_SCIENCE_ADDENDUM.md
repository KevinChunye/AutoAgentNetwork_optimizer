# PHOENIX science-table addendum (session SC, 2026-10-31)

This addendum changes the **testbed**, not the method. The policies, prompts, selection rule, DSL and executor
are the teammate's (docs/PHOENIX.md; design in docs/PHOENIX_PLAN.md, whose text is unchanged). The study's
preregistration is research/phoenix_science/prereg.md.

## Why the testbed changed
On the sklearn toy sets (breast cancer, wine, digits) the incumbent pipeline is already near the ceiling and every
operation retrains in milliseconds. On wine the median of the 144 pipelines in the configuration space already scores
0.988 validation balanced accuracy (max 1.000, spread 1.2 points; reports/phoenix_science/ceiling_runs.csv on the
toy check). Inheriting versus recomputing then has nothing to decide: recomputation is free and there is little to
gain. The science tables make both sides real: operations take seconds, so redundant work costs measurable CPU, and
the configuration space spreads widely, so the recovery choice can move the final result.

## The three datasets (verified at runtime, reports/phoenix_science/ceiling_cleaning.csv)
| dataset | source | raw rows | features | classes | dropped |
|---|---|---|---|---|---|
| covtype | sklearn `fetch_covtype` (UCI Covertype): forest cover type of 30 m cells from cartographic variables | 581,012 | 54 | 7 (labels 1-7 mapped to 0-6; about 103:1 imbalance) | 0 |
| miniboone | OpenML 41150 (UCI MiniBooNE): electron vs muon neutrino events | 130,064 | 50 | 2 (`signal` False/True) | 468 rows holding the -999 sentinel |
| higgs | OpenML 23512 (the 98,050-row OpenML version of UCI HIGGS): signal vs background collisions | 98,050 | 28 | 2 (`class` 0/1) | 1 row with missing values |

Preparation (autoagentnet/phoenix/data.py): drop unusable rows deterministically (order kept, count recorded), map
labels to 0..K-1, take ONE stratified subsample of N rows (random_state=42), then the original 60/20/20 split,
sealed test file and three training-internal calibration folds, unchanged in logic. manifest.json records the source,
both hashes, the dropped-row count, the label map, N and the subsample indices.

## N and limits (A3 ceiling check: scripts/phoenix_ceiling.py, reports/phoenix_science/ceiling.md)
All three tables are GO: the spread (max - median validation balanced accuracy over the 144 pipelines) at N = 60,000
is 25.6 points on covtype, 11.2 on HIGGS and 5.0 on MiniBooNE (rule: NO-GO below 2 points).
- N = 60,000 rows per dataset (36,000 train / 12,000 validation / 12,000 sealed test): the largest size checked; its
  slowest single operation (a 100-tree forest with no depth limit) takes 28.2 s end to end through the real tool
  worker on covtype, at most 50% of the frozen tool timeout.
- tool_timeout_s = 90 (toy 30): 28.2 s is 31% of it, leaving room for four branches sharing four cores.
- cpu_budget_s = 600 per branch (toy 120): operations take 2-28 CPU s instead of about 1 s; the 24-tool limit, not
  CPU, stays the usual binding limit, as on the toy sets.
- wall_s = 3600 per branch (toy 1200); calibration cpu_budget_s = wall_s = 7200 per model.
- Calls (8), tools (24), output tokens (4096) and input tokens (6000) are the plan's values, unchanged.
All values are frozen in configs/experiments/phoenix_science/settings.yaml.

## Trimmed matrix (all branches at the $0.20 future budget)
- E1 (main, F1 shutdown + model withdrawal): fixed, llm, full.
- E2 (negative control, F0 identity shutdown only): fixed, full.
- E1b (if the pilot passes and room allows): no_dependency, no_cost.
- 18 cases (3 datasets x T1/T2 x seeds 101-103) in a fixed random order (seed 2026). Pilot: the first case of each
  dataset in that order under the three E1 methods (9 branches); pilot cases are never evidence, so E1 has 45
  branches, E2 30 and E1b 30 on the other 15 cases. The teammate's E3 (healthy) and E4 (same-pool selectors) and the
  $0.05 budget are dropped to fit the time and money of this session.

## Changes to code that is not the method
- Withdrawn model under F1 (study.py `withdrawn_models`): balanced within template (T1 5 sonnet_low / 4 sol61_low,
  T2 4 / 5; every dataset 3 / 3). The original alternation over the whole case list confounded the withdrawn model
  with the template (T1 lost sonnet_low 6 of 9 times, T2 lost sol61_low 6 of 9 times).
- Batch runner (batch.py, `kind: phoenix_batch`): branches run concurrently in one process with one locked
  SpendGovernor, ledger and call cache; identical requests are paid once. CPU stays per branch: the engine's own CPU
  is its thread's (thread_time) and each tool's CPU is that child's (os.wait4); both equal the old measures in a
  serial run.
- Branches hard-link the checkpoint's immutable artifacts instead of copying them (disk).
- Request size: the capability estimates shown to the model are rounded (quality and success to 4 decimals,
  dollars to 6, seconds to 2; engine.compact_estimate). With a full-size table the first recovery request on the
  science tables was about 4,700 of the 6,000 allowed input tokens; rounded, about 3,900. The planner still uses the
  unrounded table.
- Schema bounds: tool_timeout_s up to 120 s and wall_s up to 7200 s (were 30 s and 1500 s).
- Model pool: luna_low_ev, sol61_low, sonnet_low if the one-call sonnet_low smoke passes; otherwise OpenAI-only.
