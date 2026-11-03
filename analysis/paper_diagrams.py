"""Walkthrough figures for the paper. Each shows how a study was set up (what was built, how it ran, what was measured)
next to its main result, so a reader can follow the experiment, not only its outcome.

How they are made: the charts are matplotlib, written as SVG with the text kept as text; the panels are HTML and
CSS; Chromium (Node Playwright, analysis/print_figure.mjs) prints each figure to a one-page vector PDF at its printed
width, 6.75 in (the ICML text width), so the type sizes below are the printed sizes. $0: reads committed results only;
every number comes from scripts/build_numbers.py (through analysis.paper_figs_teams.builder) or a committed results
file. The fonts are Inter and JetBrains Mono when installed (both free), else the browser's sans-serif.

  python -m analysis.paper_diagrams    # paper/figs/fig_overview.pdf, fig_pilot.pdf, fig_lab_setup.pdf, fig_phoenix.pdf

Terms used below:
  collective         a team, a vote of copies or a panel: several calls whose answers are combined.
  best alternative   the single setting it is compared with (one reasoning call, one stronger call, the team's best
                     member alone, or another team's vote), on the same questions.
  difference         collective accuracy minus alternative accuracy, in percentage points, paired by question; the
                     95% interval is the studies' own paired item bootstrap (2,000 draws).
  cost ratio         the collective's dollars per question divided by the alternative's.
"""
from __future__ import annotations

import glob
import io
import json
import shutil
import subprocess
import sys
import tempfile
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import pandas as pd  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
OUT = ROOT / "paper/figs"
WIDTH_IN = 6.75

# colours: one meaning each across the four figures
ORANGE, BLUE, GREY, AMBER = "#e8742a", "#4a7bd6", "#8d8d93", "#f0a020"
CLAUDE, GPT = "#c96442", "#10a37f"
INK, INK2, MUTED, GRIDC = "#202024", "#4b4b52", "#8a8a90", "#e7e7e3"
RC = {"font.family": ["Inter", "DejaVu Sans"], "font.size": 6.5, "svg.fonttype": "none", "svg.hashsalt": "aan",
      "axes.edgecolor": "#bdbdc2", "axes.labelcolor": INK2, "axes.linewidth": 0.6, "xtick.color": INK2,
      "ytick.color": INK2, "xtick.major.width": 0.6, "ytick.major.width": 0.6, "xtick.major.size": 2.5,
      "ytick.major.size": 2.5, "axes.grid": True, "grid.color": GRIDC, "grid.linewidth": 0.5,
      "axes.spines.top": False, "axes.spines.right": False, "legend.frameon": False, "axes.unicode_minus": True}


def r1(x: float, digits: int = 1) -> str:
    """Round half away from zero (as the paper's numbers.tex does) and format."""
    q = Decimal(1).scaleb(-digits)
    return str(Decimal(repr(float(x))).quantize(q, rounding=ROUND_HALF_UP))


def signed(x: float, digits: int = 1) -> str:
    s = r1(x, digits)
    return "+" + s if not s.startswith("-") else "−" + s[1:]


def svg_of(fig) -> str:
    """A matplotlib figure as an inline SVG element (text stays text, so the PDF carries real fonts)."""
    buf = io.StringIO()
    fig.savefig(buf, format="svg", transparent=True)
    plt.close(fig)
    s = buf.getvalue()
    s = s[s.index("<svg"):]
    return s.replace("<svg ", '<svg class="chart" ', 1)


# ----------------------------------------------------------------------------------------------------------- data

def pilot_grid() -> pd.DataFrame:
    """The pilot's 27 pruned teams on its 80 BBEH questions (results/p4_bbeh_grid_*/results.csv): for each team
    (config k{proposers}-{critics}-{refiners}-1) its accuracy, mean dollars per question, calls, mean slowest path
    (critical path, seconds) and mean peak context (the largest prompt one agent read, tokens)."""
    files = sorted(glob.glob(str(ROOT / "results/p4_bbeh_grid_[a-p]/results.csv")))
    r = pd.concat([pd.read_csv(f) for f in files])
    g = r.groupby("config_id").agg(acc=("correct", "mean"), usd=("cost_usd", "mean"), calls=("calls", "mean"),
                                   cp=("critical_path_s", "mean"), peak=("peak_context_tokens", "mean"),
                                   n=("task_id", "nunique")).reset_index()
    return g.sort_values("usd").reset_index(drop=True)


def frontier(g: pd.DataFrame) -> pd.DataFrame:
    """Teams no other team beats on both cost and accuracy (cheapest first)."""
    out, best = [], -1.0
    for _, row in g.sort_values(["usd", "acc"], ascending=[True, False]).iterrows():
        if row["acc"] > best:
            out.append(row)
            best = row["acc"]
    return pd.DataFrame(out)


def phoenix_case(arm: str = "claude", case: str = "higgs_T1_101", draw: str = "d1") -> dict:
    """One case's recovery trajectories (results/fam_<arm>_E1_<case>_<policy>_F1_100_<draw>): after each executed step,
    the CPU seconds spent and the validation score (balanced accuracy on training-internal rows), with the branch's
    API dollars and its caps from status.json."""
    out = {}
    for pol in ("fixed", "llm", "full"):
        run = ROOT / f"results/fam_{arm}_E1_{case}_{pol}_F1_100_{draw}"
        t = json.loads((run / "trajectory.json").read_text())
        s = json.loads((run / "status.json").read_text())
        out[pol] = {"pts": [(x["cpu_s"], x["validation_score"]) for x in t], "usd": s["budget"]["api_spent"],
                    "caps": s["budget"]}
    return out


def phoenix_caps() -> dict:
    """The caps per recovery in the main study (one cheap planner) and in the two planner arms."""
    main = sorted(glob.glob(str(ROOT / "results/sci_E1_*_full_F1_20/status.json")))[0]
    arm = sorted(glob.glob(str(ROOT / "results/fam_claude_E1_*_full_F1_100_d1/status.json")))[0]
    m, a = json.loads(Path(main).read_text())["budget"], json.loads(Path(arm).read_text())["budget"]
    return {"main_usd": m["api_limit"], "arm_usd": a["api_limit"], "calls": a["call_limit"], "tools": a["tool_limit"],
            "cpu": a["cpu_limit"]}


def lab_points():
    """LAB-Bench test (reports/self_or_social_shortlist): accuracy and dollars per question for each team's single
    members, its five team methods, and the cross-provider panel."""
    base = ROOT / "reports/self_or_social_shortlist"
    teams = {}
    for team, folder in (("Claude", "labbench_claude2"), ("GPT", "labbench_gpt")):
        teams[team] = pd.read_csv(base / folder / "summary.csv").set_index("method")
    panel = pd.read_csv(base / "cross_provider/summary.csv").set_index("method").loc["panel_X"]
    per = pd.read_csv(base / "labbench_claude2/per_item.csv")
    items = pd.Series(per["item"].unique())
    subsets = {"seqqa": int(items.str.contains("seqqa").sum()), "protocolqa": int(items.str.contains("protocolqa").sum())}
    return teams, panel, subsets


