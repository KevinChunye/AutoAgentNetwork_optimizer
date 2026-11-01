"""Economic analysis of a landscape: where the network's value comes from, per dollar.

Works on any grid of keep configs (the full 216, or a factorial grid such as levels
1, 3, 6) plus the dense run's per-agent rows (agents.csv). Everything is offline: it
reuses calls already paid for.

Terms:
  error correlation rho   how often two agents of a stage are right or wrong on the same
                          tasks (Pearson correlation of their 0/1 correctness across tasks).
  effective team size     n_eff = n / (1 + (n - 1) * rho): the number of fully independent
                          agents a stage of n correlated agents is worth (Kish's design
                          effect). rho near 1 means paying for n agents and getting ~1 vote.
  production function     accuracy as a function of agents per stage, fitted as
                          correct = task effect + sum_s b_s * log2(k_s)
                                    + sum_{s<s'} g_ss' * (log2 k_s - mean)(log2 k_s' - mean)
                          b_s: accuracy points gained per doubling of stage s's agents
                          (diminishing returns are built in by the log);
                          g_ss' > 0: stages s and s' are complements (adding to one raises the
                          other's return), g_ss' < 0: substitutes.
  marginal cost           dollars per task added per doubling of stage s's agents, from the
                          same fit on cost.
  value per dollar        b_s / marginal cost_s. The equimarginal rule of economics says a
                          budget is best spent when this is equal across stages, so the stage
                          with the highest value per dollar should grow first.
  consensus policy        "management by exception": run the first m proposers; if their
                          plurality share is at least theta, answer with it and stop; otherwise
                          run a fallback config. Its accuracy and cost per task follow exactly
                          from calls already in the landscape, because the first m proposers
                          are the same calls every config makes.

Usage: python -m analysis.economics --search results/x_a results/x_b --held results/x_c results/x_d
"""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pandas as pd

from .common import N_BOOT, SEED, bootstrap_mean_ci, color, save_figure, save_table, style
from .landscape import STAGES, Landscape, answer_classes, load_landscape, pareto_front, read_agents, summarize

MS = (2, 3, 4, 6)  # proposers a consensus policy runs first
THETAS = (0.0, 1 / 2, 2 / 3, 5 / 6, 1.0)  # agreement thresholds: always exit, half, two thirds, 5 of 6, unanimous


def effective_team_size(agents: pd.DataFrame) -> pd.DataFrame:
    """Per stage of the dense run: agents, mean accuracy, mean pairwise error correlation, n_eff."""
    rows = []
    for stage, g in agents.groupby("stage"):
        wide = g.pivot_table(index="task_id", columns="agent_id", values="correct")
        n = wide.shape[1]
        varying = wide.loc[:, wide.std() > 0]
        corr = varying.corr().to_numpy()
        pairs = corr[np.triu_indices_from(corr, k=1)] if varying.shape[1] > 1 else np.array([])
        rho = float(np.nanmean(pairs)) if len(pairs) else math.nan
        n_eff = n / (1 + (n - 1) * rho) if not math.isnan(rho) else math.nan
        rows.append({"stage": stage, "agents": n, "accuracy": float(wide.to_numpy().mean()),
                     "error_correlation": rho, "effective_team_size": n_eff})
    out = pd.DataFrame(rows).set_index("stage")
    return out.loc[[s for s in STAGES + ["aggregate"] if s in out.index]]


