# Latency card per arm (session M1)

Made by `analysis/latency_map.py` from `tables/latency_by_arm.csv` (the backfill). est = estimated from total seconds by median regression (TTFT est = the overhead; TTFAT est = overhead + mean thinking tokens / decode speed); measured = from streamed calls (timing_source "measured"), side by side where both exist. No measured column is filled until a timed run has been made. OpenAI reasoning arms recorded no reasoning tokens in these runs, so their thinking and TTFAT are left blank (audit 107).

| arm | model | calls | TTFT est s | TTFT meas | TTFAT est s | TTFAT meas | decode tok/s est [95%] | decode meas | p50 s | p95 s | thinking tok | context p50 | $/call | flag |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku | claude-haiku-5-5 | 45 | 0.46 |  | 0.5 |  | 230 [219, 256] |  | 8.8 | 35.5 | 0 | 1,374 | 0.00166 |  |
| haiku_high | claude-haiku-5-5 | 1,886 | 0.90 |  | 2.1 |  | 227 [224, 231] |  | 4.7 | 38.6 | 269 | 402 | 0.00107 |  |
| haiku_low | claude-haiku-5-5 | 2,418 | 0.82 |  | 1.0 |  | 218 [216, 220] |  | 4.7 | 23.9 | 28 | 433 | 0.00086 |  |
| haiku_max | claude-haiku-5-5 | 240 | 1.61 |  | 179.5 |  | 240 [233, 247] |  | 78.8 | 557.7 | 42,687 | 414 | 0.02150 |  |
| haiku_med | claude-haiku-5-5 | 86 | 0.91 |  | 9.1 |  | 214 [212, 236] |  | 5.8 | 41.7 | 1,741 | 410 | 0.00109 |  |
| haiku_nothink | claude-haiku-5-5 | 7,317 | 0.93 |  | 0.9 |  | 238 [235, 241] |  | 2.6 | 7.3 | 0 | 650 | 0.00033 |  |
| haiku_xhigh | claude-haiku-5-5 | 240 | 0.86 |  | 75.2 |  | 227 [224, 233] |  | 8.2 | 516.8 | 16,907 | 414 | 0.00863 |  |
| opus_max | claude-opus-5-5 | 50 | 1.43 |  | 46.0 |  | 112 [107, 113] |  | 24.0 | 178.4 | 4,993 | 410 | 0.11093 |  |
| opus_med | claude-opus-5-5 | 50 | 1.46 |  | 5.1 |  | 102 [93, 115] |  | 5.5 | 22.2 | 367 | 410 | 0.01572 |  |
| opus_nothink | claude-opus-5-5 | 100 | 1.56 |  | 1.6 |  | 106 [101, 113] |  | 5.0 | 17.9 | 0 | 389 | 0.01725 |  |
| sonnet_high | claude-sonnet-5-5 | 146 | 0.99 |  | 11.4 |  | 127 [119, 129] |  | 5.5 | 91.4 | 1,313 | 412 | 0.03089 |  |
| sonnet_low | claude-sonnet-5-5 | 743 | 0.90 |  | 0.9 |  | 122 [118, 126] |  | 4.1 | 13.4 | 0 | 393 | 0.00788 |  |
| sonnet_max | claude-sonnet-5-5 | 84 | 0.42 |  | 196.6 |  | 140 [136, 147] |  | 41.7 | 928.8 | 27,462 | 479 | 0.27967 |  |
| sonnet_med | claude-sonnet-5-5 | 86 | 0.92 |  | 2.4 |  | 123 [114, 132] |  | 4.6 | 13.4 | 180 | 410 | 0.00884 |  |
| sonnet_nothink | claude-sonnet-5-5 | 1,495 | 1.00 |  | 1.0 |  | 127 [124, 129] |  | 3.6 | 12.9 | 0 | 481 | 0.00642 |  |
| sonnet_xhigh | claude-sonnet-5-5 | 57 | 0.94 |  | 83.9 |  | 136 [126, 140] |  | 11.3 | 564.9 | 11,268 | 479 | 0.11783 |  |
| luna_low_ev | gpt-6-luna | 1,579 | 1.31 |  |  |  | 96 [93, 99] |  | 5.3 | 19.0 |  | 272 | 0.00035 | hidden reasoning, not recorded: no TTFAT estimate |
| luna_med | gpt-6-luna | 1,462 | 0.74 |  |  |  | 92 [91, 92] |  | 5.8 | 103.4 |  | 267 | 0.00104 | hidden reasoning, not recorded: no TTFAT estimate |
| luna_none | gpt-6-luna | 4,549 | 1.13 |  | 1.1 |  | 116 [111, 119] |  | 1.8 | 4.9 | 0 | 352 | 0.00008 |  |
| sol61_low | gpt-6.1-sol | 3,417 | 1.43 |  |  |  | 33 [33, 34] |  | 5.0 | 77.9 |  | 325 | 0.00535 | slow: confirm by streaming hidden reasoning, not recorded: no TTFAT estimate |
| sol61_med | gpt-6.1-sol | 440 | 2.15 |  |  |  | 34 [31, 36] |  | 5.8 | 38.4 |  | 254 | 0.00324 | slow: confirm by streaming hidden reasoning, not recorded: no TTFAT estimate |
| gpt_small |  | 5 | 1.26 |  | 1.3 |  | 97 [, ] |  | 7.1 | 10.4 | 0 | 105 | 0.00073 |  |
| luna_low |  | 5 | 1.86 |  |  |  | 89 [, ] |  | 6.8 | 12.4 |  | 105 | 0.00064 | hidden reasoning, not recorded: no TTFAT estimate |
