"""Figures for the team studies in the paper (ICML sizes), modelled on the report page's charts. $0: reads committed
results only; every value comes from scripts/build_numbers.py (the same generator as the paper's numbers) or, for the
pilot's vote curve, from the stored proposer answers.

  python -m analysis.paper_figs_teams      # paper/figs/fig_hero.pdf, fig_plateau.pdf, fig_lab.pdf, fig_phx.pdf, fig_map.pdf
"""
from __future__ import annotations

import glob
import importlib.util
import itertools
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "paper/figs"
COL, TEXT = 3.3, 6.75
BLUE, ORANGE, AQUA, YELLOW = "#2a78d6", "#eb6834", "#1baf7a", "#eda100"
INK, INK2, MUTED, GRID = "#0b0b0b", "#52514e", "#898781", "#e1e0d9"
plt.rcParams.update({
    "font.family": "sans-serif", "font.size": 8, "axes.edgecolor": "#c3c2b7", "axes.labelcolor": INK2,
    "xtick.color": MUTED, "ytick.color": MUTED, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.5,
    "axes.spines.top": False, "axes.spines.right": False, "lines.linewidth": 1.5, "legend.frameon": False,
    "pdf.fonttype": 42, "savefig.bbox": "tight"})


def builder():
    """scripts/build_numbers.py with the numbers the team figures need."""
    spec = importlib.util.spec_from_file_location("build_numbers", ROOT / "scripts/build_numbers.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    B.NUMBERS.clear()
    B.anchor_numbers()
    B.pilot_numbers()
    B.lab_numbers()
    B.phoenix_numbers()
    B.allocator_numbers()
    return {k: v["value"] for k, v in B.NUMBERS.items()}


def save(fig, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT / f"{name}.pdf")
    plt.close(fig)


def forest(ax, rows, xlabel):
    """rows: (label, mean, lo, hi, color, note) in points, top to bottom."""
    for i, (label, m, lo, hi, color, _note) in enumerate(rows):
        y = len(rows) - 1 - i
        ax.plot([lo, hi], [y, y], color=color, lw=2.2, solid_capstyle="round")
        ax.plot([m], [y], "o", ms=5.5, mfc="white", mec=color, mew=1.8)
    ax.axvline(0, color=INK, lw=0.8)
    ax.set_yticks(range(len(rows)))
    ax.set_yticklabels([r[0] for r in reversed(rows)])
    ax.tick_params(axis="y", length=0, labelcolor=INK)
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)


def fig_hero(N) -> None:
    """The collective minus its best alternative (the report page's hero): copies, different models, providers."""
    rows = [
        ("Luna: vote of 3 quick copies $-$ 1 reasoning call", -100 * N["ah2.luna.diff"], -100 * N["ah2.luna.hi"],
         -100 * N["ah2.luna.lo"], BLUE, f"{1 / N['ah2.luna.ratio']:.1f}$\\times$"),
        ("Haiku: vote of 2 quick copies $-$ 1 reasoning call", -100 * N["ah2.haiku.diff"], -100 * N["ah2.haiku.hi"],
         -100 * N["ah2.haiku.lo"], BLUE,
         f"{1 / N['ah2.haiku.ratio']:.1f}$\\times$"),
        ("19-agent Haiku team $-$ 1 Sonnet call", -100 * N["pilot.diff"], -100 * N["pilot.diff.hi"], -100 * N["pilot.diff.lo"], MUTED,
         f"{N['pilot.team.usd'] / N['pilot.sonnet.usd']:.1f}$\\times$"),
        ("Claude team (reads both peers) $-$ Sonnet alone", 100 * N["lab.claude.reviewminus"], 100 * N["lab.claude.reviewminus.lo"],
         100 * N["lab.claude.reviewminus.hi"], MUTED, f"{N['lab.claude.review.ratio']:.1f}$\\times$"),
        ("GPT team (reads both peers) $-$ Sol alone", 100 * N["lab.gpt.reviewminus"], 100 * N["lab.gpt.reviewminus.lo"],
         100 * N["lab.gpt.reviewminus.hi"], MUTED, f"{N['lab.gpt.review.usd'] / N['lab.gpt.single.usd']:.1f}$\\times$"),
        ("Claude + GPT panel $-$ GPT's own vote", 100 * N["lab.mix.gpt"], 100 * N["lab.mix.gpt.lo"], 100 * N["lab.mix.gpt.hi"], BLUE,
         f"{N['lab.mix.usd'] / N['lab.gpt.vote.usd']:.1f}$\\times$"),
    ]
    fig, ax = plt.subplots(figsize=(TEXT, 2.35))
    forest(ax, rows, "accuracy points, 95% interval (left of 0: the alternative wins)")
    ax.set_xlim(-25, 15)
    ax.set_ylim(-0.6, len(rows) - 0.1)
    for i, r in enumerate(rows):
        ax.text(15.6, len(rows) - 1 - i, r[5], va="center", ha="left", fontsize=8, color=INK2, clip_on=False)
    ax.text(15.6, len(rows) - 0.35, "cost", va="center", ha="left", fontsize=7.5, color=MUTED, clip_on=False)
    for y, text in ((5.45, f"copies ({N['anchor.items.all']:.0f} sealed questions; pilot: {N['pilot.items']:.0f} BBEH questions)"),
                    (2.45, f"different members (LAB-Bench, {N['lab.items']:.0f} questions)")):
        ax.text(-24.6, y, text, fontsize=7, color=MUTED, va="center")
    save(fig, "fig_hero")


