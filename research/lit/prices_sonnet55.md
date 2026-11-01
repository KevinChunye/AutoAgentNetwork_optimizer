# Anthropic list prices: Sonnet 5.5, Haiku 5.5, Opus 5.5

Fetch date: 2026-10-18. Scope: standard (non-batch) Claude API, global routing, default context.

### Pricing (Anthropic Claude Platform docs, page fetched 2026-10-18)
- Link: https://platform.claude.com/docs/en/about-claude/pricing (opened directly; no redirect, the page's own front matter reports the same URL)
- What it does: Official list-price table for every Claude model, plus the cache multipliers, batch, data-residency, fast-mode and long-context sections.
- How it was read: through the WebFetch tool, which returns the page converted to markdown. The table text below is copied from that markdown. I did not view the rendered HTML, and I did not open claude.com/pricing (the page points to it as "the most current pricing information").
- Key numbers (quoted table rows; columns are `Base input tokens | 5m cache writes | 1h cache writes | Cache hits and refreshes | Output tokens`):
  - `| Claude Sonnet 5.5 | $2 / MTok | $2.50 / MTok | $4 / MTok | $0.10 / MTok<sup>2</sup> | $10 / MTok |`
  - `| Claude Haiku 5.5 (for prompts up to 100,000 tokens) | $0.10 / MTok | $0.125 / MTok | $0.20 / MTok | $0.01 / MTok | $0.50 / MTok |`
  - `| Claude Haiku 5.5 (for prompts over 100,000 tokens) | $0.50 / MTok | $0.625 / MTok | $1 / MTok | $0.05 / MTok | $2.50 / MTok |`
  - `| Claude Opus 5.5 | $4 / MTok | $5 / MTok | $8 / MTok | $0.20 / MTok<sup>2</sup> | $20 / MTok |`
  - Footnote 2: "Cache hits and refreshes on Claude Opus 5.5 and Claude Sonnet 5.5 are priced at 0.05x the base input price." Other models "use the standard 0.1x multiplier."
  - Cache section: "On Claude Opus 5.5 and Claude Sonnet 5.5, a cache hit costs 5% of the standard input price ($0.20 USD per million tokens on Claude Opus 5.5, $0.10 USD on Claude Sonnet 5.5)." 5-minute write is "1.25x base input price".
  - Neighbouring row, easy to confuse with ours: `| Claude Sonnet 5 | $2 / MTok | $2.50 / MTok | $4 / MTok | $0.20 / MTok | $10 / MTok |`. Sonnet 5 (not 5.5) reads the cache at $0.20, twice the Sonnet 5.5 rate.
- Long-context and tier behaviour for Sonnet 5.5 (quoted): "Claude 4.6 and later models (except Claude Haiku 5.5) ... include the full 1M token context window at standard pricing. (A 900k-token request is billed at the same per-token rate as a 9k-token request.) Prompt caching and batch processing discounts apply at standard rates across the full context window."
  - So Sonnet 5.5 and Opus 5.5 have no long-context surcharge threshold and no price that varies with prompt length. The page lists no Sonnet 5.5 price tier other than standard vs batch vs US-only inference.
  - Haiku 5.5 is the exception: "Claude Haiku 5.5 is priced by prompt length: a request whose prompt is over 100,000 tokens pays higher prices. A request's prompt length counts all of its input tokens, including cache reads and cache writes. Each request is priced on its own: a request over the threshold pays the higher prices even when part of its prompt is a cache hit." The over-100k row is 5x the base input and output price.
  - Modifiers on the page that do not apply to our default runs: Batch API (Sonnet 5.5 `$1 / MTok` input, `$5 / MTok` output); US-only inference via `inference_geo` is a 1.1x multiplier on all categories ("Global routing (the default) uses standard pricing"); fast mode is listed only for Opus models (Opus 5.5 `$8` / `$40`), not Sonnet 5.5.
- Relevance to AutoAgentNetwork: cost (confirms the booked rates; adds one Haiku 5.5 risk, see "So what").
- Resources: public docs page, no code or data.
- Open questions it raises: Does any Haiku 5.5 request in our networks exceed 100,000 prompt tokens? The page counts cache reads and writes toward that length, so a long shared prefix plus many upstream answers is the case to check.

## Comparison with `configs/pricing.yaml` (USD per million tokens)

| Model | Column | Official (page) | Ours | Verdict |
|---|---|---|---|---|
| Sonnet 5.5 | input | 2.00 | 2.00 | equal |
| Sonnet 5.5 | cache write (5m) | 2.50 | 2.50 | equal |
| Sonnet 5.5 | cache read | 0.10 | 0.10 | equal |
| Sonnet 5.5 | output | 10.00 | 10.00 | equal |
| Haiku 5.5 (prompt <= 100k) | input | 0.10 | 0.10 | equal |
| Haiku 5.5 (prompt <= 100k) | cache write (5m) | 0.125 | 0.125 | equal |
| Haiku 5.5 (prompt <= 100k) | cache read | 0.01 | 0.01 | equal |
| Haiku 5.5 (prompt <= 100k) | output | 0.50 | 0.50 | equal |
| Opus 5.5 | input | 4.00 | 4.00 | equal |
| Opus 5.5 | cache write (5m) | 5.00 | 5.00 | equal |
| Opus 5.5 | cache read | 0.20 | 0.20 | equal |
| Opus 5.5 | output | 20.00 | 20.00 | equal |

No column is above or below ours. Everything above was read directly on the page; nothing in this table is inferred. The `pricing.yaml` values are from the file as read on 2026-10-18 (lines 11 to 13).

## So what

- `configs/pricing.yaml` needs no change for Sonnet 5.5 or Opus 5.5, and none for Haiku 5.5 at prompts up to 100,000 tokens. The "list prices as of 2026-10" comment holds.
- Haiku 5.5 has a second price row for prompts over 100,000 tokens: 0.50 / 0.625 / 0.05 / 2.50, which is 5x ours. Our file has one Haiku row, so any single Haiku request over the threshold would be under-counted 5x by the `SpendGovernor`. I did not edit `pricing.yaml` (only Kevin changes it). Two options for Kevin or the plan: (a) confirm in `aan estimate` that no planned Haiku request can reach 100,000 prompt tokens (shared prefix plus all upstream answers plus the task), or (b) add a prompt-length guard or a second price row in code. `research/plan.md` should state which.
- The cache-read discount differs by model (0.05x for Sonnet 5.5 and Opus 5.5, 0.1x for Haiku 5.5). A cache-aware cost model must take the multiplier per model rather than assume one 0.1x constant. This matters when a network mixes Haiku and Sonnet agents.
- Do not reuse the Sonnet 5 row for Sonnet 5.5: its cache read is $0.20, not $0.10.
- Not checked here: OpenAI prices (the yaml marks them UNVERIFIED), and whether our token counts match Anthropic's tokenizer.