# --------------------------------------------------------------------------------------------------------- charts

def chart_overview_forest(N, width: float) -> str:
    """The collective minus its best alternative: seven paired differences with 95% intervals and the cost ratio."""
    groups = [
        (f"Copies against one reasoning call · {N['anchor.items.all']:.0f} sealed questions", [
            ("Luna: 3 copies − 1 deep", -N["ah2.luna.diff"], -N["ah2.luna.hi"], -N["ah2.luna.lo"], "conf",
             1 / N["ah2.luna.ratio"]),
            ("Haiku: 2 copies − 1 deep", -N["ah2.haiku.diff"], -N["ah2.haiku.hi"], -N["ah2.haiku.lo"], "conf",
             1 / N["ah2.haiku.ratio"])]),
        (f"The pilot · {N['pilot.items']:.0f} BBEH questions", [
            ("19 Haiku − 1 Sonnet", -N["pilot.diff"], -N["pilot.diff.hi"], -N["pilot.diff.lo"], "desc",
             N["pilot.team.usd"] / N["pilot.sonnet.usd"])]),
        (f"Different members · LAB-Bench, {N['lab.items']:.0f} test questions", [
            ("Claude: reflect − Sonnet", N["lab.claude.reflectminus"], N["lab.claude.reflectminus.lo"],
             N["lab.claude.reflectminus.hi"], "desc", N["lab.claude.reflect.usd"] / N["lab.claude.single.usd"]),
            ("Claude: read all − Sonnet", N["lab.claude.reviewminus"], N["lab.claude.reviewminus.lo"],
             N["lab.claude.reviewminus.hi"], "desc", N["lab.claude.review.ratio"]),
            ("GPT: read all − Sol low", N["lab.gpt.reviewminus"], N["lab.gpt.reviewminus.lo"],
             N["lab.gpt.reviewminus.hi"], "desc", N["lab.gpt.review.usd"] / N["lab.gpt.single.usd"]),
            ("Claude+GPT − GPT vote", N["lab.mix.gpt"], N["lab.mix.gpt.lo"], N["lab.mix.gpt.hi"], "xprov",
             N["lab.mix.usd"] / N["lab.gpt.vote.usd"])]),
    ]
    style = {"conf": (ORANGE, ORANGE), "desc": (GREY, "white"), "xprov": (BLUE, "white")}
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(width, 2.2))
        ax = fig.add_axes([0.37, 0.155, 0.53, 0.775])
        y, ticks, labels = 0.0, [], []
        for header, rows in groups:
            ax.text(-0.69, y + 0.05, header, transform=ax.get_yaxis_transform(), fontsize=6.0, color=MUTED,
                    va="center", ha="left", zorder=5,
                    bbox={"facecolor": "white", "edgecolor": "none", "pad": 0.6})
            y += 0.85
            for label, m, lo, hi, kind, ratio in rows:
                line, face = style[kind]
                ax.plot([100 * lo, 100 * hi], [y, y], color=line, lw=2.0, solid_capstyle="round", zorder=2)
                ax.plot([100 * m], [y], "o", ms=5.2, mfc=face, mec=line, mew=1.4, zorder=3)
                ax.text(1.035, y, f"{r1(ratio)}×", transform=ax.get_yaxis_transform(), va="center", ha="left",
                        fontsize=6.8, color=INK)
                ticks.append(y)
                labels.append(label)
                y += 1.0
            y += 0.1
        ax.text(1.035, 0.05, "cost", transform=ax.get_yaxis_transform(), va="center", ha="left", fontsize=6.0,
                color=MUTED)
        ax.set_yticks(ticks)
        ax.set_yticklabels(labels, fontsize=6.8, color=INK)
        ax.tick_params(axis="y", length=0, pad=3)
        ax.tick_params(axis="x", labelsize=6.4)
        ax.set_ylim(y - 0.4, -0.5)
        ax.set_xlim(-25, 13)
        ax.set_xticks([-20, -15, -10, -5, 0, 5, 10])
        ax.set_xticklabels(["−20", "−15", "−10", "−5", "0", "+5", "+10"])
        ax.axvline(0, color=INK, lw=0.8, zorder=1)
        ax.grid(axis="y", visible=False)
        ax.spines["left"].set_visible(False)
        ax.set_xlabel("difference, accuracy points (95% interval)", fontsize=6.5, labelpad=2)
        ax.text(-0.8, 1.012, "← alternative wins", transform=ax.get_xaxis_transform(), ha="right", va="bottom",
                fontsize=6.0, color=MUTED)
        ax.text(0.8, 1.012, "collective wins →", transform=ax.get_xaxis_transform(), ha="left", va="bottom",
                fontsize=6.0, color=MUTED)
        return svg_of(fig)


def chart_pilot_scatter(N, g: pd.DataFrame, width: float) -> str:
    """The 27 teams' accuracy against dollars per question, the cost-accuracy frontier, the full team's 95% interval
    (normal approximation at n questions) and one Sonnet call."""
    full = g[g["config_id"] == "k6-6-6-1"].iloc[0]
    n = int(full["n"])
    half = 1.96 * (full["acc"] * (1 - full["acc"]) / n) ** 0.5
    f = frontier(g)
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(width, 1.98))
        ax = fig.add_axes([0.15, 0.19, 0.80, 0.76])
        ax.scatter(g["usd"], 100 * g["acc"], s=15, facecolor="white", edgecolor="#a3a3a8", lw=0.9, zorder=3)
        ax.plot(f["usd"], 100 * f["acc"], "--", color=INK2, lw=0.8, zorder=2)
        ax.scatter(f["usd"], 100 * f["acc"], s=15, facecolor="white", edgecolor=INK2, lw=1.0, zorder=4)
        ax.plot([full["usd"]] * 2, [100 * (full["acc"] - half), 100 * (full["acc"] + half)], color=BLUE, lw=1.0,
                alpha=0.55, zorder=3)
        ax.scatter([full["usd"]], [100 * full["acc"]], s=26, color=BLUE, zorder=5)
        ax.annotate(f"full team, {int(full['calls'])} calls", (full["usd"], 100 * full["acc"]), xytext=(-5, 7),
                    textcoords="offset points", ha="right", fontsize=6, color=BLUE)
        ax.annotate(f"±{r1(100 * half, 0)} points:\n95% interval at n = {n}", (full["usd"], 100 * (full["acc"] - half)),
                    xytext=(5, 0), textcoords="offset points", ha="left", va="bottom", fontsize=5.4, color=MUTED,
                    linespacing=1.05)
        ax.scatter([N["pilot.sonnet.usd"]], [100 * N["pilot.sonnet.acc"]], marker="*", s=70, color=AMBER, edgecolor=INK2,
                   lw=0.4, zorder=6)
        ax.annotate("1 Sonnet call", (N["pilot.sonnet.usd"], 100 * N["pilot.sonnet.acc"]), xytext=(-6, 2),
                    textcoords="offset points", ha="right", va="bottom", fontsize=6, color=INK)
        lo = g.iloc[0]
        ax.annotate(f"{int(lo['calls'])} calls", (lo["usd"], 100 * lo["acc"]), xytext=(3, -8), textcoords="offset points",
                    fontsize=5.6, color=MUTED)
        ax.set_xlim(0, 0.016)
        ax.set_xticks([0, 0.004, 0.008, 0.012, 0.016])
        ax.set_xticklabels(["$0", "$0.004", "$0.008", "$0.012", "$0.016"])
        ax.set_ylim(38, 76)
        ax.set_yticks([40, 50, 60, 70])
        ax.set_yticklabels(["40%", "50%", "60%", "70%"])
        ax.set_xlabel("dollars per question", fontsize=6.2, labelpad=2)
        ax.set_ylabel("accuracy", fontsize=6.2, labelpad=2)
        return svg_of(fig)


