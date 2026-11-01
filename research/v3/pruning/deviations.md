# Phase 3: where the code departs from Kevin's brief, and why

The brief is research/v3/pruning/kevin_brief.md. Each item says what the brief asks, what the code does, and
why; Kevin can overrule any of them before the G2a read (the Phase 3B rule is code, so a change is one commit).

1. **3B search set: 200 items, not 300.** The brief: Phase 1's sealed data (BBEH 300, ForecastBench 300) plus
   Phase 2's persona calls. The persona calls exist only on the 200 Phase 2 items, and a replayed network needs
   every one of its calls on every item, so `analysis/pruning_select.py` searches the 200 items where all 18
   lockbox calls exist. The alternative (300 items, persona sources only on 200) would let networks with and
   without personas be scored on different items.
2. **Plurality ties.** The brief does not say how a tie between answer classes is broken. The code gives a tie to
   the class the fitted aggregator rates most likely right; only classes with identical features (two calls of
   one source splitting) fall back to the class met first. The plain vote without a model uses the second rule
   only, as Phase 1 does, so the plain vote depends on the order calls are listed in (on the cached panel its
   average over the 63 sub-networks is 57.2% with Haiku listed first and 62.5% with Sonnet first).
3. **Fitting the aggregator.** It is fitted on every tied top class of each item, each weighted 1 / the number
   tied, so neither its coefficients nor its answers depend on call order (audit 50 found that an earlier version,
   fitted on first-met ties, gave ties to whichever source was listed later; fixed, with a test).
4. **C5 target.** The brief: reproduce the dense network's confidence. The dense aggregator's confidence is fitted
   on labels, so C5 reproduces the dense network's vote shares instead, which keeps it label-free as the brief
   requires.
5. **C1-C3b on ForecastBench.** Kevin's forecast aggregator has one number (the extremizing factor), so there is no
   coefficient per source; on forecasts C1-C3b use the weighted-vote coefficients (one weight per call on its
   log-odds). On BBEH they use Kevin's aggregator.
6. **Rounds as NetAdapt's resource.** A static flat network takes one round, and every staged design runs all
   four stages, so rounds never change on the networks Phase 3A can replay. NetAdapt is run with dollars and
   with seconds (the critical path) instead; rounds are reported for the dynamic policies.
7. **S3.** CEM only; DDPG is not built (with a handful of sources CEM searches the same space). The state features
   the brief lists (price, accuracy, correlation, budget used and left, previous action) matter only to a
   learned policy, so the CEM controller does not use them; the budget is enforced by clipping, as the brief says.
8. **Static rule details (after audit 49).** Networks are matched across the two halves by dollar budget, not by
   step index; when no budget qualifies there is no static network and P1-P2 are void (no fallback); when the
   rule picks Sonnet alone, P1 is void. An optional cost bound (`COST_BOUND`, off by default) is Kevin's choice.
