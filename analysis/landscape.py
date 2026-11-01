"""Landscape analysis (P4): keep configs of dense_3x6 on a validation slice, either a factorial
grid (v2: levels 1/3/6 per stage, 27 configs) or the full 216.

Terms (all per config, averaged over a set of tasks):
  keep         [k_propose, k_critique, k_refine, 1]: agents kept per stage (1..6)
  error        share of tasks answered wrongly (labeled)
  recon_error  share of tasks whose final answer differs from the dense network's (label-free)
  cost         cache-aware list-price dollars per task, the config run on its own
  tokens       prompt + output tokens per task
  search half  tasks used to pick a config; held-out half: tasks used to score the pick
               (protocol 4.4: the best of 216 configs on the tasks it was picked on is biased)
  reward       -error - lam * log2(cost / dense cost) (autoagentnet.pruning.rewards): each
               halving of cost is worth `lam` error points; the dense network scores -error

The landscape is held as matrices with one row per config and one column per task, so any
statistic can be recomputed on a task subset or a bootstrap resample of tasks.

Usage: python -m analysis.landscape --search results/p4_x_landscape_a results/p4_x_landscape_b \
                                     --held results/p4_x_landscape_c results/p4_x_landscape_d
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from autoagentnet.pricing import PriceBook

from .common import (
    ROOT,
    bootstrap_mean_ci,
    paired_bootstrap_diff,
    color,
    save_figure,
    save_table,
    style,
    task_bootstrap_indices,
)

STAGES = ["propose", "critique", "refine"]


def keep_of(config_id: str) -> list[int]:
    """'k6-2-3-1' -> [6, 2, 3, 1]"""
    return [int(k) for k in config_id.split("_")[0][1:].split("-")]


@dataclass
class Landscape:
    """Per-config x per-task matrices (index: config_id, columns: task_id)."""

    correct: pd.DataFrame
    agrees: pd.DataFrame
    cost: pd.DataFrame
    tokens: pd.DataFrame
    configs: pd.DataFrame  # config_id -> k_propose, k_critique, k_refine, agents
    dense_id: str
    rows: pd.DataFrame  # the raw results rows (replicate 0)

    @property
    def tasks(self) -> list[str]:
        return list(self.correct.columns)


def load_landscape(folders: list[Path]) -> Landscape:
    rows = pd.concat([pd.read_csv(Path(f) / "results.csv") for f in folders], ignore_index=True)
    rows = rows[rows["replicate"] == 0]
    configs = pd.DataFrame({"config_id": rows["config_id"].unique()})
    keeps = pd.DataFrame(configs["config_id"].map(keep_of).tolist())
    for s, name in enumerate(STAGES):
        configs[f"k_{name}"] = keeps[s]
    configs["agents"] = keeps.sum(axis=1)
    configs = configs.set_index("config_id").sort_values("agents")
    dense_id = configs["agents"].idxmax()

    def matrix(column: str) -> pd.DataFrame:
        return rows.pivot(index="config_id", columns="task_id", values=column).loc[configs.index]

    cost = matrix("cost_usd")
    if (cost.to_numpy() == 0).all():  # fake-model dry run: nothing is priced, so rank by tokens instead
        print("WARNING: every cost is $0 (fake-model dry run); using tokens / 1e6 as the cost measure")
        cost = matrix("total_tokens") / 1e6
    return Landscape(matrix("correct"), matrix("agrees_with_dense"), cost, matrix("total_tokens"),
                     configs, dense_id, rows)


def summarize(L: Landscape, tasks: list[str] | None = None) -> pd.DataFrame:
    """One row per config: error, recon_error, cost, tokens over `tasks` (default: all)."""
    t = tasks if tasks is not None else L.tasks
    out = L.configs.copy()
    out["error"] = 1 - L.correct[t].mean(axis=1)
    out["recon_error"] = 1 - L.agrees[t].mean(axis=1)
    out["cost_usd"] = L.cost[t].mean(axis=1)
    out["tokens"] = L.tokens[t].mean(axis=1)
    out["cost_compression"] = out.loc[L.dense_id, "cost_usd"] / out["cost_usd"]
    return out


def reward(summary: pd.DataFrame, dense_id: str, lam: float = 0.05, label_free: bool = False) -> pd.Series:
    """error_plus_log_cost for every config (vectorized form of autoagentnet.pruning.rewards)."""
    err = summary["recon_error"] if label_free else summary["error"]
    return -err - lam * np.log2(summary["cost_usd"] / summary.loc[dense_id, "cost_usd"])


def pareto_front(summary: pd.DataFrame, cost_col: str = "cost_usd", err_col: str = "error") -> pd.DataFrame:
    """Configs that no other config beats on both cost and error (cheapest first)."""
    ordered = summary.sort_values([cost_col, err_col])
    best_so_far = ordered[err_col].cummin()
    keep = ordered[err_col] < best_so_far.shift(1, fill_value=math.inf)
    return ordered[keep]


def error_ci(L: Landscape, config_ids, tasks: list[str]) -> pd.DataFrame:
    """95% bootstrap CI of each config's error over `tasks`."""
    out = []
    for c in config_ids:
        mean, lo, hi = bootstrap_mean_ci(1 - L.correct.loc[c, tasks].to_numpy(dtype=float))
        out.append({"config_id": c, "error": mean, "error_lo": lo, "error_hi": hi})
    return pd.DataFrame(out).set_index("config_id")


