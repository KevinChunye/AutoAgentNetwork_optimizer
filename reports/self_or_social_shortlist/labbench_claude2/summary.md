# Self-or-social pruning: test read

Test items: 144 (`results/sos_lab_claude2_test/calls.csv`). Frozen policy `0130676ba8a2d1d8` (lam 10.0, use_family False), fitted on 144 dev items. Team ['A', 'B', 'C']; vote tie order [1, 2, 0].

## Accuracy and cost per method

| method | items | accuracy | usd_per_item | calls_per_item |
|---|---|---|---|---|
| forced_social | 144 | 0.8542 | 0.043 | 6 |
| fixed_peer | 144 | 0.8542 | 0.0431 | 6 |
| full_review | 144 | 0.8472 | 0.0437 | 6 |
| random_matched | 144 | 0.8417 | 0.0238 | 3.431 |
| smartest_peer | 144 | 0.8333 | 0.0434 | 6 |
| all_reflect | 144 | 0.8333 | 0.0438 | 6 |
| policy_lam3.0 | 144 | 0.8264 | 0.0276 | 3.903 |
| policy_lam0.0 | 144 | 0.8264 | 0.0345 | 4.569 |
| policy | 144 | 0.8194 | 0.0217 | 3.431 |
| policy_lam10.0 | 144 | 0.8194 | 0.0217 | 3.431 |
| policy_lam100.0 | 144 | 0.8125 | 0.0206 | 3.333 |
| policy_lam30.0 | 144 | 0.8125 | 0.0206 | 3.333 |
| self_only | 144 | 0.8125 | 0.0222 | 3.382 |
| vote | 144 | 0.8056 | 0.0203 | 3 |
| single_C | 144 | 0.7847 | 0.0092 | 1 |
| single_B | 144 | 0.7847 | 0.01 | 1 |
| single_A | 144 | 0.7222 | 0.001 | 1 |

## Policy minus each control (95% paired item bootstrap)

| method | baseline | n | d_acc | d_acc_lo | d_acc_hi | d_cost |
|---|---|---|---|---|---|---|
| policy | vote | 144 | 0.0139 | -0.0208 | 0.0486 | 0.0015 |
| policy | all_reflect | 144 | -0.0139 | -0.0625 | 0.0278 | -0.0221 |
| policy | fixed_peer | 144 | -0.0347 | -0.0764 | 0.0002 | -0.0213 |
| policy | random_matched | 144 | -0.0222 | -0.0476 | -0.001 | -0.0021 |
| policy | full_review | 144 | -0.0278 | -0.0694 | 0.0139 | -0.022 |
| policy | self_only | 144 | 0.0069 | -0.0278 | 0.0417 | -0.0005 |
| policy | forced_social | 144 | -0.0347 | -0.0764 | 0.0002 | -0.0213 |
| policy | smartest_peer | 144 | -0.0139 | -0.0556 | 0.0278 | -0.0217 |
| policy | single_A | 144 | 0.0972 | 0.0278 | 0.1736 | 0.0208 |
| policy | single_B | 144 | 0.0347 | 0 | 0.0694 | 0.0117 |
| policy | single_C | 144 | 0.0347 | -0.0139 | 0.0903 | 0.0125 |
| fixed_peer | all_reflect | 144 | 0.0208 | -0.0069 | 0.0556 | -0.0008 |

## What the policy did

| action | share |
|---|---|
| stop | 0.856 |
| consult | 0.144 |

| sender | receiver | count |
|---|---|---|
| A | B | 7 |
| B | A | 48 |
| B | C | 7 |

## Money

- New spend of the test runs (live calls): $16.2999.
- Calibration's logical dollars (every dev call, first answers included): $15.6416.
- Deploying the policy on T items costs calibration + T x $0.02172.
