"""The self-or-social policy: an empirical table, fitted on calibration (dev) items only and frozen before the test.

Terms (all per receiver i, the agent deciding what to do after the first round):
  state      i's agreement state in the first round (protocol.agreement_states): all_agree, majority, minority,
             split or none. Computed from the parsed first answers alone; never from the gold.
  family     the item's BBEH task (e.g. "word sorting"); optional feature (use_family).
  P(a)       the estimated probability that i's final answer is correct if i takes action a. For stop it is the
             chance that i's first answer is correct; for reflect and consult:J the chance its revision is.
  cost(a)    the mean extra dollars of action a for receiver i on the calibration items (stop: 0). The policy uses
             this mean, never the cost of the call it is deciding about.
  lam        dollars-to-accuracy exchange rate: one dollar of extra cost is worth lam points of P (0-1 scale).
             lam = 30 means $0.001 costs 0.03 of P.
  U(a)       P(a) - lam * cost(a). The receiver takes the action with the largest U; ties go to the cheaper kind
             (stop, then reflect, then consult in team order).

Estimating P with shrinkage: cells go from coarse to fine,
  L0 = action kind (stop / reflect / consult), pooled over receivers;
  L1 = (receiver, action);  L2 = (receiver, state, action);  L3 = (family, receiver, state, action) if use_family.
Each finer estimate is (successes + shrink * coarser estimate) / (count + shrink), so a cell with few calibration
items stays close to the coarser one. An action never seen in calibration has no estimate and is not taken; a
receiver with no estimated action stops (the conservative fallback).

Directed value of a peer: social_net_gain(J -> i) = P(consult:J right and reflect wrong) - P(consult:J wrong and
reflect right), over the calibration items, paired on the same first answers. It is the net change in i's accuracy
from reading J instead of re-checking alone. It is directed: J -> i and i -> J are different numbers.
"""

from __future__ import annotations

import hashlib
import json
import math

import pandas as pd
from pydantic import BaseModel, ConfigDict, field_validator

from .protocol import CONSULT, REFLECT, STOP, actions_for, agreement_states, kind_of, peer_of

KIND_ORDER = {STOP: 0, REFLECT: 1, CONSULT: 2}


def voting_answers(calls: pd.DataFrame) -> pd.DataFrame:
    """The rows with the answer of every unparsed row blanked (the repo's read rule: an unparsed or truncated call is
    wrong and casts no vote; protocol.grade_reply). A BBEH row is unparsed exactly when it has no answer, so this
    changes no BBEH row; a math row keeps an unreadable answer's text in calls.csv, and it is blanked here."""
    if "parsed" not in calls:
        return calls
    return calls.assign(answer=calls["answer"].where(calls["parsed"].fillna(False).astype(bool)))


def branch_table(calls: pd.DataFrame) -> pd.DataFrame:
    """One row per (item, receiver, action) that a policy can choose: stop (from the first answer), reflect and
    consult:J (from revision calls). Input: the runner's calls.csv rows (columns item, family, grader, receiver,
    action, answer, correct, cost_usd; action "initial" for first answers). Output columns:
      item, family, receiver, action, kind, answer, correct, extra_cost (the action's own dollars; stop 0),
      state (the receiver's first-round agreement state), initial_cost (the item's first-answer dollars, every member).
    `full` rows are left out (full review is a control, not a policy action). An unparsed row casts no vote and
    counts as no answer in the agreement states (voting_answers)."""
    calls = voting_answers(calls)
    first = calls[calls["action"] == "initial"].copy()
    rows = []
    for item, group in first.groupby("item", sort=False):
        group = group.sort_values("position")
        answers = [None if pd.isna(a) else str(a) for a in group["answer"]]
        states = agreement_states(answers, str(group["grader"].iloc[0]))
        for (_, row), state in zip(group.iterrows(), states):
            rows.append({"item": item, "receiver": row["receiver"], "state": state})
    states = pd.DataFrame(rows, columns=["item", "receiver", "state"])
    initial_cost = first.groupby("item")["cost_usd"].sum().rename("initial_cost")
    stop = first.assign(action=STOP, extra_cost=0.0)
    revisions = calls[calls["action"].map(lambda a: kind_of(a) in (REFLECT, CONSULT))].assign(
        extra_cost=lambda d: d["cost_usd"])
    table = pd.concat([stop, revisions], ignore_index=True)[
        ["item", "family", "receiver", "action", "answer", "correct", "extra_cost"]]
    table = table.assign(kind=table["action"].map(kind_of))
    table = table.merge(states, on=["item", "receiver"], how="left").merge(initial_cost, on="item", how="left")
    return table


