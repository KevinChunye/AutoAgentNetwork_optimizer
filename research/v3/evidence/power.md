# Evidence plan, step 0.10: power by simulation

## Session E2: Kevin's decisions and the re-run (before any paid call)

Kevin's decisions (session E2): H5 keeps the widened bounds; H8 exploratory; H7 = accuracy non-inferiority of the 4-of-6
cascade at -8 points, its cost ratio reported, not tested; H1 a sanity check outside Holm; H4 replaced by the paired gap
test (Haiku 5-call share minus a mixed 5-call share), confirmatory only if its power is at least 0.70 at the Holm level;
Phase 1 family H4, H5, H6, H7. The Phase 2 tests H11, H15 and H16 (H16 on all 393 market questions: 50 fit, 343 scored)
move to exploratory if under 0.70.

**First pass, family of 4 (Holm floor alpha / 4 = 0.0125), 300 studies per row** (cross-vendor latent r 0.3 / 0.6 / 0.8):
- **H4 (new):** 0.90 / **0.53** / 0.17. The mixed 5-call share is less overconfident than Haiku's: simulated
  gaps at r 0.6 are Haiku 5 +15.2 points and mixed 5 +10.2, a difference of +5.0 with a 95% half-width of 4.2 (+8.3 at
  r 0.3, +2.4 at r 0.8). **Under 0.70 in the base scenario: H4 moves to exploratory** (it is reported with its
  interval). The old 12-call H4 had power about 0.
- **H5:** 0.83 under exact transfer (0.58 if the intercept is off by 0.2); at the plan's bounds 0.23. Confirmatory.
- **H6:** 1.00 in every scenario. Confirmatory.
- **H7 (accuracy leg, -8 points):** 0.80 / **0.68** / 0.60. Kevin made H7 confirmatory (B3); it stays so. With the cost
  leg it would have been 0.00 / 0.06 / 0.28.
- **H1** (sanity check): at least 0.97 in every scenario.

**Phase 2, family of 3 (alpha / 3 = 0.0167):**
- **H11** (vendor minus prompt gain per dollar, 200 BBEH + 200 ForecastBench; 150 studies per row): **0.45** when Luna's
  latent correlation with Haiku is 0.6 and a persona's 0.85; 0.85 if personas change nothing (0.6 / 1.0); 0.68 at 0.3 /
  0.7; 0.05 at 0.8 / 0.85. Under 0.70 in the base scenario: **exploratory**.
- **H15** (answer-escalate-abstain, corrected minus naive, lambda 3): 0.00-0.01. With thresholds chosen by
  cross-fitting, any monotone recalibration of the same score gives the same policy, so H15 can only detect a better
  *ranking* of items; the Haiku and Luna agreeing shares rank items almost as the plain 6-call share does. A variant with
  the decision-theory threshold (answer iff confidence >= lambda / (1 + lambda)) is not better powered here (0.01-0.03).
  In the model the corrected policy even earns less (about -$0.005 per item): fitting the correction on half of 300
  items adds noise and no ranking. **Exploratory.**
- **H16** (half-Kelly, corrected minus naive, 343 scored): 0.01-0.03 in every scenario, and the corrected bankroll grows
  less on average (-0.002 to -0.007 log growth per question): a recalibration fitted on 50 market questions is too noisy
  to beat the plain mean when the forecasts lean on the price. **Exploratory.**
- So **Phase 2 has no confirmatory test**; H11, H15 and H16 are reported with intervals. Kevin is told.
- How these demotions move with their assumptions (audit 48: H11 with the persona correlation, H15 with unequal
  vendors, H16 with a cross-fitted fit on all 393 questions) is in research/v3/evidence/power_sensitivity.md.

**Final families:** Phase 1 = H5, H6, H7 (Holm over 3; the table below uses alpha / 3 = 0.0167); Phase 2 = none.
In the final table (alpha / 3): H5 0.84 under exact transfer; H6 1.00; H7 (accuracy leg) 0.71 in the base scenario,
0.81 at latent r 0.3 and 0.63 at 0.8; H4 would be 0.56 even at alpha / 3, so it stays exploratory.


Written by `python -m analysis.evidence_power` (300 simulated studies per Phase 1 row and per H16 row, 150 per H11 and H15 row; 400 bootstrap draws each, seed 0). The model, its inputs and the Holm range are in the script's docstring. "Holm floor" is alpha / (family size): the threshold a test meets if it has the smallest p-value of its family (Phase 1: 3 tests, 0.0167; Phase 2: 3, 0.0167), which is where the plan's 70% rule is applied. "alpha" is the most lenient Holm step.

