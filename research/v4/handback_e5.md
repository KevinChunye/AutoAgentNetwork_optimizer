# Session E5 hand-back: v4 width, depth and verification

Branch `atlas_anchor`, draft PR #14. Everything below is committed; detail is in `research/log.md`,
`research/audit_log.md` (audits 68-96) and `research/v4/anchor/prereg.md`. Wording of the anchor results is audit 96's.

## Spend against the caps

- Lifetime $66.31: Anthropic $40.27 (cap $100), OpenAI $26.03 (cap $100; evidence-phase account cap $50). Evidence
  phase $66.31 of $150; the $20 pilot is closed. `configs/budget.yaml`, `configs/pricing.yaml` and `state/` were not
  edited by hand.
- API anchor (K3): Anthropic $16.87 of $48 [E6: $16.8745 in the ledger; $16.88 was a sum of rounded parts] (all Anthropic anchor calls done before the Oct 31 credit expiry); OpenAI
  $20.61 of $34 (tier 1 $16.15: Luna $2.55, Sol BBEH $4.40, Sol math $9.20; verification $4.46).
- Unledgered attempts: five proxy or server failure episodes may have been billed without a ledger row; their upper
  bounds sum to about $1.04 and K3 carried a $1.28 allowance for them.

## Patches (section 2)

- Done and audited (audit 68): key hygiene; AUROC and Murphy resolution; a held-out predictive information bound beside
  n_eff; pooled Dawid-Skene with a fixed label space; plan v4.
- Read-time and transport changes, each committed before the outcome it touches was seen: parser v2/v2.1; the shared
  math reader `autoagentnet/evidence/mathread.py` (audits 74, 83, 84, 86, 88: normalization, right-hand sides, a
  condition cut, value guards, abstentions counted apart in the unparsed stop); boxed CONFIDENCE/VERDICT/ANSWER labels
  (audit 93); Anthropic streaming above 16,000 and OpenAI streaming above 8,192 output tokens; math-verify timeouts
  counted per arm, with a frozen sensitivity rule (audits 90-92); bare bounds counted per arm (audit 95).

## Ledger and outline

- Findings ledger: `research/v3/findings.md` (F1-F18). Paper case-study outline: `research/v3/paper_case_study.md`.

## Atlas headlines ($0, public data, exploratory; `research/v4/atlas/atlas.md`, model frozen before any anchor read)

- Failures are mostly systematic: the share of failure variation that is item difficulty is 0.73 on SWE-bench Verified
  and on MathArena, 0.65 on LiveBench, and 0.42 on our Phase 1 BBEH panel.
- SWE-bench Verified (F17, F18): all 39 submissions fail 8.6% of tasks, against 0.0% under independence; held out, the
  factor model predicts the coverage of 2- to 5-system sets within 1.5-1.8 points, independence misses by 11-20.
  MiniMax M2.5 (high) resolves 75.8% at $0.073 per task against Claude Opus 4.5 (high) 76.8% at $0.754; the best pair
  covers 84.0% and all 39 cover 91.4%.

## API anchor results (`research/v4/anchor/read.md`, blocks 1 and 2, frozen code, read once each)

Items: 440 BBEH items (linguini, nycc, word sorting, causal understanding) and 93 arXivMath problems, sealed before
any call; "fresh" means new to this project (BBEH has been public since 2025). Dollars are measured at list prices.
Unparsed calls count as wrong and cast no vote. Numbers marked "auditor post-read" were computed by the auditor after
both blocks were written.

1. **AH2 (confirmatory; passes Holm at 5%, p = 0.001).** Raising a cheap model's reasoning one step beat repeating its
   no-reasoning call at the nearest measured dollars.
   - Haiku: one effort-low call ($0.00077 per item; these 5-decimal dollars are audit 96's, post-read) beat the Haiku-off 2-vote ($0.00066) by +3.7 points (95%
     item-bootstrap interval 1.3 to 6.2).
   - Luna: one low call ($0.00036) beat the Luna-none 3-vote ($0.00026) by +10.7 (7.1 to 14.2).
   - For Haiku the 2-vote equals one call in expectation, so this shows effort low beats effort off at about 1.2x the
     dollars, not that depth beats a wider vote. Against the dearer 3-vote the difference is +1.8 (-0.7 to 4.3),
     reported and not tested.
   - P1 missed: +8 lies outside Haiku's interval.
   - Haiku low's math calls come from the 12,288-token fallback; 9.3% were truncated and count as wrong.
   - On the 480 items where every AH2 call is readable: +4.2 and +11.7.
   - Auditor post-read: the effect sits mainly in word sorting (and linguini for Luna).
   - Decision as frozen: the budget rule puts the first effort step before width for cheap models on these items. It
     does not cover higher effort steps or other tasks.
2. **AH3 (confirmatory; passes).**
   - Cross-fitted on single calls, the factor model predicted the six 3-call arms' 3-vote accuracy with a mean absolute
     error of 0.8 points (largest 1.5; upper bound 2.4), and their gain over one call with 0.7 (upper bound 1.3). Both
     are smaller than P2's predictions of 2 and 1.
   - Gains were small (0.4 to 2.6), and a zero-gain predictor also meets all four limits (auditor post-read). So the
     test shows accuracy when vote gains are small, not that the model captures composition.
   - The model missed Sol low's math gain (+7.9 observed, +0.4 predicted), which comes mostly from abstentions dropping
     out of the vote.
   - Not covered: mixed panels, votes above 3, Haiku high, Sol medium, and items without single-call data.
   - Decision as frozen: the Atlas may price same-arm votes of up to 3 calls. Mixed panels stay untested.
