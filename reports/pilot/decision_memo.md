# Decision memo: AutoAgentNetwork pilot, protocol v2 (sessions 1 to 4, 2026-10-18 to 2026-10-19)

**Status.** The pilot is finished. Session 4 had working keys, ran every pre-registered step through P4, and stopped before P4b on audit 25's verdict.

- **Spend:** **$6.71** of the $20 pilot cap (Anthropic $6.7029, OpenAI $0.0069). No run exceeded 1.5× its estimate; actual spend was 0.07–0.47× the governor's worst case.
- **Hand-back reason:** the auditor said STOP on further paid work, because the premise did not hold on fresh items.

Numbers come from `reports/pilot/tables/*.csv`, written by `python -m analysis.build_report`; the full report is `reports/pilot/report.pdf`.

## What the pilot found (BBEH, four tasks; Haiku 5.5 worker; 95% paired bootstrap CIs)

| | Gate items (20–59, 100–119; n=60) | Held-out (60–99; n=40) | Pooled |
|---|---|---|---|
| dense (19 Haiku calls), accuracy | 65.0% | 60.0% | 63% (n=100) |
| dense − single Haiku | **+21.7 (+6.7 to +36.7)** | **+2.5 (−12.5 to +17.5)** | +14 (+3 to +25) |
| dense − vote over 6 proposers | +20.0 (+8.3 to +31.7) | +7.5 (−7.5 to +22.5) | +15 (+6 to +24) |
| single Sonnet − dense | +5.0 (20–59) | +12.5 (−5 to +30) | +8.75 (−6.25 to +22.5), n=80 |
| cost per task | dense $0.0111 · Sonnet $0.0140 · single $0.0008 | dense $0.0118 · Sonnet $0.0147 | |

- **The gate passed** (rule 11 under the automatic grade, the blind hand grade and the fixed grader). The gain came from critique and refinement, not voting:
  - stage accuracy: propose 45%, critique 58%, refine 61%, aggregate 63%;
  - vote6 added nothing over the average proposer.
- **The gate is biased upward** by how it was reached:
  - three candidate task sets, of which Omni-MATH was too easy (single 65–80%);
  - a P2b probe at +50;
  - a gate widening triggered only when the result was ambiguous.
- **On the held-out half, the team's edge over one Haiku did not replicate.**
- **One Sonnet call per task matched or beat the team at 1.25× its cost.** Over 80 items Sonnet leads by +8.75 points (CI includes 0).
- **H5 not met.** The search-chosen consensus policy (first 3 proposers agree, else dense) came within 2.5 points of dense but at 75% of its cost, against the 50% limit. `judge_cascade` cannot meet the limit: its routing on cached proposers puts its cost floor at 55% of dense, so it was not run.
- **Static pruning:**
  - the search-chosen joint pick 3-3-1 scored 55% at 46% of dense's cost on held-out items;
  - that beats vote6 (52.5%) and matched random pruning (+3.9, CI −4.7 to +12.1), the rule 25 trigger, as point estimates;
  - but it sits below single Haiku (57.5%) and single Sonnet (72.5%). Under H4, no pruning gain is claimed.
- **Production function** (all 80 grid items), per doubling of a stage:
  - propose +3.1 (+0.3 to +5.8), critique +1.3, refine +1.4; no interaction resolved;
  - six proposers act like 1.9 independent ones (H6 holds).