def chart_plateau(width: float) -> str:
    """Six proposers: a vote of k, at least one of k right, and that share under independent errors."""
    from analysis.paper_figs_teams import plateau_data

    ks, vote, cover, indep, n = plateau_data()
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(width, 1.18))
        ax = fig.add_axes([0.20, 0.25, 0.77, 0.70])
        ax.plot(ks, indep, "--", color=GREY, lw=0.9)
        ax.plot(ks, cover, "-o", color=GPT, ms=2.4, lw=1.1)
        ax.plot(ks, vote, "-o", color=BLUE, ms=2.4, lw=1.1)
        ax.text(6.05, indep[-1] + 1, "independent", fontsize=5.4, color=GREY, ha="right", va="bottom")
        ax.text(6.05, cover[-1] - 3, "one right", fontsize=5.4, color=GPT, ha="right", va="top")
        ax.text(6.05, vote[-1] - 3, "vote", fontsize=5.4, color=BLUE, ha="right", va="top")
        ax.set_xticks(ks)
        ax.set_ylim(30, 100)
        ax.set_yticks([40, 70, 100])
        ax.set_yticklabels(["40%", "70%", "100%"])
        ax.tick_params(labelsize=5.6)
        ax.set_xlabel("proposers k", fontsize=5.8, labelpad=1)
        return svg_of(fig)


def chart_lab(N, teams, panel, width: float) -> str:
    """LAB-Bench test: accuracy against cents per question (log) for single models, team methods and the panel."""
    names = {"Claude": {"single_A": "Haiku", "single_B": "Sonnet low", "single_C": "Sonnet med"},
             "GPT": {"single_A": "Luna", "single_B": "Sol low", "single_C": "Sol med"}}
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(width, 2.06))
        ax = fig.add_axes([0.14, 0.18, 0.83, 0.78])
        for team, color in (("Claude", CLAUDE), ("GPT", GPT)):
            s = teams[team]
            singles = s.loc[["single_A", "single_B", "single_C"]]
            methods = s.loc[["vote", "all_reflect", "fixed_peer", "full_review", "policy"]]
            ax.scatter(100 * singles["usd_per_item"], 100 * singles["accuracy"], marker="o", s=18, facecolor="white",
                       edgecolor=color, lw=1.2, zorder=3, label=f"{team}: one model")
            ax.scatter(100 * methods["usd_per_item"], 100 * methods["accuracy"], marker="s", s=14, color=color,
                       zorder=3, label=f"{team}: team of three")
            for m, off in (("single_A", (4, -7)), ("single_B", (-4, 2.5))):
                ax.annotate(names[team][m], (100 * s.loc[m, "usd_per_item"], 100 * s.loc[m, "accuracy"]),
                            xytext=off, textcoords="offset points", fontsize=6.0, color=color, va="bottom",
                            ha="left" if off[0] > 0 else "right")
        ax.scatter([100 * panel["usd_per_item"]], [100 * panel["accuracy"]], marker="*", s=60, color=BLUE,
                   edgecolor="white", lw=0.4, zorder=4, label="Claude + GPT panel")
        sol = teams["GPT"].loc["single_B"]
        ax.axhline(100 * sol["accuracy"], color=GPT, lw=0.6, ls=":", zorder=1)
        ax.set_xscale("log")
        ax.set_xticks([0.05, 0.1, 0.3, 1, 3])
        ax.set_xticklabels(["0.05¢", "0.1¢", "0.3¢", "1¢", "3¢"])
        ax.minorticks_off()
        ax.set_ylim(60, 92)
        ax.set_yticks([60, 70, 80, 90])
        ax.set_yticklabels(["60%", "70%", "80%", "90%"])
        ax.set_xlabel("cents per question (log scale)", fontsize=6.2, labelpad=2)
        ax.set_ylabel(f"accuracy, {N['lab.items']:.0f} test questions", fontsize=6.2, labelpad=2)
        ax.legend(loc="lower right", fontsize=5.6, handletextpad=0.2, borderaxespad=0.1, labelspacing=0.25,
                  markerscale=0.9)
        return svg_of(fig)


def chart_trajectory(case: dict, width: float) -> str:
    """One case: the validation score after each executed recovery step against CPU seconds, per method."""
    names = {"fixed": ("fixed takeover", GREY), "llm": ("LLM-chosen", BLUE), "full": ("PHOENIX full", ORANGE)}
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(width, 1.16))
        ax = fig.add_axes([0.12, 0.27, 0.60, 0.68])
        ends = []
        for pol in ("fixed", "llm", "full"):
            pts = [(0.0, case[pol]["pts"][0][1])] + case[pol]["pts"]
            xs, ys = zip(*pts)
            label, color = names[pol]
            ax.step(xs, ys, where="post", color=color, lw=1.4 if pol != "fixed" else 1.2, zorder=3 if pol != "fixed" else 2)
            ax.plot([xs[-1]], [ys[-1]], "o", ms=3.4, color=color, zorder=4)
            ends.append((ys[-1], pol, label, color))
        ends.sort(key=lambda e: (-e[0], ["full", "llm", "fixed"].index(e[1])))
        for i, (v, pol, label, color) in enumerate(ends):
            ax.text(1.03, 1.02 - 0.34 * i, f"{label}\n{v:.3f} · ${case[pol]['usd']:.2f}",
                    transform=ax.transAxes, fontsize=5.6, color=color, va="top", linespacing=1.1)
        ax.set_xlim(0, 120)
        ax.set_xticks([0, 30, 60, 90, 120])
        ax.set_ylim(0.60, 0.72)
        ax.set_yticks([0.60, 0.64, 0.68, 0.72])
        ax.tick_params(labelsize=5.8)
        ax.set_xlabel("CPU seconds spent on recovery", fontsize=5.9, labelpad=1)
        ax.set_ylabel("validation", fontsize=5.9, labelpad=1)
        return svg_of(fig)


