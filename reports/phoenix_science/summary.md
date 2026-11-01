# PHOENIX on science tables: summary (ScienceClaw, session SC, 2026-11-01)

**Question.** A three-model team is building a classifier on a science table. Midway, one member is shut down and a
model is withdrawn (fault F1). The team must then recover the unfinished workflow. Three recovery methods are compared:
- **fixed**: ordinary takeover. The first model still available carries on in a fixed order.
- **llm**: the planner model chooses every recovery step.
- **full**: PHOENIX. Candidate plans are ranked by expected gain per unit of cost, along the workflow's dependencies,
  and the best plan with a positive gain is run.

Does `full` deliver a better held-out result than the other two, and at what cost?

Preregistration: `research/phoenix_science/prereg.md`. The design is fixed there; Amendments 1-9 are dated and
reporting-only after the first study call. Audits: SC-1 to SC-8, SC-13, SC-14 and SC-15 (the sealed evaluation) in `research/audit_log.md`.

**Terms.**
- *Test points*: balanced accuracy on a sealed test split, ×100, so 1 point = 0.01. Balanced accuracy is the mean
  recall over classes. Each branch's final predictor was frozen first; then every predictor was scored once, all
  together (330 branches, 2026-11-01 05:25 UTC).
- *Branch*: one recovery run, for one case and one method.
- *Case*: one dataset × workflow template (T1 chain, T2 shared prefix) × checkpoint seed.
- *Paired difference*: method A minus method B on the same case. In the family arms each method ran twice per case
  with fresh model samples (two "draws"), and a case's value is the mean of its two draws.
- *Interval*: a 95% bootstrap over cases (10,000 resamples, seed 2026). The verdict is "positive" when the whole
  interval is above 0, "negative" when below 0, and "not resolved" when it includes 0.
- *Dollars*: logical API dollars per branch, i.e. what the branch's calls cost at list price, including calls
  replayed from the cache.

Datasets: forest covertype (7 classes), MiniBooNE (electron vs muon neutrinos) and HIGGS. Each is one fixed
stratified subsample of 60,000 rows, split 60/20/20.

## Results at a glance

| Study | Pool (planner first) | Cap per branch | full − fixed (test points) | full − llm (test points) |
|---|---|---|---|---|
| Main (15 evidence cases) | GPT-6 Luna low, Sol 6.1 low, Sonnet 5.5 low | $0.20 | +0.20 [−0.31, +0.95] not resolved | +0.67 [−0.04, +1.65] not resolved |
| Claude arm (18 cases × 2 draws) | Opus 5.5 medium, Haiku 5.5 low, Sonnet 5.5 low | $1.00 | +0.86 [+0.34, +1.62] positive | +0.19 [+0.04, +0.36] positive |
| GPT arm (18 cases × 2 draws) | Sol 6.1 medium, Luna 6 low, Sol 6.1 low | $1.00 | +0.56 [+0.10, +1.21] positive (fragile, see below) | +0.59 [+0.35, +0.84] positive |

| Method | Main: test pts / $ per branch | Claude arm | GPT arm |
|---|---|---|---|
| fixed | 78.16 / $0.0044 | 78.28 / $0.055 | 78.43 / $0.042 |
| llm | 77.69 / $0.0040 | 78.96 / $0.231 | 78.40 / $0.034 |
| full | 78.36 / $0.0019 | 79.15 / $0.126 | 78.99 / $0.031 |

How to read this:
- The mean test points pool three datasets with very different ceilings: covtype near 73-75, HIGGS near 68-71,
  MiniBooNE near 92. Read the paired rows, not these means, for the effect.
- Dollars are logical API dollars (calls replayed from the cache are counted at list price).
- The caps never bound. The largest branch spent $0.26, 26% of the arms' $1.00.

## What this says, in plain words

- **The only like-for-like test of the PHOENIX rule is the main study, and it is not resolved.** There, one model
  (Luna) both designs and plans for every method, so full − fixed and full − llm isolate the rule. Results:
  - full − fixed: +0.20 [−0.31, +0.95];
  - full − llm: +0.67 [−0.04, +1.65].