| test | scenario | items | power at Holm floor | power at alpha | detail |
|---|---|---|---|---|---|
| H4 (E2: Haiku 5 gap minus mixed 5 gap) | cross-vendor latent r 0.3 | 300 | 0.91 | 0.97 | difference +8.3 pts (half-width 4.6); gaps: Haiku5 +15.2, Luna5 +15.3, mixed5 +6.9, 12-call -6.1 |
| H6 | cross-vendor latent r 0.3 | 300 | 1.00 | 1.00 | Brier gain +0.089, half-width 0.026 |
| H7 (accuracy leg, -8 pts) | cross-vendor latent r 0.3 | 300 | 0.81 | 0.94 | cascade - Sonnet -0.2 pts, half-width 4.8; cost ratio 0.78 (reported, not tested since E2); escalation 0.48 |
| H1 (sanity check, outside Holm) | cross-vendor latent r 0.3 | 300 | 1.00 | 1.00 | rho 95% half-width 0.058 |
| old H4: 12-call gap > 0 (replaced) | cross-vendor latent r 0.3 | 300 | 0.00 | 0.00 | 12-call gap -6.1 pts |
| H7 with the 70% cost leg (dropped) | cross-vendor latent r 0.3 | 300 | 0.00 | 0.00 | for the record |
| H4 (E2: Haiku 5 gap minus mixed 5 gap) | cross-vendor latent r 0.6 | 300 | 0.56 | 0.72 | difference +5.0 pts (half-width 4.2); gaps: Haiku5 +15.2, Luna5 +15.3, mixed5 +10.2, 12-call -1.8 |
| H6 | cross-vendor latent r 0.6 | 300 | 1.00 | 1.00 | Brier gain +0.091, half-width 0.026 |
| H7 (accuracy leg, -8 pts) | cross-vendor latent r 0.6 | 300 | 0.71 | 0.84 | cascade - Sonnet -0.7 pts, half-width 5.1; cost ratio 0.73 (reported, not tested since E2); escalation 0.44 |
| H1 (sanity check, outside Holm) | cross-vendor latent r 0.6 | 300 | 1.00 | 1.00 | rho 95% half-width 0.058 |
| old H4: 12-call gap > 0 (replaced) | cross-vendor latent r 0.6 | 300 | 0.00 | 0.00 | 12-call gap -1.8 pts |
| H7 with the 70% cost leg (dropped) | cross-vendor latent r 0.6 | 300 | 0.07 | 0.09 | for the record |
| H4 (E2: Haiku 5 gap minus mixed 5 gap) | cross-vendor latent r 0.8 | 300 | 0.20 | 0.35 | difference +2.4 pts (half-width 4.0); gaps: Haiku5 +15.4, Luna5 +15.3, mixed5 +13.0, 12-call +1.2 |
| H6 | cross-vendor latent r 0.8 | 300 | 1.00 | 1.00 | Brier gain +0.090, half-width 0.026 |
| H7 (accuracy leg, -8 pts) | cross-vendor latent r 0.8 | 300 | 0.63 | 0.81 | cascade - Sonnet -1.1 pts, half-width 5.3; cost ratio 0.71 (reported, not tested since E2); escalation 0.41 |
| H1 (sanity check, outside Holm) | cross-vendor latent r 0.8 | 300 | 0.99 | 1.00 | rho 95% half-width 0.058 |
| old H4: 12-call gap > 0 (replaced) | cross-vendor latent r 0.8 | 300 | 0.03 | 0.10 | 12-call gap +1.2 pts |
| H7 with the 70% cost leg (dropped) | cross-vendor latent r 0.8 | 300 | 0.29 | 0.36 | for the record |
| H5 (+-0.6, 0.5-1.5) | intercept shift 0.0 | 300 | 0.84 | 0.94 | slope 90% half-width 0.19, intercept sd 0.15 |
| H5 at the plan's bounds (reported) | intercept shift 0.0 | 300 | 0.29 | 0.64 | +-0.4 and 0.6-1.4 |
| H5 (+-0.6, 0.5-1.5) | intercept shift 0.2 | 300 | 0.62 | 0.80 | slope 90% half-width 0.19, intercept sd 0.15 |
| H5 at the plan's bounds (reported) | intercept shift 0.2 | 300 | 0.11 | 0.32 | +-0.4 and 0.6-1.4 |
| H8 (exploratory) | forecasts shrunk x0.6 | 200 | 0.07 | 0.14 | fitted a 1.30 |
| H8 (exploratory) | forecasts shrunk x0.8 | 200 | 0.02 | 0.05 | fitted a 0.94 |
| H11 | cross-vendor r 0.6, persona r 0.85 | 200 + 200 | 0.45 | 0.61 | vendor minus prompt gain per dollar +118 |
| H11 | cross-vendor r 0.6, persona r 1.0 | 200 + 200 | 0.85 | 0.94 | vendor minus prompt gain per dollar +186 |
| H11 | cross-vendor r 0.8, persona r 0.85 | 200 + 200 | 0.05 | 0.11 | vendor minus prompt gain per dollar +22 |
| H11 | cross-vendor r 0.3, persona r 0.7 | 200 + 200 | 0.68 | 0.83 | vendor minus prompt gain per dollar +214 |
| H15 (lambda 3) | cross-vendor latent r 0.3 | 300 | 0.01 | 0.02 | corrected minus naive -0.0055 $/item |
| H15 variant: threshold lambda/(1+lambda), not cross-fitted (information only) | cross-vendor latent r 0.3 | 300 | 0.01 | 0.01 | corrected minus naive -0.0005 $/item |
| H15 (lambda 3) | cross-vendor latent r 0.6 | 300 | 0.01 | 0.01 | corrected minus naive -0.0053 $/item |
| H15 variant: threshold lambda/(1+lambda), not cross-fitted (information only) | cross-vendor latent r 0.6 | 300 | 0.01 | 0.03 | corrected minus naive -0.0002 $/item |
| H15 (lambda 3) | cross-vendor latent r 0.8 | 300 | 0.00 | 0.01 | corrected minus naive -0.0057 $/item |
| H15 variant: threshold lambda/(1+lambda), not cross-fitted (information only) | cross-vendor latent r 0.8 | 300 | 0.03 | 0.11 | corrected minus naive +0.0007 $/item |
| H16 (50 fit, 343 scored) | anchor on price 0.5, own signal x0.6 | 343 | 0.01 | 0.02 | corrected minus naive log growth -0.0066 |
| H16 (50 fit, 343 scored) | anchor on price 0.3, own signal x0.6 | 343 | 0.01 | 0.02 | corrected minus naive log growth -0.0059 |
| H16 (50 fit, 343 scored) | anchor on price 0.5, own signal x1.0 | 343 | 0.01 | 0.04 | corrected minus naive log growth -0.0038 |
| H16 (50 fit, 343 scored) | anchor on price 0.3, own signal x1.3 | 343 | 0.03 | 0.07 | corrected minus naive log growth -0.0023 |