def budgeted_pick(summary: pd.DataFrame, dense_id: str, share: float) -> str:
    """AMC's resource-constrained mode: lowest error among configs costing at most `share` of the
    dense network (ties: the cheaper config)."""
    fits = summary[summary["cost_usd"] <= share * summary.loc[dense_id, "cost_usd"]]
    return fits.sort_values(["error", "cost_usd"]).index[0]


def uniform_ids(summary: pd.DataFrame) -> list[str]:
    """Configs that keep the same number of agents in every stage."""
    same = (summary["k_propose"] == summary["k_critique"]) & (summary["k_critique"] == summary["k_refine"])
    return list(summary[same].sort_values("agents").index)


def sensitivity_pick(summary: pd.DataFrame, r: pd.Series) -> tuple[str, list[str]]:
    """AMC-style stage-by-stage sensitivity analysis: sweep one stage with the others dense,
    choose each stage's best keep independently, combine. Returns (pick, configs evaluated)."""
    widths = [int(summary[f"k_{s}"].max()) for s in STAGES]
    evaluated, best = [], []
    for s, name in enumerate(STAGES):
        sweep = summary
        for t, other in enumerate(STAGES):
            if t != s:
                sweep = sweep[sweep[f"k_{other}"] == widths[t]]
        evaluated += list(sweep.index)
        best.append(int(sweep.loc[r.loc[sweep.index].idxmax(), f"k_{name}"]))
    pick = f"k{best[0]}-{best[1]}-{best[2]}-1"
    evaluated = list(dict.fromkeys(evaluated + [pick]))
    return pick, evaluated


def interaction(summary: pd.DataFrame, n_tasks: int) -> dict:
    """How much of the error variation across configs an additive (no-interaction) model misses.

    additive model: error(k1,k2,k3) = grand mean + main effect of k1 + of k2 + of k3, estimated
    from group means (exact least squares for the balanced 6x6x6 grid).
    residual_share: residual variance / total variance across configs.
    noise_share: the share expected from binomial noise alone, mean p(1-p)/n over configs divided
    by the total variance; residual_share well above it suggests stages interact.
    """
    err = summary["error"]
    grand = err.mean()
    pred = pd.Series(grand, index=summary.index)
    for s in STAGES:
        pred += summary.groupby(f"k_{s}")["error"].transform("mean") - grand
    total = err.var(ddof=0)
    residual = (err - pred).var(ddof=0)
    noise = (err * (1 - err) / n_tasks).mean()
    main_effect_range = {}
    for s in STAGES:
        by_keep = summary.groupby(f"k_{s}")["error"].mean()
        main_effect_range[s] = float(by_keep.max() - by_keep.min())
    return {
        "total_var": total,
        "residual_share": residual / total if total > 0 else math.nan,
        "noise_share": noise / total if total > 0 else math.nan,
        "main_effect_range": main_effect_range,
    }


