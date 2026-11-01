# Phase 3C: the selection rule (cascades; committed before the G2a read)

Session E4, Kevin's K2-K4. This replaces Phase 3B's static rule (kept below as superseded and descriptive). The rule is
code: `analysis/pruning_cascade.py` (`select`), with the cascade mechanics in `autoagentnet/pruning/cascade.py`, both
tested offline (`tests/test_pruning_cascade.py`, `tests/test_pruning_cascade_rule.py`). It runs once, when e13, e14
and e22 exist for both vendors, writes `research/v3/pruning/selected.json` and never rewrites it. The lockbox calls
(`e31_lockbox_*`) may be collected before it exists (K4); they are read only by `python -m analysis.pruning_cascade
lockbox`, which refuses until selected.json is committed unchanged.

## Terms

- **First round**: a fixed set of cheap calls asked in parallel: Haiku x3, Haiku x5, Luna x3, Luna x5, Haiku x3 +
  Luna x3 (H7's), Haiku x2 + Luna x2; on the 200 Phase 2 items also 3 Haiku personas, 3 Luna personas, and both.
- **Weighted vote** (K2): each call carries its source's weight, the log-odds of the source's accuracy on the search
  items (floored at 0.05, deviation 21); the answer class with the most weight wins; ties go to the class answered by
  the more accurate source.
- **Agreement share**: the weight behind the winning answer over the weight of all first-round calls.
- **Cascade policy** (first round, threshold t, escalation model Sonnet or Sol): accept the winning answer when the
  share is at least t, else call the escalation model once and use its answer.
- **Acceptance rate**: share of items answered by the first round. **Accepted-wrong rate**: share of all items accepted
  with a wrong answer.
- **Learn-then-Test** (arXiv 2110.01052): thresholds from strict (1.00) to loose (0.05) in steps of 0.05; at each, the
  one-sided exact binomial test of "accepted-wrong rate above alpha" at delta 0.05; keep the loosest threshold before
  the first failure to reject. Then with probability at least 0.95 the accepted-wrong rate is at most alpha. It needs
  labels: the label-free stand-in "differs from Sonnet" is stricter (33.8% against 20.0% at 3 of 5 on the cached items).

## The rule

1. For every first round and escalation model: cross-fit on two folds (balanced within each BBEH task, seed 0). On each
   fold the weights and the threshold (alpha 0.10) come from the other fold; pooled accuracy, dollars, acceptance,
   accepted-wrong, seconds, tokens and rounds are recorded, and acceptance at alpha 0.05 and 0.20 too.
2. A policy qualifies when its cross-fitted accuracy is at least Sonnet's minus 1 point on the same items and it
   accepts at least one item (deviation 23).
3. The selected policy is the qualifying one with the lowest cross-fitted dollars per item. None qualifies: C1 and C2
   are void (no fallback).
4. Frozen: the selected first round's weights and threshold (alpha 0.10; 0.05 and 0.20 recorded) on all its search
   items. If no threshold is certified there, C1 is void.
5. C2's pair: the mixed-vendor first round with the highest cross-fitted acceptance at alpha 0.10, and Haiku x5, each
   frozen with its own threshold.
6. ForecastBench (exploratory): first rounds without personas, escalating when the spread of the first round's
   log-odds is above s; per fold s is the cheapest grid value within +0.005 Brier of Sonnet; the selected policy is the
   cheapest whose cross-fitted Brier is within 0.005 of Sonnet's.
   Since deviation 29 (audit 60) the ForecastBench reference is Sol alone, not Sonnet, in the rule and the read.

The tests this selection feeds (C1, C2, the C3 check) are preregistered in `research/v3/pruning/prereg_cascade.md`.

---

# Superseded (session E3): Phase 3B's static rule, descriptive since K3


Session E3. The rule is code: `analysis/pruning_select.py` (`select`), tested offline in
`tests/test_pruning_select_lockbox.py`. This page states it in words. It runs once, after G2a and G2b are read and
before any lockbox call, and only when every Phase 1 and Phase 2 input run is present (BBEH and ForecastBench,
both vendors); it writes `research/v3/pruning/selected.json` and never rewrites it. The lockbox configs
(`e31_lockbox_*`) refuse a paid run until that file is committed (`requires` in the panel preflight). Revised
after audit 49 (research/audit_log.md): networks are matched across halves by dollar budget, not by step index,
and there is no fallback network.

## Search data

The 200 Phase 2 BBEH items (`bbeh_phase2.txt`) and the 200 sealed ForecastBench questions (`forecast_sealed.txt`),
where Phase 1 and Phase 2's persona runs put the 18 calls the lockbox repeats: Haiku x5 and Luna x5 (base prompt),
Sonnet x1 and Sol x1, and Haiku x3 and Luna x3 under the careful, contrarian and quick personas. Second Sonnet and
Sol calls, the aggregator and the reasoning arms are not part of the search. Two folds, balanced within each BBEH
task (ForecastBench: each source), seed 0.

## Static network (Kevin's rule)

1. Run NetAdapt (cut at least $0.0005 per item per step; one proposal per source: Haiku base, Luna base, Sonnet,
   Sol and each of the six persona sources; a source drops its last calls first, since its calls are
   exchangeable; each proposal's aggregator refitted) on each half. The aggregator is Kevin's: the plurality
   answer and a ridge logistic model of P(it is right) on per-source agreement shares (ForecastBench: mean
   log-odds times a fitted extremizing factor).
2. For each budget B (every step cost of either half's path), take each half's largest network costing at most B
   on its own half, fit it there and score it on the other half; pool the two halves (cross-fitted score and
   dollars at B).
3. Select the smallest B whose cross-fitted accuracy is at least Sonnet's minus 1 point (ForecastBench: whose
   Brier is at most Sonnet's plus 0.005); under option (b) below, also with cross-fitted dollars at most 0.8x
   Sonnet's.
4. Freeze the full-data NetAdapt path (all 200 items) read at that budget, refitted on all 200.
5. If no budget qualifies, there is no static network: P1 and P2 are void (reported as void, never tested on a
   substitute). If the frozen network is Sonnet alone, P1 is void (it would compare Sonnet with itself).

## Dynamic policy

Candidates: the cheapest-first call order and the greedy gain-per-dollar order, each with a stopping threshold
tau in {0.5, 0.6, 0.7, 0.75, 0.8, 0.85, 0.9, 0.95, never}. Select the candidate with the smallest cross-fitted
dollars whose cross-fitted accuracy (Brier) is at least the static network's (with no static network, at least
step 3's floor) and, under option (b), within the cost bound. If none qualifies, there is no dynamic policy and
P3 is void; P3 is also void when there is no static network. Freeze its order (recomputed on all 200 for the
greedy order), its tau and every prefix's aggregator, fitted on all 200.

## Also frozen

The dense refit (all 18 calls, weights fitted on all 200) and Sonnet alone, the comparators of P2 and P1.

## Kevin's open choice before G2a: a cost bound

Nothing in the rule as written bounds the selected network's cost by Sonnet's. In the power simulation
(`research/v3/pruning/power.md`), under option (a) the rule often freezes a single Sonnet call (P1 void) or a
single Sol call, which costs more than Sonnet. The code carries both options as `COST_BOUND` in
`analysis/pruning_select.py`:

- (a) `COST_BOUND = None`, the rule as written and the current setting: it answers "what is the cheapest network
  NetAdapt finds that is as good as Sonnet", and the answer may be Sonnet or something dearer;
- (b) `COST_BOUND = 0.8`: a selected network costs at most 0.8x Sonnet, so it is a saving by construction, and if
  nothing that cheap is as good as Sonnet the tests are void rather than run on a substitute.

power.md gives each option's void rates and powers; the lockbox preregs follow the option in force.
