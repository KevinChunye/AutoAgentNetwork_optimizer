# Self-or-social on ArXivMath: offline readiness, 2026-10-31 (no spend)

Prereg: `research/self_or_social_shortlist/prereg_arxivmath.md` (binding). Configs:
`configs/experiments/self_or_social_math/sos_math_anthropic.yaml` (revisions of A and C) and `sos_math_openai.yaml`
(revisions of B), one name `sos_math`, so both halves add up in one calls.csv. Team A `haiku_low` (12,288 tokens),
B `sol61_low` (12,288), C `sonnet_nothink` (4,000): the refs and ceilings of the E5 anchor's math runs. Pilot:
`--task-offset 0 --task-limit 5` on both halves; the evidence is the other 88 items (`--task-offset 5`).

## Inputs

- Items: `research/v3/evidence/sealed/math_all.txt` (93 ids, the frozen order), the list of
  `configs/experiments/v4/e51_haiku_low_math12.yaml`, `e51_sol_math_low.yaml` and `e51_sonnet_math_t30.yaml`.
  Tasks: `data/external/evidence/math.jsonl`, rebuilt from the MathArena pins in `data/EXTERNAL.json`; its sha256
  matches the manifest (`9922e9a3...`). No gold holds "=".
- First answers (call 0): `results/e51_haiku_low_math12/calls.csv`, `results/e51_sol_math_low/calls.csv`,
  `results/e51_sonnet_math_t30/calls.csv`.

## Coverage (93 items x 3 members = 279 first answers)

| Check | haiku_low | sol61_low | sonnet_nothink | Total |
|---|---|---|---|---|
| (i) stored reply in calls.csv (source `<ref>:base`, call 0) | 93 | 93 | 93 | 279 / 279 |
| (ii) cache key of `initial_request(kind=math)` in `state/cache` | 93 | 93 | 93 | 279 / 279 |
| cached reply equals the stored reply word for word | 93 | 93 | 93 | 279 / 279 |
| request equals the panel's own (`panel.requests_for` on the e51 config) | 93 | 93 | 93 | 279 / 279 |

No request-format fix was needed. The cache was loaded read-only; no first answer has to be re-paid.

## Grading (decided 2026-10-31)

- Math is graded as the anchor's read grades it (`analysis/anchor_read.regrade_math`: the last box read by
  `mathread.math_read`, math-verify against the normalized gold); on the 279 stored replies the two agree row for row.
- The repo's read rule (`research/v4/cd/read.md`): unparsed and truncated calls are wrong and cast no vote, first
  answers and revisions alike (`protocol.grade_reply`, `protocol.vote_answer`, `policy.voting_answers`).

## Headroom of the first answers (under this grading; vote tie order A, B, C)

| | All 93 items | Evidence (88, pilot excluded) |
|---|---|---|
| A haiku_low alone | 15 (16.1%) | 14 (15.9%) |
| B sol61_low alone | 34 (36.6%) | 32 (36.4%) |
| C sonnet_nothink alone | 21 (22.6%) | 21 (23.9%) |
| Majority vote of the first answers | 24 (25.8%) | 23 (26.1%) |
| At least one member right | 50 (53.8%) | 47 (53.4%) |
| (Majority vote, tie order B, C, A: best first, the freeze's rule) | 42 (45.2%) | 41 (46.6%) |

The prereg's "measured before this prereg" line (15% / 18% / 23%; vote 11%; at least one right 42%) used the
panel's stored run-time grade, which compares the raw boxed answer: Sol's 17 correct stored become 34 as read. Under the
decided grading the vote of first answers is about 26% with tie order A, B, C, and consult has at most about 28 points
of headroom above it. On 60 of 93 items no two parsed first answers agree, so the tie order decides most votes:
the BBEH freeze (`analysis/self_or_social.py`, used per fold by `analysis/sos_crossfit.py`) sets the order by the
fitting fold's first-answer accuracy, best first, which here is B, C, A in both folds and lifts the vote to about 46%.

Unparsed first answers: A 9 (8 truncated at 12,288), B 33 (18 of them say the value is not known: abstentions, which
the stop rules count apart), C 3.

## Cost

Expected: the stored first replies as the revision's input (4 characters per token) and each ref's mean call-0
output (hidden reasoning included). Worst case: `aan estimate` (every output at max_tokens; x1.15 in brackets).

| Half | Items | Calls | Expected $ | Worst case $ |
|---|---|---|---|---|
| Anthropic (A, C: 3 branches + full review each) | pilot 5 | 40 | 0.38 | 1.03 (1.19) |
| OpenAI (B) | pilot 5 | 20 | 0.68 | 2.55 (2.94) |
| Anthropic | after the pilot, 88 | 704 | 6.72 | 18.20 (20.93) |
| OpenAI | after the pilot, 88 | 352 | 11.93 | 44.94 (51.68) |
| Anthropic | all 93 | 744 | 7.11 | 19.23 (22.12) |
| OpenAI | all 93 | 372 | 12.61 | 47.49 (54.62) |

Expected dollars per revision call (the configs' cost guards): haiku_low 0.0021, sonnet_nothink 0.018 (full review
0.0177), sol61_low 0.035. The prereg's projection after the pilot is pilot actual x 93 / 5 x 1.3 (about $25.6 if the
pilot costs its expected $1.06).

## Risks before the paid run (besides the budget phase)

- Kill rule at 10% unparsed per member and phase (abstentions excluded, truncations included): B's first answers are
  16% unparsed without the abstentions (15 of 93) and A's 9.7% (9 of 93, 8 of them truncated). If the revisions behave
  alike, B's or A's branch phase can stop the full run after 20 live calls. The pilot (15 branch calls per member) is
  below the 20-call minimum, so it cannot show this; the pilot's own rates are the first look.
- OpenAI room: the full OpenAI half's worst case x1.15 ($54.62; $51.68 after the pilot) is close to the room this
  ledger shows ($59.28). Any other OpenAI spend first, and the gate refuses; then slice with --task-offset/--task-limit.

Reproduce (i)/(ii): `PYTHONPATH=. python -c "from autoagentnet.cache import CallCache; from autoagentnet.self_or_social
import run as R; c = R.SelfOrSocialConfig.from_yaml('configs/experiments/self_or_social_math/sos_math_anthropic.yaml');
print(R.first_answer_readiness(c, CallCache('state/cache'))[['reused', 'cached', 'same_reply']].sum())"`.