def chart_phx_forest(N, width: float) -> str:
    """PHOENIX, sealed test: paired differences in balanced-accuracy points (95% interval)."""
    rows = [("Rule alone (Luna plans): full − fixed", "phx.main", "conf"),
            ("Opus plans every step − fixed", "phx.planner", "desc"),
            ("Opus: full − LLM-chosen", "phx.rule", "conf"),
            ("Opus: full − fixed", "phx.claude", "conf"),
            ("Sol: full − fixed", "phx.gpt", "conf")]
    style = {"conf": (ORANGE, ORANGE), "desc": (GREY, "white")}
    with plt.rc_context(RC):
        fig = plt.figure(figsize=(width, 1.08))
        ax = fig.add_axes([0.47, 0.28, 0.50, 0.68])
        for i, (label, key, kind) in enumerate(rows):
            line, face = style[kind]
            ax.plot([100 * N[key + ".lo"], 100 * N[key + ".hi"]], [i, i], color=line, lw=1.8, solid_capstyle="round")
            ax.plot([100 * N[key]], [i], "o", ms=4.2, mfc=face, mec=line, mew=1.2)
        ax.axvline(0, color=INK, lw=0.7)
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels([r[0] for r in rows], fontsize=5.8, color=INK)
        ax.set_ylim(len(rows) - 0.5, -0.6)
        ax.tick_params(axis="y", length=0, pad=2)
        ax.tick_params(axis="x", labelsize=5.8)
        ax.set_xlim(-1, 2)
        ax.set_xticks([-1, 0, 1, 2])
        ax.set_xticklabels(["−1", "0", "+1", "+2"])
        ax.grid(axis="y", visible=False)
        ax.spines["left"].set_visible(False)
        ax.set_xlabel("test balanced-accuracy points (95% interval)", fontsize=5.9, labelpad=1)
        return svg_of(fig)


# ---------------------------------------------------------------------------------------------------------- HTML

CSS = """
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: #fff; }
body { width: 6.75in; font-family: Inter, "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 6.6pt;
       line-height: 1.3; color: #202024; -webkit-print-color-adjust: exact; print-color-adjust: exact; }
#fig { width: 6.75in; padding: 1px; }
.frame { border: 1.2px dashed #6c6c72; border-radius: 11px; padding: 6px 4px 6px; }
.cols { display: grid; }
.col { min-width: 0; padding: 0 7px; display: flex; flex-direction: column; gap: 4.5px; }
.col + .col { border-left: 1px dashed #b7b7bc; }
.step { align-self: center; display: flex; align-items: center; gap: 5px; font-weight: 600; font-size: 8.3pt;
        color: #c9581a; padding: 0 3px 2.5px; border-bottom: 1.3px solid #e8742a; margin-bottom: 1.5px;
        white-space: nowrap; }
.step i { font-style: normal; width: 12.5px; height: 12.5px; border-radius: 50%; background: #e8742a; color: #fff;
          font-size: 6.8pt; font-weight: 700; display: inline-grid; place-items: center; }
.box { border: 1px solid #c4c4c0; background: #f2f2f0; border-radius: 6px; padding: 3px 6px; }
.pink { background: #fbe5e8; border-color: #e3899a; } .pink b { color: #c3364f; }
.blue { background: #e6eefa; border-color: #86a6dc; } .blue b { color: #2c5fbf; }
.green { background: #e6f2e0; border-color: #8cbf72; } .green b { color: #3a7f27; }
.yellow { background: #fdf5da; border-color: #e3b84a; } .yellow b { color: #9a6a00; }
.grey { background: #f1f1ef; border-color: #c4c4c0; }
.orange { background: #fdeee3; border-color: #ec9e6b; } .orange b { color: #c9581a; }
.claude { background: #faece6; border-color: #dc9a80; } .claude b { color: #b0502f; }
.gpt { background: #e3f4ee; border-color: #77c4a9; } .gpt b { color: #0b7d61; }
.group { border: 1.1px dashed #9a74d1; border-radius: 8px; padding: 4px 5px; display: flex; flex-direction: column;
         gap: 3.5px; }
.group.blue-d { border-color: #6d95d6; } .group.green-d { border-color: #79b25f; }
.h { font-weight: 600; font-size: 7pt; text-align: center; }
.c { text-align: center; }
.dim { color: #7d7d84; }
.small { font-size: 6pt; }
.mono { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 6pt; }
.tag { font-family: "JetBrains Mono", "DejaVu Sans Mono", monospace; font-size: 5.6pt; letter-spacing: .05em;
       color: #7d7d84; }
.arrow { display: flex; justify-content: center; margin: -1px 0; }
.bubble { background: #fdebd3; border-radius: 10px; padding: 3.5px 7px; text-align: center; position: relative; }
.lever { display: grid; grid-template-columns: 0.62in 1fr; gap: 6px; align-items: center; }
.lever svg { width: 100%; height: auto; display: block; }
.lever .t b { font-size: 6.9pt; }
.dl { color: #6a6a71; font-size: 6pt; }
.note { background: #f4f4f2; border: 1px solid #d6d6d2; border-radius: 7px; padding: 3.5px 7px; margin: 6px 3px 0;
        color: #36363c; }
.chip { display: inline-block; border: 1px solid; border-radius: 9px; padding: 0.3px 6px; font-size: 6.1pt;
        margin: 1.2px 1.5px; white-space: nowrap; }
.chip.pre { border-color: #79b25f; background: #edf6e8; } .chip.exp { border-color: #e9a04f; background: #fdf1e3; }
.legend { display: flex; flex-wrap: wrap; gap: 3px 9px; justify-content: center; font-size: 6pt; color: #4b4b52; }
.legend span { display: inline-flex; align-items: center; gap: 3px; }
.dot { width: 7px; height: 7px; border-radius: 50%; display: inline-block; border: 1.4px solid; }
.stats { display: grid; grid-template-columns: repeat(3, 1fr); gap: 3px 4px; }
.stat { border-top: 1.2px solid #202024; padding-top: 1.5px; }
.stat .v { font-weight: 600; font-size: 7.6pt; } .stat .k { color: #7d7d84; font-size: 5.7pt; }
.chart { display: block; width: 100%; height: auto; }
.ctitle { font-weight: 600; font-size: 6.6pt; text-align: center; color: #36363c; }
.methods { display: flex; flex-direction: column; gap: 5px; }
.m { display: grid; grid-template-columns: 0.42in 1fr; gap: 5px; align-items: center; }
.m svg { width: 100%; height: auto; display: block; }
ol.steps { margin: 0; padding-left: 11px; } ol.steps li { margin: 0 0 1.5px; }
"""

OVERVIEW_COLS = "1.22fr 0.95fr 1.6fr"
PILOT_COLS = "1.5fr 0.82fr 1.42fr"
LAB_COLS = "0.92fr 1.22fr 1.48fr"
PHX_COLS = "1.0fr 1.1fr 1.5fr"


def fr(cols: str) -> list[float]:
    """Grid column fractions from a CSS grid-template-columns string such as "1fr 0.9fr 1.7fr"."""
    return [float(c.rstrip("fr")) for c in cols.split()]


