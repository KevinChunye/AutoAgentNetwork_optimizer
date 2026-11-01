# Evidence plan: power sensitivity of the Phase 2 demotions (audit 48)

Written by `python -m analysis.evidence_power --sensitivity` (150 simulated studies per row, 400 bootstrap draws each, seed 1). Holm floor alpha / 3 = 0.0167. The models are those of power.md; only the named assumption moves.

- **H11** clears 0.70 only if a persona call is almost as correlated with the base call as a resample (persona latent r at or above about 0.95); the base scenario's 0.85 is an assumption, not a measurement.
- **H15** depends on the two vendors differing: when Haiku and Luna are equally accurate, their agreeing shares rank items as the plain 6-call share does and the test has no effect to find; a more accurate Luna gives the correction something to rank by.
- **H16** with its best design (cross-fitting over all 393 questions) and a panel that ignores the price and is overconfident.

| test | scenario | items | power at Holm floor | power at alpha | detail |
|---|---|---|---|---|---|
| H11 | cross-vendor r 0.6, persona r 0.85 | 200 + 200 | 0.47 | 0.67 | vendor minus prompt gain per dollar +127 |
| H11 | cross-vendor r 0.6, persona r 0.9 | 200 + 200 | 0.51 | 0.69 | vendor minus prompt gain per dollar +136 |
| H11 | cross-vendor r 0.6, persona r 0.95 | 200 + 200 | 0.71 | 0.84 | vendor minus prompt gain per dollar +158 |
| H11 | cross-vendor r 0.6, persona r 1.0 | 200 + 200 | 0.87 | 0.94 | vendor minus prompt gain per dollar +178 |
| H15 (lambda 3) | cross-vendor r 0.6, Haiku accuracy 0.48, Luna 0.48 | 300 | 0.01 | 0.02 | corrected minus naive -0.0064 $/item |
| H15 (lambda 3) | cross-vendor r 0.6, Haiku accuracy 0.48, Luna 0.58 | 300 | 0.07 | 0.11 | corrected minus naive -0.0027 $/item |
| H15 (lambda 3) | cross-vendor r 0.6, Haiku accuracy 0.48, Luna 0.65 | 300 | 0.21 | 0.29 | corrected minus naive +0.0026 $/item |
| H16, two-fold cross-fit on all 393 | anchor on price 0.0, own signal x1.5 | 393 | 0.05 | 0.12 | corrected minus naive log growth +0.0057 |
| H16, two-fold cross-fit on all 393 | anchor on price 0.0, own signal x2.0 | 393 | 0.12 | 0.28 | corrected minus naive log growth +0.0124 |
| H16, two-fold cross-fit on all 393 | anchor on price 0.3, own signal x1.5 | 393 | 0.07 | 0.15 | corrected minus naive log growth +0.0047 |
| H16, two-fold cross-fit on all 393 | anchor on price 0.5, own signal x0.6 | 393 | 0.00 | 0.03 | corrected minus naive log growth -0.0016 |
