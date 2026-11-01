# Market town: plan and preregistration (2026-10-19)

Approved by Kevin (`research/STEERING.md`, ninth entry, 2026-10-19): "Approved: market-town pilot (research/market/plan.md), about $5-8 actual inside the pilot phase cap. No other paid work." This file is binding for the market runs, together with `CLAUDE.md` and `docs/RESEARCH_PROTOCOL.md`. Changing a prereg block below means a new commit and regenerated configs (`python scripts/make_market_configs.py`) before the run. Revised after audit 26 (ADJUST, pre-run; `research/audit_log.md`) and after Kevin's answers (STEERING, tenth entry: no control_resample gate, run order M1, M2, M4, M3, M4 at 4 sessions, Sonnet sessions up to 35 minutes), before any paid call.

## 1. Question

Do LLM traders in a continuous double auction (CDA) allocate goods as well as the competitive equilibrium predicts, and as well as zero-intelligence traders who only respect their budget? And when junior (Haiku 5.5) and senior (Sonnet 5.5) traders meet in one market, who gets the surplus?

- **MT1, sanity:** an all-Haiku market reaches allocative efficiency near the ZI-C baseline on the same protocol, and its prices move toward P*.
- **MT2, scale:** an all-Sonnet market trades less and less efficiently than an all-Haiku one (the pattern Struski et al. report for GPT Large).
- **MT3, exploitation:** in a mixed market, Sonnet traders earn a larger share of their competitive-equilibrium profit than Haiku traders.

Why it matters for the project: the pilot asked how to spend calls inside one team; this asks whether agents can coordinate through prices instead, and whether seniors exploit juniors when they meet in a market. A sane market is the precondition for a firm-vs-market comparison (decision rules, section 7).

## 2. Design

**Schedule (Smith 1962 Test 1, as in arXiv 2609.02580).**

| | Rank 1 to 11 |
|---|---|
| Buyer values ($) | 3.25, 3.00, 2.75, 2.50, 2.25, 2.00, 1.75, 1.50, 1.25, 1.00, 0.75 |
| Seller costs ($) | 0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00, 3.25 |

- **Equilibrium:**
  - competitive price P* = $2.00 exactly;
  - competitive quantity Q* = 6 (the sixth pair, value 2.00 and cost 2.00, trades at zero surplus);
  - maximum surplus $7.50 per period;
  - extramarginal traders are ranks 7-11 on each side.
- **Why this schedule.** Kevin's rule was to use the paper's 11x11 schedule if it is published, and the fallback (P* 1.95-2.05, maximum surplus 6.10) otherwise. Struski et al. publish it:
  - Section 3.1 gives "$0.75 to $3.25 in $0.25 increments", p* = 2.00 and q* = 6;
  - Figure 1 plots it;
  - their repo config sets `min 0.75, max 3.25, num 11` (`research/lit/market.md`).
  - It is also the only schedule with human data (Smith Test 1) and LLM data (Struski Table 1) to compare against.
  - The fallback schedule stays in the code as a robustness variant; it is not run.

**Market rules** (code: `autoagentnet/market/engine.py`; tests: `tests/test_market.py`).
- **Traders and periods.** 11 buyers and 11 sellers, one unit each per period, 5 periods. "Values reset each period" means every trader gets its unit back with the same value or cost, as in Smith and Struski; nothing is redrawn.
- **Polling.** Each period has R = 8 polling rounds. In each round, every trader who has not yet traded in that period acts once, in an order drawn at random from (session seed, period, round).
- **Book.** It keeps only the best bid and the best ask. A new bid must beat the best bid, and a new ask must undercut the best ask.
- **Trades.** A bid at or above the best ask, an ask at or below the best bid, or ACCEPT trades one unit at the standing quote's price. Both quotes then clear (as in Gode and Sunder; Struski's repo clears only the two traders' own quotes).
- **Budget rule** (enforced; Struski only states it in the prompt). A buyer cannot bid or buy above its value, and a seller cannot ask or sell below its cost. Violations are rejected, counted and treated as PASS.
  - A bid above value is rejected even if it would cross a lower ask. The prompt says so: "may not bid or pay more than its value" (audit 26, finding 5).
