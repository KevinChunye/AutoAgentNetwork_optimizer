"""Self-or-social policy and scoring, offline on synthetic branch tables: direction, shrinkage, fallbacks,
serialization, the controls' definitions and the cost accounting."""

import pandas as pd
import pytest

from autoagentnet.self_or_social.policy import Policy, branch_table, fit, fixed_peers, smartest_peers, social_net_gain
from autoagentnet.self_or_social.score import full_review_items, paired_bootstrap, random_matched, score_items

TEAM = ["A", "B", "C"]


def calls_for(n_items: int, first: dict[str, list[str]], revised: dict[str, list[str]], gold="g", cost=0.001,
              initial_cost=0.0005, family="fam") -> pd.DataFrame:
    """calls.csv rows: first answers per member (lists over items) and revision answers per (receiver, action)."""
    rows = []
    for k in range(n_items):
        item = f"i{k}"
        for pos, r in enumerate(TEAM):
            a = first[r][k % len(first[r])]
            rows.append({"item": item, "family": family, "grader": "bbeh", "position": pos, "receiver": r,
                         "action": "initial", "answer": a, "correct": float(a == gold), "cost_usd": initial_cost})
        for (r, action), answers in revised.items():
            a = answers[k % len(answers)]
            rows.append({"item": item, "family": family, "grader": "bbeh", "position": TEAM.index(r), "receiver": r,
                         "action": action, "answer": a, "correct": float(a == gold), "cost_usd": cost})
    return pd.DataFrame(rows)


def all_branches(fill: str = "w") -> dict:
    return {(r, a): [fill] for r in TEAM for a in ["reflect"] + [f"consult:{j}" for j in TEAM if j != r]}


def test_branch_table_states_and_costs():
    calls = calls_for(2, {"A": ["w"], "B": ["g"], "C": ["g"]}, all_branches())
    table = branch_table(calls)
    assert len(table) == 2 * 3 * 4  # stop, reflect and two consults per receiver
    stop = table[table["kind"] == "stop"]
    assert set(stop["extra_cost"]) == {0.0} and table["initial_cost"].tolist() == pytest.approx([0.0015] * len(table))
    assert dict(zip(stop["receiver"], stop["state"])) == {"A": "minority", "B": "majority", "C": "majority"}


def test_directed_gain_is_not_symmetric():
    branches = all_branches("w")
    branches[("A", "consult:B")] = ["g"]  # reading B fixes A; reading A does nothing for B
    table = branch_table(calls_for(10, {"A": ["w"], "B": ["w"], "C": ["w"]}, branches))
    gain = social_net_gain(table).set_index(["receiver", "sender"])["gain"]
    assert gain[("A", "B")] == 1.0 and gain[("B", "A")] == 0.0
    assert fixed_peers(table)["A"] == "B"


def test_smartest_peer_ignores_direction():
    table = branch_table(calls_for(4, {"A": ["w"], "B": ["g"], "C": ["w"]}, all_branches()))
    assert smartest_peers(table) == {"A": "B", "B": "A", "C": "B"}


def test_policy_takes_the_best_action_and_lam_prices_it():
    branches = all_branches("w")
    branches[("A", "consult:B")] = ["g"]
    branches[("A", "reflect")] = ["g", "w"]
    table = branch_table(calls_for(20, {"A": ["w"], "B": ["w"], "C": ["w"]}, branches))
    cheap = fit(table, TEAM, lam=0.0, shrink=0.0)
    assert cheap.choose("A", "all_agree") == "consult:B"
    assert cheap.choose("B", "all_agree") == "stop"  # nothing helps B: the tie goes to stop
    dear = fit(table, TEAM, lam=2000.0, shrink=0.0)  # $0.001 costs 2 points of P: never worth it
    assert dear.choose("A", "all_agree") == "stop"
    self_only = fit(table, TEAM, shrink=0.0, kinds=["stop", "reflect"])
    assert self_only.choose("A", "all_agree") == "reflect"


def test_sparse_cells_shrink_to_coarser_and_unseen_actions_are_skipped():
    branches = all_branches("w")
    branches[("A", "consult:B")] = ["g"]
    table = branch_table(calls_for(6, {"A": ["w"], "B": ["w"], "C": ["w"]}, branches))
    pol = fit(table, TEAM, shrink=5.0)
    # L0: 6 of the 36 consult rows are right; L1 (A, consult:B): 6 of 6, shrunk to (6 + 5 * 1/6) / 11. State "split"
    # never occurred, so its L2 cell is empty and the estimate stays L1's; "all_agree" (6 of 6) moves further up
    l1 = (6 + 5 / 6) / 11
    assert pol.p_correct("A", "split", "", "consult:B") == pytest.approx(l1)
    assert pol.p_correct("A", "all_agree", "", "consult:B") == pytest.approx((6 + 5 * l1) / 11)
    assert pol.choose("A", "split") == "consult:B"
    empty = Policy(team=TEAM)
    assert empty.choose("A", "majority") == "stop"  # no estimate at all: the conservative fallback
    assert Policy(team=TEAM, allow_stop=False).choose("A", "majority") == "reflect"


