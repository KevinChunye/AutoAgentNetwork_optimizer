# Phase 3C preregistration: cascades (session E4)

Committed before the G2a read. Kevin's decisions K2-K4 (research/log.md, session E4) rebuilt Phase 3C around cascades;
the static tests P1 and P2 left the prereg (their numbers stay as descriptives, `analysis/pruning_select.py` and
`analysis/pruning_lockbox.py`). Code: `autoagentnet/pruning/cascade.py` (mechanics), `analysis/pruning_cascade.py`
(selection and lockbox read), `analysis/pruning_cascade_power.py` (power). The rule in words:
`research/v3/pruning/selection_rule.md`. Departures from Kevin's text: `research/v3/pruning/deviations.md` 21-27.

## Question

Can a cheap first round that stops when it agrees enough, and otherwise asks one mid-size model, answer BBEH-type
questions about as well as Sonnet for less, with a certified rate of confidently wrong answers? And does mixing
vendors in the first round let more items stop early at the same certified risk?

## Definitions (plain words; notation in the code)

- **First round**: Haiku x3, Haiku x5, Luna x3, Luna x5, Haiku x3 + Luna x3, Haiku x2 + Luna x2; on the 200 Phase 2
  items also 3 Haiku personas, 3 Luna personas, and both.
- **Weighted vote** (K2): a call's weight is the log-odds of its source's search accuracy (floored at 0.05); the
  answer with the most weight wins; ties go to the more accurate source.
- **Agreement share**: weight behind the winning answer over the weight of all first-round calls.
- **Cascade policy**: (first round, threshold t, escalation model Sonnet or Sol); accept when the share is at least
  t, else ask the escalation model once.
- **Acceptance rate**: share of items the first round answers. **Accepted-wrong rate**: share of all items accepted
  with a wrong answer.
- **Learn-then-Test threshold** at alpha (arXiv 2110.01052): fixed-sequence exact binomial tests from t = 1.00 down
  to 0.05 at delta 0.05; with probability at least 0.95, the accepted-wrong rate at the chosen t is at most alpha.

## Selection (frozen into research/v3/pruning/selected.json before the lockbox is read)

Per first round and escalation model, cross-fitted on two task-balanced folds: thresholds at alpha 0.10 (0.05 and
0.20 recorded). A policy qualifies if its cross-fitted accuracy is at least Sonnet's minus 1 point and it accepts at
least one item; the cheapest qualifying policy is selected. None: C1 and C2 void. C2's pair: the mixed-vendor first
round with the highest cross-fitted acceptance at alpha 0.10, and Haiku x5, each with its own threshold.

## Tests on the BBEH lockbox (research/v3/evidence/sealed/lockbox_bbeh.txt)

- **C1** (non-inferiority): frozen policy minus Sonnet, accuracy, paired by item, above -5 points. One-sided
  item-bootstrap p-value (2,000 draws, stratified by task). The dollar ratio to Sonnet is reported with a 95%
  interval.
- **C2**: the frozen mixed-vendor first round's acceptance minus Haiku x5's, paired, above 0.
- **C3** (check, not a test): the frozen policy's accepted-wrong rate with its one-sided 95% Clopper-Pearson upper
  bound; flagged if the point estimate is above alpha 0.10.
- Holm at 5% over the confirmatory ones among C1 and C2. Their status comes from the power simulation (next
  section) by the plan's 70% rule.
- ForecastBench (exploratory): escalate when the spread of the first round's log-odds is above s; the frozen policy
  minus Sonnet in Brier, with an interval, its dollar ratio and escalation rate.

## Power

`python -m analysis.pruning_cascade_power 100` (research/v3/pruning/power_cascade.md): the evidence plan's simulated
panel at the probe's measured dollars per call, 300 search items, the whole selection rule as committed, C1 and C2 on
a simulated lockbox; 100 studies per lockbox size in the base scenario (cross-vendor latent r 0.6, Luna accuracy 0.48),
50 in the others (r 0.3, r 0.8, Luna 0.30). Holm floor 0.025.

| lockbox items | C1 power at 0, floor | C1 pass rate, floor | C1b power at 0, floor | C2 pass rate, floor | dollar ratio to Sonnet |
|---|---|---|---|---|---|
| 200 | 0.26 | 0.58 | 0.76 | 0.45 | 0.41 |
| 300 | 0.34 | 0.67 | 0.89 | 0.57 | 0.41 |
| 400 | 0.45 | 0.91 | 0.95 | 0.65 | 0.41 |

(Base scenario, re-run after audit 52 with the K-class weights and C1b. "Power at 0" is the chance of clearing the
floor if the difference were exactly 0; the 70% rule uses it for the non-inferiority tests, as for E3's. "Pass rate"
counts the model's own expected difference, +3 to +4 points for C1.) In the Luna-0.30 scenario C2's mean difference
turns negative (-2 to -3 points) while C1b keeps power 0.85-0.91.

**Decision (the plan's 70% rule, base scenario, Holm floor): C1 and C2 are exploratory at every lockbox size tried.**
Both are reported with 95% intervals and one-sided p-values, without a pass/fail claim; C3 stays a check. The
session-start estimate (C1 about 0.49 / 0.65 / 0.78 at 200 / 300 / 400) was too optimistic. Growing the BBEH
lockbox to about 300 would not make either test confirmatory, so the 99 unused BBEH pool items are not sealed for
it (saving about $2.75); 40 of them host audit 51's Luna check instead.

**C1b clears the 70% rule (0.76 at 200 items).** It is preregistered as exploratory because Kevin's K3 names C1; it
becomes confirmatory (Holm over C1b and C2, C1 descriptive) only if Kevin says so before the lockbox read, which
cannot happen before the Phase 1 and Phase 2 reads anyway (`select` refuses until they are committed).

Why C1 is weak: the rule usually selects Luna x5 escalating to Sol (68 of 100 base studies), because Sol costs less
than Sonnet at measured prices and is as accurate in the model. On escalated items the policy then answers with Sol
while C1 compares with Sonnet, so the paired differences carry two models' independent errors. A comparison of the
policy with its own escalation model (zero difference on every escalated item) would be far more powerful; it is
reported as an exploratory row and offered to Kevin as a confirmatory alternative for the November half.

## Blind collection (K4)

The e31_lockbox_* configs no longer wait for selected.json: their calls may be collected first. Until selected.json is
committed, nothing but each run's status.json is opened (status.json holds calls, parse, truncation, refusals and
dollars per source, never accuracy). `python -m analysis.pruning_cascade lockbox` refuses to read the lockbox calls
until selected.json is tracked in git and unchanged, and a test checks that no other analysis script reads them. The
auditor checks in git history that selected.json was committed before the lockbox read.

## Decision

C1, C1b and C2 are exploratory (power above), so no pass or fail is claimed; each is read from its 95% interval. If
C1's interval lies above -5 points, the selected cascade is a candidate default evidence layer for BBEH-type questions
at its measured dollar ratio, to be confirmed in November with a confirmatory design (C1b if Kevin agrees). If C2's
interval lies above 0, vendor mixing in the first round is kept as a candidate. C3 flagged: the threshold did not
transfer; report it and recalibrate before any use. A void test is reported as void, never replaced by a fallback.
Sonnet alone and Sol alone are reported beside the policy (accuracy and dollars), since the rule usually escalates to
Sol (audit 52).