- **Other rejected orders:** a non-improving quote, ACCEPT with nothing standing, a quote on the wrong side, or a price of zero or less.

**LLM traders** (`autoagentnet/market/traders.py`, `caller.py`).
- **Call path.** Every call goes through MarketCaller: the call cache, then the SpendGovernor (worst case reserved, ledger written), then AgentRuntime as an AgentRequest. The traders can therefore run as Maritime containers later.
- **Prompt.** The system prompt and the market rules (identical for all traders, about 1,750 characters, so about 800 tokens and above the roughly 512-token cache minimum seen in the ledger) come first as the cached block. The trader's own situation comes after it:
  - role and own value or cost;
  - period and round;
  - best bid and ask, marked "(yours)" when it is the trader's own;
  - the last 10 trade prices this period;
  - the mean price of each earlier period;
  - own profit so far.
  - Never other traders' values. Struski show the full order history instead; ours is shorter.
- **Reply format.** "REASON: <one sentence>", then "ACTION: BID <price> | ASK <price> | ACCEPT | PASS". A reply without a readable ACTION line counts as PASS and is logged as unparsed.
  - Markdown marks (`*`, `_`, backticks) are ignored.
  - A comma decimal ("1,85") is unparsed, never read as $1.00 (audit 26, finding 4).
  - The unparsed and truncation stops are checked after every round (once 40 turns are in), so a broken format costs about two rounds, not a period.
- **Models and limits.** `haiku_nothink` (Haiku 5.5, thinking off) and `sonnet_nothink` (Sonnet 5.5, thinking `between_tools`). max_tokens 200; temperature 1 (as in Struski).
- **Seeds.** The session seed is the replicate number of every call, so sessions never share cached calls. Seeds are unique across the study:
  - M1: 1;
  - M2: 11-14;
  - M3: 21-22;
  - M4: 31 and 33 (odd ranks senior), 32 and 34 (even ranks senior);
  - ZI-C: 1000-1999.

**ZI-C baseline** (`ZICTrader`).
- **Quotes.** On every turn a buyer bids uniformly at random on [$0.01, value], and a seller asks uniformly on [cost, $4.00]. This is the full budget range, as in Gode and Sunder; the bounds follow the Struski repo's ZI range (0 to 4) with a one-cent floor.
- **Protocol.** Same engine, schedule, R and periods as the LLM runs. 1,000 sessions, free.

## 3. Metrics (`autoagentnet/market/metrics.py`)

- **Allocative efficiency E** = realized surplus / maximum surplus.
  - Realized surplus is the sum, over trades, of buyer value minus seller cost.
  - Per period, the maximum is $7.50. A session's E is its surplus over 5 x $7.50.
- **Trade ratio** = trades / Q*. The zero-surplus sixth pair counts as a trade.
- **Mean price**, per period and over the session.
- **Smith's alpha**, computed per period: 100 x the root mean squared deviation of the period's trade prices from P*, divided by P* (Smith 1962, p. 116).
  - It is undefined for a period without trades.
  - The trade count is reported next to it.
- **Extramarginal trades**: trades in which the buyer or the seller has rank above Q*.
- **Rejected-order rate** = rejected orders / orders (BID, ASK and ACCEPT).
- **Unparsed rate** = unparsed replies / turns.
- **Truncation rate** = replies stopped by max_tokens / turns.
- **Trader profit**, and **profit / CE profit**. CE profit is the profit at P*: value - 2.00 for an intramarginal buyer, 2.00 - cost for an intramarginal seller, and 0 for extramarginal traders and the rank-6 pair. Group comparisons pool profit and CE profit first.
- **Cost per session** at list prices; cached calls count at their original price.
- **Waiting** (audit 26, finding 3), per period:
  - **late PASS share**: the share of turns in rounds 6-8 by traders with a positive CE profit (ranks 1-5; every trader who acts has not traded yet) that are PASS;
  - **final spread**: best ask minus best bid after the period's last turn.
