# Phase 3A: pruning agent networks by information per dollar, on cached calls

Written by `python -m analysis.pruning_phase3a` ($0, no API). Exploratory: nothing here is a confirmatory test, and with 80 items one item is 1.25 points. Definitions are in the script's docstring and in `autoagentnet/pruning/` (replay.py, criteria.py, search.py). Folds: two halves of the 80 items, balanced within each BBEH task (seed 0); intervals resample items (2,000 draws).

## Summary

**Staged grid.** The 27 Haiku designs run from 45.0% (k1-1-1-1, $0.0027 per item) to 62.5% (k6-6-6-1, $0.0115); an extra Haiku call adds +0.92 points (+0.41 to +1.47), per stage propose +1.5, critique +0.7, refine +0.7 points per call, small and alike within noise. The best design is 8.8 points below one Sonnet call at 0.80x its cost. Picks made on one half and scored on the other have mean regret 2.8 (S1 sensitivity), 3.1 (exhaustive on the search half) and 3.4 (NetAdapt) points: within about two items of each other. **Flat panel.** Sonnet alone scores 71.2% at $0.0144; the Haiku 5-call vote 56.2% at 0.25x; the full panel with Kevin's aggregator 66.2% and with the weighted vote 65.0%, both at 1.25x. The best static sub-network (haiku:1+haiku:4+sonnet:0) scores 75.0% (+3.7 points against Sonnet) at 1.10x its cost, but it is an oracle pick among 63, made after seeing the held-out halves; among the 11 call-count vectors (the first k calls of each source) the best is haiku=1 sonnet=1 at 72.5% and 1.05x. Every static network that includes Sonnet costs at least as much as Sonnet, so static pruning cannot buy Sonnet's accuracy for less. Policies that call Sonnet only when Haiku is unsure come close for less, but not every one: the Haiku-only cascade of cached finding 8 (escalate when fewer than 3 of 5 Haiku calls agree; not the plan's H7, which mixes 3 Haiku and 3 Luna calls and needs 4 of 6, and already scored on items 60-99 in finding 8, so not a fresh test) scores 71.2% at 0.57x Sonnet's cost; the dynamic policy with the cheap-first order and a refitted confidence stop (tau chosen on the search half, 0.6 / 0.6) 65.0% at 0.69x (minus Sonnet -6.2 (-17.5 to +5.0) points); the gain-per-dollar order, Phase 3B's other dynamic candidate, only 56.2% at 0.54x (minus Sonnet -15.0 (-23.8 to -7.5) points). That order degenerates on this panel: with one call the refitted confidence is the same for every answered item, so the policy stops every item after its first call or none, and on one half no later call had a positive in-sample gain, so it stopped after one Haiku call. Pruning paths' mean regret against the exhaustive frontier (held-out half) ranges from 2.5 points (S1 sensitivity (per-source curves, threshold)) to 9.0 (C7a one-shot); S1 2.5, NetAdapt 5.2, C6 leave-one-out (iterative) 7.3. With 6 calls, 5 of them exchangeable, and 40-item halves, these differences are one or two items. Over the 63 sub-networks, Kevin's aggregator (ridge refit) scores 62.2% on average, the same whichever source is listed first; the plain vote, whose ties go to the call listed first, scores 57.2% with Haiku listed first and 62.5% with Sonnet first (ties are frequent in small sub-networks: a Haiku + Sonnet pair splits 1-1); the weighted vote 59.1%. AMC's proxy (the vote without refit) ranks the sub-networks like the refitted score: Spearman +0.67 (+0.46 to +0.79) against Kevin's aggregator, +0.45 (+0.11 to +0.58) against the weighted vote. The label-free criteria rank the calls against the label-based ones: C5 (reconstruction) correlates -0.8 on average with C1-C3b and C6 over the six calls (reconstructing the panel's vote rewards the majority source), so it would prune Sonnet first. **What Phase 1 must measure:** the Haiku-Luna error correlation (the cross-vendor latent r). On this panel the only call that carries new information is the expensive one (Haiku-Sonnet phi 0.08 against Haiku-Haiku 0.44), so pruning can only trade it away; a cheap call from another vendor whose errors are as independent as Sonnet's would make a cheap network that pruning could keep.

