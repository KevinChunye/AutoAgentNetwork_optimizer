"""The designs scoreboard (research/designs.md): every way of spending calls on a task that the
pilot can score, side by side on the same items, each compared with the dense network there.

Terms:
  search half     validation 20-59 (the first half of the P4 grid parts: a-d for Omni's 10-item
                  parts, a-h for BBEH's 5-item parts). Picks, policies and the equimarginal path
                  are chosen here.
  held-out half   validation 60-99 (the second half of the parts). Choices made on the search half
                  are only scored here, so the held-out numbers carry no winner's curse.
  vote or Sonnet  answer with the six proposers' plurality when its share is at least theta, else
                  ask one Sonnet call (plan rule 63); theta is chosen on the search half with the
                  P3 Sonnet run and scored once on the held-out half with the held-out Sonnet run.
  error           share of items answered wrongly, with a 95% task-bootstrap CI.
  cost per task   mean dollars per item at list price. Calls served from the cache count at their
                  original price, so every design is costed as if it ran alone.
  vs dense        the design's accuracy minus the dense network's accuracy on the same items, in
                  points, with a 95% paired-bootstrap CI. Positive means better than dense.
  reward          -error - lam * log2(cost / dense cost), the landscape's reward (lam = 0.05: halving
                  the cost is worth 5 points of error). Used only to choose on the search half.
  status          run (live calls), offline (scored from calls the grid already made), not run.
  role            the design that each scale-up trigger names in advance (plan, amendment 4, rule 25),
                  or "descriptive": every other row is reported but triggers nothing, so the scoreboard
                  is not a search over ~10 designs for one that happens to look good.
  rule 24         a held-out design "matches dense" when its accuracy is at least dense's minus 3 points
                  (point estimate) at no more than half dense's cost per task (H5 margin).

Usage: python -m analysis.designs   (reads results/, writes research/designs.md)
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from .common import ROOT, bootstrap_mean_ci, paired_bootstrap_diff, save_table
from .economics import MS, distinct_policies, equimarginal_path, policy_outcomes, proposer_exits
from .landscape import Landscape, load_landscape, read_agents, reward, sensitivity_pick, summarize

LAM = 0.05
DESIGNS_MD = ROOT / "research" / "designs.md"
MARGIN_POINTS, MAX_COST_SHARE = -3.0, 0.5  # rule 24
ROLES = {"best consensus policy": "trigger: H5", "joint pick (exhaustive)": "trigger: static pruning",
         "single Sonnet (senior control)": "trigger: senior (rule 18)"}

# Every design the pilot plans, in table order: (design, calls per task, where it comes from).
PLANNED = [
    ("single Haiku", "1", "p4_<cand>_single_held, live"),
    ("single Sonnet (senior control)", "1 Sonnet", "p3_<cand>_single_sonnet, live, P3 items 20-59"),
    ("dense 6-6-6-1", "19", "P4 grid"),
    ("vote6", "6", "offline: consensus m=6, theta=0"),
    ("gated_3x6", "6 or 19", "offline: consensus m=6, theta=5/6, else dense"),
    ("best consensus policy", "varies", "offline, chosen on the search half"),
    ("equimarginal endpoint", "varies", "offline, path built on the search half"),
    ("joint pick (exhaustive)", "varies", "offline, chosen on the search half"),
    ("stage-by-stage pick", "varies", "offline, chosen on the search half"),
    ("judge_cascade", "6 or 7 (+ Sonnet)", "p4b_<cand>_judge_cascade, live; not run in the pilot: its fixed routing "
     "(13 exit, 21 Haiku aggregator, 6 Sonnet of 40) puts its cost floor at 55% of dense, over rule 24's 50% (audit 25)"),
    ("single Sonnet, held-out", "1 Sonnet", "p4_<cand>_single_sonnet_held, live"),
    ("vote or Sonnet", "6 (+ 1 Sonnet)", "offline: P4 proposers + Sonnet runs; theta chosen on the search half"),
    ("mixed_vote6", "6 (3 Haiku + 3 Luna)", "not in the pilot (post-pilot option)"),
]


def read_results(results_csv: Path) -> pd.DataFrame:
    """Per-task correct and cost of one live run (replicate 0), indexed by task_id."""
    rows = pd.read_csv(results_csv)
    rows = rows[rows["replicate"] == 0].drop_duplicates("task_id").set_index("task_id")
    return rows[["correct", "cost_usd"]]


def score(design: str, calls: str, source: str, status: str, correct: pd.Series, cost: pd.Series,
          dense_correct: pd.Series, items: str) -> dict:
    """One scoreboard row: error and cost over the design's items, and its paired difference
    from dense on the items both have."""
    common = correct.index.intersection(dense_correct.index)
    acc, acc_lo, acc_hi = bootstrap_mean_ci(correct.loc[common])
    diff = paired_bootstrap_diff(correct.loc[common], dense_correct.loc[common])
    return {"design": design, "calls": calls, "source": source, "status": status, "items": items, "n": len(common),
            "error": 1 - acc, "error_lo": 1 - acc_hi, "error_hi": 1 - acc_lo, "cost_usd": float(cost.loc[common].mean()),
            "vs_dense_points": 100 * diff[0], "vs_dense_lo": 100 * diff[1], "vs_dense_hi": 100 * diff[2]}


def best_policy(L: Landscape, agents: pd.DataFrame, search: list[str], fallbacks: dict[str, str]) -> tuple[int, float, str]:
    """The consensus policy (m, theta, fallback) with the highest reward on the search half."""
    dense_cost = L.cost.loc[L.dense_id, search].mean()
    rows = []
    for m in MS:
        exits, per_agent = proposer_exits(agents, m, search)
        for theta in [t for _, t in distinct_policies((m,))]:
            for fallback in fallbacks.values():
                out = policy_outcomes(L, exits, per_agent, m, theta, fallback, search)
                r = -(1 - out["correct"].mean()) - LAM * np.log2(out["cost_usd"].mean() / dense_cost)
                rows.append({"m": m, "theta": theta, "fallback": fallback, "reward": r})
    best = pd.DataFrame(rows).sort_values("reward", ascending=False).iloc[0]
    return int(best["m"]), float(best["theta"]), str(best["fallback"])


def vote_or_sonnet(exits: pd.DataFrame, sonnet: pd.DataFrame, theta: float, tasks: list[str]) -> pd.DataFrame:
    """Per task: the six proposers' plurality when its share is at least theta, else one Sonnet call.
    Cost is the six proposers plus, when the vote does not settle it, the Sonnet call (rule 63)."""
    tasks = [t for t in tasks if t in exits.index and t in sonnet.index]
    e, s = exits.loc[tasks], sonnet.loc[tasks]
    exited = e["share"] >= theta - 1e-9
    return pd.DataFrame({"correct": np.where(exited, e["exit_correct"], s["correct"]),
                         "cost_usd": np.where(exited, e["exit_cost"], e["exit_cost"] + s["cost_usd"]),
                         "exited": exited.astype(float)}, index=tasks)


def best_vote_or_sonnet_theta(exits: pd.DataFrame, sonnet: pd.DataFrame, tasks: list[str], dense_cost: float) -> float:
    """The theta (one per distinct number of agreeing proposers out of six) with the highest reward
    on the search half; ties go to the smaller theta (plan rule 63)."""
    rows = []
    for _, theta in distinct_policies((6,)):
        out = vote_or_sonnet(exits, sonnet, theta, tasks)
        rows.append({"theta": theta, "reward": -(1 - out["correct"].mean()) - LAM * np.log2(out["cost_usd"].mean() / dense_cost)})
    best = pd.DataFrame(rows).sort_values(["reward", "theta"], ascending=[False, True]).iloc[0]
    return float(best["theta"])


def scoreboard(L: Landscape, search: list[str], held: list[str], agents: pd.DataFrame,
               single: pd.DataFrame | None = None, senior: pd.DataFrame | None = None,
               cascade: pd.DataFrame | None = None, senior_held: pd.DataFrame | None = None) -> pd.DataFrame:
    """All planned designs; those without data are listed as "not run"."""
    dense = L.correct.loc[L.dense_id]
    held_dense = dense.loc[held]
    rows = {}

    def static(design, config_id, calls, source):
        rows[design] = score(design, calls, source, "offline", L.correct.loc[config_id, held],
                             L.cost.loc[config_id, held], held_dense, f"held-out ({config_id})")

    if single is not None:
        rows["single Haiku"] = score("single Haiku", "1", PLANNED[0][2], "run", single["correct"], single["cost_usd"],
                                     held_dense, "held-out")
    if senior is not None:  # P3 items: the search half, so compared with dense there
        rows["single Sonnet (senior control)"] = score("single Sonnet (senior control)", "1 Sonnet", PLANNED[1][2], "run",
                                                       senior["correct"], senior["cost_usd"], dense, "P3 items 20-59")
    static("dense 6-6-6-1", L.dense_id, "19", "P4 grid")

    held_exits = {m: proposer_exits(agents, m, held) for m in (2, 3, 4, 6)}

    def policy(design, m, theta, fallback, calls, source):
        exits, per_agent = held_exits[m]
        out = policy_outcomes(L, exits, per_agent, m, theta, fallback, held)
        rows[design] = score(design, calls, source, "offline", out["correct"], out["cost_usd"], held_dense,
                             f"held-out (exit rate {out['exited'].mean():.0%})")

    policy("vote6", 6, 0.0, L.dense_id, "6", PLANNED[3][2])
    policy("gated_3x6", 6, 5 / 6, L.dense_id, "6 or 19", PLANNED[4][2])
    s_search = summarize(L, search)
    fallbacks = {"dense": L.dense_id, "cheapest": s_search["cost_usd"].idxmin()}
    m, theta, fallback = best_policy(L, agents, search, fallbacks)
    policy("best consensus policy", m, theta, fallback, "varies",
           f"offline, chosen on the search half: m={m}, theta={theta:.2f}, else {fallback}")

    r_search = reward(s_search, L.dense_id, LAM)
    endpoint = equimarginal_path(s_search)["config_id"].iloc[-1]
    static("equimarginal endpoint", endpoint, "varies", PLANNED[6][2])
    static("joint pick (exhaustive)", r_search.idxmax(), "varies", PLANNED[7][2])
    static("stage-by-stage pick", sensitivity_pick(s_search, r_search)[0], "varies", PLANNED[8][2])
    if cascade is not None:
        rows["judge_cascade"] = score("judge_cascade", PLANNED[9][1], PLANNED[9][2], "run", cascade["correct"],
                                      cascade["cost_usd"], held_dense, "held-out")
    if senior_held is not None:
        rows["single Sonnet, held-out"] = score("single Sonnet, held-out", "1 Sonnet", PLANNED[10][2], "run",
                                                senior_held["correct"], senior_held["cost_usd"], held_dense, "held-out")
    if senior is not None and senior_held is not None:
        search_exits, _ = proposer_exits(agents, 6, search)
        theta = best_vote_or_sonnet_theta(search_exits, senior, search, float(L.cost.loc[L.dense_id, search].mean()))
        out = vote_or_sonnet(held_exits[6][0], senior_held, theta, held)
        rows["vote or Sonnet"] = score("vote or Sonnet", PLANNED[11][1], f"offline, theta={theta:.2f} chosen on the search half",
                                       "offline", out["correct"], out["cost_usd"], held_dense,
                                       f"held-out (vote settles {out['exited'].mean():.0%})")
    table = []
    for design, calls, source in PLANNED:
        table.append(rows[design] if design in rows else
                     {"design": design, "calls": calls, "source": source, "status": "not run"})
    return with_roles(pd.DataFrame(table), dense_cost=float(L.cost.loc[L.dense_id, held].mean()))


def with_roles(table: pd.DataFrame, dense_cost: float | None = None) -> pd.DataFrame:
    """Add each row's role and, for held-out rows with data, whether it meets the rule-24 margin."""
    table = table.copy()
    table["role"] = table["design"].map(ROLES).fillna("descriptive")
    meets = []
    for row in table.to_dict("records"):
        held_row = row["status"] != "not run" and str(row.get("items", "")).startswith("held-out")
        meets.append(bool(row["vs_dense_points"] >= MARGIN_POINTS and row["cost_usd"] <= MAX_COST_SHARE * dense_cost)
                     if held_row and dense_cost else None)
    table["meets_rule_24"] = meets
    return table


