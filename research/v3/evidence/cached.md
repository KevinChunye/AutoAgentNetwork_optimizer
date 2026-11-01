# Evidence plan, step 0.9: the cached findings, recomputed

Written by `python -m analysis.evidence_cached` from results/*/results.csv with `autoagentnet/evidence/`; `tests/test_evidence_cached.py` pins every point estimate to two decimals. $0 spent. Intervals are 95% and resample items (2,000 draws, seed 0). Definitions are in the script's docstring; the two that had to be matched to the plan's numbers are: a plurality tie goes to the class reached first in call order, and "two of the 27 designs" averages each pair of designs' measure over the 351 pairs (pooling the pairs' cells instead gives 1.78 and phi 0.64).

| # | finding | recomputed | plan |
|---|---|---|---|
| 1 | Haiku repeat correlation rho, 100 items | 0.48 (0.38-0.57); ANOVA 0.48, beta-binomial ML 0.47; 5 calls = 1.71 independent | 0.48 (0.38-0.58); 1.71 |
| 2 | Items 0 of 5 / 5 of 5 right | 22 / 24, against 3.7 / 2.6 if independent (p_bar 0.482) | 22 (3.7 if independent); 24 (2.6) |
| 3a | Shared-error ratio, two Haiku calls (80) | 1.48 (1.30-1.73), phi 0.44 (+0.33 to +0.55), log error OR 1.88 | 1.48 (1.32-1.72), phi 0.44 |
| 3b | Two of the 27 designs (351 pairs, 80) | 1.80 (1.55-2.18), phi 0.65 (+0.55 to +0.73), log error OR 3.67 | 1.80 (1.56-2.18), phi 0.65 |
| 3c | Haiku and Sonnet (80) | 1.14 (0.86-1.43), phi 0.08 (-0.08 to +0.24), log error OR 0.36 | 1.14 (0.89-1.42), phi 0.08 (-0.07 to 0.24) |
| 4a | Naive share-agreeing confidence | gap +14.2 (+4.7 to +24.0), Brier 0.207 | +14.2 (+4.5 to +24.2), Brier 0.207 |
| 4b | Logistic on the share, cross-fitted by half | Brier 0.191, gap +0.6 (-9.0 to +10.5) | Brier 0.191, gap +0.6 (-9.3 to +10.2) |
| 4c | Adding Sonnet agrees | Brier 0.161, gain +0.031 (-0.005 to +0.067) | Brier 0.161, gain +0.031 (-0.005 to +0.066) |
| 8 | Haiku 3-of-5 cascade vs Sonnet, held-out 60-99 | 72.5% vs 72.5%, difference +0.0 (-15.0 to +15.0), cost ratio 0.52, escalated 0.23 (40 items) | 72.5% vs 72.5% at 52% of Sonnet's cost; difference -15 to +15 points (40 held-out items) |
| 5 | Plurality right when Sonnet agrees / not | 81% of 42 / 29% of 38 | 81% of 42 vs 29% of 38 |

Every point estimate matches the plan to its stated precision. Intervals come from a fresh bootstrap, so their ends can differ from the plan's in the second decimal.

## The frozen correction for H5

H5 carries the two-feature correction, fitted once on all 80 cached items and then frozen, to the 300 sealed BBEH items: logit P(plurality right) = -3.5513 + 4.0495 x share + 1.9921 x Sonnet agrees. On the sealed panel, "share" is the share of the 5 Haiku calls agreeing with their plurality and "Sonnet agrees" is the one Sonnet call matching it, exactly as here.
