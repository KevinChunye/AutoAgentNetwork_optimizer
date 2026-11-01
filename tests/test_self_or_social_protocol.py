"""Self-or-social protocol, offline: who reads what, the snapshot rule, the vote and the agreement states."""

import asyncio

import pytest

from autoagentnet.agents.spec import AgentOutput
from autoagentnet.evidence.panel import PanelConfig, PanelSource, requests_for
from autoagentnet.providers.base import Usage
from autoagentnet.self_or_social.engine import branch_actions, revisions, run_policy
from autoagentnet.self_or_social.policy import Policy
from autoagentnet.self_or_social.protocol import (REFLECT, STOP, Agent, actions_for, agreement_states, consult,
                                                  initial_request, revision_request, vote)
from autoagentnet.tasks import Task
from conftest import ROOT

TEAM = [Agent(id="A", ref="haiku_nothink"), Agent(id="B", ref="haiku_low", max_tokens=12288),
        Agent(id="C", ref="haiku_high", max_tokens=18432)]
ITEM = Task(id="bbeh-x-1", prompt="Is the sky green?", answer="no", grader="bbeh", meta={"task": "web of lies"})
REPLIES = {"A": "MARK-A\nANSWER: yes", "B": "MARK-B\nANSWER: no", "C": "MARK-C\nANSWER: no"}
MODELS = {a.ref: a.ref for a in TEAM}


def upstream_text(request) -> str:
    return " ".join(u.content for u in request.input.upstream)


def test_reflect_reads_only_its_own_first_reply():
    req = revision_request(TEAM[0], 0, REFLECT, ITEM, REPLIES, "haiku_nothink")
    assert upstream_text(req) == REPLIES["A"]
    assert "MARK-B" not in req.model_dump_json() and "MARK-C" not in req.model_dump_json()


def test_consult_reads_exactly_the_named_peer():
    req = revision_request(TEAM[0], 0, consult("C"), ITEM, REPLIES, "haiku_nothink")
    assert [u.content for u in req.input.upstream] == [REPLIES["A"], REPLIES["C"]]
    assert "MARK-B" not in req.model_dump_json()
    assert "haiku" not in upstream_text(req) and all("haiku" not in u.agent_id for u in req.input.upstream)


def test_full_review_reads_every_other_member():
    req = revision_request(TEAM[1], 1, "full", ITEM, REPLIES, "haiku_low")
    assert [u.content for u in req.input.upstream] == [REPLIES["B"], REPLIES["A"], REPLIES["C"]]


@pytest.mark.parametrize("action", ["consult:A", "consult:Z", STOP, "shout"])
def test_illegal_revisions_raise(action):
    with pytest.raises(ValueError):
        revision_request(TEAM[0], 0, action, ITEM, REPLIES, "haiku_nothink")


def test_actions_per_receiver():
    assert actions_for("B", TEAM) == ["stop", "reflect", "consult:A", "consult:C"]
    assert len(branch_actions(TEAM)) == 3 + 6 and len(branch_actions(TEAM, full=True)) == 12


def test_first_answer_is_the_panel_base_request():
    """Same spec and input as the evidence panel's base source, so the panel's cached calls are this run's too."""
    panel = PanelConfig(kind="panel", name="p", task_kind="bbeh", tasks="x", items="y",
                        sources=[PanelSource(ref="haiku_low", calls=1, max_tokens=12288)],
                        providers=str(ROOT / "configs/providers.yaml"))
    (_, _, _, theirs), = requests_for(panel, [ITEM], {"haiku_low": "haiku_low"})
    assert initial_request(TEAM[1], ITEM, "haiku_low") == theirs


def output(text: str) -> AgentOutput:
    return AgentOutput(agent_id="x", content=text, usage=Usage(), provider="fake", model="fake", latency_s=0.0)


def test_mutual_consults_read_the_snapshot_whatever_the_order():
    seen = {}

    async def call(request, replicate):
        seen[(request.spec.agent_id, replicate)] = upstream_text(request)
        return output(f"REVISED {request.spec.agent_id}\nANSWER: no")

    replies = {k: output(v) for k, v in REPLIES.items()}
    acts = [(TEAM[0], 0, consult("B")), (TEAM[1], 1, consult("A"))]
    asyncio.run(revisions(call, ITEM, replies, MODELS, acts))
    first = dict(seen)
    seen.clear()
    asyncio.run(revisions(call, ITEM, replies, MODELS, list(reversed(acts))))
    assert seen == first
    assert first[("sos.A.consult:B", 0)] == REPLIES["A"] + " " + REPLIES["B"]  # B's first reply, not its revision
    assert "REVISED" not in " ".join(first.values())


def test_stop_makes_no_call_and_each_member_revises_at_most_once():
    calls = []

    async def call(request, replicate):
        calls.append(request.spec.agent_id)
        return output("ANSWER: no")

    replies = {k: output(v) for k, v in REPLIES.items()}
    stop_all = Policy(team=["A", "B", "C"], kinds=["stop"])
    result = asyncio.run(run_policy(call, stop_all, TEAM, ITEM, "web of lies", replies, MODELS))
    assert calls == [] and result["revisions"] == 0 and result["answer"] == "no"
    reflect_all = Policy(team=["A", "B", "C"], allow_stop=False, kinds=["reflect"])
    result = asyncio.run(run_policy(call, reflect_all, TEAM, ITEM, "web of lies", replies, MODELS))
    assert sorted(calls) == ["sos.A.reflect", "sos.B.reflect", "sos.C.reflect"] and result["revisions"] == 3


def test_vote_plurality_ties_and_unparsed():
    assert vote(["yes", "no", "No"], "bbeh") == ("no", 1)  # equal under the bbeh grader
    assert vote(["a", "b", None], "bbeh") == ("a", 0)  # tie: the earliest member in the order
    assert vote(["a", "b", None], "bbeh", order=[1, 0, 2]) == ("b", 1)
    assert vote([None, None, None], "bbeh") == (None, None)


def test_agreement_states():
    assert agreement_states(["x", "x", "x"], "bbeh") == ["all_agree"] * 3
    assert agreement_states(["x", "y", "y"], "bbeh") == ["minority", "majority", "majority"]
    assert agreement_states(["x", "y", "z"], "bbeh") == ["split"] * 3
    assert agreement_states([None, "y", "z"], "bbeh") == ["none", "split", "split"]
    assert agreement_states(["x", None, "x"], "bbeh") == ["majority", "none", "majority"]
