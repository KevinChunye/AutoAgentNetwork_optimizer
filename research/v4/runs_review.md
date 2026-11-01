# Review of every run so far (session E6, section 3)

Written by `python scripts/review_runs.py` from results/*/calls.csv (55 runs), results/*/status*.json (every committed version), state/ledger.jsonl and configs/, as of commit 5d8e14e (the last change to results/ or state/); the reproduction table comes from `python scripts/review_runs.py --verify` (research/v4/runs_review_repro.csv). $0: no model calls. Definitions are in the script's docstring. Facts only: nothing here is a conclusion about a research question.

## Anomalies

Runs with a calls.csv, and the reads:

1. Every ledger run id belongs to a results/ folder.
2. 9 runs have no live row although the ledger bills them (a later $0 replay or regrade rewrote every row as a cache hit; their spend is only in the ledger): e11_probe_bbeh_anth, e11_probe_bbeh_open, e11_probe_forecast_anth, e11_probe_forecast_open, e12_luna_check_bbeh_open, e13_bbeh_anth, e13_bbeh_open, e22_persona_bbeh_anth, e51_sol_math.
3. Ledger above live dollars (calls paid in an earlier attempt, replayed from the cache by a resume): e22_persona_forecast_anth $0.031, e51_luna_bbeh $0.042, e51_luna_math $0.388, e51_sol_math_low $0.069, w2a_tune $0.038.
4. Every ledger record matches a calls.csv row of its run (item, source, cost) and every live row a ledger record.
5. Every config has a prereg block (question, prediction, kill, decision), today and at the commit of each attempt that recorded one (desk runs record none).
6. The truncated flag agrees with the stop reason (max_tokens or length) on every row that records one.
7. Truncation above 5% of a source's calls: e23_reasoning_bbeh_anth haiku:base 15.0%, e50_scan_bbeh_anth haiku_low:base 20.8%, e50_scan_math_anth haiku_high:base 40.0%, e51_haiku_low_math12 haiku_low:base 9.3%, e51_haiku_low_math36 haiku_low:base 6.7%, e51_haiku_math haiku_low:base 17.3%, e51_tier2_anth_math sonnet_high:base 20.0%, e60_cd_probe_haiku_math haiku_max:base 66.7%, e60_cd_probe_haiku_math haiku_xhigh:base 33.3%, w2a_smoke trader:haiku_nothink 40.0%.
8. Unparsed above 5%: e11_probe_bbeh_anth sonnet_nothink:base 10.0%, e23_reasoning_bbeh_anth haiku:base 12.5%, e50_scan_bbeh_anth haiku_low:base 20.0%, e50_scan_bbeh_open luna_low_ev:base 15.0%, e50_scan_math_anth haiku_high:base 40.0%, e50_scan_math_open luna_low_ev:base 20.0%, e50_scan_math_open sol61_low:base 10.0%, e51_haiku_low_math12 haiku_low:base 12.2%, e51_haiku_low_math36 haiku_low:base 12.0%, e51_haiku_math haiku_low:base 18.7%, e51_haiku_math haiku_nothink:base 5.3%, e51_haiku_off_math haiku_nothink:base 7.2%, e51_judge_open_math sol61_low:judge 10.8%, e51_luna_math luna_low_ev:base 15.4%, e51_luna_math luna_med:base 10.4%, e51_luna_math luna_none:base 22.2%, e51_sol_math sol61_low:base 33.3%, e51_sol_math sol61_med:base 25.0%, e51_sol_math_low sol61_low:base 37.3%, e51_sonnet_math sonnet_low:base 7.9%, e51_tier2_anth_math opus_nothink:base 11.8%, e51_tier2_anth_math sonnet_high:base 20.0%, e51_verify_open_math sol61_low:self_check 13.3%, e52_scan_sonnet_math sonnet_low:base 10.0%, e60_cd_probe_haiku_math haiku_low:base 33.3%, e60_cd_probe_haiku_math haiku_max:base 66.7%, e60_cd_probe_haiku_math haiku_xhigh:base 33.3%, w2a_smoke trader:haiku_nothink 40.0%.
9. Refusals: e11_probe_bbeh_anth sonnet_nothink:base 1, e13_bbeh_anth sonnet_nothink:base 1.
10. No model_version drift (one version per source in every run).
11. 14 runs had failed or stopped attempts (listed in the per-run table): e11_probe_bbeh_anth, e12_luna_check_bbeh_open, e13_bbeh_open, e22_persona_forecast_anth, e23_reasoning_bbeh_anth, e50_scan_bbeh_open, e51_haiku_low_math36, e51_haiku_math, e51_luna_math, e51_sol_math, e51_sol_math_low, e51_sonnet_math, e51_verify_open_math, w2a_smoke.
12. Repeated slices (two attempts with live calls on overlapping items): e11_probe_bbeh_anth [0-10], e12_luna_check_bbeh_open [0-40], e13_bbeh_open [0-26], e22_persona_forecast_anth [0-200], e51_luna_math [0-53], e51_sol_math_low [51-52], w2a_tune [0-20]. In each the later attempt took the earlier one's calls from the cache: no call was paid twice (the ledger has no record beyond its run's rows).
13. Attempts started on a dirty tree (status.json code.dirty; the changed paths are recorded only since audit 75): e13_bbeh_anth (102-154: dirty), e50_scan_bbeh_open (48-96: dirty), e51_sonnet_bbeh (35-53: dirty; 53-71: dirty; 90-106: dirty; 106-123: dirty; 269-286: dirty; 286-304: dirty; 304-323: dirty; 323-341: dirty; 341-358: dirty; 412-430: dirty; 430-440: dirty), e52_scan_sonnet_low_bbeh (0-24: dirty; 24-48: dirty; 48-64: dirty), e52_scan_sonnet_math (0-10: dirty), e52_scan_sonnet_off_bbeh (0-64: dirty).
14. Ledger run ids that no committed status.json names (an attempt whose status was overwritten before a commit): e51_luna_bbeh: e51_luna_bbeh-1793003963 (212 calls, $0.042).
15. Anchor block 1 does not reproduce: read.md: 3 committed lines differ (3 reproduced); first: `| sol61_low:base | math | 279 | 0.627 | 0.638 | 1.0 | 16 | 9 |` -> `| sol61_low:base | math | 279 | 0.627 | 0.638 | 0.0 | 16 | 9 |`; `1 math rows hit a timeout: arxivmath-0826-39 sol61_low:base call 0. Confirmatory decisions` -> `No math row hit a timeout.` (math-verify timeouts: the committed read counted 1, the reproduction 0).
16. Reads: 10 of 10 were written once from frozen code with their inputs unchanged since; 9 of 10 reproduce byte-identical from their frozen commit.

Runs without a calls.csv (audit 99, item 2):