def _design(configs: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Columns: log2(k) per prunable stage, then centred pairwise products."""
    logs = np.log2(configs[[f"k_{s}" for s in STAGES]].to_numpy(dtype=float))
    centred = logs - logs.mean(axis=0)
    names = [f"doubling {s}" for s in STAGES]
    columns = [logs[:, i] for i in range(len(STAGES))]
    for i, j in itertools.combinations(range(len(STAGES)), 2):
        columns.append(centred[:, i] * centred[:, j])
        names.append(f"{STAGES[i]} x {STAGES[j]}")
    return np.column_stack(columns), names


def _fit(y: np.ndarray, X: np.ndarray) -> np.ndarray:
    """OLS with task fixed effects: y is configs x tasks; every task has every config,
    so demeaning y within each task and X across configs removes the task effects."""
    yc = y - y.mean(axis=0, keepdims=True)
    Xc = X - X.mean(axis=0, keepdims=True)
    stacked_y = yc.T.reshape(-1)
    stacked_X = np.tile(Xc, (y.shape[1], 1))
    return np.linalg.lstsq(stacked_X, stacked_y, rcond=None)[0]


def production_function(L: Landscape, tasks: list[str] | None = None, n_boot: int = N_BOOT) -> pd.DataFrame:
    """Fitted accuracy and cost effects per stage and per pair of stages, with 95% task-bootstrap CIs."""
    tasks = tasks or L.tasks
    configs = L.configs[(L.configs[[f"k_{s}" for s in STAGES]] > 0).all(axis=1)]
    X, names = _design(configs)
    correct = L.correct.loc[configs.index, tasks].to_numpy(dtype=float)
    cost = L.cost.loc[configs.index, tasks].to_numpy(dtype=float)
    acc_hat = _fit(correct, X) * 100
    cost_hat = _fit(cost, X)
    rng = np.random.default_rng(SEED)
    boots = np.array([_fit(correct[:, rng.integers(0, len(tasks), len(tasks))], X) * 100 for _ in range(n_boot)])
    out = pd.DataFrame({
        "term": names,
        "accuracy_points": acc_hat,
        "lo": np.percentile(boots, 2.5, axis=0),
        "hi": np.percentile(boots, 97.5, axis=0),
        "cost_usd_per_task": cost_hat,
    })
    main = out["term"].str.startswith("doubling")
    out.loc[main, "points_per_cent"] = out.loc[main, "accuracy_points"] / (out.loc[main, "cost_usd_per_task"] * 100)
    out.loc[~main, "reading"] = np.where(out.loc[~main, "lo"] > 0, "complements",
                                         np.where(out.loc[~main, "hi"] < 0, "substitutes", "not resolved"))
    return out


def equimarginal_path(summary: pd.DataFrame) -> pd.DataFrame:
    """Grow from the smallest config: at each step move one stage to its next evaluated
    level, choosing the move with the most accuracy gained per extra dollar. The path is
    the economist's allocation rule; score its configs on held-out tasks like any pick."""
    keep_cols = [f"k_{s}" for s in STAGES]
    levels = {c: sorted(summary[c].unique()) for c in keep_cols}
    by_keep = summary.rename_axis("config_id").reset_index().set_index(keep_cols)
    current = tuple(levels[c][0] for c in keep_cols)
    path = []
    while True:
        row = by_keep.loc[current]
        path.append({"config_id": row["config_id"], "cost_usd": row["cost_usd"], "error": row["error"]})
        moves = []
        for i, c in enumerate(keep_cols):
            higher = [v for v in levels[c] if v > current[i]]
            if higher:
                nxt = list(current)
                nxt[i] = higher[0]
                if tuple(nxt) in by_keep.index:
                    cand = by_keep.loc[tuple(nxt)]
                    extra = cand["cost_usd"] - row["cost_usd"]
                    gain = row["error"] - cand["error"]
                    moves.append((gain / extra if extra > 0 else -math.inf, tuple(nxt)))
        if not moves:
            return pd.DataFrame(path)
        best_value, best = max(moves)
        if best_value <= 0:
            return pd.DataFrame(path)
        current = best


def proposer_exits(agents: pd.DataFrame, m: int, tasks: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    """What the first m proposers of the dense run say on each task: the share of the largest
    group of equivalent answers (plurality share), whether that answer is correct, and the cost
    of the m calls. Also returns each proposer's cost per task (columns: proposer index)."""
    prop = agents[(agents["stage"] == "propose") & agents["task_id"].isin(tasks)].copy()
    prop["index"] = prop["agent_id"].str.split(".").str[1].astype(int)
    prop = prop.sort_values(["task_id", "index"])
    rows = []
    for task, g in prop[prop["index"] < m].groupby("task_id"):
        answers = [a if isinstance(a, str) else None for a in g["answer"]]
        groups = [c for c in answer_classes(answers, g["grader"].iloc[0]) if answers[c[0]] is not None]
        largest = max((len(c) for c in groups), default=0)
        winner = next((c for c in groups if len(c) == largest), None)
        rows.append({"task_id": task, "share": largest / len(answers),
                     "exit_correct": float(g["correct"].iloc[winner[0]] == 1) if winner else 0.0,
                     "exit_cost": g["cost_usd"].sum()})
    per_agent = prop.pivot_table(index="task_id", columns="index", values="cost_usd", aggfunc="sum")
    return pd.DataFrame(rows).set_index("task_id"), per_agent


def policy_outcomes(L: Landscape, exits: pd.DataFrame, per_agent: pd.DataFrame, m: int, theta: float,
                    fallback: str, tasks: list[str]) -> pd.DataFrame:
    """Per task, the consensus policy (m, theta, fallback): exit with the plurality answer when its
    share is at least theta, else run the fallback config. The fallback reuses its own first
    k_propose proposers, so only the policy's proposers beyond those are an extra cost."""
    k1 = int(L.configs.loc[fallback, "k_propose"])
    e = exits.loc[tasks]
    exited = e["share"] >= theta - 1e-9  # shares are fractions such as 4/6; compare with a tolerance
    extra = per_agent.loc[tasks, [i for i in per_agent.columns if k1 <= i < m]].sum(axis=1)
    return pd.DataFrame({
        "correct": np.where(exited, e["exit_correct"], L.correct.loc[fallback, tasks]),
        "cost_usd": np.where(exited, e["exit_cost"], L.cost.loc[fallback, tasks] + extra),
        "exited": exited.astype(float),
    }, index=tasks)


def distinct_policies(ms=MS, thetas=THETAS) -> list[tuple[int, float]]:
    """(m, theta) pairs that behave differently. With m proposers the plurality share is a multiple
    of 1/m, so two thetas that need the same number of agreeing agents, ceil(theta x m), are one
    policy (for m=2, theta 2/3, 5/6 and 1 all mean "both agree"); the smallest theta is kept."""
    pairs, seen = [], []
    for m, theta in itertools.product(ms, thetas):
        need = math.ceil(theta * m - 1e-9)
        if (m, need) not in seen:
            seen.append((m, need))
            pairs.append((m, theta))
    return pairs


def consensus_policies(L: Landscape, agents: pd.DataFrame, fallbacks: dict[str, str],
                       ms=MS, thetas=THETAS, tasks: list[str] | None = None) -> pd.DataFrame:
    """Accuracy, cost and exit rate of every distinct (m, theta, fallback) consensus policy, offline.
    theta 0 always exits, so "m=6, theta=0.00" is the free vote over six proposers (vote6);
    "m=6, theta=0.83, else dense" is gated_3x6 (5 of 6 agree)."""
    tasks = tasks or L.tasks
    rows = []
    for m in ms:
        exits, per_agent = proposer_exits(agents, m, tasks)
        for theta, (name, fallback) in itertools.product([t for mm, t in distinct_policies((m,), thetas)], fallbacks.items()):
            out = policy_outcomes(L, exits, per_agent, m, theta, fallback, tasks)
            acc, lo, hi = bootstrap_mean_ci(out["correct"])
            rows.append({"policy": f"m={m}, theta={theta:.2f}, else {name}", "m": m, "theta": theta,
                         "min_agree": math.ceil(theta * m - 1e-9),
                         "fallback": fallback, "error": 1 - acc, "error_lo": 1 - hi, "error_hi": 1 - lo,
                         "cost_usd": float(out["cost_usd"].mean()), "exit_rate": float(out["exited"].mean())})
    return pd.DataFrame(rows).sort_values("cost_usd")


def plot_policies(static: pd.DataFrame, policies: pd.DataFrame, title: str):
    """Static configs (grey), their Pareto front, and consensus policies (colour by m)."""
    plt = style()
    fig, ax = plt.subplots()
    ax.scatter(static["cost_usd"] * 100, static["error"] * 100, s=8, color="#999999", label="static configs")
    front = pareto_front(static)
    ax.plot(front["cost_usd"] * 100, front["error"] * 100, color="#555555", lw=1, label="static Pareto front")
    for i, (m, g) in enumerate(policies.groupby("m")):
        ax.scatter(g["cost_usd"] * 100, g["error"] * 100, s=18, color=color(i), label=f"consensus policy, m={m}")
    ax.set_xlabel("cost per task (US cents)")
    ax.set_ylabel("error (%)")
    ax.set_title(title)
    ax.legend(fontsize=7)
    return fig


def plot_production(production: pd.DataFrame, title: str):
    """Figure (i): the production function. Left: accuracy points per doubling of each stage and
    the stage-pair interaction terms, with 95% task-bootstrap CIs. Right: value per dollar of each
    stage (accuracy points per US cent per task), the equimarginal comparison."""
    plt = style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.4, 3.0), gridspec_kw={"width_ratios": [3, 2]})
    y = np.arange(len(production))[::-1]
    main = production["term"].str.startswith("doubling").to_numpy()
    for i, (_, row) in enumerate(production.iterrows()):
        c = color(0) if main[i] else color(3)
        ax1.errorbar(row["accuracy_points"], y[i], xerr=[[row["accuracy_points"] - row["lo"]], [row["hi"] - row["accuracy_points"]]],
                     fmt="o", color=c, capsize=3)
    ax1.axvline(0, color="0.4", lw=0.8)
    ax1.set_yticks(y, production["term"])
    ax1.set_xlabel("accuracy points (per doubling; interactions centred)")
    effects = production[main]
    ax2.barh(effects["term"].str.replace("doubling ", ""), effects["points_per_cent"], color=color(0))
    ax2.axvline(0, color="0.4", lw=0.8)
    ax2.set_xlabel("accuracy points per US cent per task")
    fig.suptitle(title, fontsize=9)
    return fig