ARROW = ('<div class="arrow"><svg width="10" height="9" viewBox="0 0 10 9"><path d="M5 0.5v6.5M1.6 4.6 5 8l3.4-3.4" '
         'stroke="#55555b" stroke-width="1.1" fill="none" stroke-linecap="round"/></svg></div>')


FONT_FACES = ""  # set by truetype_fonts(): @font-face rules that point "Inter" at TrueType copies


def page(body: str) -> str:
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{FONT_FACES}{CSS}</style></head><body>'
            f'<div id="fig">{body}</div></body></html>')


def step(n: int, text: str) -> str:
    return f'<div class="step"><i>{n}</i>{text}</div>'


def lever_svgs() -> dict:
    """Small schematics of the three levers (width, depth, checking)."""
    node = 'fill="#fff" stroke="#202024" stroke-width="1.3"'
    width = (f'<svg viewBox="0 0 60 34"><g {node}><circle cx="9" cy="10" r="6"/><circle cx="25" cy="10" r="6"/>'
             f'<circle cx="41" cy="10" r="6"/></g><path d="M9 16 L25 27 M25 16 V27 M41 16 L25 27" stroke="#9a9aa0" '
             f'stroke-width="0.9" fill="none"/><rect x="17" y="26" width="16" height="7" rx="2" fill="#e6eefa" '
             f'stroke="#4a7bd6" stroke-width="0.9"/><text x="25" y="31.9" font-size="6" text-anchor="middle" '
             f'fill="#2c5fbf" font-family="Inter">vote</text></svg>')
    depth = (f'<svg viewBox="0 0 60 34"><circle cx="8" cy="15" r="6" {node}/><rect x="17" y="12" width="41" height="6" '
             f'rx="2" fill="#e7e7e3"/><rect x="17" y="12" width="41" height="6" rx="2" fill="#4a7bd6"/>'
             f'<text x="1" y="29" font-size="6.6" fill="#4b4b52" font-family="Inter">reasoning tokens</text></svg>')
    check = ('<svg viewBox="0 0 60 34"><g stroke-width="0.8"><rect x="4" y="3" width="12" height="7" rx="2" '
             'fill="#c9c9cd"/><rect x="4" y="13.5" width="12" height="7" rx="2" fill="#3fae6a"/>'
             '<rect x="4" y="24" width="12" height="7" rx="2" fill="#c9c9cd"/></g>'
             '<path d="M17 17 H33" stroke="#3fae6a" stroke-width="1.1"/><path d="M30 14.2 33.5 17 30 19.8" '
             'stroke="#3fae6a" stroke-width="1.1" fill="none"/><line x1="37" y1="3" x2="37" y2="31" stroke="#202024" '
             'stroke-width="1.6"/><text x="40" y="19.5" font-size="6.6" fill="#4b4b52" font-family="Inter">judge</text>'
             '</svg>')
    return {"width": width, "depth": depth, "check": check}


def html_overview(N, forest_svg: str) -> str:
    """Figure 1: the three levers, how every comparison runs, and the collective minus its best alternative."""
    L = lever_svgs()
    levers = "".join(
        f'<div class="box grey lever">{svg}<div class="t"><span class="tag">{tag}</span> <b>{head}</b> {text}'
        f'<div class="dl"><i>Deep learning:</i> {dl}</div></div></div>'
        for tag, head, svg, text, dl in (
            ("WIDTH", "More calls.", L["width"], "Several copies or models; a vote combines them.",
             "ensembles, channels (pruning)."),
            ("DEPTH", "More thinking.", L["depth"], "One call reasons longer, or a stronger model answers.",
             "bit width, model size (quantization)."),
            ("CHECKING", "A verifier picks.", L["check"], "A judge, self-check or test chooses a candidate.",
             "re-ranking, early exit.")))
    run = (f'<div class="bubble">A held-out question: a BBEH puzzle, research math or LAB-Bench biology</div>{ARROW}'
           f'<div class="group"><div class="h">Both sides, same questions</div>'
           f'<div class="box pink"><b>Collective.</b> e.g. a vote of 3 Luna copies, reasoning off</div>'
           f'<div class="box blue"><b>Best alternative.</b> e.g. 1 Luna call, reasoning on, about the same '
           f'dollars</div></div>{ARROW}'
           f'<div class="box green"><b>Exact match.</b> Each reply ends <span class="mono">ANSWER: …</span>, which '
           f'must match the key. Every call is stored and priced at list price.</div>')
    measure = (f'{forest_svg}<div class="legend">'
               f'<span><i class="dot" style="background:{ORANGE};border-color:{ORANGE}"></i>confirmatory</span>'
               f'<span><i class="dot" style="border-color:{GREY}"></i>descriptive</span>'
               f'<span><i class="dot" style="border-color:{BLUE}"></i>preregistered, not supported</span></div>'
               f'<div class="dim small c">deep: reasoning on; copies: reasoning off; read all: each member reads both '
               f'teammates, then the team votes</div>')
    note = ('<div class="note"><b>Evidence in this paper.</b> '
            f'<span class="chip exp">Pilot: 19 Haiku agents, {N["pilot.items"]:.0f} BBEH questions</span>'
            '<span class="chip exp">Atlas: public leaderboards</span>'
            f'<span class="chip pre">Anchor: depth against width, {N["anchor.items.all"]:.0f} sealed questions</span>'
            f'<span class="chip pre">LAB-Bench teams, {N["lab.items"]:.0f} test questions</span>'
            f'<span class="chip pre">PHOENIX recovery, {N["phx.recoveries"]:.0f} sealed recoveries</span>'
            ' <span class="dim">green: preregistered; orange: exploratory or post hoc</span></div>')
    body = (f'<div class="frame"><div class="cols" style="grid-template-columns: {OVERVIEW_COLS}">'
            f'<div class="col">{step(1, "Three ways to spend")}{levers}</div>'
            f'<div class="col">{step(2, "Run both sides")}{run}</div>'
            f'<div class="col">{step(3, "The collective minus its best alternative")}{measure}</div>'
            f'</div>{note}</div>')
    return page(body)


