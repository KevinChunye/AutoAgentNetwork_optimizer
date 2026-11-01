# Power of AH1-AH4 by simulation (session E5, step 5.4; before sealing)

Written by `python -m analysis.anchor_power` (60 simulated anchors per row; the frozen tests of analysis/anchor_read.py; Holm at 5% over the non-void tests). Parameters: analysis/anchor_power.py (BASE, JUDGE). Assumed, not measured: haiku_high (math), luna_med, luna_none, sol_med.

Rows "measured (scans)": the pass rate is the test's power if the scans' accuracies are the truth. Under a test's null the pass rate is its false-positive rate. A test with power under 0.70 at the chosen n is demoted to exploratory (brief 5.4; for AH1 also the e52 scan's decision).

## AH3 limits from the noise floor (the simulated anchor follows the model exactly)

| per_task | items | reps | mae_mean | mae_p90 | upper_mean | upper_p90 | mae_limit | upper_limit |
|---|---|---|---|---|---|---|---|---|
| 50 | 293 | 30 | 0.0232 | 0.0297 | 0.0450 | 0.0508 | 0.0300 | 0.0600 |
| 80 | 413 | 30 | 0.0195 | 0.0257 | 0.0376 | 0.0430 | 0.0300 | 0.0500 |
| 110 | 533 | 30 | 0.0187 | 0.0243 | 0.0342 | 0.0390 | 0.0300 | 0.0400 |

## Pass rates

| per_task | items | scenario | test | pass_rate | mean_estimate | void_rate |
|---|---|---|---|---|---|---|
| 50 | 293 | measured (scans) | AH1 | 0.000 | 0.372 | 0.000 |
| 50 | 293 | measured (scans) | AH2 | 0.800 | 0.064 |  |
| 50 | 293 | measured (scans) | AH3 | 0.833 | 0.023 |  |
| 50 | 293 | measured (scans) | AH4 | 0.117 | 0.085 |  |
| 80 | 413 | measured (scans) | AH1 | 0.000 | 0.340 | 0.000 |
| 80 | 413 | measured (scans) | AH2 | 0.917 | 0.063 |  |
| 80 | 413 | measured (scans) | AH3 | 0.983 | 0.020 |  |
| 80 | 413 | measured (scans) | AH4 | 0.150 | 0.069 |  |
| 110 | 533 | measured (scans) | AH1 | 0.000 | 0.329 | 0.000 |
| 110 | 533 | measured (scans) | AH2 | 0.967 | 0.066 |  |
| 110 | 533 | measured (scans) | AH3 | 0.967 | 0.016 |  |
| 110 | 533 | measured (scans) | AH4 | 0.233 | 0.073 |  |
| 110 | 533 | AH1 at its null (R 0.5) | AH1 | 0.017 | 0.467 | 0.000 |
| 110 | 533 | AH1 at its null (R 0.5) | AH2 | 0.967 | 0.066 |  |
| 110 | 533 | AH1 at its null (R 0.5) | AH3 | 0.950 | 0.016 |  |
| 110 | 533 | AH1 at its null (R 0.5) | AH4 | 0.183 | 0.073 |  |
| 110 | 533 | AH1 if R were 0.8 | AH1 | 0.833 | 0.768 | 0.000 |
| 110 | 533 | AH1 if R were 0.8 | AH2 | 0.967 | 0.066 |  |
| 110 | 533 | AH1 if R were 0.8 | AH3 | 0.950 | 0.016 |  |
| 110 | 533 | AH1 if R were 0.8 | AH4 | 0.333 | 0.073 |  |
| 110 | 533 | AH2 at its null (depth = width) | AH1 | 0.000 | 0.329 | 0.000 |
| 110 | 533 | AH2 at its null (depth = width) | AH2 | 0.000 | -0.013 |  |
| 110 | 533 | AH2 at its null (depth = width) | AH3 | 0.967 | 0.017 |  |
| 110 | 533 | AH2 at its null (depth = width) | AH4 | 0.183 | 0.075 |  |
| 110 | 533 | AH4 at its null (no coupling, j1 0) | AH1 | 0.000 | 0.329 | 0.000 |
| 110 | 533 | AH4 at its null (no coupling, j1 0) | AH2 | 0.967 | 0.066 |  |
| 110 | 533 | AH4 at its null (no coupling, j1 0) | AH3 | 0.967 | 0.016 |  |
| 110 | 533 | AH4 at its null (no coupling, j1 0) | AH4 | 0.000 | -0.101 |  |

## AH3 with the vote-gain criterion (audit 71)

533 items (110 BBEH per task + 93 math); 30 simulated anchors per row. Limits from the noise floor: the 90th percentiles when the simulated anchor follows the model, rounded up (level to whole points, gain to half points).

| reps | mae_mean | mae_p90 | upper_p90 | gain_mean | gain_p90 | gain_upper_p90 | mae_limit | upper_limit | gain_limit | gain_upper_limit |
|---|---|---|---|---|---|---|---|---|---|---|
| 30 | 0.0187 | 0.0249 | 0.0397 | 0.0089 | 0.0119 | 0.0192 | 0.0300 | 0.0400 | 0.0150 | 0.0200 |

| scenario | reps | pass_rate | gain_mae_mean |
|---|---|---|---|
| model true | 30 | 0.800 | 0.009 |
| per-arm item effect (sd 1.5) | 30 | 0.467 | 0.012 |
| attractors on half the items + per-arm effect (sd 1.5) | 30 | 0.100 | 0.014 |

## AH3 with 6 three-call arms (audit 74: Haiku effort high has no math cells)

Frozen limits; 30 simulated anchors per row; the other arms as above.

| scenario | reps | pass_rate | gain_mae_mean |
|---|---|---|---|
| model true | 30 | 0.800 | 0.008 |
| per-arm item effect (sd 1.5) | 30 | 0.467 | 0.012 |
| attractors on half the items + per-arm effect (sd 1.5) | 30 | 0.200 | 0.013 |

## AH3 without Haiku effort high and Sol medium (audit 87: neither has math cells)

Frozen limits; 30 simulated anchors per row; the other arms as above.

| scenario | reps | pass_rate | gain_mae_mean |
|---|---|---|---|
| model true | 30 | 0.833 | 0.009 |
| per-arm item effect (sd 1.5) | 30 | 0.467 | 0.012 |
| attractors on half the items + per-arm effect (sd 1.5) | 30 | 0.167 | 0.014 |

