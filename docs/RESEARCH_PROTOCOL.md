# Research protocol: AutoAgentNetwork (v2.1, 2026-10-26)

Binding rules for research in this repo. If a rule here conflicts with a request, follow the request only if the project lead made it; otherwise stop and ask.

**Amendment v2.1 (session E5, 2026-10-26; Kevin's K1, K2 and the E4 instruction):**
- **Question (K1).** The project's question is now v4: how should an agent system split its budget between more
  agents (width), more reasoning or a stronger tier (depth, the analogue of weight precision) and checking answers
  (verification)? Phases 1-3 are the motivating case study. `research/plan.md` holds the v4 plan;
  `research/v3/pruning/phase4_plan.md` is superseded.
- **Scan stage (K2).** A scan may precede any preregistration. It is exploratory, costs under $3, is audited once at
  its end, and never supports a confirmatory claim. Its outputs may choose tasks, arms and token budgets for a later
  prereg. Confirmatory tests still need newly sealed items, a prereg and a single read. A scan never touches sealed
  items.
- **No p-hacking (Kevin, session E4).** A change of direction needs empirical evidence from a preregistered read.
  Exploratory positives are reported with their status and are not acted on quickly. No rows are added to a read
  after it has been seen.
- **Key hygiene (K5, patch 2.1).** Code reads keys only from `AAN_*` variables and passes the key and endpoint to every
  SDK client explicitly, so `ANTHROPIC_API_KEY` and `OPENAI_API_KEY` are never used (`tests/test_key_hygiene.py`).

**What changed in v2**, after session 1 spent $0 but prepared everything and scanned the literature:
- The question is reframed from "learn per-stage pruning ratios" to "where does a multi-agent pipeline's accuracy come from, and how should a budget of agent calls be spent across stages and across tasks" (section 1).
- The full 216-config landscape is replaced by a factorial grid on 4x more tasks: statistical power, not money, is the binding constraint (section 6).
- Dynamic designs are now first-class: a free majority vote, a consensus early exit and escalation to a stronger model (section 8). Most of them can be scored offline from calls already paid for.
- Deterministic rules and agent judgment are separated explicitly (section 3). A code gate, `aan check`, now enforces pre-registration and budget fit before any paid run.

## 1. The question

**Main question.** Where does a multi-agent LLM pipeline's accuracy come from, and how should a fixed budget of agent calls be allocated across stages (static allocation) and across tasks (dynamic allocation)? Cost is measured in cache-aware dollars.

Hypotheses (H1 to H4 carried over from the design doc; H5 and H6 added in v2):
- **H1** (stages interact): a joint search over per-stage keep levels beats stage-by-stage sensitivity analysis at matched cost. Measured by the interaction terms of the production function and by held-out reward.
- **H2** (unequal value): the best keep levels differ across stages. Measured by each stage's value per dollar (section 8).
- **H3** (label-free): agreement with the dense network picks configs close to those the labeled reward picks. The pilot estimates the gap and its confidence interval only.
- **H4** (controls, primary outcome): every gain is reported against matched-cost random pruning, the single agent and a free majority vote over the proposers. A result that does not beat these is not claimed.
  - Since v2.1, also against **one senior model at matched cost**: one Sonnet 5.5 call costs about half the 19-call Haiku network per task. If a single strong model matches the team, a manager should buy the senior.
- **H5** (management by exception): a consensus policy reaches dense accuracy, within its confidence interval, at no more than half the dense cost. A consensus policy answers by vote when the proposers agree and pays for the review stages only on contested tasks.
- **H6** (diagnostic): six agents sharing one model are strongly correlated; the effective team size of the propose stage is at most 3. If H6 holds, pruning proposers is nearly free for a structural reason, and the paper should say so.

**Novelty** (from session 1's literature scan, `research/lit/prior_work.md`).
- **Not claimed:** a better pruner. MaAS, AGP and AgentSlimming learn per-query or budgeted pruning.
- **Claimed:**
  - a production-function view of a fixed propose → critique → refine → aggregate pipeline;
  - cache-aware dollar costs;
  - a joint versus stage-by-stage comparison at matched cost;
  - consensus policies evaluated exactly offline from a shared-call landscape;
  - matched random pruning and voting as the primary controls.

## 2. Money: hard rules

| Limit | Value | Enforced by |
|---|---|---|
| Lifetime cap, Anthropic | $275 (set 2026-10-31, after the 1.15 margin) | `configs/budget.yaml` + `SpendGovernor` |
| Lifetime cap, OpenAI | $100 (set 2026-10-31) | same |
| Pilot phase cap, all accounts | $20 | same; reaching it ended the pilot |
| Evidence phase cap, all accounts | $375 | same |
| Per-run cap | none of its own: the phase's `max_run_usd` equals its total; an experiment may still set `max_usd` | same |
| Safety margin | estimated spend x 1.15 is compared with every cap | same |
| Pre-run gate | `aan check`: prereg present, file committed, worst case fits every cap | `aan run` refuses otherwise |
| Provider-side backstop | Anthropic Console spend limit; OpenAI prepaid credit with auto-recharge off | Kevin |

1. Never edit `configs/budget.yaml`, `configs/pricing.yaml` or anything in `state/`. A hook blocks it; do not look for ways around the hook.
2. Keys are `AAN_ANTHROPIC_API_KEY` and `AAN_OPENAI_API_KEY`. Never create or use `ANTHROPIC_API_KEY` or `OPENAI_API_KEY`, and never print a key.
   - Environment variables reach a container only when it starts. If the keys are missing, say so in the first minutes of the session and continue with free work.
3. Every model call goes through `autoagentnet`. The only exceptions are the free model-listing endpoints (`aan models`).
4. **Before every paid run:**
   - Put a `prereg:` block (question, prediction, kill, decision) in the experiment file and commit it.
   - Run `aan check <file>`. It refuses unless the prereg exists, the file is committed and unchanged, and the run's worst case x 1.15 fits the run, phase and hard caps.
   - Dry-run any new kind of config first (`--model-override fake --task-limit 2`).
   - `aan run` performs the same check itself.
5. One paid `aan` process at a time: each process loads the ledger once, so two would not see each other's spend. Long, token-intensive single runs are fine (Kevin, 2026-10-31); the runner pushes `state/` after every chunk. Calls already made are free to re-run.
6. The runner commits and pushes `state/` after every chunk. After each run, confirm that the push reached `origin`.
7. If a run's actual spend is more than 1.5x its estimate, stop all paid work, find out why, log it and call the auditor.
8. Data whose licence forbids redistribution never goes into git. It lives in `data/external/`, which git ignores.

## 3. Who decides what: deterministic core, dynamic choices

The workflow has three layers. The lower a layer, the less the agent can change it.

| Layer | What lives there | Who changes it | How |
|---|---|---|---|
| **Invariants (code)** | caps, prices, ledger and cache persistence, task splits and their hashes, graders, metric definitions, the `aan check` gate, mid-run stop rules (`expect:`), the network block rules (a vote, exit or escalation is a fixed function of the agents' answers) | Kevin, or a reviewed PR with tests | Code + tests; the hook protects the money files |
| **Parameters (committed before a run)** | design family and levels, thresholds (theta for exits, the escalation cut-off), lambda in the reward, sequential stop rules, banding rules, task slices | the agent, pre-registered | In the experiment file's `prereg:` and fields, committed before `aan check`; changing one means a new run with a new prereg |
| **Judgment (logged and audited)** | which question to ask next, which designs from the library to try, what the results mean, which sources to read, what the report says | the agent | `research/plan.md`, `research/log.md`, auditor verdicts in `research/audit_log.md` |

The same split holds inside the networks: blocks decide by fixed rules from observed answers, so a dynamic network takes the same path on the same inputs and stays cacheable.

**Picking the next run (judgment, made explicit):** choose the run whose outcome would change the most decisions per dollar.
- Write the decision each outcome leads to in `prereg.decision`. If no plausible outcome changes a decision, don't run it.
- Prefer, in order: free offline analysis of calls already paid for → designs that can be scored offline → the cheapest live run that can still answer the question.

## 4. How a session works

On start:
1. `git pull`.
2. Read this file, `research/plan.md` and the NEXT section of `research/log.md`.
3. Run `pip install -e ".[dev]" && python -m pytest -q && aan status`, then check the keys (booleans only).

The loop:
0. **Scan (optional, v2.1).** Before a prereg, a scan of at most $3 on unsealed items may measure difficulty, cost
   and tokens to choose tasks and arms. Write what it will decide before it runs, audit it once at its end, and never
   cite it as confirmatory.
1. **Plan.** Write the step and its prereg (in the experiment file), plus a pointer in `research/plan.md`. Commit.
2. **Gate.** Run `aan check`, plus a dry run for new configs, and log both. For estimates on a new cost basis, use `aan estimate --record research/estimates.csv`.
3. **Run small.** Start each new kind of run at 10 to 20 tasks. Runs stop on their own on a budget cap or a missed expectation. Read `results/<name>/status.json` before anything else.
4. **Audit.** Call the `auditor` subagent after every paid run, before any run whose worst case exceeds $2, before changing direction, and before any conclusion.
   - Paste the verdict verbatim into `research/audit_log.md`.
   - On ADJUST, fix the listed items first. On STOP, stop that line of work.
5. **Explore.** Send the `lit-scout` subagent before spending on a question someone may have answered.
   - Keep the question tree in `research/plan.md`.
   - Keep `research/designs.md` as a scoreboard: one row per design, with held-out error, cost, confidence interval, how it was scored (offline / live) and status.
6. **Log.** Append estimate against actual spend, outcome, verdict and decision to `research/log.md`, ending with NEXT.

Stop and hand back to Kevin (report, PR, summary) when: the pilot steps are done; a cap stops a run; the auditor says STOP on the premise; the gate fails on every candidate; or something needs a price change, more budget, a network domain or a licence decision.

## 5. Known loopholes and how they are handled

The original eleven (v1) still apply; the key ones are summarised here, with those found in session 1:

1. **Gate tasks.**
   - GPQA Diamond is too small and cannot be published, and MATH is contaminated. Session 1 chose Omni-MATH by difficulty band, BBEH and AIME, graded with math-verify and the BBEH grader.
   - The difficulty band is chosen from single-agent runs on a separate banding pool, never from the gap.
2. **The premise may fail.** Voting explains most debate gains (2508.17536); automated multi-agent systems rarely beat self-consistency economically (2606.13003); learned pruners land near random pruning (2609.05933).
   - The gate is a hard kill.
   - The vote over proposers is a primary control, available for free from the dense run.
3. **No temperature control.** Each cell is one sample. `replicates: 2` on a subset measures noise. Within-stage agreement and the effective team size (H6) show whether redundancy is real.
4. **Winner's curse.** Every pick, policy threshold and design is chosen on the search half and scored on the held-out half; the test slice stays untouched.
5. **Power.** At n = 100, the minimum detectable paired difference is about 12 points at 20% discordance (`reports/pilot/tables/power.csv`).
   - Per-config comparisons are therefore underpowered at pilot scale.
   - The factorial design and the production-function fit pool many configs per effect, which is where the pilot's power comes from.
6. **Hidden thinking.** Haiku 5.5 thinks by default, and those tokens count against `max_tokens`. P0 chooses between `haiku_nothink` and `haiku_low`; `max_tokens` stays the cost ceiling.
7. **Token estimates.** The Haiku 5.5 tokenizer gives about 30% more tokens than 4 characters per token.
   - Since v2, `estimate_tokens` uses 3 characters per token, so the governor's worst case errs high.
   - `visible_output_tokens` keeps its pre-registered 4-characters definition, so evaluate the P0 prediction on input tokens against `estimated_prompt_tokens x 3/4`.
8. **Latency.** Latency from landscape runs (concurrency, cache replays) is not a speedup measurement.
9. **OpenAI.** The `gpt-6-luna` booking in `configs/pricing.yaml` ($0.20 / $1.20) is about 2.4x the official price ($0.10 / $0.50). That is safe, but it uses up the OpenAI cap early. Only Kevin can lower it.
10. **Losing state.** The ledger and cache are in git and pushed every chunk.
11. **Analysis assumptions.** Session 1's `analysis/landscape.py` and `analysis/search.py` assume the full 216 grid (greedy and sensitivity step k to k-1). For level grids, step to the next lower evaluated level. `analysis/economics.py` already works on any grid.

## 6. Pilot plan v2 (at most $20 in total; nothing spent yet)

The governor stops near $17.40 of estimated spend. Steps marked "prepared" have configs, data, estimates and dry runs from session 1. Each still needs its `prereg:` block, copied from `research/plan.md` into the experiment file, before `aan check` passes.

| Step | What | Worst case | Kill or decision criterion |
|---|---|---|---|
| P0 calibration | prepared (`configs/experiments/pilot/p0_*`): 5 live calls per model ref, hidden-token and truncation check, actual against estimated tokens. **v2.1:** also `sonnet_nothink` (for the P3 control) and `luna_low` (for P5) | $0.10 | Choose the Haiku ref (`haiku_nothink` or `haiku_low`) and record it in `plan.md` |
| P2 banding + gate probes | prepared: banding on 3 candidates, single against dense on 20 calibration items for at most 2 candidates. Haiku 5.5 is the only worker model in the pilot | $0.5 | As in `research/plan.md` (single at 30 to 60%, gap of at least 5 points) |
| P3 gate confirm | prepared: 40 fresh validation items. **New futility rule:** after the first 20 items, stop if the upper end of the 95% paired-bootstrap CI of dense minus single is below +5 points. **v2.1:** add `single_sonnet` on the same 40 items (the matched-cost senior) | $1.6 | Gap point estimate under 5 points: STOP, report alternatives. Single Sonnet at or above dense: report it as the headline control (H4) before spending on P4 |
| P4 factorial landscape | **replaces the full landscape.** `configs: {levels: [1, 3, 6]}` (27 configs, 105 calls per task against 474). Validation items 20 to 99: search half 20 to 59, held-out half 60 to 99, in runs of at most $4 and 25 minutes | about $6 (check with `aan estimate`) | Dense error outside the gate estimate ±15 points, or cost per task above 1.5x the estimate: stop and audit |
| P4b design scoring | free offline from P4's calls: `vote6`, consensus policies (m, theta) and the equimarginal path (`analysis/economics.py`). Live: `judge_cascade` on the held-out half (Sonnet only on contested tasks) | under $1 live | H5: some policy within the dense CI at half the dense cost or less. H6 from the dense run's agents (effective team size) |
| P5 transfer smoke | prepared: dense + 3 picks on `gpt_small` | $0.46 | Hidden reasoning above 2x, or a price or model-ID surprise: stop OpenAI work |
| Reserve | replicates on 10 items, reruns | $2 | |

Session 1's 216-config P4 configs (`p4_*_landscape_a..d`) are superseded. Regenerate P4 as factorial: extend `scripts/make_pilot_configs.py` or write the configs by hand. Keep its expectations blocks.

## 7. Pilot deliverables

Everything goes in `reports/pilot/`, generated by scripts in `analysis/` from `results/*/results.csv`, as in v1:
- the report PDF;
- figures a to f, with the landscape figure drawn on the factorial grid;
- `decision_memo.md` with costed options and the exact `configs/budget.yaml` change for each.

Added in v2:
- **(h)** consensus policies against the static Pareto front, on held-out tasks;
- **(i)** the production function: accuracy per doubling of each stage, with CIs, and value per dollar;
- the effective-team-size table;
- `research/designs.md` (the design scoreboard).

## 8. Design library: building networks from blocks

A network is a YAML list of stages; each stage is one block. Each block has an economic reading, which is how to reason about it before paying for it.

| Block | YAML | What it does | Economic reading |
|---|---|---|---|
| Independent workers | `kind: llm`, `width: n`, first stage | n agents answer the task independently | Buying more opinions. Worth it only while errors are independent; the effective team size is n / (1 + (n-1) * rho) |
| Free vote | `kind: vote` | Plurality of the previous stage's answers; no call | A committee decision with zero coordination cost: the baseline every review structure must beat |
| Review / refine | `kind: llm` after another stage | Agents read all upstream outputs and critique or revise | Paying for coordination. Its value is the accuracy it adds beyond the free vote, per dollar |
| Consensus exit | `exit_if_agreement: theta` | If the previous stage's plurality share is at least theta, answer with it and stop | Management by exception: easy cases settle cheaply; contested ones get the expensive process |
| Escalation | `escalate_to: <ref>`, `escalate_below: x` | The stage runs on a stronger model when agreement is below x | A specialist consulted only on hard cases; the cost is the escalation rate x the price gap |
| Stage skip | `keep: [.., 0, ..]` | A middle stage is removed and its inputs pass through | Testing whether a department adds anything |
| Edge pruning | `fan_in` | Each agent reads only some upstream outputs | Cheaper reading, but it breaks the shared cached prefix (regularity) |
| Model tier | `models` | A different model for a whole stage | Quantization's analog: a cheaper or stronger worker per stage |
| Debate | `kind: debate`, `rounds: R`, `debate_instruction`, `edges` | Agents answer, then for R - 1 rounds each reads the task and its peers' last answers (`edges[i]`: whose; default all, own included) and answers again; the stage outputs its last round | Buying deliberation: worth it only if later rounds fix more errors than they copy. Round 1 is the same calls as an independent stage, so a pruned debate pays only for its later rounds; stopping after round r and consensus exits replay offline |
| Self-or-social (experiment module, not an executor block) | `kind: self_or_social` config (`autoagentnet/self_or_social/`) | After a first round, each member stops, re-checks its own answer alone, or reads one chosen teammate's first answer and revises (at most once, always from the first-round snapshot); a frozen table fitted on calibration items picks the action from the member's agreement state; the team votes | Pricing one consult against one more round of thinking alone: a peer is read only where its directed gain over reflection pays for its dollars; calibration makes every branch once, so every policy and control is scored offline |

The economic tools that turn landscape data into design decisions are in `analysis/economics.py`:
- effective team size;
- the production function (stage effects, complements or substitutes, value per dollar);
- the equimarginal path (grow the stage with the highest accuracy per dollar first);
- exact offline scoring of consensus policies.

Ready-made designs: `dense_3x6`, `single`, `single_sonnet`, `vote6`, `gated_3x6`, `judge_cascade`, and `mixed_vote6` (after the pilot).

**Model ladder (v2.1).**
- **Worker:** Haiku 5.5 is the only worker in the pilot (Kevin, 2026-10-17).
- **GPT-6 Luna:** used for the P5 transfer check. After the pilot, it is an option for mixed teams: it costs the same list price, is billed to the separate OpenAI budget, and makes different mistakes.
- **Seniors:** Sonnet 5.5 (`sonnet_nothink`), at 20x the price. It is too expensive to run as a worker: the factorial grid would cost about $120. It serves two roles: the matched-cost single-model control, and the escalation judge.
- **Mixed teams:** a stage takes `agent_models: [a, b]`, so agent i uses model i mod 2. This raises a team's effective size at no extra price.

**Iterating on designs:**
1. Propose a design as YAML.
2. Score it offline if every call it would make is already cached. Vote, gated and prefix-sharing designs usually are.
3. Otherwise, estimate it, dry-run it and pre-register it.
4. Run it live on the search half, and score the winner on the held-out half.
5. Record it in `research/designs.md`.

A new block type needs code in `autoagentnet/network/`, a fake-model test, and a row in the table above.

## 9. Repo layout for research

```
research/plan.md        living plan: question tree, pointers to each run's prereg, next steps
research/log.md         append-only dated log; ends with a NEXT section
research/audit_log.md   every auditor verdict, verbatim, and what was done about it
research/designs.md     design scoreboard: held-out error, cost, CI, offline/live, status
research/data_cards.md  every dataset: source, licence, size, splits (with ID hashes), download command
research/estimates.csv  every recorded estimate
research/lit/           lit-scout notes, one file per topic, indexed in README.md
analysis/               scripts that make every table and figure from results/
results/<experiment>/   results.csv, summary.csv, agents.csv, status.json (written by aan run)
reports/pilot/          report, figures, tables, decision memo
state/                  ledger and cache: never edit
```