def pick_report(L: Landscape, search: list[str], held: list[str], picks: dict[str, str], lam: float) -> pd.DataFrame:
    """Held-out error, cost and reward of each named pick, with 95% task-bootstrap CIs of the
    held-out reward difference against the dense network."""
    held_summary = summarize(L, held)
    r_held = reward(held_summary, L.dense_id, lam)
    idx = task_bootstrap_indices(len(held))
    corr = L.correct[held].to_numpy(dtype=float)
    cost = L.cost[held].to_numpy(dtype=float)
    pos = {c: i for i, c in enumerate(L.correct.index)}
    d = pos[L.dense_id]
    out = []
    for name, c in picks.items():
        i = pos[c]
        err_i, err_d = 1 - corr[i][idx].mean(axis=1), 1 - corr[d][idx].mean(axis=1)
        cost_i, cost_d = cost[i][idx].mean(axis=1), cost[d][idx].mean(axis=1)
        diff = (-err_i - lam * np.log2(cost_i / cost_d)) - (-err_d)
        out.append({
            "method": name, "config_id": c, "keep": "-".join(map(str, keep_of(c)[:3])),
            "search_error": summarize(L, search).loc[c, "error"],
            "heldout_error": held_summary.loc[c, "error"],
            "heldout_recon_error": held_summary.loc[c, "recon_error"],
            "heldout_cost_usd": held_summary.loc[c, "cost_usd"],
            "cost_compression": held_summary.loc[c, "cost_compression"],
            "heldout_reward": r_held.loc[c],
            "reward_vs_dense": float(diff.mean()),
            "reward_vs_dense_lo": float(np.percentile(diff, 2.5)),
            "reward_vs_dense_hi": float(np.percentile(diff, 97.5)),
        })
    return pd.DataFrame(out)


def keep_stability(L: Landscape, search: list[str], lam: float, n_boot: int = 500) -> pd.DataFrame:
    """Bootstrap the search tasks and record which config the joint search picks each time:
    per stage, how often each keep value is chosen, and how often the pick is non-uniform (H2)."""
    idx = task_bootstrap_indices(len(search), n_boot=n_boot, seed=1)
    corr = L.correct[search].to_numpy(dtype=float)
    cost = L.cost[search].to_numpy(dtype=float)
    d = list(L.correct.index).index(L.dense_id)
    picks = []
    for b in range(n_boot):
        err = 1 - corr[:, idx[b]].mean(axis=1)
        c = cost[:, idx[b]].mean(axis=1)
        r = -err - lam * np.log2(c / c[d])
        picks.append(L.correct.index[int(np.argmax(r))])
    keeps = pd.DataFrame([keep_of(p)[:3] for p in picks], columns=STAGES)
    out = pd.DataFrame({s: keeps[s].value_counts(normalize=True) for s in STAGES}).fillna(0).sort_index()
    out.index.name = "keep"
    out.attrs["non_uniform_share"] = float((keeps.nunique(axis=1) > 1).mean())
    return out


def random_control(L: Landscape, search: list[str], held: list[str], pick: str, tolerance: float = 0.2) -> dict:
    """H4 random-pruning control: configs whose search-half cost is within +-tolerance of the
    pick's ("matched cost"); their mean held-out error is what pruning at that cost gives
    without search. advantage = random error - pick error (positive: the search helped), with a
    95% bootstrap CI over held-out tasks (per task, the pick's correctness is paired with the
    mean correctness of the matched configs; audit 1, finding 8)."""
    s, h = summarize(L, search), summarize(L, held)
    target = s.loc[pick, "cost_usd"]
    similar = s[((s["cost_usd"] - target).abs() <= tolerance * target) & (s.index != pick)].index
    if len(similar) == 0:
        return {"pick": pick, "n_similar_cost": 0}
    pick_correct = L.correct.loc[pick, held].to_numpy(dtype=float)
    random_correct = L.correct.loc[similar, held].to_numpy(dtype=float).mean(axis=0)
    advantage = paired_bootstrap_diff(pick_correct, random_correct)
    return {"pick": pick, "n_similar_cost": len(similar), "random_heldout_error": float(h.loc[similar, "error"].mean()),
            "pick_heldout_error": float(h.loc[pick, "error"]), "advantage": advantage[0],
            "advantage_lo": advantage[1], "advantage_hi": advantage[2]}


