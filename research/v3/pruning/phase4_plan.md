> **Superseded (session E5, 2026-10-26; Kevin's K1).** The project moved to v4, "width, depth and verification" (`research/plan.md`). This plan is kept as a record; nothing in it will run.

# Phase 4 plan: pruning beyond flat panels (written in session E3; no spend)

A plan for Kevin to cut, reorder or fund. Nothing here runs before he approves a November budget phase. Every
dollar figure is costed from calls already logged (results/*/results.csv), not from list prices alone; the
arithmetic is shown per row.

## What Phases 1-3 leave open

Phase 3A (research/v3/pruning/phase3a.md, cached, exploratory) found three things that shape Phase 4:

- A flat panel's static sub-networks cannot buy Sonnet's accuracy for less than Sonnet's cost: the one call that
  carries new information is the expensive one (Haiku-Sonnet error phi 0.08, Haiku-Haiku 0.44).
- Policies that call the expensive model only when cheap calls disagree can: the H7 cascade matched Sonnet's 71.2%
  at 0.57x its cost on the 80 cached items; a dynamic policy with a refitted confidence stop reached 67.5% at 0.78x.
- In staged Haiku networks each extra call adds about +0.9 points (+0.4 to +1.5), the same as an extra repeat
  vote; the 27 designs top out 8.8 points below one Sonnet call.

So the questions worth money are about (i) where independent information comes from (vendors, tiers, effort,
communication), (ii) policies rather than fixed networks, and (iii) how far scale goes before correlated errors
set a floor. Phase 1's Haiku-Luna error correlation is the input every row below depends on.

## Costs used (measured)

| call | $ per call | seconds | source |
|---|---|---|---|
| Haiku 5.5, thinking off, BBEH | 0.00071 | 5.9 | w0_haiku5, 500 calls |
| Sonnet 5.5, thinking off, BBEH | 0.0144 | 9.1 | p3/p4 single Sonnet, 80 calls |
| Haiku staged design 6-6-6 (19 calls, cached prefix) | 0.0115 per item | 32.5 | p4_bbeh_grid, 80 items |
| Luna, Sol, Opus, Astra, gpt-oss-120b | plan estimates until step 1.1's probe | | configs/experiments/evidence/e11_* |

A debate call reads its peers' previous answers, so it costs more than a single call: about 4,000 input tokens and
1,000 output tokens at Haiku's list price is 4,000 x $0.10/M + 1,000 x $0.50/M = $0.0009, against $0.00071 for a
single call. The staged grid's calls, which also read earlier agents' text, averaged 4,100 cache-read, 1,100
cache-write and 840 output tokens, $0.0006 per call (design 6-6-6), so caching the shared prefix may bring
debate calls below that; rows below use the uncached $0.0009 per Haiku debate call as a conservative figure, and
Phase 1's measured Luna cost (plan estimate $0.0007 until then).

## 4A. Communicating networks: pruning edges, rounds and agents

- **Network.** Debate on BBEH: 6 agents x 3 rounds; in rounds 2-3 each agent reads the other agents' previous
  answers (18 calls per item). Variants mix Haiku and Luna agents.
- **What is pruned.** Edges (who reads whom), rounds (stop after round r, or per item when the agents agree:
  the consensus exit already in autoagentnet/network/), agents.
- **Comparators.** AgentPrune (arXiv 2410.02506: one-shot top-K edge pruning trained by policy gradient with a
  nuclear-norm penalty) and AgentDropout (arXiv 2503.18891: node then edge dropout per round at fixed rates), as
  summarized in research/lit/prior_work.md; their public code has no licence, so both are reimplemented from
  the papers. Matched-cost random pruning is the primary control, because the
  September 2026 audit (arXiv 2609.05933) found both methods within about 0.2 points of it.
- **Evaluation.** A pruned communicating network cannot be replayed: later rounds read earlier text. Three
  levels: (1) fresh calls for every network scored (the truth, expensive); (2) an AMC-style proxy, the pruned
  network run on a 30-item subset; (3) a proxy test, as in Phase 3A: Spearman correlation between proxy and
  fresh accuracy over the networks scored both ways (Phase 3A's vote-vs-refit proxy reached only +0.45, so the
  proxy is tested, not assumed).
- **Size and cost.** 100 sealed BBEH items (a fresh draw), the dense network plus 8 pruned networks plus 4
  matched random controls = 13 networks; a pruned network averages about 10 calls per item:
  13 x 100 x 10 x $0.0009 = $11.7 (Anthropic). A Haiku-Luna mixed variant of the dense network and its best 3
  pruned versions: 4 x 100 x 12 x $0.0008 = $3.8, split about evenly between vendors.

## 4B. Prune plus cheaper tiers plus effort, under dollar and latency budgets

- **Lookup table, measured.** For each (model, effort) cell (Haiku off/on; Luna none/low/medium; Sonnet off/low;
  Sol low/medium): dollars per call, seconds, accuracy and the error correlation with every other cell. Most
  cells come from Phases 1-2; the missing ones are probed on 50 BBEH items, 2 calls per cheap cell and 1 per
  mid-size cell.
- **Search.** Over networks and dynamic policies built from the table's cells (extending
  autoagentnet/pruning/search.py with tier substitution and an effort dimension), maximize accuracy subject to
  dollars <= B and latency <= L, for B in {0.25, 0.5, 1} x Sonnet's cost and L in {10, 20, 40} seconds; rounds
  count toward latency. The frontier is predicted from the table and the top 3 picks per budget are verified
  with fresh calls.
- **Cost.** Probes: cheap cells 3 x 50 x 2 x $0.0008 = $0.24 per vendor; mid cells 2 x 50 x $0.02 = $2.0 per
  vendor. Verification: 3 picks x 3 budgets x 150 items x $0.007 (half Sonnet's cost on average) = $9.5, split
  by the picks' vendors (about $4.7 each); about $7.0 per vendor in all.

## 4C. Scale: 20 to 100 agents, the saturation curve and the error floor

- **Prediction from Phase 3A.** With repeat correlation rho, m calls are worth n_eff = m / (1 + (m - 1) rho),
  which can never exceed 1 / rho: at Haiku's rho 0.48, 100 Haiku calls are worth at most 2.1 independent ones.
  Mixing vendors raises the ceiling only as far as their cross-correlation allows. This n_eff reading is a
  labelled approximation. The floor itself is published: arXiv 2602.08003 (Turkmen, Buyukates, Bastopcu, Feb
  2026, on choosing models for an ensemble) proves that under a one-factor Gaussian-copula model with uniform
  correlation the ensemble's error tends to Phi(Phi^-1(1 - alpha) / sqrt(rho)) > 0 as models are added. Its rho
  is a latent correlation, not the 0/1 error correlation measured here (0.48), so 0.48 is not plugged into it;
  the latent value is estimated from the measured curve. 4C adds the measured curve with dollars attached, not
  the existence of a floor (research/lit/phase4_sources.md).
- **Design.** 100 calls per item of one cheap model on 100 sealed BBEH items, for Haiku, Luna and an open-weight
  model (gpt-oss-120b through OpenRouter: a separate account and key; reasoning effort low, medium or high, no
  "off"; reasoning tokens are billed as output, so the first probe logs output tokens per call and max_tokens
  leaves room for them); every m <= 100 is then read by subsampling exchangeable
  calls, so one run per source gives the whole saturation curve. Mixed panels are read the same way across
  sources.
- **Infrastructure.** Run on Maritime (the deployed agents keep the AgentRequest / AgentOutput contract) to test
  100-way concurrency; local and Maritime runs stay interchangeable (tests/test_maritime.py).
- **Cost.** Haiku 100 x 100 x $0.00071 = $7.1; Luna 100 x 100 x $0.0007 = $7.0 (Phase 1 measures it);
  gpt-oss-120b 10,000 x (I x p_in + O x p_out) / 1e6 with I and O the probe's input and output tokens per call.
  At 1,000 input and 1,500 output tokens (reasoning low), a pinned host at $0.15 / $0.60 per 1M (prices read
  2026-10-22; read again on the day) gives 10,000 x (0.00015 + 0.0009) = $10.5. OpenRouter's default routing
  weights hosts by price, so without pinning the price row must be the worst case, $0.35 / $0.95, which gives
  $17.8. Plan: pin one host and cap the account at $15, or halve the items. The provider entry already exists
  (openrouter_oss in configs/providers.yaml, through the OpenAI-compatible client, key OPENROUTER_API_KEY; Kevin
  may prefer the AAN_ prefix CLAUDE.md uses for the other keys). The account cap and the price row are Kevin's
  edits. Unverified: OpenRouter's credit-purchase fee and which effort values each host accepts.

## 4D. Decisions: sizing the W2 desk with the evidence meter

- Use the calibrated confidence (H5's correction, Phase 1) to size half-Kelly stakes on market questions against
  the freeze price, as H16 does, then compare a pruned meter's growth with Sonnet's at their costs.
- Kalshi only if its Developer Agreement allows research use; the terms page returned HTTP 429 four times in the
  last check (research/lit/v3_sources.md), so it is UNVERIFIED. Paper trading only; no money at risk.
- **Cost.** $0 of new calls if it reuses Phase 1-2 forecasts; a fresh 100-question market set at the pruned
  meter's cost (about $0.005 per question) is $0.5 per vendor.

## 4E. Depth: MathArena and checkable search problems, with reasoning on

- MathArena 2026 items (deferred from step 2.5 by Kevin's D2) with reasoning on: the depth track tests whether
  effort and calls trade off, i.e. whether pruning calls while raising effort keeps accuracy at lower cost. The
  items are the 93 gradable ArXivMath August-September 2026 problems already sealed (math_all.txt; CC BY-SA 4.0;
  MathArena grades them with an LLM judge, this project with its own final-answer matcher, a grader decision to
  state). The 2026 competition sets with final answers (AIME 2026, 30 items; HMMT February 2026, 33; CC BY-NC-SA
  4.0) predate the models' cutoff and, at 63 items, are about +-12 points wide, so they are not used. Data stay
  out of git.
- Problems with automatic checkers (AlphaEvolve-style construction problems): best-of-n with a verifier makes
  the verifier the aggregator, so pruning is about the number of candidates and their effort. Source:
  google-deepmind/alphaevolve_repository_of_problems (67 problems; Apache-2.0 code, CC-BY 4.0 other materials;
  Colab checkers for many, not all). Pick 10-15 problems whose checker is numpy-only and returns a number;
  success is the share of the best-known value reached. Checkers run locally and cost nothing; the $2 per vendor
  below is model calls.
- **Cost.** Step 2.5's estimate was $4.24 Anthropic and $6.34 OpenAI (research/v3/evidence/budget.md), but it
  priced the small models with thinking off; with reasoning on, hidden reasoning tokens bill as output. Until the
  step 1.1 probe's thinking-on math call measures it, the plan doubles that estimate (an assumption, not a
  measurement): $8.5 and $12.7, plus $2 per vendor for a checker pilot.

## 4F. Write-up and the evidence-meter API

- **Workshop paper outline.** (1) Evidence per dollar: correlated errors make extra cheap calls worth less than
  they look (Phase 1). (2) Pruning agent networks is a search over sources of independent information: exact
  replay of flat panels, criteria C1-C7 and searches S1-S4, with matched random controls (Phase 3). (3) Policies
  beat networks: cheap-first cascades with calibrated stopping (Phase 3C's lockbox). (4) The measured
  saturation curve and its dollar cost (4C; the floor itself is arXiv 2602.08003's theorem). (5) Limits: BBEH and ForecastBench only; list prices; two vendors.
- **Evidence-meter API sketch.** `POST /meter {question, kind, budget_usd, max_seconds}` returns
  `{answer, probability, calls: [{model, answer, usd}], usd, seconds, policy}`. It runs the frozen dynamic
  policy of selected.json: cheap calls first, stop when the calibrated confidence passes the policy's tau or the
  next call would break the budget; every call goes through autoagentnet's executor and SpendGovernor. It keeps
  the Maritime contract (bind $PORT, GET /health, answer within 30 s), so a 30 s budget caps the number of
  sequential rounds.

## Proposed November budget phase (Kevin decides)

| part | Anthropic $ | OpenAI $ | open-weight host $ |
|---|---|---|---|
| 4A communicating networks | 13.6 | 1.9 | 0 |
| 4B tiers and effort | 7.0 | 7.0 | 0 |
| 4C scale (100 calls x 100 items per source) | 7.1 | 7.0 | 10.5 (one pinned host) |
| 4D decisions | 0.5 | 0.5 | 0 |
| 4E depth (reasoning on: step 2.5's estimate x2, an assumption) | 10.5 | 14.7 | 0 |
| **expected** | **38.7** | **31.1** | **10.5** |
| proposed phase caps (expected x about 1.3; open-weight unpinned worst case $17.8) | 50 | 40 | 15 |

Against the lifetime caps: Anthropic has $11.12 spent and about $23.3 expected for the evidence phase, so
$38.7 more brings it to about $73 of $100 (about $84 after the x1.15 safety factor); OpenAI about $0.01 + $23.7
+ $31.1 = $54.8 (about $63). Both fit. Two assumptions carry most of the risk: the x2 for reasoning in 4E, and
Luna's price: every Luna cost here uses the price Kevin proposed ($0.10 / $0.50 per 1M); if the price table keeps
today's $0.20 / $1.20, Luna calls cost about 2.2 times as much, adding roughly $9 to OpenAI's column (4C's Luna
run alone goes from $7.0 to about $15). The order of cuts if Phase 1's measured costs come in high: 4E's checker
pilot, then 4A's mixed variant, then 4B's verification at the largest budget, then 4C's Luna run halved.

## Decisions for Kevin

1. Fund a November phase (caps above, or smaller) or stop after Phase 3C.
2. An open-weight vendor for 4C: approve OpenRouter (an OpenRouter key, an account cap of about $15, a price row
   for one pinned host) or drop the third source.
3. 4D: confirm Kalshi's terms or keep 4D on ForecastBench market questions only.
