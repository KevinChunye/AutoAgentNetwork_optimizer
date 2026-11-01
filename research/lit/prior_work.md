# Prior work: pruning agent networks, the efficiency audit, cache-aware cost, prompt re-tuning

Date: 2026-10-18. Scout: lit-scout. Protocol step: P1 in `docs/RESEARCH_PROTOCOL.md`. No model API was called.

## How to read this file

- Every source below was opened with WebFetch (arXiv abstract pages, some arXiv HTML versions, the Anthropic docs). WebFetch returns a model-written extraction of the page, not raw text. Short quotes and numbers are as the tool returned them. I did not cross-check them against PDF tables unless a note says so.
- `[abs only]` means I saw only the abstract page, so method and loss details are unverified.
- `[snippet]` means the fact came from a search-result snippet and I did not open the page.
- `research/plan.md` does not exist yet (the only file under `research/` was `STEERING.md`). The "So what" section therefore lists changes to make when the plan is written. H1 to H4 are as stated in the task brief.
- Where this file says "none of the papers I opened does X", that is limited to the pages I opened. Several pages were truncated by the tool (the note says so), and appendices were often not visible.

## Answers up front

1. **Does a prior paper already learn per-stage keep ratios with a cost-aware reward?** Not exactly, but MaAS comes close enough that the claim must be narrowed. MaAS (arXiv 2502.04180) learns, for each of L=4 layers, which operators to activate. The number activated per layer is query-dependent, an early-exit operator can skip later layers, and the training objective contains a token-cost term `lambda * C`. It differs from this project in four ways: its unit is an "operator" (CoT, debate, self-consistency and so on), not one of k identical agents in a fixed propose, critique, refine, aggregate pipeline; the choice is per query, not a static per-stage ratio; cost is tokens, not cache-aware dollars; and it has no matched-random or stage-by-stage comparison. AGP, AgentSlimming, DyLAN, AgentDropout and AgentConductor each cover another piece (see the table). Verdict: (b), novel only with re-scoping.
2. **The "September 2026 efficiency audit"** is very probably arXiv 2609.05933, "Rethinking the Evaluation of Efficiency Methods for Multi-Agent Systems" (submitted 5 Sep 2026). It finds that AgentPrune and AgentDropout land within about 0.2 points of matched random pruning. That is H4 as a published bar. The project text names no title, so the match is by date and content. "Kim et al." is very probably arXiv 2512.08296, "Towards a Science of Scaling Agent Systems" (first author Yubin Kim). Other 2026 audits fit the claim equally well or better (2606.13003, 2604.02460, 2508.17536); see Topic 2.
3. **No paper I opened reports MAS cost with cache reads.** The audit counts whitespace-split tokens. AgentSlimming bills in USD but does not mention caching. Haiku 5.5 cache reads are 0.1x input price, so this is a real gap and a real change to cost estimates (Topic 3).
4. **No paper I opened tests prompt re-tuning after removing agents.** The nearest is MASS, where a final prompt pass after fixing the topology adds about 0.85 points on average (Topic 4).

---

## Topic 1. Pruning and sparsification of LLM agent networks (2023 to 2026)

### Nearest-neighbour table

All entries come from the notes below. "Per-stage ratio?" asks whether the method learns how many agents (or units) each stage keeps.

| Paper | What is removed or chosen | Granularity | How it is learned | Cost in the objective? | Per-stage ratio? |
|---|---|---|---|---|---|
| AgentPrune 2410.02506 | edges (spatial and temporal) | per edge, one-shot top-K | policy gradient + nuclear norm | no | no |
| AgentDropout 2503.18891 | nodes per round, then edges | per round, fixed drop rate | policy gradient (from GPTSwarm) + nuclear norm | no explicit token cost | fixed rate, not learned |
| G-Designer 2410.11782 | edges of a decoded topology | per task | policy gradient + anchor + nuclear norm | no (tokens only reported) | no |
| GPTSwarm 2402.16823 | edges (and node prompts) | per edge probability | REINFORCE | no | no |
| **MaAS 2502.04180** | **operators per layer + early exit** | **per query, per layer (L=4)** | **cost-weighted policy-gradient estimator** | **yes: `lambda * C`, token cost** | **per-layer operator count, query-dependent** |
| AGP 2506.02951 | agents (hard) and edges (soft) | per query | supervised on best subgraphs, Gumbel-sigmoid | sparsity term only | agent count per query, not per stage |
| DyLAN 2310.02170 | agents (top-k by importance score, ranker k=2) | team level, and per layer | heuristic, unsupervised | no (reports API calls) | team sizes set by hand-tuned top-k |
| **AgentSlimming 2605.08813** | **nodes removed, or swapped for a cheaper LLM** | **per node, greedy** | **heuristic ranking + accept/rollback + MCTS** | **yes: USD per problem, budget `C <= B`** | **no ratio** |
| AgentConductor 2602.17100 | layered DAG per query | per layer node cap | SFT then GRPO | density penalty, no token term | caps per difficulty (4/7/10 nodes) |
| SMoA 2411.03284 | responses forwarded per layer | per layer, top-k by a judge | prompted LLMs, no training | cost reported | k=2 main, k=1 to 4 tested |
| CoRL 2511.02755 | which expert LLM to call | per turn | PPO | yes: dollar budget gate | no |

No paper I found uses DDPG or any AMC-style continuous per-stage action for LLM agents. A search for exactly that returned only a DDPG controller for pruning the weights of a single LLM [snippet, not opened].

### AgentPrune: Cut the Crap (ICLR 2025 per search results; the arXiv page lists no venue)
- Link: https://arxiv.org/abs/2410.02506 (HTML: https://arxiv.org/html/2410.02506)
- What it does: learns soft masks over spatial (within-round) and temporal (across-round) edges of the agent graph. It optimises for K' iterations on Q' of 5 or 10 queries, applies one top-K magnitude prune, and fixes the pruned graph for the remaining K minus K' rounds. It prunes edges, not agents.
- Key numbers: abstract says comparable results "at merely $5.6 cost compared to their $43.7" (MMLU); 28.1% to 72.8% token reduction when integrated into existing frameworks; AutoGen on MMLU drops from 486,034 to 349,583 prompt tokens. Per the HTML page, the objective is expected utility (policy gradient) plus a nuclear-norm rank penalty; token cost is analysed afterwards, not optimised.
- Relevance: baseline. Weak threat to novelty (edges, no cost term, no per-stage ratio).
- Resources: code at github.com/yanweiyue/AgentPrune [snippet]; licence not checked.
- Open questions: how close is it to matched random pruning at n=6? The 2609.05933 audit says very close (below).

