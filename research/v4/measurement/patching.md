# Patch-based inference for agent networks (session M1, addendum 2; theory and $0 numbers)

Status: a theory note with cached-data numbers. No call was made for it. The experiment that would test it is
designed in `patching_prereg_draft.md` and has not been run. The numbers section is written by
`analysis/patch_context.py`.

## 1. The idea in plain words

A vision transformer cuts an image into patches so that no single attention step has to read everything. A
convolutional network reads small overlapping windows first and widens its view layer by layer. An agent network has
the same choice. Its "image" is the set of messages the agents of one stage write. The question is how much of it
each agent of the next stage reads.

- **Full reading** (what the pilot's dense 6-6-6-1 network does). Every agent of a stage reads all n messages of
  the stage before.
- **Patching** is fan-in f < n. In `autoagentnet/network/spec.upstream_indices`, agent i reads the circular window
  of f messages starting at i.
  - Two neighbouring windows overlap by f - 1 messages, like overlapping patches with a halo.
  - Fan-in 1 is the extreme case: each agent reads one proposal.
- **Compression**. Every agent reads all n messages, but each message is cut to the answer plus a short reason.
- **Redistribution** combines the two:
  - small fan-in early, where messages are long and the work is local (checking one proposal);
  - a global view later, over compressed messages, where the work is to combine.

## 2. Context: what one call has to hold

Terms:

- B is the base context: system prompt, task and the stage's instruction, which every agent reads.
- L is the length of one message in tokens. Here that is the reply's output tokens, which is what is passed
  downstream.
- c is the compression ratio: compressed length over full length.

Peak context of one call:

| reading | context of one agent |
|---|---|
| full | B + nL |
| patched (fan-in f) | B + fL |
| compressed | B + ncL |

The KV cache an engine must hold grows with context (`autoagentnet/testbed/kv.py`). So does the time to process the
prompt, and so does the chance that a model loses track in a long input. Peak context is the network's memory
analogue, as it was in the pilot.

## 3. Input dollars: what caching changes

With prompt caching, a prefix that m agents share is written once (price w per token) and read m - 1 times (price r).
For Haiku 5.5, r/w = 0.01/0.125 = 0.08. Per stage, the input dollars are:

| reading | input dollars of one stage |
|---|---|
| full | (B + nL)(w + (m - 1)r) |
| patched | B(w + (m - 1)r) + m f L w (windows share no prefix, so each is written and never read) |
| compressed | (B + ncL)(w + (m - 1)r) |

Patching saves input dollars only when the windows together cost less than the shared full prefix:
m f L w < n L (w + (m - 1)r), that is, f/n < (1 + (m - 1)r/w)/m.

- For Haiku with m = 6 the bound is (1 + 5 × 0.08)/6 = 0.233.
- With n = 6 that means f < 1.4: only fan-in 1 saves input dollars.
- Fan-in 2 and 3 cut peak context but cost more, because the cache discount on a shared prefix (92% off) is larger
  than the saving from reading fewer messages.
- Compression cuts both, since it keeps the prefix shared.

The executor as built (audit M1-1) bills patching differently. Under fan-in it sends the whole non-shared block
uncached, at the input price p, and that block is the task plus the window. Only the system prompt stays a cached
shared prefix. So the task, which every agent shares, also loses its cache discount.

On the pilot's critique stage this makes patching dearer than the stylized model says:
- fan-in 1: +2% input dollars against full reading (stylized: -24%);
- fan-in 2: +50% (stylized: +36%).

**As implemented, patching never saves input dollars on a cached API.** Saving them would need the executor to keep
the task inside the cached prefix and put the window after the breakpoint, which is a code change.

## 4. Reach: how many proposals can influence the answer

Consecutive circular windows compose like stacked convolutions.

- Two patched stages of fan-in f and f' let a final agent depend on f + f' - 1 of the original proposals.
- For example, fan-in 2 then 2 reaches 3 of 6.
- Any later stage that reads all messages restores full reach. In the redistributed design, the aggregator reads
  every refined message, so the final answer can depend on all six proposals.

## 5. Evidence kept

Suppose the errors of the n proposals correlate at rho. Then f messages are worth n_eff(f) = f / (1 + (f - 1) rho)
independent proposals (protocol section 8).

With the pilot's Haiku proposers, rho = 0.43 (reports/pilot/report.md, H6):

- all six are worth 1.90;
- f = 2 is worth 1.40, i.e. 73% of all six's evidence;
- f = 2 needs about 48% of the critique stage's peak context.

So because the proposers are strongly correlated, most of what a critic learns from six proposals it already learns
from two.

## 6. Numbers from the pilot's real messages ($0, cached)

<!-- numbers -->
Pilot dense runs replayed from the cache: 100 BBEH gate items, Haiku thinking off (`analysis/patch_context.py`; $0). Mean over tasks.

Messages: propose replies average 1238 output tokens; their last two paragraphs (the measured answer-plus-reason cut: the concluding statement and the ANSWER line) 84 tokens (median 46), i.e. c = 0.07.

Input $ is the note's stylized model (windows at the cache-write price); executor $ is what the executor would bill (a non-shared prefix is sent uncached at the input price; audit M1-1).

| stage | variant | peak context | vs full | input tokens (stage) | input $ (stylized) | vs full | executor $ | vs full |
|---|---|---|---|---|---|---|---|---|
| critique | full | 8,853 | +0% | 53,117 | 0.001549 | +0% | 0.001549 | +0% |
| critique | fan-in 3 | 5,493 | -38% | 30,828 | 0.003035 | +96% | 0.003065 | +98% |
| critique | fan-in 2 | 4,254 | -52% | 23,398 | 0.002106 | +36% | 0.002322 | +50% |
| critique | fan-in 1 | 2,975 | -66% | 15,968 | 0.001178 | -24% | 0.001579 | +2% |
| critique | compressed (measured) | 1,926 | -78% | 11,557 | 0.000337 | -78% | 0.000337 | -78% |
| critique | compressed (80 tokens) | 1,903 | -79% | 11,419 | 0.000333 | -79% | 0.000333 | -79% |
| refine | full | 5,738 | +0% | 34,427 | 0.001004 | +0% | 0.001004 | +0% |
| refine | fan-in 3 | 3,772 | -34% | 21,518 | 0.001865 | +86% | 0.002134 | +113% |
| refine | fan-in 2 | 3,054 | -47% | 17,216 | 0.001327 | +32% | 0.001704 | +70% |
| refine | fan-in 1 | 2,313 | -60% | 12,913 | 0.000789 | -21% | 0.001273 | +27% |
| refine | compressed (measured) | 2,002 | -65% | 12,011 | 0.000350 | -65% | 0.000350 | -65% |
| refine | compressed (80 tokens) | 1,915 | -67% | 11,490 | 0.000335 | -67% | 0.000335 | -67% |
| aggregate | full | 5,371 | +0% | 5,371 | 0.000671 | +0% | 0.000671 | +0% |
| aggregate | fan-in 3 | 3,389 | -37% | 3,389 | 0.000424 | -37% | 0.000340 | -49% |
| aggregate | fan-in 2 | 2,666 | -50% | 2,666 | 0.000333 | -50% | 0.000268 | -60% |
| aggregate | fan-in 1 | 2,023 | -62% | 2,023 | 0.000253 | -62% | 0.000204 | -70% |
| aggregate | compressed (measured) | 1,857 | -65% | 1,857 | 0.000232 | -65% | 0.000232 | -65% |
| aggregate | compressed (80 tokens) | 1,896 | -65% | 1,896 | 0.000237 | -65% | 0.000237 | -65% |

Evidence kept (rho = 0.43): f = 1: n_eff 1.00, f = 2: n_eff 1.40, f = 3: n_eff 1.61, f = 6: n_eff 1.90; f = 2 keeps 73% of all six's n_eff.

Batching (8.5a): share of a call's base context that is shared instructions (median over items):

| family | items | shared_chars | item_chars_median | instruction_share |
|---|---|---|---|---|
| bbeh | 3696 | 107 | 1971.0 | 0.051 |
| math | 93 | 136 | 1197.0 | 0.102 |
| forecast | 4131 | 244 | 1532.0 | 0.137 |
| code | 242 | 284 | 1404.5 | 0.168 |
| pilot network: propose (task only, before upstream messages) | 3696 | 188 | 1971.0 | 0.087 |
| pilot network: critique (task only, before upstream messages) | 3696 | 224 | 1971.0 | 0.102 |
| pilot network: refine (task only, before upstream messages) | 3696 | 237 | 1971.0 | 0.107 |
| pilot network: aggregate (task only, before upstream messages) | 3696 | 216 | 1971.0 | 0.099 |

Agent loops (8.4): market traders' context by step (turns.csv; each turn shows the current book, not the trader's history):

