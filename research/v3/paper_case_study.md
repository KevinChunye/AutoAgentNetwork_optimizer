# Paper outline: the case study (Phases 1-3) — two pages

Session E5, section 3. An outline, not a draft. Every number is a row of research/v3/findings.md (F1-F18) and keeps
that row's status; nothing here is new evidence.

## 1. The question the case study motivates (half a page)

- An agent system with a fixed budget can buy more calls of a cheap model (width), more reasoning or a stronger
  tier (depth), or checks of its answers (verification). Width pays only if calls fail on different items.
- Plain-word terms used throughout: *systematic share* (how much of failure is shared across calls and systems,
  research/v4/atlas/atlas.md A1), *n_eff* (how many independent calls a set is worth), *coverage@k* (the ceiling of a
  perfect selector), *eta* (the share of that ceiling a selector reaches).
- Claim of the section: on BBEH and ForecastBench, Phases 1-3 are a case where failures are highly systematic, so
  width bought little and depth (one strong reasoning call) bought most.

## 2. Width saturates fast (half a page)

- F1: five Haiku calls are worth 1.84 independent calls (repeat correlation 0.43); ten are worth about 2.05.
- F2: across sources, latent error correlations of 0.39-0.49 among Haiku, Sonnet and Luna; the 12-call panel is
  worth 3.74 calls (4.19 under the library's estimator; both stated). Luna's low correlations mostly reflect its 19%
  accuracy: it carries no detectable information about the truth (F2's caveat, corrected after audit 68).
- F4, F14, F15: votes and staged cascades of cheap calls gain about one point per extra call and do not reach Sol
  (Haiku x5 plurality 48.3%; 12-call plurality 58.0%; no cascade setting within 2 points of Sol at 0.8x its
  dollars). All exploratory or post hoc; the frontier includes in-sample threshold choices that flatter cascades.
- F5 (confirmatory): the 4-of-6 cascade is non-inferior to Sonnet but not cheaper, because it escalates 78% of items.
- ForecastBench (F8, F9): the strong single calls score best; four cheap calls at 0.26x Sol's dollars were
  inconclusive against Sol (preregistered reading; power about 0.56).

## 3. Depth looks decisive, but is confounded (half a page)

- F3: Sol low is right on 97.3% of the sealed BBEH items at $0.0062 per call; Sonnet off on 72.0% at $0.0139. F7: Sol
  is not recalling answers (40/40 on perturbed items, old gold on 0 of 30 moved items).
- The confound: Sol was run with reasoning on, Sonnet with reasoning off. The Sol-Sonnet gap mixes vendor and
  reasoning. F10 hints that reasoning alone moves a lot (Haiku 75% with thinking vs 40% off on 20 items; exploratory,
  15% truncated) but cannot separate them.
- How the anchor resolves it (research/plan.md, AH1): run Sonnet at reasoning off and at effort low on the same
  fresh items as Sol low; R = (Sonnet low - Sonnet off) / (Sol low - Sonnet off). R above 0.5 says most of the gap is
  reasoning, not vendor. Void if the gap is under 5 points on the anchor's items. AH2 then asks the budget question
  directly: one deeper call against the k-vote of the shallower setting with the nearest measured dollars, for both
  vendors.

## 4. Verification without labels is fragile here (a quarter page)

- F11: plain Dawid-Skene over calls rates Sol at 62.5% (true 97.3%). Audit 68 found two causes that this data cannot
  separate: correlated repeats outvoting one strong call, and the model's label space (observed candidates only),
  which misranks sources even when calls are independent. A fixed label space recovers independent sources in
  simulation (research/v3/evidence/consensus_inversion.md); BBEH answers have no fixed label space, so the Phase 1
  rows are not re-fitted that way.
- F12, F13: an LLM aggregator's stated confidence is worse calibrated than the vote share (BBEH); diluting a panel
  with near-random votes shrinks the calibration gap but not the ranking (AUROC difference not distinguishable from 0).
- F16 (method): an order-dependent tie-break once produced a fake 5-point gain; every replay is now order-invariant.

## 5. Placing the case on the Atlas (a quarter page)

- The case is one point on a wider map: research/v4/atlas/atlas.md fits the same factor model to SWE-bench
  Verified, MathArena and LiveBench (F17, F18). The paper should say where BBEH sits (systematic share, tail,
  coverage vs best single) relative to those benchmarks, not generalise from BBEH alone.
- Limits to state: two benchmarks in Phases 1-3; four model families; BBEH items up to 8,000 characters; most width
  results exploratory or post hoc; one confirmatory family (H5-H7) passed only through Sol or Sonnet.

## Figures (planned)

1. n_eff against number of calls (F1, F2), with the information bound beside it.
2. Accuracy against dollars per item: single calls, votes, cascades, Sol (F3, F4), on the Atlas price frontier (A7).
3. The confound: Sonnet off, Sonnet low, Sol low on the anchor items (AH1), once read.
