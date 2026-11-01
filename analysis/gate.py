"""Gate analysis (P2 probes, P3 confirm): does the dense network beat a single agent?

Inputs: pairs of experiments run on the same tasks, named `<step>_<candidate>_single`
and `<step>_<candidate>_dense` (results/<name>/results.csv). Only the dense config of
each experiment and replicate 0 are used.

Columns of the gate table:
  n                 tasks answered by both systems
  single_acc        share of tasks the single agent answers correctly (95% bootstrap CI)
  dense_acc         same for the dense network
  gap               dense_acc - single_acc, paired over tasks, in accuracy points (0-1 scale)
  dense_only_right  tasks the dense network gets right and the single agent gets wrong
  single_only_right the reverse; the gap is (dense_only_right - single_only_right) / n
  *_cost_per_task   dollars per task, cache-aware, list price
  passes            single_acc in [0.30, 0.60] and gap >= 0.05 (protocol section 5)
  futile            the upper end of the gap's 95% CI is below +0.05: the v2 futility rule
                    (plan, amendment 3, rule 19) stops P3 when this holds on validation 20-39
  sonnet_acc        the matched-cost senior control (one Sonnet call per task), when its P3 run
                    exists; dense_minus_sonnet is paired over the same items with a 95% CI
  propose_mean_acc  mean accuracy of the dense run's 6 propose-stage agents (from agents.csv)
  vote6_acc         accuracy of a majority vote over those 6 answers (ties: earliest agent)
  vote6_tiesplit_acc  the same vote with ties split evenly: a tie among k classes counts as right
                    with probability (right classes among them) / k (descriptive; audit 15)
  pass6             share of tasks where at least one of the 6 is right (the ceiling for any aggregation)
  vote_gain         vote6_acc - propose_mean_acc; under ~0.03 means voting adds little and the
                    critique/refine stages would have to supply the gap alone (plan, P2b)
  dense_minus_vote6 dense_acc - vote6_acc, paired over tasks, with a 95% bootstrap CI; P4 runs only
                    if this is at least 0.05 on the judged items (plan, amendment 2)

Judged items (audit 1, finding 4): P2 on calibration positions 0-19; P3 on the fresh
validation positions 20-59 only (P3 runs 0-59, but 0-19 picked the candidate); when the
gate-widening runs `p3w_*` (positions 100-119) exist, P3 is judged on 20-59 and 100-119. Positions are
read from the task file named in configs/experiments/pilot/<step>_<candidate>_dense.yaml.

Usage: python -m analysis.gate p2   (or p3)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import yaml

from autoagentnet.tasks import load_tasks

from .common import ROOT, bootstrap_mean_ci, color, paired_bootstrap_diff, save_figure, save_table, style

SINGLE_RANGE = (0.30, 0.60)
MIN_GAP = 0.05
# Item positions the gate is judged on. P3w is limited to validation 100-119 so that the P4
# held-out half (60-99) stays clean (audit 3, finding 2; plan amendment 3, rule 12).
JUDGED_POSITIONS = {"p2": [(0, 20)], "p3": [(20, 60)], "p3w": [(20, 60), (100, 120)]}
CONFIGS = ROOT / "configs/experiments/pilot"


def as_list(paths) -> list[Path]:
    return [Path(p) for p in paths] if isinstance(paths, (list, tuple)) else [Path(paths)]


def slices(results_csv: Path) -> list[Path]:
    """One run's results plus its later slices: results/<name>/results.csv, then <name>_b, <name>_c, ...
    A run split with --task-offset/--task-limit writes each slice to its own directory, because a
    run overwrites results.csv with the slice it ran (audit 15)."""
    results_csv = Path(results_csv)
    found, run = [results_csv], results_csv.parent
    for letter in "bcdefgh":
        part = run.parent / f"{run.name}_{letter}" / "results.csv"
        if not part.exists():
            break
        found.append(part)
    return found


def load_dense_rows(results_csv) -> pd.DataFrame:
    """Rows of the dense (largest) config, replicate 0, one per task (several result files are stacked)."""
    rows = pd.concat([pd.read_csv(p) for p in as_list(results_csv)], ignore_index=True)
    rows = rows[rows["replicate"] == 0]
    dense_id = rows.sort_values("agents", ascending=False)["config_id"].iloc[0]
    return rows[rows["config_id"] == dense_id].drop_duplicates("task_id").set_index("task_id")


def judged_task_ids(candidate: str, step: str, judged: str, configs_dir: Path = CONFIGS) -> list[str]:
    """IDs at the positions the gate is judged on, from the step's task file."""
    config = configs_dir / f"{step}_{candidate}_dense.yaml"
    if not config.exists():  # never fall back silently to all items (audit 2, finding 6)
        raise FileNotFoundError(f"{config} not found: cannot tell which items the {step} gate is judged on")
    tasks = load_tasks(ROOT / yaml.safe_load(config.read_text())["tasks"])
    return [t.id for lo, hi in JUDGED_POSITIONS[judged] for t in tasks[lo:hi]]