9. **"Run every criterion and search method" in 3B.** The committed rule uses NetAdapt and the dynamic
   candidates only. The other criteria and searches are exploratory there; the library runs them, but a 3B
   script for the 18-call panel is not written yet (analysis/pruning_phase3a.py's flat-panel part is the template).
10. **Intervals in 3A.** Accuracies and paired differences carry item-bootstrap intervals; search outputs (path
    regrets, criteria scores, frontiers) do not, since an interval for them would re-run every search per draw.
11. **Lockbox exploratory analyses** (criteria comparison, S1-S3 regret, one-shot vs iterative, AMC's proxy,
    random pruning, dollar vs latency, ForecastBench) are not yet scripted in analysis/pruning_lockbox.py, which
    runs P1-P3 and the ForecastBench differences. They are free and can be written before the lockbox read.
12. **Added, not in the brief.** A weighted vote (one weight per call) is carried as a comparison aggregator. In
    Phase 3A, Kevin's aggregator is ahead of it on the cached panel (66.2% against 65.0% for all six calls; 62.2%
    against 59.1% on average over the 63 sub-networks). On a simulated cross-vendor panel (analysis/evidence_power.py's
    model: Haiku x5, Luna x5, Sonnet, Sol; 300 items, two folds) the weighted vote is far ahead for all 12 calls,
    79% against 68%, because it lets the two mid-size calls outvote the cheap majority, which a plurality never
    does. Phase 1's real panel will say which holds; switching the 3B rule's aggregator is one line
    (`AGGREGATOR` in analysis/pruning_select.py: "ridge" is Kevin's, "weights" the weighted vote) and Kevin's call.
13. **Baselines in 3A.** Sol and Opus have no calls on the cached flat panel, so 3A's baselines are Sonnet, the
    5-call vote, the Haiku cascade, the dense networks, random pruning, cheapest-first and top-k. On the lockbox,
    Sol is in the panel; Opus is not.
14. **S4 regret.** The brief: regret against the call-count-vector frontier. Phase 3A reports both: against the 11
    count vectors (the brief's S4) and against all 63 subsets of calls (an oracle that may also pick which
    exchangeable calls to keep). A criterion path at call granularity can keep, say, haiku:1 and haiku:4, which is
    no count vector, so its regret against the count frontier can be negative by luck.
15. **Tokens** are reported as a resource (total tokens per item, from the call logs) beside dollars, rounds and
    seconds; the searches cut dollars, as the brief's NetAdapt does.
16. **Static vs dynamic at equal dollars.** Phase 3A tabulates each dynamic policy's accuracy against the static
    frontiers' best accuracy at its dollars or less (count vectors, and any subset).
17. **N:M per-round quotas** (the brief's "vendor/tier with per-round quotas (pattern, like N:M)") are not built:
    the pattern granularity groups calls by vendor and tier, without quotas per round. With flat panels there is
    one round, so a quota per round is the same as a count per pattern.
18. **C1-C3b at call granularity** fit one agreement feature per call, while the searches refit the aggregator
    with one feature per source. At call granularity these criteria therefore score a model the searches never
    use, and their ranks among exchangeable calls of one source are noise (audit 50).
19. **The Anthropic lockbox before Oct 31** (the brief and D5) cannot run first: the selection it needs uses both
    vendors' Phase 1-2 calls, so the OpenAI Phase 1-2 runs must finish before the Anthropic lockbox half.
20. **The lockbox gate** (run the lockbox only if the frozen selection contains something cheaper than Sonnet) is a
    proposal for Kevin, not part of his plan; the e31 preregs state it as a proposal.

## Session E4 (cascades; Kevin's K2-K4)

21. **Source weights use the K-class log-odds** (K2 says "log-odds of its search accuracy"; revised after audit 52).
    K2's plain log-odds is negative below 50% accuracy, so Haiku (48% cached) and a weak Luna would have dropped to
    the floor and the weighted vote would have become a plain vote. The weight is now log((K - 1) a / (1 - a)) with
    K = 10, the symmetric Dawid-Skene weight for answers spread over K classes (K = 2 gives K2 as written). Any source
    above 10% accuracy has positive weight; the 0.05 floor is reached only below 1 / K
    (`autoagentnet/pruning/cascade.py`, K_CLASSES, W_MIN). Kevin to confirm K or choose another weight.
22. **Agreement is grader equality, not string equality.** Kevin's cached baseline (k >= 3: 67.5% accepted, 20.0%
    accepted-wrong; k >= 4: 43.8% / 10.0%; k = 5: 20.0% / 2.5%) counts two answers as agreeing when their normalized
    strings are equal. The replay library's answer classes use the BBEH grader (answers it would score the same,
    such as "(B)" and "B", are one class), which gives 72.5% / 22.5%, 52.5% / 12.5% and 28.8% / 3.8% on the same 80
    items. Both are reproduced in `tests/test_pruning_cascade.py`; the rule uses grader classes.