def test_shrinkage_pulls_a_small_cell_towards_its_parent():
    branches = all_branches("w")
    table = branch_table(calls_for(10, {"A": ["w"], "B": ["w"], "C": ["w"]}, branches))
    pol = fit(table, TEAM, shrink=5.0)
    pol.cells["L2"]["A|split|reflect"] = [1.0, 1.0]  # one right answer in a cell whose parent is never right
    assert pol.p_correct("A", "split", "", "reflect") == pytest.approx(1 / 6)


def test_bad_inputs_are_refused_or_skipped():
    with pytest.raises(ValueError):
        Policy(team=TEAM, lam=float("nan"))
    with pytest.raises(ValueError):
        Policy(team=TEAM, lam=-1)
    pol = Policy(team=TEAM, cells={"L0": {"reflect": [5.0, 5.0], "stop": [0.0, 5.0]}}, costs={"A|reflect": float("nan")})
    assert pol.choose("A", "majority") == "stop"  # reflect has no valid cost, so it is not a candidate
    with pytest.raises(ValueError):
        pol.choose("Z", "majority")


def test_policy_round_trips_through_json():
    branches = all_branches("w")
    branches[("C", "consult:A")] = ["g", "w", "w"]
    table = branch_table(calls_for(12, {"A": ["g", "w"], "B": ["w"], "C": ["w", "g"]}, branches))
    pol = fit(table, TEAM, lam=10.0, use_family=True)
    again = Policy.from_json(pol.to_json())
    assert again.hash() == pol.hash()
    for r in TEAM:
        for s in ["all_agree", "majority", "minority", "split", "none"]:
            assert again.choose(r, s, "fam") == pol.choose(r, s, "fam")


def test_scores_count_first_answers_for_every_method():
    branches = all_branches("w")
    branches[("A", "consult:B")] = ["g"]
    calls = calls_for(4, {"A": ["w"], "B": ["g"], "C": ["g"]}, branches)
    table = branch_table(calls)
    pol = fit(table, TEAM, shrink=0.0)
    per_item = score_items(table, TEAM, {f"i{k}": "bbeh" for k in range(4)}, {"policy": pol},
                           fixed_peers(table), smartest_peers(table))
    by = per_item.groupby("method").agg(acc=("correct", "mean"), cost=("cost", "mean"), calls=("calls", "mean"))
    assert by.loc["vote", "acc"] == 1.0 and by.loc["vote", "cost"] == pytest.approx(0.0015) and by.loc["vote", "calls"] == 3
    assert by.loc["all_reflect", "acc"] == 0.0 and by.loc["all_reflect", "cost"] == pytest.approx(0.0045)
    assert set(per_item["method"]) >= {"vote", "all_reflect", "fixed_peer", "smartest_peer", "policy", "random_matched"}


def test_random_matched_keeps_the_policy_counts_and_is_seeded():
    choice = {"A": "consult:B", "B": "reflect", "C": "stop"}
    draws = random_matched("i0", choice, TEAM, draws=30, seed=1)
    assert draws == random_matched("i0", choice, TEAM, draws=30, seed=1)
    for d in draws:
        kinds = sorted(a.split(":")[0] for a in d.values())
        assert kinds == ["consult", "reflect", "stop"]
        assert all(a != f"consult:{r}" for r, a in d.items())


def test_full_review_and_bootstrap():
    calls = calls_for(5, {"A": ["w"], "B": ["w"], "C": ["w"]}, {(r, "full"): ["g"] for r in TEAM})
    full = full_review_items(calls, TEAM, {f"i{k}": "bbeh" for k in range(5)})
    assert full["correct"].tolist() == [1.0] * 5 and full["calls"].iloc[0] == 6
    vote_rows = full.assign(method="vote", correct=0.0)
    diff = paired_bootstrap(pd.concat([full, vote_rows]), "full_review", "vote", draws=200)
    assert diff["n"] == 5 and diff["d_acc"] == 1.0 and diff["d_acc_lo"] == 1.0
