"""Replay hooks: score any composition of samples already drawn, exactly and for free.

Samples of a config on an item are independent draws (distinct seeds), so any vote over any subset of them, any mix
of configs and any cascade has a known answer on every item without a new generation.

Terms (plain words first):
  answer class  answers the benchmark's grader calls equal share a class on an item (bbeh grader for BBEH, math
                equivalence for math, identical behaviour for code); unparsed answers belong to no class. A class is
                right when its members are (for code, the mean correctness of its members).
  part          (system, n): n samples of one config. A composition is a list of parts, e.g. [(W4 config, 4)].
  vote credit   the plurality class's correctness, i.e. the mean correctness of the composition's own calls in that
                class (for code, members of a behaviour class can differ on hidden tests); when several classes tie
                for the most votes, the mean over the tied classes (the expected score of a random tie-break). No
                parsed answer scores 0. A 2-vote therefore equals one sample in expectation (agree: that answer;
                disagree: a coin flip), so 2-sample arms are scored by a selector (the judge), not by a vote.
  expected vote a part of n out of the k drawn samples can be any of the C(k, n) subsets; the composition's score on
                an item is the mean vote credit over all subset combinations (at most MAX_COMBOS, else a fixed
                pseudo-random selection of them). This removes the luck of which samples were drawn first.
  cost          of a composition on an item: n x the config's mean cost per sample on that item, summed over parts.
                The default cost is cost_tokens (decode-token units); pass kernel seconds to Samples.from_table for
                real-kernel GPU-seconds.
  cascade       a first-round composition answers when its plurality share (votes for the top class / calls) is at
                least t; otherwise one sample of the escalation config answers (its mean correctness: the expected
                score of one sample). pruning/cascade.py runs the weighted-vote version on a Panel (`to_panel`).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..pruning.replay import Panel
from ..tasks import answers_match, bbeh_normalize, normalize

MAX_COMBOS = 200
GRADER_OF = {"bbeh": "bbeh", "math": "math", "code": "code"}


def _key(answer: str, grader: str) -> str:
    if grader == "bbeh":
        return bbeh_normalize(answer)
    if grader in ("exact", "choice"):
        return normalize(answer) or ""
    return answer


def add_classes(table: pd.DataFrame, grader_of: dict | None = None) -> pd.DataFrame:
    """The table with `cls`: per item, an integer answer class (-1 when unparsed). Math answers are compared with
    math-verify against each class's first member; other graders by a normalized key."""
    graders = grader_of or GRADER_OF
    out = []
    for (bench, item), part in table.groupby(["benchmark", "item"], sort=False):
        grader = graders.get(str(bench).split("/", 1)[0], "exact")
        parsed = (part["answer"].notna() & (part["answer"].astype(str) != "None")).to_numpy(dtype=bool)
        cls = np.full(len(part), -1)
        reps: list[str] = []
        keys: dict[str, int] = {}
        for pos, (ok, a) in enumerate(zip(parsed, part["answer"].astype(str).to_numpy())):
            if not ok:
                continue
            if grader == "math":
                home = next((c for c, r in enumerate(reps) if answers_match(r, a, "math")), None)
                if home is None:
                    reps.append(a)
                    home = len(reps) - 1
            else:
                key = _key(a, grader)
                if key not in keys:
                    keys[key] = len(keys)
                home = keys[key]
            cls[pos] = home
        out.append(part.assign(cls=cls))
    return pd.concat(out).loc[table.index]


