# Study CD: power by simulation (section 4.4)

Written by `python -m analysis.cd_power` (400 simulated studies per row; frozen tests in
analysis/cd_read.py; a test passes at p <= 0.025, Holm's first step over two tests; the 0.05 column is
the second step). Model and planning values: the module docstring.

| sizes | items | R_true | delta | beta | max_cost_ratio | code_gap | k | power_CD1 | power_CD1_at_05 | void_CD1 | R_median | power_CD2 | power_CD2_at_05 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| core | 167 | 1.0 | 0.04 | 1.5 | 1.0 | 0.2 | 1 | 0.39 | 0.528 | 0.02 | nan | 0.15 | 0.22 |
| core | 167 | 1.0 | 0.04 | 1.5 | 3.0 | 0.2 | 3 | 0.41 | 0.532 | 0.015 | 1.0 | 0.035 | 0.055 |
| core | 167 | 0.75 | 0.02 | 1.5 | 1.0 | 0.2 | 1 | 0.125 | 0.202 | 0.015 | 0.75 | 0.068 | 0.115 |
| core | 167 | 1.25 | 0.06 | 1.5 | 1.0 | 0.2 | 1 | 0.68 | 0.795 | 0.008 | 1.278 | 0.268 | 0.39 |
| core | 167 | 1.0 | 0.04 | 1.0 | 1.0 | 0.2 | 1 | 0.268 | 0.4 | 0.018 | 0.967 | 0.1 | 0.198 |
| core | 167 | 1.0 | 0.04 | 2.0 | 1.0 | 0.2 | 1 | 0.47 | 0.618 | 0.005 | 0.968 | 0.145 | 0.24 |
| core | 167 | 1.0 | 0.04 | 1.5 | 1.0 | 0.1 | 1 | 0.202 | 0.322 | 0.095 | nan | 0.16 | 0.252 |
| core | 167 | 1.0 | 0.04 | 1.5 | 1.0 | 0.3 | 1 | 0.598 | 0.705 | 0.005 | 1.0 | 0.145 | 0.228 |
| core+reserve | 265 | 1.0 | 0.04 | 1.5 | 1.0 | 0.2 | 1 | 0.63 | 0.752 | 0.002 | 1.021 | 0.22 | 0.312 |
| core+reserve | 265 | 0.75 | 0.02 | 1.5 | 1.0 | 0.2 | 1 | 0.195 | 0.3 | 0.002 | 0.747 | 0.115 | 0.17 |
| core+reserve | 265 | 1.25 | 0.06 | 1.5 | 1.0 | 0.2 | 1 | 0.895 | 0.935 | 0.012 | 1.28 | 0.452 | 0.582 |
| core+reserve | 265 | 1.0 | 0.04 | 1.5 | 3.0 | 0.2 | 3 | 0.618 | 0.742 | 0.012 | 1.024 | 0.06 | 0.108 |
