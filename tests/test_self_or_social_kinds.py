"""Self-or-social task kinds (bbeh, math, mcq) and the vendor split, offline on the fake model.

bbeh must be byte-identical to the module before the kinds were added: same first request as the evidence panel's,
same revision texts, same template hash, same fake replies. math's first request must be the panel's math request
(so the E5 anchor's paid math answers are cache hits) and its grade the anchor read's. mcq is new: no panel kind
exists, so no earlier call is ever a cache hit for it."""

import asyncio
import json

import pandas as pd
import pytest
from pydantic import ValidationError

from analysis import anchor_read as AR
from autoagentnet.agents.spec import AgentOutput
from autoagentnet.budget import BudgetRules, effective_run_cap
from autoagentnet.cache import CallCache
from autoagentnet.experiment import Prereg
from autoagentnet.evidence import prompts as P
from autoagentnet.evidence.panel import PanelConfig, PanelSource, read_ids, requests_for
from autoagentnet.market.caller import MarketCaller, cache_key
from autoagentnet.providers.base import LLMRequest, Usage
from autoagentnet.providers.fake import FakeClient
from autoagentnet.providers.registry import ProviderRegistry
from autoagentnet.runtime.local import LocalRuntime
from autoagentnet.self_or_social import protocol as S
from autoagentnet.self_or_social import run as R
from autoagentnet.self_or_social.engine import answer_of
from autoagentnet.self_or_social.policy import branch_table
from autoagentnet.self_or_social.protocol import Agent
from autoagentnet.tasks import Task
from conftest import ROOT
from test_self_or_social_run import config

PROVIDERS = str(ROOT / "configs/providers.yaml")
# The BBEH revision texts and template hash as they were before the kinds were added (commit 4f25207).
OLD_REFLECT = ('Above is your earlier reply to the task. Check it against the task: re-read the question, verify each '
               'step and each condition, and fix any mistake you find; if it holds, keep its answer. Be concise. End '
               'with a final line of the form "ANSWER: <answer>".\n')
OLD_CONSULT = ("Above are your earlier reply to the task and a teammate's reply; either may be wrong. Check both against "
               "the task, decide which reasoning holds, and give your final answer; change your answer only for a "
               'concrete reason. Be concise. End with a final line of the form "ANSWER: <answer>".\n')
OLD_FULL = ("Above are your earlier reply to the task and two teammates' replies; any of them may be wrong. Check them "
            "against the task, decide which reasoning holds, and give your final answer; change your answer only for a "
            'concrete reason. Be concise. End with a final line of the form "ANSWER: <answer>".\n')
OLD_TEMPLATE_HASH = "a2620537eba129ac"

BBEH_ITEM = Task(id="bbeh-x-1", prompt="Is the sky green?", answer="no", grader="bbeh", meta={"task": "web of lies"})
MATH_ITEM = Task(id="arxivmath-0826-1", prompt="Compute 1/2 + 0.", answer="\\frac{1}{2}", grader="math",
                 meta={"kind": "math", "set": "arxivmath-0826"})
MCQ_ITEM = Task(id="mcq-1", prompt="Which is red? (A) sky (B) blood (C) grass", answer="B", grader="choice")
MATH_TEAM = [Agent(id="A", ref="haiku_low", max_tokens=12288), Agent(id="B", ref="sol61_low", max_tokens=12288),
             Agent(id="C", ref="sonnet_nothink", max_tokens=4000)]


def panel_request(kind: str, item: Task, ref: str, max_tokens: int):
    panel = PanelConfig(kind="panel", name="p", task_kind=kind, tasks="x", items="y",
                        sources=[PanelSource(ref=ref, calls=1, max_tokens=max_tokens)], providers=PROVIDERS)
    (_, _, _, request), = requests_for(panel, [item], {ref: ref})
    return request


@pytest.mark.parametrize("agent", [Agent(id="A", ref="haiku_nothink"), Agent(id="B", ref="haiku_low", max_tokens=12288),
                                   Agent(id="C", ref="haiku_high", max_tokens=18432)])