- **In the family arms, full − fixed is a whole-arm comparison, not a test of the rule.** In fixed, the cheap model
  that is still available designs. In full, the strong planner proposes and the rule chooses. So full − fixed is the
  rule plus a strong planner against a cheap designer (Amendment 8; audit SC-15).
- **Claude arm: most of the gain is the planner.**
  - Opus choosing every step without the rule (llm − fixed) is already +0.67 [+0.11, +1.48].
  - Adding the rule (full − llm) gives a further +0.19 [+0.04, +0.36], and costs $0.105 less per branch, because the
    rule stops when no plan has a positive gain while Opus in llm uses all 8 calls in 25 of 36 branches.
  - full − fixed (+0.86) is robust: 15 of 18 cases improve and none gets worse. Each draw alone is positive. Dropping
    any one case leaves the lower bound at +0.29 or more.
  - It also holds against each designer in fixed: +1.34 [+0.35, +2.66] when Haiku designs, +0.38 [+0.20, +0.56] when
    Sonnet low designs.
- **GPT arm: the full − fixed result is fragile.**
  - Draw 2 alone gives [−0.01, +1.52]. Against fixed's better draw per case it is [−0.00, +0.90].
  - The case with the largest difference (covtype_T1_102, +2.92) is draw noise in fixed. Its draw 2 scored 69.00
    against 74.84 for draw 1.
  - On the 12 cases with an unlimited-depth forest pending it is +0.15, not resolved.
  - full − llm (+0.59) mostly reflects Sol stopping early in llm: it keeps the current best after 3.7 calls on
    average, and on those 12 cases llm − fixed is −0.39 [−0.55, −0.22].
- **Where gains can happen.** Six arm cases have a depth-limited forest pending. The prereg names 5 for the main
  study; the arms add higgs_T1_102, a main-study pilot case. On these six, full − fixed is +1.71 [+0.26, +3.58] for
  Claude (6 wins) and +1.38 [+0.12, +2.93] for GPT (3 wins, 3 ties). On the other 12 cases it is +0.44 [+0.25,
  +0.61] for Claude and +0.15, not resolved, for GPT. Most tables sit at the grid maximum, so the room is small.
- **The whole arms beat the main study on the same 15 cases.** full − main E1 full is:
  - Claude: +0.79 [+0.28, +1.61];
  - GPT: +0.65 [+0.09, +1.52].

  But the arms change the pool, effort, output ceiling, cap and number of draws all at once, so this is not an
  effect of the planner alone.
- **Provider difference (P10).**
  - full: Claude ahead by +0.16 points [+0.05, +0.28]. This is resolved but far inside the 1-point bound
    predicted. It costs $0.095 more per branch: $0.126 against $0.031, about four times as much.
  - llm: +0.56 [+0.33, +0.80], also inside the bound.
  - fixed: no difference (−0.14 [−0.74, +0.55]).
- **The models behave differently as planners. This is model behaviour: same code, limits, cases, ceiling and
  budget (audit SC-14).** Opus keeps exploring. In full, 75% of its branches ran a pipeline the model itself brought
  in. Sol stops early: 36%, about the same as Luna's 40% in the main study.
- **Bottom line.** On these tables, PHOENIX's ranking rule adds at most a fraction of a point beyond what a strong
  planner already gets. The rule's clearest benefit is cost: with Opus it reaches a slightly better result than llm
  for about half the dollars. A test that separates the planner from the rule would need a new arm in which fixed
  designs with the strong model. Not run; it is Kevin's call.

## Predictions (stated before the calls they concern)

| | Prediction | Result |
|---|---|---|
| P1 | Main full − fixed: mean 0 to +2, interval includes 0 | **As predicted**: +0.20 [−0.31, +0.95] |
| P2 | Main full − llm dollars negative | **As predicted**: −$0.0022 [−0.0039, −0.0009] |
| P3 | Main full − fixed dollars positive | **Reversed**: −$0.0025; fixed's 8 design calls (copies of existing pipelines, Amendment 6) cost more than full's ~3 calls |
| P4 | Main F0 − F1 near 0 for fixed | **As predicted**: −0.01 [−0.03, 0.00] |
| P7 | More branches run a model-brought pipeline than main E1 | **Claude yes** (full 75% vs 40%); **GPT no** (36%) |
| P8 | full − fixed not resolved in either arm; any gain on the depth-limited cases | **Contradicted** in both arms (positive). The gain sits on the depth-limited cases for GPT only; for Claude it is also positive on the other 12 |
| P9 | Arm cost per branch above main E1 and below $1.00 | **As predicted**: $0.03-0.23 against $0.002-0.004; max branch $0.26 (Claude), $0.08 (GPT) |
| P10 | The arms do not differ by more than 1 test point | **As predicted**: every arm − arm interval lies within ±1 |

