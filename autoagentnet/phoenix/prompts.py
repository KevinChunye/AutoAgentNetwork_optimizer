"""Bounded, label-free requests over the existing agent wire format."""
from __future__ import annotations

import json

from ..agents.agent import prompt_text
from ..agents.spec import AgentInput, AgentRequest, AgentSpec
from ..providers.base import estimate_tokens
from .types import PipelineSpec, Proposal, canonical, digest

SYSTEM = """Recover a classification experiment using only the supplied operation DSL and artifacts.
An identity shutdown does not invalidate completed results. Models and tools not listed as available
cannot be used. Never invent observations, scores, capabilities, costs or file paths. Return JSON only.
There is no access to held-out test data. A valid incumbent is always an acceptable stopping point."""


# What each Proposal action means (docs/PHOENIX.md, "Recovery interfaces"); added to the propose and recover
# instructions after all three models misused the actions in the calibration pilot (prereg Amendment 2).
ACTIONS = ('Actions: INHERIT, VERIFY, RECOMPUTE and ABANDON act on an existing validate target given as "target" and '
           'take no pipelines (INHERIT keeps a valid result, VERIFY checks a staged one, RECOMPUTE redoes a missing or '
           'stale one, ABANDON drops a non-incumbent one). A new pipeline is REROUTE with exactly one PipelineSpec in '
           '"pipelines", or REROUTE with "model" and no pipelines to request a design call; SPLIT has two PipelineSpecs '
           'and a soft-vote "weight".')


def parse_json(text):
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if len(lines) < 3 or lines[-1].strip() != "```":
            raise ValueError("incomplete fenced JSON")
        stripped = "\n".join(lines[1:-1])
    return json.loads(stripped, parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def request_for(state: dict, purpose: str, model: str, worker: str, max_tokens=4096,
                max_input_tokens=6000) -> AgentRequest:
    instructions = {
        "propose": 'Return {"proposals":[up to three Proposal objects]}. Each is a local executable alternative. '
                   + ACTIONS,
        "recover": 'Return one Proposal object, or {"stop":true}. Choose the next recovery action yourself. '
                   + ACTIONS,
        "select": 'Return {"plan_id":"one of the supplied candidate ids"}, or {"stop":true}.',
        "design": 'Return {"pipeline":one PipelineSpec object}. Supply a complete executable configuration.',
        "calibrate": 'Return {"pipeline":one PipelineSpec object}. Solve the supplied development design/diagnosis task.',
    }
    payload = {"purpose": purpose, "state": state,
               "proposal_schema": Proposal.model_json_schema(), "pipeline_schema": PipelineSpec.model_json_schema()}

    def build():
        return AgentRequest(spec=AgentSpec(agent_id=worker, stage="phoenix."+purpose, index=0, model=model,
                                           system=SYSTEM, instruction=instructions[purpose],
                                           max_tokens=max_tokens, temperature=None),
                            input=AgentInput(task_id=str(state["case_id"]),
                                             task="PHOENIX_JSON\n"+canonical(payload)))

    # Trim only known summaries; never erase capabilities, budget, candidate ids or DSL constraints.
    for key in ("recent_events", "extra_artifacts"):
        while state.get(key) and estimate_tokens(prompt_text(build().spec, build().input)) > max_input_tokens:
            state[key] = state[key][1:]
    req = build()
    if estimate_tokens(prompt_text(req.spec, req.input)) > max_input_tokens:
        raise ValueError("essential recovery context exceeds input token limit")
    return req


TEMPLATE_HASH = digest({"system": SYSTEM, "proposal": Proposal.model_json_schema(),
                        "pipeline": PipelineSpec.model_json_schema(), "version": 1})
