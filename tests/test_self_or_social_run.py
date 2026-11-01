"""The self-or-social runner, offline: rows per call on the fake model, reuse of paid first answers, the estimate,
the gate, a budget refusal, slices that add up and dev/test disjointness."""

import asyncio
import json

import pandas as pd
import pytest

from autoagentnet.providers.fake import FakeClient
from autoagentnet.providers.registry import ProviderRegistry
from autoagentnet.self_or_social import run as R
from autoagentnet.self_or_social.policy import branch_table
from autoagentnet.self_or_social.protocol import Agent
from autoagentnet.tasks import Task
from conftest import ROOT

TEAM = [Agent(id="A", ref="haiku_nothink"), Agent(id="B", ref="haiku_low", max_tokens=1200),
        Agent(id="C", ref="haiku_high", max_tokens=1600)]


def write_items(tmp_path, n=4, family="word sorting"):
    tasks = [Task(id=f"bbeh-w-{i}", prompt=f"Sort puzzle {i}", answer=str(i % 3), grader="bbeh",
                  meta={"kind": "bbeh", "task": family}) for i in range(n)]
    (tmp_path / "tasks.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    (tmp_path / "ids.txt").write_text("\n".join(t.id for t in tasks) + "\n")
    return tasks


def config(tmp_path, **extra) -> R.SelfOrSocialConfig:
    extra = {"model_override": "fake", "team": TEAM, "name": "t", "items": str(tmp_path / "ids.txt"), **extra}
    return R.SelfOrSocialConfig(kind="self_or_social", tasks=str(tmp_path / "tasks.jsonl"), out_dir=str(tmp_path / "out"),
                                providers=str(ROOT / "configs/providers.yaml"), pricing=str(ROOT / "configs/pricing.yaml"),
                                budget=str(ROOT / "configs/budget.yaml"), ledger=str(tmp_path / "ledger.jsonl"),
                                cache=str(tmp_path / "cache"), require_ledger=False, git_checkpoint=False, **extra)


def test_dry_run_makes_the_whole_branch_table(tmp_path):
    write_items(tmp_path)
    rows, status = asyncio.run(R.run_sos(config(tmp_path, chunk_size=3, full_review=True)))
    assert status["state"] == "completed" and status["vendor"] == "anthropic"
    assert len(rows) == 4 * (3 + 9 + 3) and status["live_calls"] == 4 * 15
    per_item = rows.groupby("item")["action"].apply(set)
    assert all(acts == {"initial", "reflect", "consult:A", "consult:B", "consult:C", "full"} for acts in per_item)
    assert rows.groupby(["item", "receiver", "action"]).size().max() == 1
    assert {"family", "grader", "position", "sender", "answer", "parsed", "correct", "cost_usd", "from_cache",
            "reused", "prompt_hash", "reply"} <= set(rows.columns)
    assert not (tmp_path / "ledger.jsonl").exists()  # a dry run spends and records nothing
    on_disk = pd.read_csv(tmp_path / "out/t/calls.csv", dtype={"answer": str})
    assert len(on_disk) == len(rows)
    table = branch_table(on_disk)
    assert len(table) == 4 * 3 * 4


def test_slices_add_up(tmp_path):
    write_items(tmp_path)
    asyncio.run(R.run_sos(config(tmp_path, task_limit=2)))
    asyncio.run(R.run_sos(config(tmp_path, task_offset=2)))
    on_disk = pd.read_csv(tmp_path / "out/t/calls.csv")
    assert on_disk["item"].nunique() == 4 and len(on_disk) == 4 * 12


def panel_calls(tmp_path, tasks, ref="haiku_nothink"):
    """A panel calls.csv holding call 0 of `ref` for every item but the last."""
    rows = [{"item": t.id, "source": f"{ref}:base", "call": 0, "reply": f"Stored.\nANSWER: {t.answer}",
             "input_tokens": 10, "cache_write_tokens": 0, "cache_read_tokens": 0, "output_tokens": 5,
             "cost_usd": 0.0007, "seconds": 1.0, "model_version": "claude-haiku-5-5", "stop_reason": "end_turn"}
            for t in tasks[:-1]]
    path = tmp_path / "panel_calls.csv"
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def test_reused_first_answers_make_no_call_but_keep_their_cost(tmp_path):
    tasks = write_items(tmp_path)
    cfg = config(tmp_path, reuse_first=[panel_calls(tmp_path, tasks)])
    rows, status = asyncio.run(R.run_sos(cfg))
    first_a = rows[(rows["action"] == "initial") & (rows["receiver"] == "A")].set_index("item")
    assert first_a["reused"].tolist() == [True, True, True, False]
    assert first_a.loc["bbeh-w-0", "cost_usd"] == 0.0007 and first_a.loc["bbeh-w-0", "correct"] == 1.0
    assert status["live_calls"] == 4 * 12 - 3
    assert len(rows[(rows["item"] == "bbeh-w-0") & (rows["action"] == "consult:A")]) == 2  # B and C read A's
    table = R.estimate_sos(cfg.model_copy(update={"model_override": None}))
    assert int(table["calls"].sum()) == 4 * 12 - 3  # reused answers are not calls


def test_paid_config_needs_a_prereg_and_a_commit(tmp_path):
    write_items(tmp_path)
    cfg = config(tmp_path, model_override=None)
    path = tmp_path / "sos.yaml"
    path.write_text("kind: self_or_social\n")
    problems, table = R.preflight_sos(cfg, path)
    assert table is not None and int(table["calls"].sum()) == 4 * 12
    assert any("prereg" in p for p in problems) and any(f"commit {path}" in p for p in problems)


def test_one_vendor_per_run(tmp_path):
    write_items(tmp_path)
    mixed = [TEAM[0], Agent(id="L", ref="luna_low")]
    problems = R.item_problems(config(tmp_path, team=mixed))
    assert any("one vendor" in p for p in problems)


def test_dev_and_test_share_no_item_or_question(tmp_path):
    tasks = write_items(tmp_path, n=4)
    extra = Task(id="bbeh-w-dup", prompt="  sort PUZZLE 0 ", answer="0", grader="bbeh", meta={"task": "word sorting"})
    with (tmp_path / "tasks.jsonl").open("a") as f:
        f.write(extra.model_dump_json() + "\n")
    (tmp_path / "dev.txt").write_text("bbeh-w-1\nbbeh-w-dup\n")
    problems = R.item_problems(config(tmp_path, disjoint_from=[str(tmp_path / "dev.txt")]))
    assert any("also in" in p for p in problems) and any("repeat a question" in p for p in problems)
    (tmp_path / "dev2.txt").write_text("bbeh-w-dup\n")
    (tmp_path / "ids.txt").write_text("bbeh-w-2\nbbeh-w-3\n")
    assert R.item_problems(config(tmp_path, disjoint_from=[str(tmp_path / "dev2.txt")])) == []


def test_a_budget_refusal_stops_the_run_and_keeps_partial_status(tmp_path, monkeypatch):
    """Paid refs on a fake client, with a run cap below one call's worst case: the governor refuses before any
    spend, the run stops, and status.json says why."""
    write_items(tmp_path)
    real = ProviderRegistry.from_yaml

    def from_yaml(path):
        registry = real(path)
        for agent in TEAM:
            registry.set_client(agent.ref, FakeClient())
        return registry

    monkeypatch.setattr(R.ProviderRegistry, "from_yaml", staticmethod(from_yaml))
    rows, status = asyncio.run(R.run_sos(config(tmp_path, model_override=None, max_usd=1e-6)))
    assert status["state"] == "stopped" and status["reason"].startswith("budget")
    assert status["live_calls"] == 0 and rows.empty
    saved = json.loads((tmp_path / "out/t/status.json").read_text())
    assert saved["state"] == "stopped"
    assert not (tmp_path / "ledger.jsonl").exists() or (tmp_path / "ledger.jsonl").read_text().strip() == ""


@pytest.mark.parametrize("team", [[TEAM[0]], [TEAM[0], TEAM[0]], [Agent(id="A:x", ref="haiku_low"), TEAM[1]]])
def test_bad_teams_are_refused(tmp_path, team):
    with pytest.raises(ValueError):
        config(tmp_path, team=team)


def test_one_member_needs_single_member_and_no_full_review(tmp_path):
    with pytest.raises(ValueError):
        config(tmp_path, team=[TEAM[0]])
    assert config(tmp_path, team=[TEAM[0]], single_member=True, first_answers_only=True, branches=False).team == [TEAM[0]]
    assert config(tmp_path, team=[TEAM[0]], single_member=True).branches
    with pytest.raises(ValueError):
        config(tmp_path, team=[TEAM[0]], single_member=True, full_review=True)
