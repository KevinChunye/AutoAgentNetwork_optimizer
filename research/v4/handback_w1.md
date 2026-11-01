# Session W1 hand-back: Atlas extensions, paper draft, project record, roadmap

Branch `paper_atlas`, PR #17 (ready for review). All of it is committed. Detail is in `research/log.md` (W1 entry),
`research/audit_log.md` (audit W1-1, verbatim) and `research/v4/atlas/extend.md`.

## Spend

- $0 in W1: no API calls and no GPU.
- Lifetime spend is unchanged at $66.31 (Anthropic $40.27, OpenAI $26.03).
- `configs/budget.yaml`, `configs/pricing.yaml` and `state/` were not touched, and neither were E6's files.

## Analysis headlines

The analyses are $0, on public data, in `analysis/atlas_extend.py` and `research/v4/atlas/extend.md`. All are post
hoc. Their tests are in `tests/test_atlas_extend.py` and run offline.

- **P1, the vote rule against zero-gain.** The data are 695 cells (system and set) with 3 calls, in 24 sets.
  - On vote gains the rule beats zero-gain on squared error (+2.4 points², 0.6 to 3.4), but it overstates the gains:
    where it predicts 3 points or more, it predicts 4.7 and 2.9 is observed.
  - On the 3-vote accuracy itself, it is worse than zero-gain (absolute error 4.4 against 4.0).
  - So the rule ranks where votes pay, but it does not yet price them.
- **P2, depth on public pairs.** The data are 19 pairs of one model at two reasoning settings, across 11 models.
  - One more reasoning step raises ability by 0.92 logits (0.59 to 1.24).
  - It leaves the failure slope unchanged (+0.03, -0.14 to 0.21).
  - The items a model still fails at the higher setting are the items that are hard for every system.
- **P3, AH2 on public data.** The data are 10 MathArena pairs.
  - One deeper call beats the nearest-dollar 3-vote by 12.7 points (7.1 to 18.2).
  - At the top of a model's range the gain is about 0: +1.1 points for Gemini 3.1 Pro, -1.5 for Opus 5.5.
- **P4, label-free selection.**
  - Panels with one strong system among weak ones, one call each:
    - every policy loses 32 to 42 points to the strong system;
    - Dawid-Skene ranks another system first in 42 to 63% of MathArena panels;
    - a fixed label space does not remove this on real data (62 to 71%).
  - At matched calls, panels of competent systems are level with the best system's own vote (-1.8 to -0.3 points).
- **P5, the price of verification.**
  - On SWE-bench, a judge with the anchor's measured selection efficiency beats the top system at its dollars in at
    most 10% of random sets.
  - The anchor's judge could not have won either way. Its pools covered 58.0% of the BBEH items, while Sol low alone
    scored 60.6%, so even a perfect selector over those pools would have lost.
- **P6, systematic shares with intervals.**
  - SWE-bench Verified: 0.73 (items 0.70 to 0.75).
  - MathArena: 0.73. LiveBench: 0.65. The BBEH panel: 0.42.
- **P7, mixed panels of weak systems** (MathArena, single-call accuracy 0.2 to 0.7).
  - The vote gains 5.7 points with 3 systems and 12.5 with 5.
  - The factor model predicts these gains with a bias of 0.4 points.
  - It beats zero-gain in 4 of 5 sets.
- **P8, the all-wrong tail** (added after the brief, following arXiv 2606.27288). On SWE-bench, every one of the 87
  held-out systems fails 7.6% of the test tasks. Given the same information:
  - the factor model predicts 5.9%;
  - a one-factor copula predicts 3.5%;
  - independence predicts 0.

## Paper status

- **Title.** The paper is `paper/main.tex`, titled "Shared failure and the price of verification in multi-LLM
  systems". The working title "Depth before width" is withdrawn until E6's CD2 is read.
- **Format.** NeurIPS 2025 style with the preprint option. `main.pdf` compiles: the main text ends on page 8, and the
  PDF runs to 19 pages with the appendix.