## (a) The staged grid: 27 Haiku designs, whole grid points only

Each design (propose-critique-refine keep levels, then one aggregator) was run once per item; a pruned stage changes what later stages read, so nothing between grid points can be replayed. Only the 27 points are compared.

| design | calls | accuracy | acc_lo | acc_hi | dollars | seconds | regret |
|---|---|---|---|---|---|---|---|
| k1-1-1-1 | 4 | 0.4500 | 0.3375 | 0.5625 | 0.0027 | 17.2825 | 0.0000 |
| k1-3-1-1 | 6 | 0.4875 | 0.3750 | 0.6000 | 0.0035 | 21.3592 | 0.0000 |
| k1-1-3-1 | 6 | 0.5000 | 0.3875 | 0.6125 | 0.0037 | 21.7073 | 0.0000 |
| k3-1-1-1 | 6 | 0.4875 | 0.3750 | 0.6000 | 0.0043 | 23.8596 | 0.0125 |
| k1-3-3-1 | 8 | 0.5125 | 0.4000 | 0.6250 | 0.0045 | 25.3598 | 0.0000 |
| k1-6-1-1 | 9 | 0.4750 | 0.3625 | 0.5750 | 0.0049 | 22.0831 | 0.0375 |
| k3-1-3-1 | 8 | 0.5625 | 0.4500 | 0.6750 | 0.0052 | 27.7256 | 0.0000 |
| k3-3-1-1 | 8 | 0.5875 | 0.4750 | 0.7000 | 0.0052 | 27.8741 | 0.0000 |
| k1-1-6-1 | 9 | 0.5625 | 0.4500 | 0.6750 | 0.0054 | 22.5690 | 0.0250 |
| k1-6-3-1 | 11 | 0.5375 | 0.4250 | 0.6378 | 0.0059 | 25.7929 | 0.0500 |
| k3-3-3-1 | 10 | 0.5500 | 0.4375 | 0.6625 | 0.0060 | 31.2576 | 0.0375 |
| k1-3-6-1 | 11 | 0.4625 | 0.3500 | 0.5750 | 0.0061 | 25.7138 | 0.1250 |
| k6-1-1-1 | 9 | 0.5625 | 0.4500 | 0.6750 | 0.0066 | 24.8623 | 0.0250 |
| k3-6-1-1 | 11 | 0.5625 | 0.4500 | 0.6625 | 0.0067 | 28.3075 | 0.0250 |
| k3-1-6-1 | 11 | 0.6000 | 0.4875 | 0.7125 | 0.0067 | 28.2821 | 0.0000 |
| k3-3-6-1 | 13 | 0.6000 | 0.4875 | 0.7125 | 0.0074 | 31.5502 | 0.0000 |
| k1-6-6-1 | 14 | 0.5000 | 0.3875 | 0.6125 | 0.0075 | 26.0412 | 0.1000 |
| k6-1-3-1 | 11 | 0.5625 | 0.4500 | 0.6750 | 0.0075 | 28.6137 | 0.0375 |
| k3-6-3-1 | 13 | 0.6125 | 0.5000 | 0.7250 | 0.0076 | 31.6567 | 0.0000 |
| k6-3-1-1 | 11 | 0.5375 | 0.4250 | 0.6500 | 0.0076 | 28.5618 | 0.0750 |
| k6-3-3-1 | 13 | 0.5625 | 0.4500 | 0.6750 | 0.0085 | 32.2358 | 0.0500 |
| k3-6-6-1 | 16 | 0.6125 | 0.5000 | 0.7250 | 0.0090 | 31.8734 | 0.0000 |
| k6-1-6-1 | 14 | 0.5250 | 0.4125 | 0.6375 | 0.0090 | 29.3141 | 0.0875 |
| k6-6-1-1 | 14 | 0.6000 | 0.4875 | 0.7125 | 0.0092 | 29.0267 | 0.0125 |
| k6-3-6-1 | 16 | 0.5875 | 0.4750 | 0.7000 | 0.0098 | 32.2950 | 0.0250 |
| k6-6-3-1 | 16 | 0.6000 | 0.4875 | 0.7125 | 0.0101 | 32.2477 | 0.0125 |
| k6-6-6-1 | 19 | 0.6250 | 0.5250 | 0.7375 | 0.0115 | 32.4655 | 0.0000 |