def plateau_data():
    """Six Haiku proposers in the pilot (team k6-6-6-1): for k = 1..6, a plurality vote of k proposers and the share of
    questions at least one of the k answers right, each averaged over every set of k (vote ties split evenly), and
    that share under independent errors at the mean single accuracy. Returns (ks, vote %, cover %, indep %,
    questions)."""
    files = sorted(glob.glob(str(ROOT / "results/p4_bbeh_grid_[a-p]/agents.csv")))
    a = pd.concat([pd.read_csv(f) for f in files])
    p = a[(a["config_id"] == "k6-6-6-1") & (a["stage"] == "propose")].copy()
    p["norm"] = p["answer"].astype(str).str.strip().str.lower()
    ids = sorted(p["agent_id"].unique())
    ks, vote, cover = list(range(1, 7)), [], []
    for k in ks:
        accs, covs = [], []
        for subset in itertools.combinations(ids, k):
            q = p[p["agent_id"].isin(subset)]
            acc = 0.0
            for _, g in q.groupby("task_id"):
                g = g[g["answer"].notna() & (g["answer"].astype(str).str.len() > 0)]
                if len(g):
                    c = g.groupby("norm").agg(n=("correct", "size"), right=("correct", "max"))
                    acc += c[c["n"] == c["n"].max()]["right"].mean()
            accs.append(acc / q["task_id"].nunique())
            covs.append(q.groupby("task_id")["correct"].max().mean())
        vote.append(100 * np.mean(accs))
        cover.append(100 * np.mean(covs))
    single = p.groupby("task_id")["correct"].mean().mean()
    indep = [100 * (1 - (1 - single) ** k) for k in ks]
    return ks, vote, cover, indep, p["task_id"].nunique()


def fig_plateau() -> None:
    """Six Haiku proposers in the pilot: a vote of k against coverage and independence (plateau_data)."""
    ks, vote, cover, indep, n = plateau_data()
    fig, ax = plt.subplots(figsize=(COL, 2.3))
    ax.plot(ks, indep, "--", color=MUTED, label="one right, if errors were independent")
    ax.plot(ks, cover, "-o", color=AQUA, ms=3.5, label="one of the k proposers right")
    ax.plot(ks, vote, "-o", color=BLUE, ms=3.5, label="plurality vote of the k")
    ax.set_xlabel(f"proposers k (Claude Haiku 5.5, {n} BBEH questions)")
    ax.set_ylabel("accuracy (%)")
    ax.set_ylim(15, 100)
    ax.set_xticks(ks)
    ax.legend(loc="lower right", fontsize=6.6)
    save(fig, "fig_plateau")


def fig_lab(N) -> None:
    """LAB-Bench test (144 questions): accuracy against dollars per question for single models, team methods and the
    cross-provider panel."""
    base = ROOT / "reports/self_or_social_shortlist"
    fig, ax = plt.subplots(figsize=(COL, 2.6))
    names = {"single_A": ("Haiku", "Luna"), "single_B": ("Sonnet low", "Sol low"), "single_C": ("Sonnet med", "Sol med")}
    for team, folder, color, k in (("Claude", "labbench_claude2", BLUE, 0), ("GPT", "labbench_gpt", AQUA, 1)):
        s = pd.read_csv(base / folder / "summary.csv").set_index("method")
        singles = s.loc[["single_A", "single_B", "single_C"]]
        methods = s.loc[["vote", "all_reflect", "fixed_peer", "full_review", "policy"]]
        ax.scatter(100 * singles["usd_per_item"], 100 * singles["accuracy"], marker="o", s=22, facecolor="white",
                   edgecolor=color, linewidth=1.4, zorder=3, label=f"{team}: one model alone")
        ax.scatter(100 * methods["usd_per_item"], 100 * methods["accuracy"], marker="s", s=18, color=color, zorder=3,
                   label=f"{team}: team of three")
        for m in ("single_A", "single_B"):
            ax.annotate(names[m][k], (100 * s.loc[m, "usd_per_item"], 100 * s.loc[m, "accuracy"]), fontsize=6.5,
                        color=INK2, xytext=(4, -9 if m == "single_A" else 3), textcoords="offset points")
    x = pd.read_csv(base / "cross_provider/summary.csv").set_index("method").loc["panel_X"]
    ax.scatter([100 * x["usd_per_item"]], [100 * x["accuracy"]], marker="*", s=70, color=YELLOW, edgecolor=INK2,
               linewidth=0.5, zorder=4, label="Claude + GPT panel")
    ax.set_xscale("log")
    ax.set_xticks([0.05, 0.1, 0.3, 1, 3])
    ax.set_xticklabels(["0.05", "0.1", "0.3", "1", "3"])
    ax.set_xlabel("cents per question (log scale)")
    ax.set_ylabel(f"accuracy on {int(s['items'].iloc[0])} test questions (%)")
    ax.set_ylim(60, 92)
    ax.legend(loc="lower right", fontsize=6.3, handletextpad=0.3, borderaxespad=0.2)
    save(fig, "fig_lab")


