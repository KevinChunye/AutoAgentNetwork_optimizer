"""How a default moves through a multi-agent pipeline, measured from AutoAgentNetwork runs.

The dense network (configs/networks/dense_3x6.yaml) has six proposers, then critique, refine and
an aggregator, all on one model. For each task replicate we know how many proposers were wrong,
and whether each downstream agent ended up wrong. Terms:

  upstream wrong share  w: share of the six proposers whose answer was wrong (0, 1/6, ..., 1)
  adoption curve        P(downstream agent wrong | w), by stage. A pipeline that "corrects"
                        has this below w; one that "amplifies" has it above w
  spontaneous rate      P(downstream wrong | w = 0): errors a downstream agent adds on its own
  unanimity rate        P(w = 1): every proposer wrong at once. If proposers erred independently
                        with mean rate p, this would be p^6. The ratio of observed to independent
                        is the monoculture factor: how much one model's agents fail together
  proposer ICC          intra-class correlation of wrongness among the six proposers of a task
  network multiplier    P(network default) / P(single-agent default) on the same tasks: what an
                        underwriter applies to a single-agent rate when the insured runs a pipeline
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .actuarial import icc_beta_binomial

BUCKETS = [-0.01, 0.0, 0.34, 0.67, 0.99, 1.0]
BUCKET_LABELS = ["0/6", "1-2/6", "3-4/6", "5/6", "6/6"]


def proposer_table(agents: pd.DataFrame, width: int = 6) -> pd.DataFrame:
    """Per task replicate: proposers that answered and the share that were wrong."""
    p = agents[agents["stage"].eq("propose")]
    t = p.groupby(["task_id", "family", "replicate"], as_index=False).agg(
        n_prop=("correct", "size"), right=("correct", "sum"))
    t = t[t["n_prop"].eq(width)].copy()
    t["wrong"] = t["n_prop"] - t["right"]
    t["wrong_share"] = t["wrong"] / t["n_prop"]
    return t


def adoption_curve(agents: pd.DataFrame) -> pd.DataFrame:
    """P(downstream agent wrong) by stage and upstream wrong share bucket."""
    prop = proposer_table(agents)
    rows = []
    for stage in ["critique", "refine", "aggregate"]:
        d = agents[agents["stage"].eq(stage)].merge(prop[["task_id", "replicate", "wrong_share"]],
                                                    on=["task_id", "replicate"])
        if d.empty:
            continue
        d["bucket"] = pd.cut(d["wrong_share"], BUCKETS, labels=BUCKET_LABELS)
        d["wrong"] = 1 - d["correct"]
        g = d.groupby("bucket", observed=True).agg(n=("wrong", "size"), p_wrong=("wrong", "mean"),
                                                   mean_w=("wrong_share", "mean")).reset_index()
        g["stage"] = stage
        rows.append(g)
    return pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()


def monoculture(agents: pd.DataFrame) -> dict:
    """Unanimity of proposer errors against what independent errors would give."""
    prop = proposer_table(agents)
    p = 1 - prop["right"].sum() / prop["n_prop"].sum()
    width = int(prop["n_prop"].mode().iloc[0])
    observed = float(prop["wrong"].eq(width).mean())
    independent = float(p ** width)
    counts = prop.rename(columns={"n_prop": "m", "wrong": "k"})[["m", "k"]]
    return {"replicates": int(len(prop)), "proposer_wrong_rate": float(p),
            "all_wrong_observed": observed, "all_wrong_if_independent": independent,
            "monoculture_factor": observed / independent if independent > 0 else float("nan"),
            "all_right_observed": float(prop["wrong"].eq(0).mean()),
            "proposer_icc": icc_beta_binomial(counts)}


def network_multiplier(network_eps: pd.DataFrame) -> pd.DataFrame:
    """Default rates of the dense pipeline and the single agent on the tasks both answered.

    Uses Haiku rows only (both products run Haiku 5.5), paired by task and replicate.
    """
    h = network_eps[network_eps["model"].eq("haiku-5.5")]
    wide = h.pivot_table(index=["task_id", "trial"], columns="product", values="default", aggfunc="mean").dropna()
    if wide.empty or "dense_3x6" not in wide or "single" not in wide:
        return pd.DataFrame()
    rng = np.random.default_rng(0)
    tasks = wide.reset_index()["task_id"].unique()
    boots = []
    for _ in range(2000):
        pick = rng.choice(tasks, size=len(tasks), replace=True)
        w = pd.concat([wide.xs(t, level="task_id") for t in pick])
        boots.append(w["dense_3x6"].mean() / max(w["single"].mean(), 1e-9))
    return pd.DataFrame([{
        "pairs": len(wide), "tasks": len(tasks),
        "p_single": float(wide["single"].mean()), "p_dense": float(wide["dense_3x6"].mean()),
        "multiplier": float(wide["dense_3x6"].mean() / wide["single"].mean()),
        "mult_lo": float(np.percentile(boots, 2.5)), "mult_hi": float(np.percentile(boots, 97.5))}])