23. **A cascade must accept something to qualify** (not in K3's rule). A policy that accepts no item is the
    escalation model plus the first round's cost; with Sonnet as the escalation model C1 would compare Sonnet with
    itself and pass for free (audit 49's trap). If the frozen threshold certifies nothing on all search items, C1 is
    void.
24. **Search items differ by first round.** Base-prompt first rounds use the 300 Phase 1 items; the persona rounds
    exist only on the 200 Phase 2 items. Each policy is compared with Sonnet on its own items.
25. **C2's mixed-vendor first round** is the mixed round with the highest cross-fitted acceptance at alpha 0.10 (ties:
    cheaper), not necessarily the one inside the selected policy. Acceptance does not depend on the escalation model.
26. **ForecastBench spread** is the largest minus the smallest log-odds of the first round's calls; s is chosen per
    fold as the cheapest grid value (0.5-6) within +0.005 Brier of Sonnet.
27. **Learn-then-Test thresholds** run over a fixed grid (1.00, 0.95, ..., 0.05), fixed before any data, not over the
    observed share values.
28. **C1s, the policy against Sol alone, becomes the headline row** (audit 59, required item 2; logged before
    selected.json is frozen and before any e31 call is read). G2a found Sol at 97.3% on BBEH for 0.45x Sonnet's
    dollars, so C1 (against Sonnet) can pass for a policy that Sol alone dominates. The lockbox read now reports
    first C1s: the frozen policy minus Sol alone, paired accuracy with a 95% task-stratified item-bootstrap interval,
    and the policy's dollar ratio to Sol (`lockbox_tests`, exploratory, no pass/fail); on ForecastBench, the spread
    policy minus Sol in Brier beside the Sonnet row. C1, C1b, C2 and C3 are unchanged. The $0 frontier against Sol on
    the 300 Phase 1 search items (research/v3/pruning/frontier_sol.md, `python -m analysis.pruning_cascade frontier`;
    base-prompt rounds only, no Phase 2 data) finds no cascade within 2 points of Sol at 0.8x its dollars or less,
    cross-fitted or even with the threshold picked in-sample (0 of 276 settings); the cheapest within 6 points is Luna
    x3 unanimous escalating to Sol (91.0%, 0.98x Sol's dollars, in-sample).
29. **The ForecastBench cascade's reference is Sol alone, not Sonnet** (audit 60, finding 8; logged before selected.json
    exists and before any e31 call). On the 300 Phase 1 questions Sol's Brier (0.1250) matches Sonnet's (0.1255) at
    about half the dollars ($0.0022 against $0.0040 per question), so a cascade "within 0.005 of Sonnet" could still
    be beaten by Sol alone. The rule now picks the cheapest policy whose cross-fitted Brier is within 0.005 of Sol's
    (`FORECAST_REFERENCE`, `forecast_table`, `select_forecast`); the lockbox read's decision row is the frozen policy
    minus Sol alone in Brier, with Sonnet beside it; the e31_lockbox_forecast_* preregs say the same (regenerated and
    dry-run). The $0 replay (research/v3/pruning/frontier_forecast.md) would freeze Haiku x2 + Luna x2, escalating to
    Sol above a log-odds spread of 6 (2% of questions): Brier +0.0032 against Sol at 0.26x its dollars, optimistic
    because it is the best of 12 candidates on the same questions.
30. **The forecast lockbox is read three ways, with source-aware intervals** (audit 61; logged before any e31 call).
    The 200 lockbox questions are all data-series, 40 per source. [Corrected by 31: they have 12-15 resolution dates
    per source, not one, and the decision interval is H10's wider interval, not the within-source one.] The decision
    interval is the 95% bootstrap of policy minus Sol resampling questions within each source; the plain question
    bootstrap and the range when each source is left out in turn are reported beside it (`forecast_lockbox`). Readings (`reading`):
    upper end at most +0.01 at under 0.5x Sol's dollars, a candidate; lower end above 0, Sol is better; otherwise
    inconclusive. Power, from Phase 1's 150 data-series questions (per-question SD 0.044, so the standard error at 200
    is about 0.0031; normal approximation, which ignores correlation within a source): "candidate" about 0.56 if the
    true difference is Phase 1's +0.0034, 0.36 at +0.005, 0.89 at 0; "Sol is better" about 0.19 at +0.0034 and 0.89 at
    +0.01. A miss is not evidence that Sol is better. The e31_lockbox_forecast_* preregs say the same (regenerated,
    dry-run).
31. **The forecast lockbox's decision interval follows H10** (audit 62, finding 3; logged before any e31 call). Deviation
    30 rested on a wrong fact from audit 61: the 200 lockbox questions have 12-15 resolution dates per source (67 source
    x date cells), not one, and resampling questions within a source never widens the interval. The decision interval
    is now the wider of two 95% bootstraps of policy minus Sol, over questions and over source x resolution-week
    clusters (`decision_interval`, `week_cluster`), as the plan's H10 rule says for every ForecastBench interval; the
    within-source interval and the leave-one-source-out range are shown beside it. On Phase 1's 150 data-series
    questions the three intervals are -0.0038 to +0.0105 (question), -0.0026 to +0.0087 (source x week) and -0.0035
    to +0.0103 (within source), so the power figures of 30 stand. Also decided now (audit 62's direction): an
    "inconclusive" reading ends the forecast track with an honest report; it is not followed by a bigger lockbox.
    Note (audit 63, finding 4): the e31_lockbox_forecast_* question text said "40 per source, one resolution date
    each", meant per question but read by audit 61 as per source. It now says "each question at one resolution date,
    12-15 dates per source" (67 source x date cells, checked from the task file). The anth half had already run under
    the old wording; only the wording changed, not the calls, the rule or the read.
32. **The ForecastBench selection is frozen before the Phase 2 read, and the BBEH lockbox is dropped** (Kevin, Oct 22,
    in session; audit 63's finding 5). The forecast rule reads only e14_forecast_* (read at G2b) and is deterministic,
    so `select-forecast` freezes it into research/v3/pruning/selected_forecast.json now, and `lockbox forecast` reads
    the forecast lockbox once. The BBEH lockbox (e31_lockbox_bbeh_*) and e22_persona_bbeh_open are dropped, so the BBEH
    selection and C1, C1b, C1s, C2 and C3 are not run.