def spearman(a: pd.Series, b: pd.Series) -> float:
    """Rank correlation (Pearson correlation of ranks; ties get average ranks)."""
    return float(np.corrcoef(a.rank(), b.rank())[0, 1])


def answer_classes(answers: list, grader: str) -> list[list[int]]:
    """Group answer positions into classes of equivalent answers under the task's grader
    (each answer joins the first class whose first member it matches). Missing answers
    stay alone, so they never count as agreeing."""
    from autoagentnet.tasks import answers_match

    classes: list[list[int]] = []
    for i, a in enumerate(answers):
        home = None
        if isinstance(a, str):
            for c in classes:
                first = answers[c[0]]
                if isinstance(first, str) and answers_match(first, a, grader):
                    home = c
                    break
        if home is None:
            classes.append([i])
        else:
            home.append(i)
    return classes


def read_agents(agents_csv) -> pd.DataFrame:
    """Per-agent rows of one or more agents.csv files (replicate 0)."""
    paths = agents_csv if isinstance(agents_csv, (list, tuple)) else [agents_csv]
    agents = pd.concat([pd.read_csv(p, dtype={"answer": str}) for p in paths], ignore_index=True)  # "42" stays a string
    if "grader" not in agents.columns:
        agents["grader"] = "exact"
    return agents[agents["replicate"] == 0]


def within_stage_agreement(agents_csv: Path) -> pd.DataFrame:
    """From the dense network's per-agent rows: per stage, the mean share of agent pairs that
    give equivalent answers (under the task's grader), the mean share of agents in the
    largest answer group, and mean agent accuracy.
    Near-1 agreement would make pruning look free for an artificial reason (protocol 4.3)."""
    agents = read_agents(agents_csv)
    rows = []
    for (task, stage), g in agents.groupby(["task_id", "stage"]):
        n = len(g)
        sizes = pd.Series([len(c) for c in answer_classes(list(g["answer"]), g["grader"].iloc[0])])
        pairs = n * (n - 1) / 2
        rows.append({"task_id": task, "stage": stage, "agents": n,
                     "pairwise_agreement": float((sizes * (sizes - 1) / 2).sum() / pairs) if pairs else math.nan,
                     "majority_share": sizes.max() / n, "accuracy": g["correct"].mean()})
    per_task = pd.DataFrame(rows)
    out = per_task.groupby("stage")[["pairwise_agreement", "majority_share", "accuracy"]].mean()
    return out.loc[[s for s in STAGES + ["aggregate"] if s in out.index]]


def vote_correct_by_task(agents_csv, k: int = 6, task_ids: list[str] | None = None) -> pd.Series:
    """Per task: is the majority answer of the first k propose-stage agents right (1.0) or not?
    Answers are grouped by the task's grader; ties go to the earliest agent; no answer at all
    counts as wrong."""
    agents = read_agents(agents_csv)
    if task_ids is not None:
        agents = agents[agents["task_id"].isin(task_ids)]
    prop = agents[agents["stage"] == "propose"].copy()
    prop["index"] = prop["agent_id"].str.split(".").str[1].astype(int)
    prop = prop[prop["index"] < k].sort_values(["task_id", "index"])
    out = {}
    for task, g in prop.groupby("task_id"):
        classes = [c for c in answer_classes(list(g["answer"]), g["grader"].iloc[0]) if isinstance(g["answer"].iloc[c[0]], str)]
        if not classes:
            out[task] = 0.0
            continue
        largest = max(len(c) for c in classes)
        winner = [c for c in classes if len(c) == largest][0]
        out[task] = float(g["correct"].iloc[winner[0]] == 1)
    return pd.Series(out, name=f"vote{k}_correct")