- **M4 breakdown** (audit 26, finding 2):
  - **trade rate by model**: the share of (trader, period) slots of traders with a positive CE profit that end in a trade. This is who gets to trade.
  - **price edge**: the mean, over Sonnet-Haiku trades, of Sonnet's advantage relative to P*. That is P* - price when Sonnet buys and price - P* when it sells. This is at what price.

## 4. ZI-C baseline (run first, before any paid call)

`aan run configs/experiments/market/zic.yaml`, seeds 1000-1999. Results are in `results/market_zic/periods.csv` and `sessions.csv`; trades and traders are not kept, and a free rerun regenerates them.

| ZI-C, R = 8, 1,000 sessions | Value |
|---|---|
| Session efficiency, mean (SD) | **90.4%** (3.8) |
| Session efficiency, 2.5 / 5 / 50 / 95 / 97.5 percentiles | 82.0 / 84.0 / 90.7 / 96.0 / 96.7% |
| Period efficiency, 5 / 50 / 95 percentiles | 73.3 / 93.3 / 100% |
| Trades per period (Q* = 6) | 5.05 (trade ratio 0.84) |
| Extramarginal trades per period | 0.50 |
| Smith's alpha by period 1-5 (mean) | 20.5, 20.6, 20.5, 21.0, 20.8 (no trend; ZI-C has no memory) |
| Mean price by period 1-5 | 1.99, 2.00, 2.01, 2.01, 1.99 |
| Rejected-order rate | 71% (most random quotes fail quote improvement) |
| Turns per period | 125 |

- **Sensitivity to R** (200 sessions each, from the probe in the session log): R = 16 gives 95.8%. On the fallback schedule, R = 8 gives 85.9% with the [$0.01, $4.00] range and 94.6% with [$1.00, $3.00].
- **R is a confound** (research/lit/market.md, "so what" item 4). Struski allow up to 300 draws per round, about 13.6 turns per agent; R = 8 allows at most 8.
  - A trader who waits is penalized more here.
  - So M3's comparison with M2 is read against R: a Sonnet shortfall that comes with many PASS turns in the last rounds is "waiting", not mispricing.
- **Thresholds for section 7:**
  - ZI-C - 5 points = **85.4%**;
  - ZI-C - 10 points = **80.4%**.

**Struski Table 1** (comparison numbers, mean of 10 runs by round):
- GPT Small: efficiency 0.79, 0.86, 0.89, 0.89, 0.91 (mean about 0.87; the "91%" is its peak); alpha 27.6 down to 11.7.
- GPT Large: efficiency 0.36-0.67 (mean about 0.53).
- Gemini Large: efficiency 0.58-0.83 (mean about 0.70).
- Humans (Smith Test 1): alpha 11.8, 8.1, 5.2, 5.5, 3.5.
- These are OpenAI and Google models under an unenforced budget rule and a longer horizon, so the Claude numbers are new measurements, not replications.

## 5. Runs and budget

One paid run at a time, one session per run, in Kevin's order: **M1, M2 (4 sessions), M4 (4 sessions: 31, 32, 33, 34), M3 (2 sessions)**. If money or time runs short, M3 is dropped (STEERING, tenth entry).

**Before each run:**
- `aan estimate --record research/estimates.csv`;
- a dry run with the fake model;
- commit;
- `aan check` prints cleared;
- `aan bill`.

**After each run:**
- read `status.json`;
- check that the `state:` checkpoint is on origin;
- `aan bill`;
- call the auditor and paste the verdict into `research/audit_log.md`;
- log estimate against actual in `research/log.md`.

