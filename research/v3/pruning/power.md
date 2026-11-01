# Phase 3C: power of the lockbox tests P1-P3 by simulation

Written by `python -m analysis.pruning_power` (100 simulated studies per rule option in the base case, 40 in the others; 200 search and 200 lockbox items each; 1000 bootstrap draws; seed 0). The model, the tests, the two power numbers and the void rule are defined in the script's docstring. The Holm floor is alpha / 3 = 0.0167. Rule options: (a) Kevin's rule as written; (b) the same with selected networks at most 0.8x Sonnet's dollars (research/v3/pruning/selection_rule.md).

| test | scenario | studies | void rate | mean difference (points) | pass rate at Holm floor | pass rate at alpha | power at 0, Holm floor | power at 0, alpha |
|---|---|---|---|---|---|---|---|---|
| P1 | (a) as written; cross-vendor r 0.6, persona r 0.85 | 100 | 0.38 | 0.64 | 0.40 | 0.56 | 0.33 | 0.50 |
| P2 | (a) as written; cross-vendor r 0.6, persona r 0.85 | 100 | 0.09 | 6.94 | 0.60 | 0.70 | 0.09 | 0.19 |
| P3 | (a) as written; cross-vendor r 0.6, persona r 0.85 | 100 | 0.31 | 2.17 | 0.61 | 0.74 | 0.36 | 0.46 |
| P1 | (a) as written; cross-vendor r 0.3, persona r 0.85 | 40 | 0.33 | 1.81 | 0.48 | 0.56 | 0.27 | 0.43 |
| P2 | (a) as written; cross-vendor r 0.3, persona r 0.85 | 40 | 0.03 | 3.83 | 0.31 | 0.56 | 0.11 | 0.21 |
| P3 | (a) as written; cross-vendor r 0.3, persona r 0.85 | 40 | 0.23 | 0.00 | 0.48 | 0.61 | 0.49 | 0.56 |
| P1 | (a) as written; cross-vendor r 0.8, persona r 0.85 | 40 | 0.53 | 0.05 | 0.37 | 0.42 | 0.26 | 0.44 |
| P2 | (a) as written; cross-vendor r 0.8, persona r 0.85 | 40 | 0.20 | 8.31 | 0.59 | 0.81 | 0.09 | 0.19 |
| P3 | (a) as written; cross-vendor r 0.8, persona r 0.85 | 40 | 0.35 | 3.06 | 0.73 | 0.77 | 0.38 | 0.48 |
| P1 | (a) as written; cross-vendor r 0.6, persona r 1.0 | 40 | 0.30 | 2.50 | 0.61 | 0.71 | 0.43 | 0.57 |
| P2 | (a) as written; cross-vendor r 0.6, persona r 1.0 | 40 | 0.12 | 8.71 | 0.71 | 0.77 | 0.08 | 0.18 |
| P3 | (a) as written; cross-vendor r 0.6, persona r 1.0 | 40 | 0.35 | 0.83 | 0.42 | 0.62 | 0.36 | 0.47 |
| P1 | (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 0.85 | 100 | 1.00 | nan | nan | nan | nan | nan |
| P2 | (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 0.85 | 100 | 1.00 | nan | nan | nan | nan | nan |
| P3 | (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 0.85 | 100 | 1.00 | nan | nan | nan | nan | nan |
| P1 | (b) <= 0.8x Sonnet; cross-vendor r 0.3, persona r 0.85 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P2 | (b) <= 0.8x Sonnet; cross-vendor r 0.3, persona r 0.85 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P3 | (b) <= 0.8x Sonnet; cross-vendor r 0.3, persona r 0.85 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P1 | (b) <= 0.8x Sonnet; cross-vendor r 0.8, persona r 0.85 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P2 | (b) <= 0.8x Sonnet; cross-vendor r 0.8, persona r 0.85 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P3 | (b) <= 0.8x Sonnet; cross-vendor r 0.8, persona r 0.85 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P1 | (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 1.0 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P2 | (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 1.0 | 40 | 1.00 | nan | nan | nan | nan | nan |
| P3 | (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 1.0 | 40 | 1.00 | nan | nan | nan | nan | nan |

A void test is left out of its power and counted in its void rate: the void rate is how often the rule leaves nothing to test, and the power is for the studies where it does.

What the selection rule picked in the simulated studies:

| scenario | static has Sonnet or Sol | no static network | static is one Sonnet or Sol call | static costs more than Sonnet | static calls | static $ / Sonnet $ | dynamic $ / Sonnet $ | median tau |
|---|---|---|---|---|---|---|---|---|
| (a) as written; cross-vendor r 0.6, persona r 0.85 | 0.91 | 0.09 | 0.60 | 0.62 | 1.61 | 1.47 | 1.47 | 0.70 |
| (a) as written; cross-vendor r 0.3, persona r 0.85 | 0.97 | 0.03 | 0.62 | 0.68 | 2.20 | 1.57 | 1.35 | 0.60 |
| (a) as written; cross-vendor r 0.8, persona r 0.85 | 0.80 | 0.20 | 0.60 | 0.47 | 1.45 | 1.33 | 1.43 | 0.60 |
| (a) as written; cross-vendor r 0.6, persona r 1.0 | 0.88 | 0.12 | 0.42 | 0.70 | 1.73 | 1.58 | 1.44 | 0.60 |
| (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 0.85 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | nan | 0.51 | 0.60 |
| (b) <= 0.8x Sonnet; cross-vendor r 0.3, persona r 0.85 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | nan | nan | nan |
| (b) <= 0.8x Sonnet; cross-vendor r 0.8, persona r 0.85 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | nan | nan | nan |
| (b) <= 0.8x Sonnet; cross-vendor r 0.6, persona r 1.0 | 0.00 | 1.00 | 0.00 | 0.00 | 0.00 | nan | nan | nan |

## Decision (the plan's 70% rule: power at 0 at the Holm floor, base case)

- Rule (a) as written: confirmatory none; exploratory P1, P2, P3 (reported with intervals and one-sided p-values).
- Rule (b) <= 0.8x Sonnet: confirmatory none; exploratory P1, P2, P3 (reported with intervals and one-sided p-values).

The lockbox preregs (e31_lockbox_*) carry the decision for the rule in force (analysis/pruning_select.COST_BOUND; analysis/pruning_lockbox.STATUS).
