# Atlas extensions P1-P8 (session W1)

Written by `python -m analysis.atlas_extend` from research/v4/atlas/data/ and the committed anchor read (research/v4/anchor/read.md); definitions in the script's docstring. **Exploratory throughout**: public data and analyses chosen after the Atlas and the anchor were read; nothing here is a test, and nothing here changes a preregistered decision. Intervals are 95% item-bootstrap intervals (200 draws) unless named otherwise. Where predictors are compared (P1, P7), the interval is on the difference of mean squared errors in points^2: item noise adds the same variance to both squared errors and cancels, while a mean absolute error is inflated by it, so absolute errors are reported without intervals. Tables: research/v4/atlas/tables/extend/.

## P1. The vote rule against zero-gain

Every set with repeats: 695 (system, set) cells with 3 calls in 24 sets (23 MathArena sets and the Phase 1 BBEH panel). The vote rule predicts each cell's 3-vote from single-call data, cross-fitted as AH3; zero-gain predicts no gain.
- All cells: the mean absolute vote-gain error is 2.0 points for the vote rule and 2.2 for zero-gain; the squared-error difference is 2.4 (0.6 to 3.4) points^2 (positive favours the rule). The observed gain averages 1.8 points, the predicted 2.8; predicted and observed gains correlate at 0.46 across cells.
- Cells where the vote rule predicts a gain of 3 points or more (305 cells; the fair check): error 2.5 against 3.1; squared-error difference 5.4 (2.5 to 7.3) points^2; the rule predicts 4.7 and 2.9 is observed.
- The 3-vote level (accuracy, not gain): mean absolute error 4.4 points for the vote rule against 4.0 for zero-gain (one-call prediction); squared-error difference -4.2 (-9.1 to -1.6) points^2. On level the rule is worse: it adds its overstated gain to a one-call prediction that already carries the model's error.
- Cells where votes gained 3 points or more (194 cells; picked on the outcome, which favours the rule by construction): error 1.9 against 4.8; squared-error difference 20.4 (16.4 to 23.7) points^2.
- The anchor's six 3-call arms (read.md, AH3): mean absolute gain error 0.8 points for the rule against 1.5 for zero-gain; the largest observed gain is 2.6 points.
- Reading: on gains the vote rule beats zero-gain on squared error, mostly through the cells with larger gains; on absolute error the two are close, the rule overstates gains by about one point on average (two where it predicts large ones), and on the 3-vote level it is worse than zero-gain. It ranks where votes pay; it does not yet price them. Votes of two calls cannot gain at all in expectation (a right-wrong split is a tie), which is why the AH2 2-vote equals one call.

| k | scope | cells | sets | rule gain MAE | zero-gain gain MAE | gain MSE, zero-gain minus rule (points^2) | gain MSE, zero-gain minus rule (points^2) lo | gain MSE, zero-gain minus rule (points^2) hi | rule level MAE | zero-gain level MAE | level MSE, zero-gain minus rule (points^2) | level MSE, zero-gain minus rule (points^2) lo | level MSE, zero-gain minus rule (points^2) hi | mean observed gain | mean predicted gain | corr(predicted, observed gain) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | all cells | 695 | 24 | 0.0202 | 0.0221 | 2.3693 | 0.6443 | 3.3743 | 0.0438 | 0.0401 | -4.2367 | -9.1098 | -1.6059 | 0.0183 | 0.0279 | 0.4605 |
| 3 | observed gain >= 3 points | 194 | 22 | 0.0189 | 0.0482 | 20.3868 | 16.4127 | 23.7112 | 0.0493 | 0.0562 | 13.3368 | 2.6547 | 21.7581 | 0.0482 | 0.0417 | 0.2765 |
| 3 | predicted gain >= 3 points | 305 | 23 | 0.0250 | 0.0307 | 5.3694 | 2.5029 | 7.3266 | 0.0535 | 0.0471 | -6.8485 | -15.1418 | 0.0101 | 0.0291 | 0.0469 | 0.3189 |
| 5 | all cells | 78 | 7 | 0.0345 | 0.0343 | 8.2983 | -7.4229 | 19.1426 | 0.0524 | 0.0584 | 4.0519 | -36.3417 | 36.9199 | 0.0213 | 0.0204 | 0.6311 |
| 5 | observed gain >= 3 points | 27 | 6 | 0.0472 | 0.0718 | 42.3953 | 5.4701 | 75.8395 | 0.0655 | 0.0817 | 27.9012 | -75.2438 | 106.4741 | 0.0718 | 0.0584 | 0.5701 |
| 5 | predicted gain >= 3 points | 24 | 7 | 0.0509 | 0.0663 | 38.1616 | -9.7164 | 70.2404 | 0.0686 | 0.0798 | 20.9173 | -96.0761 | 119.5576 | 0.0603 | 0.0874 | 0.5252 |

Anchor arms (from read.md):

| arm | observed_one | observed | observed_gain | rule_predicted | rule_predicted_gain | zero_gain_predicted | rule_level_error | zero_gain_level_error | rule_gain_error | zero_gain_gain_error |
|---|---|---|---|---|---|---|---|---|---|---|
| haiku_low | 0.378 | 0.385 | 0.007 | 0.374 | 0.010 | 0.365 | 0.011 | 0.020 | -0.003 | 0.007 |
| haiku_off | 0.340 | 0.360 | 0.020 | 0.358 | 0.012 | 0.346 | 0.002 | 0.014 | 0.008 | 0.020 |
| luna_low | 0.333 | 0.351 | 0.019 | 0.336 | 0.006 | 0.330 | 0.015 | 0.021 | 0.013 | 0.019 |
| luna_med | 0.365 | 0.376 | 0.012 | 0.368 | 0.004 | 0.364 | 0.008 | 0.012 | 0.008 | 0.012 |
| luna_none | 0.221 | 0.226 | 0.004 | 0.231 | 0.007 | 0.224 | -0.005 | 0.002 | -0.003 | 0.004 |
| sol_low | 0.562 | 0.587 | 0.026 | 0.593 | 0.015 | 0.578 | -0.006 | 0.009 | 0.011 | 0.026 |

## P2. Depth moves ability, not the failure pattern

19 adjacent pairs of one model at two reasoning settings (11 models; MathArena, LiveBench, SWE-bench Verified). Pooled with random effects:
- ability rises by 0.92 logits (0.59 to 1.24; between-pair variance 0.35);
- failure beta changes by +0.03 (-0.14 to 0.21; between-pair variance 0.00);
- held out, the higher setting's calls are predicted better by the lower setting plus one shift than by a refit that may also change beta (log loss per call +0.0041, +0.0022 to +0.0061; positive favours the shift), and far better than by the higher setting's base rate (+0.192, +0.159 to +0.225): the items a model fails at the higher setting are the items that are hard for everyone (the difficulties come from every other system).
- The lower setting's own item outcomes plus one shift predict no better than the shared difficulty plus one shift (+0.007, -0.017 to +0.030; positive favours the shared difficulty): the test is of the population difficulty axis, not of the model's own hard items, which its few repeats measure poorly.
- The two pairs left out after a look at tokens (table below; never pooled) change failure beta by -1.62 and +0.71.
- One pair per model gives the same reading (table). Adjacent pairs of one model share a setting, so the all-pairs pooling counts some evidence twice.

