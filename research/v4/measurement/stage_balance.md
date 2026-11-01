# Stage balance and accuracy at matched tokens (session M1, 5.3, exploratory)

Made by `analysis/stage_balance.py`: the pilot's P4 factorial grid (27 configurations x 80 BBEH gate items, Haiku thinking off) replayed exactly from the call cache ($0; the replay refuses any uncached call). Definitions are in the script's docstring.

## Does a lower imbalance ratio reach higher accuracy at the same total tokens?

Accuracy regressed on log(total tokens) and one imbalance ratio, one point per configuration; 95% bootstrap over tasks (B = 500).

| imbalance of | coefficient (accuracy per unit of ratio) | 95% interval |
|---|---|---|
| context | -0.000 | [-0.074, +0.072] |
| latency | +0.211 | [-0.126, +0.567] |
| usd | -0.019 | [-0.069, +0.036] |

Spearman correlations over the 27 configurations:

| index | accuracy | imbalance_context | imbalance_latency | imbalance_usd | total_tokens |
|---|---|---|---|---|---|
| accuracy | 1.0 | 0.03 | 0.46 | -0.25 | 0.66 |
| imbalance_context | 0.03 | 1.0 | 0.62 | 0.84 | 0.07 |
| imbalance_latency | 0.46 | 0.62 | 1.0 | 0.25 | 0.32 |
| imbalance_usd | -0.25 | 0.84 | 0.25 | 1.0 | -0.1 |
| total_tokens | 0.66 | 0.07 | 0.32 | -0.1 | 1.0 |

## Configurations

| config_id | agents | tasks | accuracy | total_tokens | usd | critical_path_s | peak_context | imbalance_context | imbalance_latency | imbalance_usd |
|---|---|---|---|---|---|---|---|---|---|---|
| k1-1-1-1 | 4 | 80 | 0.45 | 11447.125 | 0.0027 | 17.2825 | 2615.9 | 1.2858 | 1.4228 | 1.226 |
| k1-1-3-1 | 6 | 80 | 0.5 | 18848.8 | 0.0037 | 21.7073 | 3862.9875 | 1.564 | 1.4374 | 1.6609 |
| k3-1-1-1 | 6 | 80 | 0.4875 | 19093.5875 | 0.0043 | 23.8596 | 5127.9125 | 1.9128 | 1.5584 | 1.9164 |
| k1-3-1-1 | 6 | 80 | 0.4875 | 19228.0375 | 0.0035 | 21.3592 | 3431.0125 | 1.4603 | 1.4174 | 1.5913 |
| k3-1-3-1 | 8 | 80 | 0.5625 | 26233.05 | 0.0052 | 27.7256 | 5144.5375 | 1.6748 | 1.5551 | 1.5956 |
| k1-3-3-1 | 8 | 80 | 0.5125 | 29162.575 | 0.0045 | 25.3598 | 3920.8 | 1.4066 | 1.4026 | 1.5168 |
| k1-1-6-1 | 9 | 80 | 0.5625 | 30146.4375 | 0.0054 | 22.569 | 6416.025 | 2.0505 | 1.4488 | 2.1335 |
| k6-1-1-1 | 9 | 80 | 0.5625 | 30505.1625 | 0.0066 | 24.8623 | 8859.075 | 2.4306 | 1.6367 | 2.365 |
| k1-6-1-1 | 9 | 80 | 0.475 | 31024.5875 | 0.0049 | 22.0831 | 5462.4625 | 1.9084 | 1.3885 | 2.0432 |
| k3-3-1-1 | 8 | 80 | 0.5875 | 31968.9125 | 0.0052 | 27.8741 | 5129.375 | 1.6997 | 1.5611 | 1.5997 |
| k3-1-6-1 | 11 | 80 | 0.6 | 37290.075 | 0.0067 | 28.2821 | 6195.6625 | 1.6839 | 1.5389 | 1.6326 |
| k6-1-3-1 | 11 | 80 | 0.5625 | 37530.6 | 0.0075 | 28.6137 | 8859.075 | 2.1982 | 1.6459 | 2.0879 |
| k3-3-3-1 | 10 | 80 | 0.55 | 41566.675 | 0.006 | 31.2576 | 5142.7625 | 1.5302 | 1.5461 | 1.3885 |
| k1-3-6-1 | 11 | 80 | 0.4625 | 44248.025 | 0.0061 | 25.7138 | 6195.325 | 1.8 | 1.4108 | 1.9334 |
| k1-6-3-1 | 11 | 80 | 0.5375 | 45009.375 | 0.0059 | 25.7929 | 5470.275 | 1.6782 | 1.399 | 1.7061 |
| k6-1-6-1 | 14 | 80 | 0.525 | 48481.15 | 0.009 | 29.3141 | 8937.05 | 1.9421 | 1.6047 | 1.7699 |
| k6-3-1-1 | 11 | 80 | 0.5375 | 50796.9375 | 0.0076 | 28.5618 | 8859.075 | 2.2248 | 1.6593 | 2.0684 |
| k3-6-1-1 | 11 | 80 | 0.5625 | 51565.4625 | 0.0067 | 28.3075 | 5776.275 | 1.6349 | 1.5384 | 1.8183 |
| k3-3-6-1 | 13 | 80 | 0.6 | 56188.075 | 0.0074 | 31.5502 | 5729.375 | 1.4761 | 1.5376 | 1.4552 |
| k6-3-3-1 | 13 | 80 | 0.5625 | 60591.8125 | 0.0085 | 32.2358 | 8859.075 | 2.039 | 1.6227 | 1.8476 |
| k3-6-3-1 | 13 | 80 | 0.6125 | 65524.5875 | 0.0076 | 31.6567 | 5776.9875 | 1.4856 | 1.5191 | 1.5974 |
| k1-6-6-1 | 14 | 80 | 0.5 | 65985.625 | 0.0075 | 26.0412 | 6334.2625 | 1.6232 | 1.4096 | 1.7417 |
| k6-3-6-1 | 16 | 80 | 0.5875 | 75088.975 | 0.0098 | 32.295 | 8886.675 | 1.8321 | 1.6371 | 1.6188 |
| k6-6-1-1 | 14 | 80 | 0.6 | 81603.3625 | 0.0092 | 29.0267 | 8864.0875 | 1.9643 | 1.6174 | 1.754 |
| k3-6-6-1 | 16 | 80 | 0.6125 | 86544.4125 | 0.009 | 31.8734 | 6061.5125 | 1.3765 | 1.5099 | 1.4323 |
| k6-6-3-1 | 16 | 80 | 0.6 | 95457.7125 | 0.0101 | 32.2477 | 8864.1 | 1.8256 | 1.5993 | 1.6019 |
| k6-6-6-1 | 19 | 80 | 0.625 | 116332.7125 | 0.0115 | 32.4655 | 8899.0125 | 1.6631 | 1.5972 | 1.4212 |

Reading: an interval that includes 0 means the cached grid cannot tell whether balance matters at fixed tokens. The grid varies stage widths only (1, 3, 6), so imbalance and total tokens move together; designs that change balance at fixed tokens (fan-in, compression; patching.md) need new calls, because a communicating network's later stages read different inputs and cannot be replayed.