3. **AH1 (exploratory; power 0.00).** Sonnet's effort-low setting closed none of the 11.1-point gap to Sol low (R = 0.02,
   -0.32 to 0.26). Low vs off: +0.2 overall (-2.8 to 3.0), +1.1 on BBEH, -4.3 on math (-12.9 to 4.3; n = 93). P3
   missed, and P5's math part missed. On BBEH the setting barely changed spending, so the vendor-versus-reasoning
   confound stays open. No claim.
4. **AH4 (exploratory; power 0.23).** The Sol low judge's selection efficiency (eta) was 0.85 on easy items and 0.14 on
   hard ones (difference 0.72, 0.41 to 1.05), the direction P4 predicted. Eta is a ratio whose hard-half denominator is
   small, which is why the interval passes 1. No claim without a new prereg.
5. **Depth against width (exploratory).**
   - On BBEH a 3-vote added at most 2.6 points over one call at about 3x the dollars.
   - On math, Sol low's 3-vote added 7.9 (35.1% to 43.0%) at $0.096 against $0.032 per item, mostly through
     abstentions.
   - One Sol low call (56.2%) beat every cheaper arm and vote. Sol medium added nothing over Sol low on BBEH (60.9% vs
     60.6%; P6 held).
   - Systematic share (no interval): 0.61 overall; BBEH 0.65, near LiveBench's 0.65; math 0.43, well below MathArena's
     0.73. The copula reproduces the all-wrong tail: 34.7% predicted against 34.2% observed when all five arms are
     wrong, against 8.2% under independence.
6. **Verification (exploratory).**
   - The Sol low judge scored 52.3% on BBEH: +13.3 over the best pool arm (9.8 to 15.8) and +8.5 over the pool
     plurality (5.4 to 11.7). It is 8.3 below one Sol low call (-12.0 to -4.8) at 1.6x the dollars (auditor post-read).
   - On math it scored +2.9 over the best pool arm (-2.5 to 8.6), capped by 22.6% coverage, and 21 points below Sol
     low alone.
   - The Haiku high judge was 3.3 below Haiku high alone (-7.0 to 0.3) at 1.5x the dollars (auditor post-read).
   - Self-checks: Sol accepted 97% of 500 answers (AUROC 0.69, calibration gap 0.34); Haiku accepted 66% of 523 (AUROC
     0.78). 33 Sol and 10 Haiku math answers were unparsed and never checked; they count as wrong.
   - On these items, a judge over cheap pools was dominated by the judge model's own answer.
7. **Label-free (exploratory).** Dawid-Skene misjudged the arms: pooled, it put Sonnet at 0.79 against a true 0.45. Its
   answer (47.5%) was below one Sol low call (56.2%), repeating the Phase 1-3 finding.

Process facts: Sol medium's math cells were dropped as whole cells after its long requests failed server-side (audit
87); Sol low math stopped once on abstentions (audit 88) and once on a proxy relay drain (audit 89), resumed without
replaying; the math self-check stopped once on boxed confidence lines (audit 93). One math row hit a math-verify
timeout; counting it correct changes no decision. Every verification prompt the read rebuilds hits the call cache
(1,996 of 1,996), so the read used exactly the prompts the runs sent.

## For Kevin

- Decide on Astra (tier-2 OpenAI, about $3; both K3 gates pass, but it changes no preregistered decision and the
  auditor recommends skipping it). Block 3 (tier 2) is held until you decide; before it is read its writer must show
  truncations and tokens and label tier-2 math as cost and token facts only (a blind, tested, audited fix).
- Approve the scope of the budget rule: the first effort step before width for cheap models, on these items only.
- Review and merge PR #14.
- The Anthropic credit expires on Oct 31; no further Anthropic calls are planned.
- Compare OpenAI's usage page for gpt-6.1-sol with the ledger for the failure windows (UTC, Oct 26): 14:05:53-14:28:50
  (ledger 72,852 output tokens), 14:59:20-15:17:47 (ledger 0), 16:49-16:56 and around 18:09; together they bound the
  unledgered attempts (at most about $1.04).
- Long OpenAI requests: the agent proxy closes tunnels when it drains (code 1012), and long Sol requests also failed
  server-side; a background-mode fallback for long requests is your call.
- Remove OPENAI_API_KEY from the environment (the code never reads it).
- `configs/pricing.yaml` books Sonnet cache reads at $0.10 per million; the docs say $0.20 (audit 68). [E6 correction: the docs say $0.10, matching the configured price
  (Kevin's D3); audit 68's note was wrong.]
- HELM and S3 trajectories need downloading on your side; Hugging Face was reachable.
- `data/external` is git-ignored and the read tests need it; the gold files' sha256 are in the log (audit 95).
- T1's PR #15: sealed/MANIFEST.md gained a run-order line after 81da6e1, so a merge may need that line kept.

## NEXT

- $0 first: on the Atlas's public repeated-run data, test the vote rule against the zero-gain predictor, with
  abstentions modelled as non-votes.
- Then test whether AH2 holds across task families on the T1 open-weight testbed's reserved items, before any new API
  spend.
- Any later judge test includes the judge model's own answer at matched dollars.
- Block 3 after your Astra decision and the writer fix.