| source | model | low | high | items | acc low | acc high | delta a | delta a lo | delta a hi | delta beta | delta beta lo | delta beta hi | refit a and beta minus shift | base rate minus shift |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| swebench_verified | gpt-5.2 | 20251211_mini-v1.17.2_gpt-5.2-2025-12-11 | 20251211_mini-v1.17.2_gpt-5.2-2025-12-11-high | 500 | 0.690 | 0.718 | 0.423 | 0.088 | 0.856 | 0.554 | 0.065 | 1.263 | 0.000 | 0.286 |
| matharena | gpt-5.2 | openai/gpt-52-low | openai/gpt-52-high | 40 | 0.438 | 0.586 | 1.634 | 0.598 | 2.609 | 0.520 | -1.031 | 1.597 | 0.018 | 0.296 |
| matharena | o3-mini | openai/o3-mini--low | openai/o3-mini--medium | 60 | 0.383 | 0.650 | 2.471 | 0.889 | 3.755 | -0.588 | -2.331 | 1.312 | -0.001 | 0.240 |
| matharena | o3-mini | openai/o3-mini--medium | openai/o3-mini | 60 | 0.650 | 0.771 | 0.961 | 0.442 | 1.832 | 0.176 | -1.059 | 1.170 | 0.005 | 0.226 |
| matharena | o4-mini | openai/o4-mini--low | openai/o4-mini--medium | 183 | 0.593 | 0.755 | 1.200 | 0.925 | 1.606 | 0.271 | -0.361 | 0.964 | 0.002 | 0.219 |
| matharena | o4-mini | openai/o4-mini--medium | openai/o4-mini--high | 183 | 0.755 | 0.869 | 1.246 | 0.902 | 1.604 | -0.379 | -1.071 | 0.424 | 0.000 | 0.134 |
| matharena | gpt-5-nano | openai/gpt-5-nano-low | openai/gpt-5-nano | 30 | 0.462 | 0.850 | 2.654 | 1.720 | 4.112 | 0.767 | -1.012 | 2.635 | 0.017 | 0.182 |
| matharena | grok-3-mini | xai/grok-3-mini-low | xai/grok-3-mini-high | 183 | 0.570 | 0.772 | 1.561 | 1.129 | 2.058 | 0.595 | -0.423 | 1.622 | 0.005 | 0.243 |
| matharena | gemini-3.1-pro | gemini/gemini-31-pro-low | gemini/gemini-31-pro-medium | 23 | 0.500 | 0.674 | 2.479 | 0.358 | 4.844 | 1.148 | -3.149 | 3.781 | 0.072 | 0.341 |
| matharena | gemini-3.1-pro | gemini/gemini-31-pro-medium | gemini/gemini-31-pro | 23 | 0.674 | 0.707 | -0.277 | -1.851 | 1.041 | -0.928 | -3.267 | 1.227 | 0.015 | 0.302 |
| matharena | fable 5.1 | anthropic/fable_51_low | anthropic/fable_51_max | 88 | 0.443 | 0.894 | 4.182 | 2.881 | 6.094 | 0.162 | -1.314 | 1.730 | 0.006 | 0.180 |
| matharena | opus 5.5 | anthropic/opus_55_high | anthropic/opus_55_max | 88 | 0.826 | 0.798 | -0.162 | -2.140 | 1.928 | 0.086 | -1.273 | 1.507 | 0.037 | 0.153 |
| matharena | gpt-6 astra | openai/gpt-6-astra-low | openai/gpt-6-astra | 88 | 0.864 | 0.947 | 2.627 | 0.730 | 5.529 | 0.454 | -0.524 | 1.457 | 0.016 | 0.142 |
| livebench | claude-3.7-sonnet | claude-3-7-sonnet-20250219-base | claude-3-7-sonnet-20250219-thinking-25k | 178 | 0.629 | 0.680 | 0.358 | -0.063 | 0.861 | -0.053 | -1.132 | 0.832 | 0.002 | 0.230 |
| livebench | claude-3.7-sonnet | claude-3-7-sonnet-20250219-thinking-25k | claude-3-7-sonnet-20250219-thinking-64k | 178 | 0.680 | 0.680 | -0.212 | -0.707 | 0.223 | -0.578 | -1.283 | -0.056 | -0.000 | 0.150 |
| livebench | o1 | o1-2024-12-17-low | o1-2024-12-17-medium | 178 | 0.506 | 0.534 | 0.128 | -0.201 | 0.433 | -0.253 | -0.816 | 0.246 | -0.001 | 0.131 |
| livebench | o1 | o1-2024-12-17-medium | o1-2024-12-17-high | 178 | 0.534 | 0.624 | 0.485 | 0.174 | 0.837 | 0.008 | -0.521 | 0.611 | 0.008 | 0.134 |
| livebench | o3-mini | o3-mini-2025-01-31-low | o3-mini-2025-01-31-medium | 228 | 0.561 | 0.605 | 0.223 | -0.105 | 0.534 | -0.057 | -0.491 | 0.333 | 0.007 | 0.114 |
| livebench | o3-mini | o3-mini-2025-01-31-medium | o3-mini-2025-01-31-high | 228 | 0.605 | 0.711 | 0.645 | 0.313 | 0.967 | 0.176 | -0.218 | 0.597 | 0.001 | 0.123 |

| scope | quantity | k | pooled | se | lo | hi | tau2 | Q |
|---|---|---|---|---|---|---|---|---|
| all adjacent pairs | delta a | 19 | 0.9172 | 0.1661 | 0.5916 | 1.2429 | 0.3499 | 117.7509 |
| all adjacent pairs | delta beta | 19 | 0.0319 | 0.0900 | -0.1445 | 0.2083 | 0.0000 | 13.9413 |
| all adjacent pairs | refit a and beta minus shift | 19 | 0.0041 | 0.0010 | 0.0022 | 0.0061 | 0.0000 | 24.6664 |
| all adjacent pairs | base rate minus shift | 19 | 0.1922 | 0.0168 | 0.1593 | 0.2252 | 0.0031 | 53.1576 |
| all adjacent pairs | low as is minus shift | 19 | 0.0341 | 0.0079 | 0.0187 | 0.0496 | 0.0007 | 194.2092 |
| all adjacent pairs | low's own items + one shift minus shift | 19 | 0.0066 | 0.0120 | -0.0170 | 0.0302 | 0.0015 | 45.6856 |
| one pair per model | delta a | 13 | 1.2092 | 0.2397 | 0.7394 | 1.6791 | 0.4880 | 88.2084 |
| one pair per model | delta beta | 13 | 0.1140 | 0.1161 | -0.1135 | 0.3416 | 0.0000 | 7.6262 |
| one pair per model | refit a and beta minus shift | 13 | 0.0044 | 0.0015 | 0.0016 | 0.0073 | 0.0000 | 19.6108 |
| one pair per model | base rate minus shift | 13 | 0.2076 | 0.0205 | 0.1675 | 0.2477 | 0.0032 | 35.2642 |
| one pair per model | low as is minus shift | 13 | 0.0588 | 0.0132 | 0.0329 | 0.0847 | 0.0014 | 166.5741 |
| one pair per model | low's own items + one shift minus shift | 13 | 0.0265 | 0.0142 | -0.0013 | 0.0544 | 0.0013 | 27.6409 |

Pairs left out of the pooling:

| source | model | low | high | items | acc low | acc high | delta a | delta a lo | delta a hi | delta beta | delta beta lo | delta beta hi |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| matharena | gpt-5.2 (setting unknown) | openai/gpt-52-high | openai/gpt-52 | 142 | 0.965 | 0.991 | 2.304 | 1.180 | 3.696 | 0.711 | -0.569 | 2.322 |
| matharena | gemini 2.0 flash (thinking checkpoint) | gemini/gemini-flash-2.0 | gemini/gemini-flash-thinking-2.0 | 60 | 0.204 | 0.446 | 3.954 | 2.032 | 7.773 | -1.621 | -5.348 | 0.491 |

## P3. One deeper call against the nearest-dollar vote (AH2 on public data)

MathArena pairs whose lower setting has 3 or more calls: 10 pairs. One call at the higher setting minus the odd-k vote of the lower setting with the nearest dollars per item (always the 3-vote here): 12.7 points (7.1 to 18.2); on the 7 pairs whose dollars are within a factor of 1.5, 11.9 (6.0 to 17.7). The step pays least at the top of a model's range (Gemini 3.1 Pro medium to default, Opus 5.5 high to max).

