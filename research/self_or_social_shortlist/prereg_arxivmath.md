# Self-or-Social on ArXivMath: preregistration (session SC, 2026-10-31)

Status: written before any revision call on these items. A new study; the teammate's BBEH study
(research/self_or_social/prereg.md) is untouched and keeps its own prereg. Configs' `prereg:` blocks point here.
Results are **preregistered-descriptive**: the 93 items were seen by earlier panel runs (first answers only).

## Question
In a mixed-vendor team that has already answered a research-level math item once, should each member stop, re-check
its own answer alone (reflect), or read one chosen teammate's answer (consult:J)? Is a per-member, per-state policy
fitted on half of the items cheaper than having everyone reflect, at no real loss of accuracy?

## Design
- Team (fixed order A, B, C): A `haiku_low`, B `sol61_low`, C `sonnet_nothink`.
- First answers: call 0 of the earlier panel runs, reused at $0 and counted as deployment cost for every method:
  results/e51_haiku_low_math12, results/e51_sol_math_low, results/e51_sonnet_math_t30 (93 items). Before any paid
  call the session checks offline that all 93 x 3 first answers are reused (no first answer is re-paid).
  Measured on these items before this prereg: single accuracy 15% / 18% / 23%; majority vote right on 11%; at least
  one member right on 42% (headroom for consult about 30 points).
- Actions and prompts: the teammate's protocol (autoagentnet/self_or_social/protocol.py), generalized to task kind
  `math` (system prompt and base request of the evidence panel's math kind; math-verify grading). Every revision
  reads the first-round snapshot; a member revises at most once; the team votes with a fixed tie order.
- Branch table: all 9 revision branches (3 reflect, 6 consult) on every item, plus the full-review control.
  Every method is scored offline from this table.
- Policy fitting: two-fold cross-fitting by item hash (sha256 of the question text; even/odd last hex digit).
  Fit the teammate's freeze (cell estimates P(correct | receiver, agreement state, action) shrunk to coarser cells;
  U = P - lam * dollars; lam grid 0, 3, 10, 30, 100; tie rule as in the teammate's prereg) on one half, score on the
  other, swap, pool the 93 scored items. The fixed directed peer and the ablations are fitted the same way.

## Primary claim (decision rule)
The policy beats all-reflect if BOTH hold, pooled over the 93 cross-fitted items:
(a) policy cost per item < all-reflect cost per item, and
(b) the lower 95% bound of (policy - all-reflect) accuracy > -3 points.
Otherwise: "not resolved". Accuracy differences against every control (all-reflect, vote of first answers, fixed
directed peer, smartest peer, random matched, full review, each single member) are reported as 95% paired item
bootstrap intervals (2,000 draws, seed 2026); an interval that includes 0 is "not resolved", never "equal".

## Predictions (before data)
- P1: the decision rule is "not resolved" or holds narrowly: consult helps only when the consulted member is right,
  and at most 42% of items have any right member.
- P2: herding is high: on most items with a disagreement, members consult sonnet_nothink (the most accurate single).
- P3: contaminations (right -> wrong) are rarer than corrections for consults into haiku_low.

## Diagnostics (reported, not tested)
- Herding rate: share of items on which all members that consult choose the same teammate.
- Per-task results: by the items' source category where available.
- Corrections (wrong -> right) and contaminations (right -> wrong) per sender -> receiver edge.
- Action shares; cost per item per method; unparsed and truncated rates per member and phase.

## Pilot and go/no-go
Pilot: the first 5% of items in frozen order (5 items) through all 9 branches and the full-review control.
GO only if all hold and the auditor agrees: (1) unparsed or truncated <= 10% per model and phase; no governor
refusal; no unknown model charge; (2) actual cost per item <= 2x its estimate; (3) the pipeline completed end to end
(first answers reused, every branch called and graded, votes computed); (4) state/ pushed and status.json completed;
(5) projected full cost = pilot actual x (93 / 5) x 1.3 fits the room. Pilot items are not used as evidence: the
evidence is the remaining 88 items (cross-fitted as above). If 1-4 fail: fix, amend, re-pilot on the next 5 items.

## Kill rules
As the teammate's: per member and phase, after 20 live calls, stop if more than 10% are unparsed or truncated or the
cost per call is above 2x its guard; stop on a governor refusal or spend above 1.5x the estimate. Stop, audit, report.

## Amendments
(none yet)

### Amendment 1 (2026-10-31, session SC; before any revision call on these items)
1. Grading: math answers are graded as the E5 anchor's read does (analysis/anchor_read.py regrade_math:
   mathread.math_read cleans the reply's answer, math-verify compares it with the normalized gold). The panel's
   run-time grade compares the raw boxed answer and undercounts (sol61_low: 17 vs 34 of 93 first answers right).
   The cleaning never reads the gold.
2. Read rule: an unparsed or truncated reply (first answer or revision) is wrong and casts no vote; the agreement
   states treat it as "none".
3. Headroom restated under this grading (first answers, 88 evidence items; research/self_or_social_math/readiness.md):
   haiku_low 15.9%, sol61_low 36.4%, sonnet_nothink 23.9%; at least one member right 53.4%. (The "measured" line above
   came from the stored panel grade.) On 60 of 93 items no two first answers agree, so the tie order decides most votes.
4. Tie order: as in the teammate's design, the freeze fits the vote order (best member first) on the fitting fold;
   it is frozen before the scoring fold is read and used for the vote of first answers, the policy and every control.
   The fixed order A, B, C is reported as a secondary vote control.
5. Go/no-go rule 1 and the kill rule are unchanged: unparsed or truncated <= 10% per model and phase, where
   "unparsed" means the parser found no final answer (an explicit "cannot be determined" counts as unparsed). On the
   first answers, sol61_low is about 16% and haiku_low about 10% unparsed or truncated (abstentions aside), so the
   pilot may fail rule 1 on revisions; then the plan's path applies (fix, amend, re-pilot on the next 5 items).
6. Execution: two halves by vendor sharing the name sos_math (configs/experiments/self_or_social_math/
   sos_math_{anthropic,openai}.yaml); revisions of A and C on Anthropic, of B on OpenAI; each reads the other
   members' first answers from reuse_first. Pilot: --task-offset 0 --task-limit 5 on both halves, one at a time.


### Amendment 2 (2026-10-31, session SC; POST-PILOT change, decided by Kevin; before the re-pilot)
The pilot (items 0-4) failed go/no-go rule 1 as written in Amendment 1 item 5: sol61_low revisions were 20% unparsed
(branch 3 of 15, full 1 of 5). All four are on one item (arxivmath-0826-12), and each is an explicit abstention: a
boxed statement that the limit is not known, with its conjectured value (mathread.abstained recognises all five sol
replies on that item, first answer included). haiku_low and sonnet_nothink: 0% unparsed, 0% truncated.
Amendment 1 item 5 counted such abstentions as unparsed, which contradicts the repo's established stop rule (audit 88;
autoagentnet/evidence/panel.py expectation_misses, mathread.abstained): an unparsed math answer that says the value
is not known is an abstention, not a format failure; abstentions are reported apart and graded wrong. Kevin chose to
amend and re-pilot (option "Amend and re-pilot", 2026-10-31):
1. Rule 1 and the kill rule count unparsed replies as expectation_misses does: explicit abstentions (mathread.abstained)
   are wrong, cast no vote, are reported apart (count and share per model and phase), and are NOT counted as unparsed.
   The 10% limits stay for format failures and for truncation.