def judged_label(judged: str) -> str:
    return ",".join(f"{lo}-{hi - 1}" for lo, hi in JUDGED_POSITIONS[judged])


def find_pairs(step: str, results_dir: Path = ROOT / "results") -> list[tuple[str, Path, Path]]:
    """(candidate, single results.csv, dense results.csv) for every complete pair of a step."""
    pairs = []
    for single in sorted(results_dir.glob(f"{step}_*_single/results.csv")):
        candidate = single.parent.name[len(step) + 1 : -len("_single")]
        dense = results_dir / f"{step}_{candidate}_dense" / "results.csv"
        if dense.exists():
            pairs.append((candidate, single, dense))
    return pairs


def voting_check(agents_csv, task_ids, dense_correct: pd.Series | None = None) -> dict:
    """Free self-consistency numbers from the dense run's propose stage. With the dense network's
    per-task correctness, also dense minus the 6-answer vote, paired over tasks with a 95%
    bootstrap CI: the P4 go/no-go (plan, amendment 2)."""
    from .landscape import read_agents, vote_correct_by_task

    agents_csv = [p for p in as_list(agents_csv) if p.exists()]
    if not agents_csv:
        return {}
    agents = read_agents(agents_csv)
    prop = agents[(agents["stage"] == "propose") & agents["task_id"].isin(task_ids)]
    vote = vote_correct_by_task(agents_csv, 6, list(task_ids))
    from .landscape import vote_tiesplit_by_task

    out = {"propose_mean_acc": prop["correct"].mean(), "vote6_acc": vote.mean(),
           "vote6_tiesplit_acc": vote_tiesplit_by_task(agents_csv, 6, list(task_ids)).mean(),
           "pass6": prop.groupby("task_id")["correct"].max().mean()}
    out["vote_gain"] = out["vote6_acc"] - out["propose_mean_acc"]
    if dense_correct is not None:
        both = vote.index.intersection(dense_correct.index)
        diff = paired_bootstrap_diff(dense_correct.loc[both], vote.loc[both])
        out.update(dense_minus_vote6=diff[0], dense_minus_vote6_lo=diff[1], dense_minus_vote6_hi=diff[2])
    return out


def senior_control(senior_csv: Path, dense_csv, task_ids) -> dict:
    """Single Sonnet against dense on the judged items both answered (plan, amendment 3, rule 18)."""
    senior, dense = load_dense_rows(senior_csv), load_dense_rows(dense_csv)
    both = senior.index.intersection(dense.index).intersection(pd.Index(task_ids))
    acc = bootstrap_mean_ci(senior.loc[both, "correct"])
    diff = paired_bootstrap_diff(dense.loc[both, "correct"], senior.loc[both, "correct"])
    return {"sonnet_n": len(both), "sonnet_acc": acc[0], "sonnet_lo": acc[1], "sonnet_hi": acc[2],
            "dense_minus_sonnet": diff[0], "dense_minus_sonnet_lo": diff[1], "dense_minus_sonnet_hi": diff[2],
            "sonnet_cost_per_task": senior.loc[both, "cost_usd"].mean()}