@dataclass
class Samples:
    """Items x k arrays per system: answer classes, correctness and cost; class correctness per item."""

    items: list[str]
    k: int
    cls: dict
    right: dict
    cost: dict
    class_right: np.ndarray

    @classmethod
    def from_table(cls_, table: pd.DataFrame, cost: pd.Series | None = None) -> "Samples":
        """cost: per row (aligned with table), the cost of each call; default cost_tokens(table)."""
        t = table if "cls" in table else add_classes(table)
        items = sorted(t["item"].unique())
        k = int(t["call"].max()) + 1
        index = pd.MultiIndex.from_product([items, range(k)], names=["item", "call"])
        cls, right, costs = {}, {}, {}
        t = t.assign(_cost=cost_tokens(t) if cost is None else cost.reindex(t.index))
        for system, part in t.groupby("system"):
            wide = part.set_index(["item", "call"]).reindex(index)
            cls[system] = wide["cls"].fillna(-1).to_numpy(dtype=int).reshape(len(items), k)
            right[system] = wide["correct"].fillna(0).to_numpy(dtype=float).reshape(len(items), k)
            costs[system] = wide["_cost"].fillna(0).to_numpy(dtype=float).reshape(len(items), k)
        width = int(t["cls"].max()) + 2
        cr = t[t["cls"] >= 0].groupby(["item", "cls"])["correct"].mean()
        class_right = np.zeros((len(items), width))
        pos = {item: i for i, item in enumerate(items)}
        for (item, c), v in cr.items():
            class_right[pos[item], int(c)] = v
        return cls_(items, k, cls, right, costs, class_right)

    def subset(self, rows) -> "Samples":
        rows = np.asarray(rows)
        pick = lambda d: {s: a[rows] for s, a in d.items()}
        return Samples([self.items[r] for r in rows], self.k, pick(self.cls), pick(self.right), pick(self.cost),
                       self.class_right[rows])


def vote_credit(C: np.ndarray, R: np.ndarray, width: int | None = None) -> np.ndarray:
    """Per item (row): the vote credit of the calls with answer classes C (-1 unparsed) and correctness R. The winning
    class scores the mean correctness of the composition's own calls in it (for code, programs with the same public
    behaviour can differ on hidden tests, so a class's credit is that of the members actually voting); tied classes
    are averaged."""
    n = C.shape[0]
    width = int(C.max()) + 1 if width is None else width
    width = max(width, 1)
    counts = np.zeros((n, width))
    right = np.zeros((n, width))
    rows = np.repeat(np.arange(n), C.shape[1])
    flat, r = C.ravel(), R.ravel()
    ok = flat >= 0
    np.add.at(counts, (rows[ok], flat[ok]), 1)
    np.add.at(right, (rows[ok], flat[ok]), r[ok])
    top = counts.max(axis=1, keepdims=True)
    tied = (counts == top) & (top > 0)
    class_mean = right / np.maximum(counts, 1)
    return np.where(top[:, 0] > 0, (tied * class_mean).sum(axis=1) / np.maximum(tied.sum(axis=1), 1), 0.0)


def _combos(k: int, parts: list[tuple[str, int]]) -> list[tuple]:
    per_part = [list(itertools.combinations(range(k), n)) for _, n in parts]
    total = int(np.prod([len(p) for p in per_part]))
    if total <= MAX_COMBOS:
        return list(itertools.product(*per_part))
    rng = np.random.default_rng(7)
    return [tuple(p[rng.integers(len(p))] for p in per_part) for _ in range(MAX_COMBOS)]


def expected_vote(s: Samples, parts: list[tuple[str, int]]) -> np.ndarray:
    """Per item: the composition's vote credit averaged over sample subsets."""
    total = np.zeros(len(s.items))
    combos = _combos(s.k, parts)
    width = s.class_right.shape[1]
    for combo in combos:
        C = np.concatenate([s.cls[system][:, list(cols)] for (system, _), cols in zip(parts, combo)], axis=1)
        R = np.concatenate([s.right[system][:, list(cols)] for (system, _), cols in zip(parts, combo)], axis=1)
        total += vote_credit(C, R, width)
    return total / len(combos)


def cost_tokens(table: pd.DataFrame) -> pd.Series:
    """The cost of a call in decode-token units: output tokens + 0.1 x input tokens (prefill costs about a tenth of
    decoding per token). Within one checkpoint, GPU time is close to proportional to it; unlike measured
    gpu_seconds it does not depend on which calls came from the cache."""
    return table["output_tokens"].astype(float) + 0.1 * table["input_tokens"].astype(float)


def composition_cost(s: Samples, parts: list[tuple[str, int]]) -> np.ndarray:
    return sum(n * s.cost[system].mean(axis=1) for system, n in parts)


