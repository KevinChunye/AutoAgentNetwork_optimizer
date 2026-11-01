# Evidence per dollar: prior work (step 0.11)

Date: 2026-10-21. Written by lit-scout. Read depth is marked on every source: FULL = HTML or page body opened and numbers quoted; ABSTRACT = abstract page only; SNIPPET = search-result text only (not opened, do not cite numbers without opening). The arXiv PDFs of 2506.07962, 2603.06612 and 2607.10139 came back as unreadable compressed streams, so those were read through their arxiv.org/html versions.

## Rule from plan step 0.11, and the verdict

Rule: if a paper already reports cross-fitted (out-of-sample) calibration of mixed-vendor LLM agreement together with dollar cost, the write-up leads with Phase 2's independence-per-dollar and decision results.

**Verdict: the rule does NOT fire.** Among the papers I opened, none reports all three of (cross-fitted calibration, mixed-vendor agreement as the feature, dollar cost). Closest misses: 2607.10139 (cross-family panel incl. Claude; calls not dollars; a calibrated law with leave-one-benchmark-out check, not cross-fitted confidence), 2607.08065 (cross-vendor only as an exploratory pairwise check; no fitted calibration; no dollars), 2407.02348 (agreement cascade with price; no calibration). Search is not exhaustive (about 10 queries); a negative here is "not found", and the 2607.* papers are new enough that a v-next could add the missing piece. Re-check arXiv before submission.

## 1. Closest papers to the exact claim

| Paper | Mixed vendor | Agreement used | Calibration out-of-sample | Dollar cost |
|---|---|---|---|---|
| 2607.10139 LLMs as a Jury | yes (Qwen, DeepSeek, Claude Sonnet 4.6, Kimi) | yes, cross-model consensus | no cross-fitting; law fit "from a labeled sample"; leave-one-benchmark-out MAE 0.024 | calls only |
| 2607.08065 When LLMs Agree | exploratory only (GPT-4.1 + 3 Claude) | yes, self-consistency share | none fitted (raw ECE) | no |
| 2407.02348 Agreement-Based Cascading | not stated in what I read | yes, ensemble agreement routes | not read | price per token/request |
| 2310.12963 AutoMix | no | self-verification, not agreement | POMDP router | relative cost |
| 2603.06612 Consensus is Not Verification | 3 families | polling | reliability diagrams only | 25x samples, no $ |

What remains open for us: (i) out-of-sample logistic correction on "k of n agree" plus "second vendor agrees"; (ii) per-call dollars from real price tables with cache; (iii) the independence-per-dollar comparison of five ways to buy a second opinion (not found in any paper I opened).

## 2. Correlated LLM errors

### Correlated Errors in Large Language Models (Kim, Garg, Peng, Garg; ICML 2025)
- Link: https://arxiv.org/abs/2506.07962 (read FULL via https://arxiv.org/html/2506.07962, first 100,000 of 116,937 characters)
- What it does: measures error agreement across 350+ LLMs on two leaderboards and a resume-screening task.
- Key numbers (quoted): "models agree 60% of the time when both models err" (abstract). HELM: 71 LLMs, 14,042 multiple-choice questions; random choice among wrong answers would give about 1/3. Mean pairwise agreement 0.6 (HELM), 0.423 (HuggingFace). Same-company indicator in a regression on agreement-when-both-wrong: +0.0658 (SE 0.003) HuggingFace, +0.0216 (SE 0.005) HELM, +0.021 (SE 0.012, p = 0.092) resumes. Shared architecture +0.0759 (HuggingFace only).
- Relevance: supports (baseline). The same-company effect is small next to the 0.6 base level, so a different vendor does not buy much independence by itself. It reports no raw same-vendor vs cross-vendor average and no dollars.
- Resources: CC BY 4.0 on arXiv; leaderboard data is public.
- Open questions: agreement is for multiple-choice with about 4 options; our BBEH answers are free-form, so the chance level differs.