**Gate:** none beyond the per-run gate above. Kevin dropped the "control_resample merged" gate (STEERING, tenth entry): no other session is spending, and the control-resample session starts from main after `market_town` is merged, so the ledger stays one history.

| Run | Config | Sessions (one run each) | Calls at most per session | Worst case per session (x 1.15) | Projected actual per session |
|---|---|---|---|---|---|
| M1 | `m1_smoke` | seed 1, 2 periods | 352 | $0.067 ($0.077) | about $0.01 |
| M2 | `m2_haiku` | seeds 11-14 | 880 | $0.168 ($0.194) | about $0.03-0.05 |
| M3 | `m3_sonnet` | seeds 21-22 | 880 | $3.367 ($3.872) | about $0.6-0.9 |
| M4 | `m4_mixed_odd` (31, 33), `m4_mixed_even` (32, 34) | 4 sessions | 880 | $1.913 / $1.622 ($2.20 / $1.87) | about $0.3-0.5 |
| | **Total** | 11 sessions | | **$14.55** | **about $2.8-4.2** |

- **How the worst case is computed.** Every trader acts in all 8 rounds of every period (no trade ever), with the longest situation text and 200 output tokens. Every prompt token is charged at the cache-write rate.
- **How the projection is computed:**
  - about 625 turns per session (ZI-C has 125 per period; an LLM that passes more has up to 176);
  - a cached 800-token prefix, about 170 uncached tokens and about 50 output tokens per call.
- **Sizing R.** R = 8 is the largest R at which an all-Sonnet session fits the $4 run cap: its worst case is 3.87 after the safety multiplier. The rules text was shortened to make it fit; R = 9 would not.
  - This uses the project's estimator, at 3 characters per token. In the ledger, real Claude 5.5 prompts run 1.22-1.5x that estimate (audit 26, finding 6).
  - So a Sonnet session's true worst case is about $3.9-4.2 before the safety multiplier. "Fits" is the governor's reading, not a guarantee.
  - Money stays protected anyway. The governor stops a run before its actual spend x 1.15 passes the $4 cap, and the projected actual is about $0.6-0.9.
- **One session per run.** `m2_haiku` has `max_usd: 0.25` and the M4 configs `max_usd: 3.0`, so `aan check` refuses more than one session per run; M3's two sessions do not fit $4 together, and M1 has one seed.
- **Re-projection and stops on actual spend** (audit 26, findings 6 and 7). After M1, log:
  - the real-to-estimated prompt-token ratio;
  - cost per turn;
  - turns per period;
  - and from these, re-project each later session.
  - **Kill on a session:** its actual spend is over 1.5x its re-projection. Stop and audit. (A kill at 1.5x the worst case could never fire.)
  - **Cumulative market stop at $8**, the top of Kevin's range. Before each run, add the market's actual spend so far to the run's re-projection; if the sum passes $8, do not start the run, and hand back.
  - If the re-projection after M1 puts M1-M4 together above $8, M3 is dropped first: its scale question is confounded with R = 8.
- **Phase cap.** The pilot has spent $6.71, and each run's worst case must fit (spent + worst case) x 1.15 <= $20.
- **Run time.** A Sonnet session makes up to 880 sequential calls. Kevin allows up to 35 minutes per all-Sonnet session (STEERING, tenth entry). State is checkpointed after every period; if the environment stops a run, it is rerun (cached calls are free) and logged.

## 6. Analysis plan (fixed before any paid run)