17. 46 results/ folders have no calls.csv: 45 ledgered runs, $9.66 (pilot, market town, W0, W1; table below).
18. For every one, the attempt its status.json names has ledger dollars equal to the status's run spend.
19. Network runs: in every results.csv row, live_calls equals that attempt's ledger records for the same config and task, and the ledger bills no config or task outside results.csv. Market runs: every ledger record matches a turns.csv row (session, trader, cost) and every live turn a record.
20. 11 of them were last rewritten by a $0 replay (no live call in their files; their spend is only in the ledger): p2_bbeh_band_single, p2_bbeh_dense, p2_bbeh_single, p2_omni_band_single, p3_bbeh_dense, p3_bbeh_dense_b, p3_bbeh_noise, p3_bbeh_single, p3_bbeh_single_sonnet, p3w_bbeh_dense, p3w_bbeh_single.
21. Runs with more than one attempt (each of these folders keeps one committed status, so the earlier attempts are seen only in the ledger, and their calls as cache hits in the files): m2_haiku 5 attempts, m3_sonnet 2 attempts, m4_mixed_even 2 attempts, m4_mixed_odd 2 attempts, p0_dense_haiku_nothink 3 attempts, p2_omni61_band_single 2 attempts, p2_omni_band_single 3 attempts, p3_bbeh_single 2 attempts.
22. Paid calls truncated (ledger stop reason) above 5%: p0_calib_gpt_small 40.0%, p0_calib_haiku 60.0%, p0_calib_haiku_low 40.0%, p0_calib_haiku_nothink 20.0%, p0_calib_luna_low 40.0%, p0_dense_haiku_nothink 13.7%.
23. Final answers (network) or turns (market) unparsed above 5%: p0_calib_gpt_small 40.0%, p0_calib_haiku 40.0%, p0_calib_haiku_low 40.0%, p0_calib_haiku_nothink 20.0%, p0_calib_luna_low 40.0%, p2_omni61_band_single 16.0%, p2_omni61_single 10.0%.
24. Refusals among paid calls: p4_bbeh_single_sonnet_held 1.
25. No config or no prereg: market_zic (missing, $0.00).
26. No committed status of these runs is failed or stopped; model_version is not recorded in their files.

## Notes on the checks (audit 99, item 3)

(a) Anchor block 1's reproduction differs only in its math-verify timeout count: the committed read counted 1, the reproduction 0 (in two reproductions). No grade changes: Sol low's math parse rates stay 0.627 at run time and 0.638 at the read, and arxivmath-0826-39 call 0 is wrong either way (a timeout reads as no match; regraded without one by `anchor_read.regrade_math`, it is still 0.0). Every accuracy, test and table value is identical, and audit 91's frozen sensitivity rule, which counts the timed-out rows correct, already found no confirmatory decision that differs. It is a nondeterministic wall-clock count, not a correction.

(b) Cross-run cache replays. Some runs' calls.csv rows include calls another run paid for (served from the shared cache, priced on the row, billed to the other run). Cost over all rows exceeds the run's own ledger dollars by $2.02 in all: e51_haiku_low_math12 +$0.184, e51_haiku_off_math +$0.048, e51_sol_math_low +$0.491, e51_sonnet_math_t30 +$1.285, w2a_tune +$0.007. "No call was paid twice" is checked within each run (every ledger record matches a row of its run, as multisets). Across runs it is checked by cache key: the 49,391 lines of state/cache hold 49,391 distinct keys (0 written twice), and for 285 of 285 run ids the number of cache lines equals the number of ledger records. A paid call writes one cache line, and a key already in the cache is served instead of paid, so no request was paid twice.

(c) Hand checks and the matcher's limit. `--numbers` lists the numbers of a claim that no number in its cited files equals once rounded to the claim's decimals (directly, as a percentage or as a share). It accepts any number in the file that rounds the same, whatever row it comes from, so a right number under the wrong label passes: F8's Haiku 0.137 and Luna 0.143 matched the pooled rows (0.1370, 0.1429) although the finding sets them beside single calls (per call 0.1377 and 0.1489). It is a screen for missing numbers only. Checked by hand:

- F1-F18: every number of every row was read against the cited file by hand, not only those `--numbers` lists.
- Recomputed from calls.csv: F3 (e13_bbeh_*: Sol low call 0 $0.0062, 92.0-100% per task, 404 output tokens; Sonnet $0.0139, 1,063 tokens; Haiku and Luna over calls 0-4) and F10 (e23 and e13: 75.0%, $0.00183 per call, 40.0% off on the same 20 items, 15% truncated).
- Recomputed with the Atlas code: the F17 corrections note's 38-system all-wrong rates.
- From the ledger: the hand-back's spend lines, the K3 parts and the failure-window token counts.
- Against research/audit_log.md (audit 96, 'auditor post-read'): the hand-back's AH1 low-vs-off interval, the senior-control gaps and dollar ratios, the zero-gain AH3 check and the per-task AH2 effects.


## Per run