| model | low | high | items | nearest k | deep acc | deep usd | wide acc | wide usd | deep / wide dollars | difference | difference lo | difference hi | note |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| gpt-5.2 | openai/gpt-52-low | openai/gpt-52-high | 40 | 3.000 | 0.613 | 0.444 | 0.400 | 0.135 | 3.300 | 0.212 | 0.133 | 0.304 |  |
| o3-mini | openai/o3-mini--low | openai/o3-mini--medium | 60 | 3.000 | 0.650 | 0.038 | 0.372 | 0.041 | 0.920 | 0.278 | 0.172 | 0.400 |  |
| o3-mini | openai/o3-mini--medium | openai/o3-mini | 60 | 3.000 | 0.771 | 0.079 | 0.683 | 0.111 | 0.708 | 0.087 | 0.021 | 0.171 |  |
| o4-mini | openai/o4-mini--low | openai/o4-mini--medium | 183 | 3.000 | 0.754 | 0.026 | 0.650 | 0.029 | 0.889 | 0.104 | 0.054 | 0.144 |  |
| o4-mini | openai/o4-mini--medium | openai/o4-mini--high | 183 | 3.000 | 0.869 | 0.054 | 0.807 | 0.072 | 0.746 | 0.062 | 0.025 | 0.103 |  |
| gpt-5-nano | openai/gpt-5-nano-low | openai/gpt-5-nano | 30 | 3.000 | 0.850 | 0.011 | 0.567 | 0.002 | 4.579 | 0.283 | 0.142 | 0.442 |  |
| grok-3-mini | xai/grok-3-mini-low | xai/grok-3-mini-high | 183 | 3.000 | 0.772 | 0.010 | 0.596 | 0.009 | 1.123 | 0.176 | 0.127 | 0.219 |  |
| gemini-3.1-pro | gemini/gemini-31-pro-low | gemini/gemini-31-pro-medium | 23 | 3.000 | 0.674 | 0.119 | 0.449 | 0.081 | 1.471 | 0.225 | 0.086 | 0.406 |  |
| gemini-3.1-pro | gemini/gemini-31-pro-medium | gemini/gemini-31-pro | 23 | 3.000 | 0.707 | 0.350 | 0.696 | 0.313 | 1.119 | 0.011 | -0.038 | 0.060 |  |
| fable 5.1 | anthropic/fable_51_low | anthropic/fable_51_max | 0 |  |  |  |  |  |  |  |  |  | lower setting has under 3 calls, or under half the calls are priced |
| opus 5.5 | anthropic/opus_55_high | anthropic/opus_55_max | 88 | 3.000 | 0.795 | 1.040 | 0.811 | 0.329 | 3.159 | -0.015 | -0.087 | 0.053 |  |
| gpt-6 astra | openai/gpt-6-astra-low | openai/gpt-6-astra | 0 |  |  |  |  |  |  |  |  |  | lower setting has under 3 calls, or under half the calls are priced |

| scope | quantity | k | pooled | se | lo | hi | tau2 | Q |
|---|---|---|---|---|---|---|---|---|
| all pairs | difference | 10 | 0.1266 | 0.0282 | 0.0712 | 0.1819 | 0.0061 | 59.2793 |
| all pairs | difference vs 3-vote | 10 | 0.1264 | 0.0280 | 0.0714 | 0.1814 | 0.0060 | 58.2137 |
| dollars within a factor of 1.5 | difference | 7 | 0.1187 | 0.0297 | 0.0604 | 0.1770 | 0.0047 | 37.3277 |
| dollars within a factor of 1.5 | difference vs 3-vote | 7 | 0.1197 | 0.0293 | 0.0622 | 0.1772 | 0.0046 | 36.5723 |

## P4. When label-free selection works