## Session E1, the first pass: what this step changed before sealing (the plan's rule: under 70% power, change counts or margins)

A first pass with the plan's settings (6 tests in the Phase 1 family, alpha / 6 = 0.0083; the table below re-runs
the plan's margins beside the new ones):
- **H1, H6:** power at least 0.96 in every scenario. Unchanged.
- **H7** (cascade non-inferior to Sonnet at -6 points): power 0.24-0.48. The cascade minus Sonnet interval at 300
  items is about +-5 points (the plan's target, +-5.5, holds), but a margin of 6 sits too close to it. **Margin set to
  -8 points**: in the final table (alpha / 5) power is 0.70 in the base scenario, 0.82 at latent r 0.3 and 0.57 at
  0.8 (an exploratory pass at -10 points gave 0.79-0.92).
  The 70% cost condition is unchanged.
- **H5** (frozen correction transfers; TOST intercept +-0.4, slope 0.6-1.4): power 0.14 even when the correction
  transfers exactly. The intercept's bootstrap sd at 300 items is about 0.15 log-odds, so +-0.4 cannot be shown at
  alpha / 6. **Bounds set to intercept +-0.6 and slope 0.5-1.5**: power 0.81 under exact transfer and 0.54 if the true
  intercept is off by 0.2 (final table, alpha / 5).
- **H8** (extremizing lowers Brier on 200 sealed questions): power 0.003-0.11 for forecasts shrunk by 0.5-0.8, and
  still 0.02-0.15 with 600 cross-fitted questions. A Brier gain from an extremizing factor near 1.2 is too small to
  detect at any count this budget allows. **H8 moves to exploratory** (reported with its interval), so the Phase 1
  Holm family is H1, H4, H5, H6, H7 (alpha / 5 = 0.01). This is outside the rule's "counts or margins", so Kevin
  confirms it at G0.
- **H4** (the 12-call panel's naive share overstates accuracy): power near 0, because in the model, calibrated to
  reproduce Haiku's cached +14-point gap from five calls, the mixed 12-call panel's share is overconfident by only
  -6 to +1.5 points. More items cannot fix a near-zero effect. H4 stays confirmatory as preregistered; the
  simulation predicts it fails, which would itself be a finding (vendor mixing removes the "k of n" overconfidence).
  A failing H4 still takes one Holm slot: the smallest p-value is tested at alpha / 5 rather than alpha / 4 (audit 47).
- **H7's cost leg** (audit 47): the rows above test accuracy only. With the plan's per-call estimates the six cheap
  calls cost 0.29 of a Sonnet call, so the cost ratio is 0.29 + the escalation rate, and the simulated escalation rate
  (fewer than 4 of 6 agreeing) is above 0.41 in every scenario: H7 as preregistered is predicted to fail on cost (row
  "H7_both_legs"). The probe's measured costs (step 1.1) and the real agreement rate decide it; options for Kevin
  before step 1.3: keep it (and report the likely failure), escalate unless 3 of 6 agree, or raise the cost bound.
- **H1** (audit 47) compares a model's repeat calls with another model, so it measures "same model" more than "same
  vendor"; its power is near 1 in every scenario. H2 (latent r, same-vendor cross-tier vs cross-vendor same-tier)
  is the informative vendor comparison. Unchanged pending Kevin.

Precision targets at 300 items: rho 95% half-width about 0.06 (target +-0.06); calibration slope 90% half-width
about 0.19 (target +-0.25); cascade minus Sonnet about +-5 points (target +-5.5); Brier gain about +-0.026 (target
+-0.02, missed slightly). The model's inputs for Luna, Sol and Sonnet's repeat correlation are assumptions until
Phase 1 measures them.
