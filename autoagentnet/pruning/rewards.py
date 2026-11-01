"""Reward functions for the pruning search.

Terms:
  error       share of tasks the network answers wrongly (against gold answers).
  recon_error share of tasks where its final answer differs from the dense
              network's. Pass it as `error` for a label-free reward.
  cost        the resource being cut: tokens, dollars or FLOPs.
  dense_cost  the same resource for the unpruned (dense) network.
"""

from __future__ import annotations

import math


def amc_log_cost(error: float, cost: float) -> float:
    """AMC's R_FLOPs = -error * log(cost). Kept to compare against AMC.

    It has three problems on agent networks:
      - error = 0 gives reward 0 at any cost, so cost stops mattering once a config is perfect;
      - cost below 1 (dollars, for example) flips the sign of log, so measure cost in tokens or FLOPs;
      - halving the cost is worth only error*ln2/ln(cost) error points
        (about 1 point at error 0.2 and cost 1e6 tokens).
    """
    if cost <= 1:
        raise ValueError("amc_log_cost needs cost > 1; use tokens or FLOPs, not dollars")
    return -error * math.log(cost)


def error_plus_log_cost(error: float, cost: float, dense_cost: float, lam: float = 0.05) -> float:
    """-error - lam * log2(cost / dense_cost).

    Each halving of cost is worth `lam` error points (lam = 0.05 means 5 points),
    whatever the current error, and the dense network scores exactly -error.
    """
    return -error - lam * math.log2(cost / dense_cost)


def budgeted_error(error: float, cost: float, budget: float) -> float:
    """AMC's resource-constrained mode: -error if cost <= budget, otherwise -1
    (worse than any config that fits the budget)."""
    return -error if cost <= budget else -1.0