def fig_phx(N) -> None:
    """PHOENIX: sealed test balanced-accuracy points, paired by case (18 cases; arms: mean of two draws)."""
    rows = [
        ("rule alone: one cheap planner, full $-$ takeover", 100 * N["phx.main"], 100 * N["phx.main.lo"], 100 * N["phx.main.hi"], BLUE, ""),
        ("Opus plans every step $-$ takeover", 100 * N["phx.planner"], 100 * N["phx.planner.lo"], 100 * N["phx.planner.hi"], MUTED, ""),
        ("Opus + rule $-$ Opus plans every step", 100 * N["phx.rule"], 100 * N["phx.rule.lo"], 100 * N["phx.rule.hi"], BLUE, ""),
        ("Opus + rule $-$ takeover", 100 * N["phx.claude"], 100 * N["phx.claude.lo"], 100 * N["phx.claude.hi"], BLUE, ""),
        ("Sol + rule $-$ takeover", 100 * N["phx.gpt"], 100 * N["phx.gpt.lo"], 100 * N["phx.gpt.hi"], BLUE, ""),
    ]
    fig, ax = plt.subplots(figsize=(COL, 2.0))
    forest(ax, rows, "test balanced-accuracy points, 95% interval")
    ax.set_xlim(-1, 2)
    save(fig, "fig_phx")


def fig_map() -> None:
    """The budget map on 440 BBEH questions: the winning team per dollar budget (columns) and 95th-percentile
    latency budget (rows); shading is its accuracy; empty rows: no team is fast enough."""
    m = pd.read_csv(ROOT / "research/v4/measurement/tables/config_map.csv")
    m = m[(m["benchmark"] == "bbeh") & (m["latency"] == "p95 total")]
    usd = sorted(m["usd_budget"].unique())
    lat = sorted(m["latency_budget"].unique())
    label = {"single": "", "vote@3": " ×3"}
    short = {"haiku_low": "Haiku low", "haiku_off": "Haiku", "sol_low": "Sol low", "sonnet_low": "Sonnet low",
             "luna_none": "Luna", "luna_low": "Luna low"}
    fig, ax = plt.subplots(figsize=(TEXT, 2.45))
    cmap = plt.get_cmap("Blues")
    for i, L in enumerate(lat):
        for j, U in enumerate(usd):
            row = m[(m["usd_budget"] == U) & (m["latency_budget"] == L)]
            y = len(lat) - 1 - i
            if row.empty or pd.isna(row["winner"].iloc[0]):
                ax.add_patch(plt.Rectangle((j, y), 1, 1, facecolor="#f3f2ee", edgecolor="white", hatch="///", lw=0))
                continue
            w, acc = row["winner"].iloc[0], row["accuracy"].iloc[0]
            model, kind = w.rsplit(" ", 1)
            ax.add_patch(plt.Rectangle((j, y), 1, 1, facecolor=cmap(0.15 + 0.75 * (acc - 0.2) / 0.45), edgecolor="white", lw=1))
            vote = " ×3 · " if kind.startswith("vote") else " "
            ax.text(j + 0.5, y + 0.5, f"{short.get(model, model)}\n{vote.strip(' ') + ' ' if vote.strip() else ''}{100 * acc:.0f}%",
                    ha="center", va="center", fontsize=6.4, color="white" if acc > 0.45 else INK, linespacing=1.1)
    ax.set_xlim(0, len(usd))
    ax.set_ylim(0, len(lat))
    ax.set_xticks([j + 0.5 for j in range(len(usd))])
    ax.set_xticklabels([f"${u:g}" for u in usd])
    ax.set_yticks([len(lat) - 1 - i + 0.5 for i in range(len(lat))])
    ax.set_yticklabels([f"≤ {L:g} s" for L in lat])
    ax.set_xlabel("dollars per question")
    ax.set_ylabel("p95 latency")
    ax.grid(False)
    ax.tick_params(length=0)
    for side in ("left", "bottom"):
        ax.spines[side].set_visible(False)
    save(fig, "fig_map")


def main() -> None:
    N = builder()
    fig_hero(N)
    fig_plateau()
    fig_lab(N)
    fig_phx(N)
    fig_map()
    print("5 figures ->", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main()