### AgentDropout (ACL 2025)
- Link: https://arxiv.org/abs/2503.18891 (HTML: https://arxiv.org/html/2503.18891; ACL long paper listed in a search result [snippet])
- What it does: trains intra-round and inter-round adjacency matrices, then drops the nodes with the lowest weighted in- and out-degree in each round ("select the nodes with the smallest weighted in- and out-degree"), then retrains and drops edges.
- Key numbers: abstract says about 21.6% fewer prompt tokens and 18.4% fewer completion tokens, with a performance gain of 1.14. Llama3-8B average 68.70 vs 66.51 for AgentPrune. The number kept is set by a fixed dropout rate (alpha for nodes, beta for edges, values 0.1 and 0.2); a sweep from 0.2 to 0.8 shows "higher rates lower average performance". Node dropout optimises task performance only; the edge step adds a nuclear-norm sparsity term. About 40 training samples.
- Relevance: closest published per-round node pruning. It supports the idea that agent counts can drop without much loss. Threatens novelty only slightly: the rate is a hyperparameter, not learned, and no cost reward.
- Resources: models Llama3-8B-Instruct, Qwen2.5-72B-Instruct, DeepSeek-V3; datasets MMLU, GSM8K, AQuA, MultiArith, SVAMP, HumanEval. Code and licence not checked.
- Open questions: a rate swept from 0.2 to 0.8 gives a one-dimensional curve; nobody sweeps different rates per round. That is H2.

### G-Designer (2024)
- Link: https://arxiv.org/abs/2410.11782 (HTML: https://arxiv.org/html/2410.11782)
- What it does: a variational graph auto-encoder over agents plus a task node decodes a task-adaptive topology.
- Key numbers: "MMLU accuracy of 84.50%, HumanEval pass@1 of 89.90%, token consumption reduced by up to 95.33%". Per the HTML page the loss is `L_utility + L_anchor + L_sparse` (nuclear norm); "There is no explicit token-cost term in the training loss." The agent count is fixed (five GPT-4 agents in the main runs).
- Relevance: baseline. Not a threat.
- Open questions: none specific.

### GPTSwarm: Language Agents as Optimizable Graphs (ICML 2024)
- Link: https://arxiv.org/abs/2402.16823 (HTML v3: https://arxiv.org/html/2402.16823v3; the PDF came back as binary and was not readable)
- What it does: each candidate edge has a probability; REINFORCE with Adam estimates gradients from M sampled graphs because the utility is non-differentiable.
- Key numbers: MMLU collaborative setting +2.1% +/- 1.1% over the baseline across 5 seeds; Mini Crosswords with GPT-3.5-Turbo 0.575 vs 0.465 for the initial distribution and 0.510 for a fixed-edge-density control. The objective has no cost or budget term; the paper notes "denser graphs are likely to require more computational resources" and controls for edge count with a fixed-density baseline.
- Relevance: baseline, and a precedent for the matched-density control (the same idea as H4).
- Open questions: none specific.

### MaAS: Multi-agent Architecture Search via Agentic Supernet (2025)
- Link: https://arxiv.org/abs/2502.04180 (HTML: https://arxiv.org/html/2502.04180). arXiv lists no venue.
- What it does: a supernet with L=4 layers, each a distribution over operators (CoT, LLM-Debate, Self-Consistency, Self-Refine, Ensemble, Testing, ReAct, early exit). For each query it samples a system: operators are activated in order of score until a cumulative threshold of 0.3 is reached, and sampling the early-exit operator skips the remaining layers.
- Key numbers (quoted as returned): "We set the number of layers as L=4." "Operators are activated sequentially, starting from the one with the highest score." "This ensures that the number of selected operators per layer is query-dependent." Cost term: "C(.) evaluates the cost of multi-agent systems, represented by token cost"; objective (Eq. 10) is `min E[ -p(a | q, pi, O) + lambda * C(G; q) ]`; lambda tested at 1e-3, 5e-3, 1e-2. Abstract: 6% to 45% of the inference cost of existing systems, 0.54% to 11.82% better. On MATH with gpt-4o-mini: training $3.38, inference $0.42 in total; AFlow training $22.50.
- Relevance: **threatens novelty (partial).** It is the closest thing to "learn per-layer width under a cost-aware reward".
- Differences that survive: operators, not identical agents; per query, not a static per-stage ratio; token cost, not cache-aware dollars; no random-pruning or single-agent control; no comparison of joint vs sequential layer search.
- Resources: models gpt-4o-mini, Qwen-2.5-72b, llama-3.1-70b; benchmarks GSM8K, MATH, MultiArith, HumanEval, MBPP, GAIA. Code and licence not checked.
- Open questions: would a static per-stage ratio from MaAS-style cost weighting (`lambda * C`) match a per-query MaAS policy? That is a cheap offline baseline once the landscape table exists.

### AGP: Adaptive Graph Pruning for Multi-Agent Communication (2025)
- Link: https://arxiv.org/abs/2506.02951 (HTML: https://arxiv.org/html/2506.02951)
- What it does: a node-mask head keeps agents with sigmoid output at least 0.5 (hard pruning of agent count) and an edge head sets weights (soft pruning). The agent count is chosen once per query, with rounds fixed at K=3.
- Key numbers: "dynamically configure the number of agents and their communication topologies per task". Loss is `L_edge + beta * L_node` with beta=1; the node loss includes a sparsity term `lambda_s * <y>`. The page defines a cost-weighted utility but the training loss has no token term. Trained supervised on 460 labelled subgraphs (labels from fine-tuned subgraph search), not RL. gpt-4o-mini average 91.04% vs 89.56% for G-Designer; about 90% fewer prompt tokens on MMLU vs GPTSwarm. Ablation: removing hard pruning costs 2.45 points on MMLU, removing soft pruning 4.16. Reported as one run per condition for AGP.
- Relevance: **threatens novelty (partial)** for "learn how many agents to keep". Not per stage, no cost reward, no RL.
- Open questions: per-query agent count is richer than a static ratio; the cost of that richness is a training set of hundreds of labelled graphs.

