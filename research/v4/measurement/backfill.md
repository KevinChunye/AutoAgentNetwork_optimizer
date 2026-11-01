# Latency backfill: every run so far (session M1, estimates from totals)

Made by `analysis/latency_backfill.py` from every `results/*/calls.csv` and `results/*/agents.csv`; no grade column is read. Every number below is **estimated** from each call's total seconds and tokens (timing_source "estimated"); none is a stream measurement. Definitions are in the script's docstring and in `research/v4/measurement.md`.

- Calls: 35,456 rows in 123 runs, 26,500 of them live (cache hits are left out of every fit).
- Total seconds include the agent proxy path of the cloud sessions, the run's concurrency (usually 8) and the provider's load at that hour; they are not a clean single-request latency.
- Overhead (the intercept) estimates time to first token plus network and queue time; decode speed (1 / slope) estimates output tokens per second, thinking included. Intervals: 95% bootstrap over calls.

## Per arm (live calls)

| arm | model | calls | p50 s | p95 s | overhead s [95%] | decode tok/s [95%] | output p50 | thinking mean | context p50 | $/call | flag |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku | claude-haiku-5-5 | 45 | 8.8 | 35.5 | 0.46 [0.20, 1.04] | 230 [219, 256] | 1,952 | 0 | 1,374 | 0.00166 |  |
| haiku_high | claude-haiku-5-5 | 1,886 | 4.7 | 38.6 | 0.90 [0.84, 0.97] | 227 [224, 231] | 852 | 269 | 402 | 0.00107 |  |
| haiku_low | claude-haiku-5-5 | 2,418 | 4.7 | 23.9 | 0.82 [0.78, 0.87] | 218 [216, 220] | 830 | 28 | 433 | 0.00086 |  |
| haiku_max | claude-haiku-5-5 | 240 | 78.8 | 557.7 | 1.61 [0.76, 3.07] | 240 [233, 247] | 18,081 | 42,687 | 414 | 0.02150 |  |
| haiku_med | claude-haiku-5-5 | 86 | 5.8 | 41.7 | 0.91 [0.82, 1.52] | 214 [212, 236] | 946 | 1,741 | 410 | 0.00109 |  |
| haiku_nothink | claude-haiku-5-5 | 7,317 | 2.6 | 7.3 | 0.93 [0.90, 0.95] | 238 [235, 241] | 355 | 0 | 650 | 0.00033 |  |
| haiku_xhigh | claude-haiku-5-5 | 240 | 8.2 | 516.8 | 0.86 [0.68, 1.09] | 227 [224, 233] | 1,674 | 16,907 | 414 | 0.00863 |  |
| opus_max | claude-opus-5-5 | 50 | 24.0 | 178.4 | 1.43 [0.73, 2.21] | 112 [107, 113] | 2,400 | 4,993 | 410 | 0.11093 |  |
| opus_med | claude-opus-5-5 | 50 | 5.5 | 22.2 | 1.46 [1.10, 2.05] | 102 [93, 115] | 403 | 367 | 410 | 0.01572 |  |
| opus_nothink | claude-opus-5-5 | 100 | 5.0 | 17.9 | 1.56 [1.30, 1.82] | 106 [101, 113] | 365 | 0 | 389 | 0.01725 |  |
| sonnet_high | claude-sonnet-5-5 | 146 | 5.5 | 91.4 | 0.99 [0.70, 1.09] | 127 [119, 129] | 484 | 1,313 | 412 | 0.03089 |  |
| sonnet_low | claude-sonnet-5-5 | 743 | 4.1 | 13.4 | 0.90 [0.80, 0.99] | 122 [118, 126] | 390 | 0 | 393 | 0.00788 |  |
| sonnet_max | claude-sonnet-5-5 | 84 | 41.7 | 928.8 | 0.42 [-0.63, 1.07] | 140 [136, 147] | 5,232 | 27,462 | 479 | 0.27967 |  |
| sonnet_med | claude-sonnet-5-5 | 86 | 4.6 | 13.4 | 0.92 [0.71, 1.19] | 123 [114, 132] | 474 | 180 | 410 | 0.00884 |  |
| sonnet_nothink | claude-sonnet-5-5 | 1,495 | 3.6 | 12.9 | 1.00 [0.94, 1.05] | 127 [124, 129] | 319 | 0 | 481 | 0.00642 |  |
| sonnet_xhigh | claude-sonnet-5-5 | 57 | 11.3 | 564.9 | 0.94 [0.26, 1.20] | 136 [126, 140] | 1,587 | 11,268 | 479 | 0.11783 |  |
| luna_low_ev | gpt-6-luna | 1,579 | 5.3 | 19.0 | 1.31 [1.20, 1.44] | 96 [93, 99] | 357 | 0 | 272 | 0.00035 |  |
| luna_med | gpt-6-luna | 1,462 | 5.8 | 103.4 | 0.74 [0.69, 0.79] | 92 [91, 92] | 448 | 0 | 267 | 0.00104 |  |
| luna_none | gpt-6-luna | 4,549 | 1.8 | 4.9 | 1.13 [1.10, 1.17] | 116 [111, 119] | 76 | 0 | 352 | 0.00008 |  |
| sol61_low | gpt-6.1-sol | 3,417 | 5.0 | 77.9 | 1.43 [1.38, 1.49] | 33 [33, 34] | 111 | 0 | 325 | 0.00535 | slow: confirm by streaming |
| sol61_med | gpt-6.1-sol | 440 | 5.8 | 38.4 | 2.15 [1.91, 2.48] | 34 [31, 36] | 85 | 0 | 254 | 0.00324 | slow: confirm by streaming |
| gpt_small | nan | 5 | 7.1 | 10.4 | 1.26 [, ] | 97 [, ] | 617 | 0 | 105 | 0.00073 |  |
| luna_low | nan | 5 | 6.8 | 12.4 | 1.86 [, ] | 89 [, ] | 437 | 0 | 105 | 0.00064 |  |