def expected_cascade(s: Samples, first: list[tuple[str, int]], escalate: str, t: float) -> tuple[np.ndarray, np.ndarray]:
    """(credit, cost) per item of a cascade, averaged over first-round subsets; escalation = one sample of
    `escalate` (scored at its mean correctness and mean cost on the item)."""
    combos = _combos(s.k, first)
    n_calls = sum(n for _, n in first)
    credit = np.zeros(len(s.items))
    seconds = np.zeros(len(s.items))
    esc_right, esc_cost = s.right[escalate].mean(axis=1), s.cost[escalate].mean(axis=1)
    for combo in combos:
        C = np.concatenate([s.cls[system][:, list(cols)] for (system, _), cols in zip(first, combo)], axis=1)
        G = np.concatenate([s.cost[system][:, list(cols)] for (system, _), cols in zip(first, combo)], axis=1)
        R = np.concatenate([s.right[system][:, list(cols)] for (system, _), cols in zip(first, combo)], axis=1)
        width = s.class_right.shape[1]
        counts = np.zeros((len(s.items), width))
        rows = np.repeat(np.arange(len(s.items)), C.shape[1])
        ok = C.ravel() >= 0
        np.add.at(counts, (rows[ok], C.ravel()[ok]), 1)
        accept = counts.max(axis=1) / n_calls >= t - 1e-9
        credit += np.where(accept, vote_credit(C, R, width), esc_right)
        seconds += G.sum(axis=1) + np.where(accept, 0.0, esc_cost)
    return credit / len(combos), seconds / len(combos)


def compositions(systems: pd.DataFrame, k: int = 6, escalate: str | None = None) -> list[dict]:
    """Every composition the testbed replays (for T5 and the tables). `systems`: one row per config with columns
    system, size_b, precision, budget (table.configs). Kinds:
      vote      k-votes n = 1..k of each config
      mixprec   at one size and budget, n/2 samples of each of two precisions (n = 2, 4, 6)
      mixsize   at one precision and budget, n/2 samples of each of two sizes (n = 2, 4, 6)
      cascade   a 3-vote of any config that is not the escalation config, escalating to one sample of `escalate`
                when fewer than all 3 agree (t = 1) or fewer than 2 of 3 (t = 2/3)."""
    out = []
    for system in systems["system"]:
        out += [{"kind": "vote", "name": f"{system} x{n}", "parts": [(system, n)]} for n in range(1, k + 1)]
    for (size, budget), part in systems.groupby(["size_b", "budget"]):
        for a, b in itertools.combinations(part.sort_values("precision")["system"], 2):
            out += [{"kind": "mixprec", "name": f"{a}+{b} x{n}", "parts": [(a, n // 2), (b, n // 2)]} for n in (2, 4, 6)]
    for (precision, budget), part in systems.groupby(["precision", "budget"]):
        for a, b in itertools.combinations(part.sort_values("size_b")["system"], 2):
            out += [{"kind": "mixsize", "name": f"{a}+{b} x{n}", "parts": [(a, n // 2), (b, n // 2)]} for n in (2, 4, 6)]
    if escalate is not None:
        for system in systems["system"]:
            if system != escalate:
                out += [{"kind": "cascade", "name": f"{system} x3 -> {escalate} @{t:.2f}", "parts": [(system, 3)],
                         "escalate": escalate, "t": t} for t in (1.0, 2 / 3)]
    return out


def score(s: Samples, comp: dict) -> tuple[np.ndarray, np.ndarray]:
    """(credit, cost) per item of one composition."""
    if comp["kind"] == "cascade":
        return expected_cascade(s, comp["parts"], comp["escalate"], comp["t"])
    return expected_vote(s, comp["parts"]), composition_cost(s, comp["parts"])


def to_panel(table: pd.DataFrame, grader: str = "bbeh") -> Panel:
    """The table as a pruning.replay Panel (one unit per system and call; `cost` holds cost_tokens), so the pruning
    searches and pruning/cascade.py's weighted cascades run on testbed samples unchanged."""
    calls = table.drop(columns="source").rename(columns={"system": "source"}).assign(
        parsed=lambda t: t["answer"].notna() & (t["answer"].astype(str) != "None"),
        cost_usd=cost_tokens, seconds=cost_tokens,
        answer=lambda t: t["answer"].astype(str))
    return Panel.from_calls(calls[["item", "source", "call", "answer", "parsed", "correct", "cost_usd", "seconds"]],
                            grader=grader)
