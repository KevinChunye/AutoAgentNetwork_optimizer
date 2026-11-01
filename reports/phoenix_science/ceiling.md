# A3 ceiling and timing check (scripts/phoenix_ceiling.py; free, CPU only)

Generated 2026-10-31 from reports/phoenix_science/ceiling_runs.csv (one row per pipeline) and ceiling_summary.csv.
Each dataset was prepared exactly as data.prepare_from_raw does (cleaning, one stratified N-row subsample with seed
42, the 60/20/20 split); the whole PHOENIX configuration space (3 scalers x 4 PCA settings x 12 classifier settings =
144 pipelines, workflow.py's trusted operators) was fitted on the training rows and scored on the validation rows.
The sealed test rows were dropped before anything was fitted.

Terms: bacc = validation balanced accuracy (mean recall over classes); spread = (max - median) bacc over the 144
pipelines, in points; seconds = single-threaded CPU seconds of one operation in-process (three jobs ran in
parallel on four cores).

## Cleaning
| dataset | raw_rows | dropped_rows | clean_rows | features | classes | class_counts |
|---|---|---|---|---|---|---|
| covtype | 581012 | 0 | 581012 | 54 | 7 | [211840, 283301, 35754, 2747, 9493, 17367, 20510] |
| miniboone | 130064 | 468 | 129596 | 50 | 2 | [93108, 36488] |
| higgs | 98050 | 1 | 98049 | 28 | 2 | [46223, 51826] |

## Accuracy spread and operation time
| dataset | rows | median_bacc | p90_bacc | max_bacc | spread_points | fit_s_median | fit_s_max | predict_s_median | predict_s_max | slowest_op_s | go |
|---|---|---|---|---|---|---|---|---|---|---|---|
| covtype | 20000 | 0.476 | 0.622 | 0.679 | 20.275 | 0.948 | 8.34 | 0.021 | 0.423 | 8.34 | GO |
| covtype | 40000 | 0.492 | 0.679 | 0.707 | 21.498 | 1.929 | 18.692 | 0.035 | 1.383 | 18.692 | GO |
| covtype | 60000 | 0.493 | 0.713 | 0.749 | 25.598 | 2.906 | 26.669 | 0.051 | 2.666 | 26.669 | GO |
| higgs | 20000 | 0.583 | 0.674 | 0.703 | 12.036 | 0.384 | 5.421 | 0.028 | 0.537 | 5.421 | GO |
| higgs | 40000 | 0.596 | 0.676 | 0.709 | 11.371 | 0.79 | 12.485 | 0.049 | 1.376 | 12.485 | GO |
| higgs | 60000 | 0.594 | 0.674 | 0.706 | 11.238 | 1.154 | 18.853 | 0.062 | 2.564 | 18.853 | GO |
| miniboone | 20000 | 0.874 | 0.911 | 0.918 | 4.397 | 0.627 | 6.371 | 0.022 | 0.37 | 6.371 | GO |
| miniboone | 40000 | 0.868 | 0.911 | 0.92 | 5.161 | 0.969 | 16.104 | 0.039 | 1.418 | 16.104 | GO |
| miniboone | 60000 | 0.868 | 0.911 | 0.918 | 5.015 | 1.583 | 25.317 | 0.048 | 2.989 | 25.317 | GO |

NO-GO rule (spread < 2 points): no dataset is NO-GO. MiniBooNE has the smallest spread (about 5 points).

## The slowest operation through the real tool worker
Fitting a random forest with 100 trees and no depth limit is the slowest operation on every dataset. Run end to end
through autoagentnet.phoenix.tools.ToolRunner (process start, data and parent loading, artifact write) on covtype at
N = 60,000 (minmax, PCA 0.99, the slowest configuration):

| operation | wall s | child CPU s | worker compute s | artifact MB |
|---|---|---|---|---|
| prepare | 2.0 | 2.0 | 1.2 | 14.2 |
| fit (forest 100, no depth limit) | 28.2 | 27.9 | 26.7 | 90.9 |
| predict | 2.6 | 2.6 | 1.7 | 0.7 |
| validate | 2.3 | 2.2 | 1.3 | 0.0 |

## Choice (frozen in configs/experiments/phoenix_science/settings.yaml)
- N = 60,000 for all three datasets: the largest size checked, and its slowest single operation (28.2 s end to end)
  is at most 50% of the frozen tool timeout.
- tool_timeout_s = 90 (toy value 30): 28.2 s is 31% of it, which leaves room for four branches sharing four cores.
- cpu_budget_s = 600 per recovery branch (toy 120): operations now take 2-28 CPU s instead of about 1 s; at 600 s the
  24-tool limit, not CPU, remains the usual binding limit, as on the toy sets.
- wall_s = 3600 per recovery branch (toy 1200): up to 24 tools and 8 model calls with four branches in parallel.
- Calibration: cpu_budget_s = 7200 and wall_s = 7200 per model (30 tasks of about 15 tool runs each).
- Disk: one such forest is 91 MB; branches hard-link the checkpoint's artifacts, so only new work takes space.
