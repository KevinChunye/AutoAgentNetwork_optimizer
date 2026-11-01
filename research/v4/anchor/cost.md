# Anchor expected cost against K3 (110 BBEH items per task + 93 math)

Written by `python -m analysis.anchor_cost`; prices per call in its docstring table (measured or assumed, column prices). Expected cost only; each config's worst case comes from `aan estimate` before it runs.

| tier | arm | account | bbeh | math | calls | usd | prices |
|---|---|---|---|---|---|---|---|
| 1 | haiku_off | anthropic | 440 | 93 | 3 | 0.563 | measured |
| 1 | haiku_low | anthropic | 440 | 93 | 3 | 0.939 | measured (ceiling 6,144; the anchor's 12,288 adds only where it truncated) |
| 1 | haiku_high | anthropic | 440 | 93 | 3 | 3.714 | BBEH measured on 8 calls; math assumed: measured $0.0058 at 18,432 with 4 of 10 truncated, doubled ceiling |
| 1 | sonnet_off | anthropic | 440 | 93 | 1 | 3.636 | measured (e52) |
| 1 | sonnet_low | anthropic | 440 | 93 | 1 | 3.613 | measured (e52) |
| 1 second calls | sonnet_off | anthropic | 34 | 16 | 1 | 0.392 | measured (e52) |
| 1 second calls | sonnet_low | anthropic | 34 | 16 | 1 | 0.396 | measured (e52) |
| 1 | luna_none | openai | 440 | 93 | 3 | 0.188 | BBEH measured in Phase 1; math assumed |
| 1 | luna_low | openai | 440 | 93 | 3 | 0.591 | measured |
| 1 | luna_med | openai | 440 | 93 | 3 | 1.558 | assumed: 2.5x Luna low |
| 1 | sol_low | openai | 440 | 93 | 3 | 6.762 | measured |
| 1 | sol_med | openai | 440 | 93 | 1 | 5.680 | assumed: 2.5x Sol low |
| 2 | opus_low | anthropic | 68 | 32 | 1 | 1.612 | assumed: 2x Sonnet low (Opus list prices are 2x Sonnet's) |
| 2 | sonnet_high | anthropic | 41 | 19 | 1 | 1.416 | assumed: 3x Sonnet low |
| 2 | astra_low | openai | 68 | 32 | 1 | 3.018 | assumed: 5x Sol low (Astra list prices are 5x Sol's) |
| verification | haiku_low | anthropic | 440 | 93 | 1 | 0.313 | measured (ceiling 6,144; the anchor's 12,288 adds only where it truncated) |
| verification | sol_low | openai | 440 | 93 | 1 | 2.254 | measured |
| verification | sol_low | openai | 880 | 186 | 1 | 4.508 | measured |
| verification | haiku_high | anthropic | 440 | 93 | 1 | 1.238 | BBEH measured on 8 calls; math assumed: measured $0.0058 at 18,432 with 4 of 10 truncated, doubled ceiling |

| account | tier | usd |
|---|---|---|
| anthropic | 1 | 12.47 |
| anthropic | 1 second calls | 0.79 |
| anthropic | 2 | 3.03 |
| anthropic | verification | 1.55 |
| openai | 1 | 14.78 |
| openai | 2 | 3.02 |
| openai | verification | 6.76 |

Totals: Anthropic $17.83 (K3 $48: fits); OpenAI $24.56 (K3 $34: fits). OpenAI tier 1 $14.78: Astra allowed by K3 (needs under $20).