| run | steps | first_context | last_context | peak_context |
|---|---|---|---|---|
| m1_smoke | 15 | 781.0 | 808.0 | 811 |
| m2_haiku | 39 | 779.0 | 833.0 | 841 |
| m3_sonnet | 39 | 780.0 | 829.0 | 836 |
| m4_mixed_even | 39 | 782.0 | 832.0 | 836 |
| m4_mixed_odd | 39 | 781.0 | 830.0 | 836 |

<!-- /numbers -->

Reading the numbers:

- The critique stage reproduces the first pass (stylized dollars):
  - full peak context about 8,850 tokens;
  - fan-in 2: -52% at +36% input dollars;
  - fan-in 3: -38% at +96%;
  - fan-in 1: -66% at -24%;
  - compression to 80 tokens per message: -79% on both.
- As the executor bills it, every fan-in costs more than full reading: fan-in 1 +2%, fan-in 2 +50%, fan-in 3 +98%.
  Compression is the same in both models.
- The measured answer-plus-reason cut replaces the 80-token placeholder. It keeps each reply's concluding statement
  and its ANSWER line, which averages about 84 tokens per proposal (median 46), so the placeholder was about right.
- **What the cache cannot say.** These are context and input-dollar numbers only. A patched or compressed network's
  critics read different inputs, so they write different messages. Output tokens, latency and accuracy therefore
  need new calls. A communicating network does not replay; only a vote or an early exit over existing answers does.

