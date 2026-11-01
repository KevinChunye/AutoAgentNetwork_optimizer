import asyncio
import math

import pytest

from autoagentnet.experiment import ExperimentConfig, Expectations, estimate_experiment, run_experiment
from autoagentnet.pruning.rewards import amc_log_cost, budgeted_error, error_plus_log_cost
from autoagentnet.pruning.space import PruneSpace
from conftest import ROOT


def test_prune_space(network):
    space = PruneSpace(network)
    assert space.size() == 216 == len(space.configs())
    assert space.from_keep_fractions([0.5, 0.5, 0.1, 1.0]).keep == [3, 3, 1, 1]


def test_rewards():
    assert amc_log_cost(0.0, 1e6) == 0  # zero error ignores cost: the known AMC pitfall
    with pytest.raises(ValueError):
        amc_log_cost(0.2, 0.5)  # dollars < 1 would flip the sign
    assert error_plus_log_cost(0.2, 100, 100) == pytest.approx(-0.2)
    assert error_plus_log_cost(0.2, 50, 100, lam=0.05) == pytest.approx(-0.15)
    assert budgeted_error(0.2, 10, 20) == -0.2 and budgeted_error(0.0, 30, 20) == -1.0


def test_smoke_experiment_is_a_dry_run(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml").model_copy(
        update={"out_dir": str(tmp_path)}
    )
    bill_before = (ROOT / "state/ledger.jsonl").read_text()
    rows, summary, status = asyncio.run(run_experiment(cfg))
    assert status["state"] == "completed" and status["checkpoints"] == []
    assert len(rows) == 8 * 6  # 8 tasks x (dense + 5 configs)
    dense = summary.loc["k6-6-6-1"]
    assert dense["recon_error"] == 0 and dense["speedup"] == pytest.approx(1)
    assert summary.loc["k1-1-1-1", "token_compression"] > 5
    assert not math.isnan(dense["error"])
    assert (tmp_path / "smoke" / "status.json").exists()
    assert (ROOT / "state/ledger.jsonl").read_text() == bill_before  # dry runs never touch the bill (paid rows may exist)


def test_missed_expectation_stops_the_run_early(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml").model_copy(
        update={"out_dir": str(tmp_path), "chunk_size": 2,
                "expect": Expectations(min_tasks=2, dense_error_range=(0.0, 0.5))}
    )
    rows, summary, status = asyncio.run(run_experiment(cfg))
    assert status["state"] == "stopped" and "dense error" in status["reason"]
    assert status["tasks_done"] == 2  # stopped after the first chunk, not after all 8 tasks


def test_one_truncating_stage_stops_the_run(tmp_path, monkeypatch):
    # audit 6: the aggregator is 1 call in 19, so it can truncate on every task while the pooled
    # rate stays near 5%; the per-stage check catches it
    from autoagentnet.providers.fake import FakeClient

    complete = FakeClient.complete

    async def truncating_aggregator(self, request):
        response = await complete(self, request)
        if "combine your team" in request.system:
            response = response.model_copy(update={"stop_reason": "max_tokens"})
        return response

    monkeypatch.setattr(FakeClient, "complete", truncating_aggregator)
    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml").model_copy(
        update={"out_dir": str(tmp_path), "chunk_size": 2, "configs": [],
                "expect": Expectations(min_tasks=2, max_truncation_rate=0.06)}
    )
    rows, summary, status = asyncio.run(run_experiment(cfg))
    assert rows["truncated_calls"].sum() / rows["calls"].sum() < 0.06  # the pooled rate alone would not stop it
    assert status["state"] == "stopped" and "100.0% of aggregate calls truncated" in status["reason"]
    assert status["tasks_done"] == 2


def test_unknown_config_keys_are_rejected():
    with pytest.raises(ValueError):
        ExperimentConfig(name="x", network="n", tasks="t", budget_usd={"anthropic": 500})


