# API anchor: preregistration (session E5, step 5.4)

Written and committed before the anchor's first call. The tests are the code in `analysis/anchor_read.py`, frozen with
this file; power is in `research/v4/anchor/power.md`; the items and their hashes are in
`research/v4/anchor/sealed/MANIFEST.md`. Every config (`configs/experiments/v4/e51_*.yaml`) carries a prereg block
that points here.

## Question

On fresh, sealed items, how should a fixed budget be split between width (repeat calls of a model), depth (more
reasoning, or a stronger tier) and verification (self-checks, judges), for Anthropic and OpenAI models? And does the
Atlas factor model predict what a composition of calls will score?

## Items

- 440 BBEH items, 110 from each of linguini, nycc, word sorting and causal understanding (`sealed/bbeh_anchor.txt`).
  The tasks were chosen by the K2 scan's rule (`research/v4/anchor/scan_read.md`). They cover two of the six skill
  groups (language; knowledge and commonsense), and Sol low is near its ceiling on word sorting (audit 70).
- 93 arXivMath items (`research/v3/evidence/sealed/math_all.txt`), sealed in v3 and never called.
- Claims are limited to "these four BBEH tasks (prompts up to 8,000 characters) and these 93 arXivMath problems".
- Run order (audit 71): the BBEH items run interleaved across the four tasks (`sealed/bbeh_anchor_order.txt`, the
  same 440 ids), so every slice covers every task.
- Text-only rules dropped malformed linguini items and word-sorting items whose Thought 1 respells a list word
  (`scripts/seal_anchor.py`). 200 further items (50 per task) are reserved for the open-weight testbed (T1).

## Arms (configs e51_*)

Arms are named by effort. Claude 5.5 models reject budget_tokens. Ceilings (max_tokens) are generous, so truncation
is not part of an arm (audits 69-70). BBEH and math ceilings are given where they differ.

| tier | vendor | arm (ref) | calls per item | ceiling |
|---|---|---|---|---|
| 1 | Anthropic | Haiku off (haiku_nothink) | 3 | 4,000 |
| 1 | Anthropic | Haiku effort low (haiku_low) | 3 | 12,288 |
| 1 | Anthropic | Haiku effort high (haiku_high); on math in its own config (e51_haiku_high_math) | 3 | 18,432 / 36,864 |
| 1 | Anthropic | Sonnet off (sonnet_nothink: between_tools, no thinking on a direct prompt) | 1, plus a second call on 50 items | 4,000 |
| 1 | Anthropic | Sonnet effort low (sonnet_low) | 1, plus a second call on 50 items | 12,288 |
| 1 | OpenAI | Luna none, low, medium (luna_none, luna_low_ev, luna_med) | 3 each | 2,000 / 4,000; 6,144; 12,288 (math: 12,288 and 24,576 for low and medium, "Audit 81" below) |
| 1 | OpenAI | Sol low (sol61_low) | 3 | 6,144 (math: 12,288, "Audit 81") |
| 1 | OpenAI | Sol medium (sol61_med) | 1 | 12,288 (math: 24,576, "Audit 81") |
| 2 | Anthropic | Opus effort low (opus_nothink) on 100 items; Sonnet effort high (sonnet_high) on 60 | 1 | 12,288; 18,432 / 36,864 |
| 2 | OpenAI | Astra low (astra_low) on 100 items, only if OpenAI tier 1 costs under $20 (K3) | 1 | 12,288 |
| verification | Anthropic | Haiku effort low self-checks its own call 0; Haiku effort high judges the Luna-low pool (3 calls) | 1 | as the arm |
| verification | OpenAI | Sol low self-checks its own call 0; Sol low judges the union of the Haiku-off and Luna-low pools (6 calls) | 1 | 6,144 (math: 12,288, "Audit 81") |

- A judge sees the distinct candidate answers of its pool, with no counts and no sources, and must pick one. A
  self-check returns a verdict and a confidence (`prompts.VERIFY_INSTRUCTION`; VERIFY_HASH).
- Grading uses parser v2 (anchor only). It accepts a bare last line of any shape, and strips a qualifier after a dash
  or semicolon, or a trailing parenthetical, from the answer and the gold alike. A hedge between two answers ("(H) or
  (A)") is kept whole and so graded wrong (audit 71). Format compliance is recorded apart (`format_ok`). Every gold of
  the four tasks grades right under v2.
- **Read-time parser v2.1 (deviation after audit 72, committed before any outcome was looked at):** the read regrades
  every arm's stored BBEH replies with v2.1, which adds to v2: one apostrophe mark (’ = '), a trailing parenthetical
  dropped before any split, and on closed-label tasks (causal understanding, nycc) a leading label before a comma,
  period or colon. Every gold still grades right under v2.1.
- Haiku effort high on math runs in its own config. If it stops on truncation (over 2%), its math cells are dropped,
  as the scan's math decision says: it runs no further math calls, AH3 leaves it out (a panel per test, below), and
  its BBEH cells stay.

## Confirmatory tests: Holm at 5% over AH2 and AH3

The tests are in `analysis/anchor_read.py`: one-sided item-bootstrap p-values, 2,000 draws, seed 0.