def vote_tiesplit_by_task(agents_csv, k: int = 6, task_ids: list[str] | None = None) -> pd.Series:
    """Per task: the expected correctness of the majority vote over the first k propose answers when
    ties are split evenly (the share of the tied largest classes that are right). Descriptive."""
    agents = read_agents(agents_csv)
    if task_ids is not None:
        agents = agents[agents["task_id"].isin(task_ids)]
    prop = agents[agents["stage"] == "propose"].copy()
    prop["index"] = prop["agent_id"].str.split(".").str[1].astype(int)
    prop = prop[prop["index"] < k].sort_values(["task_id", "index"])
    out = {}
    for task, g in prop.groupby("task_id"):
        classes = [c for c in answer_classes(list(g["answer"]), g["grader"].iloc[0]) if isinstance(g["answer"].iloc[c[0]], str)]
        if not classes:
            out[task] = 0.0
            continue
        largest = max(len(c) for c in classes)
        tied = [c for c in classes if len(c) == largest]
        out[task] = sum(float(g["correct"].iloc[c[0]] == 1) for c in tied) / len(tied)
    return pd.Series(out, name=f"vote{k}_tiesplit")


def propose_vote_baseline(agents_csv, task_ids: list[str] | None = None) -> pd.DataFrame:
    """Self-consistency baseline for free: majority vote over the first k propose-stage answers
    of the dense run (k = 1..6). Cost = those k propose calls."""
    agents = read_agents(agents_csv)
    if task_ids is not None:
        agents = agents[agents["task_id"].isin(task_ids)]
    prop = agents[agents["stage"] == "propose"].copy()
    prop["index"] = prop["agent_id"].str.split(".").str[1].astype(int)
    out = []
    for k in range(1, int(prop["index"].max()) + 2):
        correct = vote_correct_by_task(agents_csv, k, task_ids)
        mean, lo, hi = bootstrap_mean_ci(correct)
        out.append({"k": k, "accuracy": mean, "lo": lo, "hi": hi,
                    "cost_usd": prop[prop["index"] < k].groupby("task_id")["cost_usd"].sum().mean()})
    return pd.DataFrame(out)


def cost_breakdown(L: Landscape, config_ids: dict[str, str], pricing: Path = ROOT / "configs/pricing.yaml",
                   model: str = "claude-haiku-5-5") -> pd.DataFrame:
    """Dollars per task split into input, cache write, cache read and output (figure e)."""
    price = PriceBook.from_yaml(pricing).price(model, "anthropic")
    rates = {"input_tokens": price.input, "cache_write_tokens": price.cache_write or price.input,
             "cache_read_tokens": price.cache_read or price.input, "output_tokens": price.output}
    rows = L.rows
    out = []
    for name, c in config_ids.items():
        r = rows[rows["config_id"] == c]
        out.append({"name": name, "config_id": c, **{k.replace("_tokens", ""): (r[k] * v / 1e6).mean() for k, v in rates.items()}})
    return pd.DataFrame(out).set_index("name")


# ---------- figures ----------

def plot_landscape(s: pd.DataFrame, ci: pd.DataFrame, named: dict[str, str], title: str):
    """Figure (b): every config's error against cost, the Pareto frontier with 95% CIs, and named baselines."""
    plt = style()
    from matplotlib.ticker import FuncFormatter, NullFormatter

    fig, axes = plt.subplots(1, 2, figsize=(8.0, 3.4), sharey=True)
    for ax, (col, label) in zip(axes, [("cost_usd", "cost per task (USD, cache-aware list price)"), ("tokens", "tokens per task")]):
        ax.scatter(s[col], 100 * s["error"], s=8, color="0.6", label=f"{len(s)} configs", zorder=1)
        front = pareto_front(s, col)
        f_ci = ci.loc[front.index]
        ax.errorbar(front[col], 100 * front["error"], yerr=[100 * (front["error"] - f_ci["error_lo"]), 100 * (f_ci["error_hi"] - front["error"])],
                    fmt="-o", ms=3, color=color(0), capsize=2, lw=1, label="Pareto frontier (95% CI)", zorder=2)
        for i, (name, c) in enumerate(named.items()):
            if c in s.index:
                ax.scatter(s.loc[c, col], 100 * s.loc[c, "error"], marker="D", s=30, color=color(i + 1), label=name, zorder=3)
        ax.set_xscale("log")
        ax.xaxis.set_minor_formatter(NullFormatter())
        dollars = col == "cost_usd"
        ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _, dollars=dollars: f"\\${v:g}" if dollars else f"{v:,.0f}"))
        ax.set_xlabel(label)
    axes[0].set_ylabel("error (%)")
    handles, labels = axes[0].get_legend_handles_labels()
    fig.legend(handles, labels, fontsize=7, loc="upper center", ncol=4, frameon=False, bbox_to_anchor=(0.5, -0.02))
    fig.suptitle(title, fontsize=9)
    return fig