**What it took to measure anything** (all decided by Kevin or pre-registered, then audited; 20 audits in session 4):
- **Token caps.** The Haiku/Sonnet 5.5 tokenizer gives about 2.2 characters per token, so caps went from 300–800 to 3200.
- **Thinking off on Sonnet.** Sonnet 5.5 rejects `thinking: disabled`, so `sonnet_nothink` sends `between_tools`.
- **Graders.**
  - Math: plain-text and Unicode answers, "find all" formats.
  - BBEH: Unicode minus, thousands separators, `<...>` answers (the format BBEH's prompt shows), dyck "completion" tails.
  - Every grader fix came with tests; golds never changed.
- **New process rules.** A per-stage truncation stop over every config's calls, slices in separate result folders, and a blind hand grade for every gate decision.

## Options (worst case = the governor's estimator at the 3200 caps, ×1.15; projected = pilot's measured cost per task)

BBEH's four kept tasks have 749 items. Positions 0–119 are used, and **629 are untouched (120–748)**, so B and C cannot both get fresh items.

| | Option | What it would show | Worst case | Projected actual | `configs/budget.yaml` |
|---|---|---|---|---|---|
| **0** | **Stop here** (recommended) | — | $0 | $0 | none |
| B-core | dense, single Haiku and one Sonnet call on 600 fresh BBEH items (120–719); vote6, every consensus policy and vote-or-Sonnet come free from the same runs | H4 at a paired MDE of about 6 points: is the team better than one Haiku, and is one Sonnet better than the team? | **$76.22** (dense $51.34, Sonnet $23.70, single $1.18) | **about $16.4** (600 × [$0.0118 + $0.0147 + $0.0008]) | below |
| B | B-core plus P4's two picks, 3-3-1-1 and 6-6-1-1 | adds H1 (joint against stage-by-stage) and the static-pruning trigger at power | **$88.51** (picks +$12.29) | about $19.5 | below, total 40 |
| B + cascade | B plus `judge_cascade` | H5 for the cascade; it cannot meet rule 24 on the pilot's routing | $163.63 | about $25 | not recommended |
| C | the 1/3/6 grid at n = 200 (production function) | H2 and H6 with CIs about 0.45× the pilot's width | $89.91 | about $12 | not recommended: overlaps B's items, and the pilot finds width beyond one critic flat |

**Why the projected cost is so far below the worst case.** The governor reserves every agent's full 3200-token cap and every prompt at the cache-write rate. The pilot's agents wrote 400–1,250 tokens on average, and shared prefixes were cache reads.

**How to set the phase total.** `total_usd` is a lifetime limit on summed spend across both accounts, so it includes the pilot's $6.71. The governor checks (spent + reserved + the next call's worst case) × 1.15 against it, and each run is capped at $4. Two choices:
- **Projected (recommended if B-core is funded):** 6.71 + 16.4 × 1.25 margin + one run's worst-case headroom ($4.6), about **$32**, rounded to **$35**. If spend runs higher than projected, the governor stops the run at $35 and the session hands back. Nothing is overspent.
- **Conservative:** 6.71 + the full worst case 76.22, about **$85**. Anthropic's lifetime spend would then stay under its $100 cap.

The exact edit for B-core, keeping the pilot entry:

```yaml
phase: confirm1
phases:
  pilot:
    total_usd: 20
    max_run_usd: 4
  confirm1:
    total_usd: 35      # projected; 85 for the full worst case; 40 for option B with the picks
    max_run_usd: 4
```

B-core runs in about 15 runs of 40 items each:
- dense at $2.05 worst case per 20 items, so 20-item runs;
- Sonnet 40 per run;
- single 600 in one run.

At the projected cost, it takes about 1.5 hours of wall-clock.

## Recommendation

**Stop the pruning line (option 0).** The question the pilot was built for — which agents of a team can be pruned — needs a team that clearly beats its own parts. On BBEH, the 19-call Haiku team did not beat one Haiku on fresh items, and one Sonnet call matched it for 1.25× the cost. The remaining Anthropic credit (it expires 2026-11-01) is better spent elsewhere.

**Fund B-core only if** a power-level answer to "team vs one Haiku vs one senior" on BBEH is worth about $16 (up to $35 at the cap). It is the cheapest decisive test of H4. P4's picks and the cascade are not worth funding.

## What I need from Kevin

1. **Confirm the session-4 STEERING entries on the PR.** They record your choices among options the session put to you:
   - token caps (A2, then critique 1600, then uniform 3200);
   - the unparsed limit for Omni d61;
   - the BBEH truncation and cost stops;
   - negative P2 gap to P3 futility;
   - Sonnet and cascade cost stops;
   - go to P4, and the P4 audit cadence;
   - the grader fix, the hand/fixed headline and the held-out Sonnet run.
2. **Decide:** stop (option 0), or fund B-core with the `confirm1` entry above.
3. **Optional, not blocking:** the price table has one Haiku row, but Haiku 5.5 costs 5× for prompts over 100,000 tokens. Pilot prompts stayed under 40,000 tokens.