### Consensus is Not Verification (Denisov-Blanch et al.; arXiv 2026)
- Link: https://arxiv.org/abs/2603.06612 (read FULL via HTML)
- What it does: tests polling-style aggregation (voting, prediction-based) where no verifier exists, on Com2Sense, HLE (35 binary), BoolQ, Predict-the-Future, plus MATH/AIME as verifiable contrast. Models: Gemma-3-4B, GPT-oss-20B/120B, Qwen3-32B/235B (no Claude, no GPT-5-class).
- Key numbers (quoted): "Even on this zero-knowledge baseline, different LMs exhibit correlations as high as 0.35" (Cohen's kappa on 10,000 random-string prompts). "Model errors are highly correlated both within and across model families" (no separate within-model number given). On MATH the most common wrong answer is 65-87% of wrong responses; on 53% of MATH questions where several models erred they gave the same wrong answer. Polling tested "even at 25x the inference cost of naive sampling" with no consistent gain.
- Relevance: threatens the value of extra same-source calls (supports our rho framing); gives no calibration metric and no cost per correct answer.
- Resources: CC BY-NC-SA 4.0 (PDF metadata).
- Open questions: no Claude or OpenAI frontier models, so cross-vendor evidence is thin.

### LLMs as a Jury (Ning Liu; arXiv 2607.10139 v3)
- Link: https://arxiv.org/abs/2607.10139 (read FULL via HTML, first 100,000 of 148,892 characters; the user also named an alphaxiv copy, which I did not open)
- What it does: cross-model consensus as the selector for reasoning answers; a closed-form law predicts consensus accuracy from mean member accuracy a, mean pairwise error correlation rho, and shared-misconception rate s.
- Key numbers (quoted): mean pairwise error correlation within-model (self-consistency) 0.68; same-family 0.52; cross-family 0.47. Shared-error floor (empirical / predicted): MATH-500 0.004 / 0.006, GPQA 0.030 / 0.030, MMLU-Pro 0.143 / 0.155. Law mean absolute error 0.028 (accuracy) and 0.009 (floor). Agreement-gated cascade: "MATH-500 reaches 0.956 at 2.2 calls per problem, and AIME-2024 reaches 0.700 at 3.2 calls". Leave-one-benchmark-out MAE 0.024. Panel includes Claude Sonnet 4.6 and (ablation) Claude Opus 4.8.
- Relevance: closest prior; supports (same ordering within > same-family > cross-family) and partly threatens novelty on "cross-vendor agreement predicts accuracy and costs fewer calls". The gap from 0.52 to 0.47 is small; cross-family is not near zero. Our cached Haiku-Sonnet phi 0.08 is far lower, but their rho is an error correlation on math, ours is a correctness correlation on BBEH; do not compare numbers directly.
- Resources: CC BY 4.0. No cross-fitting and no dollars (calls only).
- Open questions: it has no persona, reasoning-effort or bigger-model arm, so our question (d) is not answered here.

### When LLMs Agree, Are They Right? (arXiv 2607.08065)
- Link: https://arxiv.org/abs/2607.08065 (read FULL via HTML)
- What it does: audits self-consistency share and cross-model agreement as confidence on GPQA Diamond and AIME. Main audit uses GPT-4.1 family at temperature 1.0, K = 50; exploratory Claude check (haiku-4.5, sonnet-4.6, opus-4.7) with K = 10 on 48 GPQA and 24 AIME items.
- Key numbers (quoted): GPQA ECE 0.41 and Brier 0.42 for gpt-4.1; Claude GPQA ECE haiku 0.34, sonnet 0.24, opus 0.35. Cross-vendor: GPT-4.1 and Claude tiers agree on the majority answer on "roughly 48-63%" of 46 shared GPQA items; shared wrong answers exceed a permutation null for haiku (p = .003) and sonnet (p = .005) but not opus (p = .07). Adaptive sampling "19.8 vs. 50" samples (about 60% fewer). "cross-family agreement does not by itself certify correctness."
- Relevance: baseline and supports H4 (naive agreement is overconfident). Confirms no fitted or cross-fitted calibration and no dollars. Tiny cross-vendor sample.
- Open questions: ECE is on the raw score; we should show the same raw number as our "before" row.

## 3. Self-consistency confidence and overconfidence

- 2607.08065 (above): overconfident, high-agreement answers wrong 48% of the time for gpt-4.1 on GPQA per the search summary (SNIPPET; the figure is in the paper I opened but I did not re-quote the sentence).
- Self-Consistency Boosts Calibration for Math Reasoning, https://arxiv.org/abs/2403.09849 (SNIPPET only): self-consistency methods generally beat p(True) and logit baselines on ECE and Brier. Not opened; open before citing.
- Opposing evidence, https://arxiv.org/abs/2603.29559 (SNIPPET only): on grading, self-reported confidence beat self-consistency (ECE 0.166 vs 0.229). Not opened.
- Relevance: the field result is mixed and task-dependent, which is why a fitted correction is needed. Our cached +14.2-point overconfidence on BBEH (plan finding 4) is consistent in sign.

## 4. Aggregating correlated forecasters and extremizing

### Combining multiple probability predictions using a simple logit model (Satopaa, Baron, Foster, Mellers, Tetlock, Ungar; Int. J. Forecasting 2014)
- Link: https://www.academia.edu/13898151 (403 on fetch; SNIPPET only from a search result: "Over 1300 experts predicted 69 geopolitical events"; the aggregator "in effect extremizes the average log-odds")
- Relevance: supports H8 (extremizing factor on mean log-odds). Open the paper itself before quoting.

### Two Reasons to Make Aggregated Probability Forecasts More Extreme (Baron, Mellers, Tetlock, Stone, Ungar; Decision Analysis 2014)
- Link: https://faculty.wharton.upenn.edu/wp-content/uploads/2015/07/2015---two-reasons-to-make-aggregated-probability-forecasts_1.pdf (unreadable PDF; SNIPPET only: it "give[s] two intuitive justifications for extremizing"; the reasons themselves were NOT read)
- Relevance: supports; the reasons are not verified here, so do not state them in the paper from this note.

### Modeling Probability Forecasts via Information Diversity (Satopaa, Pemantle, Ungar; arXiv 1406.2148)
- Link: https://arxiv.org/abs/1406.2148 (ABSTRACT)
- Key claim: optimal "extremizing an average probability forecast" depends on "the experts' information overlap" (paraphrase of summary; the quoted phrase "shifting it closer to its nearest extreme" is from the abstract).
- Relevance: supports, directly. High overlap (correlated errors) means less extremizing is optimal. This links H8's fitted factor a to our measured rho and phi, and gives a testable link: a should fall as pairwise correlation rises.

### Wisdom of the Silicon Crowd (Schoenegger, Tuminauskaite, Park, Tetlock; arXiv 2402.19379)
- Link: https://arxiv.org/abs/2402.19379 (ABSTRACT)
- Key numbers (quoted/paraphrased): 12 LLMs, 31 binary questions, 925 human forecasters; LLM crowd "not statistically different" from the human crowd; mean LLM predictions were above 50% (acquiescence); showing the median human forecast improved GPT-4 and Claude 2 by 17% to 28%.
- Relevance: baseline. Acquiescence bias means a plain mean needs a bias correction before extremizing. The abstract page does not mention extremizing or Brier scores, so I cannot say whether the paper tests extremizing.

### ForecastBench (Karger et al.; arXiv 2409.19839)
- Link: https://arxiv.org/abs/2409.19839 (read FULL via HTML, first 100,000 of 170,281 characters)
- Key numbers (quoted): superforecasters Brier 0.096 on the 200-question subset, top LLM (Claude 3.5 Sonnet) 0.122; "The top-performing LLMs all had access to" market freeze values, best model without them 0.136. Its LLM ensemble combines GPT-4o, Claude-3.5-Sonnet and Gemini-1.5-Pro with three prompts each (nine forecasts per question); aggregation by median, geometric mean and geometric mean of log odds, citing Satopaa et al. 2014. The ensemble Brier lives in Appendix E, which I did not read.
- Relevance: baseline and partial novelty threat (mixed-vendor ensemble on ForecastBench exists). It does not estimate cross-model correlation, fit extremizing, or report cost. Relevance to H9: market freeze values are given to the model, as in our prompt.
- Resources: question sets CC BY-SA 4.0 (per v3_sources.md).

### AIA Forecaster technical report (arXiv 2511.07678)
- Link: https://arxiv.org/abs/2511.07678 (read FULL via HTML, first 100,000 of 141,208 characters)
- Key numbers (quoted): "Platt scaling and a certain class of extremization techniques are mathematically equivalent"; extremizing coefficient sqrt(3) adopted "to avoid the risk of overfitting"; mean of 10 forecasts Brier 0.1140 vs 0.1182 for one random forecast (FB-7-21); Platt scaling on the arithmetic mean gave the lowest Brier of the corrections tested, 0.1076. Market ensemble: FB-Market AIA 0.075, market 0.097, ensemble 0.079; MarketLiquid AIA 0.126, market 0.111, ensemble 0.106.
- Relevance: baseline for H8 and H9. It says nothing about correlation among forecasts and reports no cost. Because Platt scaling on the mean equals extremizing, our H8 and the H6 logistic correction are the same family; report both as one slope.

### Not opened, leads only
- LLM-SoccerArena, https://arxiv.org/abs/2607.24573 (SNIPPET: 7 models, 104 matches, mean pairwise correlation of probabilities 0.943, equal-weight ensemble gain 0.0047 Brier). Useful as a low-diversity contrast; verify before citing.
- HK26 ICML 2026 Forecast workshop paper, https://mcml.ai/publications/hk26/ (SNIPPET: logit-mean followed by extremization gives strong correlations with Brier). Not opened.
- FRI blog on LLM-superforecaster parity, https://forecastingresearch.substack.com/p/ai-models-have-likely-reached-parity (SNIPPET only).

## 5. Dawid-Skene and label-free accuracy for LLMs

### Multi-Source Emotion Annotation in Children's Language (Said and Villaneau; CAS @ LREC 2026)
- Link: https://aclanthology.org/2026.cas-1.11/ (ABSTRACT)
- Key numbers (quoted): Dawid-Skene estimated GPT-5.2 valence accuracy at 90.7% against 71.0% versus the human gold standard; it also underestimated Claude Sonnet 4, "which reverses the model ranking". 2,106 segments, 500 with gold. The authors attribute the gap to shared neutralization bias.
- Relevance: directly bears on H17 (Dawid-Skene within +-10 points of truth). Shared errors inflate the estimate, which is exactly the rho and phi we measure. Prediction: Dawid-Skene will overstate the accuracy of the 10 cheap calls if they share errors; treat H17 as likely to fail for same-source clusters and report the gap versus gold.
- Resources: expert gold subset released.
- Open questions: single-task, annotation, not reasoning puzzles.

### Others (SNIPPET only, not opened)
- judgepanel on PyPI (https://pypi.org/project/judgepanel/): fits Dawid-Skene to a judge panel; its documentation warns it assumes conditionally independent judges. Not opened.
- Calibrate, Don't Curate, https://arxiv.org/abs/2605.09702 (ABSTRACT): full judge panel beats top-k selection for calibrated evaluation; RewardBench2 NLL 0.006 vs 0.013; the page does not mention Dawid-Skene. Supports keeping weak, non-redundant members; relevant to H6.
- SSME, https://arxiv.org/abs/2501.11866 (ABSTRACT): semi-supervised accuracy estimation, "5.1x" error reduction against labeled data alone; the page does not name Dawid-Skene.
- I found no paper that applies Dawid-Skene to price-matched same-vendor repeats versus cross-vendor sources.

## 6. Cost-aware cascades and selective prediction

### FrugalGPT (Chen, Zaharia, Zou; arXiv 2305.05176)
- Link: https://arxiv.org/abs/2305.05176 (ABSTRACT)
- Key numbers (quoted): "match the performance of the best individual LLM (e.g. GPT-4) with up to 98% cost reduction"; at equal cost, accuracy up 4% over GPT-4.
- Relevance: baseline cascade. Learned scorer per tier (the 500-sample training claim is from a secondary snippet, unchecked). Reports cost reduction, not cost per correct answer.

### AutoMix (Madaan et al.; NeurIPS 2024)
- Link: https://arxiv.org/abs/2310.12963 (ABSTRACT)
- Key numbers (quoted): "reducing computational cost by over 50% for comparable performance"; five models, five datasets. Few-shot self-verification feeding a POMDP router.
- Relevance: baseline for H7. Numbers differ across versions (the snippet lists 86% and 89% in earlier ones); cite v-NeurIPS only.

### Agreement-Based Cascading (arXiv 2407.02348)
- Link: https://arxiv.org/abs/2407.02348 (ABSTRACT)
- Key numbers (quoted): "uses agreement between ensembles of models at each level of the cascade as a basis for data-dependent routing"; "2-25x reduction in average price per token or request" against state-of-the-art LLM cascades.
- Relevance: threatens novelty of H7's design (escalate unless at least 4 of 6 agree is an agreement cascade). Our contribution would be the dollar accounting under cache pricing and a non-inferiority margin, not the idea. Read the body before the write-up.

### C3PO (arXiv 2511.07396)
- SNIPPET only: label-free cascade bounding the probability that cost exceeds a budget with conformal prediction. Not opened.

None of the six reports "cost per correct answer" as a headline metric in what I read; this is mine to define (plan H15 uses net dollars per item at a stated penalty lambda).

## Summary table for the plan

| Plan item | Best prior | Direction |
|---|---|---|
| rho within vs between source (H1, H2) | 2607.10139: 0.68 / 0.52 / 0.47; Kim: same-company +0.02 to +0.07 | supports ordering; effect of vendor looks small |
| H4 naive agreement overconfident | 2607.08065 ECE 0.24-0.41 on GPQA | supports |
| H5, H6 correction | none cross-fitted with mixed vendors | open |
| H7 cascade | ABC 2407.02348, AutoMix, FrugalGPT | novelty is the cost accounting only |
| H8 extremizing | Satopaa 2014 (snippet), AIA report (Platt = extremizing), 1406.2148 | supports; a should shrink with overlap |
| H9 market | ForecastBench (freeze value access), AIA (ensemble helps only on liquid markets) | baseline |
| H17 Dawid-Skene | Said and Villaneau 90.7 vs 71.0 | predicts failure under shared error |

## So what (changes to research/v3/evidence/plan.md)

1. Do not re-order the write-up: the lead-with-Phase-2 rule does not fire. Keep Phase 1 (calibrated mixed-vendor agreement with cost) as the lead, but state the claim narrowly as "cross-fitted, on free-form puzzles and forecasts, with list-price dollars", because 2607.10139 and 2607.08065 are near neighbours.
2. Add 2607.10139's three-number law (a, rho, s) as a comparison in step 0.8 or the Phase 2 analysis: does it predict our panel's majority accuracy from the measured rho and shared-wrong rate? Cheap and would sit beside H3.
3. H7: cite Agreement-Based Cascading. State in the prereg that the agreement rule is not new and the test is cost under cache pricing with a -6 point margin.
4. H8: add a check that the fitted extremizing factor a moves with measured pairwise correlation (1406.2148), and fit the bias first (acquiescence in 2402.19379; Platt scaling includes an intercept, as AIA notes).
5. H17: pre-register the expected direction (Dawid-Skene overstates accuracy of correlated sources) and also report the gap for a cross-vendor-only subset.
6. Metric: define cost per correct answer explicitly; no prior paper headlines it.
7. Reading to finish before submission: the Satopaa 2014 and Baron 2014 papers themselves, ForecastBench Appendix E, the body of 2407.02348, and 2403.09849.