| run | config | prereg (now / at run) | items | calls | ledger $ (attempts) | live $ (rows) | cache hits | max trunc / unparsed | refused | drift | failed or stopped attempts (every committed status) | status*.json not completed (today) | repeated slices | read (once, frozen, inputs kept, reproduced) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e11_probe_bbeh_anth | evidence/e11_probe_bbeh_anth.yaml | yes / yes | 10 | 21 | 0.1668 (2) | 0.0000 (0) | 21 | 0.0% / 10.0% | 1 | 0 | 0-10 failed: BadRequestError: Error code: 400 - {'type': 'error', 'error' | status_first_run_failed.json | 0-10 | cost probe (sets the guards; no read) |
| e11_probe_bbeh_open | evidence/e11_probe_bbeh_open.yaml | yes / yes | 10 | 21 | 0.0841 (1) | 0.0000 (0) | 21 | 0.0% / 0.0% | 0 | 0 | - | - | - | cost probe (sets the guards; no read) |
| e11_probe_forecast_anth | evidence/e11_probe_forecast_anth.yaml | yes / yes | 10 | 20 | 0.0418 (1) | 0.0000 (0) | 20 | 0.0% / 0.0% | 0 | 0 | - | - | - | cost probe (sets the guards; no read) |
| e11_probe_forecast_open | evidence/e11_probe_forecast_open.yaml | yes / yes | 10 | 20 | 0.0222 (1) | 0.0000 (0) | 20 | 0.0% / 0.0% | 0 | 0 | - | - | - | cost probe (sets the guards; no read) |
| e12_luna_check_bbeh_open | phase4/e12_luna_check_bbeh_open.yaml | yes / yes | 40 | 80 | 0.0330 (2) | 0.0000 (0) | 80 | 0.0% / 2.5% | 0 | 0 | 0-40 stopped: expectation missed: luna_low_ev:base costs $0.00067 per call | - | 0-40 | luna_check.md (not reproduced) |
| e13_bbeh_anth | evidence/e13_bbeh_anth.yaml | yes / yes | 300 | 1900 | 6.2215 (6) | 0.0000 (0) | 1900 | 0.0% / 0.2% | 1 | 0 | - | - | - | Phase 1 G2a: ok; Phase 2: ok; Atlas: ok; Atlas frozen model: ok |
| e13_bbeh_open | evidence/e13_bbeh_open.yaml | yes / yes | 300 | 1900 | 2.5009 (12) | 0.0000 (0) | 1900 | 0.0% / 1.3% | 0 | 0 | 0-26 failed: BadRequestError: Error code: 400 - {'error': {'message': 'In | - | 0-26 | Phase 1 G2a: ok; Phase 2: ok; Atlas: ok; Atlas frozen model: ok |
| e14_forecast_anth | evidence/e14_forecast_anth.yaml | yes / yes | 300 | 1900 | 1.9830 (3) | 1.9830 (1900) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Phase 1 G2b: ok; Phase 2: ok; Forecast selection: ok |
| e14_forecast_open | evidence/e14_forecast_open.yaml | yes / yes | 300 | 1900 | 1.0090 (10) | 1.0090 (1900) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Phase 1 G2b: ok; Phase 2: ok; Forecast selection: ok |
| e15_sol_probe_anth | phase4/e15_sol_probe_anth.yaml | yes / yes | 40 | 40 | 0.5399 (1) | 0.5399 (40) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | sol_probe.md (not reproduced) |
| e15_sol_probe_open | phase4/e15_sol_probe_open.yaml | yes / yes | 40 | 40 | 0.2555 (1) | 0.2555 (40) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | sol_probe.md (not reproduced) |
| e22_persona_bbeh_anth | evidence/e22_persona_bbeh_anth.yaml | yes / yes | 200 | 600 | 0.3959 (1) | 0.0000 (0) | 600 | 0.0% / 0.0% | 0 | 0 | - | - | - | Phase 2: ok |
| e22_persona_forecast_anth | evidence/e22_persona_forecast_anth.yaml | yes / yes | 200 | 600 | 0.1239 (2) | 0.0934 (450) | 150 | 0.0% / 0.0% | 0 | 0 | 0-200 stopped: expectation missed: haiku_nothink:careful costs $0.00028 per | - | 0-200 | Phase 2: ok |
| e22b_aggregator_bbeh_anth | evidence/e22b_aggregator_bbeh_anth.yaml | yes / yes | 200 | 200 | 0.1281 (1) | 0.1281 (200) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Phase 2: ok |
| e22b_aggregator_forecast_anth | evidence/e22b_aggregator_forecast_anth.yaml | yes / yes | 200 | 200 | 0.0482 (1) | 0.0482 (200) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Phase 2: ok |
| e23_reasoning_bbeh_anth | evidence/e23_reasoning_bbeh_anth.yaml | yes / yes | 20 | 40 | 0.0732 (1) | 0.0732 (40) | 0 | 15.0% / 12.5% | 0 | 0 | 0-20 stopped: expectation missed: 12.5% of haiku:base replies unparsed (li | status.json | - | Phase 2: ok |
| e31_lockbox_forecast_anth | evidence/e31_lockbox_forecast_anth.yaml | yes / yes | 200 | 1800 | 1.2088 (2) | 1.2088 (1800) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Forecast lockbox: ok |
| e31_lockbox_forecast_open | evidence/e31_lockbox_forecast_open.yaml | yes / yes | 200 | 1800 | 0.5923 (6) | 0.5923 (1800) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Forecast lockbox: ok |
| e50_scan_bbeh2_anth | v4/e50_scan_bbeh2_anth.yaml | yes / yes | 32 | 32 | 0.0092 (1) | 0.0092 (32) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | scan (exploratory; research/v4/anchor/scan_read.md, not reproduced) |
| e50_scan_bbeh2_open | v4/e50_scan_bbeh2_open.yaml | yes / yes | 32 | 32 | 0.0717 (1) | 0.0717 (32) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | scan (exploratory; research/v4/anchor/scan_read.md, not reproduced) |
| e50_scan_bbeh_anth | v4/e50_scan_bbeh_anth.yaml | yes / yes | 120 | 270 | 0.3038 (1) | 0.3038 (270) | 0 | 20.8% / 20.0% | 0 | 0 | - | - | - | scan (exploratory; research/v4/anchor/scan_read.md, not reproduced) |
| e50_scan_bbeh_open | v4/e50_scan_bbeh_open.yaml | yes / yes | 120 | 240 | 0.6972 (3) | 0.6972 (240) | 0 | 0.0% / 15.0% | 0 | 0 | 48-96 stopped: expectation missed: 37.5% of luna_low_ev:base replies unpars | status_items_48_96.json | - | scan (exploratory; research/v4/anchor/scan_read.md, not reproduced) |
| e50_scan_math_anth | v4/e50_scan_math_anth.yaml | yes / yes | 10 | 30 | 0.0738 (1) | 0.0738 (30) | 0 | 40.0% / 40.0% | 0 | 0 | - | - | - | scan (exploratory; research/v4/anchor/scan_read.md, not reproduced) |
| e50_scan_math_open | v4/e50_scan_math_open.yaml | yes / yes | 10 | 20 | 0.1503 (1) | 0.1503 (20) | 0 | 0.0% / 20.0% | 0 | 0 | - | - | - | scan (exploratory; research/v4/anchor/scan_read.md, not reproduced) |
| e51_haiku_bbeh | v4/e51_haiku_bbeh.yaml | yes / yes | 440 | 3960 | 2.2977 (8) | 2.2977 (3960) | 0 | 1.5% / 1.5% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_haiku_low_math12 | v4/e51_haiku_low_math12.yaml | yes / yes | 93 | 279 | 0.3891 (1) | 0.3891 (204) | 75 | 9.3% / 12.2% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_haiku_low_math36 | v4/e51_haiku_low_math36.yaml | yes / yes | 25 | 75 | 0.2362 (1) | 0.2362 (75) | 0 | 6.7% / 12.0% | 0 | 0 | 0-59 failed: ValueError: Streaming is required for operations that may ta; 0-59 stopped: expectation missed: 6.7% of haiku_low:base replies truncated | status.json, status_items_0.json | - | stopped or dropped; replaced by a fallback run (process facts only) |
| e51_haiku_math | v4/e51_haiku_math.yaml | yes / yes | 25 | 150 | 0.2323 (1) | 0.2323 (150) | 0 | 17.3% / 18.7% | 0 | 0 | 0-93 stopped: expectation missed: 17.3% of haiku_low:base replies truncate | status.json, status_items_0.json | - | stopped or dropped; replaced by a fallback run (process facts only) |
| e51_haiku_off_math | v4/e51_haiku_off_math.yaml | yes / yes | 93 | 279 | 0.1144 (1) | 0.1144 (204) | 75 | 0.0% / 7.2% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_judge_open_bbeh | v4/e51_judge_open_bbeh.yaml | yes / yes | 440 | 440 | 0.9589 (9) | 0.9589 (440) | 0 | 0.0% / 2.7% | 0 | 0 | - | - | - | Anchor block 2: ok |
| e51_judge_open_math | v4/e51_judge_open_math.yaml | yes / yes | 93 | 93 | 1.0089 (4) | 1.0089 (93) | 0 | 0.0% / 10.8% | 0 | 0 | - | - | - | Anchor block 2: ok |
| e51_luna_bbeh | v4/e51_luna_bbeh.yaml | yes / yes | 440 | 3960 | 1.0432 (6) | 1.0009 (3748) | 212 | 0.0% / 0.0% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_luna_math | v4/e51_luna_math.yaml | yes / yes | 93 | 837 | 1.5029 (3) | 1.1145 (612) | 225 | 1.1% / 22.2% | 0 | 0 | 0-53 stopped: expectation missed: 30.7% of luna_low_ev:base replies unpars | - | 0-53 | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_sol_bbeh | v4/e51_sol_bbeh.yaml | yes / yes | 440 | 1760 | 4.4012 (44) | 4.4012 (1760) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_sol_math | v4/e51_sol_math.yaml | yes / yes | 5 | 19 | 0.7435 (1) | 0.0000 (0) | 19 | 0.0% / 33.3% | 0 | 0 | 0-5 failed: APIConnectionError: Connection error.; 0-5 failed: InternalServerError: Error code: 500 - {'error': {'message': | status.json, status_items_0.json | - | stopped or dropped; replaced by a fallback run (process facts only) |
| e51_sol_math_low | v4/e51_sol_math_low.yaml | yes / yes | 93 | 279 | 8.4584 (13) | 8.3893 (262) | 17 | 0.0% / 37.3% | 0 | 0 | 40-48 stopped: expectation missed: 30.2% of sol61_low:base replies unparsed; 48-56 failed: APIConnectionError: Connection error. | status_items_40.json, status_items_48.json | 51-52 | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_sonnet_bbeh | v4/e51_sonnet_bbeh.yaml | yes / yes | 440 | 962 | 5.3927 (25) | 5.3927 (962) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_sonnet_math | v4/e51_sonnet_math.yaml | yes / yes | 34 | 76 | 1.2852 (2) | 1.2852 (76) | 0 | 2.6% / 7.9% | 0 | 0 | 18-34 stopped: expectation missed: 2.6% of sonnet_low:base replies truncate | status.json, status_items_18.json | - | stopped or dropped; replaced by a fallback run (process facts only) |
| e51_sonnet_math_t30 | v4/e51_sonnet_math_t30.yaml | yes / yes | 93 | 204 | 2.2996 (4) | 2.2996 (128) | 76 | 1.0% / 4.9% | 0 | 0 | - | - | - | Anchor block 1: reproduction differs (math-verify timeout count, note a); Anchor block 2: ok; Anchor block 3: ok |
| e51_tier2_anth_bbeh | v4/e51_tier2_anth_bbeh.yaml | yes / yes | 123 | 133 | 1.3864 (10) | 1.3864 (133) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Anchor block 3: ok |
| e51_tier2_anth_math | v4/e51_tier2_anth_math.yaml | yes / yes | 25 | 27 | 2.5089 (3) | 2.5089 (27) | 0 | 20.0% / 20.0% | 0 | 0 | - | - | - | Anchor block 3: ok |
| e51_verify_anth_bbeh | v4/e51_verify_anth_bbeh.yaml | yes / yes | 440 | 880 | 0.5923 (3) | 0.5923 (880) | 0 | 0.7% / 0.7% | 0 | 0 | - | - | - | Anchor block 2: ok |
| e51_verify_anth_math | v4/e51_verify_anth_math.yaml | yes / yes | 83 | 83 | 0.1399 (1) | 0.1399 (83) | 0 | 3.6% / 3.6% | 0 | 0 | - | - | - | Anchor block 2: ok |
| e51_verify_open_bbeh | v4/e51_verify_open_bbeh.yaml | yes / yes | 440 | 440 | 1.1272 (9) | 1.1272 (440) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | Anchor block 2: ok |
| e51_verify_open_math | v4/e51_verify_open_math.yaml | yes / yes | 60 | 60 | 1.3649 (3) | 1.3649 (60) | 0 | 0.0% / 13.3% | 0 | 0 | 0-34 stopped: expectation missed: 30.8% of sol61_low:self_check replies un | status_items_0.json | - | Anchor block 2: ok |
| e52_scan_sonnet_low_bbeh | v4/e52_scan_sonnet_low_bbeh.yaml | yes / yes | 64 | 64 | 0.3462 (3) | 0.3462 (64) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | scan (exploratory; logged, no read file) |
| e52_scan_sonnet_math | v4/e52_scan_sonnet_math.yaml | yes / yes | 10 | 20 | 0.2582 (1) | 0.2582 (20) | 0 | 0.0% / 10.0% | 0 | 0 | - | - | - | scan (exploratory; logged, no read file) |
| e52_scan_sonnet_off_bbeh | v4/e52_scan_sonnet_off_bbeh.yaml | yes / yes | 64 | 64 | 0.3553 (1) | 0.3553 (64) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | scan (exploratory; logged, no read file) |
| e60_cd_probe_haiku_bbeh | v4/e60_cd_probe_haiku_bbeh.yaml | yes / yes | 3 | 18 | 0.0146 (1) | 0.0146 (18) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | study CD probe (running at this review's commit; no read yet) |
| e60_cd_probe_haiku_math | v4/e60_cd_probe_haiku_math.yaml | yes / yes | 3 | 18 | 0.1796 (1) | 0.1796 (18) | 0 | 66.7% / 66.7% | 0 | 0 | - | - | - | study CD probe (running at this review's commit; no read yet) |
| w2a_judge_101 | desk/w2a_judge_101.yaml | yes / n/a | 200 | 1462 | 0.4280 (1) | 0.4280 (1462) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | desk run (v3 track; analysis/desk.py, not reproduced) |
| w2a_judge_102_105 | desk/w2a_judge_102_105.yaml | yes / n/a | 800 | 1852 | 0.6061 (1) | 0.6061 (1852) | 0 | 0.5% / 0.5% | 0 | 0 | - | - | - | desk run (v3 track; analysis/desk.py, not reproduced) |
| w2a_smoke | desk/w2a_smoke.yaml | yes / n/a | 20 | 20 | 0.0037 (1) | 0.0037 (20) | 0 | 40.0% / 40.0% | 0 | 0 | 0-20 stopped: expectation missed: 40.0% of trader replies unparsed (limit  | status.json | - | desk run (v3 track; analysis/desk.py, not reproduced) |
| w2a_smoke2 | desk/w2a_smoke2.yaml | yes / n/a | 20 | 20 | 0.0070 (1) | 0.0070 (20) | 0 | 0.0% / 0.0% | 0 | 0 | - | - | - | desk run (v3 track; analysis/desk.py, not reproduced) |
| w2a_tune | desk/w2a_tune.yaml | yes / n/a | 200 | 1469 | 0.4243 (2) | 0.3859 (1317) | 152 | 0.5% / 0.5% | 0 | 0 | - | - | 0-20 | desk run (v3 track; analysis/desk.py, not reproduced) |

Ledger $ counts every attempt of the run; live $ only the rows the last attempt paid for. Where they differ, every ledger record still matches a row (see anomalies): the difference is calls replayed from the cache by a later attempt. These runs hold $56.84 of the ledger's $66.50; the runs without a calls.csv hold $9.66 (next sections).

## Per source

| run | source | calls | live | cache hits | truncated | unparsed | refused | stop reasons | model versions |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| e11_probe_bbeh_anth | haiku_nothink:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e11_probe_bbeh_anth | opus_nothink:base | 1 | 0 | 1 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-opus-5-5 |
| e11_probe_bbeh_anth | sonnet_nothink:base | 10 | 0 | 10 | 0.0% | 10.0% | 1 | end_turn 90.0%, refusal 10.0% | claude-sonnet-5-5 |
| e11_probe_bbeh_open | astra_low:base | 1 | 0 | 1 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-astra |
| e11_probe_bbeh_open | luna_none:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e11_probe_bbeh_open | sol61_low:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e11_probe_forecast_anth | haiku_nothink:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e11_probe_forecast_anth | sonnet_nothink:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e11_probe_forecast_open | luna_none:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e11_probe_forecast_open | sol61_low:base | 10 | 0 | 10 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e12_luna_check_bbeh_open | luna_low_ev:base | 40 | 0 | 40 | 0.0% | 2.5% | 0 | stop 100.0% | gpt-6-luna |
| e12_luna_check_bbeh_open | luna_none:base | 40 | 0 | 40 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e13_bbeh_anth | haiku_nothink:base | 1500 | 0 | 1500 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e13_bbeh_anth | sonnet_nothink:base | 400 | 0 | 400 | 0.0% | 0.2% | 1 | end_turn 99.8%, refusal 0.2% | claude-sonnet-5-5 |
| e13_bbeh_open | luna_none:base | 1500 | 0 | 1500 | 0.0% | 1.3% | 0 | stop 100.0% | gpt-6-luna |
| e13_bbeh_open | sol61_low:base | 400 | 0 | 400 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e14_forecast_anth | haiku_nothink:base | 1500 | 1500 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e14_forecast_anth | sonnet_nothink:base | 400 | 400 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e14_forecast_open | luna_none:base | 1500 | 1500 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e14_forecast_open | sol61_low:base | 400 | 400 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e15_sol_probe_anth | sonnet_nothink:base | 40 | 40 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e15_sol_probe_open | sol61_low:base | 40 | 40 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e22_persona_bbeh_anth | haiku_nothink:careful | 200 | 0 | 200 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22_persona_bbeh_anth | haiku_nothink:contrarian | 200 | 0 | 200 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22_persona_bbeh_anth | haiku_nothink:quick | 200 | 0 | 200 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22_persona_forecast_anth | haiku_nothink:careful | 200 | 150 | 50 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22_persona_forecast_anth | haiku_nothink:contrarian | 200 | 150 | 50 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22_persona_forecast_anth | haiku_nothink:quick | 200 | 150 | 50 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22b_aggregator_bbeh_anth | haiku_nothink:aggregator | 200 | 200 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e22b_aggregator_forecast_anth | haiku_nothink:aggregator | 200 | 200 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e23_reasoning_bbeh_anth | haiku:base | 40 | 40 | 0 | 15.0% | 12.5% | 0 | end_turn 85.0%, max_tokens 15.0% | claude-haiku-5-5 |
| e31_lockbox_forecast_anth | haiku_nothink:base | 1000 | 1000 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e31_lockbox_forecast_anth | haiku_nothink:careful | 200 | 200 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e31_lockbox_forecast_anth | haiku_nothink:contrarian | 200 | 200 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e31_lockbox_forecast_anth | haiku_nothink:quick | 200 | 200 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e31_lockbox_forecast_anth | sonnet_nothink:base | 200 | 200 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e31_lockbox_forecast_open | luna_none:base | 1000 | 1000 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e31_lockbox_forecast_open | luna_none:careful | 200 | 200 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e31_lockbox_forecast_open | luna_none:contrarian | 200 | 200 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e31_lockbox_forecast_open | luna_none:quick | 200 | 200 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e31_lockbox_forecast_open | sol61_low:base | 200 | 200 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e50_scan_bbeh2_anth | haiku_nothink:base | 32 | 32 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e50_scan_bbeh2_open | sol61_low:base | 32 | 32 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e50_scan_bbeh_anth | haiku_high:base | 30 | 30 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e50_scan_bbeh_anth | haiku_low:base | 120 | 120 | 0 | 20.8% | 20.0% | 0 | end_turn 79.2%, max_tokens 20.8% | claude-haiku-5-5 |
| e50_scan_bbeh_anth | haiku_nothink:base | 120 | 120 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e50_scan_bbeh_open | luna_low_ev:base | 120 | 120 | 0 | 0.0% | 15.0% | 0 | stop 100.0% | gpt-6-luna |
| e50_scan_bbeh_open | sol61_low:base | 120 | 120 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e50_scan_math_anth | haiku_high:base | 10 | 10 | 0 | 40.0% | 40.0% | 0 | end_turn 60.0%, max_tokens 40.0% | claude-haiku-5-5 |
| e50_scan_math_anth | haiku_low:base | 10 | 10 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e50_scan_math_anth | haiku_nothink:base | 10 | 10 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e50_scan_math_open | luna_low_ev:base | 10 | 10 | 0 | 0.0% | 20.0% | 0 | stop 100.0% | gpt-6-luna |
| e50_scan_math_open | sol61_low:base | 10 | 10 | 0 | 0.0% | 10.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_haiku_bbeh | haiku_high:base | 1320 | 1320 | 0 | 1.5% | 1.5% | 0 | end_turn 98.5%, max_tokens 1.5% | claude-haiku-5-5 |
| e51_haiku_bbeh | haiku_low:base | 1320 | 1320 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e51_haiku_bbeh | haiku_nothink:base | 1320 | 1320 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e51_haiku_low_math12 | haiku_low:base | 279 | 204 | 75 | 9.3% | 12.2% | 0 | end_turn 90.7%, max_tokens 9.3% | claude-haiku-5-5 |
| e51_haiku_low_math36 | haiku_low:base | 75 | 75 | 0 | 6.7% | 12.0% | 0 | end_turn 93.3%, max_tokens 6.7% | claude-haiku-5-5 |
| e51_haiku_math | haiku_low:base | 75 | 75 | 0 | 17.3% | 18.7% | 0 | end_turn 82.7%, max_tokens 17.3% | claude-haiku-5-5 |
| e51_haiku_math | haiku_nothink:base | 75 | 75 | 0 | 0.0% | 5.3% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e51_haiku_off_math | haiku_nothink:base | 279 | 204 | 75 | 0.0% | 7.2% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e51_judge_open_bbeh | sol61_low:judge | 440 | 440 | 0 | 0.0% | 2.7% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_judge_open_math | sol61_low:judge | 93 | 93 | 0 | 0.0% | 10.8% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_luna_bbeh | luna_low_ev:base | 1320 | 1245 | 75 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e51_luna_bbeh | luna_med:base | 1320 | 1258 | 62 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e51_luna_bbeh | luna_none:base | 1320 | 1245 | 75 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6-luna |
| e51_luna_math | luna_low_ev:base | 279 | 204 | 75 | 0.0% | 15.4% | 0 | stop 100.0% | gpt-6-luna |
| e51_luna_math | luna_med:base | 279 | 204 | 75 | 1.1% | 10.4% | 0 | stop 98.9%, length 1.1% | gpt-6-luna |
| e51_luna_math | luna_none:base | 279 | 204 | 75 | 0.0% | 22.2% | 0 | stop 100.0% | gpt-6-luna |
| e51_sol_bbeh | sol61_low:base | 1320 | 1320 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_sol_bbeh | sol61_med:base | 440 | 440 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_sol_math | sol61_low:base | 15 | 0 | 15 | 0.0% | 33.3% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_sol_math | sol61_med:base | 4 | 0 | 4 | 0.0% | 25.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_sol_math_low | sol61_low:base | 279 | 262 | 17 | 0.0% | 37.3% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_sonnet_bbeh | sonnet_low:base | 481 | 481 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e51_sonnet_bbeh | sonnet_nothink:base | 481 | 481 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e51_sonnet_math | sonnet_low:base | 38 | 38 | 0 | 2.6% | 7.9% | 0 | end_turn 97.4%, max_tokens 2.6% | claude-sonnet-5-5 |
| e51_sonnet_math | sonnet_nothink:base | 38 | 38 | 0 | 0.0% | 2.6% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e51_sonnet_math_t30 | sonnet_low:base | 102 | 64 | 38 | 1.0% | 4.9% | 0 | end_turn 99.0%, max_tokens 1.0% | claude-sonnet-5-5 |
| e51_sonnet_math_t30 | sonnet_nothink:base | 102 | 64 | 38 | 0.0% | 3.9% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e51_tier2_anth_bbeh | opus_nothink:base | 83 | 83 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-opus-5-5 |
| e51_tier2_anth_bbeh | sonnet_high:base | 50 | 50 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e51_tier2_anth_math | opus_nothink:base | 17 | 17 | 0 | 0.0% | 11.8% | 0 | end_turn 100.0% | claude-opus-5-5 |
| e51_tier2_anth_math | sonnet_high:base | 10 | 10 | 0 | 20.0% | 20.0% | 0 | end_turn 80.0%, max_tokens 20.0% | claude-sonnet-5-5 |
| e51_verify_anth_bbeh | haiku_high:judge | 440 | 440 | 0 | 0.7% | 0.7% | 0 | end_turn 99.3%, max_tokens 0.7% | claude-haiku-5-5 |
| e51_verify_anth_bbeh | haiku_low:self_check | 440 | 440 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e51_verify_anth_math | haiku_low:self_check | 83 | 83 | 0 | 3.6% | 3.6% | 0 | end_turn 96.4%, max_tokens 3.6% | claude-haiku-5-5 |
| e51_verify_open_bbeh | sol61_low:self_check | 440 | 440 | 0 | 0.0% | 0.0% | 0 | stop 100.0% | gpt-6.1-sol |
| e51_verify_open_math | sol61_low:self_check | 60 | 60 | 0 | 0.0% | 13.3% | 0 | stop 100.0% | gpt-6.1-sol |
| e52_scan_sonnet_low_bbeh | sonnet_low:base | 64 | 64 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e52_scan_sonnet_math | sonnet_low:base | 10 | 10 | 0 | 0.0% | 10.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e52_scan_sonnet_math | sonnet_nothink:base | 10 | 10 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e52_scan_sonnet_off_bbeh | sonnet_nothink:base | 64 | 64 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-sonnet-5-5 |
| e60_cd_probe_haiku_bbeh | haiku_high:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_bbeh | haiku_low:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_bbeh | haiku_max:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_bbeh | haiku_med:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_bbeh | haiku_nothink:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_bbeh | haiku_xhigh:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_math | haiku_high:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_math | haiku_low:base | 3 | 3 | 0 | 0.0% | 33.3% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_math | haiku_max:base | 3 | 3 | 0 | 66.7% | 66.7% | 0 | max_tokens 66.7%, end_turn 33.3% | claude-haiku-5-5 |
| e60_cd_probe_haiku_math | haiku_med:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_math | haiku_nothink:base | 3 | 3 | 0 | 0.0% | 0.0% | 0 | end_turn 100.0% | claude-haiku-5-5 |
| e60_cd_probe_haiku_math | haiku_xhigh:base | 3 | 3 | 0 | 33.3% | 33.3% | 0 | end_turn 66.7%, max_tokens 33.3% | claude-haiku-5-5 |
| w2a_judge_101 | member2:haiku_nothink | 200 | 200 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | member3:haiku_nothink | 200 | 200 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | member4:haiku_nothink | 200 | 200 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | member5:haiku_nothink | 200 | 200 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | member6:haiku_nothink | 200 | 200 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | risk:haiku_nothink | 155 | 155 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | trader:haiku_nothink | 200 | 200 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_101 | twin:haiku_nothink | 107 | 107 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_judge_102_105 | risk:haiku_nothink | 638 | 638 | 0 | 0.2% | 0.2% | 0 | not recorded |  |
| w2a_judge_102_105 | trader:haiku_nothink | 800 | 800 | 0 | 0.5% | 0.5% | 0 | not recorded |  |
| w2a_judge_102_105 | twin:haiku_nothink | 414 | 414 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_smoke | trader:haiku_nothink | 20 | 20 | 0 | 40.0% | 40.0% | 0 | not recorded |  |
| w2a_smoke2 | trader:haiku_nothink | 20 | 20 | 0 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | member2:haiku_nothink | 200 | 180 | 20 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | member3:haiku_nothink | 200 | 180 | 20 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | member4:haiku_nothink | 200 | 180 | 20 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | member5:haiku_nothink | 200 | 180 | 20 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | member6:haiku_nothink | 200 | 180 | 20 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | risk:haiku_nothink | 167 | 150 | 17 | 0.0% | 0.0% | 0 | not recorded |  |
| w2a_tune | trader:haiku_nothink | 200 | 180 | 20 | 0.5% | 0.5% | 0 | not recorded |  |
| w2a_tune | twin:haiku_nothink | 102 | 87 | 15 | 0.0% | 0.0% | 0 | not recorded |  |

## Runs without a calls.csv

Network runs (pilot P0-P4, W0, W1) are read from results.csv (one row per config, task and replicate, with its calls and live calls); market runs from turns.csv (one row per trader turn) and sessions.csv. "last attempt" is the run id its status.json names. Truncated is the share of paid calls (ledger records) that stopped on max_tokens or length; unparsed is the share of final answers (network) or turns (market) without a readable answer.

| run | kind | config | prereg | tasks | calls | live | ledger calls ($, attempts) | last attempt: ledger calls / $ / status $ | rows not reconciled | truncated (paid) | unparsed | refused | failed | read |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| m1_smoke | market | market/m1_smoke.yaml | yes | 1 | 206 | 206 | 206 ($0.0142, 1) | 206 / 0.0142 / 0.0142 | 0 | 0.0% | 0.0% | 0 | - | market town (analysis/market.py; not reproduced) |
| m2_haiku | market | market/m2_haiku.yaml | yes | 4 | 2080 | 1780 | 2080 ($0.1443, 5) | 224 / 0.0161 / 0.0161 | 0 | 0.2% | 0.1% | 0 | - | market town (analysis/market.py; not reproduced) |
| m3_sonnet | market | market/m3_sonnet.yaml | yes | 2 | 1066 | 1066 | 1066 ($1.1973, 2) | 527 / 0.5882 / 0.5882 | 0 | 0.0% | 0.0% | 0 | - | market town (analysis/market.py; not reproduced) |
| m4_mixed_even | market | market/m4_mixed_even.yaml | yes | 2 | 1044 | 1044 | 1044 ($0.5719, 2) | 511 / 0.2716 / 0.2716 | 0 | 0.2% | 0.2% | 0 | - | market town (analysis/market.py; not reproduced) |
| m4_mixed_odd | market | market/m4_mixed_odd.yaml | yes | 2 | 1067 | 1067 | 1067 ($0.6745, 2) | 539 / 0.3339 / 0.3339 | 0 | 0.0% | 0.0% | 0 | - | market town (analysis/market.py; not reproduced) |
| market_zic | market (no model calls) | missing | NO | 0 | 0 | 0 | 0 ($0.0000, 0) | 0 / 0.0000 / 0.0000 | 0 | 0.0% |  | 0 | - | market town (analysis/market.py; not reproduced) |
| p0_calib_gpt_small | network | pilot/p0_calib_gpt_small.yaml | yes | 5 | 5 | 5 | 5 ($0.0036, 1) | 5 / 0.0036 / 0.0036 | 0 | 40.0% | 40.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p0_calib_haiku | network | pilot/p0_calib_haiku.yaml | yes | 5 | 5 | 5 | 5 ($0.0018, 1) | 5 / 0.0018 / 0.0018 | 0 | 60.0% | 40.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p0_calib_haiku_low | network | pilot/p0_calib_haiku_low.yaml | yes | 5 | 5 | 5 | 5 ($0.0015, 1) | 5 / 0.0015 / 0.0015 | 0 | 40.0% | 40.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p0_calib_haiku_nothink | network | pilot/p0_calib_haiku_nothink.yaml | yes | 5 | 5 | 5 | 5 ($0.0012, 1) | 5 / 0.0012 / 0.0012 | 0 | 20.0% | 20.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p0_calib_luna_low | network | pilot/p0_calib_luna_low.yaml | yes | 5 | 5 | 5 | 5 ($0.0032, 1) | 5 / 0.0032 / 0.0032 | 0 | 40.0% | 40.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p0_calib_sonnet_nothink | network | pilot/p0_calib_sonnet_nothink.yaml | yes | 5 | 5 | 5 | 5 ($0.0233, 1) | 5 / 0.0233 / 0.0233 | 0 | 0.0% | 0.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p0_dense_haiku_nothink | network | pilot/p0_dense_haiku_nothink.yaml | yes | 2 | 38 | 26 | 102 ($0.0399, 3) | 26 / 0.0117 / 0.0117 | 0 | 13.7% | 0.0% | 0 | - | P0 calibration (logged; not reproduced) |
| p2_bbeh_band_single | network | pilot/p2_bbeh_band_single.yaml | yes | 126 | 126 | 0 | 126 ($0.0688, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p2_bbeh_dense | network | pilot/p2_bbeh_dense.yaml | yes | 20 | 380 | 0 | 380 ($0.2349, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p2_bbeh_single | network | pilot/p2_bbeh_single.yaml | yes | 20 | 20 | 0 | 20 ($0.0161, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p2_omni61_band_single | network | pilot/p2_omni61_band_single.yaml | yes | 25 | 25 | 15 | 25 ($0.0156, 2) | 15 / 0.0087 / 0.0087 | 0 | 0.0% | 16.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p2_omni61_single | network | pilot/p2_omni61_single.yaml | yes | 20 | 20 | 20 | 20 ($0.0105, 1) | 20 / 0.0105 / 0.0105 | 0 | 0.0% | 10.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p2_omni_band_single | network | pilot/p2_omni_band_single.yaml | yes | 117 | 117 | 0 | 127 ($0.0668, 3) | 0 / 0.0000 / 0.0000 | 0 | 1.6% | 3.4% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p3_bbeh_dense | network | pilot/p3_bbeh_dense.yaml | yes | 40 | 760 | 0 | 380 ($0.2313, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p3_bbeh_dense_b | network | pilot/p3_bbeh_dense_b.yaml | yes | 20 | 380 | 0 | 380 ($0.2128, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p3_bbeh_noise | network | pilot/p3_bbeh_noise.yaml | yes | 10 | 380 | 0 | 190 ($0.1174, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p3_bbeh_single | network | pilot/p3_bbeh_single.yaml | yes | 60 | 60 | 0 | 40 ($0.0302, 2) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p3_bbeh_single_sonnet | network | pilot/p3_bbeh_single_sonnet.yaml | yes | 40 | 40 | 0 | 40 ($0.5607, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p3w_bbeh_dense | network | pilot/p3w_bbeh_dense.yaml | yes | 20 | 380 | 0 | 380 ($0.2270, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p3w_bbeh_single | network | pilot/p3w_bbeh_single.yaml | yes | 20 | 20 | 0 | 20 ($0.0164, 1) | 0 / 0.0000 / 0.0000 | 0 | 0.0% | 0.0% | 0 | - | pilot gate (reports/pilot; not reproduced) |
| p4_bbeh_grid_a | network | pilot/p4_bbeh_grid_a.yaml | yes | 5 | 1485 | 430 | 430 ($0.2541, 1) | 430 / 0.2541 / 0.2541 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_b | network | pilot/p4_bbeh_grid_b.yaml | yes | 5 | 1485 | 430 | 430 ($0.2115, 1) | 430 / 0.2115 / 0.2115 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_c | network | pilot/p4_bbeh_grid_c.yaml | yes | 5 | 1485 | 430 | 430 ($0.2303, 1) | 430 / 0.2303 / 0.2303 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_d | network | pilot/p4_bbeh_grid_d.yaml | yes | 5 | 1485 | 430 | 430 ($0.2496, 1) | 430 / 0.2496 / 0.2496 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_e | network | pilot/p4_bbeh_grid_e.yaml | yes | 5 | 1485 | 430 | 430 ($0.2106, 1) | 430 / 0.2106 / 0.2106 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_f | network | pilot/p4_bbeh_grid_f.yaml | yes | 5 | 1485 | 430 | 430 ($0.2153, 1) | 430 / 0.2153 / 0.2153 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_g | network | pilot/p4_bbeh_grid_g.yaml | yes | 5 | 1485 | 430 | 430 ($0.2560, 1) | 430 / 0.2560 / 0.2560 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_h | network | pilot/p4_bbeh_grid_h.yaml | yes | 5 | 1485 | 430 | 430 ($0.2177, 1) | 430 / 0.2177 / 0.2177 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_i | network | pilot/p4_bbeh_grid_i.yaml | yes | 5 | 1485 | 525 | 525 ($0.2737, 1) | 525 / 0.2737 / 0.2737 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_j | network | pilot/p4_bbeh_grid_j.yaml | yes | 5 | 1485 | 525 | 525 ($0.3223, 1) | 525 / 0.3223 / 0.3223 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_k | network | pilot/p4_bbeh_grid_k.yaml | yes | 5 | 1485 | 525 | 525 ($0.2787, 1) | 525 / 0.2787 / 0.2787 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_l | network | pilot/p4_bbeh_grid_l.yaml | yes | 5 | 1485 | 525 | 525 ($0.3224, 1) | 525 / 0.3224 / 0.3224 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_m | network | pilot/p4_bbeh_grid_m.yaml | yes | 5 | 1485 | 525 | 525 ($0.3086, 1) | 525 / 0.3086 / 0.3086 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_n | network | pilot/p4_bbeh_grid_n.yaml | yes | 5 | 1485 | 525 | 525 ($0.2939, 1) | 525 / 0.2939 / 0.2939 | 0 | 0.2% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_o | network | pilot/p4_bbeh_grid_o.yaml | yes | 5 | 1485 | 525 | 525 ($0.2698, 1) | 525 / 0.2698 / 0.2698 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_grid_p | network | pilot/p4_bbeh_grid_p.yaml | yes | 5 | 1485 | 525 | 525 ($0.2926, 1) | 525 / 0.2926 / 0.2926 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| p4_bbeh_single_held | network | pilot/p4_bbeh_single_held.yaml | yes | 40 | 40 | 40 | 40 ($0.0308, 1) | 40 / 0.0308 / 0.0308 | 0 | 0.0% | 0.0% | 0 | - | pilot P4 (reports/pilot; not reproduced) |
| p4_bbeh_single_sonnet_held | network | pilot/p4_bbeh_single_sonnet_held.yaml | yes | 40 | 40 | 40 | 40 ($0.5889, 1) | 40 / 0.5889 / 0.5889 | 0 | 0.0% | 2.5% | 1 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| w0_haiku5 | network | v3/w0_haiku5.yaml | yes | 100 | 500 | 400 | 400 ($0.2785, 1) | 400 / 0.2785 / 0.2785 | 0 | 0.0% | 0.0% | 0 | - | Phase 3A (phase3a.md, F14/F15; exploratory, written 4 times, last 99688fa; inputs unchanged since) |
| w1_band_bbeh | network | v3/w1_band_bbeh.yaml | yes | 20 | 100 | 100 | 100 ($0.0688, 1) | 100 / 0.0688 / 0.0688 | 0 | 0.0% | 0.0% | 0 | - | W1 band check (logged; not reproduced) |

## Reads: once, frozen, reproduced

Each read was reproduced by `--verify` from its frozen commit in a temporary git worktree (data/external symlinked in, every API key removed) and its outputs compared byte for byte with the committed ones. Anchor block 3 (tier 2) was read at 6252e0b, after this review began; it was added after audit 99 and reproduced the same way.

| read | frozen commit | written at | output | written once | code unchanged, frozen to written | inputs unchanged since the read | reproduction | notes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Phase 1 G2a | a78e128 | bc5e884 | research/v3/evidence/phase1_bbeh.md | yes | yes | yes | identical | - |
| Phase 1 G2b | c0264d8 | d93b59c | research/v3/evidence/phase1_forecast.md | yes | yes | yes | identical | - |
| Phase 2 | 7cfec4f | 653d07a | research/v3/evidence/phase2.md | yes | yes | yes | identical | - |
| Forecast selection | 6e79e77 | 84cbcf9 | research/v3/pruning/selected_forecast.json | yes | yes | yes | identical | - |
| Forecast lockbox | 84cbcf9 | 1a5f001 | research/v3/pruning/lockbox_forecast.md | yes | yes | yes | identical | - |
| Anchor block 1 | 831b2e6 | 40f4854 | research/v4/anchor/read.md | yes | yes | yes | read.md: 3 committed lines differ (3 reproduced); first: `\| sol61_low:base \| math \| 279 \| 0.627 \| 0.638 \| 1.0 \| 16 \| 9 \|` -> `\| sol61_low:base \| math \| 279 \| 0.627 \| 0.638 \| 0.0 \| 16 \| 9 \|`; `1 math rows hit a timeout: arxivmath-0826-39 sol61_low:base call 0. Confirmatory decisions` -> `No math row hit a timeout.` | - |
| Anchor block 2 | b651158 | 37b615b | research/v4/anchor/read.md | yes | yes | yes | identical | - |
| Anchor block 3 | f160a31 | 6252e0b | research/v4/anchor/read.md | yes | yes | yes | identical | also changed with the output: research/audit_log.md |
| Atlas | 9cb3d81 | 343f50e | research/v4/atlas/atlas.md, research/v4/atlas/tables/ | yes | yes | yes | identical | also changed with the output: research/v3/findings.md |
| Atlas frozen model | 95ada93 | a398a46 | research/v4/atlas/frozen_model.json | yes | yes | yes | identical | factor.py and the response table match frozen_model.json's sha256 at 831b2e6, b651158, f160a31, HEAD |

Reproduction runs: Phase 1 G2a 55 s, exit 0; Phase 1 G2b 13 s, exit 0; Phase 2 17 s, exit 0; Forecast selection 2 s, exit 0; Forecast lockbox 2 s, exit 0; Anchor block 1 264 s, exit 0, math-verify timeouts 0 (the committed read counted 1); Anchor block 2 89 s, exit 0, math-verify timeouts 0 (the committed read counted 0); Anchor block 3 35 s, exit 0; Atlas 502 s, exit 0; Atlas frozen model 2 s, exit 0. math-verify grades each math answer under a wall-clock limit, so its timeout count can differ between two runs of the same code on the same rows.

## Corrections to research/v3/findings.md (F1-F18) and research/v4/handback_e5.md

| where | as written | in the file | file | kind |
| --- | --- | --- | --- | --- |
| findings.md, Corrections, F17 | the brief's implied 6.3% (all-wrong rate under L0) holds for 38 systems | no committed file holds the 38-system numbers; recomputed with analysis/atlas_analyses.f17_f18's fit on the 38 submissions with costs: observed 9.8% (as written), L0 6.6% (0.0663), L1 9.7%, copula 5.9% | research/v4/atlas/tables/f17_numbers.csv (39 systems only); research/v4/atlas/data/swebench_verified.parquet | number |
| findings.md, F8 | Haiku 0.137, Luna 0.143 (beside the single calls Sol 0.128 and Sonnet 0.129) | 0.1370 and 0.1429 are the pooled 5-call forecasts; one call scores 0.1377 (Haiku) and 0.1489 (Luna) | research/v3/evidence/phase1_forecast.md (Brier and log loss) | label |
| findings.md, F2 caveat | Luna x5 is worth 2.19 calls | 2.19 (2.1890) is the pruning library's estimator; under G2a's estimator, which gives the row's 12-call 3.74, Luna x5 is 2.18 (1.93 to 2.52) | research/v3/evidence/information_posthoc.md; research/v3/evidence/phase1_bbeh.md (4) | label |
| handback_e5.md, Spend, API anchor (K3) | Anthropic $16.88 of $48 | $16.87 (16.8745: e51_* Anthropic ledger rows; $16.88 is the sum of four rounded parts in research/log.md) | state/ledger.jsonl | number |
| handback_e5.md, For Kevin | configs/pricing.yaml books Sonnet cache reads at $0.10 per million; the docs say $0.20 (audit 68) | Anthropic's pricing page lists $0.10/M for Sonnet 5.5 cache hits, matching configs/pricing.yaml; audit 68's note was wrong (Kevin's D3) | research/log.md (session E6 D3); configs/pricing.yaml | number |
| handback_e5.md, AH2 | Haiku low $0.00077 vs Haiku-off 2-vote $0.00066; Luna low $0.00036 vs Luna-none 3-vote $0.00026 (not marked auditor post-read) | read.md shows these dollars only to 3-4 decimals ($0.0008 vs $0.0007; $0.0004 vs $0.0003); the 5-decimal values are audit 96's post-read numbers ($0.000766 vs $0.000663; $0.000358 vs $0.000255) | research/v4/anchor/read.md (Depth against width); research/audit_log.md (audit 96) | label |

Every number of F1-F18 and of the E5 hand-back was checked against the file it cites (research/v4/runs_review_corrections.csv; `--numbers` lists the numbers not found verbatim in their sources, which were then checked by hand).

