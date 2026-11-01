"""analysis/economics.py on synthetic landscapes with known answers."""

import itertools
import math

import numpy as np
import pandas as pd
import pytest

from analysis.economics import consensus_policies, effective_team_size, equimarginal_path, production_function
from analysis.landscape import Landscape, summarize


def synthetic_landscape(n_tasks=60, seed=1) -> Landscape:
    """Factorial grid 1/3/6 per stage. Truth: each doubling of proposers adds 8 points,
    of refiners 3 points, critique adds nothing; cost grows with agents."""
    rng = np.random.default_rng(seed)
    keeps = list(itertools.product([1, 3, 6], [1, 3, 6], [1, 3, 6]))
    ids = [f"k{a}-{b}-{c}-1" for a, b, c in keeps]
    configs = pd.DataFrame(keeps, columns=["k_propose", "k_critique", "k_refine"], index=ids)
    configs["agents"] = configs.sum(axis=1) + 1
    tasks = [f"t{i}" for i in range(n_tasks)]
    difficulty = rng.normal(0, 0.1, n_tasks)
    p = (0.35 + 0.08 * np.log2(configs["k_propose"].to_numpy())[:, None]
         + 0.03 * np.log2(configs["k_refine"].to_numpy())[:, None] + difficulty[None, :]).clip(0.01, 0.99)
    correct = pd.DataFrame((rng.random(p.shape) < p).astype(float), index=ids, columns=tasks)
    cost_per_config = 0.001 * configs["k_propose"] + 0.0005 * configs["k_critique"] + 0.001 * configs["k_refine"] + 0.0003
    cost = pd.DataFrame(np.repeat(cost_per_config.to_numpy()[:, None], n_tasks, axis=1), index=ids, columns=tasks)
    return Landscape(correct=correct, agrees=correct.copy(), cost=cost, tokens=cost * 1e6,
                     configs=configs, dense_id="k6-6-6-1", rows=pd.DataFrame())


def test_production_function_recovers_which_stage_matters():
    fit = production_function(synthetic_landscape(), n_boot=200).set_index("term")
    propose, critique = fit.loc["doubling propose"], fit.loc["doubling critique"]
    assert propose["lo"] > 3 and abs(critique["accuracy_points"]) < propose["accuracy_points"] / 2
    assert propose["cost_usd_per_task"] > 0 and fit.loc["propose x critique", "reading"] in {"not resolved", "complements", "substitutes"}


def test_equimarginal_path_grows_the_best_value_stage_first():
    L = synthetic_landscape(n_tasks=400)
    path = equimarginal_path(summarize(L))
    assert path["config_id"].iloc[0] == "k1-1-1-1"
    assert path["config_id"].iloc[1].startswith("k3-1-1")  # proposers have the best value per dollar
    assert path["cost_usd"].is_monotonic_increasing


def agents_frame(answers_by_task: dict[str, list[str]], gold: str = "42") -> pd.DataFrame:
    rows = []
    for task, answers in answers_by_task.items():
        for i, a in enumerate(answers):
            rows.append({"task_id": task, "stage": "propose", "agent_id": f"propose.{i}", "answer": a,
                         "grader": "exact", "correct": float(a == gold), "cost_usd": 0.001, "replicate": 0})
    return pd.DataFrame(rows)


def test_effective_team_size():
    rng = np.random.default_rng(0)
    copies = {f"t{i}": ["42" if rng.random() < 0.5 else "41"] * 6 for i in range(200)}
    assert effective_team_size(agents_frame(copies)).loc["propose", "effective_team_size"] == pytest.approx(1.0)
    independent = {f"t{i}": ["42" if rng.random() < 0.5 else "41" for _ in range(6)] for i in range(400)}
    assert effective_team_size(agents_frame(independent)).loc["propose", "effective_team_size"] > 4


def test_consensus_policy_costs_and_exits():
    L = synthetic_landscape(n_tasks=2)
    L.correct.loc[:, :] = 1.0
    agents = agents_frame({"t0": ["42"] * 6, "t1": ["1", "2", "3", "4", "5", "6"]})
    table = consensus_policies(L, agents, {"dense": "k6-6-6-1"}, ms=(6,), thetas=(1.0,))
    row = table.iloc[0]
    assert row["exit_rate"] == 0.5  # t0 exits on a unanimous vote, t1 falls back to dense
    dense_cost = L.cost.loc["k6-6-6-1"].mean()
    assert row["cost_usd"] == pytest.approx((0.006 + dense_cost) / 2)
    assert row["error"] == 0.0


def test_production_figure_and_vote_policy(tmp_path, monkeypatch):
    import analysis.common as common
    from analysis.economics import plot_production

    monkeypatch.setattr(common, "FIGURES", tmp_path)
    fit = production_function(synthetic_landscape(), n_boot=50)
    common.save_figure(plot_production(fit, "test"), "i")
    assert (tmp_path / "i.pdf").exists() and (tmp_path / "i.png").exists()


def test_two_thirds_means_four_of_six_and_duplicates_are_dropped():
    # audit 4, finding 5: theta 0.67 excluded 4 of 6 (0.6667 < 0.67); thetas needing the same count are one policy
    from analysis.economics import distinct_policies

    pairs = distinct_policies()
    needs = [(m, math.ceil(t * m - 1e-9)) for m, t in pairs]  # agreeing agents each policy requires
    assert (6, 2 / 3) in pairs and (6, 4) in needs and (3, 2) in needs  # 4 of 6 and 2 of 3 are scored
    assert len(needs) == len(set(needs)) and len(pairs) == 15
    L = synthetic_landscape(n_tasks=1)
    agents = agents_frame({"t0": ["42"] * 4 + ["1", "2"]})  # 4 of 6 agree
    table = consensus_policies(L, agents, {"dense": "k6-6-6-1"}, ms=(6,), thetas=(2 / 3, 5 / 6))
    assert list(table.sort_values("theta")["exit_rate"]) == [1.0, 0.0]
