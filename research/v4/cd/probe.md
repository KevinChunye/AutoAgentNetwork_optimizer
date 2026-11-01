# Study CD: the cost probe (session E6, section 4.2)

Written before any CD call. The study's question and tests are in analysis/cd_read.py (docstring); the full prereg
(research/v4/cd/prereg.md) follows this probe and comes before any main call (brief 4.4: "committed before the first
paid call beyond the probe").

## What the probe measures

Per arm and family: output tokens and thinking tokens per call (mean, 90th and 99th percentile, maximum), dollars per
call as billed, the share of calls cut by the ceiling, the share unparsed, and seconds per call. No accuracy is computed
on probe items, and none is looked at: the probe's calls.csv is read only through the cost and token columns
(`analysis/cd_probe.py`).

## Items

The 10 probe items of each family (research/v4/cd/sealed/{bbeh,math,code}_probe.txt; MANIFEST.md). They are not CD's
test items: BBEH probe items were called by earlier pilot runs, math probe items are 10 of arxivmath-0426, code probe
items are 10 of the 25 oldest release_v6 problems.

## Arms and ceilings

Every arm once (scripts/make_cd_configs.py): Haiku 5.5 thinking off and effort low, medium, high, xhigh, max; Sonnet
5.5 thinking off (thinking type between_tools, as E5) and effort low ... max; Opus 5.5 at medium and max (tier B); Sol
low, Sol medium and Luna low (OpenAI bridge). Effort levels as the Claude API docs list them (checked 2026-10-27): low,
medium, high, xhigh, max for Haiku 5.5 and Sonnet 5.5; thinking can be turned off only at effort high or below; Opus
5.5 cannot turn it off. Ceilings (audit 98): 8,192 with thinking off; every Haiku thinking arm 65,536 (E5's Haiku
low reached 36,864 on math); Sonnet and Opus 16,384 at low, 32,768 at medium and high, 32,768 at xhigh and max (65,536
on math and code); OpenAI 32,768. Each is at or under the model's documented maximum output (Claude 5.5 models
128,000; OpenAI's limits are not recorded in the repo, so OpenAI stays at the 32,768 the project has used).
Anthropic streams above 16,000; OpenAI uses background mode above 8,192 (D5).

## Order and stop (cost only)

1. Anthropic first (the credit expires on November 1): Haiku, then Sonnet, each family's items 1-3 first (stage 1;
   scripts/run_cd.py cuts slices exactly at item 3). Stage 2 (items 4-10), by number (audit 98): each cell (arm x
   family) is projected at 7 x its stage-1 mean dollars per call, and cells are taken in ascending projected cost while
   the probe's total (stage 1 spent plus the taken cells) stays at or under $6 (analysis/cd_probe.py stage2_cells);
   the other cells stay at 3 items. Taken cells run in configs with only those arms.
2. Opus is probed before tier B only (it serves tier B's sizing), under the same rule with its own $3.
3. OpenAI last, after the Anthropic work (audit 97): its first background-mode call is a 1-2 item slice whose usage,
   stop_reason and cost are checked in calls.csv before the rest. Every BackgroundFailed adds that call's worst case to
   the allowance for unledgered attempts.

The per-source stops (unparsed, truncation, cost) need 20 calls (min_calls) and so cannot fire on the probe's 10;
what binds is the $4 run cap per slice, the governor and the CD guard. Every slice goes through scripts/run_cd.py: `aan check`, the run cap ($4 worst case per slice), the CD guard
(Anthropic $52, OpenAI $10: the evidence phase's shared room of $64.13, audit 97), and no Anthropic call after
October 31 (UTC).

## What follows from it

- Each main arm's ceiling: the probe's 99th percentile of output tokens x 1.5, rounded up to a multiple of 1,024, at
  least 4,096 (a call cut at the probe's ceiling counts at the ceiling). Any main arm above 2% truncation stops for an
  audit.
- Guards (dollars per call for the cost stop): the probe's mean x 1.5 per arm and family.
- Tier A's projected cost from the measured means, against $40; the number of items, the reserves added (in their
  sealed order) and the arms that run on a subset are set in the prereg by a rule on these costs alone.
- Tier B sized to the room left after tier A and the OpenAI bridge.