def network_svg() -> str:
    """The pilot's dense team: question, six proposers, six critics, six refiners, one aggregator, answer."""
    X = {"q": 13, "p": 66, "c": 126, "r": 186, "g": 240, "a": 281}
    ys = [9 + 16.5 * i for i in range(6)]
    mid = (ys[0] + ys[-1]) / 2
    edges = [(X["q"], mid, X["p"], y) for y in ys]
    edges += [(X["p"], a, X["c"], b) for a in ys for b in ys] + [(X["c"], a, X["r"], b) for a in ys for b in ys]
    edges += [(X["r"], y, X["g"], mid) for y in ys] + [(X["g"], mid, X["a"], mid)]
    out = ['<svg viewBox="0 0 294 134" class="chart">']
    out += [f'<line x1="{a}" y1="{b}" x2="{c}" y2="{d}" stroke="#cacacf" stroke-width="0.45"/>' for a, b, c, d in edges]
    for key in ("p", "c", "r"):
        out += [f'<circle cx="{X[key]}" cy="{y}" r="6" fill="#fff" stroke="#202024" stroke-width="1.2"/>' for y in ys]
    out.append(f'<circle cx="{X["g"]}" cy="{mid}" r="8" fill="#202024"/>')
    for key, t in (("q", "Q"), ("a", "A")):
        out.append(f'<rect x="{X[key] - 10}" y="{mid - 10}" width="20" height="20" rx="4" fill="#e6eefa" '
                   f'stroke="#4a7bd6" stroke-width="1.1"/><text x="{X[key]}" y="{mid + 3.8}" font-size="10.5" '
                   f'text-anchor="middle" fill="#2c5fbf" font-family="Inter" font-weight="600">{t}</text>')
    for key, t in (("p", "Propose"), ("c", "Critique"), ("r", "Refine"), ("g", "Aggregate")):
        out.append(f'<text x="{X[key]}" y="110" font-size="11" text-anchor="middle" fill="#202024" '
                   f'font-family="Inter">{t}</text>')
    for key in ("p", "c", "r"):
        out.append(f'<rect x="{X[key] - 28}" y="116" width="56" height="16" rx="8" fill="#fbe5e8" stroke="#e3899a" '
                   f'stroke-width="0.8"/><text x="{X[key]}" y="127.6" font-size="10" text-anchor="middle" '
                   f'fill="#c3364f" font-family="Inter">keep 1, 3, 6</text>')
    out.append("</svg>")
    return "".join(out)


def html_pilot(N, g: pd.DataFrame, scatter_svg: str, plateau_svg: str) -> str:
    """Figure: the pilot. The 19-agent team, how it is pruned and scored, and the 27 teams against one Sonnet call."""
    full = g[g["config_id"] == "k6-6-6-1"].iloc[0]
    build = (f'{network_svg()}'
             f'<div class="box grey">{int(full["calls"])} Claude Haiku 5.5 agents. Six proposers answer, six critics '
             f'read all six answers, six refiners read every critique, one aggregator answers.</div>'
             f'<div class="box pink"><b>Prune.</b> Keep the first 1, 3 or 6 agents of each middle stage: '
             f'{len(g)} teams of {int(g["calls"].min())} to {int(g["calls"].max())} calls, each against one Sonnet '
             f'5.5 call with thinking off.</div>')
    score = (f'<div class="ctitle">The full team</div><div class="stats">'
             f'<div class="stat"><div class="v">{r1(100 * full["acc"])}%</div><div class="k">accuracy</div></div>'
             f'<div class="stat"><div class="v">${full["usd"]:.4f}</div><div class="k">per question</div></div>'
             f'<div class="stat"><div class="v">{int(full["calls"])}</div><div class="k">calls</div></div>'
             f'<div class="stat"><div class="v">{full["cp"]:.0f} s</div><div class="k">slowest path</div></div>'
             f'<div class="stat"><div class="v">{full["peak"] / 1000:.1f}k</div><div class="k">peak context</div></div>'
             f'<div class="stat"><div class="v">{r1(N["pilot.neff"])}</div><div class="k">effective proposers</div>'
             f'</div></div>'
             f'<div class="ctitle">Six proposers act like {r1(N["pilot.neff"])}</div>{plateau_svg}')
    measure = (f'<div class="ctitle">Each dot is one team on the same {int(full["n"])} questions</div>{scatter_svg}'
               f'<div class="dim small c">Dashed: teams no other team beats on both cost and accuracy.</div>')
    body = (f'<div class="frame"><div class="cols" style="grid-template-columns: {PILOT_COLS}">'
            f'<div class="col">{step(1, "Build and prune a team")}{build}</div>'
            f'<div class="col">{step(2, "Score the full team")}{score}</div>'
            f'<div class="col">{step(3, f"{len(g)} teams: cost against accuracy")}{measure}</div>'
            f'</div></div>')
    return page(body)


def method_glyph(kind: str) -> str:
    """Three members (circles) and what round 2 does with their first answers."""
    c = [(9, 13), (25, 13), (41, 13)]

    def node(x, y, col="#202024"):
        return f'<circle cx="{x}" cy="{y}" r="5" fill="#fff" stroke="{col}" stroke-width="1.1"/>'

    arr = 'stroke="#4a7bd6" stroke-width="0.9" fill="none" marker-end="url(#ah)"'
    defs = ('<defs><marker id="ah" viewBox="0 0 6 6" refX="5" refY="3" markerWidth="4" markerHeight="4" '
            'orient="auto"><path d="M0 0 6 3 0 6z" fill="#4a7bd6"/></marker></defs>')
    if kind == "vote":
        extra = ('<path d="M9 18 L25 26 M25 18 V26 M41 18 L25 26" stroke="#9a9aa0" stroke-width="0.8"/>'
                 '<rect x="19" y="25" width="12" height="5" rx="1.5" fill="#202024"/>')
    elif kind == "reflect":
        extra = "".join(f'<path d="M{x - 3.5} {y - 4} A4 3.5 0 1 1 {x + 3.5} {y - 4}" {arr}/>' for x, y in c)
    elif kind == "peer":
        extra = (f'<path d="M14 11 Q25 3 37 11" {arr}/><path d="M36 15.5 L14 15.5" {arr}/>'
                 f'<path d="M22 17 Q17 24 12 18" {arr}/>')
    elif kind == "review":
        extra = (f'<path d="M14 10 Q25 1 36 10" {arr}/><path d="M36 16 Q25 25 14 16" {arr}/>'
                 f'<path d="M14 13 L20 13" {arr}/><path d="M36 13 L30 13" {arr}/>')
    elif kind == "rule":
        extra = ('<path d="M25 22 L30 27 L25 32 L20 27 Z" fill="#fdf5da" stroke="#e3b84a" stroke-width="0.9"/>'
                 '<path d="M9 18 L22 25 M25 18 V22 M41 18 L28 25" stroke="#e3b84a" stroke-width="0.8"/>')
    else:  # a panel of two providers' members
        return (f'<svg viewBox="0 0 50 34">{node(9, 13, CLAUDE)}{node(25, 13, GPT)}{node(41, 13, GPT)}'
                '<path d="M9 18 L25 26 M25 18 V26 M41 18 L25 26" stroke="#9a9aa0" stroke-width="0.8"/>'
                '<rect x="19" y="25" width="12" height="5" rx="1.5" fill="#4a7bd6"/></svg>')
    return f'<svg viewBox="0 0 50 34">{defs}{"".join(node(x, y) for x, y in c)}{extra}</svg>'


