"""The calls of one item: first answers, the revision branches, the full-review control, and a deployed policy.

Every model call goes through `call(request, replicate)`, which is MarketCaller.call in a run (call cache, spend
governor, ledger), so nothing here talks to a provider. First answers already paid for by an earlier panel run can
be passed in as `reused` outputs instead of calls (their recorded dollars still count as the deployment's cost).
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from ..agents.spec import AgentOutput, AgentRequest
from ..tasks import Task
from .policy import Policy
from .protocol import (REFLECT, STOP, Agent, agreement_states, consult, initial_request, peer_of, revision_request, vote,
                       vote_answer)

Call = Callable[[AgentRequest, int], Awaitable[AgentOutput]]

REVISION_REPLICATE = 0  # every revision is sample 0 of its request; a second sample would need a new number


def answer_of(output: AgentOutput, parser: str = "v2", kind: str = "bbeh") -> str | None:
    """The answer a reply casts in the vote (protocol.vote_answer: the task kind's parser, so first answers and
    revisions are parsed alike; for math and mcq a truncated or unreadable reply casts none)."""
    return vote_answer(kind, output.content or "", output.stop_reason, parser)


async def first_replies(call: Call, team: list[Agent], item: Task, model_of: dict[str, str],
                        reused: dict[str, AgentOutput] | None = None, kind: str = "bbeh") -> dict[str, AgentOutput]:
    """Agent id -> first reply. A member with a reused output is not called."""
    reused = reused or {}

    async def one(agent: Agent) -> AgentOutput:
        if agent.id in reused:
            return reused[agent.id]
        return await call(initial_request(agent, item, model_of[agent.ref], kind), agent.call)

    outputs = await asyncio.gather(*(one(a) for a in team))
    return {a.id: o for a, o in zip(team, outputs)}


def branch_actions(team: list[Agent], full: bool = False) -> list[tuple[Agent, int, str]]:
    """Every revision of a calibration item: (receiver, team position, action) for reflect and each consult edge,
    then (with `full`) each member's full review."""
    out = []
    for i, agent in enumerate(team):
        out.append((agent, i, REFLECT))
        out += [(agent, i, consult(peer.id)) for peer in team if peer.id != agent.id]
    if full:
        out += [(agent, i, "full") for i, agent in enumerate(team)]
    return out


async def revisions(call: Call, item: Task, replies: dict[str, AgentOutput], model_of: dict[str, str],
                    actions: list[tuple[Agent, int, str]], kind: str = "bbeh"
                    ) -> list[tuple[Agent, str, AgentOutput | BaseException]]:
    """Run the given revisions concurrently. Each reads the snapshot `replies` only. A failed call is returned as
    its exception (the caller decides; a BudgetExceeded must stop the run)."""
    snapshot = {k: v.content or "" for k, v in replies.items()}
    requests = [revision_request(agent, i, action, item, snapshot, model_of[agent.ref], kind)
                for agent, i, action in actions]
    outputs = await asyncio.gather(*(call(r, REVISION_REPLICATE) for r in requests), return_exceptions=True)
    return [(agent, action, out) for (agent, _, action), out in zip(actions, outputs)]


async def run_policy(call: Call, policy: Policy, team: list[Agent], item: Task, family: str,
                     replies: dict[str, AgentOutput], model_of: dict[str, str], parser: str = "v2",
                     order: list[int] | None = None, kind: str = "bbeh") -> dict:
    """A deployed team on one item: each member decides from its first-round state alone, only the chosen
    revisions are called, and the team votes. Returns the actions, the final answers, the voted answer and the
    calls made (cache hits included)."""
    answers = [answer_of(replies[a.id], parser, kind) for a in team]
    states = agreement_states(answers, item.grader)
    chosen = {a.id: policy.choose(a.id, s, family) for a, s in zip(team, states)}
    todo = [(a, i, chosen[a.id]) for i, a in enumerate(team) if chosen[a.id] != STOP]
    done = await revisions(call, item, replies, model_of, todo, kind)
    errors = [o for _, _, o in done if isinstance(o, BaseException)]
    if errors:
        raise errors[0]
    finals = {a.id: replies[a.id] for a in team}
    finals.update({a.id: o for a, _, o in done})
    final_answers = [answer_of(finals[a.id], parser, kind) for a in team]
    voted, winner = vote(final_answers, item.grader, order)
    return {"states": dict(zip([a.id for a in team], states)), "actions": chosen,
            "first_answers": dict(zip([a.id for a in team], answers)),
            "final_answers": dict(zip([a.id for a in team], final_answers)), "answer": voted,
            "winner": None if winner is None else team[winner].id, "revisions": len(todo),
            "edges": [(peer_of(chosen[a.id]), a.id) for a in team if peer_of(chosen[a.id]) is not None]}
