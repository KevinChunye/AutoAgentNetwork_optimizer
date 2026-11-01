"""Scoring every method from one branch table (policy.branch_table), offline and at no cost.

Each method picks one action per receiver per item; the team's final answer is the vote of the receivers' final
answers (protocol.vote, ties by `order`). Per item and method:
  correct   1 if the voted answer is right (the grade of the member whose answer the vote returns), else 0;
            for random_matched, the mean over its seeded draws;
  cost      the item's logical deployment dollars: every first answer (initial_cost; counted for every method,
            even when the experiment reused an earlier run's call) plus the dollars of the chosen revisions;
  calls     model calls a deployment makes: the first answers plus the chosen revisions.

Methods (the definitions frozen in the prereg):
  vote           every receiver stops: the plurality of the first answers;
  all_reflect    every receiver reflects;
  fixed_peer     every receiver consults its fixed peer (policy.fixed_peers, from calibration);
  smartest_peer  every receiver consults the calibration's most accurate other member (no direction; ablation 2);
  policy         the frozen self-or-social policy;
  self_only      the same fit restricted to stop and reflect (no social information);
  forced_social  the policy with stop removed: exactly one revision per receiver, reflect or the best consult
                 (ablation 1: against all_reflect at the same number of extra calls);
  random_matched per item, as many reflects and as many consults as the policy chose there, given to random
                 receivers (and random legal peers), `draws` seeded draws averaged.
"""

from __future__ import annotations

import hashlib
import random

import pandas as pd

from .policy import Policy, voting_answers
from .protocol import CONSULT, REFLECT, STOP, consult, kind_of, vote


class ItemBranches:
    """One item's branch rows, indexed by (receiver, action)."""

    def __init__(self, rows: pd.DataFrame, team: list[str], grader: str):
        self.team = team
        self.grader = grader
        self.family = str(rows["family"].iloc[0])
        self.initial_cost = float(rows["initial_cost"].iloc[0])
        self.state = dict(zip(rows[rows["kind"] == STOP]["receiver"], rows[rows["kind"] == STOP]["state"]))
        self.rows = {(r, a): (None if pd.isna(ans) else str(ans), float(c) if pd.notna(c) else 0.0, float(x))
                     for r, a, ans, c, x in zip(rows["receiver"], rows["action"], rows["answer"], rows["correct"],
                                                rows["extra_cost"])}

    def has(self, choice: dict[str, str]) -> bool:
        return all((r, a) in self.rows for r, a in choice.items())

    def outcome(self, choice: dict[str, str], order: list[int]) -> dict:
        """The team's result for one action per receiver."""
        finals = [self.rows[(r, choice[r])] for r in self.team]
        answer, winner = vote([f[0] for f in finals], self.grader, order)
        correct = 0.0 if winner is None else finals[winner][1]
        extra = sum(f[2] for f in finals)
        revisions = sum(1 for r in self.team if choice[r] != STOP)
        return {"answer": answer, "correct": correct, "cost": self.initial_cost + extra,
                "calls": len(self.team) + revisions,
                "actions": " ".join(f"{r}={choice[r]}" for r in self.team)}


def random_matched(item_id: str, policy_choice: dict[str, str], team: list[str], draws: int, seed: int) -> list[dict[str, str]]:
    """`draws` random choices with the policy's number of reflects and consults on this item: receivers drawn
    without replacement, each consult's peer drawn among the other members. Seeded by (seed, item, draw)."""
    n_reflect = sum(1 for a in policy_choice.values() if kind_of(a) == REFLECT)
    n_consult = sum(1 for a in policy_choice.values() if kind_of(a) == CONSULT)
    out = []
    for d in range(draws):
        rng = random.Random(int(hashlib.sha256(f"{seed}:{item_id}:{d}".encode()).hexdigest()[:12], 16))
        receivers = rng.sample(team, n_reflect + n_consult)
        choice = {r: STOP for r in team}
        for r in receivers[:n_reflect]:
            choice[r] = REFLECT
        for r in receivers[n_reflect:]:
            choice[r] = consult(rng.choice([j for j in team if j != r]))
        out.append(choice)
    return out


