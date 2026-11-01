# Market Town: LLM traders in a double auction against the competitive equilibrium

<div class="byline">AutoAgentNetwork, market-town pilot (session 5, 2026-10-19). Branch <code>market_town</code>. Every number below is filled in by <code>python -m analysis.market</code> from <code>results/</code>; the plan and preregistration are in <code>research/market/plan.md</code>.</div>

<div class="abstract" markdown="1">

**Question.** Do Claude traders in a continuous double auction allocate goods as efficiently as the competitive equilibrium predicts? Do they do better than zero-intelligence traders who only respect their budget? And when junior (Haiku 5.5) and senior (Sonnet 5.5) traders meet in one market, who captures the surplus?

**Design.**

- Smith's (1962) Test 1 schedule, as used by Struski et al. (arXiv 2609.02580): 11 buyers and 11 sellers, values and costs from $0.75 to $3.25. The competitive price P* is $2.00, the competitive quantity Q* is 6 units, and the maximum surplus is $7.50 per period.
- Five periods of 8 polling rounds each, and a best-bid / best-ask book with an enforced budget rule.
- Conditions: M1 (smoke) and M2, all Haiku, M2 with 4 sessions; M4, Sonnet on half of each side, 4 sessions; M3, all Sonnet, 2 sessions. The baseline is 1,000 sessions of ZI-C traders on the same protocol.

**Results.**

{{include:reports/market/abstract_results.md}}

</div>

<div class="columns" markdown="1">

## 1. Why a market

The pilot (`reports/pilot/`) asked how to spend agent calls inside one team. Its premise did not hold on fresh items: one Sonnet call matched the 19-call Haiku team. A second way to organize agents is through prices: agents trade, and the market coordinates them. That idea is only worth pursuing if LLM traders produce a sane market. Such a market:

- allocates units to the traders who value them most;
- converges toward the competitive price;
- does at least as well as random traders who only respect their budget, since that baseline already reaches about 90% efficiency here.

The mixed market also asks a question for an agent company. When seniors and juniors trade against each other, does the senior capture the junior's surplus?

## 2. Design

**Schedule.**

- Buyer values: 3.25, 3.00, ..., 0.75. Seller costs: 0.75, 1.00, ..., 3.25.
- Supply and demand cross at P* = $2.00 and Q* = 6. The sixth pair (value $2.00, cost $2.00) trades at zero surplus.
- Ranks 7-11 on each side are extramarginal: at P* they should not trade, and every trade they make displaces surplus.

{{figure:a_supply_demand|Figure (a). Induced demand (buyer values) and supply (seller costs). They cross at P* = $2.00 and Q* = 6 (Smith 1962, Test 1; Struski et al. 2026).}}

**Market rules.**

- Every period, each trader has one unit to buy or sell.
- Each period has R = 8 polling rounds. In each round, every trader who has not yet traded acts once, in a seeded random order.
- The book holds only the best bid and the best ask. A new bid must beat the best bid, and a new ask must undercut the best ask.
- A crossing quote, or ACCEPT, trades at the standing quote's price, and both quotes then clear.
- The budget rule is enforced: a buyer cannot bid above its value and a seller cannot ask below its cost. Such orders are rejected and count as a PASS.

**LLM traders.**

- Each trader reads the market rules (identical for all traders, and cached as a shared prompt prefix), then its own situation:
    - its value or cost;
    - the period and round;
    - the best bid and ask;
    - the last 10 trade prices this period;
    - the mean price of earlier periods;
    - its profit so far.
- It replies with one line of reasoning and an action: BID, ASK, ACCEPT or PASS.
- Models: Haiku 5.5 and Sonnet 5.5, thinking off, temperature 1, at most 200 output tokens.
- Each session has its own seed, used as the replicate number of every call, so no session reuses another's cached calls.

**ZI-C baseline** (Gode and Sunder 1993). Each turn, a buyer bids uniformly between $0.01 and its value, and a seller asks uniformly between its cost and $4.00. It never learns. 1,000 sessions run on the same engine.

**Metrics.**

- Allocative efficiency: realized surplus over $7.50 per period.
- Smith's alpha, per period: 100 × the RMS deviation of trade prices from P*, divided by P*.
- Extramarginal trades.
- Rejected-order and unparsed rates.
- Profit as a share of the profit each trader would earn at P* (CE profit).
- Waiting:
    - the late PASS share: PASS turns by traders with a positive CE profit in rounds 6-8;
    - the final spread.
- Intervals: 95% intervals resample sessions (10,000 draws). With 2-4 sessions per condition they are crude, and each is shown with its n.

## 3. The ZI-C baseline

{{table:conditions_report}}

On this protocol, ZI-C reaches {{value:zic_eff}}% mean session efficiency (1,000 sessions). Its alpha is about 20.6 in every period, because ZI-C has no memory. The preregistered decision lines are therefore:

- at least {{value:sane_at}}% for "sane";
- below {{value:worse_below}}% for "worse than random".

## 4. Results

{{include:reports/market/results.md}}

{{figure:c_efficiency|Figure (c). Session efficiency by condition (dots: sessions; diamonds: mean with 95% session-resampled interval) against the ZI-C distribution (grey histogram; line: mean; band: ZI-C - 10 to - 5 points).}}

{{figure:b_price_paths|Figure (b). Trade prices in each period for every session of M2, M4 and M3, against P* = $2.00 (dashed).}}

{{figure:e_alpha|Figure (e). Smith's alpha by period: mean over sessions per condition; humans (Smith 1962 Test 1) and GPT Small (Struski et al. 2026) for reference.}}

{{figure:d_m4_profit|Figure (d). M4: profit as a share of CE profit for Sonnet and Haiku traders, by side (100% = what trading at P* would give).}}

## 5. Decisions (preregistered)

{{table:decisions}}

{{include:reports/market/discussion.md}}

## 6. Spend

{{table:spend}}

## Appendix: tables

{{table:by_period}}

{{table:sessions}}

{{table:m4_profit}}

{{table:m4_placebo}}

</div>
