# Three-minute pitch: Learn when to think alone, and when to ask whom

Status: draft. Every `[number]` in brackets must be filled from `reports/self_or_social/summary.md`, which is
written by `analysis/self_or_social.py read`, and from nowhere else. The demo is a replay of recorded calls
(`reports/self_or_social/demo.html`), and the slide must say so.

## 0:00-0:25 The problem

- More agents are not automatically better. In this repo's earlier pilot, a 19-agent Haiku network did not beat one
  Sonnet call. The difference was not resolved; the report is historical.
- The real question is about the next model call. Should each agent spend it re-checking its own answer, or reading
  a teammate's? And which teammate?

## 0:25-1:05 The mechanism (one demo item)

- Three Haiku agents answer independently. Their answers are frozen.
- Each agent then picks one of three actions:
  - **stop**: no call;
  - **reflect**: re-check alone;
  - **consult J**: read teammate J's answer once.
- Only the edges that are actually used light up. Each agent revises at most once, and the team votes.
- Show the replay page: the first answers, the actions, the lit arrows, the final vote and the dollars.

## 1:05-1:35 How it learns, fairly

- On 200 calibration items, every option is run on the same first answers.
- That measures what reading J does for agent i, compared with i simply re-checking. This is a paired, directed gain:
  J→i is not the same as i→J.
- A small table of estimates is shrunk towards coarser cells and then frozen. No LLM decides whether to meet.

## 1:35-2:30 Results (240 held-out items, frozen before the test)

- Accuracy and dollars per item for each method: vote `[number]`, all-reflect `[number]`, fixed peer `[number]`,
  random matched `[number]`, full review `[number]`, Sonnet alone `[number]`, self-or-social `[number]`.
- Policy minus all-reflect: `[d_acc]` points (95% CI `[lo, hi]`), at `[d_cost]` dollars per item.
- What the policy did:
  - stop `[share]`, reflect `[share]`, consult `[share]`;
  - the most used edge: `[sender→receiver]`.
- If the interval includes 0, say "not resolved". If the result is negative, present it as the finding: on these
  tasks, a teammate's answer is not worth more than re-checking.

## 2:30-3:00 Why it matters

- It is a checkable communication-budget module for existing agent workflows: pay for a peer only where the data
  say the peer beats re-checking.
- Limits: one team, 4 BBEH tasks, items reused from an earlier study (so preregistered-descriptive), and one
  revision round.

## Background number for Q&A (dev first round, $0, from committed anchor replies)

On the 200 dev items, the vote of the three Haiku first answers is right 40.5% of the time. Sonnet low alone is
right 50%. 97 of the 200 items have all three agents agreeing.