Regret here is in-sample (all 80): the frontier's accuracy at the design's cost or less minus its own.

### Stage sensitivity (one stage at a time, the others at 6)

| stage | level | design | accuracy | dollars | d_accuracy | d_dollars | diff_ci | points_per_extra_call |
|---|---|---|---|---|---|---|---|---|
| propose | 3 | k3-6-6-1 | 0.6125 | 0.0090 | -0.0125 | -0.0025 | -1.2 (-10.0 to +7.5) | 0.4167 |
| propose | 1 | k1-6-6-1 | 0.5000 | 0.0075 | -0.1250 | -0.0040 | -12.5 (-23.8 to -1.2) | 2.5000 |
| critique | 3 | k6-3-6-1 | 0.5875 | 0.0098 | -0.0375 | -0.0016 | -3.8 (-10.0 to +2.5) | 1.2500 |
| critique | 1 | k6-1-6-1 | 0.5250 | 0.0090 | -0.1000 | -0.0024 | -10.0 (-17.5 to -3.8) | 2.0000 |
| refine | 3 | k6-6-3-1 | 0.6000 | 0.0101 | -0.0250 | -0.0014 | -2.5 (-7.5 to +2.5) | 0.8333 |
| refine | 1 | k6-6-1-1 | 0.6000 | 0.0092 | -0.0250 | -0.0023 | -2.5 (-7.5 to +2.5) | 0.5000 |

