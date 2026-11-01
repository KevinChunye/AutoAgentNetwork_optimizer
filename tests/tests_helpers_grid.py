"""A synthetic 1/3/6 factorial landscape (27 configs) for the analysis tests."""

import itertools

import numpy as np
import pandas as pd

from analysis.landscape import Landscape


def grid_landscape(n_tasks: int = 60, seed: int = 1) -> Landscape:
    """Accuracy rises 8 points per doubling of proposers and 3 per doubling of refiners;
    critique adds nothing; cost grows with agents."""
    rng = np.random.default_rng(seed)
    keeps = list(itertools.product([1, 3, 6], [1, 3, 6], [1, 3, 6]))
    ids = [f"k{a}-{b}-{c}-1" for a, b, c in keeps]
    configs = pd.DataFrame(keeps, columns=["k_propose", "k_critique", "k_refine"], index=ids)
    configs["agents"] = configs.sum(axis=1) + 1
    tasks = [f"t{i:02d}" for i in range(n_tasks)]
    p = (0.35 + 0.08 * np.log2(configs["k_propose"].to_numpy())[:, None]
         + 0.03 * np.log2(configs["k_refine"].to_numpy())[:, None]).clip(0.01, 0.99)
    correct = pd.DataFrame((rng.random((len(ids), n_tasks)) < p).astype(float), index=ids, columns=tasks)
    per_config = 0.001 * configs["k_propose"] + 0.0005 * configs["k_critique"] + 0.001 * configs["k_refine"] + 0.0003
    cost = pd.DataFrame(np.repeat(per_config.to_numpy()[:, None], n_tasks, axis=1), index=ids, columns=tasks)
    agrees = correct.eq(correct.loc["k6-6-6-1"], axis=1).astype(float)
    return Landscape(correct=correct, agrees=agrees, cost=cost, tokens=cost * 1e6, configs=configs,
                     dense_id="k6-6-6-1", rows=pd.DataFrame())