- **Primary intervals.** 95% intervals come from resampling sessions with replacement within each condition (10,000 draws; a difference resamples each condition independently). With 2 to 4 sessions per condition these intervals are crude, and they are labeled with n.
- **Secondary intervals.** Intervals that resample periods are reported only where periods are exchangeable: for ZI-C (no memory), and for LLM conditions marked "treats periods as independent". LLM traders see earlier periods' prices, so their periods are not independent.
- **ZI-C reference.** The ZI-C distribution is the 1,000-session one in section 4. Its mean's interval is about ±0.24 points.
- **M4 profit gap** = pooled Sonnet profit / pooled Sonnet CE profit - pooled Haiku profit / pooled Haiku CE profit, in points, over all 4 M4 sessions (A: 31, 33; B: 32, 34) together (`metrics.profit_gap`).
  - Every rank is Sonnet in two sessions and Haiku in the other two, so the two CE pools are equal ($75.00 each over 5 periods).
  - The gap is therefore the sum of the 22 rank differences (profit as Sonnet - profit as Haiku) over $75.00.
  - It is also reported by side.
- **The M4 interval is descriptive only** (audit 26, finding 1). The rank-pair interval (`metrics.rank_pair_interval`) ignores session-to-session variation.
  - On a ZI-C null (300 A/B pairs with no senior at all), it excludes 0 in 6.7% (session log; the auditor's run gave 10.7%) instead of 5%.
  - On the same null, the gap's SD is 10.5 points, it reaches 10 points in 17% of pairs and 20 points in 3.3%, and its 95th percentile is 17.6.
- **The M4 test is against placebo gaps** (`metrics.placebo_gaps(per_side=2)`): every split of M2's 4 all-Haiku sessions into two "A" sessions (odd ranks labeled "Sonnet") and two "B" sessions (even ranks labeled "Sonnet"), as in M4. There are 6 splits. They measure the noise of the label split on real LLM sessions.
  - **ZI-C null for this design** (1,000 draws of 2 A + 2 B sessions, session log): gap SD 7.8 points; P(gap >= 10) 10.3%; P(gap >= 20) 0.8%; 95th percentile 13.6; the median largest of 6 placebo gaps is 9.9. The full rule (at least 20 and above all 6 placebo gaps from 4 other sessions) fires in 0.8% of null draws.
- **The M4 gap is broken down** into the trade rate by model and the price edge (`metrics.senior_breakdown`). That way a Sonnet that waits (MT2) and loses trades is not mistaken for a Sonnet that loses on price.
- **The M3 contrast is against a null.** On ZI-C, 2 sessions fall at least 7 points below 4 sessions by chance 2.8% of the time (SD of the difference 3.5 points). Both efficiency and trades come out lower 28% of the time.
- **Figures** (`reports/market/`):
  - (a) supply and demand steps with P*;
  - (b) trade price paths by period for each condition, against P*;
  - (c) efficiency by condition against the ZI-C distribution;
  - (d) M4 profit / CE profit, Sonnet against Haiku, by side;
  - (e) alpha by period.
- **Diagnosis**, if efficiency falls short, from `turns.csv`. Three readings:
  - no trades: many PASS turns, or spreads that never close;
  - extramarginal trades;
  - anchoring: prices stuck near the first trade of period 1.

## 7. Decision rules (fixed)

- **M2 efficiency** (mean over 4 sessions, point estimate; interval reported):
  - **at least 85.4%** (ZI-C - 5): LLM markets are sane. Propose a firm-vs-market follow-up to Kevin. No scale-up without him;
  - **below 80.4%** (ZI-C - 10): the headline is that LLM traders are worse than budget-constrained random traders. Diagnose by the three readings in section 6;
  - **in between:** report "near ZI-C", with no proposal.
- **M3 vs M2:** MT2 "holds" only if both hold (audit 26, finding 3):
  - M3's mean efficiency is at least 7 points below M2's;
  - M3 has fewer trades per period.
  - Read against R: a higher late PASS share and a wider final spread mean waiting, not mispricing.
- **M4:** seniors "exploit" juniors only if both hold (audit 26, finding 1):
  - the gap is at least 20 points;
  - the gap is larger than every M2 placebo gap (6 splits).
  - A gap between 10 and 20 points meets Kevin's prediction but is reported as "not distinguishable from label noise at n = 4".
  - Either way the breakdown says whether it is trades or prices.
  - The gap is not interpreted at all if either model is over 5% unparsed or truncated in M4 (audit 27). The format stops are checked per model after every round, so one model's failures cannot hide behind the other's turns.
  - Four sessions do not set an agent-company design rule. A gap that clears the bar is a reason to propose a larger M4 to Kevin.
- **Any kill** stops paid work until the auditor says GO.
- **No scale-up** without Kevin.

## 8. Preregistration (copied verbatim into the configs by `scripts/make_market_configs.py`)

<!-- prereg:begin (copied verbatim into configs/experiments/market/*.yaml by scripts/make_market_configs.py) -->
```yaml
m1_smoke:
  question: Does an all-Haiku (haiku_nothink) market run cleanly for 2 periods at R = 8 on the Smith schedule - replies parse, nothing truncates, few orders are rejected, and trades happen?
  prediction: "Unparsed replies under 5% of turns; no reply truncated at max_tokens 200; rejected orders under 10% of orders (BID, ASK, ACCEPT); at least 3 trades in each of the 2 periods."
  kill: "Unparsed over 10% or truncation over 5% (the run stops itself, checked after every round): fix the prompt or parser (free, with a fake-model test), commit, and rerun M1 under a new seed before anything else. Spend over 1.5x the worst-case estimate, or no trade in either period: stop and audit."
  decision: "No kill: log the real-to-estimated prompt-token ratio, cost per turn and turns per period, re-project every later session, apply the $8 cumulative market stop (M3 is dropped first if M1-M4 would pass $8), then go to M2. A missed prediction that is not a kill (for example rejected orders at 10-25%) is logged and audited, and M2 runs if the auditor says GO."
m2_haiku:
  question: How efficient and how convergent is an all-Haiku market over 5 periods (4 sessions, seeds 11-14), against ZI-C on the same protocol (90.4%) and against Struski et al.'s GPT Small (0.79-0.91 by round)?
  prediction: "Mean session efficiency 75-95%; period-5 mean trade price within $0.15 of P* (1.85-2.15), averaged over sessions; Smith's alpha lower in period 5 than in period 1, averaged over sessions."
  kill: "A session's actual spend over 1.5x its re-projection after M1 (section 5), or a session with zero trades in every period: stop and audit. The run also stops itself after 3 periods in a row without a trade, or at over 10% unparsed or over 5% truncated replies (checked after every round). If the market's actual spend so far plus this run's re-projection passes $8, the run does not start."
  decision: "Mean efficiency at least 85.4% (ZI-C - 5): LLM markets are sane; propose a firm-vs-market follow-up to Kevin. Below 80.4% (ZI-C - 10): headline 'LLM traders are worse than budget-constrained random traders', diagnose (no trades vs extramarginal trades vs anchoring) from turns.csv. In between: report as near ZI-C, no proposal. M2's sessions also give the 6 placebo gaps for M4. M4 and then M3 run in every case unless a kill or the $8 stop fires (M3 is dropped first)."
m3_sonnet:
  question: Does an all-Sonnet (sonnet_nothink) market (2 sessions, seeds 21-22) trade less and less efficiently than the all-Haiku market, the pattern Struski et al. report for GPT Large (waiting for the spread to close)?
  prediction: "Fewer trades per period and lower mean session efficiency than M2 (point estimates over all sessions); a higher late PASS share (rounds 6-8, traders with a positive CE profit) and a wider final spread than M2."
  kill: "A session's actual spend over 1.5x its re-projection after M1 (section 5), or a session with zero trades in every period: stop and audit. The run also stops itself after 3 periods in a row without a trade, or at over 10% unparsed or over 5% truncated replies (checked after every round). If the market's actual spend so far plus this run's re-projection passes $8, the run does not start."
  decision: "Holds only if M3's mean efficiency is at least 7 points below M2's and M3 has fewer trades per period (a 2-vs-4-session ZI-C null reaches -7 points 2.8% of the time): the scale pattern appears on Claude too; with a higher late PASS share and wider final spread it is waiting, which R = 8 penalizes, not mispricing. Otherwise: not shown at this n; report the point estimates. M3 runs last (Kevin's order: M1, M2, M4, M3)."
m4_mixed:
  question: With Sonnet on half of each side (A sessions, seeds 31 and 33, on the odd ranks; B sessions, seeds 32 and 34, on the even ranks; so every rank is Sonnet twice and Haiku twice), do Sonnet traders earn a larger share of their competitive-equilibrium profit than Haiku traders, and does mixing change efficiency?
  prediction: "Pooled Sonnet profit / CE profit exceeds pooled Haiku profit / CE profit by at least 10 points (all 4 sessions together, point estimate); mean efficiency of the 4 mixed sessions not above M2's."
  kill: "A session's actual spend over 1.5x its re-projection after M1 (section 5), or a session with zero trades in every period: stop and audit. The run also stops itself after 3 periods in a row without a trade, or at over 10% unparsed or over 5% truncated replies (checked after every round). If the market's actual spend so far plus this run's re-projection passes $8, the run does not start."
  decision: "The gap is not interpreted if either model is over 5% unparsed or over 5% truncated in M4 (audit 27; rates by model are reported in the M4 tables). Exploitation is claimed only if the gap is at least 20 points and larger than every M2 placebo gap (the 6 splits of M2's 4 sessions into two A and two B sessions, labeled odd/even as in M4); on a ZI-C null this rule fires in 0.8% of draws, and the gap alone reaches 10 points in 10.3%. A gap of 10-20 points meets the prediction but is reported as not distinguishable from label noise at n = 4. The rank-pair interval is descriptive only. The breakdown (trade rate by model, price edge in Sonnet-Haiku trades) says whether the gap comes from who trades or from prices. Four sessions set no agent-company design rule; a gap over the bar is a reason to propose a larger M4 to Kevin. Then M3, unless money or time is short."
```
<!-- prereg:end -->

## 9. Deviations from Kevin's prompt, and why

1. **Schedule.** The paper's 11x11 schedule replaces the fallback, which was Kevin's own rule. P* = 2.00, Q* = 6 and maximum surplus 7.50, not 6.10.
2. **"2609.02580's small model: 91%"** is GPT Small's peak, in round 5; its five-round mean is about 0.87. The M2 prediction range (75-95%) is unchanged.
3. **"Scale paradox"** is not the paper's term. The authors hedge the scale claim, and the waiting mechanism is shown for GPT Large only (Gemini Large trades but disperses prices). M3's prediction is kept as Kevin wrote it.
4. **M4's "half of each side."** It is 6 + 6 in the A sessions (odd ranks; seeds 31, 33) and 5 + 5 in the B sessions (even ranks; seeds 32, 34). With 4 sessions every rank is senior in exactly two sessions (Kevin, tenth entry).
5. **Stopping rules.** The in-run stop after 3 zero-trade periods in a row (2 for M1) is an early form of the kill "zero trades in every period". It saves money when a market is clearly broken.
6. **Audit 26 (ADJUST, pre-run) changes:**
   - the kill on spend compares against the re-projection after M1, not the worst case;
   - a cumulative $8 market stop;
   - one session per run enforced by `max_usd`;
   - stricter bars: M3 at least 7 points below M2; M4 at least 20 points and beyond every placebo gap;
   - the M4 breakdown and the waiting metrics;
   - the parser fixes and per-round format stops;
   - the budget-rule wording in the prompt.
   - Kevin's own predictions are unchanged.
7. **Order of runs and M4 size (Kevin, tenth entry).** M1, M2, M4, M3; M3 is dropped if money or time runs short. M4 has 4 sessions (A/B value assignment x 2 seeds) as long as the projected market total stays under the $8 stop; its prereg and placebo calculation were updated for 4 sessions, and the auditor's OK is needed before M4 runs.
