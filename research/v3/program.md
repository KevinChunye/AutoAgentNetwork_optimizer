# AutoAgentNetwork v3: Realistic Agent Organizations

2026-10-20 · Kevin Wang. Repo copy of the research plan doc (https://claude.ai/code/artifact/9747bb80-a978-4a6f-858b-02cd51ea24da). Sessions read this file; if the doc and this file differ, this file plus `research/STEERING.md` govern, and the session flags the difference to Kevin.

## Summary

v3 replaces the pilot's toy setups with realistic ones. It uses public, contamination-resistant data with open metrics. It tests position sizing under known truth. And it runs agent economies in which personal agents interact over real protocols, under rules borrowed from human society.

- **What we know** ($9.31 spent so far). A 19-call Haiku team gains from review, not voting, but one Sonnet call beats it per dollar. Claude traders allocate efficiently in a double auction, but their prices drift toward an example in the prompt.
- **What v3 adds.** Five workstreams:
    - W0 closes the pilot;
    - W1 reruns the team study on public benchmarks;
    - W2 tests conviction and position sizing;
    - W3 makes the market realistic;
    - W4 builds an agent economy over A2A, first in-process and then on Maritime.
- **How sessions choose data.** Each workstream has a ranked ladder of sources. A session tests them top-down and uses the first one that passes every check. Every failure is logged, never silent.
- **What each workstream delivers:** a preregistered plan, a record of which data sources were used and why, a report section with figures, and a decision rule that fired.
- **Budget.** A proposed phase `v3` with a $50 lifetime total, including the $9.31 already spent. The Anthropic credit expires on 2026-11-01, so W0 to W3 run first.

## Where we stand

Two pilots ran in October 2026 for $9.31 in total. Both ask how to organize agents: inside a team (a hierarchy) or between agents through prices (a market).

| Experiment | Setup | What it found | Main caveat |
| --- | --- | --- | --- |
| Team pilot ($6.71) | 19 Haiku 5.5 calls in four stages: 6 propose, 6 critique, 6 refine, 1 aggregate. Run on four BIG-Bench Extra Hard tasks, with 27 pruned team sizes, one Haiku call, a vote of the six proposers, and one Sonnet 5.5 call. | Accuracy climbs at the review stages: 45% average proposer, 51% vote, 58% critique, 62.5% final. Six proposers act like 1.9 independent agents; six critics like 1.2. One Sonnet call scored 71% vs the team's 62.5% at 1.25x the cost. No cheaper design kept the team's accuracy at half its cost. | The single-Haiku control was sampled once per item. On held-out items it beat the average proposer by +13.8 points, so the team's held-out edge over one Haiku (+2.5) is unresolved. |
| Market town ($2.60) | Smith's 1962 double auction: 11 buyers and 11 sellers with private values from $0.75 to $3.25. Competitive price $2.00, 6 trades, $7.50 maximum surplus per period. Five periods of 8 rounds. All-Haiku, all-Sonnet and mixed markets, against 1,000 zero-intelligence sessions. | Efficiency was 95% (all-Haiku), 98% (mixed) and 96% (all-Sonnet), against 90.4% for random budget-respecting traders. No exploitation in mixed markets: a +5.4-point profit gap against a 6.8-point placebo range. No efficiency loss for Sonnet. | 47 of 50 periods priced below $2.00. The prompt's format example was "1.85", the most common trade price. With 2 to 4 sessions per condition, effects under about 7 points can't be ruled out. |

Reports: `reports/pilot/report.pdf` and `reports/market/report.pdf`.

## Rules that carry over

Every v3 session follows `CLAUDE.md` and `docs/RESEARCH_PROTOCOL.md`. These pilot lessons are added as binding rules.

1. **Money.**
    - Every model call goes through `autoagentnet`: governor, ledger and cache. Only Kevin edits `configs/budget.yaml`, `configs/pricing.yaml` and `state/`.
    - One paid run at a time, at most $4 each.
2. **Preregistration.** A `prereg:` block (question, prediction, kill, decision) is committed before any paid run, and `aan check` must print cleared. The auditor reviews every paid run.
3. **Lockbox.** Designs, thresholds and picks are chosen on a search split and judged once on a sealed held-out split. A grader change after seeing results keeps frozen and fixed tables side by side.
4. **Sampling.** Every single-agent control gets at least 5 samples per item, and seeds are recorded. The pilot's held-out swing came from a one-sample control.
5. **Reporting.** Each result is reported as a leaderboard row: accuracy, cost per item, n, and a 95% paired interval. Use bootstrap intervals, plus t-intervals when n is under 10 sessions.
6. **Prompts.** No concrete example values in instructions; use placeholders such as `<price>`. Record a hash of every prompt template. Prompt sensitivity is measured, not assumed away.
7. **Contamination.** Data must postdate the model's training cutoff or carry a canary, and the evidence is recorded.
8. **Plain definitions.** Every variable and metric is defined in plain words before its notation appears.
9. **Git.** Short branch names, never push to `main`, and no attribution lines in commits or PRs.

## Data-source ladder protocol

Each workstream ranks its data sources (rungs) best first. A session tests each rung top-down and uses the first that passes every check. Free checks run before the one paid check, so a failing rung costs nothing.

**Checks, in order (stop at the first failure):**

1. **Reachable.** The download works from the session. A blocked host is recorded by name so Kevin can add it to the network allowlist.
2. **Licensed.** The license allows research use. Any gated terms are accepted (`HF_TOKEN` present).
3. **Gradable.**
    - Answers can be checked automatically.
    - Golds are filtered as the plan says.
    - The grader matches 100% of golds against themselves.
    - A hand check of 10 golds agrees.
4. **Big enough.** After filters, at least the workstream's minimum item count, enough for a calibration split, a search split and a sealed held-out split of at least 40.
5. **Fresh.** Published or resolved after the model's training cutoff, or canary-protected. The evidence is recorded: a cutoff source and dates.
6. **In band** (the only paid check, about $0.10). One Haiku call scores inside the workstream's target band on 20 calibration items x 5 samples.

**When a rung fails:**

- Record the rung, the failed check and the evidence. Then move to the next rung.
- Never mix rungs inside one experiment.
- A session may add a rung it discovers, but only below the listed ones and with a logged reason.
- If every rung fails, skip the workstream, say why in the report, and go on to the next workstream.

**Record:** `research/v3/data_sources.md`, one row per rung tried. Columns:

- workstream, rung, source with link and version, license;
- checks passed, the check that failed, and the evidence;
- whether it was chosen.

Offline tests cover the ladder logic with mocked downloads, so a network failure always falls through cleanly.

## Workstreams

Five workstreams run in the order below. Costs are rough guesses from pilot per-call prices. The governor's estimate replaces them before any run.

| Order | Workstream | Question | First-choice data | Rough actual cost |
| --- | --- | --- | --- | --- |
| 1 | W0 Close the pilot | Was held-out single Haiku a lucky draw? | BBEH items 20-119 (cached) | $0.60 |
| 2 | W2 Conviction desk | Does confidence track competence, and which desk structure stops overconfident sizing? | Synthetic events with known truth; then ForecastBench | $4-9 |
| 3 | W1 Open-metric team benchmark | Does a Haiku team beat one Haiku and one Sonnet on fresh public benchmarks? | MathArena 2026 competitions | $6-10 |
| 4 | W3 Market realism | Does "sane" survive realistic market rules and background traders? | Our engine; then ABIDES | $2-5 |
| 5 | W4 Agent commons | Which human institutions make agent-to-agent economies efficient and safe, and does running each agent on its own VM matter? | Synthetic economy over A2A | $5-10 in-process; Maritime to be set |

### W0 Close the pilot

- **Design.** Four more single-Haiku samples per item on BBEH positions 20-119, so each item has 5. One Sonnet call per item on 100-119. No team calls are needed: they are cached.
- **Measure.** Team minus the 5-sample Haiku average ("Haiku5") on held-out 60-99, with a paired 95% bootstrap interval. Also on 20-59, 100-119 and all 100.
- **Decision.**
    - At least +10: the held-out drop was the control's draw.
    - +5 to +10: unresolved.
    - Under +5: the team's edge over one Haiku is small.
- Preregistered as plan amendment 7. About $0.60 actual, $1.50 worst case.

### W1 Open-metric team benchmark

**Question.** On public, contamination-resistant benchmarks with leaderboards, does the 19-call Haiku team beat four alternatives per dollar? They are: one Haiku call (5 samples), a majority vote of those 5 samples, the pilot's two pruned picks, and one Sonnet call.

**Ladder** (target band: one Haiku at 25-65%; minimum 120 items):

1. **MathArena 2026 competitions, pooled.** AIME 2026 (`MathArena/aime_2026`: 30 integer answers, CC BY-NC-SA), HMMT February 2026 and the other 2026 sets on MathArena's Hugging Face page. Check that they postdate Haiku 5.5's training cutoff.
2. **LiveBench, newest release.** Math and reasoning categories with ground-truth answers.
3. **Humanity's Last Exam, text-only exact-match questions** (`cais/hle`, MIT, gated: needs `HF_TOKEN`). It may fail the band because it is too hard.
4. **BBEH, positions 120 onward** (untouched), for continuity with the pilot.

**Design.**

- Calibration split: the first 20 items. Search and held-out split the rest; held-out has at least 40 items and stays sealed.
- Arms, all on the same items:
    - one Haiku call, 5 samples;
    - vote of those 5 samples;
    - dense team;
    - the picks 3-3-1 and 6-6-1;
    - one Sonnet call, 2 samples.
- Optional, with Kevin's OK: a mixed-vendor team (3 Haiku + 3 OpenAI proposers), to test whether vendor diversity raises effective team size.
- Math rungs keep the pilot's math personas. Other rungs use neutral perspectives.

**Measures.**

- Accuracy and cost per item for each arm.
- Team minus Haiku5 and Sonnet minus team, with paired intervals.
- Accuracy by stage, effective team size, and a leaderboard row per arm.

**Decision.**

- Held-out team minus Haiku5 is at least +5 with an interval above 0: the team works on fresh public data.
- Sonnet is at least as accurate as the team at no more than 1.5x its cost: "buy the senior" replicates.

**Cost.** About $0.035 per item for all arms (3200-token caps), so about $5 for 150 items plus about $1.50 for picks.

### W2 Conviction desk

**Question.** Does an agent's stated confidence track its competence? Which desk structure stops overconfident position sizing? This extends *Confidence Without Competence* from forecasts to bets.

**Terms.**

- *p*: the agent's stated probability that a yes/no event happens.
- *q*: the market price of a contract that pays $1 if it does.
- *Kelly stake*: the share of bankroll that maximizes long-run wealth growth, f* = (p - q) / (1 - q) for a yes bet.
- *Calibration error (ECE)*: the average gap between stated confidence and hit rate.
- *Brier score*: mean squared error of *p*.
- *False-conviction rate*: the share of bets made at 90% or higher confidence that lose.

**W2-A: synthetic, known truth** (no ladder; the generator lives in code). The pilot's selection lessons show why truth must be known.

- **Events.**
    - Each event has a hidden yes/no state, a stated prior, and *k* private clues of known accuracy for each agent.
    - A public price *q* is set from public information plus noise.
    - Each agent's true Bayesian probability and true Kelly stake are therefore computable.
- **Decision and wealth.** Each agent states *p*, picks a side and a stake *f* in [0, 1] of its bankroll, and plays 200 events in sequence.
- **Salience treatment.** Half the events carry a vivid, named story that adds no information. That tests whether naming inflates conviction (the effect in *Confidence Without Competence*) when accuracy can't change by construction.
- **Structures.**
    - S1 solo trader.
    - S2 trader plus a risk manager who sets the stake from *p* and the trader's track record.
    - S3 mechanical half-Kelly from the trader's *p*.
    - S4 a committee of 6 with different prompts: log-odds pooled, then mechanical sizing.
    - S5 a market of bankrolled traders in our auction engine, testing whether wealth flows to the calibrated (Blume and Easley's market-selection result).
- **Splitting the loss.** Each loss splits into two parts:
    - *belief error*: *p* against the true probability;
    - *sizing error*: *f* against Kelly at the agent's own *p*, and against Kelly at the true probability.
- **Lockbox.** Structure settings are fixed on seed block 1 and judged once on sealed seed block 2.

**W2-B: real questions.**

Ladder (minimum 150 resolved questions; each must resolve after the model's training cutoff):

1. **ForecastBench**, newest question sets (MIT, updated nightly).
2. **Live Kalshi markets** through the public API. Forecast now, score at resolution, with the market price as the benchmark.
3. **Live Polymarket markets** through the public Gamma API, the same way.
4. **KalshiBench v2**, filtered to questions closing after the cutoff. Expected to fail: its markets close by 2025-11-16.

**Measures.**

- ECE, Brier and log score.
- Sizing error.
- Overbet rate and false-conviction rate.
- Mean log wealth growth, maximum drawdown and ruin rate.
- The salience effect on *p* and *f*.
- For W2-B, P&L of fractional Kelly against the market price.

**Decision.**

- If a structure cuts sizing error by at least a third on the sealed block without lowering log growth, it is the recommended desk design.
- A salience effect on *f* with an interval above 0 replicates the naming effect in the betting setting.

**Cost.** About one call per decision per agent, 7 for S4: W2-A about $3-6 with Haiku and Sonnet arms, W2-B about $1-3. OpenAI committee members only with Kevin's OK.

### W3 Market realism

**Question.** Does the market town's "sane" result survive realistic rules? How do LLM traders behave among realistic background traders?

**Part a: one change at a time on our engine,** against a rerun of the all-Haiku baseline (M2) with a neutral prompt:

- Randomized or placeholder price examples (removes the "1.85" anchor).
- 16 rounds per period instead of 8.
- Value shocks mid-session.
- 3 units per trader.
- The budget rule not enforced, so losses are possible and measured.
- Asynchronous arrivals with latency, so speed matters.

**Part b ladder** (richer markets; first that installs, runs a 2-agent smoke test offline and accepts our caller wins):

1. **ABIDES** (`jpmorganchase/abides-jpmc-public`). LLM traders among noise, value and momentum agents and a market maker. Measure price-discovery error and price impact.
2. **Magentic Marketplace** (`microsoft/multi-agent-marketplace`). Claude assistants shop for customers among business agents, with search, negotiation and payment. Measure welfare and first-offer bias.
3. **Our engine with strategy bots as background traders** (zero-intelligence, Kaplan sniper, ZIP).

**Measures.**

- Efficiency and Smith's alpha.
- Profit split between buyers and sellers.
- Losses, when the budget rule is off.
- Price-discovery error (ABIDES) or welfare (Magentic).

**Decision.** If efficiency stays within 5 points of the neutral baseline under every change, "sane" is robust. Any change that drops it by 10 or more is the headline.

**Cost.** About $2-5.

### W4 Agent commons

**Question.** Which institutions borrowed from human society make an economy of personal agents efficient and safe? Does running each agent on its own VM over A2A change outcomes?

**Economy.**

- *N* synthetic persons, each represented by one agent with a budget, a list of needs, and goods or skills to sell.
- Needs and supplies are designed so the welfare-maximizing set of trades can be solved exactly (an assignment problem), so "efficiency" works as in the market town.
- 0%, 10% or 20% of agents are adversaries: scammers and prompt injectors.

**Protocol ladder:**

1. The official A2A Python SDK for agent-to-agent messages (Agent Cards, tasks, messages), plus the MCP Python SDK for each agent's own tools: wallet, inventory, calendar.
2. Minimal JSON-RPC over HTTP following the A2A v1.0 spec, plus plain function tools.
3. An in-process message bus with A2A-shaped messages. This fallback keeps the schema.

**Institutions** (each switched on or off in a fractional factorial):

- identity: signed Agent Cards, so only verified sellers can sell;
- escrow until delivery is verified;
- machine-checkable contracts, with an arbiter agent for disputes;
- liability for defects;
- network-wide reputation;
- user-signed spending mandates (AP2-style);
- circuit breakers;
- an injection firewall: instructions inside a counterparty's message are never followed, and canaries trace leaks, as in *Kill-Chain Canaries*.

**Measures.**

- Welfare as a share of the optimum.
- Completed transactions.
- Fraud success rate and dispute rate.
- Time to settle.
- How far injections spread.
- Cost per transaction.

**Phases.**

- **a.** In-process, 20 agents.
- **b.** The same agents and economy on Maritime, one micro-VM per agent, compared with the in-process run. The difference is the effect of the setup: timing, real private state, protocol friction, attack surface.
- On Maritime, agents call a central governed LLM gateway (our governor), never a provider directly. No provider keys sit inside agent VMs.

**Decision.** Recommend the smallest set of institutions that reaches at least 90% of optimal welfare with fraud success under 5%. Report whether the setup itself changes welfare by more than 5 points.

**Cost.** Phase a with 20 agents about $5-10. Phase b is set after Kevin's Maritime answers.

## Assumptions vs realistic setups

Each simplification in the pilots maps to the v3 setup that replaces it.

| Pilot assumption | Why it matters | v3 setup | Where |
| --- | --- | --- | --- |
| Puzzles with one short answer | Real work is multi-step, uses tools, and mistakes have consequences | Fresh public benchmarks now; tool tasks graded on end state (tau2-bench) as a later rung | W1 |
| One model, all agents reading everything, math personas on logic tasks | Real teams split information and mix seniority and vendors | Neutral roles; an optional mixed-vendor arm; effective team size measured | W1 |
| One sample per control item | Single draws swing by 10+ points on 40 items | At least 5 samples per control item | W0, W1 |
| Confidence never priced | Overconfidence costs money only through position size | Stated *p*, stake and bankroll; Kelly as the yardstick | W2 |
| Data the model may have seen | Recall inflates accuracy and confidence | Freshness check on every rung; live questions resolving later | All |
| One unit each, same values every period | Real markets have shocks, inventory, entry and exit | Value shocks; 3 units per trader | W3 |
| Turns in rounds, at most 8 per period | Real markets are continuous, so speed is power (first-offer bias of 60-100% in Magentic Marketplace) | Asynchronous arrivals with latency; 16 rounds | W3 |
| The engine blocks loss-making orders | Real agents must manage their own risk | Budget rule off; losses measured | W3 |
| A price example in the prompt | Instructions leak into behavior | Placeholder examples; prompt hashes recorded | All |
| Agents trade for themselves, with known values and no talk | Real agents act for a principal, negotiate, and may lie or inject | Delegated agents, negotiation, adversaries, institutions | W3b, W4 |
| Everything in one process | Separate VMs bring timing, private state, protocol friction and attack surface | The same economy in-process and on Maritime over A2A | W4 |
| 2-4 sessions per condition | Only large effects are visible | Runs sized to detect about 7 points, with power stated in each prereg | All |

## Budget, phases and session order

v3 needs about $30-40 of new spend. Lifetime spend so far is $9.31: Anthropic $9.30, OpenAI $0.007. The pilot phase allows $20 in total, which covers W0 and most of W2 but not W1 to W4.

**Proposed `configs/budget.yaml` change** (Kevin only). `total_usd` is lifetime spend across both accounts, so it includes the $9.31:

```yaml
phase: v3
phases:
  pilot:
    total_usd: 20
    max_run_usd: 4
  v3:
    total_usd: 50
    max_run_usd: 4
```

| Workstream | Rough actual | Reserved in plan |
| --- | --- | --- |
| W0 | $0.60 | $1 |
| W2 (A and B) | $4-9 | $9 |
| W1 | $6-10 | $10 |
| W3 | $2-5 | $5 |
| W4a | $5-10 | $10 |
| Reserve | | $5 |
| **Total new** | **$18-35** | **$40** |

**Session order:**

1. **S1, setup:** data-source ladders for every workstream, then W0, then W2-A if the budget phase allows.
2. **S2:** W2-A, or W2-B if A is already done.
3. **S3:** W1.
4. **S4:** W3.
5. **S5:** W4a, in-process.
6. **S6:** W4b, on Maritime, after Kevin's answers.

The Anthropic credit expires on 2026-11-01, so S1 to S4 should run before then. The current Anthropic key expires on 2026-11-18. Each session ends by rewriting the NEXT section of `research/log.md`, so the next session can pick up with "continue from NEXT".

## Environment setup and decisions for Kevin

S1 can start with what exists today. Anything missing makes a rung fail, and the ladder moves to the next rung. The probe names every blocked host and missing token, so this list can be finished after S1 reports.

**Setup in the Claude Code cloud environment:**

- [ ] **Network allowlist (Custom).**
    - Keep `huggingface.co` and its download hosts (BBEH already downloads).
    - Add `api.elections.kalshi.com` and `gamma-api.polymarket.com` for W2-B.
    - Add `arxiv.org` and `export.arxiv.org` for literature checks.
    - Add `api.openai.com` only if OpenAI arms are approved.
- [ ] **`HF_TOKEN` environment variable** (read scope). Accept the gated terms for `cais/hle` on Hugging Face. Only needed if W1 reaches rung 3.
- [ ] **Keys.** `AAN_ANTHROPIC_API_KEY` is the AAN-workspace key that expires on 2026-11-18. `AAN_OPENAI_API_KEY` is only for approved OpenAI arms. Never set `ANTHROPIC_API_KEY`.
- [ ] **Budget phase `v3`** in `configs/budget.yaml` (section above). Without it, S1 stops after W0 and W2-A.
- [ ] **Merge the branch** that adds `research/v3/program.md` (this plan) to the repo.

**Decisions:**

- [ ] Approve OpenAI models as a diversity arm in W1 and W2? If yes, check the `gpt-6-luna` price row and pick a low-reasoning setting first.
- [ ] **Maritime questions for W4b:**
    - Can agent VMs reach each other over the network?
    - Can they reach an LLM gateway that we run?
    - What is the API key or CLI login for deploys?
    - How does its LLM proxy bill?
- [ ] Confirm the $50 `v3` total, or set a different one.

## Sources

**Data and benchmarks**

- [MathArena AIME 2026 dataset](https://huggingface.co/datasets/MathArena/aime_2026)
- [Humanity's Last Exam dataset](https://huggingface.co/datasets/cais/hle)
- [ForecastBench](https://github.com/forecastingresearch/forecastbench)
- [KalshiBench (arXiv 2512.16030)](https://arxiv.org/html/2512.16030v1) and its [dataset](https://huggingface.co/datasets/2084Collective/kalshibench-v2)
- [tau2-bench](https://github.com/sierra-research/tau2-bench)

**Markets and agent economies**

- [Competitive Market Behavior of LLMs (arXiv 2609.02580)](https://www.alphaxiv.org/abs/2609.02580)
- [LLM Agents Do Not Replicate Human Market Traders (arXiv 2502.15800)](https://arxiv.org/html/2502.15800v3)
- [Magentic Marketplace (arXiv 2510.25779)](https://arxiv.org/html/2510.25779v1)
- [LLM-Agent Interactions on Markets with Information Asymmetries (arXiv 2603.08853)](https://arxiv.org/abs/2603.08853)
- [GovSim: Cooperate or Collapse (arXiv 2404.16698)](https://arxiv.org/abs/2404.16698v4)
- [EconSimulacra (arXiv 2606.26883)](https://arxiv.org/abs/2606.26883)

**Confidence and sizing**

- [Ordinal Gates, Cardinal Bets (arXiv 2609.00187)](https://www.alphaxiv.org/abs/2609.00187)
- [Preference Optimization Drives Monoculture in LLM Prediction Markets (arXiv 2606.26583)](https://arxiv.org/pdf/2606.26583)

**Protocols and hosting**

- [A2A v1.0 overview](https://agenticcommerceprotocol.info/standards/a2a)
- [Maritime overview](https://www.everydev.ai/tools/maritime/llms.txt)

**Pilots:** `reports/pilot/report.pdf`, `reports/market/report.pdf` and `research/audit_log.md`.