def test_bbeh_first_request_is_byte_identical_to_the_panel(agent):
    """Default kind and kind bbeh: the same JSON as the panel's base request, so the same cache key."""
    theirs = panel_request("bbeh", BBEH_ITEM, agent.ref, agent.max_tokens)
    registry = ProviderRegistry.from_yaml(PROVIDERS)
    for mine in (S.initial_request(agent, BBEH_ITEM, agent.ref), S.initial_request(agent, BBEH_ITEM, agent.ref, "bbeh")):
        assert mine.model_dump_json() == theirs.model_dump_json()
        assert cache_key(registry, mine, 0) == cache_key(registry, theirs, 0)


def test_bbeh_revision_texts_and_template_hash_are_unchanged():
    assert (S.REFLECT_INSTRUCTION, S.CONSULT_INSTRUCTION, S.FULL_INSTRUCTION) == (OLD_REFLECT, OLD_CONSULT, OLD_FULL)
    assert S.SYSTEM == P.BBEH_SYSTEM
    assert R.TEMPLATE_HASH == R.template_hash("bbeh") == OLD_TEMPLATE_HASH
    replies = {"A": "x\nANSWER: 1", "B": "y\nANSWER: 2"}
    req = S.revision_request(Agent(id="A", ref="haiku_low"), 0, "consult:B", BBEH_ITEM, replies, "haiku_low")
    assert req.spec.system == P.BBEH_SYSTEM and req.spec.instruction == OLD_CONSULT


@pytest.mark.parametrize("agent", MATH_TEAM)
def test_math_first_request_is_the_panel_math_request(agent):
    theirs = panel_request("math", MATH_ITEM, agent.ref, agent.max_tokens)
    mine = S.initial_request(agent, MATH_ITEM, agent.ref, "math")
    assert mine.model_dump_json() == theirs.model_dump_json()
    assert mine.spec.stage == "panel_math" and mine.spec.system == P.MATH_SYSTEM
    assert mine.spec.agent_id == f"{agent.ref}.base" and mine.input.shared_prefix


def test_mcq_is_new_and_has_no_panel_counterpart():
    mine = S.initial_request(Agent(id="A", ref="haiku_low"), MCQ_ITEM, "haiku_low", "mcq")
    assert mine.spec.stage == "panel_mcq" and mine.spec.system == S.MCQ_SYSTEM
    assert mine.spec.instruction == S.MCQ_INSTRUCTION and "ANSWER: <letter>" in mine.spec.system
    with pytest.raises(ValidationError):  # the panel has no mcq kind, so no panel call can share this cache key
        PanelConfig(kind="panel", name="p", task_kind="mcq", tasks="x", items="y", sources=[PanelSource(ref="haiku_low")])
    with pytest.raises(ValueError):
        S.initial_request(Agent(id="A", ref="haiku_low"), MCQ_ITEM, "haiku_low", "forecast")


@pytest.mark.parametrize("kind", S.KINDS)
def test_revisions_change_only_the_system_and_the_answer_line(kind):
    replies = {"A": "mine", "B": "theirs", "C": "third"}
    agent = Agent(id="A", ref="haiku_low")
    for action, body in [("reflect", S.REFLECT_BODY), ("consult:B", S.CONSULT_BODY), ("full", S.FULL_BODY)]:
        req = S.revision_request(agent, 0, action, MATH_ITEM, replies, "haiku_low", kind)
        assert req.spec.system == S.system_of(kind) and req.spec.instruction == body + S.ANSWER_LINE[kind]
        assert req.spec.stage == "sos_revise" and not req.input.shared_prefix
    assert "\\boxed{}" in S.ANSWER_LINE["math"] and "\\boxed{}" in P.MATH_SYSTEM
    assert set(R.TaskKind.__args__) == set(S.KINDS)
    assert len({R.template_hash(k) for k in S.KINDS}) == 3


def output(text: str) -> AgentOutput:
    return AgentOutput(agent_id="x", content=text, usage=Usage(), provider="fake", model="fake", latency_s=0.0)