def to_markdown(table: pd.DataFrame, note: str) -> str:
    """research/designs.md: the scoreboard with errors and differences in points."""
    lines = ["# Designs scoreboard", "", "Written by `python -m analysis.designs` (also run by `analysis/build_report.py`); "
             "do not edit by hand. Terms are defined in the module docstring.", "", note, "",
             "| design | role | calls per task | status | items | n | error % (95% CI) | cost per task (cents) | vs dense, points (95% CI) | rule 24 | source |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in table.to_dict("records"):
        if row["status"] == "not run":
            lines.append(f"| {row['design']} | {row['role']} | {row['calls']} | not run | | | | | | | {row['source']} |")
            continue
        rule = {True: "yes", False: "no"}.get(row["meets_rule_24"], "")
        lines.append(f"| {row['design']} | {row['role']} | {row['calls']} | {row['status']} | {row['items']} | {int(row['n'])} | "
                     f"{100 * row['error']:.1f} ({100 * row['error_lo']:.1f} to {100 * row['error_hi']:.1f}) | "
                     f"{100 * row['cost_usd']:.3f} | {row['vs_dense_points']:+.1f} ({row['vs_dense_lo']:+.1f} to "
                     f"{row['vs_dense_hi']:+.1f}) | {rule} | {row['source']} |")
    return "\n".join(lines) + "\n"


def main(search_dirs: list[Path], held_dirs: list[Path], results_dir: Path = ROOT / "results",
         out: Path = DESIGNS_MD) -> pd.DataFrame:
    """Score every design from the P4 grid parts and the live control runs; write designs.md."""
    if not search_dirs:
        table = with_roles(pd.DataFrame([{"design": d, "calls": c, "source": s, "status": "not run"} for d, c, s in PLANNED]))
        out.write_text(to_markdown(table, "No P4 data yet: every design is listed as planned."))
        return table
    paths = list(search_dirs) + list(held_dirs)
    L = load_landscape(paths)
    first = pd.concat([pd.read_csv(Path(f) / "results.csv") for f in search_dirs])["task_id"].unique().tolist()
    search = [t for t in L.tasks if t in first]
    held = [t for t in L.tasks if t not in first] or search
    agents = read_agents([p / "agents.csv" for p in paths if (p / "agents.csv").exists()])

    def live(pattern):
        from .gate import slices

        found = sorted(results_dir.glob(pattern))
        if not found:
            return None
        parts = [read_results(p) for p in slices(found[0] / "results.csv")]  # a split run's slices (audit 15)
        return pd.concat(parts)[lambda t: ~t.index.duplicated()]

    table = scoreboard(L, search, held, agents, single=live("p4_*_single_held"), senior=live("p3_*_single_sonnet"),
                       cascade=live("p4b_*_judge_cascade"), senior_held=live("p4_*_single_sonnet_held"))
    save_table(table.round(5), "designs")
    note = (f"Held-out half: {len(held)} items; search half: {len(search)} items. "
            + ("WARNING: no held-out parts yet, so every row is scored on the search half (winner's curse)."
               if held == search else "Choices were made on the search half only."))
    out.write_text(to_markdown(table, note))
    print(table[["design", "status", "n", "error", "cost_usd", "vs_dense_points"]].round(3).to_string(index=False))
    return table


if __name__ == "__main__":
    from .build_report import p4_halves

    main(*p4_halves())
