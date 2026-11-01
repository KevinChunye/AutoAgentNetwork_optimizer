# Scale-up roadmap (session W1, 2026-10-27)

From the W1 brief (2026-10-27). Each item says what to do, why the
evidence so far asks for it (with the file that shows it), and what decides when it is done. Plan targets (2,000+ items,
8+ task families, k >= 5 repeats, the Gemini credit, the batch discount) are Kevin's; nothing here is a result.

## 1. Robustness: more items, more task families, a time split

**What.**
- Grow from about 500 items per study (the anchor: 533) to 2,000+ across 8+ task families, including agentic ones:
  SWE-bench Verified or SWE-bench Live subsets, Terminal-Bench, tau-bench.
- A time-split replication wave on next month's items (items published after every model's cutoff and after the
  design is frozen).
- Random-effects pooling across tasks as the default read, so a claim is about the population of task families, not
  one benchmark.
- k >= 5 repeats wherever call noise matters (votes, self-checks, the vote rule).

**Why.**
- The anchor's AH2 effect sits mainly in word sorting (auditor post-read, research/v4/handback_e5.md); a claim about
  "cheap models" needs many families.
- P8 (research/v4/atlas/extend.md): the all-wrong tail of 5-system sets is unresolved on MathArena because the test
  halves hold 15-26 problems. The tail is where width fails, so it needs hundreds of items per family.
- P2 and P3 pool 19 and 10 public pairs with between-pair variance; random effects are already the right read.
- P1: votes of 2 calls cannot gain; gains show from 3 calls and the vote rule overstates them by 1-2 points. Five
  repeats separate call luck from item difficulty (L3 dispersion in autoagentnet/atlas/factor.py).
- arXiv 2606.27288 shows that answer format moves the all-wrong rate (free response vs multiple choice). The families
  must span formats, and the paper must not pool across them without saying so.

**Done when.** A preregistered replication of AH2 (depth before width) and of the vote rule on mixed panels (P7's
design) passes on the time-split wave, pooled over 8+ families, with power >= 0.80 from a simulation run before
sealing.

## 2. Systems: a third vendor, the open-weight testbed, a larger Atlas

**What.**
- A third vendor through the sponsored Gemini credit (about $1k), used once, after the design is frozen, for the final
  replication. Not for exploration.
- The open-weight testbed (session T1): the Lightning pilot, then stage 1 (research/v4/testbed/RUN_GPU.md), then larger
  GPUs for 27B-class models.
- The public Atlas extended with HELM per-instance results, Open LLM Leaderboard details and SWE-bench trajectories
  (step-level signals for verification).

**Why.**
- Two vendors leave the vendor-against-reasoning confound open (AH1, exploratory; the Sol-Sonnet gap was not closed
  by Sonnet's effort step).
- The testbed is the only place where precision, size and thinking budget are varied on one model family at measured
  cost, with execution-based checks on code.
- HELM and the Open LLM Leaderboard add hundreds of systems on multiple-choice items, the format where shared failure
  should be lowest; SWE-bench trajectories turn the step-count signal (median AUROC 0.68, F18) into richer cheap
  signals.

**Done when.** The frozen design runs once on Gemini within its credit; the testbed's stage 1 is read under its
prereg; the Atlas has a multiple-choice source and a trajectory-level verification signal.

## 3. Cost: batch discounts, caching, measured token limits

**What.**
- 50% batch discounts: Anthropic Message Batches (confirmed on its pricing page 2026-10-27); OpenAI Batch API (verify
  before use). Batch prices need new rows in configs/pricing.yaml; Kevin edits that file.
- Prompt caching of shared prefixes (task and upstream text before any agent-specific text).
- max_tokens set from measured usage per arm (the anchor's truncation stops came from limits set before measurement).

**Why.** Every comparison in the project is at measured dollars. Batch and cache prices change which arm is cheapest,
so they change depth-against-width decisions (P3's nearest-dollar k), not only the bill. Output limits set before
measurement stopped two anchor runs on truncation (audits 73 and 76), and unparsed answers stopped two more (audits 83
and 88).

**Done when.** The price table carries batch rows, the governor books batch calls at batch prices, and a replay of the
anchor at batch prices shows which AH2 comparisons move.

## 4. Application: a budget allocator and a runtime router

**What.**
- **Budget allocator.** Inputs: a 30-50 item pilot of the candidate systems and a price table. Output: the depth,
  width and verification mix with predicted accuracy, cost and uncertainty. Built from the factor model:
  - the pilot fits abilities and slopes against Atlas difficulties;
  - the vote rule ranks where width pays (P1: it overstates gains by one to two points and its 3-vote level error is
    larger than zero-gain's) and predicts mixed weak panels without bias (P7); it needs a calibration step before it
    prices width;
  - the depth shift (P2) prices one reasoning step where the step is a cheap model's first (AH2); beyond that, CD2
    (session E6) decides;
  - the selection map (P4) and measured judge efficiency (P5) price verification;
  - a bootstrap over pilot items gives the uncertainty.
- **Runtime router.** Thresholds on cheap signals (self-check, execution, internal signals for open models), with risk
  control by Learn-then-Test, so the escalation rate meets a stated error bound on held-out items.
- **Targets.**
  - coding agents: cost per resolved issue (SWE-bench's 10x price gap for one point, F18);
  - evaluation-cost reduction: predict a benchmark score from few items, with the factor model's held-out item
    predictions;
  - forecasting desks: F8 and F9 show the market price is hard to beat.

**Why.** The Atlas results only matter if they change a purchase:
- the price frontier (A7) already shows cheap systems near the top;
- P5 shows that verification over cheap sets rarely beats the top system at its dollars.

**Done when.** The allocator, fitted on a 50-item pilot, predicts held-out accuracy of the recommended mix within its
stated interval on the time-split wave, and the router's escalation meets its risk bound.

## 5. Process

**What.**
- Keep preregistration and single reads for confirmatory work.
- Replace per-run audits in exploratory phases with automated verify-mode reproduction: a script re-derives every
  number of a run from its committed files and fails on any difference.
- The auditor reads designs, stops and conclusions.

**Why.**
- The project ran 101 audits (through W1-1) for $66 of API spend (research/audit_log.md). Most exploratory audits checked
  bookkeeping that code can check.
- scripts/build_numbers.py already regenerates every number of the paper and the record from committed files; verify
  mode extends that to runs.

**Done when.** Every exploratory run ends with a passing reproduction and no audit, and every confirmatory read still
gets a preregistration, a single read and an audit.

## Order

1. The batch and cache price rows (Kevin).
2. The testbed pilot (Lightning Studio).
3. The allocator, built at $0 on the Atlas plus the anchor.
4. The 8-family design, its prereg and power.
5. The time-split wave.
6. The Gemini replication once the design is frozen.