def html_lab(N, teams, panel, subsets, chart_svg: str) -> str:
    """Figure: the LAB-Bench team study. Two teams, the round-2 methods, and accuracy against cost."""
    claude, gpt = teams["Claude"], teams["GPT"]
    field = (f'<div class="bubble">LAB-Bench biology, multiple choice: {subsets["seqqa"]} DNA-sequence and '
             f'{subsets["protocolqa"]} protocol questions</div>{ARROW}'
             f'<div class="box claude"><b>Claude team.</b> Haiku 5.5 low; Sonnet 5.5 low and medium</div>'
             f'<div class="box gpt"><b>GPT team.</b> GPT-6 Luna low; GPT-6.1 Sol low and medium</div>{ARROW}'
             f'<div class="box grey"><b>Round 1.</b> Each member answers alone; the answers are frozen. '
             f'<b>Final answer:</b> a plurality vote of the members\' final answers.</div>')
    rows = [("vote", "<b>Vote</b> the first answers; no round 2."),
            ("reflect", "<b>Think again alone.</b>"),
            ("peer", "<b>Ask the best teammate</b> (picked on practice questions)."),
            ("review", "<b>Read both teammates</b>, then revise."),
            ("rule", "<b>Learned rule:</b> stop, think again or ask one teammate, per member; fitted on practice "
                     "questions and frozen."),
            ("panel", "<b>Claude + GPT panel:</b> vote of Sonnet low, Luna low and Sol medium; replayed for $0.")]
    methods = "".join(f'<div class="m">{method_glyph(k)}<div>{t}</div></div>' for k, t in rows)
    coord = (f'<div class="group blue-d"><div class="methods">{methods}</div></div>'
             f'<div class="box yellow"><b>Preregistered.</b> The rule: cheaper than everyone thinking again and at '
             f'most 3 points less accurate. The panel: above both providers\' own votes.</div>')
    sol, best = gpt.loc["single_B"], claude.loc["fixed_peer"]
    measure = (f'{chart_svg}<div class="box grey small"><b>One Sol low call</b> scored {r1(100 * sol["accuracy"])}% '
               f'at {r1(100 * sol["usd_per_item"], 2)}¢ a question (dotted line); the best Claude team '
               f'{r1(100 * best["accuracy"])}% at {r1(100 * best["usd_per_item"], 1)}¢. The panel scored '
               f'{r1(100 * panel["accuracy"])}%, {signed(100 * N["lab.mix.gpt"])} points against GPT\'s own vote.</div>')
    body = (f'<div class="frame"><div class="cols" style="grid-template-columns: {LAB_COLS}">'
            f'<div class="col">{step(1, "Field a team of three")}{field}</div>'
            f'<div class="col">{step(2, "Round 2: use the teammates?")}{coord}</div>'
            f'<div class="col">{step(3, f"Score {N["lab.items"]:.0f} test questions once")}{measure}</div>'
            f'</div></div>')
    return page(body)


def workflow_svg() -> str:
    """A science table, three agents building pipelines, one agent lost (fault F1), the best predictor sealed."""
    t = 'font-family="Inter" text-anchor="middle"'
    out = ['<svg viewBox="0 0 196 100" class="chart">']
    out.append('<rect x="3" y="30" width="30" height="28" rx="3" fill="#fff" stroke="#202024" stroke-width="1"/>')
    for i in range(1, 4):
        out.append(f'<line x1="3" y1="{30 + 7 * i}" x2="33" y2="{30 + 7 * i}" stroke="#bdbdc2" stroke-width="0.6"/>')
    for x in (13, 23):
        out.append(f'<line x1="{x}" y1="30" x2="{x}" y2="58" stroke="#bdbdc2" stroke-width="0.6"/>')
    out.append(f'<text x="18" y="70" font-size="8.6" fill="#4b4b52" {t}>table</text>')
    agents = [(60, 17, "A"), (60, 44, "B"), (60, 71, "C")]
    for x, y, _ in agents:
        out.append(f'<line x1="34" y1="44" x2="{x - 9}" y2="{y}" stroke="#bdbdc2" stroke-width="0.7"/>')
    pipes = [(92, 6), (92, 23), (92, 40), (92, 57), (92, 74)]
    for a, p in [(0, 0), (0, 1), (1, 2), (1, 3), (2, 4)]:
        lost = a == 1
        dash = ' stroke-dasharray="2 1.5"' if lost else ""
        out.append(f'<line x1="{agents[a][0] + 9}" y1="{agents[a][1]}" x2="92" y2="{pipes[p][1] + 6}" '
                   f'stroke="{"#e3899a" if lost else "#9a9aa0"}" stroke-width="0.8"{dash}/>')
    for x, y, name in agents:
        lost = name == "B"
        out.append(f'<circle cx="{x}" cy="{y}" r="9" fill="{"#fbe5e8" if lost else "#fff"}" '
                   f'stroke="{"#c3364f" if lost else "#202024"}" stroke-width="1.2"/>')
        if lost:
            out.append(f'<path d="M{x - 5.5} {y - 5.5} L{x + 5.5} {y + 5.5} M{x + 5.5} {y - 5.5} L{x - 5.5} {y + 5.5}" '
                       f'stroke="#c3364f" stroke-width="1.8" stroke-linecap="round"/>')
        else:
            out.append(f'<text x="{x}" y="{y + 3.2}" font-size="9" fill="#202024" font-weight="600" {t}>{name}</text>')
    for i, (x, y) in enumerate(pipes):
        lost = i in (2, 3)
        dash = ' stroke-dasharray="2 1.5"' if lost else ""
        out.append(f'<rect x="{x}" y="{y}" width="44" height="12" rx="3" fill="{"#fff" if lost else "#e6eefa"}" '
                   f'stroke="{"#e3899a" if lost else "#86a6dc"}" stroke-width="0.8"{dash}/>'
                   f'<text x="{x + 22}" y="{y + 8.8}" font-size="8" fill="{"#c3364f" if lost else "#2c5fbf"}" {t}>'
                   f'{"pending" if lost else "pipeline"}</text>')
        out.append(f'<line x1="{x + 44}" y1="{y + 6}" x2="148" y2="44" stroke="#bdbdc2" stroke-width="0.6"/>')
    out.append(f'<rect x="148" y="31" width="45" height="26" rx="4" fill="#e6f2e0" stroke="#8cbf72" stroke-width="0.9"/>'
               f'<text x="170.5" y="42" font-size="8" fill="#3a7f27" {t}>best</text>'
               f'<text x="170.5" y="51.5" font-size="8" fill="#3a7f27" {t}>predictor</text>')
    out.append(f'<text x="60" y="95" font-size="8.4" fill="#c3364f" {t}>member B lost</text>')
    out.append("</svg>")
    return "".join(out)