def test_estimate_is_an_upper_bound_without_spending(monkeypatch):
    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/landscape_3x6.yaml").model_copy(
        update={"task_limit": 1}
    )
    table = asyncio.run(estimate_experiment(cfg))  # Haiku prices, no key needed, nothing called
    row = table.loc[("anthropic", "claude-haiku-5-5")]
    assert row["calls"] == 474
    assert row["worst_case_x_safety"] > row["worst_case_usd"] > 0


def paid_like_config(tmp_path, **updates) -> ExperimentConfig:
    """The real (non-dry) run path, with a fake model that is priced and billed to 'anthropic'."""
    (tmp_path / "providers.yaml").write_text(
        "models:\n  haiku: {provider: fake, model: fake-model, account: anthropic}\n"
    )
    (tmp_path / "pricing.yaml").write_text("fake-model: {input: 1.0, output: 5.0}\n")
    (tmp_path / "ledger.jsonl").touch()
    base = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml")
    return base.model_copy(update={
        "model_override": None, "providers": str(tmp_path / "providers.yaml"),
        "pricing": str(tmp_path / "pricing.yaml"), "ledger": str(tmp_path / "ledger.jsonl"),
        "cache": str(tmp_path / "cache"), "out_dir": str(tmp_path / "results"),
        "git_checkpoint": False, **updates,
    })


def test_paid_path_bills_once_and_reuses_the_cache(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    # fake price 10x Haiku's; with the amendment 6 caps (3200 tokens) all 8 smoke tasks would pass the run cap
    cfg = paid_like_config(tmp_path, max_usd=4.0, task_limit=4)
    _, _, first = asyncio.run(run_experiment(cfg))
    from autoagentnet.meter import Ledger

    spent = Ledger(cfg.ledger).spent_usd("anthropic")
    assert first["state"] == "completed" and spent > 0
    assert list((tmp_path / "cache").glob("*.jsonl.gz"))  # shards compressed after each chunk
    _, _, second = asyncio.run(run_experiment(cfg))
    assert Ledger(cfg.ledger).spent_usd("anthropic") == pytest.approx(spent)  # nothing paid twice


def test_run_cap_stops_a_paid_run(tmp_path, monkeypatch):
    monkeypatch.chdir(ROOT)
    monkeypatch.delenv("AAN_MODEL_OVERRIDE", raising=False)
    cfg = paid_like_config(tmp_path, max_usd=0.2)
    _, _, status = asyncio.run(run_experiment(cfg))
    from autoagentnet.meter import Ledger

    assert status["state"] == "stopped" and "run cap" in status["reason"]
    assert Ledger(cfg.ledger).spent_usd() * 1.15 <= 0.2


def test_truncation_in_a_pruned_config_only_stops_the_run(tmp_path, monkeypatch):
    # audit 7, finding 1: in P4 most calls belong to pruned configs; an aggregator that truncates only
    # when it reads fewer than six refined answers must still stop the run
    from autoagentnet.providers.fake import FakeClient

    complete = FakeClient.complete

    async def truncating_pruned_aggregator(self, request):
        response = await complete(self, request)
        upstream = "".join(b.text for b in request.blocks).count("ANSWER:")
        if "combine your team" in request.system and upstream < 6:
            response = response.model_copy(update={"stop_reason": "max_tokens"})
        return response

    monkeypatch.setattr(FakeClient, "complete", truncating_pruned_aggregator)
    monkeypatch.chdir(ROOT)
    cfg = ExperimentConfig.from_yaml(ROOT / "configs/experiments/smoke.yaml").model_copy(
        update={"out_dir": str(tmp_path), "chunk_size": 2, "configs": [[3, 3, 3, 1], [1, 1, 1, 1]],
                "expect": Expectations(min_tasks=2, max_truncation_rate=0.30)}
    )
    rows, summary, status = asyncio.run(run_experiment(cfg))
    dense = rows[rows["config_id"] == "k6-6-6-1"]
    assert dense["truncated_calls"].sum() == 0  # the dense config alone would never stop it
    assert status["state"] == "stopped" and "of aggregate calls truncated" in status["reason"]
