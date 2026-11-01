# Evidence plan: budget, run schedule and drop orders

Written by `python -m analysis.evidence_budget`. Worst cases assume every call uses its full max_tokens at the dearest input rate; each slice's worst case is at most $3.48 ($4 run cap / 1.15). A slice "o+n" is `--task-offset o --task-limit n`.

## The plan's expected spend (list prices, before the probe; kept for comparison)

| step | Anthropic $ | OpenAI $ |
|---|---|---|
| 1.1 probes | 0.55 | 0.79 |
| 1.3 BBEH panel | 6.82 | 8.70 |
| 1.4 ForecastBench panel | 3.52 | 4.53 |
| 2.2 prompt variety | 0.64 | 0.65 |
| 2.2b aggregator | 0.36 | 0.36 |
| 2.3 more reasoning | 1.10 | 1.14 |
| 3C pruning lockbox (200 BBEH + 200 ForecastBench) | 6.08 | 7.56 |
| 2.4 Opus on BBEH (150 items) | 4.27 | 0.00 |
| **total** | **23.34** | **23.73** |

Dropped or deferred by Kevin in session E3: step 1.4b (243 extra market questions, about $2.3 / $2.9), MathArena 2.5 (deferred to Phase 4 with reasoning on, about $4.24 / $6.34) and Opus on ForecastBench (about $2.25).

Caps (the budget rules on main): active phase `evidence`, total $150, run $4, account caps Anthropic $100, OpenAI $50, all lifetime, compared after x1.15. Spent so far $17.68; room left for new estimated spend: Anthropic $69.40, OpenAI $43.35. Expected new spend still to come at the probe's measured costs (2.3 at the plan's figure): Anthropic $19.14, OpenAI $7.09, which leaves Anthropic $50.3, OpenAI $36.3 of headroom.

## Run schedule

Expected $ is the config's calls at the probe's measured dollars per call (blank: a ref not probed).

| config | vendor | items | runs | expected $ | worst case $ | slices |
|---|---|---|---|---|---|---|
| e11_probe_bbeh_anth | anthropic | 10 | 1 | 0.17 | 0.53 | 0+10 |
| e11_probe_bbeh_open | openai | 10 | 1 | 0.08 | 1.06 | 0+10 |
| e11_probe_forecast_anth | anthropic | 10 | 1 | 0.04 | 0.17 | 0+10 |
| e11_probe_forecast_open | openai | 10 | 1 | 0.02 | 0.82 | 0+10 |
| e11_probe_math_anth | anthropic | 10 | 1 |  | 1.33 | 0+10 |
| e11_probe_math_open | openai | 10 | 1 |  | 1.73 | 0+10 |
| e11b_probe_opus_anth | anthropic | 10 | 1 | 0.23 | 0.85 | 0+10 |
| e13_bbeh_anth | anthropic | 300 | 6 | 6.64 | 20.06 | 0+49, 49+53, 102+52, 154+53, 207+50, 257+43 |
| e13_bbeh_open | openai | 300 | 11 | 2.73 | 36.06 | 0+26, 26+28, 54+31, 85+29, 114+27, 141+30, 171+29, 200+26, 226+30, 256+27, 283+17 |
| e14_forecast_anth | anthropic | 300 | 3 | 1.87 | 7.8 | 0+150, 150+120, 270+30 |
| e14_forecast_open | openai | 300 | 10 | 0.96 | 33.8 | 0+40, 40+40, 80+34, 114+29, 143+24, 167+28, 195+28, 223+28, 251+28, 279+21 |
| e22_persona_bbeh_anth | anthropic | 200 | 1 | 0.48 | 1.27 | 0+200 |
| e22_persona_bbeh_open | openai | 200 | 1 | 0.10 | 1.27 | 0+200 |
| e22_persona_forecast_anth | anthropic | 200 | 1 | 0.11 | 0.5 | 0+200 |
| e22_persona_forecast_open | openai | 200 | 1 | 0.05 | 0.5 | 0+200 |
| e22b_aggregator_bbeh_anth | anthropic | 200 | 1 | 0.16 | 0.43 | 0+200 |
| e22b_aggregator_bbeh_open | openai | 200 | 1 | 0.03 | 0.43 | 0+200 |
| e22b_aggregator_forecast_anth | anthropic | 200 | 1 | 0.04 | 0.17 | 0+200 |
| e22b_aggregator_forecast_open | openai | 200 | 1 | 0.02 | 0.17 | 0+200 |
| e23_reasoning_bbeh_anth | anthropic | 200 | 1 |  | 1.65 | 0+200 |
| e23_reasoning_bbeh_open | openai | 200 | 1 |  | 1.65 | 0+200 |
| e23_reasoning_forecast_anth | anthropic | 200 | 1 |  | 1.63 | 0+200 |
| e23_reasoning_forecast_open | openai | 200 | 1 |  | 1.63 | 0+200 |
| e24_opus_bbeh_anth | anthropic | 150 | 4 | 3.42 | 12.68 | 0+41, 41+41, 82+41, 123+27 |
| e31_lockbox_bbeh_anth | anthropic | 200 | 4 | 4.00 | 11.84 | 0+58, 58+58, 116+58, 174+26 |
| e31_lockbox_bbeh_open | openai | 200 | 6 | 1.51 | 19.84 | 0+35, 35+34, 69+35, 104+35, 139+35, 174+26 |
| e31_lockbox_forecast_anth | anthropic | 200 | 2 | 1.09 | 4.66 | 0+149, 149+51 |
| e31_lockbox_forecast_open | openai | 200 | 6 | 0.55 | 17.66 | 0+39, 39+39, 78+39, 117+39, 156+39, 195+5 |

## Drop orders (session E3; regenerated after Kevin's D1-D5, to be confirmed by Kevin)

They apply if a vendor projects past $27 of new spend after the probe (1.1), or if the Oct 31 Anthropic deadline is at
risk. Apply in this order, one step at a time, re-estimating after each. The rule that generated them: drop the work
scheduled last first (Kevin's D5 order), and never the confirmatory parts (the Phase 1 panel, which carries H5-H7).
Since session E4 the Phase 3C lockbox carries no confirmatory test (C1 and C2 are exploratory by power; Kevin's
K4 collects it blind), so it is the first candidate to drop if a vendor runs short.

- **Anthropic:** (1) Opus on BBEH cut to 100 items (`e24_opus_bbeh_anth --task-limit 100`, saving about $1.4);
  (2) Opus on BBEH dropped (about $2.8 more); (3) the Haiku half of 2.3 (`e23_reasoning_*_anth`, $1.10);
  (4) the Haiku aggregator 2.2b (`e22b_aggregator_*_anth`, $0.36).
- **OpenAI:** (1) Astra (2.4b, gated, not run before G2); (2) the Luna half of 2.3 (`e23_reasoning_*_open`, $1.14);
  (3) the Luna aggregator 2.2b (`e22b_aggregator_*_open`, $0.36).
- The persona arms (2.2) stay: Phase 3 searches over them and the lockbox repeats them.
- **Astra** (2.4b) runs only if OpenAI new spend after the lockbox is at most $26, and only after G2.

Order of work (Kevin's D5): probes -> e13 BBEH -> e14 ForecastBench -> persona, aggregator and more-reasoning arms ->
Phase 3C lockbox -> Opus BBEH (Anthropic, by Oct 31); the same order for OpenAI by Nov 5. One paid run at a time.