def social_net_gain(table: pd.DataFrame) -> pd.DataFrame:
    """Directed net gain of each consult edge over reflection, paired by (item, receiver).
    Columns: receiver, sender, n (paired items), fix (consult right, reflect wrong), harm (consult wrong, reflect
    right), gain = fix - harm, consult_acc, reflect_acc."""
    reflect = table[table["kind"] == REFLECT][["item", "receiver", "correct"]].rename(columns={"correct": "r"})
    cons = table[table["kind"] == CONSULT][["item", "receiver", "action", "correct"]].rename(columns={"correct": "c"})
    paired = cons.merge(reflect, on=["item", "receiver"], how="inner")
    paired = paired.assign(sender=paired["action"].map(peer_of),
                           fix=(paired["c"] > 0.5) & (paired["r"] < 0.5), harm=(paired["c"] < 0.5) & (paired["r"] > 0.5))
    out = paired.groupby(["receiver", "sender"]).agg(n=("c", "size"), fix=("fix", "mean"), harm=("harm", "mean"),
                                                    consult_acc=("c", "mean"), reflect_acc=("r", "mean")).reset_index()
    return out.assign(gain=out["fix"] - out["harm"]).sort_values(["receiver", "sender"]).reset_index(drop=True)


def fixed_peers(table: pd.DataFrame) -> dict[str, str]:
    """Each receiver's fixed peer: the sender with the largest directed social_net_gain on the calibration items
    (ties: team order of the sender as it appears)."""
    gains = social_net_gain(table).sort_values(["receiver", "gain"], ascending=[True, False], kind="stable")
    return dict(gains.groupby("receiver")["sender"].first())


def smartest_peers(table: pd.DataFrame) -> dict[str, str]:
    """Each receiver's peer chosen without direction: the other member with the highest first-answer accuracy on
    the calibration items (the ablation that drops the directed estimate)."""
    acc = table[table["kind"] == STOP].groupby("receiver")["correct"].mean().sort_values(ascending=False, kind="stable")
    return {r: next(s for s in acc.index if s != r) for r in acc.index}


