"""Induced values and costs, and the competitive equilibrium they imply.

Terms:
  buyer value    the most a buyer can pay for its one unit; a buyer who buys at price p earns
                 value - p (its profit), and earns nothing if it does not trade.
  seller cost    the least a seller can accept for its one unit; a seller who sells at price p
                 earns p - cost.
  rank           position in the schedule: buyer rank 1 has the highest value, seller rank 1 the
                 lowest cost. Ranks start at 1.
  demand / supply   the buyer values sorted high to low, and the seller costs sorted low to high.
  Q* (competitive quantity)   the number of units traded where demand meets supply: the largest q
                 with the q-th highest value at or above the q-th lowest cost.
  P* (competitive price)      any price that clears the market at Q*: at least the Q*-th cost and the
                 (Q*+1)-th value, at most the Q*-th value and the (Q*+1)-th cost. `p_low` and `p_high`
                 bound that range; `p_star` is its midpoint, the price used for Smith's alpha and for
                 CE profit.
  maximum surplus   the sum of value - cost over the Q* pairs that trade at P*: the most total
                 profit any allocation of the units can produce.
  intramarginal  a trader who trades at P* (buyer or seller rank <= Q*); extramarginal traders
                 (rank > Q*) should not trade, and a trade by one of them lowers efficiency. On the Smith
                 schedule the rank-6 pair (value 2.00, cost 2.00) is intramarginal with zero CE profit.
  CE profit      a trader's profit if every trade happened at p_star: value - p_star for an
                 intramarginal buyer, p_star - cost for an intramarginal seller, 0 otherwise.
"""

from __future__ import annotations

from pydantic import BaseModel, model_validator

# Smith (1962) Test 1, as used by Struski et al. (arXiv 2609.02580, Section 3.1): 11 buyers and 11 sellers,
# values and costs from $0.75 to $3.25 in $0.25 steps; P* = 2.00, Q* = 6 (the 6th pair, 2.00 / 2.00, has
# zero surplus), maximum surplus 7.50. The default, so results compare with Smith's humans and Struski's
# LLMs (research/lit/market.md).
SMITH_VALUES = [3.25, 3.00, 2.75, 2.50, 2.25, 2.00, 1.75, 1.50, 1.25, 1.00, 0.75]
SMITH_COSTS = [0.75, 1.00, 1.25, 1.50, 1.75, 2.00, 2.25, 2.50, 2.75, 3.00, 3.25]
# The fallback schedule from Kevin's market-town prompt (P* in [1.95, 2.05], Q* = 6, maximum surplus 6.10),
# kept as a robustness variant.
FALLBACK_VALUES = [3.00, 2.80, 2.60, 2.40, 2.20, 2.05, 1.95, 1.80, 1.60, 1.40, 1.20]
FALLBACK_COSTS = [1.00, 1.20, 1.40, 1.60, 1.80, 1.95, 2.05, 2.20, 2.40, 2.60, 2.80]


class Schedule(BaseModel):
    """One unit per trader. `values[i]` belongs to buyer B{i+1}, `costs[i]` to seller S{i+1};
    both lists are given in rank order (values high to low, costs low to high)."""

    values: list[float] = SMITH_VALUES
    costs: list[float] = SMITH_COSTS

    @model_validator(mode="after")
    def _ranked(self) -> "Schedule":
        if self.values != sorted(self.values, reverse=True) or self.costs != sorted(self.costs):
            raise ValueError("list buyer values high to low and seller costs low to high (rank order)")
        return self

    @property
    def q_star(self) -> int:
        q = 0
        while q < min(len(self.values), len(self.costs)) and self.values[q] >= self.costs[q]:
            q += 1
        return q

    @property
    def p_low(self) -> float:
        q = self.q_star
        candidates = [self.costs[q - 1]] if q else [self.costs[0]]
        if q < len(self.values):
            candidates.append(self.values[q])
        return max(candidates)

    @property
    def p_high(self) -> float:
        q = self.q_star
        candidates = [self.values[q - 1]] if q else [self.values[0]]
        if q < len(self.costs):
            candidates.append(self.costs[q])
        return min(candidates)

    @property
    def p_star(self) -> float:
        return round((self.p_low + self.p_high) / 2, 4)

    @property
    def max_surplus(self) -> float:
        q = self.q_star
        return round(sum(self.values[:q]) - sum(self.costs[:q]), 4)

    def buyer_ids(self) -> list[str]:
        return [f"B{i}" for i in range(1, len(self.values) + 1)]

    def seller_ids(self) -> list[str]:
        return [f"S{i}" for i in range(1, len(self.costs) + 1)]

    def ce_profit(self, role: str, rank: int) -> float:
        """Profit at p_star for the trader of this role and rank (0 for extramarginal traders)."""
        if rank > self.q_star:
            return 0.0
        if role == "buyer":
            return round(self.values[rank - 1] - self.p_star, 4)
        return round(self.p_star - self.costs[rank - 1], 4)