### DyLAN: Dynamic LLM-Powered Agent Network (COLM 2024)
- Link: https://arxiv.org/abs/2310.02170 (HTML v2: https://arxiv.org/html/2310.02170v2)
- What it does: team optimisation picks the top-k agents by an unsupervised Agent Importance Score from a preliminary trial. During solving, an LLM ranker keeps the top 2 responses per layer ("We set k=2 in the agent team reformation"), and early stopping triggers when over 2/3 of agents in a layer agree.
- Key numbers: team sizes 12 to 8 (code generation), 8 to 4, 7 to 4. **Table 8, code generation (writers/reviewers: Pass@1, API calls): 6/6: 76.2, 23.04; 4/4: 82.9, 16.85; 4/3: 81.1, 14.64; 4/2: 77.4, 12.50; 3/3: 78.0, 11.73; 3/2: 75.6, 9.60.** No cost-aware objective; cost is API calls.
- Relevance: supports (fewer agents can be better, and the optimum depends on both layers jointly) and threatens novelty slightly (per-layer top-k selection exists, heuristically). Table 8 is the only published per-layer width grid I found; it looks like a miniature version of this project's 216-config landscape.
- Open questions: 4/4 beats 6/6 by 6.7 points with a third fewer calls. Is that the same effect as H1 and H2, or noise? The page gives no confidence intervals.

### AgentSlimming: Towards Efficient and Cost-Aware Multi-Agent Systems (2026)
- Link: https://arxiv.org/abs/2605.08813 (HTML: https://arxiv.org/html/2605.08813); submitted 9 May 2026; paper licence CC BY-NC-SA 4.0 per the arXiv page; code at github.com/CitrusYL/AgentSlimming (link on the page, not opened).
- What it does: a compression framework for graph-structured LLM workflows. Each node gets four signals fused by reciprocal rank fusion: degree centrality, betweenness, leave-one-out Shapley proxy `S(G) - S(G minus v)`, and delta-cost. Greedy removal tries the top 3 candidates and accepts one if `S(G_p) >= tau * S(G_base)` with tau=0.95, patching edges and rolling back on failure. A second pass swaps a node's LLM for a cheaper one. An MCTS refinement follows.
- Key numbers: abstract "reduces average token cost by up to 78.9%"; tables report USD per problem. GSM8K 95.5 accuracy at 78.8% lower cost; MBPP 73.3 to 77.9 at 71.7% lower cost; MATH 74.8 to 73.9 at 42.7% lower cost; AIME 67.1 to 65.7 at 19.2% lower cost. Cost is "measured in USD per problem", computed "based on the actual API billing rate", objective "maximize S(G) subject to C(G) <= B". I found no mention of prompt caching. GPT-4.1-mini with GPT-4.1-nano as surrogate; temperature 0.
- Relevance: **threatens novelty (partial)** on "dollar-aware agent removal under a budget"; **baseline** for a sequential, leave-one-out method, which is the analog of stage-by-stage sensitivity analysis (H1).
- Differences that survive: greedy and local rather than a joint search; no per-stage keep ratio; no cache accounting; in the sections I saw, no comparison with AgentPrune, AgentDropout or random pruning (the page was truncated at the appendix).
- Open questions: does greedy leave-one-out lose to joint search when stages interact? Nobody has tested it.

### AgentConductor: Topology Evolution for Multi-Agent Competition-Level Code Generation (2026)
- Link: https://arxiv.org/abs/2602.17100 (HTML: https://arxiv.org/html/2602.17100v1); submitted 19 Feb 2026; ICML 2026 poster [snippet].
- What it does: a Qwen-2.5-3B orchestrator, trained with SFT then GRPO, builds a layered DAG per query. Per-turn node caps by difficulty: N_max = 4 (easy), 7 (medium), 10 (hard). Reward `r = r_e + r_g`, where `r_g` is a density reward that goes negative when the node count exceeds N_max(l).
- Key numbers: abstract "up to 14.6% higher pass@1", "13% density reduction", "68% token cost reduction". The fetch of Table 3 (APPS) indicated at most about 47% total-token reduction against any single baseline, so I could not reproduce the 68% headline from that table. "There is no explicit token-cost term."
- Relevance: supports (per-layer node counts matter, difficulty-dependent). Not a cost-aware reward.
- Open questions: difficulty-conditioned widths suggest a static ratio may be weaker than a per-query policy.

### SMoA: Sparse Mixture-of-Agents (2024, under review)
- Link: https://arxiv.org/abs/2411.03284 (HTML: https://arxiv.org/html/2411.03284)
- What it does: a judge picks the best k responses from n processors per layer; a moderator stops early. No training.
- Key numbers: main setup 4 processors, 2 layers, k=2; k=3 best on MMAU, k=4 declining. Qwen2-72B ablation: MoA cost 3.25 (MMAU 25.95) vs SMoA cost 1.75 (MMAU 24.57); without early stopping SMoA costs 3.70. Cost units are not defined on the page.
- Relevance: supports (per-layer sparsification of a layered, fully-connected design roughly halves cost for a small loss). This is the same shape as the dense network here.
- Open questions: how do k and layer count interact? Only k was swept.

### S2-MAD (NAACL 2025)
- Link: https://arxiv.org/abs/2502.04790 [abs only]
- What it does: "a novel sparsification strategy designed to reduce token costs within MAD". Up to 94.5% token reduction vs standard debate with accuracy loss under 2.0%. The abstract page does not say which agents participate or how that is chosen. A search snippet said a decision-making mechanism admits agents by how unique their outputs are [snippet].
- Relevance: supports; baseline for debate sparsification.

### EIB-Learner: Information Propagation Effects of Communication Topologies (EMNLP 2025 per a search snippet)
- Link: https://arxiv.org/abs/2505.23352 [abs only]
- What it does: a causal analysis finds that "moderately sparse topologies ... typically achieve optimal task performance"; the method fuses dense and sparse connectivity patterns.
- Relevance: supports H2-style interior optima (neither dense nor minimal). No numbers on the page.
- Open questions: does "moderate" mean the same fraction at every stage?

### Optima (arXiv 2024; ACL 2025 Findings per a snippet, page says "Under review")
- Link: https://arxiv.org/abs/2410.08115 [abs only]
- What it does: trains the agents' LLMs (SFT, DPO, MCTS-style data) with a reward balancing task performance, token efficiency and communication readability. Llama 3 8B.
- Key numbers: "up to 2.8x performance gain" using "less than 10% of the tokens" on information-asymmetric tasks.
- Relevance: a cost-aware reward for agent systems, but it changes weights, not network width. Different lever.