def test_mcq_parse_and_grade():
    assert S.mcq_letter("Thinking.\nANSWER: (b)") == "B"
    assert S.mcq_letter("ANSWER: B) blood") == "B"
    assert S.mcq_letter("ANSWER: B or C") is None and S.mcq_letter("ANSWER: A, C") is None  # hedges
    assert S.mcq_letter("The answer is B.") is None
    right = S.grade_reply("mcq", MCQ_ITEM, "ANSWER: B")
    assert right == {"answer": "B", "parsed": True, "correct": 1.0, "prob": None}
    assert S.grade_reply("mcq", MCQ_ITEM, "ANSWER: C")["correct"] == 0.0
    assert S.grade_reply("mcq", MCQ_ITEM, "no letter")["parsed"] is False
    assert S.grade_reply("mcq", MCQ_ITEM, "ANSWER: B", stop_reason="refusal")["parsed"] is False
    assert answer_of(output("ANSWER: (c)"), kind="mcq") == "C" and S.format_ok("mcq", "ANSWER: zz")


def test_math_parse_and_grade_follow_the_anchor_read(tmp_path):
    """The read form (math_read) of the last box, graded by math-verify against the normalized gold: equal to
    analysis/anchor_read.regrade_math, which the E5 anchor's read uses, row for row."""
    assert S.parse_reply("math", "work\n\\boxed{c = \\tfrac{1}{2}}") == "\\frac{1}{2}"
    assert S.grade_reply("math", MATH_ITEM, "\\boxed{c = \\tfrac{1}{2}}")["correct"] == 1.0
    assert S.grade_reply("math", MATH_ITEM, "\\boxed{0.5}")["correct"] == 1.0
    assert S.grade_reply("math", MATH_ITEM, "ANSWER: 1/3")["correct"] == 0.0
    assert S.grade_reply("math", MATH_ITEM, "no answer") == {"answer": None, "parsed": False, "correct": 0.0, "prob": None}
    assert S.format_ok("math", "\\boxed{1}") and not S.format_ok("math", "1")
    replies = ["\\boxed{c = \\tfrac{1}{2}}", "\\boxed{0.5}", "ANSWER: 1/3", "nothing", "\\boxed{\\text{unknown}}",
               "x\n\\boxed{\\frac12}\n"]
    (tmp_path / "math.jsonl").write_text(MATH_ITEM.model_dump_json() + "\n")
    rows = pd.DataFrame({"item": MATH_ITEM.id, "task_kind": "math", "reply": replies, "stop_reason": "end_turn",
                         "answer": None, "parsed": False, "correct": 0.0})
    read = AR.regrade_math(rows, tasks_file=tmp_path / "math.jsonl")
    mine = pd.DataFrame([S.grade_reply("math", MATH_ITEM, r) for r in replies])
    assert mine["parsed"].tolist() == read["parsed"].tolist() and mine["correct"].tolist() == read["correct"].tolist()
    assert mine["answer"].fillna("-").tolist() == read["answer"].fillna("-").tolist()


