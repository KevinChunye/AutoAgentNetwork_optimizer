"""Offline tests for analysis/cross_provider.py: the panel vote with abstention (handoff), the tie-break by dev
ranking, the cross-provider panel list and the dev selection rule. Synthetic stored calls only; no model call."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import cross_provider as cp  # noqa: E402


def calls(rows):
    """rows: (item, receiver, answer or None, correct, cost) -> a stored-calls frame of first answers."""
    return pd.DataFrame([{"item": i, "receiver": r, "action": "initial", "answer": a, "parsed": a is not None,
                          "correct": c, "cost_usd": cost, "grader": "choice"} for i, r, a, c, cost in rows])


def answers(tmp_path, claude_rows, gpt_rows):
    paths = {}
    for provider, rows in (("claude", claude_rows), ("gpt", gpt_rows)):
        path = tmp_path / f"{provider}.csv"
        calls(rows).to_csv(path, index=False)
        paths[provider] = str(path)
    return cp.first_answers(paths)


def test_a_member_without_an_answer_abstains_and_the_others_decide(tmp_path):
    fa = answers(tmp_path,
                 [("q1", "A", "B", 0.0, 0.001), ("q1", "B", None, 0.0, 0.0), ("q1", "C", "C", 1.0, 0.01)],
                 [("q1", "A", "C", 1.0, 0.001), ("q1", "B", "C", 1.0, 0.005), ("q1", "C", None, 0.0, 0.0)])
    ranking = ["claude:B", "gpt:C", "claude:A", "gpt:A", "gpt:B", "claude:C"]
    out = cp.panel_items(fa, ["claude:B", "gpt:C", "gpt:B"], ranking, "p")
    row = out.iloc[0]
    assert row["answered"] == 1 and row["answer"] == "C" and row["correct"] == 1.0
    assert row["cost"] == pytest.approx(0.005)


def test_no_answer_at_all_is_wrong(tmp_path):
    fa = answers(tmp_path, [("q1", k, None, 0.0, 0.0) for k in "ABC"], [("q1", k, None, 0.0, 0.0) for k in "ABC"])
    out = cp.panel_items(fa, ["claude:A", "gpt:A", "gpt:B"], sorted(fa["member"].unique()), "p")
    assert out.iloc[0]["correct"] == 0.0 and out.iloc[0]["answered"] == 0


def test_a_tie_goes_to_the_member_ranked_highest_on_dev(tmp_path):
    fa = answers(tmp_path,
                 [("q1", "A", "A", 1.0, 0.001), ("q1", "B", "B", 0.0, 0.01), ("q1", "C", None, 0.0, 0.0)],
                 [("q1", "A", "C", 0.0, 0.001), ("q1", "B", "B", 0.0, 0.005), ("q1", "C", "B", 0.0, 0.01)])
    panel = ["claude:A", "claude:B", "gpt:A"]  # three different answers: a three-way tie
    first = cp.panel_items(fa, panel, ["claude:A", "claude:B", "gpt:A", "claude:C", "gpt:B", "gpt:C"], "p")
    assert first.iloc[0]["answer"] == "A" and first.iloc[0]["correct"] == 1.0
    second = cp.panel_items(fa, panel, ["gpt:A", "claude:A", "claude:B", "claude:C", "gpt:B", "gpt:C"], "p")
    assert second.iloc[0]["answer"] == "C" and second.iloc[0]["correct"] == 0.0


def test_eighteen_cross_provider_panels_from_six_members():
    members = [f"{p}:{k}" for p in ("claude", "gpt") for k in "ABC"]
    panels = cp.cross_panels(members)
    assert len(panels) == 18
    assert all(len({m.split(":")[0] for m in p}) == 2 for p in panels)


def test_selection_takes_the_most_accurate_panel_then_the_cheaper(tmp_path):
    # two items; claude:C and gpt:B are right on both, everyone else wrong; gpt:B is cheaper than gpt:C
    claude = [(q, k, "X" if k == "C" else "Y", 1.0 if k == "C" else 0.0, {"A": 0.001, "B": 0.01, "C": 0.02}[k])
              for q in ("q1", "q2") for k in "ABC"]
    gpt = [(q, k, "X" if k == "B" else "Z", 1.0 if k == "B" else 0.0, {"A": 0.001, "B": 0.005, "C": 0.03}[k])
           for q in ("q1", "q2") for k in "ABC"]
    fa = answers(tmp_path, claude, gpt)
    frozen = cp.select(fa)
    assert frozen["ranking"][:2] == ["gpt:B", "claude:C"]
    assert frozen["best_single"] == "gpt:B"
    # gpt:B alone against two different wrong answers wins the three-way tie as the top-ranked member, so the
    # cheapest panel that is right on both items is gpt:B with the two cheapest wrong members
    assert frozen["X"] == ["claude:A", "gpt:A", "gpt:B"]
    best = pd.DataFrame(frozen["dev_panels"])
    assert best.loc[0, "accuracy"] == 1.0 and best.loc[0, "cost"] == best[best["accuracy"] == 1.0]["cost"].min()


def test_team_vote_uses_the_frozen_order(tmp_path):
    fa = answers(tmp_path,
                 [("q1", "A", "A", 1.0, 0.001), ("q1", "B", "B", 0.0, 0.01), ("q1", "C", "C", 0.0, 0.01)],
                 [("q1", k, "A", 1.0, 0.001) for k in "ABC"])
    assert cp.team_vote_items(fa, "claude", [0, 1, 2]).iloc[0]["correct"] == 1.0
    assert cp.team_vote_items(fa, "claude", [1, 2, 0]).iloc[0]["answer"] == "B"


def test_the_team_vote_check_stops_on_a_mismatch(tmp_path):
    read = tmp_path / "read"
    read.mkdir()
    pd.DataFrame([{"item": "q1", "method": "vote", "correct": 1.0}, {"item": "q2", "method": "vote", "correct": 0.0}]
                 ).to_csv(read / "per_item.csv", index=False)
    mine = pd.DataFrame([{"item": "q1", "method": "claude_vote", "correct": 1.0}, {"item": "q2", "method": "claude_vote", "correct": 0.0}])
    cp.check_team_votes(mine, {"claude": str(read)})
    flipped = mine.assign(correct=[1.0, 1.0])
    with pytest.raises(SystemExit):
        cp.check_team_votes(flipped, {"claude": str(read)})
    with pytest.raises(SystemExit):
        cp.check_team_votes(mine.iloc[:1], {"claude": str(read)})