## 7. Agent loops: temporal patching (8.4)

A single agent that works in a loop (read, act, observe, repeat) re-reads its whole history at every step. Its
context grows step by step, so its peak is at the end. That is the opposite of a CNN, whose widest layers come first.

Two common fixes are patching in time:

- **Compaction** replaces old steps with a summary. It is compression along the time axis.
- **Sub-agents** take a piece of the work with a fresh context and return a short result. The halo is the shared
  context each sub-agent must re-read: the task, and the part of the history it is given.

The same trade-offs as above apply:

- peak context falls;
- input dollars depend on whether the re-read halo is a cached shared prefix;
- reach is restored only if some step reads every sub-agent's result.

**Data in this repo.** The only per-step logs are the market sessions (`results/m*/turns.csv`; table above).

- A trader's context stays nearly flat over a session: about 780 to 830 tokens over up to 39 steps. Each turn shows the
  current book, not the full history.
- So these logs are a stateless loop and cannot show the growing-context profile.

**What would test it.** Agent trajectories on SWE-bench (for example SWE-bench Verified runs of mini-swe-agent, whose
per-step messages are public). They give:

- context per step;
- where compaction would cut;
- how often a later step re-reads an early observation (the halo a sub-agent would need).

Not downloaded here.

## 8. Batching (8.5)

**(a) Several items per call** amortises only what the items share: the system prompt and instruction. The task text
is never shared. The shared-instruction share of the base context, per task family, is in the table above.

- It is small: about 5% on BBEH and 10-17% on math, forecasting and code.
- So batching items saves little input, and it puts all items into one longer context.

**(b) On the GPU**, continuous batching with automatic prefix caching makes extra samples of one prompt cheap in
prompt KV. vLLM stores a shared prefix once (`kv.configuration_kv_bytes`), so k samples cost the prefix once plus k
outputs. Chunked prefill splits a long prompt's prefill into pieces scheduled with other requests' decoding, which
bounds peak prefill memory. That is engine-level patching.

- The testbed's serve command turns prefix caching on.
- Each `sample` run records what the server reports in `serve_card-<checkpoint>.json`.
- vLLM does not report chunked prefill (a scheduler setting).

**(c) Provider batch APIs** halve the price but change neither context nor latency to the first token in a useful
way: results come back within hours.

## 9. Hypotheses for the draft prereg

See `patching_prereg_draft.md`:

1. Fan-in 2 at critique stays within 2 points of full accuracy at about half the peak context.
2. Compression beats patching on both peak context and input dollars.

Neither has been tested.
