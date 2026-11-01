### 4.1 M1: the smoke test

One all-Haiku session of 2 periods. Every M1 prediction was met:

- unparsed 0% (prediction under 5%);
- no truncation;
- rejected orders 1.9% (prediction under 10%);
- 6 and 7 trades per period (prediction at least 3).

The shared rules prefix (631 tokens) was written to the cache once and read on every later call, so a Haiku turn cost about $0.00007. M1 is not pooled with M2.

### 4.2 M2: all-Haiku markets

**Efficiency.**

- Four sessions reached {{value:m2_efficiency_pct}}% mean efficiency (92.7, 97.3, 98.0 and 92.7%). Every session beat the ZI-C mean of {{value:zic_eff}}%. The lowest session (92.7%) is above ZI-C's median of 90.7%.
- About {{value:m2_extramarginal_per_period}} extramarginal trades happen per period, against 0.50 for ZI-C. LLM traders almost always trade the right units, but too many of them: {{value:m2_trades_per_period}} trades per period against ZI-C's 5.05. The sixth pair (zero surplus) often trades as well.

**Prices.**

- Prices sit below P* in almost every period: {{value:m2_periods_below_pstar}} period means are below $2.00. ZI-C, on the same engine, prices at 1.99-2.01.
- Buyers earn {{value:m2_buyer_share}}% of their CE profit, sellers {{value:m2_seller_share}}%.
- **Possible prompt anchor.** The shared rules say "Prices are in dollars and cents, for example 1.85". In M2, {{value:m2_share_at_185}}% of trades are at exactly $1.85, tied for the most common price. In M4 and M3, $1.85 is the most common trade price. So the below-P* bias and the buyer advantage may come partly from the prompt rather than from the traders' reasoning (audit 37).
- Smith's alpha falls from {{value:m2_alpha_first}} (period 1) to {{value:m2_alpha_last}} (period 5) in every session. That is learning across periods, which ZI-C (alpha 20.5-21.0, flat) cannot do.
- For comparison, GPT Small in Struski et al. goes from 27.6 to 11.7, and Smith's human subjects from 11.8 to 3.5.

**Reply format.** {{value:m2_rejected_rate_pct}}% of orders are rejected, mostly sellers asking below cost in late periods. {{value:m2_unparsed_rate_pct}}% of replies are unparsed.

### 4.3 M4: Sonnet and Haiku in one market

**Design.** Sonnet held the odd ranks of both sides in sessions 31 and 33, and the even ranks in sessions 32 and 34. Every rank was senior twice and junior twice, so the two models' competitive-equilibrium profit pools are equal ($75 each).

**The gap.**

- Sonnet earned {{value:m4_gap}} points more of that pool than Haiku: buyers {{value:m4_gap_buyer}}, sellers {{value:m4_gap_seller}}.
- The rank-pair interval is {{value:m4_gap_lo}} to {{value:m4_gap_hi}}. It is descriptive only, because it ignores session-to-session variation.
- Labeling M2's all-Haiku sessions the same way gives placebo gaps of up to {{value:m4_placebo_max}} points. So the gap is within label noise.
- The preregistered reading is **"{{value:m4_verdict}}"**.

**Where the edge comes from.**

- Who trades: Sonnet's intramarginal seats traded in {{value:m4_trade_rate_senior}} of their slots and Haiku's in {{value:m4_trade_rate_junior}}.
- At what price: in the {{value:m4_cross_trades}} Sonnet-Haiku trades, Sonnet's price edge over P* averaged ${{value:m4_price_edge}}.
- On the same seats, intramarginal ranks earned ${{value:same_intramarginal_m4_sonnet_profit}} per session as Sonnet, ${{value:same_intramarginal_m4_haiku_profit}} as Haiku in M4, and ${{value:same_intramarginal_m2_profit}} in all-Haiku M2.

**Efficiency.** Mixed markets reached {{value:m4_efficiency_pct}}% efficiency (t-interval {{value:m4_eff_t_lo}}-{{value:m4_eff_t_hi}}), against M2's {{value:m2_efficiency_pct}}% ({{value:m2_eff_t_lo}}-{{value:m2_eff_t_hi}}). The point estimate misses the prediction that mixed markets would not beat M2, but the intervals overlap, and no ranking is claimed.

**Reply format.** Sonnet's replies were clean: 0 unparsed, 0 truncated and 0 rejected orders in 1,037 turns. Each Sonnet turn cost about $0.0011, with the prefix cached.

### 4.4 M3: all-Sonnet markets

**Results** (2 sessions, against M2's 4):

- {{value:m3_trades_per_period}} trades per period against M2's {{value:m2_trades_per_period}}. The difference is all extramarginal trades ({{value:m3_extramarginal_per_period}} against {{value:m2_extramarginal_per_period}} per period); intramarginal trades are {{value:m3_intramarginal_per_period}} against {{value:m2_intramarginal_per_period}}. So "fewer trades" here is Sonnet avoiding bad trades, not Sonnet waiting.
- {{value:m3_efficiency_pct}}% efficiency, {{value:m3_eff_diff}} points from M2. The session-resampled interval is {{value:m3_eff_diff_lo}} to {{value:m3_eff_diff_hi}}, the pooled t-interval {{value:m3_eff_diff_t_lo}} to {{value:m3_eff_diff_t_hi}}. A 7-point drop is not ruled out, and neither is a gain. No efficiency ranking between the conditions is claimed.
- The waiting measures are too thin to read:
    - the late PASS share ({{value:m3_late_pass_share}} against {{value:m2_late_pass_share}}) rests on 12 M3 turns in 4 of 10 periods;
    - the final spread exists in only 7 of 10 M3 periods, and is narrower than M2's (${{value:m3_final_spread}} against ${{value:m2_final_spread}}).
- **Verdict.** The preregistered "holds" needs at least a 7-point drop in efficiency and fewer trades. So MT2 is **not shown** at n = 2 against 4. It is not refuted either.

**Other observations.**

- Sonnet markets have the lowest price dispersion of the LLM conditions: alpha {{value:m3_alpha_first}} in period 1 and {{value:m3_alpha_last}} in period 5.
- Their prices still sit below P*, and $1.85 is their most common trade price ({{value:m3_share_at_185}}% of trades).
- One period of session 21 fell to 66.7%. An extramarginal buyer took a $0.03 profit early in the last period, and two high-value buyers, anchored on the earlier mean price, never met a seller again. It is a single-period event.