def write_kind_items(tmp_path, kind: str, n: int = 3) -> list[Task]:
    if kind == "math":
        tasks = [Task(id=f"arxivmath-0826-{i}", prompt=f"Compute {i}.", answer=str(i % 3), grader="math",
                      meta={"kind": "math", "set": "arxivmath-0826"}) for i in range(n)]
    else:
        tasks = [Task(id=f"mcq-{i}", prompt=f"Question {i}: (A) x (B) y (C) z", answer="ABC"[i % 3], grader="choice")
                 for i in range(n)]
    (tmp_path / "tasks.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    (tmp_path / "ids.txt").write_text("\n".join(t.id for t in tasks) + "\n")
    return tasks


@pytest.mark.parametrize("kind", ["math", "mcq"])
def test_dry_run_of_a_kind_makes_the_whole_branch_table(tmp_path, kind):
    write_kind_items(tmp_path, kind)
    cfg = config(tmp_path, task_kind=kind)
    assert R.item_problems(cfg) == []
    rows, status = asyncio.run(R.run_sos(cfg))
    assert status["state"] == "completed" and status["task_kind"] == kind
    assert len(rows) == 3 * (3 + 9) and status["live_calls"] == 3 * 12
    assert set(rows["task_kind"]) == {kind} and set(rows["template_hash"]) == {R.template_hash(kind)}
    assert rows["parsed"].all()  # the fake replies parse under the kind's parser (mcq: letters, FakeSosClient)
    initial = rows[rows["action"] == "initial"]
    assert set(initial["prompt_hash"]) == {R.request_hash(S.initial_request(a, t, "fake", kind))
                                          for t in R.select_items(cfg) for a in cfg.team}
    if kind == "mcq":
        assert set(rows["answer"]) <= {"A", "B", "C", "D"}
    table = branch_table(pd.read_csv(tmp_path / "out/t/calls.csv", dtype={"answer": str}))
    assert len(table) == 3 * 3 * 4


def test_fake_sos_client_changes_only_mcq_replies():
    plain, sos = FakeClient(), R.FakeSosClient()
    for system in (P.BBEH_SYSTEM, P.MATH_SYSTEM):
        request = LLMRequest(model="fake", system=system, blocks=[], max_tokens=100)
        assert asyncio.run(sos.complete(request)).text == asyncio.run(plain.complete(request)).text
    request = LLMRequest(model="fake", system=S.MCQ_SYSTEM, blocks=[], max_tokens=100)
    assert S.mcq_letter(asyncio.run(sos.complete(request)).text) in {"A", "B", "C", "D"}


def test_a_kind_needs_items_of_its_grader(tmp_path):
    write_kind_items(tmp_path, "mcq")
    assert any("task_kind 'math'" in p for p in R.item_problems(config(tmp_path, task_kind="math")))


def first_answers_csv(tmp_path, tasks, team, kind="math", name="panel.csv"):
    """A panel calls.csv holding call 0 of every member's ref for every item, in the panel's columns."""
    rows = [{"item": t.id, "task_kind": kind, "source": f"{a.ref}:base", "call": 0, "reply": f"Stored {a.id}.\nANSWER: {t.answer}",
             "input_tokens": 10, "cache_write_tokens": 0, "cache_read_tokens": 0, "output_tokens": 5,
             "cost_usd": 0.001, "seconds": 1.0, "model_version": a.ref, "stop_reason": "end_turn"}
            for t in tasks for a in team]
    pd.DataFrame(rows).to_csv(tmp_path / name, index=False)
    return str(tmp_path / name)


def test_reuse_reads_only_rows_of_the_runs_kind(tmp_path):
    tasks = write_kind_items(tmp_path, "math")
    team = [Agent(id="A", ref="haiku_nothink"), Agent(id="B", ref="haiku_low")]
    bbeh_rows = first_answers_csv(tmp_path, tasks, team, kind="bbeh")
    assert R.reused_outputs([bbeh_rows], team, "math") == {}
    assert len(R.reused_outputs([bbeh_rows], team, "bbeh")) == 6 and len(R.reused_outputs([bbeh_rows], team)) == 6


def test_a_mixed_vendor_team_runs_once_per_vendor(tmp_path):
    """sol61_low bills OpenAI. Each vendor's run calls only its members, reads the others' reused first answers, and
    the two runs (same name) add up to the whole branch table."""
    tasks = write_kind_items(tmp_path, "math")
    team = [Agent(id="A", ref="haiku_low"), Agent(id="B", ref="sol61_low"), Agent(id="C", ref="sonnet_nothink")]
    assert any("one vendor" in p for p in R.item_problems(config(tmp_path, task_kind="math", team=team)))
    anth = config(tmp_path, task_kind="math", team=team, vendor="anthropic")
    assert any("not in reuse_first" in p for p in R.item_problems(anth))
    with pytest.raises(ValueError):
        asyncio.run(R.run_sos(anth))
    stored = first_answers_csv(tmp_path, tasks, team)
    anth = anth.model_copy(update={"reuse_first": [stored]})
    openai = anth.model_copy(update={"vendor": "openai"})
    assert R.item_problems(anth) == [] and R.item_problems(openai) == []
    assert any("bills vendor" in p for p in R.item_problems(anth.model_copy(update={"vendor": "nobody"})))
    paid = anth.model_copy(update={"model_override": None})
    assert int(R.estimate_sos(paid)["calls"].sum()) == 3 * 6  # A's and C's 3 revisions per item; no first answer
    assert set(R.estimate_sos(paid).index.get_level_values("account")) == {"anthropic"}
    rows_a, status_a = asyncio.run(R.run_sos(anth))
    rows_o, status_o = asyncio.run(R.run_sos(openai))
    assert status_a["receivers"] == ["A", "C"] and status_o["receivers"] == ["B"]
    assert status_a["live_calls"] == 3 * 6 and status_o["live_calls"] == 3 * 3
    assert set(rows_o.loc[rows_o["action"] != "initial", "receiver"]) == {"B"}
    assert rows_o.loc[rows_o["action"] == "initial", "reused"].all()
    merged = pd.read_csv(tmp_path / "out/t/calls.csv", dtype={"answer": str})
    assert len(merged) == 3 * (3 + 9) and merged.groupby(["item", "receiver", "action"]).size().max() == 1


def test_first_answer_readiness_and_the_market_callers_key(tmp_path):
    """cache_key is the key MarketCaller stores a call under; readiness finds reused and cached first answers."""
    tasks = write_kind_items(tmp_path, "math", n=2)
    team = [Agent(id="A", ref="haiku_nothink"), Agent(id="B", ref="haiku_low")]
    registry = ProviderRegistry.from_yaml(PROVIDERS)
    registry.set_client("fake", FakeClient())
    cache = CallCache()
    caller = MarketCaller(LocalRuntime(registry), registry, pricebook=None, cache=cache, governor=None, run_id="r",
                          market="m", condition="c")
    request = S.initial_request(team[0], tasks[0], "fake", "math")
    reply = asyncio.run(caller.call(request, replicate=0))
    assert cache.get(cache_key(registry, request, 0)) is not None and cache.get(cache_key(registry, request, 1)) is None
    # store A's first answer to item 0 under its paid key, with the same text as a reuse_first row
    paid = S.initial_request(team[0], tasks[0], "haiku_nothink", "math")
    cache.put(cache_key(registry, paid, 0), reply.model_copy(update={"content": "Stored A.\nANSWER: 0"}).model_dump_json())
    stored = first_answers_csv(tmp_path, tasks[:1], team)
    cfg = config(tmp_path, task_kind="math", team=team, reuse_first=[stored])
    ready = R.first_answer_readiness(cfg, cache).set_index(["item", "member"])
    assert ready["reused"].tolist() == [True, True, False, False]
    assert ready["cached"].tolist() == [True, False, False, False]
    assert ready["same_reply"].tolist() == [True, False, False, False]
    assert ready.loc[(tasks[0].id, "A"), "key"] == cache_key(registry, paid, 0)
    assert json.loads(cache.get(ready.loc[(tasks[0].id, "A"), "key"]))["content"] == "Stored A.\nANSWER: 0"


def test_no_per_config_run_cap_by_default(tmp_path):
    """Kevin's run-cap policy: max_usd is optional; without it only the phase's max_run_usd and the hard caps apply."""
    write_kind_items(tmp_path, "math", n=2)
    team = [Agent(id=x, ref="sonnet_nothink", max_tokens=30000) for x in "ABC"]
    prereg = Prereg(question="q", prediction="p", kill="k", decision="d")
    cfg = config(tmp_path, task_kind="math", team=team, model_override=None, prereg=prereg)
    assert cfg.max_usd is None and R.SelfOrSocialConfig.model_fields["max_usd"].default is None
    rules = BudgetRules.from_yaml(cfg.budget)
    assert effective_run_cap(rules, cfg.max_usd) == rules.active_phase.max_run_usd
    path = tmp_path / "sos.yaml"
    path.write_text("kind: self_or_social\n")
    problems, table = R.preflight_sos(cfg, path)
    assert float(table["worst_case_usd"].sum()) > 4.0  # above the old $4 default
    assert not any("worst case does not fit" in p for p in problems)
    capped, _ = R.preflight_sos(cfg.model_copy(update={"max_usd": 4.0}), path)  # a config may still set its own cap
    assert any("worst case does not fit" in p for p in capped)


def test_new_first_answers_run_in_two_stages_per_vendor(tmp_path):
    """LAB-Bench's shape: no earlier run holds the first answers. Stage 1 (first_answers_only) makes each vendor's
    members' first answers; stage 2 reads the stage-1 calls.csv (self-or-social rows) and revises. In a dry run a
    missing results/<x> file is read from runs/dry/<x>."""
    write_kind_items(tmp_path, "mcq", n=2)
    team = [Agent(id="A", ref="haiku_low"), Agent(id="B", ref="sol61_low"), Agent(id="C", ref="sonnet_nothink")]
    first = {v: config(tmp_path, task_kind="mcq", team=team, vendor=v, first_answers_only=True, name="first")
             for v in ("anthropic", "openai")}
    assert R.item_problems(first["anthropic"]) == []  # stage 1 needs no other member's first answer
    assert int(R.estimate_sos(first["anthropic"].model_copy(update={"model_override": None}))["calls"].sum()) == 2 * 2
    for v in ("anthropic", "openai"):
        rows, status = asyncio.run(R.run_sos(first[v]))
        assert status["first_answers_only"] and set(rows["action"]) == {"initial"}
    stage1 = tmp_path / "out/first/calls.csv"
    assert len(pd.read_csv(stage1)) == 2 * 3
    reused = R.reused_outputs([str(stage1)], team, "mcq")
    assert len(reused) == 6 and all(o.provider == "reused" for o in reused.values())
    assert R.reused_outputs([str(tmp_path / "missing.csv")], team) == {}
    second = config(tmp_path, task_kind="mcq", team=team, vendor="anthropic", name="second", reuse_first=[str(stage1)])
    assert R.item_problems(second) == []
    rows, status = asyncio.run(R.run_sos(second))
    assert status["live_calls"] == 2 * 6 and rows.loc[rows["action"] == "initial", "reused"].all()
    dry = second.model_copy(update={"reuse_first": ["results/sos_unit_missing/calls.csv"]})
    assert R.reuse_paths(dry) == ["runs/dry/sos_unit_missing/calls.csv"]
    assert R.reuse_paths(dry.model_copy(update={"model_override": None})) == ["results/sos_unit_missing/calls.csv"]
    with pytest.raises(ValueError):
        config(tmp_path, team=team, branches=False, full_review=False)


def test_labbench_team_configs_follow_the_prereg():
    """LAB-Bench prereg Amendment 1: one vendor-homogeneous team per vendor family, mcq, ceilings 12,288 at low effort
    and 24,576 at medium, no per-config run cap, phase scienceclaw; dev and test disjoint; test requires the team's
    frozen policy; the pilot (first 8 dev items in frozen order) holds at least 2 items of each subset."""
    folder = ROOT / "configs/experiments/self_or_social_labbench"
    registry = ProviderRegistry.from_yaml(PROVIDERS)
    prereg = "research/self_or_social_shortlist/prereg_labbench.md"
    teams = {"claude": ["haiku_low", "sonnet_low", "opus_med"], "claude2": ["haiku_low", "sonnet_low", "sonnet_med"],
             "gpt": ["luna_low_ev", "sol61_low", "sol61_med"]}   # claude: stopped at its gate (Amendment 3); gpt: Amendment 4
    for team, refs in teams.items():
        for split, other in (("dev", "test"), ("test", "dev")):
            cfg = R.SelfOrSocialConfig.from_yaml(folder / f"sos_lab_{team}_{split}.yaml")
            assert [a.ref for a in cfg.team] == refs and [a.id for a in cfg.team] == ["A", "B", "C"]
            assert cfg.task_kind == "mcq" and cfg.vendor is None and cfg.max_usd is None and cfg.phase == "scienceclaw"
            assert cfg.branches and cfg.full_review and not cfg.first_answers_only and cfg.prereg is not None
            assert all(a.max_tokens == (24576 if a.ref.endswith("_med") else 12288) for a in cfg.team)
            assert cfg.items.endswith(f"{split}.txt") and cfg.disjoint_from == [cfg.items.replace(split, other)]
            assert prereg in cfg.requires
            assert (f"research/self_or_social_shortlist/labbench_frozen_{team}.json" in cfg.requires) == (split == "test")
            known = [a.ref for a in cfg.team if a.ref in registry.models]  # terra61_low until Kevin adds it
            assert len({registry.account_of(r) for r in known}) == 1
    dev = read_ids(ROOT / "research/self_or_social_shortlist/labbench_sealed/dev.txt")
    pilot = pd.Series([i.split("-")[1] for i in dev[:8]]).value_counts()  # ids are labbench-<subset>-<uuid>
    assert set(pilot.index) == {"seqqa", "protocolqa"} and pilot.min() >= 2