Simulation map (one system at 0.85 one-call accuracy beside others at 0.3, 0.5 or 0.7; item difficulty sd 0.5 or 2.0, a systematic share of 0.07 or 0.55; 1 or 3 calls per system; averaged over 3, 5 and 9 systems and two levels of repeat agreement; 8 panels of 150 items per cell). Gains are over the best single system; "inverts" is the share of panels where the method rates another system above the truly best one.
- With weak companions and one call each, plain and pooled Dawid-Skene (observed-answer label space) invert and fall far below the strong system; a fixed label space (100 labels) removes the inversion but still loses to the strong system when difficulty is shared.
- With competent companions and little shared difficulty, every policy gains about 14 points; with a high systematic share the gain shrinks to about 5.
- MathArena panels: one strong system (0.85 or more) with weak ones (0.5 or less), one call each: every policy loses 31.6 to 42.4 points to the strong system and Dawid-Skene ranks another system first in 42-63% of panels; with 4 calls each, plain Dawid-Skene matches the strong system. Many competent systems (0.6-0.85) with 4 calls: every policy gains 7.4-8.2 points over one call of the best system, at four times its calls. Among competent systems the "best" one is a near tie, so its rank says little. LiveBench has no answers, so it cannot enter.
- Matched calls (three systems, one call each, against the best system's own 3-vote): lone strong, every policy loses 25.7 to 34.6 points; many competent, plurality -1.8, plain Dawid-Skene -1.0 points.
- On MathArena the fixed label space does not remove the inversion: with one call each it ranks another system first in 62-71% of lone-strong panels, against 42-63% for plain Dawid-Skene, unlike in the simulation.

| others | sd_b | systematic share | repeats | best single | coverage | plurality gain | Dawid-Skene gain | pooled Dawid-Skene gain | pooled Dawid-Skene, fixed labels gain | Dawid-Skene inverts | pooled Dawid-Skene inverts | pooled Dawid-Skene, fixed labels inverts |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.300 | 0.500 | 0.071 | 1 | 0.840 | 0.948 | -0.183 | -0.507 | -0.507 | -0.039 | 0.833 | 0.833 | 0.000 |
| 0.300 | 0.500 | 0.071 | 3 | 0.852 | 0.999 | 0.006 | 0.098 | -0.504 | 0.062 | 0.000 | 0.646 | 0.000 |
| 0.300 | 2.000 | 0.549 | 1 | 0.853 | 0.881 | -0.290 | -0.600 | -0.600 | -0.121 | 0.958 | 0.958 | 0.000 |
| 0.300 | 2.000 | 0.549 | 3 | 0.850 | 0.967 | -0.173 | -0.068 | -0.380 | -0.120 | 0.000 | 0.438 | 0.000 |
| 0.500 | 0.500 | 0.071 | 1 | 0.847 | 0.977 | -0.010 | -0.198 | -0.198 | 0.047 | 0.479 | 0.479 | 0.000 |
| 0.500 | 0.500 | 0.071 | 3 | 0.849 | 1.000 | 0.122 | 0.133 | -0.123 | 0.131 | 0.000 | 0.312 | 0.000 |
| 0.500 | 2.000 | 0.549 | 1 | 0.857 | 0.911 | -0.120 | -0.063 | -0.063 | -0.040 | 0.042 | 0.042 | 0.000 |
| 0.500 | 2.000 | 0.549 | 3 | 0.847 | 0.974 | -0.038 | 0.004 | -0.054 | -0.017 | 0.000 | 0.021 | 0.000 |
| 0.700 | 0.500 | 0.071 | 1 | 0.843 | 0.991 | 0.096 | 0.094 | 0.094 | 0.111 | 0.000 | 0.000 | 0.000 |
| 0.700 | 0.500 | 0.071 | 3 | 0.850 | 1.000 | 0.146 | 0.147 | 0.147 | 0.147 | 0.000 | 0.000 | 0.000 |
| 0.700 | 2.000 | 0.549 | 1 | 0.850 | 0.949 | 0.016 | 0.036 | 0.036 | 0.038 | 0.000 | 0.000 | 0.000 |
| 0.700 | 2.000 | 0.549 | 3 | 0.853 | 0.986 | 0.062 | 0.068 | 0.068 | 0.068 | 0.000 | 0.000 | 0.000 |

MathArena panels:

| kind | systems | calls | best single | coverage | plurality | Dawid-Skene | pooled Dawid-Skene | pooled Dawid-Skene, fixed labels | best system's own vote, same calls | plurality minus best system's own vote | Dawid-Skene minus best system's own vote | pooled Dawid-Skene minus best system's own vote | pooled Dawid-Skene, fixed labels minus best system's own vote | plurality gain | Dawid-Skene gain | pooled Dawid-Skene gain | pooled Dawid-Skene, fixed labels gain | Dawid-Skene inverts | pooled Dawid-Skene inverts | pooled Dawid-Skene, fixed labels inverts | panels |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| lone strong | 3 | all 4 calls | 0.920 | 0.982 | 0.820 | 0.950 | 0.779 | 0.896 |  |  |  |  |  | -0.100 | 0.031 | -0.141 | -0.023 | 0.000 | 0.142 | 0.000 | 120 |
| lone strong | 3 | call 0 | 0.926 | 0.941 | 0.610 | 0.692 | 0.692 | 0.603 | 0.950 | -0.340 | -0.257 | -0.257 | -0.346 | -0.316 | -0.234 | -0.234 | -0.323 | 0.417 | 0.417 | 0.617 | 120 |
| lone strong | 5 | all 4 calls | 0.928 | 0.985 | 0.702 | 0.928 | 0.691 | 0.792 |  |  |  |  |  | -0.225 | 0.000 | -0.237 | -0.136 | 0.000 | 0.233 | 0.000 | 90 |
| lone strong | 5 | call 0 | 0.942 | 0.958 | 0.558 | 0.518 | 0.518 | 0.584 |  |  |  |  |  | -0.384 | -0.424 | -0.424 | -0.358 | 0.633 | 0.633 | 0.711 | 90 |
| many competent | 3 | all 4 calls | 0.804 | 0.954 | 0.879 | 0.883 | 0.882 | 0.884 |  |  |  |  |  | 0.075 | 0.079 | 0.078 | 0.080 | 0.222 | 0.200 | 0.211 | 180 |
| many competent | 3 | call 0 | 0.851 | 0.921 | 0.833 | 0.841 | 0.841 | 0.848 | 0.851 | -0.018 | -0.010 | -0.010 | -0.003 | -0.018 | -0.010 | -0.010 | -0.002 | 0.322 | 0.322 | 0.261 | 180 |
| many competent | 5 | all 4 calls | 0.824 | 0.964 | 0.898 | 0.906 | 0.906 | 0.906 |  |  |  |  |  | 0.074 | 0.082 | 0.083 | 0.082 | 0.344 | 0.350 | 0.356 | 180 |
| many competent | 5 | call 0 | 0.870 | 0.947 | 0.876 | 0.881 | 0.881 | 0.880 |  |  |  |  |  | 0.006 | 0.011 | 0.011 | 0.010 | 0.394 | 0.394 | 0.417 | 180 |

## P5. The price of verification

Random 2-5 system sets, one call each. Room: coverage minus the best member, what a perfect selector adds. Price: the set's dollars minus the best member's, per point of room. "Above top at its dollars": the share of sets whose selected accuracy (best member + eta x room) beats the benchmark's most accurate system while costing no more. Judge calls are not priced here, so these shares are upper bounds.
- SWE-bench Verified: the room grows from 4.8 points (pairs) to 8.3 (5 systems) at $0.062 to $0.163 per point per task; a judge with the anchor's best measured eta beats Claude Opus 4.5 (high) at its dollars in at most 10% of sets, a perfect selector in at most 13%.
- MathArena: the room is 1 to 4.5 points, because the top systems are near 100% on most sets.
- The anchor (read.md): the Sol low judge captured eta 0.70 (0.57 to 0.80) of the room over cheap pools on BBEH, reaching 52.3%, yet Sol low answering alone scored 60.6% at $0.0024 per item against $0.0040 for the judge and its pools. The pools covered only 58.0% of the items, below Sol alone, so even a perfect selector over them would have lost: the comparison measures the pools, not the judge's signal. A fair test needs pools whose coverage exceeds the judge model's own accuracy.

| source | k | best single | coverage | room | extra usd | extra usd per point of room | top system | top usd | above top at its dollars, eta sol_low bbeh (0.70) | above top at its dollars, eta 1 (perfect selector) |
|---|---|---|---|---|---|---|---|---|---|---|
| livebench/LCB_generation | 2 | 0.513 | 0.537 | 0.024 |  |  | 0.897 |  | 0.000 | 0.000 |
| livebench/LCB_generation | 3 | 0.550 | 0.585 | 0.035 |  |  | 0.897 |  | 0.000 | 0.000 |
| livebench/LCB_generation | 4 | 0.622 | 0.667 | 0.045 |  |  | 0.897 |  | 0.000 | 0.000 |
| livebench/LCB_generation | 5 | 0.639 | 0.695 | 0.056 |  |  | 0.897 |  | 0.000 | 0.000 |
| livebench/coding_completion | 2 | 0.475 | 0.517 | 0.042 |  |  | 0.860 |  | 0.000 | 0.000 |
| livebench/coding_completion | 3 | 0.533 | 0.607 | 0.074 |  |  | 0.860 |  | 0.000 | 0.000 |
| livebench/coding_completion | 4 | 0.588 | 0.689 | 0.101 |  |  | 0.860 |  | 0.000 | 0.000 |
| livebench/coding_completion | 5 | 0.633 | 0.739 | 0.106 |  |  | 0.860 |  | 0.000 | 0.000 |
| livebench/typos | 2 | 0.592 | 0.681 | 0.088 |  |  | 0.806 |  | 0.000 | 0.000 |
| livebench/typos | 3 | 0.627 | 0.765 | 0.138 |  |  | 0.806 |  | 0.000 | 0.000 |
| livebench/typos | 4 | 0.645 | 0.809 | 0.164 |  |  | 0.806 |  | 0.000 | 0.000 |
| livebench/typos | 5 | 0.658 | 0.838 | 0.180 |  |  | 0.806 |  | 0.000 | 0.000 |
| matharena/aime_2025 | 2 | 0.867 | 0.877 | 0.010 | 0.100 | 0.097 | 1.000 | 0.076 | 0.000 | 0.000 |
| matharena/aime_2025 | 3 | 0.935 | 0.947 | 0.012 | 0.208 | 0.169 | 1.000 | 0.076 | 0.000 | 0.000 |
| matharena/aime_2025 | 4 | 0.943 | 0.957 | 0.014 | 0.366 | 0.268 | 1.000 | 0.076 | 0.000 | 0.000 |
| matharena/aime_2025 | 5 | 0.954 | 0.965 | 0.011 | 0.482 | 0.438 | 1.000 | 0.076 | 0.000 | 0.000 |
| matharena/arxivmath-0626 | 2 | 0.779 | 0.818 | 0.039 | 0.612 | 0.155 | 0.938 | 0.142 | 0.000 | 0.000 |
| matharena/arxivmath-0626 | 3 | 0.841 | 0.883 | 0.043 | 2.116 | 0.497 | 0.938 | 0.142 | 0.000 | 0.000 |
| matharena/arxivmath-0626 | 4 | 0.862 | 0.905 | 0.043 | 2.992 | 0.694 | 0.938 | 0.142 | 0.000 | 0.000 |
| matharena/arxivmath-0626 | 5 | 0.877 | 0.922 | 0.045 | 4.327 | 0.964 | 0.938 | 0.142 | 0.000 | 0.000 |
| matharena/hmmt_feb_2025 | 2 | 0.843 | 0.862 | 0.018 | 0.069 | 0.037 | 1.000 | 0.008 | 0.000 | 0.000 |
| matharena/hmmt_feb_2025 | 3 | 0.903 | 0.927 | 0.024 | 0.166 | 0.070 | 1.000 | 0.008 | 0.000 | 0.000 |
| matharena/hmmt_feb_2025 | 4 | 0.928 | 0.949 | 0.021 | 0.237 | 0.114 | 1.000 | 0.008 | 0.000 | 0.000 |
| matharena/hmmt_feb_2025 | 5 | 0.953 | 0.975 | 0.022 | 0.348 | 0.155 | 1.000 | 0.008 | 0.000 | 0.000 |
| matharena/hmmt_feb_2026 | 2 | 0.939 | 0.960 | 0.021 | 0.086 | 0.041 | 1.000 | 0.012 | 0.000 | 0.000 |
| matharena/hmmt_feb_2026 | 3 | 0.961 | 0.981 | 0.020 | 0.207 | 0.101 | 1.000 | 0.012 | 0.000 | 0.000 |
| matharena/hmmt_feb_2026 | 4 | 0.965 | 0.987 | 0.022 | 0.318 | 0.144 | 1.000 | 0.012 | 0.000 | 0.000 |
| matharena/hmmt_feb_2026 | 5 | 0.973 | 0.992 | 0.019 | 0.492 | 0.258 | 1.000 | 0.012 | 0.000 | 0.000 |
| matharena/smt_2025 | 2 | 0.899 | 0.919 | 0.020 | 0.045 | 0.022 | 0.962 | 0.140 | 0.000 | 0.000 |
| matharena/smt_2025 | 3 | 0.916 | 0.939 | 0.022 | 0.103 | 0.046 | 0.962 | 0.140 | 0.000 | 0.000 |
| matharena/smt_2025 | 4 | 0.933 | 0.951 | 0.018 | 0.152 | 0.083 | 0.962 | 0.140 | 0.000 | 0.000 |
| matharena/smt_2025 | 5 | 0.935 | 0.953 | 0.018 | 0.210 | 0.116 | 0.962 | 0.140 | 0.000 | 0.000 |
| swebench_verified | 2 | 0.686 | 0.733 | 0.048 | 0.298 | 0.062 | 0.768 | 0.754 | 0.095 | 0.130 |
| swebench_verified | 3 | 0.714 | 0.778 | 0.064 | 0.633 | 0.099 | 0.768 | 0.754 | 0.065 | 0.095 |
| swebench_verified | 4 | 0.727 | 0.804 | 0.076 | 1.029 | 0.135 | 0.768 | 0.754 | 0.020 | 0.020 |
| swebench_verified | 5 | 0.734 | 0.817 | 0.083 | 1.356 | 0.163 | 0.768 | 0.754 | 0.005 | 0.005 |

Anchor judges:

| judge | items | n | judge accuracy | eta | eta lo | eta hi | best pool arm | coverage | judge model alone | judge model alone usd | judge usd | pool usd |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku_high_judge | bbeh | 440 | 0.4270 | 0.4100 | 0.1760 | 0.6220 | 0.3890 | 0.4820 | 0.4598 | 0.0010 | 0.0010 | 0.0010 |
| sol_low_judge | bbeh | 440 | 0.5230 | 0.7010 | 0.5710 | 0.7960 | 0.3890 | 0.5800 | 0.6061 | 0.0024 | 0.0020 | 0.0020 |
| sol_low_judge | math | 93 | 0.1400 | 0.2500 | -0.2970 | 0.6570 | 0.1110 | 0.2260 | 0.3513 | 0.0321 | 0.0110 | 0.0040 |
| sol_low_judge | all | 533 | 0.4560 | 0.6530 | 0.5270 | 0.7530 | 0.3400 | 0.5180 | 0.5616 | 0.0076 | 0.0040 | 0.0020 |

## P6. Intervals for the systematic shares

L0 share var(b) / (var(b) + pi^2/3) and the median L1 share, refitted per draw. Item draws resample items within each task family (95% interval). For systems, a bootstrap repeats systems and raises the share, so the systems are instead split at random into two halves, 20 times, each half fitted on its own; the table gives the range of the 40 half shares (a half has fewer systems, so the range is wider than an interval for the full set would be). The anchor's shares (0.65 BBEH, 0.43 math) need the gold files in data/external/ and wait for E6's fetch script.

| source | quantity | share | item lo | item hi | item draws | half-split min | half-split max | halves |
|---|---|---|---|---|---|---|---|---|
| swebench_verified | (all) L0 | 0.728 | 0.703 | 0.749 | 200 | 0.707 | 0.728 | 40 |
| swebench_verified | (all) L1 median | 0.769 | 0.742 | 0.792 | 200 | 0.757 | 0.785 | 40 |
| swebench_verified | swebench_verified L0 | 0.728 | 0.703 | 0.749 | 200 | 0.707 | 0.728 | 40 |
| matharena | (all) L0 | 0.732 | 0.718 | 0.748 | 200 | 0.668 | 0.707 | 40 |
| matharena | (all) L1 median | 0.805 | 0.787 | 0.825 | 200 | 0.752 | 0.822 | 40 |
| matharena | matharena/aime_2025 L0 | 0.670 | 0.538 | 0.754 | 200 | 0.593 | 0.675 | 40 |
| matharena | matharena/aime_2026 L0 | 0.444 | 0.112 | 0.616 | 200 | 0.313 | 0.469 | 40 |
| matharena | matharena/apex_2025 L0 | 0.148 | 0.063 | 0.217 | 200 | 0.081 | 0.274 | 40 |
| matharena | matharena/apex_shortlist L0 | 0.298 | 0.217 | 0.359 | 200 | 0.275 | 0.412 | 40 |
| matharena | matharena/arxivmath-0126 L0 | 0.722 | 0.605 | 0.778 | 200 | 0.664 | 0.745 | 40 |
| matharena | matharena/arxivmath-0226 L0 | 0.674 | 0.575 | 0.744 | 200 | 0.595 | 0.698 | 40 |
| matharena | matharena/arxivmath-0326 L0 | 0.637 | 0.538 | 0.700 | 200 | 0.554 | 0.682 | 40 |
| matharena | matharena/arxivmath-0426 L0 | 0.683 | 0.589 | 0.744 | 200 | 0.587 | 0.718 | 40 |
| matharena | matharena/arxivmath-0526 L0 | 0.692 | 0.582 | 0.777 | 200 | 0.635 | 0.706 | 40 |
| matharena | matharena/arxivmath-0626 L0 | 0.627 | 0.498 | 0.717 | 200 | 0.559 | 0.695 | 40 |
| matharena | matharena/arxivmath-1225 L0 | 0.747 | 0.598 | 0.800 | 200 | 0.683 | 0.743 | 40 |
| matharena | matharena/brumo_2025 L0 | 0.497 | 0.353 | 0.597 | 200 | 0.362 | 0.512 | 40 |
| matharena | matharena/cmimc_2025 L0 | 0.556 | 0.456 | 0.647 | 200 | 0.443 | 0.569 | 40 |
| matharena | matharena/hmmt_feb_2025 L0 | 0.570 | 0.426 | 0.647 | 200 | 0.486 | 0.605 | 40 |
| matharena | matharena/hmmt_feb_2026 L0 | 0.516 | 0.397 | 0.610 | 200 | 0.397 | 0.512 | 40 |
| matharena | matharena/hmmt_nov_2025 L0 | 0.546 | 0.245 | 0.703 | 200 | 0.418 | 0.534 | 40 |
| matharena | matharena/kangaroo_2025_1-2 L0 | 0.587 | 0.480 | 0.638 | 200 | 0.440 | 0.593 | 40 |
| matharena | matharena/kangaroo_2025_11-12 L0 | 0.380 | 0.276 | 0.474 | 200 | 0.224 | 0.393 | 40 |
| matharena | matharena/kangaroo_2025_3-4 L0 | 0.571 | 0.436 | 0.655 | 200 | 0.462 | 0.618 | 40 |
| matharena | matharena/kangaroo_2025_5-6 L0 | 0.626 | 0.543 | 0.683 | 200 | 0.496 | 0.648 | 40 |
| matharena | matharena/kangaroo_2025_7-8 L0 | 0.530 | 0.309 | 0.639 | 200 | 0.359 | 0.533 | 40 |
| matharena | matharena/kangaroo_2025_9-10 L0 | 0.345 | 0.131 | 0.450 | 200 | 0.140 | 0.397 | 40 |
| matharena | matharena/smt_2025 L0 | 0.689 | 0.547 | 0.762 | 200 | 0.603 | 0.680 | 40 |
| livebench | (all) L0 | 0.649 | 0.614 | 0.685 | 200 | 0.626 | 0.657 | 40 |
| livebench | (all) L1 median | 0.733 | 0.693 | 0.774 | 200 | 0.699 | 0.762 | 40 |
| livebench | livebench/LCB_generation L0 | 0.730 | 0.677 | 0.766 | 200 | 0.698 | 0.738 | 40 |
| livebench | livebench/coding_completion L0 | 0.542 | 0.470 | 0.621 | 200 | 0.497 | 0.602 | 40 |
| livebench | livebench/typos L0 | 0.597 | 0.527 | 0.658 | 200 | 0.566 | 0.624 | 40 |
| bbeh_phase1 | (all) L0 | 0.424 | 0.379 | 0.466 | 200 | 0.414 | 0.475 | 40 |
| bbeh_phase1 | (all) L1 median | 0.620 | 0.476 | 0.730 | 200 | 0.655 | 0.741 | 40 |
| bbeh_phase1 | bbeh/boolean expressions L0 | 0.411 | 0.306 | 0.482 | 200 | 0.414 | 0.460 | 40 |
| bbeh_phase1 | bbeh/dyck languages L0 | 0.378 | 0.270 | 0.462 | 200 | 0.350 | 0.454 | 40 |
| bbeh_phase1 | bbeh/geometric shapes L0 | 0.503 | 0.435 | 0.567 | 200 | 0.459 | 0.523 | 40 |
| bbeh_phase1 | bbeh/web of lies L0 | 0.333 | 0.251 | 0.393 | 200 | 0.224 | 0.415 | 40 |
| swebench_verified (39 with details) | (all) L0 | 0.692 | 0.668 | 0.711 | 200 | 0.646 | 0.695 | 40 |
| swebench_verified (39 with details) | (all) L1 median | 0.775 | 0.746 | 0.804 | 200 | 0.734 | 0.829 | 40 |
| swebench_verified (39 with details) | swebench_verified L0 | 0.692 | 0.668 | 0.711 | 200 | 0.646 | 0.695 | 40 |

## P7. Composition where it matters: mixed panels of weaker systems

Panels of 3 and 5 different MathArena systems with one-call accuracy 0.2-0.7 (one call each; 1577 and 1585 panels in 5 sets), cross-fitted. The vote gains 5.7 points over the mean member with 3 systems and 12.5 with 5.
- Factor model: error 6.4 and 6.6 points, bias 0.4 and 0.4.
- Zero-gain: absolute error larger by 1.8 and 7.0 points; the factor model is closer in 4 of 5 sets (3 systems) and 4 of 5 (5).
- Independence: absolute error larger by 5.5 and 9.6 points; the factor model is closer in 4 and 5 sets.
- No intervals: with 15-25 test items per set, item-bootstrap intervals of these errors were far from symmetric (audit W1-1); the per-set table replaces them.
- The item-level wrong-answer coincidence (from systems outside the panel) changes nothing material.

| k | panels | sets | MAE factor model | MAE factor model, item coincidence | MAE independence | MAE zero-gain | bias factor model | bias factor model, item coincidence | bias independence | bias zero-gain | MAE independence minus factor model | MSE independence minus factor model (points^2) | MAE zero-gain minus factor model | MSE zero-gain minus factor model (points^2) | mean observed vote | mean member accuracy (zero-gain) | sets where the factor model beats zero-gain | sets where the factor model beats independence |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | 1577 | 5 | 0.0637 | 0.0638 | 0.1185 | 0.0822 | 0.0040 | 0.0023 | 0.0337 | -0.0567 | 0.0548 | 148.7855 | 0.0185 | 33.5715 | 0.5295 | 0.4727 | 4 | 4 |
| 5 | 1585 | 5 | 0.0662 | 0.0657 | 0.1621 | 0.1364 | 0.0040 | 0.0025 | 0.1230 | -0.1254 | 0.0959 | 318.2373 | 0.0702 | 153.6749 | 0.5949 | 0.4696 | 4 | 5 |

| k | set | panels | MAE factor model | MAE factor model, item coincidence | MAE independence | MAE zero-gain | bias factor model | bias factor model, item coincidence | bias independence | bias zero-gain | MAE independence minus factor model | MSE independence minus factor model (points^2) | MAE zero-gain minus factor model | MSE zero-gain minus factor model (points^2) | mean observed vote | mean member accuracy (zero-gain) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 3 | matharena/aime_2025 | 400.0000 | 0.0556 | 0.0554 | 0.0732 | 0.0588 | 0.0281 | 0.0280 | 0.0610 | -0.0358 | 0.0177 | 32.3776 | 0.0032 | 4.9829 | 0.5295 | 0.4937 |
| 3 | matharena/apex_shortlist | 388.0000 | 0.0888 | 0.0895 | 0.1712 | 0.1190 | -0.0039 | -0.0066 | 0.0367 | -0.0712 | 0.0824 | 306.2667 | 0.0302 | 49.1703 | 0.5350 | 0.4639 |
| 3 | matharena/arxivmath-0626 | 365.0000 | 0.0574 | 0.0582 | 0.1140 | 0.0964 | -0.0283 | -0.0307 | -0.0142 | -0.0906 | 0.0567 | 113.0376 | 0.0390 | 74.5465 | 0.5931 | 0.5024 |
| 3 | matharena/hmmt_feb_2025 | 400.0000 | 0.0543 | 0.0532 | 0.1213 | 0.0603 | 0.0153 | 0.0129 | 0.0476 | -0.0360 | 0.0670 | 152.6538 | 0.0060 | 12.4998 | 0.4569 | 0.4209 |
| 3 | matharena/smt_2025 | 24.0000 | 0.0472 | 0.0533 | 0.0455 | 0.0260 | 0.0363 | 0.0441 | 0.0254 | -0.0023 | -0.0018 | 22.1638 | -0.0212 | -14.0982 | 0.6821 | 0.6797 |
| 5 | matharena/aime_2025 | 400.0000 | 0.0552 | 0.0559 | 0.1632 | 0.1159 | 0.0291 | 0.0307 | 0.1627 | -0.1151 | 0.1080 | 252.7891 | 0.0608 | 128.3574 | 0.6145 | 0.4994 |
| 5 | matharena/apex_shortlist | 379.0000 | 0.1048 | 0.1069 | 0.1968 | 0.1796 | 0.0039 | 0.0026 | 0.1140 | -0.1356 | 0.0920 | 423.9707 | 0.0747 | 182.1399 | 0.5948 | 0.4593 |
| 5 | matharena/arxivmath-0626 | 400.0000 | 0.0468 | 0.0481 | 0.1230 | 0.1395 | -0.0254 | -0.0276 | 0.0759 | -0.1393 | 0.0762 | 192.2693 | 0.0927 | 190.7302 | 0.6296 | 0.4903 |
| 5 | matharena/hmmt_feb_2025 | 400.0000 | 0.0606 | 0.0543 | 0.1689 | 0.1146 | 0.0079 | 0.0037 | 0.1400 | -0.1135 | 0.1083 | 413.8738 | 0.0540 | 117.2921 | 0.5388 | 0.4253 |
| 5 | matharena/smt_2025 | 6.0000 | 0.0342 | 0.0519 | 0.0592 | 0.0317 | 0.0342 | 0.0519 | 0.0592 | -0.0317 | 0.0250 | 24.7294 | -0.0025 | -1.3663 | 0.7304 | 0.6988 |

## P8. The all-wrong tail on held-out items

arXiv 2606.27288 reports that a calibrated one-factor copula underprices the share of items every system fails by about 2.5x on open-ended math. Here half the systems fit difficulties, held-out systems are fitted on half the items (calibration), and the tail is scored on the other half (test). The factor model and the copula get the same information, the calibration items only (audit W1-1, item 1); the factor model given each test item's difficulty from the other systems' answers on it is shown beside them, with the share of test items those other systems all fail.
- SWE-bench Verified, all 87 held-out systems: 7.6% of test tasks are failed by all (19 of 250; Clopper-Pearson 4.6 to 11.6). Same information: factor model 5.9, copula 3.5, independence 0.00. More information: factor model with test-item difficulty 6.9; the other systems alone fail 7.2%.
- MathArena, 5-system sets: the factor model underpredicts the tail on 2 of 6 sets (interval above 0), the copula on 2; the test halves hold 15 to 26 items, so the math tail is poorly measured.

| benchmark | k | members | test items | observed all-wrong | factor model | copula | independence | observed minus factor model | observed minus factor model lo | observed minus factor model hi | observed minus copula | observed minus copula lo | observed minus copula hi | factor model, test-item difficulty | fit systems all wrong on the test items | all-wrong items |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| swebench_verified | 2 | 2 | 250 | 0.3348 | 0.3263 | 0.3289 | 0.2292 | 0.0085 | -0.0372 | 0.0600 | 0.0059 | -0.0398 | 0.0574 | 0.3366 | 0.0720 |  |
| swebench_verified | 3 | 3 | 250 | 0.2927 | 0.2795 | 0.2795 | 0.1236 | 0.0132 | -0.0208 | 0.0552 | 0.0132 | -0.0207 | 0.0552 | 0.2915 | 0.0720 |  |
| swebench_verified | 5 | 5 | 250 | 0.2217 | 0.2065 | 0.1930 | 0.0273 | 0.0151 | -0.0308 | 0.0622 | 0.0287 | -0.0173 | 0.0758 | 0.2193 | 0.0720 |  |
| swebench_verified | 10 | 10 | 250 | 0.1697 | 0.1517 | 0.1264 | 0.0007 | 0.0180 | -0.0210 | 0.0644 | 0.0433 | 0.0043 | 0.0897 | 0.1630 | 0.0720 |  |
| swebench_verified | 20 | 20 | 250 | 0.1339 | 0.1168 | 0.0848 | 0.0000 | 0.0171 | -0.0214 | 0.0483 | 0.0491 | 0.0106 | 0.0803 | 0.1290 | 0.0720 |  |
| swebench_verified | all | 87 | 250 | 0.0760 | 0.0588 | 0.0354 | 0.0000 | 0.0172 | -0.0188 | 0.0492 | 0.0406 | 0.0046 | 0.0726 | 0.0694 | 0.0720 | 19.0000 |
| livebench/LCB_generation | 2 | 2 | 39 | 0.4946 | 0.3936 | 0.4033 | 0.2929 | 0.1010 | 0.0100 | 0.1991 | 0.0913 | 0.0003 | 0.1894 | 0.4756 | 0.0769 |  |
| livebench/LCB_generation | 3 | 3 | 39 | 0.3941 | 0.2988 | 0.3088 | 0.1421 | 0.0953 | -0.0118 | 0.2233 | 0.0853 | -0.0217 | 0.2134 | 0.3750 | 0.0769 |  |
| livebench/LCB_generation | 5 | 5 | 39 | 0.3291 | 0.2430 | 0.2536 | 0.0474 | 0.0861 | -0.0190 | 0.1826 | 0.0755 | -0.0296 | 0.1720 | 0.3102 | 0.0769 |  |
| livebench/LCB_generation | 10 | 10 | 39 | 0.1946 | 0.1495 | 0.1672 | 0.0016 | 0.0451 | -0.0339 | 0.1591 | 0.0274 | -0.0516 | 0.1414 | 0.1865 | 0.0769 |  |
| livebench/LCB_generation | 20 | 20 | 39 | 0.1112 | 0.0872 | 0.1130 | 0.0000 | 0.0239 | -0.0515 | 0.1030 | -0.0018 | -0.0772 | 0.0772 | 0.1059 | 0.0769 |  |
| livebench/LCB_generation | all | 75 | 39 | 0.0513 | 0.0166 | 0.0515 | 0.0000 | 0.0347 | -0.0166 | 0.1116 | -0.0002 | -0.0515 | 0.0767 | 0.0183 | 0.0769 | 2.0000 |
| livebench/coding_completion | 2 | 2 | 25 | 0.4122 | 0.4967 | 0.5147 | 0.4390 | -0.0845 | -0.1820 | 0.0179 | -0.1025 | -0.2000 | -0.0001 | 0.4279 | 0.0000 |  |
| livebench/coding_completion | 3 | 3 | 25 | 0.2864 | 0.3801 | 0.3940 | 0.2561 | -0.0937 | -0.1769 | 0.0039 | -0.1076 | -0.1908 | -0.0099 | 0.2943 | 0.0000 |  |
| livebench/coding_completion | 5 | 5 | 25 | 0.1880 | 0.2957 | 0.3127 | 0.1169 | -0.1077 | -0.1828 | -0.0227 | -0.1247 | -0.1998 | -0.0397 | 0.2008 | 0.0000 |  |
| livebench/coding_completion | 10 | 10 | 25 | 0.0902 | 0.1906 | 0.2111 | 0.0140 | -0.1004 | -0.1588 | -0.0394 | -0.1209 | -0.1793 | -0.0599 | 0.0994 | 0.0000 |  |
| livebench/coding_completion | 20 | 20 | 25 | 0.0260 | 0.1003 | 0.1345 | 0.0001 | -0.0743 | -0.0915 | -0.0503 | -0.1085 | -0.1257 | -0.0845 | 0.0357 | 0.0000 |  |
| livebench/coding_completion | all | 75 | 25 | 0.0000 | 0.0064 | 0.0542 | 0.0000 | -0.0064 | -0.0064 | -0.0064 | -0.0542 | -0.0542 | -0.0542 | 0.0003 | 0.0000 | 0.0000 |
| livebench/typos | 2 | 2 | 49 | 0.3084 | 0.3269 | 0.3319 | 0.2399 | -0.0185 | -0.1058 | 0.0634 | -0.0235 | -0.1108 | 0.0584 | 0.2955 | 0.0816 |  |
| livebench/typos | 3 | 3 | 49 | 0.2251 | 0.2326 | 0.2482 | 0.1117 | -0.0075 | -0.0989 | 0.0762 | -0.0231 | -0.1145 | 0.0605 | 0.2124 | 0.0816 |  |
| livebench/typos | 5 | 5 | 49 | 0.1540 | 0.1392 | 0.1691 | 0.0261 | 0.0148 | -0.0530 | 0.0847 | -0.0152 | -0.0829 | 0.0548 | 0.1434 | 0.0816 |  |
| livebench/typos | 10 | 10 | 49 | 0.0892 | 0.0527 | 0.0931 | 0.0005 | 0.0364 | -0.0148 | 0.1032 | -0.0040 | -0.0552 | 0.0628 | 0.0896 | 0.0816 |  |
| livebench/typos | 20 | 20 | 49 | 0.0427 | 0.0128 | 0.0519 | 0.0000 | 0.0299 | -0.0043 | 0.0782 | -0.0092 | -0.0434 | 0.0391 | 0.0607 | 0.0816 |  |
| livebench/typos | all | 31 | 49 | 0.0204 | 0.0032 | 0.0352 | 0.0000 | 0.0172 | -0.0032 | 0.0581 | -0.0148 | -0.0352 | 0.0260 | 0.0448 | 0.0816 | 1.0000 |
| matharena/aime_2025 | 2 | 2 | 15 | 0.0987 | 0.0947 | 0.0911 | 0.0544 | 0.0039 | -0.0698 | 0.1240 | 0.0075 | -0.0662 | 0.1276 | 0.0980 | 0.0000 |  |
| matharena/aime_2025 | 3 | 3 | 15 | 0.0703 | 0.0529 | 0.0536 | 0.0158 | 0.0174 | -0.0483 | 0.1371 | 0.0167 | -0.0489 | 0.1364 | 0.0583 | 0.0000 |  |
| matharena/aime_2025 | 5 | 5 | 15 | 0.0543 | 0.0152 | 0.0170 | 0.0009 | 0.0391 | -0.0142 | 0.1458 | 0.0373 | -0.0160 | 0.1440 | 0.0195 | 0.0000 |  |
| matharena/aime_2025 | 10 | 10 | 15 | 0.0300 | 0.0019 | 0.0021 | 0.0000 | 0.0281 | -0.0019 | 0.0881 | 0.0279 | -0.0021 | 0.0879 | 0.0033 | 0.0000 |  |
| matharena/aime_2025 | 20 | 20 | 15 | 0.0113 | 0.0000 | 0.0001 | 0.0000 | 0.0113 | -0.0000 | 0.0453 | 0.0113 | -0.0001 | 0.0453 | 0.0001 | 0.0000 |  |
| matharena/aime_2025 | all | 33 | 15 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | 0.0000 | 0.0000 | 0.0000 |
| matharena/hmmt_feb_2025 | 2 | 2 | 15 | 0.2390 | 0.1108 | 0.1103 | 0.0839 | 0.1282 | 0.0185 | 0.2388 | 0.1287 | 0.0190 | 0.2393 | 0.1802 | 0.0000 |  |
| matharena/hmmt_feb_2025 | 3 | 3 | 15 | 0.1647 | 0.0471 | 0.0503 | 0.0270 | 0.1176 | 0.0311 | 0.2250 | 0.1144 | 0.0279 | 0.2218 | 0.0910 | 0.0000 |  |
| matharena/hmmt_feb_2025 | 5 | 5 | 15 | 0.0657 | 0.0071 | 0.0078 | 0.0013 | 0.0586 | 0.0079 | 0.1347 | 0.0578 | 0.0071 | 0.1339 | 0.0213 | 0.0000 |  |
| matharena/hmmt_feb_2025 | 10 | 10 | 15 | 0.0123 | 0.0001 | 0.0000 | 0.0000 | 0.0123 | -0.0001 | 0.0346 | 0.0123 | -0.0000 | 0.0347 | 0.0005 | 0.0000 |  |
| matharena/hmmt_feb_2025 | 20 | 20 | 15 | 0.0007 | 0.0000 | 0.0000 | 0.0000 | 0.0007 | -0.0000 | 0.0020 | 0.0007 | -0.0000 | 0.0020 | 0.0000 | 0.0000 |  |
| matharena/hmmt_feb_2025 | all | 32 | 15 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | 0.0000 | 0.0000 | 0.0000 |
| matharena/smt_2025 | 2 | 2 | 26 | 0.1212 | 0.0422 | 0.0422 | 0.0169 | 0.0790 | -0.0097 | 0.1835 | 0.0790 | -0.0097 | 0.1835 | 0.0741 | 0.0769 |  |
| matharena/smt_2025 | 3 | 3 | 26 | 0.1073 | 0.0188 | 0.0193 | 0.0023 | 0.0885 | -0.0088 | 0.1866 | 0.0880 | -0.0093 | 0.1861 | 0.0475 | 0.0769 |  |
| matharena/smt_2025 | 5 | 5 | 26 | 0.0921 | 0.0042 | 0.0055 | 0.0000 | 0.0879 | -0.0042 | 0.1956 | 0.0866 | -0.0055 | 0.1943 | 0.0239 | 0.0769 |  |
| matharena/smt_2025 | 10 | 10 | 26 | 0.0704 | 0.0001 | 0.0003 | 0.0000 | 0.0703 | -0.0001 | 0.1408 | 0.0701 | -0.0003 | 0.1406 | 0.0024 | 0.0769 |  |
| matharena/smt_2025 | 20 | 20 | 26 | 0.0421 | 0.0000 | 0.0000 | 0.0000 | 0.0421 | -0.0000 | 0.1223 | 0.0421 | -0.0000 | 0.1223 | 0.0000 | 0.0769 |  |
| matharena/smt_2025 | all | 22 | 26 | 0.0385 | 0.0000 | 0.0000 | 0.0000 | 0.0385 | -0.0000 | 0.1154 | 0.0385 | -0.0000 | 0.1154 | 0.0000 | 0.0769 | 1.0000 |
| matharena/apex_shortlist | 2 | 2 | 23 | 0.1449 | 0.1479 | 0.1476 | 0.1225 | -0.0031 | -0.0519 | 0.0425 | -0.0028 | -0.0516 | 0.0428 | 0.1359 | 0.0000 |  |
| matharena/apex_shortlist | 3 | 3 | 23 | 0.0672 | 0.0668 | 0.0695 | 0.0404 | 0.0004 | -0.0294 | 0.0375 | -0.0024 | -0.0321 | 0.0347 | 0.0532 | 0.0000 |  |
| matharena/apex_shortlist | 5 | 5 | 23 | 0.0126 | 0.0194 | 0.0211 | 0.0046 | -0.0068 | -0.0155 | 0.0035 | -0.0085 | -0.0172 | 0.0017 | 0.0108 | 0.0000 |  |
| matharena/apex_shortlist | 10 | 10 | 23 | 0.0002 | 0.0006 | 0.0015 | 0.0000 | -0.0004 | -0.0006 | 0.0000 | -0.0013 | -0.0015 | -0.0009 | 0.0001 | 0.0000 |  |
| matharena/apex_shortlist | all | 20 | 23 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | 0.0000 | 0.0000 | 0.0000 |
| matharena/arxivmath-0626 | 2 | 2 | 24 | 0.2201 | 0.1368 | 0.1451 | 0.0873 | 0.0834 | -0.0452 | 0.2014 | 0.0750 | -0.0535 | 0.1930 | 0.2142 | 0.0833 |  |
| matharena/arxivmath-0626 | 3 | 3 | 24 | 0.1710 | 0.0692 | 0.0817 | 0.0235 | 0.1018 | 0.0072 | 0.2362 | 0.0894 | -0.0052 | 0.2237 | 0.1499 | 0.0833 |  |
| matharena/arxivmath-0626 | 5 | 5 | 24 | 0.1288 | 0.0229 | 0.0360 | 0.0017 | 0.1058 | 0.0231 | 0.2152 | 0.0927 | 0.0100 | 0.2021 | 0.0920 | 0.0833 |  |
| matharena/arxivmath-0626 | 10 | 10 | 24 | 0.0883 | 0.0024 | 0.0095 | 0.0000 | 0.0859 | -0.0008 | 0.2101 | 0.0788 | -0.0079 | 0.2030 | 0.0408 | 0.0833 |  |
| matharena/arxivmath-0626 | all | 16 | 24 | 0.0833 | 0.0002 | 0.0045 | 0.0000 | 0.0831 | -0.0002 | 0.2081 | 0.0789 | -0.0045 | 0.2039 | 0.0219 | 0.0833 | 2.0000 |
| matharena/hmmt_feb_2026 | 2 | 2 | 17 | 0.0451 | 0.0330 | 0.0323 | 0.0102 | 0.0121 | -0.0315 | 0.0759 | 0.0128 | -0.0308 | 0.0766 | 0.0264 | 0.0000 |  |
| matharena/hmmt_feb_2026 | 3 | 3 | 17 | 0.0232 | 0.0121 | 0.0129 | 0.0008 | 0.0111 | -0.0121 | 0.0497 | 0.0104 | -0.0129 | 0.0489 | 0.0097 | 0.0000 |  |
| matharena/hmmt_feb_2026 | 5 | 5 | 17 | 0.0112 | 0.0025 | 0.0043 | 0.0000 | 0.0087 | -0.0025 | 0.0311 | 0.0069 | -0.0043 | 0.0292 | 0.0022 | 0.0000 |  |
| matharena/hmmt_feb_2026 | 10 | 10 | 17 | 0.0006 | 0.0000 | 0.0000 | 0.0000 | 0.0006 | -0.0000 | 0.0018 | 0.0006 | -0.0000 | 0.0018 | 0.0000 | 0.0000 |  |
| matharena/hmmt_feb_2026 | all | 16 | 17 | 0.0000 | 0.0000 | 0.0000 | 0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | -0.0000 | 0.0000 | 0.0000 | 0.0000 |