def gate_row(candidate: str, single_csv: Path, dense_csv: Path, task_ids: list[str] | None = None) -> dict:
    single, dense = load_dense_rows(single_csv), load_dense_rows(dense_csv)
    common = single.index.intersection(dense.index)
    if task_ids is not None:
        common = common.intersection(pd.Index(task_ids))
    s, d = single.loc[common, "correct"], dense.loc[common, "correct"]
    s_acc, d_acc, gap = bootstrap_mean_ci(s), bootstrap_mean_ci(d), paired_bootstrap_diff(d, s)
    return {
        "candidate": candidate,
        "n": len(common),
        "single_acc": s_acc[0], "single_lo": s_acc[1], "single_hi": s_acc[2],
        "dense_acc": d_acc[0], "dense_lo": d_acc[1], "dense_hi": d_acc[2],
        "gap": gap[0], "gap_lo": gap[1], "gap_hi": gap[2],
        "dense_only_right": int(((d == 1) & (s == 0)).sum()),
        "single_only_right": int(((d == 0) & (s == 1)).sum()),
        "single_unparsed": 1 - single.loc[common, "parsed"].mean(),
        "dense_unparsed": 1 - dense.loc[common, "parsed"].mean(),
        "single_truncation": single.loc[common, "truncated_calls"].sum() / single.loc[common, "calls"].sum(),
        "dense_truncation": dense.loc[common, "truncated_calls"].sum() / dense.loc[common, "calls"].sum(),
        "single_cost_per_task": single.loc[common, "cost_usd"].mean(),
        "dense_cost_per_task": dense.loc[common, "cost_usd"].mean(),
        "passes": bool(SINGLE_RANGE[0] <= s_acc[0] <= SINGLE_RANGE[1] and gap[0] >= MIN_GAP),
        "futile": bool(gap[2] < MIN_GAP),
        **voting_check([p.parent / "agents.csv" for p in as_list(dense_csv)], common, d),
    }


def gate_table(pairs: list[tuple[str, Path, Path]], task_ids: list[str] | None = None) -> pd.DataFrame:
    return pd.DataFrame([gate_row(c, s, d, task_ids) for c, s, d in pairs])


def plot_gate(table: pd.DataFrame, title: str):
    """Figure (a): single vs dense accuracy per candidate (left) and the paired gap (right), 95% CIs."""
    plt = style()
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(7.0, 3.0), gridspec_kw={"width_ratios": [2, 1]})
    y = range(len(table))
    for i, (system, label) in enumerate([("single", "single agent"), ("dense", "dense 3x6+1")]):
        acc, lo, hi = table[f"{system}_acc"], table[f"{system}_lo"], table[f"{system}_hi"]
        ax1.errorbar(100 * acc, [v + (0.15 if i else -0.15) for v in y],
                     xerr=[100 * (acc - lo), 100 * (hi - acc)], fmt="o", color=color(i), label=label, capsize=3)
    ax1.axvspan(100 * SINGLE_RANGE[0], 100 * SINGLE_RANGE[1], color="0.85", zorder=0, label="target single range")
    ax1.set_yticks(list(y), [f"{c} (n={n})" for c, n in zip(table["candidate"], table["n"])])
    ax1.set_xlabel("accuracy (%)")
    ax1.set_xlim(0, 100)
    ax1.legend(fontsize=7, loc="lower right")
    ax2.errorbar(100 * table["gap"], list(y), xerr=[100 * (table["gap"] - table["gap_lo"]), 100 * (table["gap_hi"] - table["gap"])],
                 fmt="s", color=color(2), capsize=3)
    ax2.axvline(100 * MIN_GAP, color=color(3), ls="--", lw=1, label="gate: +5 points")
    ax2.axvline(0, color="0.4", lw=0.8)
    ax2.set_yticks(list(y), [""] * len(table))
    ax2.set_xlabel("dense - single (points)")
    ax2.legend(fontsize=7)
    fig.suptitle(title, fontsize=9)
    return fig


def by_source(candidate: str, step: str, singles, denses, ids, configs_dir: Path = CONFIGS) -> pd.DataFrame:
    """Contamination probe (plan, amendment 1, rule 9): accuracy of each system on HMMT items
    (public, answers online) and on the rest. Empty for task sets without a `source` field."""
    config = configs_dir / f"{step}_{candidate}_dense.yaml"
    if not config.exists() or ids is None:
        return pd.DataFrame()
    source = {t.id: t.meta.get("source") for t in load_tasks(ROOT / yaml.safe_load(config.read_text())["tasks"])}
    if not any(source.values()):
        return pd.DataFrame()
    single, dense = load_dense_rows(singles), load_dense_rows(denses)
    common = single.index.intersection(dense.index).intersection(pd.Index(ids))
    group = pd.Series({t: "HMMT" if str(source.get(t, "")).startswith("HMMT") else "other" for t in common})
    table = pd.DataFrame({"group": group, "single": single.loc[common, "correct"], "dense": dense.loc[common, "correct"]})
    out = table.groupby("group").agg(n=("single", "size"), single_acc=("single", "mean"), dense_acc=("dense", "mean"))
    return out.reset_index().assign(candidate=candidate)