def main(search_folders: list[str], held_folders: list[str] | None = None) -> dict:
    """Production function on all tasks (rule 65); the equimarginal path is built on the search half and,
    with the consensus policies, reported on the held-out half."""
    held_folders = held_folders or []
    paths = [Path(f) for f in search_folders + held_folders]
    L = load_landscape(paths)
    first = pd.concat([pd.read_csv(Path(f) / "results.csv") for f in search_folders])["task_id"].unique().tolist()
    search = [t for t in L.tasks if t in first]
    held = [t for t in L.tasks if t not in first] or search
    agents = pd.concat([read_agents(p / "agents.csv") for p in paths if (p / "agents.csv").exists()])

    team = effective_team_size(agents)
    save_table(team.round(3), "econ_effective_team_size", index=True)
    # The production function is not a selection, so it is fit on every task (plan rule 65, written
    # before the held-out parts ran); the search-half fit is kept beside it.
    production = production_function(L, L.tasks)
    save_table(production.round(4), "econ_production_function")
    save_table(production_function(L, search).round(4), "econ_production_function_search")
    save_figure(plot_production(production, f"Production function, all {len(L.tasks)} tasks (95% CIs)"),
                "i_production_function")
    path = equimarginal_path(summarize(L, search))
    held_summary = summarize(L, held)
    path = path.assign(held_error=held_summary.loc[path["config_id"], "error"].to_numpy(),
                       held_cost_usd=held_summary.loc[path["config_id"], "cost_usd"].to_numpy())
    save_table(path.round(5), "econ_equimarginal_path")
    fallbacks = {"dense": L.dense_id, "cheapest": held_summary["cost_usd"].idxmin()}
    policies = consensus_policies(L, agents, fallbacks, tasks=held)
    save_table(policies.round(5), "econ_consensus_policies")
    save_figure(plot_policies(held_summary, policies, f"Consensus policies vs static configs, {len(held)} held-out tasks"),
                "h_consensus_policies")
    print(team.round(3).to_string())
    print(production.round(3).to_string(index=False))
    return {"team": team, "production": production, "path": path, "policies": policies}


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--search", nargs="+", required=True)
    parser.add_argument("--held", nargs="*", default=[])
    a = parser.parse_args()
    main(a.search, a.held)
