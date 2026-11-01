# Agent insurance: pricing cover for agent defaults

Exploratory, no paid calls (2026-10-20). Everything here is computed from data already on disk or public. Code: `autoagentnet/insurance/`; analysis: `python -m analysis.insurance`; outputs: `reports/insurance/tables/` and `figures/`; assumptions: `configs/insurance/assumptions.yaml`; tests: `tests/test_insurance.py`.

## Question

Can an insurer price cover for losses caused by LLM agents acting for a principal, by model and by deployment context, from agent traces rather than claims history? What does a default cost, how do defaults cluster, and what capital does a book of such policies need?

## Data

| Source | What | Rows | Use |
|---|---|---|---|
| tau2-bench `data/tau2/results/final` (MIT licence, sierra-research/tau2-bench) | Claude 3.7 Sonnet, GPT-4.1, GPT-4.1 mini, o4-mini as customer-service agents; airline (50 tasks), retail (114), telecom (114); 4 trials per task; full tool-call trajectories and graded rewards | 4,448 episodes | frequency, default type, dollar exposure, task clustering, pass^k |
| AAN market town (`results/m*/turns.csv`) | Haiku 5.5 and Sonnet 5.5 traders in a double auction, each with a value or cost limit | 2,069 orders | mandate-breach rate by model, the guardrail's effect |
| AAN pilot (`results/p*/agents.csv`, `results.csv`) | Haiku 5.5 dense 3x6 pipeline and single agents on BBEH | 792 proposer calls, 132 dense replicates | error contagion between stages, monoculture, network multiplier |

`research/insurance/tau2_episodes.csv` is the derived episode table, so the report rebuilds without the 283 MB download. Rebuild: `python -m analysis.insurance --tau2 <tau2-bench>/data/tau2/results/final`.

Definitions (also in the module docstrings):
- **default**: tau2 reward below 1; a market order outside the trader's limit; a wrong network answer.
- **commission**: a default where the agent wrote to the database and the final database is wrong. **omission**: database wrong, no write. **communication**: database right, another check failed.
- **exposure**: dollar value of the orders or reservations a defaulting episode's writes touched, each object counted once. An upper bound on loss.
- **LGD** (loss given default): share of exposure actually lost. Not measurable here; 0.25 base, 0.10 to 1.00 in the sensitivity table.

## Method

1. Frequency per (model, context) with a 95% interval that resamples whole tasks, the beta-binomial ICC across a task's 4 trials, and Buhlmann credibility toward the context's pooled rate.
2. Severity: exposure distribution of commission defaults by context, from the tool results.
3. Pure premium = sum over default kinds of P(kind) x dollars per default. Gross premium = (expected loss + cost of capital x capital) / (1 - expense ratio), capital = TVaR(99.5%) - mean of the book's annual loss.
4. Portfolio Monte Carlo (`portfolio.py`): Poisson defaults per insured-month; insured-level drift; a model-wide shock that multiplies every insured's rate on that model; resampled exposures x Beta LGD; approval gate, deductible, limit; co-TVaR capital allocation.
5. Rate level: benchmark tasks are selected to be hard, so benchmark rates are relativities, not deployment levels. The level is a scenario (`levels:` in the config) until an insured's own traces set it.

## Findings (numbers from `reports/insurance/tables/`)

- Defaults split very differently at similar pass rates. o4-mini on airline has the lowest wrong-write rate (26.5%) but escalates 45.5% of conversations and omits 14%; pricing on pass rate alone misprices it.
- Within a context, the four models are hard to tell apart at benchmark scale: credibility weight Z is about 0.4 on airline (50 tasks) and about 0 on retail. Model-specific rates need hundreds of tasks per cell, not tens.
- Defaults cluster by task: ICC 0.41 to 0.66, so 200 episodes are worth about 70 independent ones. pass^4 is 18% to 60%.
- Retail commission exposure averages $1,890 (p95 $5,924); airline $503 (62% carry money). Telecom writes carry no dollar exposure in the data.
- Market town: Haiku 5.5 sellers tried to sell below cost on 11.5% of orders (67 of 584), buyers 1.1%; Sonnet 5.5 0 of 675 (95% upper bound 1.2% sellers, 0.7% buyers). The engine's budget rule rejected every one, so the guardrail removed this loss class completely.
- Pipeline: the Haiku 5.5 dense 3x6 network defaults 0.61x as often as one Haiku agent (95% CI 0.45 to 0.78), but its six proposers are all wrong together 21% of the time against 2.7% if independent (7.9x), and when they are, refine and aggregate stay wrong about 95% of the time. The pipeline lowers frequency without diversifying the model.
- Book of 40 insureds, 20,000 episodes each, production level (1% of benchmark rates): expected loss $587k a year, gross premium about $1.01 per episode (agent compute in tau2 is $0.01 to $0.58 per episode). One model instead of four: same expected loss, capital up 77%. Approval gate on writes over $500 (80% catch): premium down 77%. As the book grows, capital / expected loss falls to 0.24 with four models and stalls near 0.51 with one.
- The premium is driven by LGD first (LGD 0.10: -63%; 1.00: +340%), then shock duration (+24% for 3 months) and shock size (+15% for 5x). Cost of capital barely matters at this capital level.

## Not yet supported

- No claims data exists; LGD, remediation costs and the shock model are assumptions.
- tau2 results are 2025 models. Current-model rates need new runs (below) or HAL's reliability data.
- Exposure counts the whole object touched, not the wrong delta, so it overstates severity.

## Proposed next steps (need Kevin's decision; nothing is preregistered or approved)

1. **Insured market town** (est. $2 to 4, market sessions cost $0.3 to 0.6 each): an engine flag that turns the budget rule off so breaches become real loss trades, plus an insurer that reprices each trader's cover by model from earlier sessions (experience rating). Questions: does the Haiku/Sonnet relativity hold when breaches are allowed; does experience rating converge within a few sessions. Changes market comparability, so it needs a new prereg.
2. **Current-model tau2 rates** (est. $6 to 10 for airline, 50 tasks x 2 trials, Haiku 5.5 and Sonnet 5.5): needs a tau2 adapter that routes calls through the SpendGovernor. Or use HAL's published reliability numbers first, for free.
3. **Heterogeneous pipeline**: rerun the contagion measurement with mixed-model proposers to see whether the 7.9x monoculture factor falls (the `mixed_vote6` network already exists).