2. Re-pilot on the next 5 items in frozen order (items 5-9: --task-offset 5 --task-limit 5, both halves). Items 0-9
   are pilot items and never evidence; the evidence is the remaining 83 items (offsets 10-92), cross-fitted as before.
3. Incident during the first pilot (research/log.md, 23:28 UTC): one sol61_low call killed in flight by the harness's
   1-hour background limit may bill unledgered (at most ~$0.13); it is reported to Kevin for reconciliation. Paid
   runs are now started detached (setsid nohup).
4. Written after the pilot, before items 5-92. Conditions from audit SC-7 (agreed):
   - "Unparsed" excludes only non-truncated replies flagged by mathread.abstained (it reads only the words inside
     \text{}, never the gold). Abstentions stay wrong, cast no vote, and are reported per member and phase.
   - Unreadable boxes (e.g. bounds such as "8\le\chi\le12"), missing boxes and truncations still count toward the 10%.
   - If the re-pilot (items 5-9) fails rules 1-4, ArXivMath is NO-GO: no further amendment.
   - Before the full run Kevin reconciles the possible unledgered sol61_low charge (<= ~$0.13) or accepts the bound.
   - Detection limit, stated before the full run: with 83 items, a paired 95% interval around a zero mean
     difference has a half-width of about 1.96 x sqrt(d) / 83 x 100 points for d items on which the policy and
     all-reflect disagree, so the lower bound clears -3 points only if d <= 1 at no mean difference (or the policy is
     more accurate). "Not resolved" is the expected verdict unless the two differ on almost no item.
   - Rule 3 for the pilot is shown by the offline scorer (votes and policy actions computed from the pilot table).
5. Kevin (2026-11-01, 00:1x UTC): "I accept the $0.13 bound, go ahead": the possible unledgered sol61_low charge is
   accepted at its bound (<= ~$0.13) instead of being reconciled.
6. Kevin (2026-11-01, 00:2x UTC), replacing the separate re-pilot of item 2: "don't create pilot just to smoketest
   but you should do the beginning of the actual run so then if the pilot run succeed then completing the rest of
   the full run". So each half runs items 5-92 as ONE run (--task-offset 5, no limit; Anthropic half, then OpenAI
   half, one after the other because they share results/sos_math). The gate is the runner's own stop rules, checked
   on the cumulative live calls after every chunk of 10 items (per member and phase once it has 20 live calls):
   unparsed share as in item 1 and condition 4 above, truncated share, and cost per call (max_cost_ratio x
   usd_per_call), plus the governor's caps. If any trips, the run stops itself, ArXivMath is NO-GO and nothing is
   amended further. Rules 3 and 5 (votes and policy actions computed; cost projection) are checked from the run's
   tables after each half and before the cross-fit. Evidence stays items 10-92 (83 items, as in item 2 and the
   detection limit); items 5-9 are run in the same pass but are not evidence, so nothing is re-used from a pilot.
   Nothing in the design, prompts, parser or analysis changes between items 5-9 and the rest.
