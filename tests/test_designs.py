"""Network building blocks (vote, consensus exit, escalation, stage skip), factorial
designs and the paid-run preflight gate."""

import asyncio
import re

import pytest

from autoagentnet.budget import BudgetRules, SpendGovernor
from autoagentnet.cache import CallCache
from autoagentnet.consensus import plurality
from autoagentnet.experiment import ExperimentConfig, preflight
from autoagentnet.meter import Ledger
from autoagentnet.network.spec import NetworkSpec, PruneConfig
from autoagentnet.providers.base import LLMResponse, Usage
from autoagentnet.pruning.space import PruneSpace
from autoagentnet.tasks import Task
from conftest import ROOT, make_executor

TASK = Task(id="t1", prompt="What is 6 x 7?", answer="42")


class ScriptedClient:
    """Answers by agent: proposer i says answers[i]; every later agent repeats the
    plurality it read. Records the model of every request."""

    provider = "scripted"

    def __init__(self, answers: list[str]):
        self.answers = answers
        self.models: list[str] = []

    async def complete(self, request) -> LLMResponse:
        self.models.append(request.model)
        upstream = re.findall(r"ANSWER:\s*(\S+)", request.blocks[0].text)
        if upstream:
            answer = plurality(upstream)[0]
        else:  # a proposer: its perspective line tells which agent it is
            perspective = re.search(r"Your approach: (.*)", request.blocks[1].text).group(1).strip()
            answer = self.answers[PERSPECTIVES.index(perspective)]
        return LLMResponse(text=f"work\nANSWER: {answer}", usage=Usage(input_tokens=100, output_tokens=20),
                           model=request.model, provider=self.provider, latency_s=0.1, stop_reason="end_turn")


PERSPECTIVES = NetworkSpec.from_yaml(ROOT / "configs/networks/dense_3x6.yaml").stages[0].perspectives


def network(name: str) -> NetworkSpec:
    return NetworkSpec.from_yaml(ROOT / f"configs/networks/{name}.yaml")


def scripted(registry, answers, refs=("fake",)) -> ScriptedClient:
    client = ScriptedClient(answers)
    for ref in refs:
        registry.set_client(ref, client)
    return client


def test_plurality_share():
    assert plurality(["42", "42", "41", None]) == ("42", 0.5)
    assert plurality([None, None]) == (None, 0.0)


def test_vote_stage_is_free_and_takes_the_plurality(registry):
    scripted(registry, ["42", "42", "42", "41", "40", "42"])
    result = asyncio.run(make_executor(network("vote6"), registry).run(TASK))
    assert result.final == "ANSWER: 42"
    assert len(result.calls) == 6  # the vote is a rule, not a call


def test_consensus_exit_skips_the_review_stages(registry):
    scripted(registry, ["42"] * 5 + ["41"])  # 5 of 6 agree
    result = asyncio.run(make_executor(network("gated_3x6"), registry).run(TASK))
    assert result.exit_stage == "critique" and len(result.calls) == 6 and result.final == "ANSWER: 42"

    scripted(registry, ["42", "42", "42", "41", "41", "40"])  # contested: pays for every stage
    contested = asyncio.run(make_executor(network("gated_3x6"), registry).run(TASK))
    assert contested.exit_stage is None and len(contested.calls) == 19


def test_estimates_assume_the_expensive_path(registry):
    scripted(registry, ["42"] * 6)
    result = asyncio.run(make_executor(network("gated_3x6"), registry, worst_case_paths=True).run(TASK))
    assert result.exit_stage is None and len(result.calls) == 19


def test_escalation_uses_the_stronger_model_only_when_contested(registry, pricebook):
    governor = SpendGovernor(Ledger(), BudgetRules(hard_caps_usd={"anthropic": 100}))

    def run(answers):
        client = scripted(registry, answers, refs=("haiku", "sonnet_nothink"))  # judge_cascade escalates to sonnet_nothink
        executor = make_executor(network("judge_cascade"), registry, pricebook=pricebook,
                                 governor=governor, model_override=None)
        return asyncio.run(executor.run(TASK)), client

    contested, client = run(["1", "2", "3", "4", "5", "42"])  # plurality share 1/6 < 0.5
    assert contested.escalated == ["aggregate"] and client.models[-1] == "claude-sonnet-5-5"
    split, client = run(["42", "42", "42", "41", "41", "41"])  # share 0.5: no escalation, no exit
    assert split.escalated == [] and client.models[-1] == "claude-haiku-5-5"