def plot_interactions(s: pd.DataFrame, title: str):
    """Figure (c): mean error for each pair of stages' keeps, averaged over the third stage."""
    plt = style()
    fig, axes = plt.subplots(1, 3, figsize=(9.0, 2.9))
    pairs = [("propose", "critique"), ("propose", "refine"), ("critique", "refine")]
    vmin, vmax = 100 * s["error"].min(), 100 * s["error"].max()
    for ax, (a, b) in zip(axes, pairs):
        grid = 100 * s.pivot_table(index=f"k_{a}", columns=f"k_{b}", values="error", aggfunc="mean")
        im = ax.imshow(grid.to_numpy(), origin="lower", cmap="viridis", vmin=vmin, vmax=vmax, aspect="auto")
        ax.set_xticks(range(grid.shape[1]), grid.columns)
        ax.set_yticks(range(grid.shape[0]), grid.index)
        ax.set_xlabel(f"agents kept: {b}")
        ax.set_ylabel(f"agents kept: {a}")
        ax.grid(False)
    fig.colorbar(im, ax=axes, label="mean error (%)", shrink=0.9)
    fig.suptitle(title, fontsize=9)
    return fig


def plot_cost_breakdown(table: pd.DataFrame, title: str):
    """Figure (e): stacked dollars per task by token type."""
    plt = style()
    fig, ax = plt.subplots(figsize=(5.0, 3.0))
    left = np.zeros(len(table))
    for i, col in enumerate(["input", "cache_write", "cache_read", "output"]):
        ax.barh(table.index, 1000 * table[col], left=left, color=color(i), label=col.replace("_", " "))
        left += 1000 * table[col].to_numpy()
    ax.set_xlabel("cost per task (USD x 1000)")
    ax.legend(fontsize=7)
    ax.set_title(title, fontsize=9)
    return fig


def baseline_controls(L: Landscape, held: list[str], single_results: list[Path], agents_csvs: list[Path]) -> pd.DataFrame:
    """Held-out error and cost of the non-pruning baselines (audit 1, finding 8): the single agent
    (from the gate runs on the same tasks) and a majority vote over the dense run's 6 propose
    answers (cost: those 6 calls). Each is compared with the dense network on the same tasks."""
    rows = []
    dense_correct = L.correct.loc[L.dense_id, held]
    singles = [p for p in single_results if Path(p).exists()]
    if singles:
        single = pd.concat([pd.read_csv(p) for p in singles])
        single = single[(single["replicate"] == 0) & single["task_id"].isin(held)].drop_duplicates("task_id").set_index("task_id")
        common = single.index
        if len(common):
            diff = paired_bootstrap_diff(single.loc[common, "correct"], dense_correct.loc[common])
            rows.append({"baseline": "single agent", "n": len(common), "heldout_error": 1 - single["correct"].mean(),
                         "cost_usd": single["cost_usd"].mean(), "minus_dense_acc": diff[0], "lo": diff[1], "hi": diff[2]})
    agents = [p for p in agents_csvs if Path(p).exists()]
    if agents:
        vote = propose_vote_baseline(agents, task_ids=held)
        six = vote.iloc[-1]
        rows.append({"baseline": f"vote over {int(six['k'])} propose answers", "n": len(held),
                     "heldout_error": 1 - six["accuracy"], "cost_usd": six["cost_usd"]})
    return pd.DataFrame(rows)