- **AH2: depth beats width at equal dollars.**
  - Haiku: one Haiku effort-low call minus the Haiku-off k-vote whose measured dollars per item are nearest to that
    call's (k in 1..3).
  - Luna: Luna low minus the Luna-none k-vote, chosen the same way.
  - Both differences must be above 0. p is the larger of the two one-sided p-values.
  - Stated plainly (audit 71): the scans' price ratios (Haiku effort low 1.84x Haiku off; Luna low 1.71x Luna none)
    make the nearest k equal to 2. A 2-vote with ties split equals one call in expectation, so AH2 then compares one
    deeper call with the shallower arm at about twice its dollars; it does not test a wider vote. The difference against
    the 3-vote (about 3x the dollars) is reported beside it, with an interval, and not tested.
  - Power 0.97 at this n.
- **AH3: compositional prediction.**
  - The item halves are cross-fitted (seed 0). On each fit half, L1 is fitted to call 0 of every generator arm.
  - On the other half, each item's difficulty posterior comes from call 0 of the other arms.
  - Each 3-call arm's 3-vote accuracy is predicted from its one-call success probability and its wrong-answer
    coincidence q, averaged over that posterior.
  - Two criteria must hold (paired item bootstrap; upper bounds one-sided at level 0.05/4):
    - level: the MAE over the 3-call arms of observed minus predicted 3-vote accuracy is at most 3 points, its upper
      bound at most 4;
    - gain (audit 71): the MAE of observed minus predicted vote gain (3-vote accuracy minus one-call accuracy) is at
      most 1.5 points, its upper bound at most 2. A predictor that ignores voting ("a vote equals one call") fails
      this one.
  - All four limits come from the noise floor that a true model leaves at 533 items (power.md: the 90th percentiles,
    rounded up). AH3 passes 0.80 of simulated anchors when the model is true, 0.47 with a per-arm item effect, and
    0.10 with item-level wrong-answer attractors plus that effect.

## Exploratory (demoted by power; reported with p, no Holm decision)

- **AH1: reasoning explains the vendor gap.**
  - R = (Sonnet effort low - Sonnet off) / (Sol low - Sonnet off) > 0.5; void if Sol low - Sonnet off < 5 points.
  - Power 0.00 at the e52 scan's accuracies (R about 0.35), so it is demoted by the e52 scan's decision.
- **AH4: verifier coupling.**
  - The cross-vendor judge's (Sol low over both pools) eta on items above the median difficulty is lower than on
    items at or below it.
  - Difficulty is the L1 difficulty fitted from the arms outside the pools.
  - Power 0.23.
- **Other descriptive reads, each with item-bootstrap intervals:**
  - The depth-versus-width picture per vendor and per task kind: accuracy against measured dollars per item, for every
    arm, every k-vote and Sol medium. Tier 2 is included where it ran.
  - Verification: each judge's eta and accuracy against the best single call and the plurality; the self-checks'
    AUROC and Murphy resolution (`evidence/calibration.py`).
  - Label-free accuracy by pooled Dawid-Skene, against the truth.
  - The anchor's systematic share and its all-wrong tail against L0, L1 and the copula, placed on the Atlas
    (`research/v4/atlas/atlas.md`).

## Predictions (written before any call)

- **P1:** AH2's Haiku difference is about +8 points at matched dollars, and its Luna difference is positive (the
  scans: Haiku effort low 40% vs Haiku off 32% on the mix).
- **P2:** AH3's level MAE is about 2 points and its gain MAE about 1 point.
- **P3:** AH1's R is about 0.35. Sonnet effort low barely reasons on these BBEH tasks; on math it doubles Sonnet off.
- **P4:** AH4: eta(easy) - eta(hard) > 0.
- **P5:** BBEH: Haiku effort low and Sonnet effort low are within 5 points of their "off" arms. Math: both are at
  least 15 points above them.
- **P6:** Sol medium is at most 5 points above Sol low on BBEH.

## Kill rules and process