def by_task(candidate: str, step: str, singles, denses, ids, configs_dir: Path = CONFIGS) -> pd.DataFrame:
    """Descriptive (plan, amendment 6, rule 55): single, dense and vote6 accuracy for each task family
    (the `task` field of BBEH items). Empty for task sets without that field."""
    from .landscape import vote_correct_by_task

    config = configs_dir / f"{step}_{candidate}_dense.yaml"
    if not config.exists() or ids is None:
        return pd.DataFrame()
    family = {t.id: t.meta.get("task") for t in load_tasks(ROOT / yaml.safe_load(config.read_text())["tasks"])}
    if not any(family.values()):
        return pd.DataFrame()
    single, dense = load_dense_rows(singles), load_dense_rows(denses)
    common = single.index.intersection(dense.index).intersection(pd.Index(ids))
    agents = [p.parent / "agents.csv" for p in as_list(denses) if (p.parent / "agents.csv").exists()]
    vote = vote_correct_by_task(agents, 6, list(common)) if agents else pd.Series(dtype=float)
    table = pd.DataFrame({"task": [family.get(t) for t in common], "single": single.loc[common, "correct"].values,
                          "dense": dense.loc[common, "correct"].values,
                          "vote6": vote.reindex(common).values})
    out = table.groupby("task").agg(n=("single", "size"), single_acc=("single", "mean"), dense_acc=("dense", "mean"),
                                    vote6_acc=("vote6", "mean"))
    return out.reset_index().assign(candidate=candidate)


def by_recall(candidate: str, singles, denses, ids) -> pd.DataFrame:
    """Contamination covariate (plan, amendment 6, rule 41): accuracy of the single agent's calls and of
    the dense run's proposers, split by whether the output cites a remembered answer (recall_cue).
    Descriptive only; it triggers nothing. Empty for runs from before the column existed."""
    from .landscape import read_agents

    parts = []
    for system, csvs, stage in [("single", singles, None), ("dense proposers", denses, "propose")]:
        paths = [p.parent / "agents.csv" for p in as_list(csvs) if (p.parent / "agents.csv").exists()]
        if not paths:
            continue
        agents = read_agents(paths)
        if "recall_cue" not in agents.columns:
            continue
        if stage is not None:
            agents = agents[agents["stage"] == stage]
        if ids is not None:
            agents = agents[agents["task_id"].isin(ids)]
        parts.append(agents.assign(system=system))
    if not parts:
        return pd.DataFrame()
    calls = pd.concat(parts)
    out = calls.groupby(["system", "recall_cue"]).agg(calls=("correct", "size"), accuracy=("correct", "mean"))
    return out.reset_index().assign(candidate=candidate)


def main(step: str = "p2", results_dir: Path = ROOT / "results", configs_dir: Path = CONFIGS) -> pd.DataFrame:
    pairs = find_pairs(step, results_dir)
    if not pairs:
        print(f"no complete {step} single/dense pairs under results/")
        return pd.DataFrame()
    widening = {c: (s, d) for c, s, d in find_pairs("p3w", results_dir)} if step == "p3" else {}
    rows, sources, recalls, families = [], [], [], []
    for candidate, single, dense in pairs:
        singles, denses, judged = slices(single), slices(dense), step
        if candidate in widening:
            singles += slices(widening[candidate][0])
            denses += slices(widening[candidate][1])
            judged = "p3w"
        ids = judged_task_ids(candidate, step, judged, configs_dir)
        row = gate_row(candidate, singles, denses, ids) | {"judged_positions": judged_label(judged)}
        senior = results_dir / f"{step}_{candidate}_single_sonnet" / "results.csv"
        if senior.exists():
            row |= senior_control(slices(senior), denses, ids)
        rows.append(row)
        sources.append(by_source(candidate, step, singles, denses, ids, configs_dir))
        recalls.append(by_recall(candidate, singles, denses, ids))
        families.append(by_task(candidate, step, singles, denses, ids, configs_dir))
    table = pd.DataFrame(rows)
    families = [t for t in families if not t.empty]
    if families:
        save_table(pd.concat(families).round(4), f"gate_{step}_by_task")
    recalls = [t for t in recalls if not t.empty]
    if recalls:
        save_table(pd.concat(recalls).round(4), f"gate_{step}_by_recall")
    sources = [t for t in sources if not t.empty]
    if sources:
        save_table(pd.concat(sources).round(4), f"gate_{step}_by_source")
    save_table(table.round(4), f"gate_{step}")
    save_figure(plot_gate(table, f"Gate {step.upper()}: accuracy with 95% bootstrap CIs (paired gap)"), f"a_gate_{step}")
    print(table.round(3).to_string(index=False))
    return table


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "p2")