def test_a_middle_stage_can_be_skipped(registry, fake, tasks):
    result = asyncio.run(make_executor(network("dense_3x6"), registry).run(tasks[0], PruneConfig(keep=[6, 0, 6, 1])))
    assert [s.stage for s in result.stages] == ["propose", "refine", "aggregate"] and len(result.calls) == 13
    with pytest.raises(ValueError):
        PruneConfig(keep=[0, 6, 6, 1]).check(network("dense_3x6"))


def test_factorial_design_shares_calls(registry, fake, tasks):
    space = PruneSpace(network("dense_3x6"))
    configs = space.factorial([1, 3, 6])
    assert len(configs) == 27
    executor = make_executor(network("dense_3x6"), registry, cache=CallCache())

    async def all_configs():
        await asyncio.gather(*(executor.run(tasks[0], c) for c in configs))

    asyncio.run(all_configs())
    assert fake.calls == 105  # 6 + 3x6 + 9x6 + 27, against 474 for all 216 configs
    assert len(space.factorial([0, 2, 6])) == 2 * 3 * 3  # skip allowed in middle stages only


def test_preflight_gate(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    dry = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml")
    assert preflight(dry, "configs/experiments/smoke.yaml") == ([], None)

    paid = ExperimentConfig.from_yaml(ROOT / "configs/experiments/landscape_3x6.yaml").model_copy(
        update={"task_limit": 1, "model_override": None})
    problems, table = preflight(paid, tmp_path / "untracked.yaml")
    assert any("prereg" in p for p in problems) and any("commit" in p for p in problems)
    assert table.loc[("anthropic", "claude-haiku-5-5"), "calls"] == 474

    too_big = paid.model_copy(update={"task_limit": None, "max_usd": 0.05})
    problems, _ = preflight(too_big, tmp_path / "untracked.yaml")
    assert any("does not fit" in p for p in problems)


def test_mixed_team_alternates_models(registry, pricebook):
    governor = SpendGovernor(Ledger(), BudgetRules(hard_caps_usd={"anthropic": 100, "openai": 100}))
    client = scripted(registry, ["42"] * 6, refs=("haiku_nothink", "luna_low"))
    executor = make_executor(network("mixed_vote6"), registry, pricebook=pricebook, governor=governor,
                             model_override=None, warm_cache_first=False)
    result = asyncio.run(executor.run(TASK))
    assert sorted(client.models) == ["claude-haiku-5-5"] * 3 + ["gpt-6-luna"] * 3
    assert result.final == "ANSWER: 42"
    assert set(governor.ledger.bill().index.get_level_values("account")) == {"anthropic", "openai"}


def test_vote_or_sonnet_policy_and_theta_choice():
    # plan rule 63: the plurality settles a task when enough proposers agree, else one Sonnet call
    import pandas as pd

    from analysis.designs import best_vote_or_sonnet_theta, vote_or_sonnet

    tasks = ["t1", "t2", "t3", "t4"]
    exits = pd.DataFrame({"share": [1.0, 4 / 6, 3 / 6, 2 / 6], "exit_correct": [1.0, 1.0, 0.0, 0.0],
                          "exit_cost": [0.006] * 4}, index=tasks)
    sonnet = pd.DataFrame({"correct": [1.0, 0.0, 1.0, 1.0], "cost_usd": [0.014] * 4}, index=tasks)
    out = vote_or_sonnet(exits, sonnet, 2 / 3, tasks)
    assert list(out["correct"]) == [1.0, 1.0, 1.0, 1.0] and list(out["exited"]) == [1.0, 1.0, 0.0, 0.0]
    assert out["cost_usd"].iloc[2] == pytest.approx(0.020)
    assert best_vote_or_sonnet_theta(exits, sonnet, tasks, dense_cost=0.011) == pytest.approx(2 / 3)
