# Kevin's Phase 3 and Phase 4 brief (session E3 prompt, sections 3 and 4, verbatim)

Recorded after audit 49 (finding 8) so the rule, margins and step size are in the repo. Deviations are listed in research/v3/pruning/deviations.md.

```text
3. PHASE 3 — pruning agent networks by information per dollar ("AMC for agent networks")
Idea: a multi-agent network is a set of noisy, correlated calls with prices. Pruning = choosing which calls to make, as a fixed network (static) or a per-item rule (dynamic), to maximize answer quality per dollar. Flat panels of independent calls can be replayed exactly from cached calls, so any pruned network is evaluated for free (AMC's cheap evaluation, with no approximation). Methods come from neural-network pruning: Han et al. 2015 (iterative prune + fine-tune), OBD/OBS, Network Slimming, He et al. 2017 channel pruning, APoZ, AMC, NetAdapt, "Rethinking the Value of Network Pruning".
Terms (put in docstrings):
- source: one model at one setting with one prompt. call: one answer. dense network: every call collected per item.
- pruned network: kept call counts per source (static), or a rule that decides per item which call to make next and when to stop (dynamic).
- aggregator: the plurality answer plus a logistic model of P(answer correct) from the kept calls' agreement features; refitting it after pruning plays the role of fine-tuning. For ForecastBench: mean log-odds times a fitted extremizing factor.
- quality: accuracy (BBEH), Brier (ForecastBench). Resources, reported separately (they differ like params, MACs and latency): calls, tokens, list-price dollars per item, sequential rounds, wall-clock seconds (from the call logs).

3.1 Library autoagentnet/pruning/ (free), tested on simulated panels with known answers (use analysis/evidence_power.py's generator):
- replay.py: per-call rows + a network or policy -> per-item answer, confidence, dollars, rounds, seconds. No API.
- Granularity: call (fine-grained); source (channel); vendor/tier with per-round quotas (pattern, like N:M); stage, for staged teams (layer).
- criteria.py, each a score per call group on search items:
  C1 magnitude: |standardized coefficient| in an L2-regularized dense aggregator.
  C2 slimming: L1 path (and group-L1 by vendor) of gates per group; order of reaching zero.
  C3 OBD: 1/2 * h * w^2 from the aggregator's log-loss Hessian. C3b OBS: w^2 / (2 * [H^-1]_gg), which keeps cross terms (the correlation-aware version).
  C4 APoZ analog, label-free: flip rate (share of items where dropping the group changes the final answer) and agreement-with-plurality rate.
  C5 reconstruction (He et al.), label-free: LASSO choice of groups that best reproduce the dense network's confidence, then refit.
  C6 measured: exact leave-one-group-out loss after refit.
  C7 information per dollar: marginal effective independent calls (1' R^-1 1, R = error-correlation matrix of the kept calls) per dollar, and marginal mutual information under a Gaussian-copula error model per dollar (the cost-weighted extension of arXiv 2602.08003).
- search.py:
  S1 sensitivity analysis: prune one source at a time down to 0, one curve per source, threshold T -> keep counts. State its two flaws (no interactions, no cost).
  S2 NetAdapt: from dense, each iteration try cutting $0.0005 per item from every source, refit the aggregator, keep the single best change; repeat down to the cheapest -> the frontier. Run once with dollars and once with rounds as the resource.
  S3 AMC-style: a controller sets each source's keep fraction in a fixed order (state: price, accuracy, correlation with kept calls, budget used and left, previous action; reward: -error; budget enforced by clipping actions). Use the cross-entropy method first; DDPG only if time allows. Test AMC's key assumption: across all designs, Spearman rank correlation between raw-vote accuracy and refit accuracy.
  S4 exhaustive: enumerate every call-count vector (calls within a source are exchangeable) -> the true search frontier; report each method's regret against it.
  Also compare: one-shot vs iterative ranking (re-score after every removal); refit options (dense aggregator restricted to kept calls, ridge refit, plain refit; cross-fit everything); static vs dynamic (stop when P(correct) >= tau, next call = largest expected gain per dollar estimated by replay; compare at equal average dollars and report rounds).
  Baselines: random pruning at matched cost (200 random subsets), cheapest-first, top-k most accurate, the H7 cascade, Sonnet, Sol, Opus (BBEH), the dense refit panel.
- Figures (vector PDF + PNG in reports/v3/pruning/): per-source sensitivity curves; quality vs $/item (log x) for every method; rank agreement among criteria; one-shot vs iterative; static vs dynamic; dollar vs latency frontiers.

3.2 Phase 3A (free, tonight; exploratory, because this data has been seen before)
(a) Staged teams: the pilot grid (results/p4_bbeh_grid_a..p: 27 Haiku designs with propose / critique / refine stages at 1, 3 or 6 agents, 80 BBEH items) is a dense network whose "layers" are stages and whose "channels" are agents. Do stage sensitivity (one stage 6 -> 3 -> 1, others at 6), NetAdapt over stage levels, the frontier against the 5-call vote and Sonnet, and regret against all 27 points. Inside a staged team, pruning an upstream agent changes downstream inputs, so only whole grid points are comparable; say so.
(b) Flat panel: the cached 5 Haiku + 1 Sonnet calls (results/w0_haiku5, p3/p4 single Sonnet; items 20-99): every criterion, S1-S4, static vs dynamic.
Write research/v3/pruning/phase3a.md with every number carrying an item-cluster bootstrap interval, plus the figures. The prior expectation to check: stage sensitivity is flat (each extra Haiku call adds about 0.07 of an independent call), so NetAdapt removes most of the team.

3.3 Phase 3B (free; after the G2a / G2b sealed reads)
Search set = Phase 1 sealed data (BBEH 300; ForecastBench 300) plus Phase 2's persona calls. Run every criterion and search method. Selection rule, fixed and committed before the G2a read:
- BBEH static: the cheapest point on the S2 frontier whose cross-fitted search accuracy is >= Sonnet's - 1 point.
- BBEH dynamic: the policy with the smallest average cost whose cross-fitted search accuracy is >= that static network's.
- ForecastBench: the same, with Brier <= Sonnet's + 0.005.
Freeze the chosen networks (counts, thresholds, refit coefficients) in research/v3/pruning/selected.json and push it before any lockbox call.

3.4 Phase 3C (paid lockbox; seal and preregister tonight, run only after selected.json is pushed)
- Seal now: 200 BBEH items from positions 140+ that are in no existing list, and 200 ForecastBench data-series questions used nowhere (one resolution date each). Ids + SHA-256 in MANIFEST.md; no item text.
- Configs e31_lockbox_bbeh_anth/open and e31_lockbox_forecast_anth/open with prereg blocks: haiku_nothink x5, luna_none x5, sonnet_nothink x1, sol61_low x1, plus Haiku x3 and Luna x3 under the persona prompts. About $6 Anthropic and $7.5 OpenAI. Anthropic half before Oct 31.
- Score every frozen network by replay on the lockbox calls.
- Confirmatory (Phase 3 Holm family):
  P1 selected static network's accuracy minus Sonnet's >= -5 points;
  P2 selected static network minus the dense refit panel >= -3 points;
  P3 dynamic policy minus static network >= -3 points (average cost ratio reported).
- Run power by simulation before sealing; demote anything under 0.70 and say so.
- Exploratory: criteria comparison, S1-S3 regret, one-shot vs iterative, AMC's proxy test, gap to random pruning, dollar vs latency frontiers, ForecastBench.

4. PHASE 4 PLAN (write only, no spend): research/v3/pruning/phase4_plan.md with goals, design, budget ask, gates and Kevin's decisions for:
4A Communicating networks: debate and critique across vendors. Measure how reading others' answers raises error correlation; prune edges and rounds by flip rate and information per dollar, against an AgentPrune/AgentDropout-style learned mask. Replay is not exact here, so specify the evaluation: fresh calls, an AMC-style proxy, and a test of that proxy.
4B Prune plus cheaper tiers: per node choose keep/drop, model tier (Haiku/Sonnet/Opus; Luna/Sol/Astra) and reasoning effort, under dollar and latency budgets, from a measured lookup table of dollars and seconds per (model, effort, task) built from the logs (AMC's latency table; Deep Compression's prune + quantize).
4C Scale: 20-100 agents with persona and memory diversity on Maritime, plus a third, open-weight vendor (OpenRouter gpt-oss-120b; needs Kevin's key and a cap). Measure the saturation curve of independent calls vs number of agents, and whether vendor diversity lowers the error floor that arXiv 2602.08003 predicts for correlated errors.
4D Decisions: the pruned panel's confidence as the W2 desk's sizing input on ForecastBench market questions (Kalshi if its terms are confirmed).
4E Depth: MathArena (deferred) and the AlphaEvolve checkers (60 of 68 run) with reasoning on.
4F Write-up: a workshop paper outline, "Pruning agent networks by information per dollar", using Phase 1-3 figures, and a sketch of the evidence-meter API.
Budget: propose a November phase per vendor (after the Anthropic credit ends), costed from the logs.
```