- **Per config, over every call it has made so far** (`stop_over_config`, audit 71): stop if a source leaves over 5%
  of its replies unparsed (math: over 30%, Kevin's Oct 19 allowance for abstentions; the scans saw up to 2 of 10), or
  truncates over 2% of its calls. A run that stops on truncation goes to an audit before any further call. Also stop
  if a source costs over 2x its guard per call (BBEH guards: the dearest of the four tasks in the scans), or if the
  governor projects a vendor past its cap.
- **Running guard against K3** (`scripts/run_anchor.py`): no slice starts if the anchor's spend so far for its vendor
  plus the slice's expected cost would pass $48 (Anthropic) or $34 (OpenAI).
- **One run at a time.** Each config runs in slices whose worst case fits the $4 run cap (`scripts/anchor_slices.py`).
  After each config (all its slices): read status.json, confirm state/ was pushed, and call the auditor. That is one
  audit per config, not per slice: a logged deviation that audit 71 accepted once the stop rules count all of a
  config's calls.
- **Order** (audit 71: Luna before Sol, because the Anthropic verification needs the Luna pool before Oct 31):
  1. Anthropic tier 1: Haiku on BBEH, Haiku on math, Haiku effort high on math, Sonnet on BBEH, Sonnet on math.
  2. OpenAI: Luna on BBEH and math.
  3. Anthropic verification: the Haiku self-check, and Haiku effort high judging the Luna pool. Every Anthropic call is
     to finish by Oct 31, when the credit expires.
  4. OpenAI: Sol on BBEH and math, then the OpenAI verification.
  5. Tier 2 if K3 leaves room: Anthropic before Oct 31, and Astra only under K3's gate.
- **Drop order** if a re-estimate breaks K3 (5.6): Sonnet effort high, Opus, Astra, Luna medium, then the second-call
  subsets.

## Decisions

- **AH2 passes** (both vendors): on these items, at matched measured dollars, one deeper call of a cheap model beats a
  vote of its shallower calls. Budget rules in the paper put depth before width for cheap models.
- **AH2 fails:** the paper says depth was not shown to beat width at equal dollars here, and reports both differences
  with their intervals.
- **AH3 passes:** at this scale the factor model predicts a single arm's 3-vote accuracy and its gain over one call.
  The Atlas may use it to price same-arm votes before buying them. Mixed panels (calls of different arms) are not
  tested here and stay exploratory (audit 71).
- **AH3 fails:** compositions must be measured, not predicted. The paper reports the error and where it comes from.
- **Exploratory results** (AH1, AH4, the rest) are reported as such and start no claim without a new preregistered
  test on new items.

## Deviations during the runs (each committed before the next call, decided on process facts only)

- **Audit 72, parser v2.1 at read time** (see Arms).
- **Audit 73, Haiku effort low on math (option d).** e51_haiku_math stopped after 25 items: Haiku effort low truncated
  13 of 75 calls at 12,288 (on 5 items, with almost no visible text), against the 2% stop. Haiku off continues alone
  (e51_haiku_off_math; its first 25 items come from the cache). Haiku effort low reruns on all 93 math items at 36,864
  (e51_haiku_low_math36; 2% stop; guard $0.0025). If that run completes on every item, its calls are Haiku effort
  low's math cells. If it stops on truncation, the pre-declared fallback (a) applies: Haiku effort low runs at 12,288
  with a 30% truncation stop (e51_haiku_low_math12), truncation counts as wrong and is reported per task, and the
  36,864 calls stay out of AH2 and AH3. The read picks the run by this rule alone (anchor_read.haiku_low_math_run).
  Haiku effort high on math then runs as planned; if Haiku effort low needed the fallback, Haiku effort high's math
  cells are dropped without calls (its scan mean, 11,547 tokens, is six times Haiku effort low's).
- **Audit 74, math at read time (committed before any Sonnet, Luna or Sol anchor math reply existed; the e50/e52 scans' replies did exist, audit 75):** the read regrades
  every arm's stored math replies with `normalize_math_read` on answer and gold alike: LaTeX control spaces and ~
  become spaces, \big-style size commands go, \tfrac and \dfrac become \frac, and a short leading "name =" goes when
  the gold has no "=". Checks, never by accuracy: all 93 golds still match themselves; on the Haiku math runs the
  parse status flips for 3 and 4 calls, all from unparsed to parsed.
- **Audit 74, verification on math:** Haiku effort high's math judge cells are dropped like its generator cells;
  Haiku effort low's math self-check keeps its generator's 30% truncation stop; the math verification configs read
  the kept Haiku runs (e51_haiku_off_math, e51_haiku_low_math12). AH3 now has 6 three-call arms (Haiku effort high
  has no math cells), not the 7 power.md simulated; its power with 6 is reported in the read; the limits stay frozen.
- **Pre-declared for Sonnet off, Sonnet effort low, Luna and Sol on math (audit 73; Sonnet off at 4,000 added by audit
  75, before any Sonnet math call):** a math run that stops on truncation resumes at the same ceiling with a 30%
  truncation stop (config `<name>_t30`: the same sources and ceilings, so the calls already made come from the cache);
  truncation counts as wrong and is reported per task; the read then takes that config's math cells from the `_t30` run,
  by this rule alone. The stop rules count a source's live calls only (cached calls are not counted) and apply once it
  has at least 20 of them (expect.min_calls), over every live call of the config so far (corrected by audit 76: a
  truncation in a source's first 20 live calls stops the run when the count reaches 20, not at once).
- **Sonnet on math (the pre-declared fallback; process facts only):** e51_sonnet_math stopped at slice 18+16 on
  truncation: Sonnet effort low hit its 12,288 ceiling on 1 of 38 calls (2.6%, over the 2% stop; the truncated call
  was in slice 0+18, where 19 live calls were under min_calls 20, so the stop came in slice 18+16). The rule above
  applies: e51_sonnet_math_t30 (the same sources and ceilings, a 30% truncation stop) runs all 93 items, its first 34
  from the cache; the read takes Sonnet's math cells from it (anchor_read.TIER1_RUNS); e51_sonnet_math is closed with
  a $0 run cap. The post-stop audit (76) comes before any further call.
- **Audit 75, verification (committed before any verification call):** a judge's pick is its ANSWER line, read
  before any \boxed, and "Candidate k" is the k-th candidate as shown (prompts.judge_reply), at run time and at the
  read alike; whether an item had candidates is decided by the run-time answers (as the run decided whom to call);
  a self-check's verdict needs no confidence line (verdict measures use every verdict, AUROC and Murphy the rows with
  a confidence). Two exploratory reads are added: Sonnet's second calls (agreement of the two calls, both, one or
  neither right, and the coincidence q) and block 3 (each tier-2 arm against the tier-1 arms on its own items).
- **Audit 76, before any verification, Luna or Sol call:**
  - Judge edges: a pick that names more than one candidate ("Candidate 2 or Candidate 3") is a hedge, kept as written
    and so graded wrong, as hedges are for every arm; with no ANSWER line, a last line that names a candidate is the
    pick; a candidate's line breaks become spaces, so a multi-line candidate is picked whole.
  - Every remaining generator or verification config that stops on truncation goes to its post-stop audit and then
    resumes as `<name>_t30` (the same sources and ceilings, a 30% truncation stop; the calls already made come from
    the cache). e51_luna_bbeh_t30 and e51_verify_anth_bbeh_t30 are written ahead, for the Oct 31 deadline.
  - At the read, a truncated call counts as wrong for every arm and every role: it is unparsed, so it has no answer,
    no vote, no pick and no verdict (`anchor_read.regrade`). A config's rows come from its `_t30` run when that run
    exists (`anchor_read.fallback`).
  - The Haiku math self-check's guard is $0.0025 per call, its generator's math guard.
  - If e51_luna_bbeh stops on any rule, the Anthropic verification on BBEH still runs before Oct 31, on the items
    whose Luna-low pool exists by then. The Haiku-effort-high judge is called only where candidates exist, and the read
    takes it on the items with a complete pool (a panel needs every unit), naming the items left out. The Haiku
    self-check needs no Luna call. No Anthropic call is made after Oct 31.
- **Audit 77, before any judge or self-check call on BBEH:** a judge or self-check run reads a pool's `_t30` run
  when that run exists (`panel.panel_files`), exactly as the read does (`anchor_read.fallback`), and each status
  records the files it read. With no ANSWER line, a judge's last line before its CONFIDENCE line can be the pick. The
  block-2 read names every item each judge's read leaves out. Tier-2 `_t30` configs are written ahead.
- **Audit 78, before any Luna call (blind):** Luna medium's guard ($0.0013 per BBEH call) is assumed, never measured.
  If e51_luna_bbeh stops on a source's cost (over 2x its guard), the post-stop audit sets that source's guard to its
  measured price per call so far (rounded up to the next $0.0001) and the same config resumes (the calls already made
  come from the cache); nothing else changes, so the Luna-low pool and the read are unaffected. A stop on an unparsed
  rate goes to its post-stop audit with no pre-declared change; a truncation stop takes the `_t30` fallback above.
  A `_t30` file replaces its run's file (for a run and for the read alike, `panel.fallback_file`) only if it holds at
  least the run's items; a paid judge or self-check run refuses while a panel file it reads is uncommitted or such a
  shorter fallback exists. The block-2 read also names each self-check's left-out items (checked calls 0 that got no
  self-check because they were unparsed at run time).
- **Audit 80, before any tier-2 call:** the block-3 read (tier 2) takes each run through the same fallback rule as
  blocks 1 and 2 (`anchor_read.fallback`), so a tier-2 config that stops on truncation and resumes as `_t30` is read
  from its fallback, not from the partial run. Block 3 stays descriptive; tier-2 math (17 and 10 items) supports cost
  and token facts only.
- **Audit 81, before any OpenAI math call (blind):**
  - Math ceilings: Luna low and Sol low, and Sol's math self-check and judge, run math at 12,288 (not 6,144); Luna
    medium and Sol medium at 24,576 (not 12,288). As the Arms section intends, truncation is then not part of an arm:
    on the anchor's math, 19.7% of Haiku-low and 4.9% of Sonnet-low calls went past 6,144 tokens. BBEH ceilings are
    unchanged.
  - Math guards: rebased to the scan price x 2.1. Luna low $0.0016, Luna medium $0.004, Sol low $0.030, Sol medium
    $0.075; Sol's math self-check and judge $0.030.
  - Audit 78's cost-stop rule applies to every remaining config. A stop on a source's cost resumes the same config
    with that source's guard set to its measured price so far, rounded up to the next $0.0001.
  - The `_t30` truncation fallback still applies to each of them, and the read states any truncation per arm and task.
- **Audit 82 (blind; before any Sol call):**
  - Tier-2 math ran with no stop rule in force (17 and 10 calls, under min_calls 20) and cost 2.9x its guard-based
    estimate. Block 3 states Sonnet effort high's 2 truncations of 10 on math, counts them as wrong, and gives tier-2
    math as cost and token facts only.
  - K3 projection for OpenAI: before each OpenAI config, and at each post-stop audit, the remaining OpenAI spend is
    projected at measured prices per source and task kind (the anchor's own mean price per call where it exists, else
    the guard) and added to the anchor's OpenAI spend so far. The drop list, in order, never a config in the middle of
    its run:
    1. Astra (e51_tier2_open_*);
    2. Sol medium's math cells (e51_sol_math then runs with Sol low alone, as a declared variant);
    3. e51_judge_open_math;
    4. e51_verify_open_math.
    A drop is decided right before its own config would run (so the latest measured prices count), in list order: the
    config runs only if the projection, with it included, fits $34; otherwise it and every later config in the list
    that does not fit are dropped, and the drop is final. A config outside the list runs only if the projection with
    every not-yet-run config of the list removed fits $34; otherwise paid work stops for an audit. Each projection and
    any drop is logged before the config runs.
  - The OpenAI client waits up to 30 minutes for a reply (`providers/openai_compat.REQUEST_TIMEOUT_S`), so a long Sol
    reply is not cut off and retried. Each audit of a Sol config reports the longest call in seconds per source.
- **Audit 83 (after e51_luna_math stopped on its unparsed rate; decided on parse status only, never on a grade):**
  - The math answer is read by one shared function, `autoagentnet/evidence/mathread.math_read`, at run time and at the
    read alike.
    - At run time it sets the `parsed` flag under parser v2, which drives the stop rules and self-check eligibility.
      The stored answer stays raw, so a judge sees the raw answers.
    - At the read it is used by `anchor_read.regrade_math`, for every arm alike.
  - The rule:
    - Audit 74's normalization comes first.
    - Only if that form does not parse and the gold has no "=": drop \displaystyle and take the right-hand side of
      the answer's single top-level "=", provided no \text, "or" or "and" comes before it.
    - A normalization never makes a readable answer unreadable: if no normalized form parses but the answer as
      written does, it is read as written. This guard was added because audit 74's rule had turned 4 Luna calls
      unreadable.
  - Parse counts, as written / audit 74 / audit 83 (truncated calls unparsed):
    - Haiku effort low 245/249/250 of 279; Haiku off 259/262/264 of 279.
    - Luna on its first 25 items: none 45/51/61, low 52/60/67, medium 58/65/74, each of 75.
    - Sonnet and tier 2 unchanged.
    - No call goes from parsed to unparsed. All 93 golds read as themselves.
  - Tests: tests/test_mathread.py.
  - Raising the stop was rejected: it would hide a measurement error that differs by arm.
  - e51_luna_math resumes as the same config: its 225 calls replay from the cache, and the 30% stop counts live
    calls under this parse.
  - Sol math and the OpenAI math verification and judges run under it.
  - Open for the read code, to be settled blind before the block-1 read: answers that parse as written but are
    equations are read as equations. Among parsed answers, that is Haiku off 10/264. Corrected by audit 84: over all
    93 items it is Luna none 6, low 8 and medium 6 (my first count covered Luna's first 25 items only). This is
    settled by "Audit 84" below.
- **Audit 84, before any Sol math call (blind; parse status and the grader's own equivalence only, never a grade):**
  - `mathread.math_read` gains two steps.
    - A readable answer that is still an equation with a single top-level "=" is read as its right-hand side when the
      grader already reads it so (`answers_match(rhs, answer)`). No grade can change, and answers that differ only by
      a "name =" fall in one vote class whichever is seen first.
    - No rewrite changes the value of an answer that is readable as written. If the read form does not match it
      under the grader, the answer as written is read.
  - On the stored math replies:
    - parse counts are unchanged at every stage;
    - 1 equation is left (Sonnet off's set answer, whose right-hand side the grader does not equate);
    - 1 Haiku-off answer is read as written again (audit 74's control-space rule had changed its value);
    - all 93 golds read as themselves.
  - Exploratory, beside AH2 and with no Holm decision: AH2 on the items where every call of the four AH2 arms is
    readable at the read (`anchor_read.ah2_readable`). Answers that cannot be read differ by vendor and weigh more
    on the wide arm (audit 84, finding 7).
  - Block 1 also reports parse rates per arm at each grader stage (`anchor_read.parse_stages`).
- **Audit 86 (after e51_sol_math's first slice failed; before any further Sol math call):**
  - Transport. An OpenAI request with a ceiling above 8,192 tokens streams (`providers/openai_compat.STREAM_ABOVE_TOKENS`;
    tests in tests/test_providers.py). The payload gains exactly `stream` and `stream_options`; cache keys, usage,
    model and finish reason are unchanged; a cut stream raises and leaves no cache entry and no ledger row. Audit 86
    took the cause to be long, silent non-streaming requests dropped by the agent proxy and retried by the SDK, about
    300 s per attempt (the 693 s Sol medium call and the 389 s Luna medium call each fit one dropped attempt plus a
    silent retry). Corrected by audit 87: streaming does not make bytes flow while the model reasons, and the streamed
    retry of the same request got no headers for about 277 s per attempt and then a server 500, so the failing class
    is long requests themselves, not the transport.
  - Reading, step 2b of `mathread.math_read`, for every arm alike. When an answer is still unreadable and the gold has
    no "=", a condition after its first top-level \quad or \qquad is dropped, if that tail has no top-level "=", no
    hedge word, and a relation or \text. Steps 2 and 2b apply only to an answer with at most one top-level "=" as
    written. On all stored math replies:
    - Sol low +4 (unparsed 9 to 5 of its first 15 calls) and Luna low +1; every other arm 0;
    - none from parsed to unparsed, no readable read changed, and all golds read as themselves.
    Sol's 5 calls that stay unparsed are abstentions or a bare bound ("open; conjectured value is c", "v >= c"), which
    stay unparsed as for every arm.
  - Corrected diagnosis (audit 86, finding 4): of Sol low's 9 unparsed calls, 4 were "value with a condition", 3
    "unknown/conjectured" boxes, 1 had no box and 1 was a bare bound.
  - K3: every projection adds $0.50 for attempts that may have been billed without a ledger row.
  - Pre-declared: if a second connection error happens under streaming, Sol medium's math cells are dropped as whole
    cells, and Sol low continues alone in a Sol-low-only variant, after a dry run shows its keys hit the cache.
  - Resume: the same config with `--to-offset 5`. That gives 19 calls from the cache and 1 live call (the request that
    failed, now streamed). More than 1 live call means the keys changed, and the run stops. Then the remaining slices
    run in invocations sized to 60 minutes or less.
- **Audit 87 (after the one-call test: the 19 cached calls replayed, and the streamed Sol medium request failed with a
  server 500 on every attempt, about 277 s each):**
  - The pre-declared drop is read as applying. "A second connection error under streaming" is taken in substance: the
    same request failed again on every attempt, with the transport changed. So Sol medium's math cells are dropped as
    whole cells.
  - Sol low continues alone in e51_sol_math_low, with the same Sol-low source and ceiling. Its 15 calls so far are in
    the cache (scripts/cache_proof.py: 15 of 15 on items 0-4; slice 0+8 must show 24 calls, 15 cached and 9 live,
    or stop). e51_sol_math is closed with a $0 run cap.
  - The read takes Sol low's math cells from e51_sol_math_low (`anchor_read.TIER1_RUNS`). Sol medium's 4 math calls
    are process facts only. e51_verify_open_math self-checks Sol low's call 0 from e51_sol_math_low.
  - AH3 consequence: AH3's complete arms use call 0 of every complete arm, the 1-call arms included, for the item
    posteriors. Sol medium is no longer complete on math, so AH3 runs without it. The read reports AH3's power
    without Sol medium (analysis/anchor_power.py). P6 and the BBEH rows are unaffected.
  - Pre-declared, blind: a Sol low math call that fails every attempt in two invocations is recorded as an empty,
    unparsed reply. It counts as wrong, as truncation does, and is reported per arm, so Sol low stays a complete arm.
  - K3: the allowance for unledgered attempts is $1.00 (it was $0.50), as two failure episodes may have been billed.
- **Audit 88 (after e51_sol_math_low stopped at slice 40+8 on the unparsed rate, 39 of 129 live calls; before item
  48 is called; decided by form only, without opening `correct`):**
  - Corrected census of Sol low's 44 unparsed calls on its first 48 items (144 calls):
    - 29 abstentions, 26 of them live ("unknown", "open", "not presently known", "not established here", "Not
      determined", "no closed form");
    - 4 bare bounds; 1 with no box;
    - 10 value forms: 3 the reader should read (rules A and B below) and 7 outside the parser and outside every
      gold's form (long sum, floor or determinant formulas, a `cases` answer, the same max term on both sides of an
      "="). No gold contains \sum, \lfloor, \det, cases, \text, "=" or an inequality, so those 7 stay unreadable.
  - Reading, `mathread.math_read`, for every arm alike:
    - Rule A (step 2): when the normalized form has no readable right-hand side, the single top-level "=" of the
      answer normalized without audit 74's "name =" cut is tried. That cut stops at the "=" inside `\sum_{n=0}`.
    - Rule B (step 2b): the condition cut needs only a gold without "="; the count of top-level "=" as written is
      dropped, since `condition_cut` already refuses a tail with a top-level "=" (`N=1+3+1+3=8\qquad(k\ge4)` reads 8).
    - On all 2,090 stored base-prompt math replies: Sol low +3 (100 to 103 of 144, all 3 live); every other arm 0;
      none from parsed to unparsed; no readable read changes value; all 93 golds read as themselves
      (tests/test_mathread.py).
  - Stop rule (option b): an unparsed math answer whose words inside `\text{}` say the value is not known
    (`mathread.abstained`: unknown, open, not known, conjectur*, not established, not determined, undetermined,
    unresolved, cannot, no closed form) is counted apart, as refusals are. The 30% limit applies to the other unparsed
    calls, as a share of all live calls of the source (`panel.expectation_misses`). Abstentions stay wrong at the read.
    - Stored flags: Sol low 29, Luna none 4, low 6, medium 7, Haiku off 1, Sol medium 1.
    - Rows already written keep their run-time `parsed` flag, so the stop's rate today is 13 of 129 (10.1%); the
      read applies rules A and B to every row.
    - Kevin set 30% to catch a format collapse; raising it (option a) would stop catching new format gaps.
  - Resume with `--from-offset 48`, not 40: replaying 40+8 would rewrite its 24 live rows as cached rows (dropping 10
    unparsed calls from the stop's count) and overwrite status_items_40.json. Two invocations, 48-72 and 72-93.
  - K3 (audit 82 rule, $1.00 allowance): 12.01 + 1.00 + Sol low's 135 remaining calls at $0.0335 (4.52) + OpenAI
    BBEH self-check and judge 3.87 + OpenAI math self-check and judge 5.58 = $26.97, which fits $34; with Astra,
    $30.02. Astra's gates on this projection: tier 1 $16.52 (under $20), Sol math $9.58 (under $13.05); both are
    checked again on measured spend before any Astra call.
  - To decide blind before the read (audit 88, finding 7): whether a bound parses depends on the variable's name
    (`r\ge c` parses, `v_*\ge c` does not; parsed bounds: Luna 13, Sol low 5). A bound never matches a gold but does
    form vote classes.
- **Audit 89 (after slice 48+8 of e51_sol_math_low failed on a proxy relay drain after 23 of 24 calls; before the
  missing call is asked again):**
  - Cause: the agent proxy closed two tunnels to api.openai.com with code 1012 ("server_draining"). 237 s and 298 s
    are how long the tunnels lived, not how long a request ran: both opened at 16:49:31 and carried several requests.
    arxivmath-0926-50 call 2 started at 16:51:29, so its first attempt died after about 119 s; the 16:54:29 closure
    was most likely its retry. About $0.04-0.08 unledgered.
  - K3: the allowance for unledgered attempts is $1.25 (it was $1.00): the upper bounds of the four episodes so far
    sum to $1.01. No decision moves.
  - Resume (R2): the missing call alone, as run_anchor runs a slice: `aan check` and `aan run` with `--task-offset
    51 --task-limit 1` (0926-50; calls 0 and 1 replay from the cache, call 2 is live), the vendor keys outside the AAN_
    names removed from the environment; the status must show 3 calls, 1 live, or the work stops; status.json is kept
    as status_items_51.json. Only those 2 rows are rewritten as cached. Then run_anchor `--from-offset 56
    --to-offset 72` and `--from-offset 72`. Replaying slice 48+8 (R1) would rewrite 23 live rows as cached and move
    the stop's count from 21/152 to 13/130; changing the write path (R3) mid-config is not worth it.
  - Audit 87's empty-reply rule is not coded now. If this call fails every attempt again (a relay drain counts as a
    failure), the fill is written keyed by an explicit list of (config, item, call, both run ids), never by a missing
    row, which could silently fill a slice that never ran.
  - Audit 88 finding 7, decided blind: (a) a bare bound is read as the grader reads it, for every arm; the read
    reports bounds per arm. No gold contains an inequality, so no grade or vote outcome can change either way. A parsed
    bound does enter AH3's q (`anchor_read.coincidence`, pairs of parsed wrong calls): 0926-51 adds 3 pairs (1
    coinciding) and the set answer on 0826-37 adds pairs. (a) keeps q consistent with the vote classes and with the
    run-time parsed flags that `panel.checked_answers` uses for self-check eligibility. Code (audit 95, before any
    read): `anchor_read.bare_bound` (form only; a set's escaped braces count as braces, so a set is not a bound) and
    the `bounds` and `bounds_read` columns of `parse_stages`.
  - The abstention share on items 48-55 (9 of 23, against about 20% on the first 48 items) changes nothing: any
    change now would be driven by outcomes.
- **Audit 90 (e51_sol_math_low complete; before the first OpenAI verification call; for e51_verify_open_bbeh,
  e51_judge_open_bbeh, e51_verify_open_math and e51_judge_open_math alike):**
  - A slice that fails (a relay drain or any other transport failure) is resumed item by item: `aan check` and then
    `aan run ... --task-offset i --task-limit 1` for each item with a missing call, the vendor keys outside the AAN_
    names removed from the environment, status.json kept as status_items_<i>.json. A failed slice is never replayed
    whole (replaying rewrites its live rows as cached rows).
  - A verification call that fails every attempt in two invocations is written as an empty, unparsed reply, keyed by
    an explicit list of (config, item, call, both run ids), never by a missing row. For a self-check that is no
    verdict: the item is named as left out of the self-check read. For a judge it is no pick: the item stays in the
    judge read and is counted wrong.
  - Each new drain episode adds its upper bound to the K3 allowance for unledgered attempts, and the log says so.
  - A stop on the unparsed rate is first followed by a form census that separates replies with no VERDICT or ANSWER
    line from replies missing only the CONFIDENCE line; Sol has not answered the self-check or judge prompts before,
    so the BBEH self-check runs first as a cheap format pilot.
  - Order: BBEH self-check, BBEH judge, math self-check, math judge. K3 $26.85 (with Astra $29.90); no drop is
    needed. Astra changes no preregistered decision (block 3 is descriptive).
- **Audit 91 (written blind, before any read; the read code counts math-verify timeouts per row since adfec9e):**
  - A math-verify timeout (in parsing or comparing) is read as math-verify reads it: no match. The read reports the
    count per arm (`anchor_read.parse_stages`, column `timeouts`).
  - If any tier-1 math row (every arm the read regrades, not only the confirmatory ones) has a nonzero count, the read
    lists those rows (item, source, call) and recomputes AH2 and AH3 once with every such row counted correct. A
    decision that differs between the two is reported as not robust to grader timeouts; the decision as frozen
    (timeouts read as no match) stands. The bump acts through the panel's answer classes: a class's correctness is its
    first member's (`replay.Panel` class_correct), so a bumped row moves a vote only where it heads its class.
    Code: `anchor_read.timeout_sensitivity` (in `explore_block1` and the block-1 writer), with a fake-data test.
  - Audit 92: block 1 is graded once (`anchor_read.block1` regrades the tier-1 calls once and passes them to the tests
    and the exploratory reads), and every math-verify timeout during a block's read (regrading, the vote classes that
    `Panel.from_calls` builds with the grader, the judges' math candidates) is counted (`counting_timeouts`) and
    reported in block 1 and block 2.
- **Audit 93 (after e51_verify_open_math slice 0+34 stopped on the unparsed rate, 8 of 26; before any further
  verification call; form only, no grade or verdict value looked at):**
  - Census: all 8 have a VERDICT line that parses; none has a confidence the parser read, because Sol boxed it (the
    math system prompt asks for a \boxed last line): `CONFIDENCE: \(\boxed{0.99}\)` (5) and
    `\boxed{\text{CONFIDENCE: }0.93}` (3). The form occurs in no other stored verification row.
  - Rules, every source alike (prompts, TEMPLATE_HASH, VERIFY_HASH and the configs unchanged):
    - `prompts.parse_confidence` (and `parse_verdict`) read the value when only spaces, *, $, \( \[, \boxed{, \text{
      and } stand between the label and it; a number right after the label keeps being read
      (`CONFIDENCE: 0.90 \(\boxed{2}\)` reads 0.90).
    - `prompts.judge_reply` reads a boxed "ANSWER: ..." line as a plain one, reads a pick that names a candidate only
      inside \text{} as naming it, and drops every CONFIDENCE line, boxed or not, before the fallback parse, so a boxed
      confidence is never read as a pick.
    - The read (`anchor_read.verify_calls`) parses every self-check's verdict and confidence again from its stored
      reply with these parsers (a refused row gets none), before the truncation rule.
  - Check on all 2,269 stored self-check, judge and aggregator rows: 8 confidences change (exactly the 8 rows above,
    from none to a value), 0 verdicts change, 0 of the 880 judge picks change.
  - Stored `parsed` flags stay as written, so the stop over this config sees these 8 as unparsed; the rule (b) of
    counting a verdict alone as parsed is not taken (it would loosen Kevin's format stop mid-config).
  - Resume `--from-offset 34` (slice 0+34's calls all ran), then e51_judge_open_math under the same parsers. K3 ($1.28
    allowance): 18.90 + 1.28 + 0.86 + 2.79 = $23.83; with Astra $26.88.
- **Audit 94 (before e51_judge_open_math; written blind):**
  - What the judges were shown is checked through the cache keys (the key hashes the full prompt): the read's requests
    are rebuilt with `panel.requests_for` and each key looked up in the call cache (read only). A judge or self-check
    item whose rebuilt request misses the cache (the read's candidates differ from what the run showed) is named and
    left out of that judge's or self-check's read; more than 2 misses in a config go to an audit before the read.
  - Then, form only: `anchor_read.judge_shown` equals the rebuilt CANDIDATES lines; the read's pick equals the stored
    answer; every parsed raw pick matches a shown candidate (answers_match or whitespace-normalized equality), with the
    exceptions listed by form; all inside `counting_timeouts`.
  - e51_judge_open_math runs in two invocations (`--to-offset 52`, then `--from-offset 52`) with no CPU-heavy work
    alongside (math-verify's timeout is wall-clock).
- **Notes for the read (audit 73, findings 5-7):**
  - Dropping an arm's math cells would remove the math items from AH2's one panel and drop that arm from AH3 on BBEH
    too, so no arm's math cells are dropped except under the rules above.
  - AH2's nearest k depends on the measured prices: with Haiku effort low's math cost the pooled price ratio can
    reach about 2.5 (k = 2) or above 3 (k = 3). The frozen rule (nearest measured dollars) decides; the read states
    the k it used.
  - Counting truncation as wrong biases only against P1 (depth). Items where all three calls of an arm hit the
    ceiling are the per-arm item-effect case, under which AH3 passed 0.47 of simulated anchors, not 0.80.
  - The test limits stay as frozen.

## Reads

One read per block, after all of the block's runs, on this frozen code (`research/v4/anchor/read.md`):

1. Tier-1 generators of both vendors: AH2, AH3, AH1 and the depth-versus-width picture. Each test reads a panel of
   only the arms it needs, so one arm's missing cells cannot drop items from another test; AH3 uses the arms that ran
   on every item and names any it leaves out (`analysis/anchor_read.py`, read_block1).
2. Verification: AH4, the judges and the self-checks.
3. Tier 2: exploratory.

The Atlas gate is met before read 1: `research/v4/atlas/frozen_model.json` is frozen, and this file's predictions are
committed.
