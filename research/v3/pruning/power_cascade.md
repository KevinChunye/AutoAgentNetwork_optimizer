# Phase 3C (cascades): power of C1 and C2 by simulation

Written by `python -m analysis.pruning_cascade_power 100` (100 studies per lockbox size in the base scenario, 50 in the others; 300 search items; 1000 bootstrap draws; seed 0). The model, the tests and the power numbers are defined in the script's docstring. Holm floor: 0.025 (two tests).

| cross-vendor r | Luna accuracy | lockbox items | studies | void rate | C1 mean diff (pts) | C1 pass rate, floor | C1 power at 0, floor | C1b mean diff (pts) | C1b power at 0, floor | C2 mean diff (pts) | C2 pass rate, floor | dollar ratio | acceptance | accepted wrong |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.60 | 0.48 | 200 | 100 | 0.00 | 3.79 | 0.58 | 0.26 | 3.33 | 0.76 | 5.86 | 0.45 | 0.41 | 0.25 | 0.03 |
| 0.60 | 0.48 | 300 | 100 | 0.00 | 2.92 | 0.67 | 0.34 | 3.29 | 0.89 | 5.43 | 0.57 | 0.41 | 0.24 | 0.03 |
| 0.60 | 0.48 | 400 | 100 | 0.00 | 3.68 | 0.91 | 0.45 | 3.42 | 0.95 | 5.02 | 0.65 | 0.41 | 0.26 | 0.03 |
| 0.30 | 0.48 | 200 | 50 | 0.00 | 2.93 | 0.46 | 0.23 | 3.11 | 0.77 | 1.04 | 0.06 | 0.41 | 0.24 | 0.03 |
| 0.30 | 0.48 | 300 | 50 | 0.00 | 3.40 | 0.74 | 0.32 | 3.59 | 0.89 | 1.13 | 0.30 | 0.40 | 0.26 | 0.03 |
| 0.80 | 0.48 | 200 | 50 | 0.00 | 3.21 | 0.58 | 0.28 | 3.16 | 0.77 | 6.86 | 0.62 | 0.41 | 0.25 | 0.03 |
| 0.80 | 0.48 | 300 | 50 | 0.00 | 3.40 | 0.78 | 0.38 | 3.53 | 0.87 | 6.84 | 0.66 | 0.39 | 0.27 | 0.03 |
| 0.60 | 0.30 | 200 | 50 | 0.00 | 1.56 | 0.36 | 0.27 | 0.69 | 0.85 | -1.67 | 0.06 | 0.51 | 0.17 | 0.04 |
| 0.60 | 0.30 | 300 | 50 | 0.00 | 0.81 | 0.36 | 0.36 | 0.64 | 0.91 | -3.29 | 0.06 | 0.49 | 0.18 | 0.04 |

What the rule selected (lockbox 200):

| scenario | first round | escalation | studies |
|---|---|---|---|
| r 0.6, Luna 0.48 | luna x5 | sol61 | 68 |
| r 0.6, Luna 0.48 | luna x3 | sol61 | 21 |
| r 0.6, Luna 0.48 | luna personas x3 | sol61 | 5 |
| r 0.6, Luna 0.48 | haiku x5 | sol61 | 3 |
| r 0.6, Luna 0.48 | luna x5 | sonnet | 2 |
| r 0.6, Luna 0.48 | haiku x2 + luna x2 | sol61 | 1 |
| r 0.3, Luna 0.48 | luna x5 | sol61 | 37 |
| r 0.3, Luna 0.48 | luna x3 | sol61 | 7 |
| r 0.3, Luna 0.48 | luna personas x3 | sol61 | 4 |
| r 0.3, Luna 0.48 | haiku x5 | sol61 | 1 |
| r 0.3, Luna 0.48 | luna personas x3 | sonnet | 1 |
| r 0.8, Luna 0.48 | luna x5 | sol61 | 35 |
| r 0.8, Luna 0.48 | luna x3 | sol61 | 11 |
| r 0.8, Luna 0.48 | luna personas x3 | sol61 | 2 |
| r 0.8, Luna 0.48 | haiku x3 + luna x3 | sol61 | 1 |
| r 0.8, Luna 0.48 | haiku x5 | sol61 | 1 |
| r 0.6, Luna 0.3 | luna x5 | sol61 | 29 |
| r 0.6, Luna 0.3 | haiku x5 | sol61 | 7 |
| r 0.6, Luna 0.3 | haiku x2 + luna x2 | sol61 | 6 |
| r 0.6, Luna 0.3 | haiku personas x3 | sol61 | 3 |
| r 0.6, Luna 0.3 | haiku x3 | sol61 | 2 |
| r 0.6, Luna 0.3 | haiku personas x3 + luna personas x3 | sol61 | 1 |
| r 0.6, Luna 0.3 | luna personas x3 | sol61 | 1 |
| r 0.6, Luna 0.3 | luna x5 | sonnet | 1 |

## Decision (70% rule, base scenario, Holm floor)

- Lockbox of 200 BBEH items: C1 expl, C2 expl.
- Lockbox of 300 BBEH items: C1 expl, C2 expl.
- Lockbox of 400 BBEH items: C1 expl, C2 expl.
