# Designs scoreboard

Written by `python -m analysis.designs` (also run by `analysis/build_report.py`); do not edit by hand. Terms are defined in the module docstring.

Held-out half: 40 items; search half: 40 items. Choices were made on the search half only.

| design | role | calls per task | status | items | n | error % (95% CI) | cost per task (cents) | vs dense, points (95% CI) | rule 24 | source |
|---|---|---|---|---|---|---|---|---|---|---|
| single Haiku | descriptive | 1 | run | held-out | 40 | 42.5 (27.5 to 57.5) | 0.077 | -2.5 (-17.5 to +12.6) | yes | p4_<cand>_single_held, live |
| single Sonnet (senior control) | trigger: senior (rule 18) | 1 Sonnet | run | P3 items 20-59 | 40 | 30.0 (17.5 to 45.0) | 1.402 | +5.0 (-15.0 to +25.0) |  | p3_<cand>_single_sonnet, live, P3 items 20-59 |
| dense 6-6-6-1 | descriptive | 19 | offline | held-out (k6-6-6-1) | 40 | 40.0 (25.0 to 55.0) | 1.184 | +0.0 (+0.0 to +0.0) | no | P4 grid |
| vote6 | descriptive | 6 | offline | held-out (exit rate 100%) | 40 | 47.5 (32.5 to 62.5) | 0.413 | -7.5 (-22.5 to +7.5) | no | offline: consensus m=6, theta=0 |
| gated_3x6 | descriptive | 6 or 19 | offline | held-out (exit rate 32%) | 40 | 37.5 (22.5 to 52.5) | 0.971 | +2.5 (+0.0 to +7.5) | no | offline: consensus m=6, theta=5/6, else dense |
| best consensus policy | trigger: H5 | varies | offline | held-out (exit rate 32%) | 40 | 42.5 (27.5 to 57.5) | 0.905 | -2.5 (-10.0 to +5.0) | no | offline, chosen on the search half: m=3, theta=0.83, else k6-6-6-1 |
| equimarginal endpoint | descriptive | varies | offline | held-out (k3-3-1-1) | 40 | 45.0 (30.0 to 60.0) | 0.539 | -5.0 (-17.5 to +7.5) | no | offline, path built on the search half |
| joint pick (exhaustive) | trigger: static pruning | varies | offline | held-out (k3-3-1-1) | 40 | 45.0 (30.0 to 60.0) | 0.539 | -5.0 (-17.5 to +7.5) | no | offline, chosen on the search half |
| stage-by-stage pick | descriptive | varies | offline | held-out (k6-6-1-1) | 40 | 45.0 (30.0 to 60.0) | 0.952 | -5.0 (-15.0 to +5.0) | no | offline, chosen on the search half |
| judge_cascade | descriptive | 6 or 7 (+ Sonnet) | not run | | | | | | | p4b_<cand>_judge_cascade, live; not run in the pilot: its fixed routing (13 exit, 21 Haiku aggregator, 6 Sonnet of 40) puts its cost floor at 55% of dense, over rule 24's 50% (audit 25) |
| single Sonnet, held-out | descriptive | 1 Sonnet | run | held-out | 40 | 27.5 (15.0 to 42.5) | 1.472 | +12.5 (-5.0 to +30.0) | no | p4_<cand>_single_sonnet_held, live |
| vote or Sonnet | descriptive | 6 (+ 1 Sonnet) | offline | held-out (vote settles 32%) | 40 | 30.0 (17.5 to 45.0) | 1.499 | +10.0 (-7.5 to +27.5) | no | offline, theta=0.83 chosen on the search half |
| mixed_vote6 | descriptive | 6 (3 Haiku + 3 Luna) | not run | | | | | | | not in the pilot (post-pilot option) |