### CoRL: Controlling Performance and Budget of a Centralized Multi-agent LLM System with RL (2025)
- Link: https://arxiv.org/abs/2511.02755 (HTML: https://arxiv.org/html/2511.02755)
- What it does: a Qwen2.5-7B controller, trained with PPO, decides each turn whether to answer or dispatch a sub-query to one of the frozen expert LLMs (o3, GPT-4.1, GPT-4.1-nano). Budget level (low, medium, high) is given in the prompt.
- Key numbers: "The final reward function is a multiplication of the performance reward and cost reward"; `r_c = 1 if cost <= B else 0`. Cost is in dollars ("the $ needed per query"). MATH500: o3 0.938 at $5.642 vs CoRL high 0.958 at $5.870, CoRL low 0.900 at $4.650. Random routing among experts 0.880 on MATH500. The page's budget thresholds are inconsistent between the appendix and Section 5.
- Relevance: supports (an RL controller under a dollar budget works, and a random-routing control is reported); a third way to put cost into a reward, besides AMC's action-space bound and MaAS's penalty. Not a pruning paper.
- Open questions: the budget gate gives zero reward over budget, which is a sparse signal; with 216 configs it is unnecessary.

### Others (abstract level, except AFlow, where I also read the HTML)
- AFlow (https://arxiv.org/abs/2410.10762, HTML https://arxiv.org/html/2410.10762): MCTS over code workflows; "5.7% average improvement"; smaller models beat GPT-4o "at 4.55% of its inference cost in dollars". The search objective has no cost term ("cost is tracked ... to construct a pareto front"). Baseline, not a threat.
- RGA-Designer (https://arxiv.org/abs/2608.20099, 20 Aug 2026) [abs only]: a reward model for "task correctness and structural compactness" fine-tunes a graph generator; 20.5% fewer tokens at ARG-Designer accuracy. Per-task topology, not per-stage ratios.
- Graph-GRPO (https://arxiv.org/abs/2603.02701, Findings of ACL 2026 per a snippet) [abs only]: GRPO over groups of sampled communication graphs; abstract says nothing about cost or agent counts.
- Codebook Agent (https://arxiv.org/abs/2609.02264, 2 Sep 2026) [abs only]: amortised topology design; the abstract reports that edge count is negatively correlated with measured token use (Pearson r about -0.4), and regresses a proxy on per-task normalised token cost. Warns that edge count is a poor cost proxy, which matters for any structural cost model.
- SafeSieve (https://arxiv.org/abs/2508.11733, AAAI 2026) [abs only]: progressive link pruning, 12.4% to 27.8% token reduction, 13.3% lower deployment cost in heterogeneous settings.

### AMC: AutoML for Model Compression (ECCV 2018), the method being transplanted
- Link: https://arxiv.org/abs/1802.03494 (HTML: https://arxiv.org/html/1802.03494)
- What it does: a DDPG agent emits a continuous sparsity ratio for each layer in turn, given a state that describes the layer.
- Key numbers: "4x FLOPs reduction on VGG-16 ... 2.7% better accuracy than the handcrafted model compression policy"; MobileNet 1.81x measured speedup on a phone with 0.1% top-1 loss.
- What matters for design (from the HTML page): resource-constrained mode uses `R_err = -Error` (Eq. 4) and enforces the budget by bounding the action space ("action_t <- min(action_t, action_max)" and a floor so the remaining layers can still meet the target). Accuracy-guaranteed mode uses `R_FLOPs = -Error * log(FLOPs)` (Eq. 5). During search "we evaluate the reward accuracy without fine-tuning"; only "the best-explored model is fine-tuned".
- Relevance: the method under test. The handcrafted rule-based policy that AMC beats is the analog of stage-by-stage sensitivity analysis.
- Open questions: in AMC the layers are a fixed chain with a cheap, near-deterministic evaluator. Here each evaluation is a noisy LLM run, and with 216 configs enumeration is cheap, so the RL controller's value is sample efficiency, not reachability (protocol loophole 5).

### Label-free reward (H3): supporting and cautionary sources
- TTRL (https://arxiv.org/abs/2504.16084) [abs only]: majority-vote results "yield surprisingly effective rewards" for RL on unlabelled data; it can "consistently surpass the upper limit of the initial model maj@n". Supports the plausibility of an agreement-based reward.
- Hu et al. 2605.09618 (Topic 2): vote entropy "predicts where debate is safe, not where debate is needed"; 31 of 47 debate-helpful examples (66%) occur when voting is unanimous but wrong. Inference for H3: an agreement-with-dense reward cannot reward a pruned network for fixing a dense network's confident errors, so it can at best track dense accuracy.
- No paper I opened uses agreement with a dense network as the reward for pruning an agent network.

---

## Topic 2. The efficiency-audit protocol, and where multi-agent beat a single agent

### Rethinking the Evaluation of Efficiency Methods for Multi-Agent Systems (EMNLP 2026 per the arXiv page, 2026)
- Link: https://arxiv.org/abs/2609.05933 (HTML: https://arxiv.org/html/2609.05933). Submitted 5 Sep 2026, v1. CC BY 4.0. Code: https://github.com/chili-lab/rethinking-mas-efficiency-eval (link on the page, not opened).
- What it does: runs AgentPrune, AgentDropout, AGP, DAGP and GPTSwarm under one backbone, agent registry and runtime, with matched random-pruning controls and a single-agent baseline, varying topology, agent count (anchor n=6, reduced to 4), depth (anchor r=2, up to 4) and tool use.
- Key numbers (quoted as returned): over the 20 main-grid cells "optimized methods average -0.77 accuracy points versus the original MAS, and matched random pruning averages -0.44". "learned pruning often provides only limited advantage over this control." AgentPrune and AgentDropout land within about 0.2 points of their random controls; only DAGP shows a clear gap (+1.29 vs +0.08). Single-agent baselines: GSM8K 89.76, MMLU 70.80, HumanEval 83.23, LiveCodeBench 50.00; on LiveCodeBench "the uncompressed MAS is often no better than the single agent". Collapse: GPTSwarm on a Chain topology for GSM8K falls from 93.78 to 7.51; AGP on a Random topology for HumanEval drops 17.39 points. Recommendation: a pruning method "should be credited only when it beats random pruning at the same budget."
- Models and data: Qwen3-4B-Instruct-2507 (GSM8K), Llama-3.1-8B-Instruct (MMLU-500), Qwen2.5-Coder-7B-Instruct (HumanEval, LiveCodeBench-150).
- Cost accounting (appendix): token counts are whitespace-split lengths, "an upper bound rather than a per-call replay"; edge-passing tokens are "shown to be misleading". Cost in dollars and caching are not mentioned in the portion I read (the page was truncated at about 200,000 of 223,511 characters).
- Relevance: **threatens the premise of H4 and sets the bar for it.** Also **baseline** protocol (matched random pruning, single agent, fixed backbone). It audits pruning of one mask in 4B to 8B open models; it does not study per-stage ratios or cache-aware dollars.
- Open questions: random pruning "already preserves accuracy" where redundancy is high. Does a 3x6 Haiku network with a perspective prompt per agent have that much redundancy? The project's own agreement-inside-stage measurement (loophole 3) is the direct test.

### Towards a Science of Scaling Agent Systems (Kim et al., 2025; v3 April 2026)
- Link: https://arxiv.org/abs/2512.08296 (HTML: https://arxiv.org/html/2512.08296). v1 9 Dec 2025, v3 8 Apr 2026. First author Yubin Kim.
- What it does: 260 configurations, 6 agentic benchmarks, 3 LLM families, 5 architectures (single agent plus Independent, Centralized, Decentralized, Hybrid multi-agent). Models include GPT-5 variants, Gemini 2.5, Claude Sonnet 3.7, 4 and 4.5.
- Key numbers: abstract range "+80.8% on decomposable financial reasoning to -70.0% on sequential planning". Budget matching: "All MAS and SAS configurations were matched for total reasoning-token budget (mean 4,800 tokens per trial)". Finance-Agent: Centralized +80.8% (0.631 vs 0.349), Decentralized +74.5%, Hybrid +73.1%. BrowseComp-Plus: Decentralized +9.2% (0.347 vs 0.318). Workbench: Decentralized +5.6%. PlanCraft: all multi-agent variants -39.1% to -70.0%. SWE-bench Verified: -2.1% to -14.9%. Saturation: "tasks where single-agent performance already exceeds 45% accuracy experience negative returns from additional agents". Error amplification: Independent 17.2x, Centralized 4.4x. The abstract reports cross-validated R^2 of 0.373 (0.413 with a task-grounded capability metric) and best architecture chosen correctly for 87% of held-out configurations. A search summary cited 180 configurations and R^2 0.513 for an earlier version; I used the page I opened.
- Relevance: **supports the gate** (multi-agent helps on decomposable, parallelizable tasks; hurts on sequential ones; a weaker single agent leaves more to gain) and **threatens the premise** on tasks where the single-agent baseline is already above about 45%. The gate's 30 to 60% single-agent band straddles that threshold.
- Open questions: the propose, critique, refine chain is sequential, which is the regime where Kim et al. see losses. Reasoning QA is not among their benchmarks.

### The Illusion of Multi-Agent Advantage (2026)
- Link: https://arxiv.org/abs/2606.13003 (HTML: https://arxiv.org/html/2606.13003v2). v1 11 Jun 2026.
- What it does: audits six automatically designed MAS (DyLAN, MAS-Zero, ADAS, AFlow, MaAS, MAS-Orchestra) against CoT-SC (5-sample majority vote) on GPQA-Diamond, HLE-Maths, SWE-Bench Lite, BrowseComp-Plus and a synthetic task, with GPT-4o, GPT-OSS-120B, GPT-5 and Gemini-2.5-Pro.
- Key numbers (quoted): "automatic MAS consistently underperform CoT-SC despite being up to 10x more expensive"; "automated MAS frameworks rarely surpass CoT-SC and never do so economically". The only three significant gains: DyLAN on GPT-OSS +6.6pp at 5x cost, DyLAN on GPT-5 +4.3pp at 2.5x, MAS-Orchestra on GPT-5 +6.0pp at 1.9x; "significant MAS uplift only occurs on HLE-Math using GPT-5 and Gemini-2.5-Pro". An expert-designed MAS on the authors' synthetic decomposition task reached 96.5% vs 57.0% for CoT-SC on GPT-5 at comparable cost.
- Relevance: **threatens the premise**; **baseline** (CoT-SC at 5 samples is the control to beat). It is also a candidate for the project's "efficiency audit", but its date (June 2026) does not match "September", so I rank 2609.05933 first.
- Open questions: the page notes prior comparisons "rarely control for inference budgets"; no explicit cost-matched protocol is given.

### Single-Agent LLMs Outperform Multi-Agent Systems on Multi-Hop Reasoning Under Equal Thinking Token Budgets (Tran and Kiela, 2026)
- Link: https://arxiv.org/abs/2604.02460. v1 2 Apr 2026, v2 11 Apr 2026. [abs only]
- Key numbers: "We find that SAS consistently match or outperform MAS on multi-hop reasoning tasks when reasoning tokens are held constant." Predicts multi-agent becomes competitive "when a single agent's context use degrades or more compute is spent". Warns of budget-control artifacts in API setups (Gemini 2.5) that can inflate multi-agent gains. Qwen3, DeepSeek-R1-Distill-Llama, Gemini 2.5.
- Relevance: **threatens the premise**; changes how to match budgets. Note that Haiku 5.5 has adaptive thinking billed as output (protocol loophole 8).

### Debate or Vote (Choi et al., NeurIPS 2025 Spotlight)
- Link: https://arxiv.org/abs/2508.17536
- Key numbers: "Majority Voting alone accounts for most of the performance gains typically attributed to MAD"; debate "induces a martingale over agents' belief trajectories", so debate alone does not raise expected correctness; "simple ensembling methods remain strong and more reliable alternatives in many practical settings". Seven benchmarks; models not named on the page.
- Relevance: **threatens the premise**; supports a self-consistency control at matched cost.

### Multi-Agent Reasoning Improves Compute Efficiency: Pareto-Optimal Test-Time Scaling (Wunderlich et al., ACL 2026 SRW)
- Link: https://arxiv.org/abs/2605.01566 [abs only]. Submitted 2 May 2026.
- Key numbers: "debate and mixture-of-agents outperform self-consistency by 1.3% and 2.7% points"; "self-consistency saturates earlier, multi-agent gains persist"; MMLU-Pro and BBH; models not named on the page.
- Relevance: **supports**: the one 2026 source I opened that reports a multi-agent win over self-consistency at equal compute, on reasoning QA. The margin is small.

### Statistical Scouting Finds Debate-Safe but Not Debate-Useful Cases (Hu et al., 2026)
- Link: https://arxiv.org/abs/2605.09618 [abs only]. Submitted 10 May 2026.
- Key numbers: three protocols under a 960-token cap (greedy, three-sample voting, two-agent critique-revise debate); Llama 3.1 8B and Ministral 3 8B; MuSiQue and GSM8K. "each (model, dataset) cell has a different winner". An oracle that picks the right protocol per example beats the best fixed protocol by +14.0 and +13.7 pp on MuSiQue. A vote-entropy router gains only +1.3 and +1.7 pp, with confidence intervals including zero.
- Relevance: supports that the right amount of debate depends on the example (a per-query width could beat a static ratio) and bears on H3 (see above).

### Do More Agents Help? Evaluating Accuracy and Cost in LLM Multi-Agent Workflows (BenchAgent, 2026)
- Link: https://arxiv.org/abs/2606.05670 [abs only]. v1 4 Jun 2026, v2 9 Oct 2026.
- Key numbers: six MAS configurations vs a single-agent reference on ten benchmarks with GPT-4.1, three runs, 3,302 instances per configuration per run. EvoAgent was the only MAS to beat the reference (79.70 vs 76.65 pooled accuracy, in all three runs). The other five trailed by 1.71 to 8.76 points. LLM-Debate +9.67 on HumanEval but -1.96 pooled at 1.39x tokens; ChatEval +22.25 on IFEval but behind in pooled accuracy at 4.34x tokens.
- Relevance: supports a per-task gate (a network can win one task and lose pooled) and threatens the premise on average.

### Rethinking the Value of Multi-Agent Workflow: A Strong Single Agent Baseline (Xu et al., 2026)
- Link: https://arxiv.org/abs/2601.12307 [abs only]. Submitted 18 Jan 2026.
- Key numbers: "a single agent can reach the performance of homogeneous workflows with an efficiency advantage from KV cache reuse"; a single agent "can even match the performance of an automatically optimized heterogeneous workflow". No numbers on the page.
- Relevance: **threatens** and changes a cost estimate: a single-agent control that simulates the workflow in one multi-turn conversation also gets cache reuse. Price the controls with the same cache accounting as the network.

### Engineering Sustainable Agents (Astekin et al., Oct 2026)
- Link: https://arxiv.org/abs/2610.03010 [abs only]. Submitted 2 Oct 2026.
- Key numbers: multi-agent designs use about 6.36x the energy and 6.07x the time of a non-agentic baseline on average; "Lightweight non-agentic and single-agent configurations still dominate the Pareto front", 59 of 66 Pareto-optimal configurations. Accuracy gains "limited and task-specific", with vulnerability detection the stated exception.
- Relevance: threatens the premise on software-engineering tasks; not a pruning paper.

### Mixture-of-Agents and Self-MoA (the dense network's architecture)
- MoA (Wang et al. 2024): https://arxiv.org/abs/2406.04692 [abs only]. "Each agent takes all the outputs from agents in the previous layer as auxiliary information"; an open-source-only MoA scores 65.1% vs 57.5% for GPT-4 Omni on AlpacaEval 2.0. This is exactly the dense fan-in pattern used here.
- Self-MoA (Li et al. 2025): https://arxiv.org/abs/2502.00674 [abs only]. Aggregating outputs from only the single best LLM beats mixing different models: +6.6% on AlpacaEval 2.0 and +3.8% on average over MMLU, CRUX and MATH. Relevant because the project's agents are one model with different perspective prompts, so diversity comes only from sampling and prompts.

### Where multi-agent did beat a single agent or self-consistency, at what budget

| Source | Condition | Result | Budget match |
|---|---|---|---|
| Kim et al. 2512.08296 | decomposable, parallelizable financial reasoning (Finance-Agent) | +73.1% to +80.8% relative over single agent | matched reasoning tokens, mean 4,800 per trial |
| Kim et al. | web browsing (BrowseComp-Plus), tool use (Workbench) | +9.2% and +5.6% (Decentralized) | same |
| Wunderlich 2605.01566 | MMLU-Pro and BBH | debate +1.3pp, MoA +2.7pp over self-consistency | equal compute budget |
| Jwalapuram 2606.13003 | HLE-Math with GPT-5 and Gemini-2.5-Pro; GPT-5 and GPT-OSS with DyLAN or MAS-Orchestra | +4.3 to +6.6pp | not cost-matched: 1.9x to 5x CoT-SC cost |
| Jwalapuram | expert-designed MAS on a decomposition benchmark | 57.0% to 96.5% (GPT-5) | comparable to CoT-SC cost |
| Hu et al. 2605.09618 | per-example oracle choice among greedy, voting, debate | +14.0 and +13.7pp over best fixed protocol | 960-token cap |
| BenchAgent 2606.05670 | EvoAgent pooled over ten benchmarks, GPT-4.1 | 79.70 vs 76.65 | token ratio not given on the page |
| DyLAN 2310.02170 | team selection on some MMLU subjects | up to 25.0% accuracy gain | not compared with a single agent in the abstract |

The pattern in these sources: wins come on decomposable or parallelizable tasks, when the single agent is weak (under about 45% in Kim et al.), when the design is written by experts, or when the margin is small (1 to 3 points) and mostly available to voting-like aggregation.

---

## Topic 3. Cache-aware cost evaluation of agent systems

### Anthropic pricing page (the provider's page; the source for the project's cost model)
- Link: https://platform.claude.com/docs/en/about-claude/pricing (opened 2026-10-18)
- Key numbers: **Claude Haiku 5.5 (prompts up to 100,000 tokens): $0.10 input, $0.125 5-minute cache write, $0.20 1-hour cache write, $0.01 cache hit, $0.50 output, per MTok.** Prompts over 100,000 tokens: $0.50, $0.625, $1, $0.05, $2.50. Batch API: $0.05 input and $0.25 output (up to 100,000 tokens). "A request's prompt length counts all of its input tokens, including cache reads and cache writes." Multipliers (from the caching docs page below): "5-minute cache write tokens are 1.25 times the base input tokens price", 1-hour writes 2 times, "Cache read tokens are 0.1 times the base input tokens price".
- Check against the repo: `configs/pricing.yaml` has `claude-haiku-5-5: {input: 0.10, output: 0.50, cache_write: 0.125, cache_read: 0.01}`, which matches. The file has no 1-hour write price and no over-100,000-token tier; neither matters at the prompt sizes of this network.
- Relevance: **cost.** Once cache reads cost $0.01, a cached input token costs one fiftieth of an output token. Illustration (my arithmetic, assumed sizes): an agent call with a 3,000-token cached prefix and 500 output tokens costs 3,000 x $0.01/1e6 = $0.00003 for input and 500 x $0.50/1e6 = $0.00025 for output. Output dominates. Pruning an agent then saves mostly its output tokens plus the write cost of the larger downstream prefix. It saves much less of the fan-in input cost than raw token counts suggest, because cached input is cheap. This is an inference from the quoted prices, not a result from a paper.

### Anthropic prompt-caching docs
- Link: https://platform.claude.com/docs/en/build-with-claude/prompt-caching (opened 2026-10-18)
- Key numbers (quoted): minimum cacheable prompt for Claude Haiku 5.5 is 512 tokens; "Cache hits require 100% identical prompt segments, including all text and images up to and including the block marked with cache control"; prefixes are built in the order `tools`, `system`, `messages`; "By default, the cache has a 5-minute lifetime" refreshed on each use; "a cache entry only becomes available after the first response begins. If you need cache hits for parallel requests, wait for the first response before sending subsequent requests."
- Relevance: **cost.** This matches the CLAUDE.md rule on identical prefixes. The executor already warms the cache: `autoagentnet/network/executor.py` lines 151 to 155 await the first request of a stage and then gather the rest, which is what the docs ask for. It does so only when the shared prefix is estimated at `cache_min_tokens` (default 512, equal to the documented Haiku 5.5 minimum) or more. A dense stage that meets this should cost one write at 1.25x and five reads at 0.1x. Sending the six calls concurrently would instead pay near-full price for several of them. The first stage's shared prefix is only the task text, which can fall under 512 tokens and then gets no caching at all.
- Open questions: does the 5-minute lifetime hold across the 216-config enumeration order, so that configs sharing a prefix run close together?

### Don't Break the Cache: An Evaluation of Prompt Caching for Long-Horizon Agentic Tasks (Lumer et al., 2026)
- Link: https://arxiv.org/abs/2601.06007. v1 9 Jan 2026, v2 31 Jan 2026.
- What it does: measures cost and time to first token for OpenAI, Anthropic and Google across more than 500 agent sessions with 10,000-token system prompts on DeepResearch Bench, with three caching strategies.
- Key numbers: "prompt caching reduces API costs by 41-80% and improves time to first token by 13-31% across providers". Benefits are roughly linear in prompt size once the minimum is met. Dynamic content at the end of the prompt, and excluding dynamic tool results from the cache, work best.
- Relevance: **cost**, supports the cache-aware accounting. The setting is single-agent multi-turn tool use, not multi-agent fan-in, and the models are not named on the page.

### Cache-Aware Prompt Compression: A Two-Tier Cost Model for LLM API Caching (Song, 2026)
- Link: https://arxiv.org/abs/2607.15516 [abs only]. Submitted 17 Jul 2026, single author.
- Key numbers: "Sonnet's cache has a two-tier architecture with a sharp threshold near 3,500 tokens"; hit rate "plateaus at about 0.83 below the threshold, versus the 1.0 ideal assumed in the literature".
- Relevance: **cost, caution.** This conflicts with the 512-token minimum in the official docs for Haiku 5.5 and was measured on Sonnet. I cannot reconcile them. Measure `cache_read_input_tokens` on real Haiku 5.5 calls in P0 and do not assume a hit rate of 1.0.

### AI Agents That Matter (Kapoor et al., 2024)
- Link: https://arxiv.org/abs/2407.01502 [abs only]
- Key numbers: "SOTA agents are needlessly complex and costly"; benchmarks have a "narrow focus on accuracy without attention to other metrics"; the authors propose "jointly optimizing" accuracy and cost.
- Relevance: supports the accuracy-versus-cost framing and a Pareto presentation.

### Checked, nothing usable on caching
- Token Economics for LLM Agents (https://arxiv.org/abs/2605.09104) [abs only]: a survey; the abstract does not mention cached-input pricing.
- The efficiency audit 2609.05933 and MaAS report token counts; AgentSlimming reports USD from billing rates. None of the pages I read models cache reads and writes in MAS cost.

---

## Topic 4. Prompt re-tuning after pruning (the analog of fine-tuning after pruning)

### Multi-Agent Design: Optimizing Agents with Better Prompts and Topologies (MASS, ICLR 2026)
- Link: https://arxiv.org/abs/2502.02533 (HTML: https://arxiv.org/html/2502.02533). v1 4 Feb 2025, v2 31 Jan 2026.
- What it does: three stages, each conditioned on the previous: block-level prompt optimisation (1PO), topology optimisation in a pruned search space (2TO), workflow-level prompt optimisation on the best topology (3PO). Topology choices are pruned by an influence score `I = E(a*) / E(a0*)` with a softmax at temperature 0.05.
- Key numbers (quoted): "there is a large gain, 6% on average, between block-level optimization and single-agent APO"; "another 3% gain can be achieved by composing influential topologies"; the text says 3PO adds "~2%", but Table 6 shows the average rising from 77.55 to 78.40, about 0.85 points, with per-task changes from -1.21 (MuSiQue) to +4.69 (HotpotQA). Optimisation cost (Table 7): 24M input and 11M output tokens, about $5.09 on Gemini 1.5. Models Gemini 1.5 Pro and Flash; validated on Claude 3.5 Sonnet and Mistral Nemo 12B.
- Relevance: **supports**, as the closest analog of "tune after the structure is fixed", and a cost reference. The final prompt pass gives small, task-dependent gains. It adds structure; it does not remove agents.
- Cost note (my arithmetic): 24M input and 11M output at Haiku 5.5 list prices would be 24 x $0.10 + 11 x $0.50 = $7.90 before any caching, which is about 40% of the $20 pilot cap.
- Open questions: nobody has measured whether the 3PO gain is larger after agents are removed, which is the claim the "fine-tune after pruning" analogy implies.

### Optimizing Instructions and Demonstrations for Multi-Stage Language Model Programs (MIPRO, EMNLP 2024)
- Link: https://arxiv.org/abs/2406.11695 [abs only]
- Key numbers: optimises "the free-form instructions and few-shot demonstrations of every module" without module-level labels; "outperforms baseline optimizers on five of seven diverse multi-stage LM programs" with Llama-3-8B; up to 13% accuracy. The abstract does not give the call budget.
- Relevance: supports per-stage prompt tuning for a staged program. Cost unknown.

### TextGrad (2024)
- Link: https://arxiv.org/abs/2406.07496 [abs only]
- Key numbers: GPT-4o zero-shot on GPQA from 51% to 55%; "about a 20% relative performance gain" on LeetCode-Hard.
- Relevance: a candidate optimiser for a post-pruning prompt pass. No pruning experiment.

### MAS-PromptBench (2026)
- Link: https://arxiv.org/abs/2606.23664 [abs only]. Submitted 22 Jun 2026.
- Says it studies "whether, when, and by how much prompt optimization improves MAS performance", varying workflow, communication protocol and team size. The abstract has no numbers. Read the full text before relying on it for team-size effects.

### Re-tuning after pruning: the state of the evidence
- A targeted search found no paper that removes agents and then re-tunes prompts to recover accuracy [search, nothing opened to the contrary]. MASPO (https://arxiv.org/pdf/2605.06623) and MAPRO (https://arxiv.org/pdf/2510.07475) appeared in search results as joint multi-agent prompt optimisers [snippet, not opened].
- AMC's own recipe is the cleanest analog: search without fine-tuning, then fine-tune the winner only.

---

## Not opened, or not resolved

- GPTSwarm PDF returned binary; the HTML v3 was used instead.
- MasRouter: a search returned nothing; not assessed.
- Semantic Scholar was not used.
- Venue claims for EIB-Learner (EMNLP 2025), Optima (ACL 2025 Findings), AgentDropout (ACL 2025), AgentConductor (ICML 2026) and Graph-GRPO (Findings of ACL 2026) come from search snippets or arXiv comment fields; the abstract pages for EIB-Learner and Optima did not confirm them.
- DAGP and the full text of SafeSieve, S2-MAD, Graph-GRPO, Codebook Agent, RGA-Designer and several abstract-only audits were not read beyond their abstract pages.
- The exact phrase "September 2026 efficiency audit" was not found anywhere; 2609.05933 is a best match by date and subject.

---

## So what

### Novelty verdict: (b) novel only with re-scoping

"First to learn per-stage keep ratios with a cost-aware reward" is not safe. MaAS learns per-layer unit counts with a token-cost penalty, AgentSlimming prunes agents under a dollar budget, AGP learns agent counts, DyLAN and SMoA do per-layer top-k, AgentDropout drops nodes per round. The protocol's P1 kill criterion ("a prior paper already learns per-stage ratios with a cost-aware reward") is partly met by MaAS, so re-scope before paid work, as the protocol says.

What I found nobody has done, within the pages I opened:
1. A static, per-stage keep ratio for identical agents in a fixed propose, critique, refine, aggregate pipeline, chosen by an AMC-style continuous controller with a budget by construction.
2. Cost as cache-aware dollars (reads at 0.1x, writes at 1.25x, output at 5x input) rather than token counts.
3. A direct comparison of joint search against stage-by-stage sensitivity analysis at matched cost (H1). AgentSlimming's greedy leave-one-out and DyLAN's top-k are local methods, and neither is compared with a joint search.
4. A label-free reward defined as agreement with the dense network (H3).
5. Matched random pruning and single-agent controls as the primary outcome, not a robustness check (H4).

### Changes to make in `research/plan.md`

1. **Rewrite the novelty claim.** Cite MaAS, AGP, AgentSlimming, DyLAN, AgentDropout and AgentConductor as nearest work, and state the five gaps above. Frame the contribution as "which stage can be pruned, and do stages interact", not as a better pruner. The sources suggest per-query policies (MaAS, AGP, AgentConductor, the oracle in Hu et al.) may beat any static ratio, so do not claim state of the art.
2. **Make H4 the primary outcome.** The September audit found AgentPrune and AgentDropout within about 0.2 points of matched random pruning, and the project's n=6 is the audit's anchor size. Report the keep-ratio pick minus matched-cost random pruning with a bootstrap interval. Enforce at least one agent per stage; the audit shows structural collapse (93.78 to 7.51 for one method on one topology).
3. **Add controls and baselines to the offline analysis** (free once the landscape table exists): matched-cost random pruning; uniform keep across stages; greedy stage-by-stage or leave-one-out (the H1 comparator, AMC's handcrafted-policy analog); a DyLAN-style fixed top-k; a MaAS-style `lambda * C` scalarisation. For the gate, add a self-consistency control at roughly the dense network's dollar cost, because Choi et al., Tran and Kiela and Jwalapuram et al. all report that voting or self-consistency matches or beats debate-style networks. Estimate its extra cost with `--model-override fake` before running it; I have not priced it.
4. **State how cost enters the objective.** Three published options: AMC bounds the action space so the budget always holds (best for matched-cost comparisons); MaAS adds `lambda * C`; CoRL multiplies reward by a budget indicator. Record the choice and the reason.
5. **Cost model.** Keep `configs/pricing.yaml`; it matches the official page. Note in the plan that output tokens dominate once reads cost $0.01 per million, so pruning savings are roughly proportional to calls and output length. Measure the real cache-read share in P0 rather than assuming it (the 3,500-token threshold claim in 2607.15516 conflicts with the docs). Price single-agent and self-consistency controls with the same cache accounting. Keep the cache warm-up and locality of config order in mind for the 216-config run (5-minute lifetime).
6. **H1 and H2 priors.** DyLAN's Table 8 (6/6: 76.2, 4/4: 82.9, 3/3: 78.0, 4/2: 77.4) is published evidence that the optimum is interior and depends on both layers jointly. EIB-Learner's "moderately sparse" result points the same way. Treat them as motivation, not as confirmation: no confidence intervals were visible.
7. **H3 expectation.** Agreement-with-dense is TTRL-like and can at best track dense accuracy. It cannot reward fixing the dense network's confident errors (Hu et al.: 66% of debate-helpful cases are unanimous-but-wrong). Pre-register that H3 should hold best on tasks where dense accuracy is high, and report agreement alongside accuracy to show where it breaks.
8. **Gate task selection.** Prefer candidate tasks with decomposable structure and a single-agent accuracy below about 45%; Kim et al. report negative returns above that and large losses on sequential tasks, and the propose, critique, refine chain is sequential.
9. **Defer prompt re-tuning.** No paper tests it after removing agents. Following AMC, search without re-tuning and, if budget remains, re-tune only the winner. MASS-scale optimisation at Haiku 5.5 prices is about $7.90 before caching, too large for the $20 pilot. The expected gain is one to two points (MASS 3PO).
10. **Wording.** The protocol's "debate-style networks do not beat a single agent" should cite specific sources: 2609.05933 (efficiency methods), 2606.13003 and 2508.17536 and 2604.02460 (debate against self-consistency or voting), 2512.08296 (task dependence). Say "often" and keep the exceptions in the table in Topic 2.