class Policy(BaseModel):
    """A frozen policy. `cells` maps a level ("L0".."L3") to {cell key: [successes, count]}; `costs` maps
    "receiver|action" to the mean extra dollars. Fit with `fit`; decide with `choose`. It holds no item ids and
    no answers, only counts per cell."""

    model_config = ConfigDict(extra="forbid")
    team: list[str]
    lam: float = 0.0
    shrink: float = 5.0
    use_family: bool = False
    kinds: list[str] = [STOP, REFLECT, CONSULT]  # the action kinds this policy may take
    allow_stop: bool = True  # False: every receiver revises (the forced-revision ablation)
    cells: dict[str, dict[str, list[float]]] = {}
    costs: dict[str, float] = {}

    @field_validator("lam", "shrink")
    @classmethod
    def _finite(cls, v: float) -> float:
        if not math.isfinite(v) or v < 0:
            raise ValueError(f"lam and shrink must be finite and >= 0, got {v}")
        return v

    def hash(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]

    def to_json(self) -> str:
        return json.dumps(self.model_dump(), indent=1, sort_keys=True)

    @classmethod
    def from_json(cls, text: str) -> "Policy":
        return cls(**json.loads(text))

    def keys(self, receiver: str, state: str, family: str, action: str) -> list[tuple[str, str]]:
        """(level, cell key) from coarse to fine."""
        out = [("L0", kind_of(action)), ("L1", f"{receiver}|{action}"), ("L2", f"{receiver}|{state}|{action}")]
        if self.use_family:
            out.append(("L3", f"{family}|{receiver}|{state}|{action}"))
        return out

    def p_correct(self, receiver: str, state: str, family: str, action: str) -> float | None:
        """The shrunk estimate of P(correct) for this action, or None if calibration never saw it."""
        p = None
        for level, key in self.keys(receiver, state, family, action):
            hits, n = self.cells.get(level, {}).get(key, [0.0, 0.0])
            if p is None:
                p = hits / n if n > 0 else None
            else:
                p = (hits + self.shrink * p) / (n + self.shrink)
        return p

    def cost(self, receiver: str, action: str) -> float | None:
        if action == STOP:
            return 0.0
        c = self.costs.get(f"{receiver}|{action}")
        return c if c is not None and math.isfinite(c) and c >= 0 else None

    def scores(self, receiver: str, state: str, family: str) -> pd.DataFrame:
        """Every candidate action with its P, cost and U (rows in tie-break order; unestimated actions dropped)."""
        rows = []
        for action in actions_for(receiver, [_Id(t) for t in self.team]):
            if kind_of(action) not in self.kinds or (action == STOP and not self.allow_stop):
                continue
            p, c = self.p_correct(receiver, state, family, action), self.cost(receiver, action)
            if p is None or c is None or not math.isfinite(p):
                continue
            rows.append({"action": action, "p": p, "cost": c, "u": p - self.lam * c})
        return pd.DataFrame(rows, columns=["action", "p", "cost", "u"])

    def choose(self, receiver: str, state: str, family: str = "") -> str:
        """The receiver's action. Inputs are only what a deployed node knows before revising: its id, its
        first-round agreement state and the item's family. Fallback: stop (or reflect when stop is not allowed)."""
        if receiver not in self.team:
            raise ValueError(f"unknown receiver {receiver!r}; the team is {self.team}")
        table = self.scores(receiver, state, family)
        if table.empty:
            return STOP if self.allow_stop else REFLECT
        best = table["u"].max()
        return str(table[table["u"] >= best - 1e-12]["action"].iloc[0])


class _Id:
    """The minimal stand-in for protocol.Agent that actions_for needs (an `id`)."""

    def __init__(self, id: str):
        self.id = id


def fit(table: pd.DataFrame, team: list[str], lam: float = 0.0, shrink: float = 5.0, use_family: bool = False,
        kinds: list[str] | None = None, allow_stop: bool = True) -> Policy:
    """Fit the cells and costs from a calibration branch table (branch_table). Only `correct` and `extra_cost`
    of the calibration rows are used; the result is a Policy that stores counts per cell."""
    known = table[table["correct"].notna()]
    known = known.assign(hit=known["correct"].astype(float))
    level_cols = {"L0": ["kind"], "L1": ["receiver", "action"], "L2": ["receiver", "state", "action"],
                  "L3": ["family", "receiver", "state", "action"]}
    cells: dict[str, dict[str, list[float]]] = {}
    for level, cols in level_cols.items():
        if level == "L3" and not use_family:
            continue
        agg = known.groupby(cols)["hit"].agg(["sum", "count"]).reset_index()
        key = agg[cols].astype(str).agg("|".join, axis=1)
        cells[level] = {k: [float(s), float(n)] for k, s, n in zip(key, agg["sum"], agg["count"])}
    revisions = table[table["kind"] != STOP]
    mean_cost = revisions.groupby(["receiver", "action"])["extra_cost"].mean().reset_index()
    costs = {f"{r}|{a}": float(c) for r, a, c in zip(mean_cost["receiver"], mean_cost["action"], mean_cost["extra_cost"])
             if math.isfinite(c)}
    return Policy(team=team, lam=lam, shrink=shrink, use_family=use_family, kinds=kinds or [STOP, REFLECT, CONSULT],
                  allow_stop=allow_stop, cells=cells, costs=costs)