def main(search_folders: list[str], held_folders: list[str] | None = None, lam: float = 0.05,
         single_results: list[str] | None = None) -> dict:
    """search_folders: runs whose tasks are the search half; held_folders: runs whose tasks
    are held out (empty: picks are scored on the search tasks, i.e. with the winner's curse).
    single_results: gate runs of the single agent covering the same tasks (for the controls).

    Caveat on recon_error (audit 1, finding 8): a pruned config reuses the dense run's cached
    upstream calls, so its answers share randomness with the dense answers and agreement is
    higher than between independent samples. The label-free reward is therefore optimistic."""
    from .search import regret_curves, plot_regret

    held_folders = held_folders or []
    paths = [Path(f) for f in search_folders + held_folders]
    L = load_landscape(paths)
    first = pd.concat([pd.read_csv(Path(f) / "results.csv") for f in search_folders])["task_id"].unique().tolist()
    search = [t for t in L.tasks if t in first]
    held = [t for t in L.tasks if t not in first] or search
    s_all, s_search = summarize(L, None), summarize(L, search)
    r_search, r_free = reward(s_search, L.dense_id, lam), reward(s_search, L.dense_id, lam, label_free=True)

    sens, sens_evals = sensitivity_pick(s_search, r_search)
    uniform = uniform_ids(s_search)
    picks = {
        "dense": L.dense_id,
        "joint (exhaustive, labeled)": r_search.idxmax(),
        "joint (exhaustive, label-free)": r_free.idxmax(),
        "stage-by-stage sensitivity": sens,
        "best uniform": r_search.loc[uniform].idxmax(),
        "budgeted, <= 50% of dense cost": budgeted_pick(s_search, L.dense_id, 0.5),
        "budgeted, <= 25% of dense cost": budgeted_pick(s_search, L.dense_id, 0.25),
        "smallest (1-1-1-1)": s_search["agents"].idxmin(),
    }
    report = pick_report(L, search, held, picks, lam)
    save_table(report.round(4), "p4_picks")
    stab = keep_stability(L, search, lam)
    save_table(stab.round(3), "p4_keep_stability", index=True)
    inter = interaction(s_all, len(L.tasks))
    controls = pd.DataFrame([random_control(L, search, held, picks[k]) | {"method": k} for k in
                             ["joint (exhaustive, labeled)", "joint (exhaustive, label-free)", "stage-by-stage sensitivity",
                              "best uniform", "budgeted, <= 50% of dense cost"]])
    save_table(controls.round(4), "p4_random_control")
    agents_csvs = [p / "agents.csv" for p in paths]
    baselines = baseline_controls(L, held, [Path(p) for p in single_results or []], agents_csvs)
    if not baselines.empty:
        save_table(baselines.round(4), "p4_baselines")
    save_table(s_all.round(5), "p4_landscape_all", index=True)
    ci = error_ci(L, s_all.index, L.tasks)
    named = {k: v for k, v in picks.items() if k in ("dense", "joint (exhaustive, labeled)", "joint (exhaustive, label-free)",
                                                     "stage-by-stage sensitivity", "best uniform")}
    save_figure(plot_landscape(s_all, ci, named, f"P4 landscape, {len(L.tasks)} tasks"), "b_landscape")
    save_figure(plot_interactions(s_all, "P4 stage interactions: mean error by pair of stages"), "c_interactions")
    save_figure(plot_cost_breakdown(cost_breakdown(L, named), "Cost per task by token type"), "e_cost_breakdown")
    curves = regret_curves(L, search, held, lam)
    save_table(curves.round(5), "p4_regret")
    save_figure(plot_regret(curves, "Regret vs evaluations (picks scored on held-out tasks)"), "d_regret")
    existing = [p for p in agents_csvs if p.exists()]
    agreement = within_stage_agreement(existing) if existing else pd.DataFrame()  # all parts, not part a only
    if not agreement.empty:
        save_table(agreement.round(3), "p4_within_stage_agreement", index=True)
    summary = {
        "n_tasks": len(L.tasks), "n_search": len(search), "n_held": len(held), "n_configs": len(L.configs),
        "interaction": inter, "non_uniform_share": stab.attrs["non_uniform_share"],
        "spearman_error_recon": spearman(s_all["error"], s_all["recon_error"]),
        "sensitivity_evaluations": len(sens_evals),
    }
    print(report.round(3).to_string(index=False))
    print(summary)
    return summary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--search", nargs="+", required=True)
    parser.add_argument("--held", nargs="*", default=[])
    parser.add_argument("--lam", type=float, default=0.05)
    parser.add_argument("--single", nargs="*", default=[], help="single-agent results.csv covering the same tasks")
    a = parser.parse_args()
    main(a.search, a.held, a.lam, a.single)
