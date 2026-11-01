"""The search space for structured pruning: stage s keeps 1..width_s agents.

3x6+1 network (three stages of six agents and one aggregator): 6*6*6*1 = 216 configs.
4x5+1 network: 5^4 = 625 configs.
"""

from __future__ import annotations

import itertools
import math

from ..network.spec import NetworkSpec, PruneConfig


class PruneSpace:
    def __init__(self, network: NetworkSpec):
        self.network = network

    def size(self) -> int:
        return math.prod(self.network.widths)

    def configs(self) -> list[PruneConfig]:
        ranges = [range(1, w + 1) for w in self.network.widths]
        return [PruneConfig(keep=list(keep)) for keep in itertools.product(*ranges)]

    def factorial(self, levels: list[int]) -> list[PruneConfig]:
        """A grid over a few keep levels per stage instead of every count, e.g. levels
        [1, 3, 6] gives 27 configs of dense_3x6 instead of 216. Levels above a stage's
        width are capped; one-agent stages keep 1; 0 (skip the stage) applies only to
        middle llm stages. Because configs share their upstream calls, [1, 3, 6] costs
        105 calls per task against 474 for all 216 configs, so the same money buys
        about 4.5 times as many tasks."""
        last = len(self.network.stages) - 1
        per_stage = []
        for s, stage in enumerate(self.network.stages):
            if stage.width == 1:
                per_stage.append([1])
                continue
            allowed = [min(level, stage.width) for level in levels if level > 0 or (0 < s < last and stage.kind == "llm")]
            per_stage.append(sorted(set(allowed)))
        return [PruneConfig(keep=list(keep)) for keep in itertools.product(*per_stage)]

    def from_keep_fractions(self, fractions: list[float]) -> PruneConfig:
        """fractions[s] = share of stage s's agents to keep, in (0, 1]. This is the
        AMC action. keep = fraction x width, rounded half up, at least 1."""
        if len(fractions) != len(self.network.stages):
            raise ValueError(f"{len(fractions)} fractions for {len(self.network.stages)} stages")
        keep = [max(1, min(w, math.floor(f * w + 0.5))) for f, w in zip(fractions, self.network.widths)]
        return PruneConfig(keep=keep)