def html_phoenix(N, caps: dict, traj_svg: str, forest_svg: str) -> str:
    """Figure: PHOENIX. The workflow and the fault, the three recoveries under equal caps, and what was measured."""
    task = (f'<div class="bubble">A public science table: forest cover type, MiniBooNE neutrino events or HIGGS '
            f'collider events</div>{ARROW}{workflow_svg()}'
            f'<div class="box grey">Three agents build classifier pipelines (prepare, fit, predict, validate). '
            f'Halfway, one is shut down and its model withdrawn (fault F1). {N["phx.cases"]:.0f} cases: 3 tables × '
            f'2 workflow templates × 3 seeds.</div>')
    recover = ('<div class="box grey"><b>Fixed takeover.</b> The next model in line redoes the missing work.</div>'
               '<div class="box blue"><b>LLM-chosen.</b> A planner model picks each step: keep, verify, recompute, '
               'reroute or stop.</div>'
               '<div class="box orange"><b>PHOENIX full.</b> The planner proposes plans; a search prices each in '
               'dollars and CPU along the dependencies, reuses valid results, and runs the plan with the most expected '
               'gain per unit of budget.</div>'
               f'<div class="box yellow"><b>Equal caps per recovery:</b> ${caps["main_usd"]:.2f} (main study) or '
               f'${caps["arm_usd"]:.2f} (arms) of API, {caps["calls"]} model calls, {caps["tools"]} tool runs, '
               f'{caps["cpu"]:.0f} CPU s. <b>Planner:</b> GPT-6 Luna (main); Claude Opus 5.5 or GPT-6.1 Sol (arms, '
               f'two draws per case).</div>')
    measure = (f'<div class="ctitle">While recovering: one HIGGS case, Opus planning</div>{traj_svg}'
               f'<div class="ctitle">Sealed test, scored once: {N["phx.recoveries"]:.0f} recoveries, paired by case'
               f'</div>{forest_svg}')
    body = (f'<div class="frame"><div class="cols" style="grid-template-columns: {PHX_COLS}">'
            f'<div class="col">{step(1, "A team loses a member")}{task}</div>'
            f'<div class="col">{step(2, "Recover three ways")}{recover}</div>'
            f'<div class="col">{step(3, "Validation, then a sealed test")}{measure}</div>'
            f'</div></div>')
    return page(body)


# -------------------------------------------------------------------------------------------------------- printing

INTER = Path("/usr/share/fonts/opentype/inter")
INTER_FACES = (("Inter-Regular", 400, "normal"), ("Inter-Italic", 400, "italic"), ("Inter-SemiBold", 600, "normal"),
               ("Inter-Bold", 700, "normal"))


def otf_to_ttf(src: Path, dst: Path) -> None:
    """Convert a CFF-flavoured OpenType font to TrueType outlines (fontTools' otf2ttf recipe). Chromium embeds CFF
    fonts in a PDF as Type 3 glyphs, which publishers' PDF checks reject; TrueType fonts embed as TrueType."""
    from fontTools.pens.cu2quPen import Cu2QuPen
    from fontTools.pens.ttGlyphPen import TTGlyphPen
    from fontTools.ttLib import TTFont, newTable

    font = TTFont(str(src))
    order = font.getGlyphOrder()
    glyphs = font.getGlyphSet()
    quad = {}
    for name in glyphs.keys():
        pen = TTGlyphPen(glyphs)
        glyphs[name].draw(Cu2QuPen(pen, 1.0, reverse_direction=True))
        quad[name] = pen.glyph()
    font["loca"] = newTable("loca")
    font["glyf"] = glyf = newTable("glyf")
    glyf.glyphOrder = order
    glyf.glyphs = quad
    del font["CFF "]
    if "VORG" in font:
        del font["VORG"]
    glyf.compile(font)
    hmtx = font["hmtx"]
    for name, g in glyf.glyphs.items():
        if hasattr(g, "xMin"):
            hmtx[name] = (hmtx[name][0], g.xMin)
    font["maxp"] = maxp = newTable("maxp")
    maxp.tableVersion = 0x00010000
    for field in ("maxZones",):
        setattr(maxp, field, 1)
    for field in ("maxTwilightPoints", "maxStorage", "maxFunctionDefs", "maxInstructionDefs", "maxStackElements",
                  "maxSizeOfInstructions"):
        setattr(maxp, field, 0)
    maxp.maxComponentElements = max(len(getattr(g, "components", []) or []) for g in glyf.glyphs.values())
    maxp.compile(font)
    post = font["post"]
    post.formatType, post.extraNames, post.mapping, post.glyphOrder = 2.0, [], {}, order
    font.sfntVersion = "\000\001\000\000"
    font.save(str(dst))


def truetype_fonts(workdir: Path) -> str:
    """@font-face rules naming TrueType copies of Inter (made in workdir) "Inter"; empty when Inter is not
    installed, in which case the figures fall back to the browser's sans-serif."""
    rules = []
    for name, weight, style in INTER_FACES:
        src = INTER / f"{name}.otf"
        if not src.exists():
            return ""
        dst = workdir / f"{name}.ttf"
        if not dst.exists():
            otf_to_ttf(src, dst)
        rules.append(f'@font-face {{ font-family: "Inter"; src: url("{dst.as_uri()}") format("truetype"); '
                     f'font-weight: {weight}; font-style: {style}; }}')
    return "\n".join(rules) + "\n"


def col_width(fracs: list[float], i: int) -> float:
    """Approximate width in inches of column i of a figure's grid (frame and column padding removed)."""
    inner = WIDTH_IN - 2 * (1.2 + 4 + 1) / 96
    return inner * fracs[i] / sum(fracs) - 14 / 96


def render(html: str, name: str, workdir: Path) -> Path:
    """Print one figure's HTML to paper/figs/<name>.pdf with Chromium (analysis/print_figure.mjs)."""
    src = workdir / f"{name}.html"
    src.write_text(html)
    OUT.mkdir(parents=True, exist_ok=True)
    out = OUT / f"{name}.pdf"
    node = shutil.which("node")
    if node is None:
        raise SystemExit("node is needed to print the figures (with Playwright's Chromium)")
    subprocess.run([node, str(ROOT / "analysis/print_figure.mjs"), str(src), str(out), str(WIDTH_IN)], check=True)
    return out


def build(N) -> dict:
    """The four figures' HTML, from the numbers N and the committed results."""
    g = pilot_grid()
    teams, panel, subsets = lab_points()
    pc, lc, xc = fr(PILOT_COLS), fr(LAB_COLS), fr(PHX_COLS)
    return {
        "fig_overview": html_overview(N, chart_overview_forest(N, col_width(fr(OVERVIEW_COLS), 2))),
        "fig_pilot": html_pilot(N, g, chart_pilot_scatter(N, g, col_width(pc, 2)), chart_plateau(col_width(pc, 1))),
        "fig_lab_setup": html_lab(N, teams, panel, subsets, chart_lab(N, teams, panel, col_width(lc, 2))),
        "fig_phoenix": html_phoenix(N, phoenix_caps(), chart_trajectory(phoenix_case(), col_width(xc, 2)),
                                    chart_phx_forest(N, col_width(xc, 2))),
    }


def main(keep_html: Path | None = None) -> None:
    from analysis.paper_figs_teams import builder

    global FONT_FACES
    N = builder()
    with tempfile.TemporaryDirectory() as tmp:
        work = keep_html or Path(tmp)
        work.mkdir(parents=True, exist_ok=True)
        FONT_FACES = truetype_fonts(work)
        pages = build(N)
        for name, html in pages.items():
            render(html, name, work)
    print(len(pages), "figures ->", OUT.relative_to(ROOT))


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else None)
