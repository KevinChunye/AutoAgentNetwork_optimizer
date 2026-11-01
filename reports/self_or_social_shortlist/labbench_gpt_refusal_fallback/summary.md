# Self-or-social pruning: test read

Test items: 144 (`results/sos_lab_gpt_test/calls.csv`). Frozen policy `7ee99724e790c5c5` (lam 30.0, use_family False), fitted on 144 dev items. Team ['A', 'B', 'C']; vote tie order [2, 1, 0].

## Accuracy and cost per method

| method | items | accuracy | usd_per_item | calls_per_item |
|---|---|---|---|---|
| full_review | 144 | 0.8889 | 0.0316 | 6 |
| random_matched | 144 | 0.8757 | 0.0214 | 3.458 |
| vote | 144 | 0.875 | 0.0182 | 3 |
| policy_lam100.0 | 144 | 0.875 | 0.0184 | 3.319 |
| policy | 144 | 0.875 | 0.0189 | 3.458 |
| policy_lam10.0 | 144 | 0.875 | 0.0189 | 3.458 |
| policy_lam3.0 | 144 | 0.875 | 0.0189 | 3.458 |
| policy_lam30.0 | 144 | 0.875 | 0.0189 | 3.458 |
| policy_lam0.0 | 144 | 0.875 | 0.019 | 3.479 |
| fixed_peer | 144 | 0.875 | 0.0308 | 6 |
| smartest_peer | 144 | 0.875 | 0.0308 | 6 |
| all_reflect | 144 | 0.875 | 0.0325 | 6 |
| single_B | 144 | 0.8681 | 0.0055 | 1 |
| self_only | 144 | 0.8681 | 0.0182 | 3.056 |
| forced_social | 144 | 0.8611 | 0.0312 | 6 |
| single_C | 144 | 0.8264 | 0.0122 | 1 |
| single_A | 144 | 0.6458 | 0.0005 | 1 |

## Policy minus each control (95% paired item bootstrap)

| method | baseline | n | d_acc | d_acc_lo | d_acc_hi | d_cost |
|---|---|---|---|---|---|---|
| policy | vote | 144 | 0 | -0.0208 | 0.0208 | 0.0007 |
| policy | all_reflect | 144 | 0 | -0.0417 | 0.0417 | -0.0136 |
| policy | fixed_peer | 144 | 0 | -0.0347 | 0.0347 | -0.0118 |
| policy | random_matched | 144 | -0.0007 | -0.0233 | 0.0208 | -0.0024 |
| policy | full_review | 144 | -0.0139 | -0.0486 | 0.0208 | -0.0126 |
| policy | self_only | 144 | 0.0069 | -0.0139 | 0.0278 | 0.0007 |
| policy | forced_social | 144 | 0.0139 | -0.021 | 0.0556 | -0.0123 |
| policy | smartest_peer | 144 | 0 | -0.0347 | 0.0347 | -0.0118 |
| policy | single_A | 144 | 0.2292 | 0.1528 | 0.3056 | 0.0185 |
| policy | single_B | 144 | 0.0069 | -0.0347 | 0.0486 | 0.0134 |
| policy | single_C | 144 | 0.0486 | 0.0069 | 0.0903 | 0.0067 |
| fixed_peer | all_reflect | 144 | 0 | -0.0278 | 0.0278 | -0.0018 |

## What the policy did

| action | share |
|---|---|
| stop | 0.847 |
| consult | 0.153 |

| sender | receiver | count |
|---|---|---|
| B | A | 38 |
| C | A | 21 |
| C | B | 7 |

## Money

- New spend of the test runs (live calls): $10.2333.
- Calibration's logical dollars (every dev call, first answers included): $9.5292.
- Deploying the policy on T items costs calibration + T x $0.01894.
