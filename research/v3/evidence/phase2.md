# Evidence plan, Phase 2 analysis (steps 2.6-2.9)

Written by `python -m analysis.evidence_phase2`, committed in step 0.13 before any paid call. Definitions are in the script's docstring. Intervals 95%, item (or question) bootstrap, 2,000 draws, seed 0.

## H11 and the independence-per-dollar table (n_eff gain per dollar of one extra call)

| task | arm | gain per dollar (95%) |
|---|---|---|
| bbeh | resample | 546.3 (396.9 to 741.8) |
| bbeh | vendor | 6544.2 (4802.8 to 8782.9) |
| bbeh | reasoning | 516.5 (183.4 to 1394.9) |
| bbeh | prompt:careful | 437.3 (319.3 to 597.5) |
| bbeh | prompt:contrarian | 651.8 (467.1 to 872.3) |
| bbeh | prompt:quick | 812.0 (596.5 to 1095.1) |
| bbeh | prompt | 633.7 (497.2 to 795.5) |
| forecast | resample | 8.8 (5.9 to 12.5) |
| forecast | vendor | 678.9 (305.6 to 1127.0) |
| forecast | reasoning | nan (nan to nan) |
| forecast | prompt:careful | 18.1 (6.3 to 37.3) |
| forecast | prompt:contrarian | 37.6 (17.1 to 63.5) |
| forecast | prompt:quick | 20.5 (11.7 to 30.2) |
| forecast | prompt | 25.4 (14.1 to 40.0) |

H11 statistic (vendor minus prompt, mean over tasks): +3282.0 (+2386.6 to +4403.0), one-sided p 0.0000.

**H12 (expl), BBEH, 20 items with both arms:** thinking on minus off: rho +0.567 (-0.068 to +1.125), accuracy +35.0 points (+12.5 to +57.5). The thinking-on Haiku rows come from e23's 20-item probe only (it stopped on truncation, deviation E5): 8,000-token cap, truncated calls scored wrong, n = 20; descriptive.

**H15 (exploratory), net dollars per item, answer-escalate-abstain:**

| lambda | corrected | naive | difference (95%) | always Sonnet |
|---|---|---|---|---|
| 1 | +0.0217 | +0.0244 | -0.0026 (-0.0078 to +0.0029) | +0.0301 |
| 3 | -0.0004 | -0.0072 | +0.0067 (-0.0012 to +0.0139) | -0.0259 |
| 10 | -0.0262 | -0.0002 | -0.0260 (-0.0473 to -0.0080) | -0.2219 |

**H17 (expl), Dawid-Skene vs true accuracy (BBEH sealed):** haiku_nothink:base 58.1% vs 43.3% (+14.8), luna_none:base 16.5% vs 19.3% (-2.8), sol61_low:base 62.5% vs 97.3% (-34.8), sonnet_nothink:base 63.6% vs 72.0% (-8.4); every source within 10 points: no.

**H18 (expl), BBEH Brier:** naive share 0.189, correction 0.011, aggregator (haiku) 0.236; aggregator (haiku) minus naive share +0.047 (+0.014 to +0.080); aggregator (haiku) minus correction +0.225 (+0.191 to +0.259).

## Against Sol alone, and thinking on against off (deviation E3, audit 60; exploratory)

Difference = system minus comparator, paired over the n items where both have calls, with a 95% item-bootstrap interval: accuracy on BBEH (Phase 2 items), Brier on ForecastBench (sealed questions; negative = the system forecasts better). Dollar ratio = the system's dollars per item over the comparator's, on the same n items; an aggregator's dollars include the 12 panel calls it reads. The thinking-on Haiku rows come from e23's 20-item probe only (it stopped on truncation, deviation E5): 8,000-token cap, truncated calls scored wrong, n = 20; descriptive.

| task | system | minus | n | difference | low | high | dollar ratio |
|---|---|---|---|---|---|---|---|
| bbeh | Haiku thinking on, one call | Sol alone | 20 | -0.2500 | -0.4250 | -0.1000 | 0.4144 |
| bbeh | Haiku thinking on, one call | Haiku thinking off, one call | 20 | 0.3500 | 0.1250 | 0.5750 | 2.7036 |
| bbeh | aggregator (haiku) | Sol alone | 200 | -0.4400 | -0.5050 | -0.3750 | 4.0524 |
| forecast | aggregator (haiku) | Sol alone | 200 | 0.0057 | 0.0007 | 0.0118 | 3.7398 |
| forecast | aggregator (haiku) | the 12-call panel's pooled forecast | 200 | 0.0011 | -0.0022 | 0.0041 | 1.0298 |

**H16 (exploratory), half-Kelly against the freeze price, 100 sealed market questions:** mean log growth corrected +0.0078, naive -0.0067, difference +0.0144 (-0.0009 to +0.0280). No fees or spread are modeled.

## One-sided p-values (all exploratory since session E2's power re-run; no Holm family)

| test | p |
|---|---|
| H11 | 0.0000 |
| H15 | 0.0500 |
| H16 | 0.0340 |