def score_items(table: pd.DataFrame, team: list[str], graders: dict[str, str], policies: dict[str, Policy],
                fixed: dict[str, str], smartest: dict[str, str], order: list[int] | None = None,
                draws: int = 20, seed: int = 0) -> pd.DataFrame:
    """Per item and method: correct, cost, calls, actions. `policies` maps a method name to a frozen policy
    (at least "policy"; also "self_only" and "forced_social"). random_matched follows policies["policy"].
    Items lacking a branch a method needs (a failed call) are left out of that method only."""
    order = order or list(range(len(team)))
    rows = []
    for item, group in table.groupby("item", sort=False):
        branches = ItemBranches(group, team, graders[item])
        choices: dict[str, dict[str, str]] = {
            "vote": {r: STOP for r in team},
            "all_reflect": {r: REFLECT for r in team},
            "fixed_peer": {r: consult(fixed[r]) for r in team},
            "smartest_peer": {r: consult(smartest[r]) for r in team},
        }
        for name, pol in policies.items():
            choices[name] = {r: pol.choose(r, branches.state.get(r, "none"), branches.family) for r in team}
        for name, choice in choices.items():
            if branches.has(choice):
                rows.append({"item": item, "family": branches.family, "method": name, **branches.outcome(choice, order)})
        if "policy" in choices:
            draws_ok = [c for c in random_matched(item, choices["policy"], team, draws, seed) if branches.has(c)]
            if draws_ok:
                results = pd.DataFrame([branches.outcome(c, order) for c in draws_ok])
                rows.append({"item": item, "family": branches.family, "method": "random_matched", "answer": None,
                             "correct": results["correct"].mean(), "cost": results["cost"].mean(),
                             "calls": results["calls"].mean(), "actions": f"{len(draws_ok)} draws"})
    return pd.DataFrame(rows)


def full_review_items(calls: pd.DataFrame, team: list[str], graders: dict[str, str], order: list[int] | None = None) -> pd.DataFrame:
    """The full-review control from its own rows (action "full"): every member reads both others and revises."""
    order = order or list(range(len(team)))
    calls = voting_answers(calls)  # an unparsed review casts no vote
    first = calls[calls["action"] == "initial"]
    initial_cost = first.groupby("item")["cost_usd"].sum()
    full = calls[calls["action"] == "full"]
    rows = []
    for item, group in full.groupby("item", sort=False):
        by = dict(zip(group["receiver"], zip(group["answer"], group["correct"], group["cost_usd"])))
        if not all(r in by for r in team):
            continue
        finals = [by[r] for r in team]
        answer, winner = vote([None if pd.isna(f[0]) else str(f[0]) for f in finals], graders[item], order)
        rows.append({"item": item, "family": str(group["family"].iloc[0]), "method": "full_review", "answer": answer,
                     "correct": 0.0 if winner is None else float(finals[winner][1]),
                     "cost": float(initial_cost.get(item, 0.0)) + float(sum(f[2] for f in finals)),
                     "calls": 2 * len(team), "actions": "all=full"})
    return pd.DataFrame(rows)


def paired_bootstrap(per_item: pd.DataFrame, method: str, baseline: str, draws: int = 2000, seed: int = 0) -> dict:
    """Accuracy and cost difference of `method` minus `baseline` over the items both have, with a 95% percentile
    interval from resampling items (one draw resamples items, so every method's correlation is kept)."""
    import numpy as np

    wide = per_item.pivot_table(index="item", columns="method", values=["correct", "cost"])
    if (("correct", method) not in wide) or (("correct", baseline) not in wide):
        return {"method": method, "baseline": baseline, "n": 0}
    both = wide[[("correct", method), ("correct", baseline), ("cost", method), ("cost", baseline)]].dropna()
    d_acc = (both[("correct", method)] - both[("correct", baseline)]).to_numpy()
    d_cost = (both[("cost", method)] - both[("cost", baseline)]).to_numpy()
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d_acc), size=(draws, len(d_acc))) if len(d_acc) else None
    acc_draws = d_acc[idx].mean(axis=1) if idx is not None else np.array([np.nan])
    return {"method": method, "baseline": baseline, "n": int(len(d_acc)),
            "d_acc": float(d_acc.mean()) if len(d_acc) else float("nan"),
            "d_acc_lo": float(np.quantile(acc_draws, 0.025)), "d_acc_hi": float(np.quantile(acc_draws, 0.975)),
            "d_cost": float(d_cost.mean()) if len(d_cost) else float("nan")}