Main effect per extra call of each stage (level 6 minus level 1, averaged over the other two stages' nine settings, per item, divided by the 5 extra calls; points, 95% CI):

| stage | points per extra call | dollars per extra call |
|---|---|---|
| propose | +1.5 (+0.0 to +2.9) | 0.00079 |
| critique | +0.7 (-0.0 to +1.4) | 0.00047 |
| refine | +0.7 (+0.2 to +1.2) | 0.00049 |

Pooled over all 27 designs, a least-squares line of accuracy on calls per item has slope +0.92 points per extra call (+0.41 to +1.47).

**The prior "stage sensitivity flat (~0.07 independent call per extra Haiku call)".** The designs' outputs are strongly correlated (mean pairwise phi of correctness 0.65, 351 pairs). Read through n_eff(m) = m / (1 + (m - 1) rho) with rho = 0.65, going from 4 calls (1-1-1) to 19 (6-6-6) moves n_eff from 1.36 to 1.50: 0.009 independent-call equivalents per extra call (a model-based translation: the calls inside a design are not exchangeable repeats). Measured directly, accuracy rises +0.92 points per extra call (+0.41 to +1.47), and the three stages' per-call effects are alike within noise, so "flat" holds in the sense of small, similar per-call gains: an extra staged call is worth about what an extra repeat vote is worth (the 5-call vote gains +3.75 points over one call, +0.94 per extra call). In independent-call equivalents the two translations disagree: via the repeat-vote yardstick (4 extra votes buy n_eff 1.82 - 1 = 0.82 independent calls at Haiku rho 0.44, i.e. 0.217 independent calls per point), an extra staged call is worth 0.20 independent calls, a point estimate only: the yardstick's vote gain is itself uncertain (+3.7 (-1.8 to +9.2) points), and its interval reaches 0, where the translation has no upper bound; via the design-correlation formula, 0.009. The prior's 0.07 lies between them; these data do not pin the number down, and only the points-per-call reading is a measurement. The brief's corollary, that NetAdapt removes most of the team: its cheapest design within one item of 6-6-6 (all 80 items) is k3-6-3-1 (13 of 19 calls, 66% of the dollars), so it removes about 32% of the calls, not most; its next step costs 5.0 points (k3-6-1-1).

### NetAdapt over stage levels ($0.0005 per item per step; all 80 items)

| step | design | moved | accuracy | dollars | seconds |
|---|---|---|---|---|---|
| 0 | k6-6-6-1 |  | 0.6250 | 0.0115 | 32.4655 |
| 1 | k3-6-6-1 | propose | 0.6125 | 0.0090 | 31.8734 |
| 2 | k3-6-3-1 | refine | 0.6125 | 0.0076 | 31.6567 |
| 3 | k3-6-1-1 | refine | 0.5625 | 0.0067 | 28.3075 |
| 4 | k3-3-1-1 | critique | 0.5875 | 0.0052 | 27.8741 |
| 5 | k1-3-1-1 | propose | 0.4875 | 0.0035 | 21.3592 |
| 6 | k1-1-1-1 | critique | 0.4500 | 0.0027 | 17.2825 |

With seconds (the critical path) as the resource, 1 s per step:

| step | design | moved | accuracy | dollars | seconds |
|---|---|---|---|---|---|
| 0 | k6-6-6-1 |  | 0.6250 | 0.0115 | 32.4655 |
| 1 | k6-6-1-1 | refine | 0.6000 | 0.0092 | 29.0267 |
| 2 | k6-1-1-1 | critique | 0.5625 | 0.0066 | 24.8623 |
| 3 | k3-1-1-1 | propose | 0.4875 | 0.0043 | 23.8596 |
| 4 | k1-1-1-1 | propose | 0.4500 | 0.0027 | 17.2825 |

Rounds do not vary on this grid (every design runs all four stages), so the round-based NetAdapt the plan names reduces to the dollar one; the critical path in seconds is the latency resource that does vary.

### Picks under a budget: search half -> held-out half

Each method picks a design using the search half only; regret is the held-out frontier's accuracy at the pick's held-out cost or less minus the pick's held-out accuracy, averaged over both directions and the budgets $0.004 to $0.0115 per item.

| method | mean_regret | max_regret | picks |
|---|---|---|---|
| S1 sensitivity | 0.0281 | 0.1000 | 16 |
| exhaustive (search half) | 0.0312 | 0.0750 | 16 |
| NetAdapt | 0.0344 | 0.0750 | 16 |

## (b) The flat panel: 5 Haiku + 1 Sonnet, every sub-network replayed

### Reference networks (all 80 items; refit and dynamic rows cross-fitted)

| network | accuracy % (95% CI) | $ per item | minus Sonnet, points | cost / Sonnet |
|---|---|---|---|---|
| Sonnet (1 call) | 71.2 (61.3-81.2) | 0.0144 | - | 1.0000 |
| Haiku, 1 call (mean of 5) | 52.5 (44.5-60.7) | 0.0007 | -18.8 (-30.5 to -6.8) | 0.0497 |
| Haiku 5-call vote | 56.2 (46.2-67.5) | 0.0036 | -15.0 (-28.7 to -1.2) | 0.2485 |
| dense vote (6 calls) | 63.7 (52.5-73.8) | 0.0179 | -7.5 (-20.0 to +5.0) | 1.2485 |
| dense refit (6 calls, Kevin's aggregator) | 66.2 (56.2-76.2) | 0.0179 | -5.0 (-16.2 to +6.2) | 1.2485 |
| dense weighted vote (6 calls) | 65.0 (55.0-75.0) | 0.0179 | -6.2 (-13.8 to +0.0) | 1.2485 |
| Haiku cascade, escalate if < 3 of 5 agree | 71.2 (61.3-81.2) | 0.0081 | +0.0 (-10.0 to +11.2) | 0.5667 |
| Haiku cascade, escalate if < 4 of 5 agree | 73.8 (63.7-83.8) | 0.0111 | +2.5 (-5.0 to +11.2) | 0.7731 |
| Haiku cascade, escalate if < 5 of 5 agree | 75.0 (65.0-83.8) | 0.0141 | +3.8 (-1.2 to +10.0) | 0.9842 |
| dynamic, gain per $ (tau picked on the search half: 0.4 / 0.6) | 56.2 (45.0-66.2) | 0.0078 | -15.0 (-23.8 to -7.5) | 0.5419 |
| dynamic, Haiku x5 then Sonnet (tau picked on the search half: 0.6 / 0.6) | 65.0 (55.0-75.0) | 0.0099 | -6.2 (-17.5 to +5.0) | 0.6896 |

### Criteria on the full panel (all 80, descriptive)

Higher = keep. The five Haiku calls are exchangeable repeats, so differences among them are noise; the source-level table is the informative one.

| group | C1 | C2 | C3 | C3b | C4 | C5 | C6 | C7a | C7b | agreement | dollars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku | 0.337 | 0.281 | 7.852 | 1.755 | 0.375 | 0.853 | 0.011 | 445.420 | 19.858 | 0.695 | 0.004 |
| sonnet | 0.781 | 0.853 | 12.822 | 6.357 | 0.100 | 0.108 | 0.085 | 51.486 | 11.364 | 0.625 | 0.014 |

| unit | C1 | C2 | C3 | C3b | C4 | C5 | C6 | C7a | C7b | agreement | dollars |
|---|---|---|---|---|---|---|---|---|---|---|---|
| haiku:0 | 0.142 | 0.174 | 0.582 | 0.189 | 0.138 | 0.853 | -0.044 | 103.976 | 2.688 | 0.787 | 0.001 |
| haiku:1 | 0.543 | 0.530 | 6.038 | 2.674 | 0.138 | 0.728 | 0.008 | 239.186 | 46.414 | 0.662 | 0.001 |
| haiku:2 | 0.202 | 0.281 | 0.887 | 0.362 | 0.062 | 0.728 | -0.015 | 166.760 | 9.503 | 0.650 | 0.001 |
| haiku:3 | 0.131 | 0.108 | 0.493 | 0.160 | 0.113 | 0.853 | -0.007 | 46.271 | 0.015 | 0.700 | 0.001 |
| haiku:4 | 0.299 | 0.329 | 2.311 | 0.897 | 0.062 | 0.853 | -0.024 | 17.940 | 9.978 | 0.675 | 0.001 |
| sonnet:0 | 0.767 | 0.853 | 11.533 | 5.708 | 0.100 | 0.621 | 0.085 | 51.486 | 11.364 | 0.625 | 0.014 |

### Pruning paths against the exhaustive frontier (refit weights, held-out half, both directions)

| method | mean regret (points) | max regret (points) | mean regret vs count vectors | first removed (fold 0 / fold 1) |
|---|---|---|---|---|
| S1 sensitivity (per-source curves, threshold) | 2.50 | 7.50 | 1.88 | - / - |
| S2 NetAdapt ($0.0005 steps) | 5.21 | 15.00 | 5.00 | haiku x1 / haiku x1 |
| C6 one-shot | 6.87 | 15.00 | 2.92 | haiku:3 / haiku:0 |
| C2 one-shot | 7.29 | 30.00 | 5.62 | haiku:3 / haiku:3 |
| C2 iterative | 7.29 | 30.00 | 5.62 | haiku:3 / haiku:3 |
| C6 iterative | 7.29 | 15.00 | 4.58 | haiku:3 / haiku:0 |
| C5 iterative | 7.71 | 15.00 | -inf | sonnet:0 / sonnet:0 |
| C7b one-shot | 7.71 | 20.00 | -inf | haiku:3 / haiku:3 |
| C7b iterative | 7.71 | 20.00 | -inf | haiku:3 / haiku:3 |
| C1 iterative | 8.12 | 30.00 | 6.46 | haiku:3 / haiku:0 |
| C3 iterative | 8.12 | 30.00 | 6.46 | haiku:3 / haiku:0 |
| C3b iterative | 8.12 | 30.00 | 6.46 | haiku:3 / haiku:0 |
| C3 one-shot | 8.33 | 30.00 | 6.67 | haiku:3 / haiku:0 |
| C4 one-shot | 8.33 | 15.00 | -inf | haiku:4 / haiku:1 |
| C4 iterative | 8.33 | 15.00 | 3.96 | haiku:4 / haiku:1 |
| C5 one-shot | 8.54 | 15.00 | -inf | sonnet:0 / sonnet:0 |
| C7a iterative | 8.75 | 15.00 | -inf | haiku:4 / haiku:1 |
| C1 one-shot | 8.96 | 30.00 | 7.29 | haiku:3 / haiku:0 |
| C3b one-shot | 8.96 | 30.00 | 7.29 | haiku:3 / haiku:0 |
| C7a one-shot | 8.96 | 15.00 | -inf | haiku:4 / haiku:1 |

### Refit options over the 63 sub-networks (cross-fitted accuracy)

| refit | mean_accuracy | best |
|---|---|---|
| plain | 0.6222 | 0.7500 |
| ridge | 0.6222 | 0.7500 |
| restrict | 0.6133 | 0.7500 |
| weights | 0.5907 | 0.7250 |
| none | 0.5722 | 0.7125 |

### S2 NetAdapt, cross-fitted per step (descriptive)

| step | kept (fold 0 / fold 1) | search_accuracy | cross_fitted_accuracy | dollars |
|---|---|---|---|---|
| 0 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 / haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 | 0.6625 | 0.6625 | 0.0179 |
| 1 | haiku:0+haiku:1+haiku:2+haiku:3+sonnet:0 / haiku:0+haiku:1+haiku:2+haiku:3+sonnet:0 | 0.6625 | 0.6625 | 0.0173 |
| 2 | haiku:0+haiku:1+haiku:2+sonnet:0 / haiku:0+haiku:1+haiku:2+sonnet:0 | 0.7000 | 0.7000 | 0.0166 |
| 3 | haiku:0+haiku:1+sonnet:0 / haiku:0+haiku:1+sonnet:0 | 0.7250 | 0.7250 | 0.0159 |
| 4 | haiku:0+sonnet:0 / haiku:0+sonnet:0 | 0.7250 | 0.7250 | 0.0151 |
| 5 | sonnet:0 / sonnet:0 | 0.7125 | 0.7125 | 0.0144 |

Rows pool the two halves' networks at the same step index; here the two halves' networks agree at every step, but they need not, which is why the Phase 3B rule matches the halves by dollar budget instead (audit 49, analysis/pruning_select.py). Read by step index, with Sonnet's 71.2% minus 1 point as the floor: step 5 qualifies: sonnet:0 / sonnet:0, cross-fitted accuracy 71.2% at $0.0144 per item. Sonnet scores 62.5% on fold 0's search half and 80.0% on fold 1's: with 40 items a half, that gap alone is several items.

### S3: CEM controller (reward = plain-vote accuracy on the search half if dollars fit the budget, else -1)

| budget | picked (fold 0 / fold 1) | held-out accuracy | dollars | distinct networks evaluated |
|---|---|---|---|---|
| 0.0036 | haiku:0+haiku:1+haiku:2 / haiku:0+haiku:1+haiku:2 | 0.5750 | 0.0022 | 5/6 |
| 0.0075 | haiku:0+haiku:1+haiku:2 / haiku:0+haiku:1+haiku:2 | 0.5750 | 0.0022 | 6/6 |
| 0.0150 | sonnet:0 / sonnet:0 | 0.7125 | 0.0144 | 8/7 |

AMC's proxy test over the 63 sub-networks: Spearman correlation between plain-vote accuracy (no refit) and cross-fitted refit accuracy +0.67 (+0.46 to +0.79); bootstrap share at or below 0: 0.000; same best network: no.

### Static vs dynamic

| policy | tau | accuracy | dollars | tokens | rounds | seconds | order (fold 0) |
|---|---|---|---|---|---|---|---|
| gain per $ order | 0.4000 | 0.4875 | 0.0007 | 2496.0125 | 1.0000 | 5.9304 | haiku:1 |
| gain per $ order | 0.5000 | 0.4875 | 0.0007 | 2496.0125 | 1.0000 | 5.9304 | haiku:1 |
| gain per $ order | 0.6000 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.6500 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.7000 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.7500 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.8000 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.8500 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.9000 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 0.9500 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| gain per $ order | 1.0100 | 0.5625 | 0.0078 | 3686.1750 | 1.5000 | 10.4122 | haiku:1 |
| fixed order: Haiku x5 then Sonnet | 0.4000 | 0.5250 | 0.0008 | 2492.8625 | 1.0000 | 5.8828 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.5000 | 0.5750 | 0.0032 | 5149.6375 | 2.0125 | 12.6205 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.6000 | 0.6500 | 0.0099 | 10760.9875 | 4.2500 | 27.4731 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.6500 | 0.6500 | 0.0117 | 12071.0250 | 4.7875 | 30.9477 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.7000 | 0.6625 | 0.0156 | 14183.0000 | 5.6750 | 36.5335 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.7500 | 0.6625 | 0.0179 | 14997.2875 | 6.0000 | 38.8984 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.8000 | 0.6625 | 0.0179 | 14997.2875 | 6.0000 | 38.8984 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.8500 | 0.6625 | 0.0179 | 14997.2875 | 6.0000 | 38.8984 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.9000 | 0.6625 | 0.0179 | 14997.2875 | 6.0000 | 38.8984 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 0.9500 | 0.6625 | 0.0179 | 14997.2875 | 6.0000 | 38.8984 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |
| fixed order: Haiku x5 then Sonnet | 1.0100 | 0.6625 | 0.0179 | 14997.2875 | 6.0000 | 38.8984 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 |

At equal average dollars: each policy's cross-fitted accuracy against the static frontiers' best accuracy at its dollars or less (count vectors: the first k calls of each source; any subset: the oracle over all 63).

| policy | tau | accuracy | dollars | rounds | static, count vectors | static, any subset (oracle) | dynamic minus count-vector static (points) |
|---|---|---|---|---|---|---|---|
| gain per $ order | 0.4000 | 0.4875 | 0.0007 | 1.0000 |  | 0.5375 | inf |
| gain per $ order | 0.5000 | 0.4875 | 0.0007 | 1.0000 |  | 0.5375 | inf |
| gain per $ order | 0.6000 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.6500 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.7000 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.7500 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.8000 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.8500 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.9000 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 0.9500 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| gain per $ order | 1.0100 | 0.5625 | 0.0078 | 1.5000 | 0.5750 | 0.6000 | -1.2500 |
| fixed order: Haiku x5 then Sonnet | 0.4000 | 0.5250 | 0.0008 | 1.0000 | 0.5250 | 0.5750 | 0.0000 |
| fixed order: Haiku x5 then Sonnet | 0.5000 | 0.5750 | 0.0032 | 2.0125 | 0.5750 | 0.6000 | 0.0000 |
| fixed order: Haiku x5 then Sonnet | 0.6000 | 0.6500 | 0.0099 | 4.2500 | 0.5750 | 0.6000 | 7.5000 |
| fixed order: Haiku x5 then Sonnet | 0.6500 | 0.6500 | 0.0117 | 4.7875 | 0.5750 | 0.6000 | 7.5000 |
| fixed order: Haiku x5 then Sonnet | 0.7000 | 0.6625 | 0.0156 | 5.6750 | 0.7250 | 0.7250 | -6.2500 |
| fixed order: Haiku x5 then Sonnet | 0.7500 | 0.6625 | 0.0179 | 6.0000 | 0.7250 | 0.7500 | -6.2500 |
| fixed order: Haiku x5 then Sonnet | 0.8000 | 0.6625 | 0.0179 | 6.0000 | 0.7250 | 0.7500 | -6.2500 |
| fixed order: Haiku x5 then Sonnet | 0.8500 | 0.6625 | 0.0179 | 6.0000 | 0.7250 | 0.7500 | -6.2500 |
| fixed order: Haiku x5 then Sonnet | 0.9000 | 0.6625 | 0.0179 | 6.0000 | 0.7250 | 0.7500 | -6.2500 |
| fixed order: Haiku x5 then Sonnet | 0.9500 | 0.6625 | 0.0179 | 6.0000 | 0.7250 | 0.7500 | -6.2500 |
| fixed order: Haiku x5 then Sonnet | 1.0100 | 0.6625 | 0.0179 | 6.0000 | 0.7250 | 0.7500 | -6.2500 |

Call-count vectors (S4 as the brief defines it), cross-fitted, with tokens per item:

| counts | score | dollars | tokens | seconds |
|---|---|---|---|---|
| haiku=1 sonnet=0 | 0.5250 | 0.0008 | 2492.8625 | 5.8828 |
| haiku=2 sonnet=0 | 0.5250 | 0.0015 | 4973.2625 | 6.3758 |
| haiku=3 sonnet=0 | 0.5750 | 0.0022 | 7492.1375 | 6.8074 |
| haiku=4 sonnet=0 | 0.5625 | 0.0029 | 10047.8500 | 7.0558 |
| haiku=5 sonnet=0 | 0.5625 | 0.0036 | 12590.9000 | 7.2699 |
| haiku=0 sonnet=1 | 0.7125 | 0.0144 | 2406.3875 | 9.1104 |
| haiku=1 sonnet=1 | 0.7250 | 0.0151 | 4899.2500 | 9.1941 |
| haiku=2 sonnet=1 | 0.7250 | 0.0159 | 7379.6500 | 9.2766 |
| haiku=3 sonnet=1 | 0.7000 | 0.0166 | 9898.5250 | 9.4127 |
| haiku=4 sonnet=1 | 0.6625 | 0.0173 | 12454.2375 | 9.4927 |
| haiku=5 sonnet=1 | 0.6625 | 0.0179 | 14997.2875 | 9.5756 |

### Baselines at matched cost

| matched to | target $ | random networks | distinct | mean accuracy | 90th percentile |
|---|---|---|---|---|---|
| 5-call vote cost | 0.0036 | 200 | 6 | 0.5604 | 0.5625 |
| Sonnet cost | 0.0144 | 200 | 32 | 0.6811 | 0.7250 |
| dynamic pick (fixed order) cost | 0.0099 | 0 | 0 |  |  |

No sub-network costs within 25% of the dynamic pick's dollars: every static network either leaves Sonnet out (at most $0.0036) or pays for it in full (at least $0.0144). That gap is what a dynamic policy fills.

| baseline | budget | picked (fold 0) | held-out accuracy | dollars |
|---|---|---|---|---|
| cheapest-first | 0.0036 | haiku:1+haiku:2+haiku:3+haiku:4 | 0.5500 | 0.0032 |
| top-k accurate | 0.0036 | haiku:0+haiku:1+haiku:3+haiku:4 | 0.5625 | 0.0032 |
| cheapest-first | 0.0075 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4 | 0.5625 | 0.0036 |
| top-k accurate | 0.0075 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4 | 0.5625 | 0.0036 |
| cheapest-first | 0.0150 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4 | 0.5625 | 0.0036 |
| top-k accurate | 0.0150 | haiku:1+sonnet:0 | 0.5625 | 0.0147 |
| cheapest-first | 0.0181 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 | 0.6625 | 0.0179 |
| top-k accurate | 0.0181 | haiku:0+haiku:1+haiku:2+haiku:3+haiku:4+sonnet:0 | 0.6625 | 0.0179 |

## Figures

- `reports/v3/pruning/grid_frontier.pdf`
- `reports/v3/pruning/grid_frontier.png`
- `reports/v3/pruning/grid_sensitivity.pdf`
- `reports/v3/pruning/grid_sensitivity.png`
- `reports/v3/pruning/flat_frontier.pdf`
- `reports/v3/pruning/flat_frontier.png`
- `reports/v3/pruning/flat_regret.pdf`
- `reports/v3/pruning/flat_regret.png`
- `reports/v3/pruning/sensitivity_curves.pdf`
- `reports/v3/pruning/sensitivity_curves.png`
- `reports/v3/pruning/flat_methods_logx.pdf`
- `reports/v3/pruning/flat_methods_logx.png`
- `reports/v3/pruning/criteria_rank_agreement.pdf`
- `reports/v3/pruning/criteria_rank_agreement.png`
- `reports/v3/pruning/one_shot_vs_iterative.pdf`
- `reports/v3/pruning/one_shot_vs_iterative.png`
- `reports/v3/pruning/dollar_vs_latency.pdf`
- `reports/v3/pruning/dollar_vs_latency.png`
