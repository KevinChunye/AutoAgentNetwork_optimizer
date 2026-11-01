"""Self-or-social pruning: the actions, the first-round snapshot, the revision prompts and the vote.

Terms:
  agent     one member of the team (A, B, C): a model ref, the call index of its first answer (the call cache's
            replicate number) and its max_tokens. Its first answer uses the evidence panel's base prompt word for
            word (evidence/prompts.py), so first answers already paid for by an earlier panel run can be reused.
  snapshot  the team's first-round replies to one item, frozen before any revision. Every revision reads the
            snapshot, never another agent's revision, so the order in which revisions run cannot change any input.
  action    what one agent (the receiver) does after the snapshot:
              stop        keep its first answer; no model call;
              reflect     re-check its own first reply alone; one call; it reads no peer text;
              consult:J   read agent J's first reply next to its own and revise; one call.
            Each agent takes at most one action, so an item costs at most n first answers plus n revisions.
  branch    one possible revision call (receiver, action). For n agents an item has n reflect branches and
            n(n-1) consult branches; a calibration run makes all of them, so every policy and baseline can be
            scored from one table (the action depends only on the snapshot, so the scored call is the call a
            deployed policy would make: same request, same cache key).
  full      the full-review control: every agent reads both other first replies and revises once.

The final answer of the team is the plurality of its members' final answers (`vote`), ties broken by a fixed
member order frozen before the test.

Task kinds (`kind`, a config's `task_kind`; default bbeh):
  bbeh   BIG-Bench Extra Hard. First answer: the evidence panel's bbeh base request; graded by the panel's bbeh path.
  math   MathArena arXiv problems. First answer: the evidence panel's math base request (answer in \\boxed{} on the
         last line). Read and graded as the E5 anchor's read grades math (analysis/anchor_read.regrade_math): the
         last box (else an ANSWER line), read by mathread.math_read, compared by math-verify (tasks.answers_match,
         grader math) with the gold under mathread.normalize_math. The answer is read as against a gold without "="
         (math_read uses the gold only to ask whether it holds "=", and no ArXivMath gold does), so a member's answer,
         its vote and its agreement state never depend on the gold; on a gold holding "=" the read would differ. The
         panel's run-time `correct` column compares the raw answer instead and undercounts (Sol low's 93 first
         answers: 17 correct as stored, 34 as read).
  mcq    multiple choice. The evidence panel has no such kind, so its prompts (MCQ_SYSTEM, MCQ_INSTRUCTION) are new
         and no earlier panel call is ever a cache hit for its first answers. The reply ends with "ANSWER: <letter>";
         the answer is that option letter, graded by exact letter match (the "choice" grader); a line naming several
         letters ("B or C") is a hedge and stays unparsed.
Only the system text and the final answer-format line of the revision prompts depend on the kind; their body is the
same for every kind (bbeh's prompts are word for word those used before the kinds were added).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ..agents.spec import AgentInput, AgentRequest, AgentSpec, Upstream
from ..evidence import prompts as P
from ..evidence.mathread import math_read, normalize_math
from ..evidence.panel import REFUSAL_STOP_REASONS, grade
from ..providers.base import TRUNCATED_STOP_REASONS
from ..tasks import MULTI_LETTER_RE, Task, answers_match, choice_letter, extract_answer
from ..tasks import parse_answer as math_parse

KINDS = ("bbeh", "math", "mcq")
GRADER_OF = {"bbeh": "bbeh", "math": "math", "mcq": "choice"}  # the grader a kind's task file must name

MCQ_SYSTEM = 'Answer the multiple-choice question. Be concise. End with a final line of the form "ANSWER: <letter>".\n'
MCQ_INSTRUCTION = "Answer the question above.\n"

STOP, REFLECT, CONSULT = "stop", "reflect", "consult"


def consult(peer: str) -> str:
    """The action name of consulting agent `peer`, e.g. consult:B."""
    return f"{CONSULT}:{peer}"


def kind_of(action: str) -> str:
    """stop, reflect or consult."""
    return action.split(":", 1)[0]


def peer_of(action: str) -> str | None:
    """The consulted agent of a consult action; None for stop and reflect."""
    return action.split(":", 1)[1] if action.startswith(CONSULT + ":") else None


class Agent(BaseModel):
    """One team member. `call` is the replicate number of its first answer (0 reuses an earlier panel's call 0)."""

    model_config = ConfigDict(extra="forbid")
    id: str
    ref: str
    call: int = 0
    max_tokens: int = 4000


def actions_for(receiver: str, team: list[Agent]) -> list[str]:
    """Every legal action of one receiver: stop, reflect, and consult of each other member, in team order."""
    return [STOP, REFLECT] + [consult(a.id) for a in team if a.id != receiver]


def check_kind(kind: str) -> str:
    if kind not in KINDS:
        raise ValueError(f"unknown task kind {kind!r}; known: {', '.join(KINDS)}")
    return kind


def system_of(kind: str) -> str:
    """The system text of every call of a kind: the evidence panel's for bbeh and math (prompts.SYSTEMS), MCQ_SYSTEM
    for mcq."""
    return MCQ_SYSTEM if check_kind(kind) == "mcq" else P.SYSTEMS[kind]


def base_instruction(kind: str) -> str:
    """Block 2 of a first answer: the evidence panel's base instruction for bbeh and math, MCQ_INSTRUCTION for mcq."""
    return MCQ_INSTRUCTION if check_kind(kind) == "mcq" else P.instruction(kind, "base")


SYSTEM = system_of("bbeh")  # the BBEH system (the name every BBEH caller used before the kinds were added)

# The final line each kind's revision asks for: the answer format its system text asks for.
ANSWER_LINE = {
    "bbeh": 'End with a final line of the form "ANSWER: <answer>".\n',
    "math": "Give one final answer in closed form, written inside \\boxed{} on the last line.\n",
    "mcq": 'End with a final line of the form "ANSWER: <letter>".\n',
}
REFLECT_BODY = (
    "Above is your earlier reply to the task. Check it against the task: re-read the question, verify each step "
    "and each condition, and fix any mistake you find; if it holds, keep its answer. Be concise. "
)
CONSULT_BODY = (
    "Above are your earlier reply to the task and a teammate's reply; either may be wrong. Check both against the "
    "task, decide which reasoning holds, and give your final answer; change your answer only for a concrete reason. "
    "Be concise. "
)
FULL_BODY = (
    "Above are your earlier reply to the task and two teammates' replies; any of them may be wrong. Check them "
    "against the task, decide which reasoning holds, and give your final answer; change your answer only for a "
    "concrete reason. Be concise. "
)


def revision_instruction(action_kind: str, kind: str = "bbeh") -> str:
    """Block 2 of a revision: the body of a reflect, consult or full action, then the kind's answer-format line."""
    body = {REFLECT: REFLECT_BODY, CONSULT: CONSULT_BODY, "full": FULL_BODY}[action_kind]
    return body + ANSWER_LINE[check_kind(kind)]


REFLECT_INSTRUCTION = revision_instruction(REFLECT)  # the BBEH texts, word for word as before the kinds were added
CONSULT_INSTRUCTION = revision_instruction(CONSULT)
FULL_INSTRUCTION = revision_instruction("full")
OWN_LABEL, PEER_LABEL = "your earlier reply", "teammate"


def initial_request(agent: Agent, item: Task, model: str, kind: str = "bbeh") -> AgentRequest:
    """The first-answer request: the evidence panel's base source for this ref and task kind, field for field
    (evidence/panel.py requests_for: agent id "<ref>.base", stage "panel_<kind>", index 0, the kind's system and base
    instruction, the member's max_tokens, no temperature, the task text as a shared prefix), so its cache key is the
    panel's. `model` is the ref actually called (the fake model in a dry run); the agent id names the ref as written."""
    spec = AgentSpec(agent_id=f"{agent.ref}.base", stage=f"panel_{check_kind(kind)}", index=0, model=model,
                     system=system_of(kind), instruction=base_instruction(kind), max_tokens=agent.max_tokens,
                     temperature=None)
    return AgentRequest(spec=spec, input=AgentInput(task_id=item.id, task=item.prompt, shared_prefix=True))


def revision_request(agent: Agent, index: int, action: str, item: Task, replies: dict[str, str], model: str,
                     kind: str = "bbeh") -> AgentRequest:
    """One revision call of `agent` (team position `index`) for a reflect, consult:J or full action.

    `replies` is the snapshot: agent id -> first reply text. A reflect reads only the receiver's own first reply;
    consult:J reads the receiver's own and J's; full reads the receiver's own and every other member's, in team
    order. Peers are shown without their model or name. The upstream text is specific to the receiver, so
    shared_prefix is off (a cache write would cost more than it saves). The system text and the instruction's
    answer-format line are the task kind's."""
    own = Upstream(agent_id=OWN_LABEL, content=replies[agent.id])
    if action == REFLECT:
        upstream, text = [own], revision_instruction(REFLECT, kind)
    elif action == "full":
        peers = [j for j in replies if j != agent.id]
        upstream = [own] + [Upstream(agent_id=f"{PEER_LABEL} {k}", content=replies[j]) for k, j in enumerate(peers, 1)]
        text = revision_instruction("full", kind)
    elif peer_of(action) is not None:
        peer = peer_of(action)
        if peer == agent.id or peer not in replies:
            raise ValueError(f"{agent.id} cannot consult {peer!r}: not another member of the team")
        upstream, text = [own, Upstream(agent_id=PEER_LABEL, content=replies[peer])], revision_instruction(CONSULT, kind)
    else:
        raise ValueError(f"{action!r} is not a revision (stop makes no call)")
    spec = AgentSpec(agent_id=f"sos.{agent.id}.{action}", stage="sos_revise", index=index, model=model,
                     system=system_of(kind), instruction=text, max_tokens=agent.max_tokens, temperature=None)
    return AgentRequest(spec=spec, input=AgentInput(task_id=item.id, task=item.prompt, upstream=upstream,
                                                    shared_prefix=False))


def mcq_letter(text: str) -> str | None:
    """The option letter of an mcq reply: the last ANSWER line's letter ("ANSWER: B", "ANSWER: (b)", "ANSWER: B) 42"
    all give "B", tasks.choice_letter). None when there is no ANSWER line, it starts with no option letter, or it names
    several ("B or C", "A, C": a hedge, tasks.MULTI_LETTER_RE)."""
    line = extract_answer(text or "")
    if line is None or MULTI_LETTER_RE.match(line):
        return None
    return choice_letter(line)


NO_EQUATION_GOLD = ""  # math_read reads an answer against its gold only through whether the gold holds "="; this stands
# for "a gold without '='", so the read form never depends on the item's gold (every ArXivMath gold is such a gold)


def parse_reply(kind: str, text: str, parser: str = "v2") -> str | None:
    """The final answer of a reply, first answer or revision alike: bbeh, the evidence panel's parser at `parser`;
    math, the last \\boxed{} (else an ANSWER line; the same in every parser version) read by mathread.math_read as
    against a gold without "=" (NO_EQUATION_GOLD); mcq, mcq_letter."""
    if check_kind(kind) == "mcq":
        return mcq_letter(text)
    if kind == "math":
        raw = P.parse_answer("math", text or "")
        return math_read(raw, NO_EQUATION_GOLD) if raw is not None else None
    return P.parse_answer(kind, text or "", parser)


def format_ok(kind: str, text: str) -> bool:
    """Whether the reply carries the final line its prompt asks for (an ANSWER line; for math a box or an ANSWER
    line), whatever a fallback then recovers."""
    if check_kind(kind) == "mcq":
        return extract_answer(text or "") is not None
    return P.format_ok(kind, text or "")


def readable(kind: str, answer: str | None) -> bool:
    """Whether a parsed answer can be graded and voted: math, when math-verify parses its read form; else not None."""
    if answer is None:
        return False
    return kind != "math" or len(math_parse(answer)) > 0


def grade_reply(kind: str, item: Task, reply: str, stop_reason: str | None = None, parser: str = "v2") -> dict:
    """answer, parsed, correct and prob of one reply; a reply stopped on a safety decline is unparsed and wrong, as in
    the panel.
      bbeh  the evidence panel's grade of a base-prompt reply (panel.grade at `parser`), as before the kinds were added;
      math  the anchor read's grade (analysis/anchor_read.regrade_math): answer = parse_reply's read form; parsed when
            math-verify parses it (`readable`); correct when parsed and equal under the math grader to the gold under
            mathread.normalize_math;
      mcq   the option letter (mcq_letter); parsed when there is one; correct when it is the gold's letter.
    math and mcq follow the repo's read rule (research/v4/cd/read.md): a truncated reply (it stopped at max_tokens) is
    unparsed and wrong, with no answer, like a refusal. An unparsed math answer keeps its text (so the stop rules can
    tell an abstention, "\\text{unknown}", from a format failure), but it is wrong and, like every unparsed answer,
    casts no vote (policy.branch_table and score.full_review_items vote only parsed answers; engine.answer_of is
    vote_answer)."""
    if check_kind(kind) == "bbeh":
        return grade(kind, "base", item, reply or "", stop_reason, parser=parser)
    if stop_reason in REFUSAL_STOP_REASONS or stop_reason in TRUNCATED_STOP_REASONS:
        return {"answer": None, "parsed": False, "correct": 0.0, "prob": None}
    answer = parse_reply(kind, reply, parser)
    parsed = readable(kind, answer)
    if kind == "math":
        right = parsed and item.answer is not None and answers_match(normalize_math(item.answer), answer, "math")
    else:
        right = parsed and answers_match(item.answer, answer, "choice")
    return {"answer": answer, "parsed": parsed, "correct": float(right), "prob": None}


def vote_answer(kind: str, text: str, stop_reason: str | None = None, parser: str = "v2") -> str | None:
    """The answer a reply casts in the team's vote and agreement states, None when it casts none. bbeh: parse_reply,
    as before the kinds were added. math and mcq: the graded answer when grade_reply counts it parsed (so a truncated,
    refused or unreadable reply casts no vote)."""
    if check_kind(kind) == "bbeh":
        return parse_reply(kind, text, parser)
    if stop_reason in REFUSAL_STOP_REASONS or stop_reason in TRUNCATED_STOP_REASONS:
        return None
    answer = parse_reply(kind, text, parser)
    return answer if readable(kind, answer) else None


def vote(answers: list[str | None], grader: str, order: list[int] | None = None) -> tuple[str | None, int | None]:
    """The plurality of the members' final answers and the position of the member whose answer is returned.

    Answers equal under the task's grader form one class; unparsed answers (None) are not counted. The largest class
    wins; a tie goes to the class holding the earliest member in `order` (team positions, default team order), and
    the answer returned is that member's. No parsed answer gives (None, None)."""
    order = list(range(len(answers))) if order is None else order
    rank = {pos: r for r, pos in enumerate(order)}
    classes: list[list[int]] = []
    for pos, a in enumerate(answers):
        if a is None:
            continue
        for members in classes:
            if answers_match(answers[members[0]], a, grader):
                members.append(pos)
                break
        else:
            classes.append([pos])
    if not classes:
        return None, None
    best = min(classes, key=lambda m: (-len(m), min(rank[p] for p in m)))
    chosen = min(best, key=lambda p: rank[p])
    return answers[chosen], chosen


def agreement_states(answers: list[str | None], grader: str) -> list[str]:
    """Each member's agreement state in the first round, from the parsed answers only (no gold):
      all_agree  every member has the same answer;
      majority   the member's answer is shared by another member, but not by all;
      minority   the member is alone and the others share one answer;
      split      the member is alone and the others do not share one answer either;
      none       the member's own answer is unparsed.
    These states are what a policy may see; the revision call itself never sees them."""
    n = len(answers)
    states = []
    for i, a in enumerate(answers):
        if a is None:
            states.append("none")
            continue
        same = sum(1 for b in answers if b is not None and answers_match(a, b, grader))
        if same == n:
            states.append("all_agree")
        elif same >= 2:
            states.append("majority")
        else:
            others = [b for j, b in enumerate(answers) if j != i]
            parsed = [b for b in others if b is not None]
            shared = len(parsed) == len(others) and all(answers_match(parsed[0], b, grader) for b in parsed[1:])
            states.append("minority" if parsed and shared else "split")
    return states