Per-dataset rows in `report/tables.md` are descriptive.

## Disclosures

- **Validation and test.** On validation (what the methods select on), full − fixed was +0.97 (Claude) and +0.69
  (GPT); on test it is +0.86 and +0.56 (test and validation scores correlate at r = 0.997 over the 330 branches,
  which end on 51 distinct predictors). The test split was read once, by the evaluation, after all 330 branches were
  sealed (sealed manifest committed first: 6843063; scores: 8e4cb5c).
- **Draw-to-draw noise.** Two fresh draws of the same method on the same case differ by up to 5.85 points (GPT
  fixed, one case) and 1.81 (Claude llm); full's largest difference is 0.78 in both arms.
- **Status labels (Amendment 7).** fixed branches that used all 8 calls are reported as "call limit reached" (the
  engine stamps no_positive_feasible_plan). Counts:
  - main E1: 15 call limit, 15 no positive plan, 8 completed, 7 limits reached;
  - Claude: 36 / 36 / 11 / 25;
  - GPT: 36 / 36 / 36 / 0.
- **Ceilings and transport.** Every GPT call ran through OpenAI's background mode (its ceiling, 16,384, is above the
  streaming limit). Sol 6.1 barely reasons here: 0 thinking tokens in 146 Sol-low calls, and 12-40 on average at
  medium. Opus made 6 invalid replies of 388 (5 reasons over 500 characters) and Sonnet 5 of 144; GPT 0 of 616.
- **Cache writes.** Prompt-cache writes never read back are 14% of the Claude arm's dollars. GPT cache writes are 88%
  of the GPT arm's dollars, with 2% of written tokens read back. Both price tables charge 1.25× for writes, so no
  provider is favoured.
- **Disk incident (Claude arm, 02:58 UTC).** The disk filled; fitted-model scratch of finished calibration tasks was
  deleted. Branch predictors are intact (368 sampled hashes, and all 330 frozen predictors validated at the
  evaluation).
- **Code changed after the runs.** `autoagentnet/phoenix/report.py` (pairing within each draw) was merged after the
  last GPT call. The sealed check does not hash it, but the 454 frozen PHOENIX configs can no longer be preflighted
  again; none will be.
- **Analysis fixes before this summary.**
  - The call count per branch now comes from `state.json` (branches.csv has none), so the "call limit reached" label
    applies.
  - P7 is a per-branch rate.
  - `paired()` no longer counts empty case × dataset × withdrawn-model combinations in `nonzero`.
    - This fix (8df2234) came after the evaluation.
    - It changes only that column: SC-15 re-ran the pre-fix code, and all 54 contrast rows keep the same cases,
      means, intervals, verdicts and win/tie/loss counts.
- **Two paid processes ran at once** with Kevin's permission (the ledger is shared and re-read before every call).

## Spend

| Study | Calls | Dollars |
|---|---|---|
| Main study (calibration, pilot, E1, E2, E1b) | 616 | $0.56 |
| Claude arm (calibration + 108 branches) | 766 | $15.39 |
| GPT arm (calibration + 108 branches) | 616 | $3.99 |
| Sealed evaluation | 0 | $0 |

Files: `reports/phoenix_science/report/tables.md` (every table, generated by `analysis/phoenix_science.py`),
`branches.csv`, `paired.csv`, `reports/phoenix_science/evaluation/` (combined and sealed manifests, test scores),
`reports/phoenix_science/replay/` (one real F1 case, covtype_T1_101 full draw 1, in each arm; the replay reads
stored events and makes no model calls).