## Stage profile of staged runs

Mean over tasks per stage, then max / mean over stages (1.0 = balanced). Cached rows keep their original measured seconds here.

| run | config | tasks | stages | context by stage | imbalance (max stage) | latency s by stage | imbalance (max stage) | $ by stage | imbalance (max stage) |
|---|---|---|---|---|---|---|---|---|---|
| p0_dense_haiku_nothink | k6-6-6-1 | 2 | propose,critique,refine,aggregate | 164.5,3470,4758,3912 | 1.55 (refine) | 4.256,5.524,3.218,2.103 | 1.46 (critique) | 0.001707,0.002474,0.002684,0.0006929 | 1.42 (refine) |
| p2_bbeh_dense | k6-6-6-1 | 20 | propose,critique,refine,aggregate | 1407,8831,6078,5499 | 1.62 (critique) | 8.423,6.239,4.433,2.281 | 1.58 (propose) | 0.00393,0.003847,0.003087,0.0008826 | 1.34 (propose) |
| p3_bbeh_dense | k6-6-6-1 | 40 | propose,critique,refine,aggregate | 1337,8854,5885,5399 | 1.65 (critique) | 7.977,5.801,4.38,2.163 | 1.57 (propose) | 0.003964,0.003789,0.003038,0.0008655 | 1.36 (propose) |
| p3_bbeh_dense_b | k6-6-6-1 | 20 | propose,critique,refine,aggregate | 1437,8225,5342,5302 | 1.62 (critique) | 7.101,4.627,4.379,2.177 | 1.55 (propose) | 0.003617,0.003358,0.002844,0.0008207 | 1.36 (propose) |
| p3_bbeh_noise | k6-6-6-1 | 10 | propose,critique,refine,aggregate | 1200,9030,5738,5254 | 1.70 (critique) | 7.513,5.971,4.23,2.276 | 1.50 (propose) | 0.004096,0.003815,0.003009,0.00087 | 1.39 (propose) |
| p3w_bbeh_dense | k6-6-6-1 | 20 | propose,critique,refine,aggregate | 1364,8418,5826,5470 | 1.60 (critique) | 7.444,5.138,4.539,2.392 | 1.53 (propose) | 0.003737,0.00367,0.003049,0.000895 | 1.32 (propose) |
| p4_bbeh_grid_a | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1254,9878,6327,5708 | 1.71 (critique) | 8.503,5.949,4.009,2.77 | 1.60 (propose) | 0.004503,0.004231,0.003311,0.0009717 | 1.38 (propose) |
| p4_bbeh_grid_b | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1145,8263,5220,4757 | 1.71 (critique) | 7.284,5.647,3.891,1.883 | 1.56 (propose) | 0.003731,0.003449,0.002696,0.0007787 | 1.40 (propose) |
| p4_bbeh_grid_c | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1273,8910,5548,5476 | 1.68 (critique) | 7.577,4.871,4.677,1.852 | 1.60 (propose) | 0.004012,0.003662,0.00305,0.0008488 | 1.39 (propose) |
| p4_bbeh_grid_d | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1399,8456,5671,5255 | 1.63 (critique) | 6.757,4.983,4.731,1.678 | 1.49 (propose) | 0.003744,0.003581,0.002897,0.0007944 | 1.36 (propose) |
| p4_bbeh_grid_e | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1485,7754,5464,5253 | 1.55 (critique) | 7.33,5.03,4.977,2.17 | 1.50 (propose) | 0.003366,0.003312,0.002817,0.0008187 | 1.31 (propose) |
| p4_bbeh_grid_f | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1295,7378,4950,5261 | 1.56 (critique) | 6.941,4.372,4.032,1.794 | 1.62 (propose) | 0.00324,0.003084,0.002826,0.0007825 | 1.30 (propose) |
| p4_bbeh_grid_g | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1420,9388,5414,5866 | 1.70 (critique) | 7.463,4.522,4.712,2.518 | 1.55 (propose) | 0.004204,0.003606,0.003147,0.0009312 | 1.41 (propose) |
| p4_bbeh_grid_h | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1549,8380,5540,4829 | 1.65 (critique) | 6.668,4.583,3.793,2.226 | 1.54 (propose) | 0.003658,0.003428,0.002587,0.0007506 | 1.40 (propose) |
| p4_bbeh_grid_i | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1261,9097,5752,5000 | 1.72 (critique) | 7.438,5.123,4.489,2.315 | 1.54 (propose) | 0.00411,0.003803,0.002853,0.0008594 | 1.41 (propose) |
| p4_bbeh_grid_j | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1320,9740,5380,6138 | 1.73 (critique) | 7.575,4.395,4.983,1.424 | 1.65 (propose) | 0.004412,0.0037,0.003328,0.0008593 | 1.44 (propose) |
| p4_bbeh_grid_k | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1408,8818,5701,4951 | 1.69 (critique) | 7.448,4.632,4.903,2.09 | 1.56 (propose) | 0.003923,0.003656,0.002746,0.0007961 | 1.41 (propose) |
| p4_bbeh_grid_l | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1369,9578,6141,5003 | 1.73 (critique) | 7.934,5.056,4.053,1.927 | 1.67 (propose) | 0.004315,0.004028,0.002869,0.0008109 | 1.44 (propose) |
| p4_bbeh_grid_m | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1464,9670,6440,5299 | 1.69 (critique) | 9.529,7.866,4.529,3.092 | 1.52 (propose) | 0.004331,0.004146,0.003022,0.0008549 | 1.40 (propose) |
| p4_bbeh_grid_n | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1145,8562,5684,6194 | 1.59 (critique) | 9.223,4.978,5.116,2.083 | 1.72 (propose) | 0.00388,0.003734,0.003496,0.0009785 | 1.28 (propose) |
| p4_bbeh_grid_o | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1267,8334,5564,4807 | 1.67 (critique) | 7.275,4.749,3.808,2.547 | 1.58 (propose) | 0.003727,0.003573,0.002721,0.0007881 | 1.38 (propose) |
| p4_bbeh_grid_p | k6-6-6-1 | 5 | propose,critique,refine,aggregate | 1201,9586,5660,5622 | 1.74 (critique) | 7.982,4.925,4.212,3.13 | 1.58 (propose) | 0.004374,0.003873,0.003178,0.0009484 | 1.41 (propose) |