- **Sections:**
  - introduction, definitions;
  - the Atlas;
  - preregistered API studies (Phase 1 and the anchor; CD pending);
  - verification;
  - the open-weight testbed (design only);
  - related work (checked against each paper's abstract; ACBench is not cited, being about weight compression);
  - limitations, conclusion.
- **Appendices.** Preregistrations, power, the audit process, runs and spend, and every number with its status.
- **Figures** (7, from `analysis/paper_figs.py`):
  - systematic shares;
  - the all-wrong tail;
  - depth shifts;
  - depth against width;
  - the judge;
  - the label-free selection map;
  - the price frontier.
- **Numbers.** Every number is `\nm{key}` from `paper/numbers.tex`. `scripts/build_numbers.py` builds all 427 of
  them from committed files, each with its status and source. Spend in the runs table reconciles to $66.31.
- **Missing:**
  - E6's CD read (CD2 decides the title and the depth claim) and its runs review;
  - the testbed results (T1);
  - authors and venue;
  - the 2026 style file;
  - a re-audit of the post-W1-1 revision.

## HTML record

- **Link:** https://claude.ai/artifact/Czo1e2taEktNYuEmDJYLCa. It is private until shared from its Share menu.
- **Source.** `reports/v4/story.html` is built from `story_data.json`; the template is
  `reports/v4/story_template.html`.
- **Checks.** Light and dark themes and phone width were checked in Chromium: no horizontal overflow and no console
  errors.

## Roadmap

`research/v4/roadmap.md` covers Kevin's five points: robustness, systems, cost, application and process. Each has what
to do, why, and what decides when it is done. It ends with an order of work:
1. the batch and cache price rows (Kevin);
2. the testbed pilot;
3. the allocator, at $0;
4. the 8-family design with its prereg and power;
5. the time-split wave;
6. the Gemini replication.

## Audit W1-1: ADJUST

All of its items were applied at $0:
- **P8:** the factor model and the copula now get the same information.
- **P1:** the 3-vote accuracy is reported next to the gain.
- **P7 and P6:** P7 uses per-set counts, and P6 uses system half-splits.
- **P4:** a matched-call comparison is added.
- **Wording:** depth is claimed only for the first reasoning step, in audit 96's wording.
- **P5:** the judge's coverage cap is stated.
- **P2:** the own-items predictor and the two excluded pairs are reported.
- **Statuses:** numbers taken after the read are marked post hoc, and the typed numbers on the page are now generated.
- **Records:** a NEXT section is in the log, and P3's prediction for CD2 is logged in `research/plan.md` before CD2 is
  read: about 0, from -5 to +5 points.

The fixes were not re-audited, because the brief asked for one auditor call.

## Pending on E6 and T1

- **E6, CD.**
  - `depth_review` holds the CD prereg, power analysis, probe and sealed lists. It has no CD read yet.
  - When the read reaches main: merge main, then rerun `python scripts/build_numbers.py`. The "pending" CD numbers
    fill in, and CD2 decides the title.
- **E6, runs review.**
  - `runs_review.md` and `scripts/fetch_external.py` are on E6's branches (`runs_review`, `depth_review`), not on main.
  - Once the fetch script is on main, `python -m analysis.atlas_extend --resume` adds the anchor's per-item share
    intervals (P6).
- **T1.** The GPU pilot waits on a Lightning Studio from Kevin. The paper's testbed section is design only until the
  pilot and stage 1 are read.

## Deviations from the brief

- The Atlas has 464 public systems, not "500+": SWE-bench Verified 173, MathArena 126, LiveBench 165.
- LiveBench is left out of P4 and P5: its rows carry scores but no answers and no costs.
- The anchor is used only through its committed read tables. Its per-call grades are run-time grades, and the gold
  files the read used (`data/external/`) are git-ignored and absent here.
- P8 was added, because a related paper reports exactly this tail.
- Two per-row tables are committed so that every number traces to a file: `p1_rows.csv` (4 MB) and `p7_rows.csv`
  (13 MB).

## Tests

- The W1 tests pass: 21 in all.
- In the full suite, 686 pass. 15 others fail or error, all with FileNotFoundError on git-ignored files in
  `data/external/` that this container lacks. None of them touch W1's code.
