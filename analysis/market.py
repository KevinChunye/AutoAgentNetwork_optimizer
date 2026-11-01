"""Market-town analysis: tables, figures, decision values and the report (reports/market/).

Reads results/<name>/{sessions,periods,traders,trades,turns}.csv written by `aan run` on the market configs
(configs/experiments/market/) and results/market_zic/ for the ZI-C baseline. Every number in
reports/market/report.md is filled from the files this script writes.

Terms (research/market/plan.md, sections 3 and 6):
  condition        zic (random baseline), haiku (M2), mixed (M4: Sonnet on half of each side), sonnet (M3);
                   M1 (smoke) is reported on its own and never pooled with M2
  session CI       95% interval from resampling a condition's sessions with replacement (10,000 draws);
                   a difference between two conditions resamples each one's sessions independently
  period CI        the same over periods; only valid where periods are exchangeable (ZI-C), reported for
                   LLM conditions as "treats periods as independent"
  efficiency       realized surplus / maximum surplus (7.50 per period), in percent
  alpha            Smith's coefficient of convergence, per period (100 x RMS deviation from P* / P*)
  late PASS share  share of turns in rounds 6-8 by traders with a positive CE profit that are PASS
  final spread     best ask - best bid after a period's last turn
  M4 profit gap    pooled Sonnet profit / CE profit - pooled Haiku profit / CE profit, in points

Usage: python -m analysis.market   (writes reports/market/tables, figures, report.html, report.pdf)
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

from autoagentnet.market.metrics import (placebo_gaps, profit_gap, rank_pair_interval, senior_breakdown,
                                         waiting_metrics)
from autoagentnet.market.schedule import Schedule

from . import common

RESULTS = common.ROOT / "results"
REPORT = common.ROOT / "reports" / "market"
TABLES = REPORT / "tables"
FIGURES = REPORT / "figures"
N_BOOT = 10_000
ROUNDS = 8
SENIOR = "sonnet_nothink"
CONDITIONS = {  # condition -> result folders, in Kevin's run order
    "smoke": ["m1_smoke"],
    "haiku": ["m2_haiku"],
    "mixed": ["m4_mixed_odd", "m4_mixed_even"],
    "sonnet": ["m3_sonnet"],
}
LABELS = {"zic": "ZI-C", "smoke": "M1 Haiku smoke", "haiku": "M2 all Haiku", "mixed": "M4 mixed",
          "sonnet": "M3 all Sonnet"}
SHORT = {"ZI-C": "zic", "M1 Haiku smoke": "m1", "M2 all Haiku": "m2", "M4 mixed": "m4", "M3 all Sonnet": "m3",
         "total": "total"}  # value-name prefixes for the report
COLORS = {"zic": "black", "smoke": "sky", "haiku": "blue", "mixed": "green", "sonnet": "vermillion"}
# Published comparison numbers (research/lit/market.md): Struski et al. Table 1 and Smith (1962) Test 1
STRUSKI_GPT_SMALL_EFF = [0.79, 0.86, 0.89, 0.89, 0.91]
STRUSKI_GPT_SMALL_ALPHA = [27.6, 18.2, 12.6, 13.6, 11.7]
SMITH_ALPHA = [11.8, 8.1, 5.2, 5.5, 3.5]


def load(names: list[str], table: str, results: Path = RESULTS) -> pd.DataFrame:
    parts = [pd.read_csv(results / n / f"{table}.csv").assign(run=n) for n in names
             if (results / n / f"{table}.csv").exists()]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


# Preregistered decision values (research/market/plan.md, sections 4 and 7). Fixed numbers, not recomputed from
# the ZI-C file, so the rule cannot drift with a rerun (audit 27, finding 5).
SANE_AT = 85.4  # ZI-C 90.4% - 5 points: LLM markets are sane
WORSE_BELOW = 80.4  # ZI-C 90.4% - 10 points: LLM traders are worse than budget-constrained random traders
PRICE_BAND = 0.15  # period-5 mean price within this many dollars of P*
M3_DROP = 7.0  # M3 holds only if its efficiency is at least this many points below M2's (and it trades less)
M4_BAR = 20.0  # M4 exploitation needs a gap of at least this many points, above every placebo gap
M4_FORMAT_LIMIT = 0.05  # the M4 gap is not interpreted if either model is over 5% unparsed or truncated
EPS = 1e-9  # boundaries are inclusive; floating point must not move a value at the line to the wrong side


def m2_rule(eff_pct: float) -> str:
    if eff_pct >= SANE_AT - EPS:
        return "sane (>= ZI-C - 5)"
    if eff_pct < WORSE_BELOW - EPS:
        return "worse than ZI-C (< ZI-C - 10)"
    return "near ZI-C"


def price_within(last: float, p_star: float = 2.0) -> bool:
    return abs(last - p_star) <= PRICE_BAND + EPS


def m3_holds(eff_diff: float, trades_diff: float) -> bool:
    return eff_diff <= -M3_DROP + EPS and trades_diff < 0


def m4_verdict(gap: float, placebo_max: float, format_ok: bool) -> str:
    """The preregistered M4 reading of the pooled profit gap (points)."""
    if not format_ok:
        return "not interpreted: a model is over 5% unparsed or truncated"
    if gap >= M4_BAR - EPS and gap > placebo_max:
        return "exploitation"
    if gap >= 10 - EPS:
        return "meets the prediction, not distinguishable from label noise"
    return "no exploitation found"


def complete_sessions(sessions: pd.DataFrame) -> pd.DataFrame:
    return sessions[sessions["complete"].astype(bool)] if "complete" in sessions else sessions


def mean_ci(values, n_boot: int = N_BOOT) -> tuple[float, float, float]:
    return common.bootstrap_mean_ci(values, n_boot=n_boot)


T95 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306, 9: 2.262}  # two-sided 95% t


def t_interval(values) -> tuple[float, float]:
    """95% t-interval of the mean. With 2-4 sessions the session bootstrap is too narrow (it never goes
    beyond the observed sessions), so the report shows both (audit 31). Normal value 1.96 from 10 sessions up.
    Not computed for fewer than 3 sessions: at n = 2 it is too wide to mean anything (audit 37)."""
    x = np.asarray(values, float)
    if len(x) < 3:
        return (np.nan, np.nan)
    half = T95.get(len(x) - 1, 1.96) * x.std(ddof=1) / np.sqrt(len(x))
    return (float(x.mean() - half), float(x.mean() + half))


def pooled_t_diff(a, b) -> tuple[float, float]:
    """95% pooled-variance t-interval of mean(a) - mean(b) (two independent sets of sessions; audit 37)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    df = len(a) + len(b) - 2
    if len(a) < 2 or len(b) < 2:
        return (np.nan, np.nan)
    pooled = ((len(a) - 1) * a.var(ddof=1) + (len(b) - 1) * b.var(ddof=1)) / df
    half = T95.get(df, 1.96) * np.sqrt(pooled * (1 / len(a) + 1 / len(b)))
    d = a.mean() - b.mean()
    return (float(d - half), float(d + half))


def same_rank_table(data: dict) -> pd.DataFrame:
    """Each M4 rank against the same rank in all-Haiku M2 (audit 32, finding 5): which ranks a model holds
    changes its raw PASS share and profit, so Sonnet is compared with Haiku on the same seats. Per (role,
    rank): mean session profit and PASS share in M2, in M4 when the seat is Sonnet, and in M4 when it is Haiku."""
    if "mixed" not in data or "haiku" not in data:
        return pd.DataFrame()
    rows = []
    for label, t, model in [("m2", data["haiku"], None), ("m4_sonnet", data["mixed"], SENIOR), ("m4_haiku", data["mixed"], "haiku")]:
        turns, traders = t["turns"], t["traders"]
        if model == SENIOR:
            turns, traders = turns[turns["model"] == SENIOR], traders[traders["model"] == SENIOR]
        elif model == "haiku":
            turns, traders = turns[turns["model"] != SENIOR], traders[traders["model"] != SENIOR]
        passes = turns.assign(passed=turns["outcome"].eq("pass")).groupby(["role", "rank"])["passed"].mean()
        profit = traders.groupby(["role", "rank"])["profit"].mean()
        rows.append(pd.DataFrame({f"{label}_profit": profit, f"{label}_pass": passes}))
    out = pd.concat(rows, axis=1).reset_index()
    out["group"] = np.where(out["rank"] <= Schedule().q_star, "intramarginal", "extramarginal")
    return out


def diff_ci(a, b, n_boot: int = N_BOOT, seed: int = 0) -> tuple[float, float, float]:
    """Mean of a - mean of b, resampling each set independently (sessions of two conditions)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0 or len(b) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    draws = a[rng.integers(0, len(a), (n_boot, len(a)))].mean(1) - b[rng.integers(0, len(b), (n_boot, len(b)))].mean(1)
    return (float(a.mean() - b.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5)))


def gather(results: Path = RESULTS) -> dict[str, dict[str, pd.DataFrame]]:
    """Every condition's tables. A session a stop rule cut short stays in, with the periods it played
    (audit 27, finding 4): a market that stops trading is exactly what the M2 rule has to see."""
    data = {}
    zic_sessions = pd.read_csv(results / "market_zic" / "sessions.csv") if (results / "market_zic").exists() else None
    if zic_sessions is not None:
        data["zic"] = {"sessions": zic_sessions, "periods": pd.read_csv(results / "market_zic" / "periods.csv")}
    for condition, names in CONDITIONS.items():
        sessions = load(names, "sessions", results)
        if sessions.empty:
            continue
        if "periods_planned" in sessions:  # a stopped session's missing periods count as zero surplus (audit 28)
            sessions = sessions.assign(efficiency=sessions["surplus"] / (sessions["periods_planned"] * Schedule().max_surplus))
        seeds = set(sessions["seed"])
        tables = {"sessions": sessions}
        for name in ("periods", "traders", "trades", "turns"):
            frame = load(names, name, results)
            tables[name] = frame[frame["seed"].isin(seeds)] if not frame.empty else frame
        data[condition] = tables
    return data


def condition_table(data: dict) -> pd.DataFrame:
    rows = []
    for condition, t in data.items():
        s, p = t["sessions"], t["periods"]
        eff, lo, hi = mean_ci(100 * s["efficiency"])
        t_lo, t_hi = t_interval(100 * s["efficiency"])
        stopped = int((~s["complete"].astype(bool)).sum()) if "complete" in s else 0
        row = {"condition": LABELS[condition], "sessions": len(s), "stopped": stopped, "efficiency_pct": eff,
               "eff_lo": lo, "eff_hi": hi, "eff_t_lo": t_lo, "eff_t_hi": t_hi,
               "trades_per_period": p["trades"].mean(), "trade_ratio": s["trade_ratio"].mean(),
               "extramarginal_per_period": p["extramarginal"].mean(), "mean_price": p["mean_price"].mean(),
               "last_period_price": p[p["period"] == p["period"].max()]["mean_price"].mean(),
               "alpha_first": p[p["period"] == 1]["alpha"].mean(),
               "alpha_last": p[p["period"] == p["period"].max()]["alpha"].mean(),
               "rejected_rate": s["rejected_rate"].mean(), "unparsed_rate": s["unparsed_rate"].mean(),
               "truncated_rate": s["truncated_rate"].mean(), "turns_per_session": s["turns"].mean(),
               "cost_per_session": s["cost_usd"].mean()}
        if "turns" in t and not t["turns"].empty:
            w = waiting_metrics(t["turns"], Schedule(), ROUNDS)
            row.update(late_pass_share=w["late_pass_share"].mean(), final_spread=w["final_spread"].mean())
        rows.append(row)
    return pd.DataFrame(rows)


def by_period_table(data: dict) -> pd.DataFrame:
    rows = []
    for condition, t in data.items():
        p = t["periods"]
        g = p.groupby("period").agg(efficiency=("efficiency", "mean"), trades=("trades", "mean"),
                                    mean_price=("mean_price", "mean"), alpha=("alpha", "mean"),
                                    extramarginal=("extramarginal", "mean"), sessions=("seed", "nunique"))
        rows.append(g.reset_index().assign(condition=LABELS[condition]))
    out = pd.concat(rows, ignore_index=True) if rows else pd.DataFrame()
    return out[["condition", "period", "sessions", "efficiency", "trades", "mean_price", "alpha", "extramarginal"]]


def session_table(data: dict) -> pd.DataFrame:
    rows = [t["sessions"].assign(condition=LABELS[c]) for c, t in data.items() if c != "zic"]
    if not rows:
        return pd.DataFrame()
    cols = ["condition", "seed", "periods", "trades", "efficiency", "mean_price", "last_period_mean_price",
            "extramarginal", "rejected_rate", "unparsed_rate", "truncated_rate", "turns", "cost_usd"]
    out = pd.concat(rows, ignore_index=True)
    return out[[c for c in cols if c in out]].sort_values(["condition", "seed"])


def m4_tables(data: dict) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """M4 profit by side and model, M2 placebo gaps, and the decision values."""
    if "mixed" not in data:
        return pd.DataFrame(), pd.DataFrame(), {}
    t = data["mixed"]
    traders, trades = t["traders"], t["trades"]
    senior = traders["model"] == SENIOR
    if senior.all() or not senior.any():  # a dry run routes every trader to one model
        return pd.DataFrame(), pd.DataFrame(), {}
    gap = profit_gap(traders, senior)
    lo, hi = rank_pair_interval(traders, senior)
    periods_run = t["sessions"].set_index("seed")["periods"]
    breakdown = senior_breakdown(traders, trades, SENIOR, Schedule().p_star, periods_run)
    by_side = traders.assign(model=np.where(senior, "Sonnet", "Haiku")).groupby(["role", "model"])[
        ["profit", "ce_profit"]].sum().reset_index()
    by_side["profit_share_pct"] = 100 * by_side["profit"] / by_side["ce_profit"]
    total = traders.assign(model=np.where(senior, "Sonnet", "Haiku")).groupby("model")[["profit", "ce_profit"]].sum()
    total = total.reset_index().assign(role="all")
    total["profit_share_pct"] = 100 * total["profit"] / total["ce_profit"]
    by_side = pd.concat([by_side, total], ignore_index=True)
    placebo = pd.DataFrame()
    if "haiku" in data and data["haiku"]["traders"]["seed"].nunique() >= 4:
        placebo = placebo_gaps(data["haiku"]["traders"], per_side=2)
    turns = t["turns"].assign(model=lambda d: np.where(d["model"] == SENIOR, "Sonnet", "Haiku"),
                              unparsed=lambda d: d["outcome"].eq("unparsed"),
                              truncated=lambda d: d["truncated"].fillna(False).astype(bool),
                              passed=lambda d: d["outcome"].eq("pass"),
                              order=lambda d: d["action"].isin(["BID", "ASK", "ACCEPT"]),
                              rejected=lambda d: d["outcome"].str.startswith("rejected"))
    fmt = turns.groupby("model").agg(turns=("trader", "size"), unparsed_rate=("unparsed", "mean"),
                                     truncated_rate=("truncated", "mean"), pass_share=("passed", "mean"),
                                     orders=("order", "sum"), rejected=("rejected", "sum")).reset_index()
    fmt["rejected_rate"] = fmt["rejected"] / fmt["orders"]  # per order, as plan section 3 defines it (audit 32)
    fmt = fmt.drop(columns=["rejected"])
    format_ok = bool((fmt["unparsed_rate"] <= M4_FORMAT_LIMIT + EPS).all()
                     and (fmt["truncated_rate"] <= M4_FORMAT_LIMIT + EPS).all())
    by_side = by_side.merge(fmt, on="model", how="left")
    values = {"m4_gap": gap["all"], "m4_gap_buyer": gap["buyer"], "m4_gap_seller": gap["seller"],
              "m4_gap_lo": lo, "m4_gap_hi": hi, "m4_sessions": int(t["sessions"]["seed"].nunique()),
              "m4_placebo_max": float(placebo["gap_all"].max()) if not placebo.empty else float("nan"),
              "m4_placebo_n": int(len(placebo)), **{f"m4_{k}": v for k, v in breakdown.items()}}
    values["m4_format_ok"] = format_ok
    values.update({f"m4_{m.lower()}_{k}": float(v) for m, row in fmt.set_index("model").iterrows()
                   for k, v in row.items() if k != "turns"})
    placebo_max = values["m4_placebo_max"] if not placebo.empty else np.inf  # no placebo: the bar cannot be cleared
    values["m4_verdict"] = m4_verdict(values["m4_gap"], placebo_max, format_ok)
    values["m4_exploitation"] = values["m4_verdict"] == "exploitation"
    return by_side, placebo, values


def decisions(data: dict, values: dict) -> pd.DataFrame:
    """Each preregistered prediction and decision rule, with the measured value."""
    rows = []
    zic = 100 * data["zic"]["sessions"]["efficiency"].mean() if "zic" in data else float("nan")
    values.update(zic_eff=zic, sane_at=SANE_AT, worse_below=WORSE_BELOW)
    if "smoke" in data:
        t = data["smoke"]
        p, s = t["periods"], t["sessions"]
        rows += [
            ("M1", "unparsed under 5% of turns", 100 * s["unparsed_rate"].mean(), s["unparsed_rate"].mean() < 0.05),
            ("M1", "no reply truncated", 100 * s["truncated_rate"].mean(), s["truncated_rate"].mean() == 0),
            ("M1", "rejected orders under 10%", 100 * s["rejected_rate"].mean(), s["rejected_rate"].mean() < 0.10),
            ("M1", "at least 3 trades in each period", p["trades"].min(), p["trades"].min() >= 3),
        ]
    if "haiku" in data:
        t = data["haiku"]
        s, p = t["sessions"], t["periods"]
        eff = 100 * s["efficiency"].mean()
        last = p[p["period"] == 5]["mean_price"].mean()
        a1, a5 = p[p["period"] == 1]["alpha"].mean(), p[p["period"] == 5]["alpha"].mean()
        values.update(m2_eff=eff, m2_last_price=last, m2_alpha1=a1, m2_alpha5=a5)
        rule = m2_rule(eff)
        values["m2_rule"] = rule
        rows += [
            ("M2", "mean efficiency 75-95%", eff, 75 <= eff <= 95),
            ("M2", "period-5 mean price within $0.15 of P*", last, price_within(last)),
            ("M2", "alpha lower in period 5 than period 1", a5 - a1, a5 < a1),
            ("M2", f"decision rule: {rule}", eff, None),
        ]
    if "mixed" in data and "m4_gap" in values:
        mix_eff = 100 * data["mixed"]["sessions"]["efficiency"].mean()
        values["m4_eff"] = mix_eff
        rows += [
            ("M4", "Sonnet minus Haiku profit share >= 10 points", values["m4_gap"],
             values["m4_gap"] >= 10 - EPS if values["m4_format_ok"] else None),  # not interpreted (audit 28)
            ("M4", "mixed efficiency not above M2", mix_eff, mix_eff <= values.get("m2_eff", np.inf)),
            ("M4", "both models at most 5% unparsed and truncated", None, values["m4_format_ok"]),
            ("M4", f"exploitation rule (gap >= 20 and above every placebo gap): {values['m4_verdict']}",
             values["m4_gap"], values["m4_exploitation"]),
        ]
    if "sonnet" in data and "haiku" in data:
        s3, s2 = data["sonnet"], data["haiku"]
        d_eff = diff_ci(100 * s3["sessions"]["efficiency"], 100 * s2["sessions"]["efficiency"])
        d_trades = s3["periods"]["trades"].mean() - s2["periods"]["trades"].mean()
        w3 = waiting_metrics(s3["turns"], Schedule(), ROUNDS)
        w2 = waiting_metrics(s2["turns"], Schedule(), ROUNDS)
        t_lo, t_hi = pooled_t_diff(100 * s3["sessions"]["efficiency"], 100 * s2["sessions"]["efficiency"])
        values.update(m3_eff=100 * s3["sessions"]["efficiency"].mean(), m3_eff_diff=d_eff[0], m3_eff_diff_lo=d_eff[1],
                      m3_eff_diff_hi=d_eff[2], m3_eff_diff_t_lo=t_lo, m3_eff_diff_t_hi=t_hi, m3_trades_diff=d_trades,
                      m3_late_pass=w3["late_pass_share"].mean(), m2_late_pass=w2["late_pass_share"].mean(),
                      m3_spread=w3["final_spread"].mean(), m2_spread=w2["final_spread"].mean())
        holds = m3_holds(d_eff[0], d_trades)
        values["m3_holds"] = bool(holds)
        rows += [
            ("M3", "fewer trades per period than M2", d_trades, d_trades < 0),
            ("M3", "lower efficiency than M2", d_eff[0], d_eff[0] < 0),
            ("M3", "higher late PASS share than M2", values["m3_late_pass"] - values["m2_late_pass"],
             values["m3_late_pass"] > values["m2_late_pass"]),
            ("M3", "wider final spread than M2", values["m3_spread"] - values["m2_spread"],
             values["m3_spread"] > values["m2_spread"]),
            ("M3", "MT2 holds: efficiency >= 7 points below M2 and fewer trades", d_eff[0], holds),
        ]
    return pd.DataFrame(rows, columns=["run", "prediction or rule", "value", "met"])


# --- figures ----------------------------------------------------------------------------------------

def style():
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update({"font.size": 8, "axes.spines.top": False, "axes.spines.right": False,
                         "figure.dpi": 150, "axes.grid": True, "grid.alpha": 0.25})
    return plt


def color(condition: str) -> str:
    return common.PALETTE[COLORS[condition]]


def fig_supply_demand() -> None:
    plt = style()
    s = Schedule()
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    q = np.arange(0, len(s.values) + 1)
    ax.step(q, [s.values[0]] + s.values, where="pre", color=common.PALETTE["blue"], label="demand (buyer values)")
    ax.step(q, [s.costs[0]] + s.costs, where="pre", color=common.PALETTE["vermillion"], label="supply (seller costs)")
    ax.axhline(s.p_star, color="black", lw=0.8, ls="--", label=f"P* = ${s.p_star:.2f}")
    ax.axvline(s.q_star, color="grey", lw=0.6, ls=":")
    ax.text(s.q_star + 0.15, 0.85, f"Q* = {s.q_star}", fontsize=7)
    ax.set_xlabel("units (rank)")
    ax.set_ylabel("$ per unit")
    ax.legend(fontsize=6.5, loc="upper right")
    common.save_figure(fig, "a_supply_demand", FIGURES)


def fig_price_paths(data: dict) -> None:
    plt = style()
    conditions = [c for c in ("haiku", "mixed", "sonnet") if c in data]
    if not conditions:
        return
    fig, axes = plt.subplots(len(conditions), 1, figsize=(6.8, 1.8 * len(conditions)), sharex=True, squeeze=False)
    for ax, condition in zip(axes[:, 0], conditions):
        trades = data[condition]["trades"].sort_values(["seed", "period", "trade_no"])
        for i, (seed, g) in enumerate(trades.groupby("seed")):
            x = g["period"] - 1 + g["trade_no"] / (g.groupby("period")["trade_no"].transform("max") + 1)
            ax.plot(x, g["price"], marker="o", ms=2, lw=0.7, alpha=0.8,
                    color=common.PALETTE[common.SERIES[i % len(common.SERIES)]], label=f"seed {seed}")
        ax.axhline(2.0, color="black", lw=0.8, ls="--")
        for k in range(1, 5):
            ax.axvline(k, color="grey", lw=0.4)
        ax.set_ylabel("price ($)")
        ax.set_title(LABELS[condition], fontsize=8, loc="left")
        ax.legend(fontsize=5.5, ncol=4, loc="upper right")
    axes[-1, 0].set_xticks([k + 0.5 for k in range(5)], [f"period {k + 1}" for k in range(5)])
    common.save_figure(fig, "b_price_paths", FIGURES)


def fig_efficiency(data: dict) -> None:
    plt = style()
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    if "zic" in data:
        z = 100 * data["zic"]["sessions"]["efficiency"]
        ax.hist(z, bins=np.arange(60, 101, 2), orientation="horizontal", color="lightgrey",
                weights=np.full(len(z), 1 / len(z)) * 4, label="ZI-C sessions (scaled)")
        ax.axhline(z.mean(), color="black", lw=0.8, label=f"ZI-C mean {z.mean():.1f}%")
        ax.axhspan(z.mean() - 10, z.mean() - 5, color="orange", alpha=0.12, label="ZI-C -10 to -5")
    for i, condition in enumerate([c for c in ("smoke", "haiku", "mixed", "sonnet") if c in data]):
        e = 100 * data[condition]["sessions"]["efficiency"]
        x = 1.2 + i * 0.6
        m, lo, hi = mean_ci(e)
        ax.scatter(np.full(len(e), x), e, s=10, color=color(condition), zorder=3)
        ax.errorbar(x + 0.15, m, yerr=[[m - lo], [hi - m]], fmt="D", ms=4, color=color(condition), capsize=2)
        ax.text(x + 0.07, 101.5, LABELS[condition].split(" ")[0], ha="center", fontsize=6.5)
    ax.set_xlim(0, 3.8)
    ax.set_ylim(60, 103)
    ax.set_xticks([])
    ax.set_ylabel("session efficiency (%)")
    ax.legend(fontsize=5.5, loc="lower right")
    common.save_figure(fig, "c_efficiency", FIGURES)


def fig_m4_profit(by_side: pd.DataFrame) -> None:
    if by_side.empty:
        return
    plt = style()
    fig, ax = plt.subplots(figsize=(3.4, 2.4))
    sides = ["buyer", "seller", "all"]
    for j, model in enumerate(["Haiku", "Sonnet"]):
        part = by_side[by_side["model"] == model].set_index("role").reindex(sides)
        ax.bar(np.arange(3) + (j - 0.5) * 0.38, part["profit_share_pct"], width=0.36,
               color=common.PALETTE["blue" if model == "Haiku" else "vermillion"], label=model)
    ax.axhline(100, color="black", lw=0.8, ls="--")
    ax.set_xticks(range(3), ["buyers", "sellers", "all"])
    ax.set_ylabel("profit / CE profit (%)")
    ax.legend(fontsize=6.5)
    common.save_figure(fig, "d_m4_profit", FIGURES)


def fig_alpha(data: dict) -> None:
    plt = style()
    fig, ax = plt.subplots(figsize=(3.4, 2.6))
    periods = np.arange(1, 6)
    ax.plot(periods, SMITH_ALPHA, ls=":", color="grey", marker="s", ms=3, label="humans (Smith 1962)")
    ax.plot(periods, STRUSKI_GPT_SMALL_ALPHA, ls="--", color="grey", marker="^", ms=3, label="GPT Small (Struski)")
    for condition in [c for c in ("zic", "haiku", "mixed", "sonnet") if c in data]:
        p = data[condition]["periods"]
        g = p.groupby("period")["alpha"].mean()
        ax.plot(g.index, g.values, marker="o", ms=3, color=color(condition), label=LABELS[condition])
    ax.set_xlabel("period")
    ax.set_ylabel("Smith's alpha")
    ax.set_xticks(periods)
    ax.legend(fontsize=5.5)
    common.save_figure(fig, "e_alpha", FIGURES)


# --- report -------------------------------------------------------------------------------------------

def spend_table(data: dict) -> pd.DataFrame:
    rows = [{"condition": LABELS[c], "sessions": len(t["sessions"]), "cost_usd": t["sessions"]["cost_usd"].sum(),
             "per_session": t["sessions"]["cost_usd"].mean()} for c, t in data.items() if c != "zic"]
    out = pd.DataFrame(rows)
    if not out.empty:
        out = pd.concat([out, pd.DataFrame([{"condition": "total", "sessions": out["sessions"].sum(),
                                             "cost_usd": out["cost_usd"].sum(), "per_session": np.nan}])],
                        ignore_index=True)
    return out


def readable(value):
    """Round a number for the report's prose: 2 decimals from 1 up, 3 below (0.0266 -> 0.027)."""
    if isinstance(value, (bool, str)) or value is None:
        return value
    value = float(value)
    if value != value:
        return value
    return round(value, 2) if abs(value) >= 1 else round(value, 3)


def build(results: Path = RESULTS) -> dict:
    data = gather(results)
    TABLES.mkdir(parents=True, exist_ok=True)
    values: dict = {}
    tables = {"conditions": condition_table(data), "by_period": by_period_table(data), "sessions": session_table(data),
              "spend": spend_table(data)}
    report_columns = {"condition": "condition", "sessions": "sessions", "efficiency_pct": "efficiency %",
                      "eff_lo": "session CI lo", "eff_hi": "session CI hi", "eff_t_lo": "t CI lo", "eff_t_hi": "t CI hi",
                      "trades_per_period": "trades / period", "mean_price": "mean price",
                      "last_period_price": "period-5 price", "alpha_first": "alpha p1", "alpha_last": "alpha p5"}
    tables["conditions_report"] = tables["conditions"][list(report_columns)].rename(columns=report_columns)  # fits a page
    by_side, placebo, m4 = m4_tables(data)
    values.update(m4)
    tables.update(m4_profit=by_side, m4_placebo=placebo, decisions=decisions(data, values),
                  m4_same_ranks=same_rank_table(data))
    for name, table in tables.items():
        if not table.empty:
            common.save_table(table.round(4), name, TABLES)
    fig_supply_demand()
    fig_price_paths(data)
    fig_efficiency(data)
    fig_m4_profit(by_side)
    fig_alpha(data)
    if not tables["spend"].empty:
        values["spend_total"] = float(tables["spend"]["cost_usd"].iloc[-1])
        for row in tables["spend"].itertuples():
            values[f"spend_{SHORT.get(row.condition, 'total')}"] = float(row.cost_usd)
    for row in tables["conditions"].to_dict("records"):  # per-condition numbers for the report's prose
        key = SHORT[row["condition"]]
        for column in ["efficiency_pct", "eff_lo", "eff_hi", "eff_t_lo", "eff_t_hi", "trades_per_period",
                       "extramarginal_per_period", "mean_price", "last_period_price", "alpha_first", "alpha_last",
                       "rejected_rate", "unparsed_rate", "late_pass_share", "final_spread", "cost_per_session"]:
            if column in row and row[column] == row[column]:
                values[f"{key}_{column}"] = float(row[column])
                if column.endswith("_rate"):
                    values[f"{key}_{column}_pct"] = round(100 * float(row[column]), 2)
        if key not in ("zic", "m1"):
            t = data[{"m2": "haiku", "m4": "mixed", "m3": "sonnet"}[key]]
            periods, trades = t["periods"], t["trades"]
            values[f"{key}_periods_below_pstar"] = f"{int((periods['mean_price'] < Schedule().p_star).sum())} of {len(periods)}"
            intra = trades[~trades["extramarginal"].astype(bool)].groupby(["seed", "period"]).size()
            values[f"{key}_intramarginal_per_period"] = float(
                intra.reindex(periods.set_index(["seed", "period"]).index, fill_value=0).mean())
            prices = trades["price"].round(2)
            values[f"{key}_modal_price"] = float(prices.value_counts().idxmax())
            values[f"{key}_share_at_185"] = round(100 * float((prices == 1.85).mean()), 1)  # the rules' example price
    llm = [data[c]["periods"] for c in ("haiku", "mixed", "sonnet") if c in data]
    if llm:
        allp = pd.concat(llm)
        values["llm_periods_below_pstar"] = f"{int((allp['mean_price'] < Schedule().p_star).sum())} of {len(allp)}"
    for condition in ("haiku", "mixed", "sonnet"):  # who gets the surplus: profit / CE profit by side
        if condition in data:
            pooled = data[condition]["traders"].groupby("role")[["profit", "ce_profit"]].sum()
            for role, r in pooled.iterrows():
                values[f"{SHORT[LABELS[condition]]}_{role}_share"] = float(100 * r["profit"] / r["ce_profit"])
    same = tables["m4_same_ranks"]
    if not same.empty:
        g = same.groupby("group")[["m2_profit", "m4_sonnet_profit", "m4_haiku_profit", "m2_pass", "m4_sonnet_pass",
                                   "m4_haiku_pass"]].mean()
        for group, r in g.iterrows():
            values.update({f"same_{group}_{k}": float(v) for k, v in r.items()})
    values = {k: readable(v) for k, v in values.items()}
    (TABLES / "values.json").write_text(json.dumps(values, indent=2, default=lambda v: None if v != v else v))
    return values


def main() -> Path:
    from . import build_report

    values = build()
    common.TABLES, common.FIGURES = TABLES, FIGURES  # the pilot's renderer reads its folders from common
    text = (REPORT / "report.md").read_text()
    title = text.splitlines()[0].lstrip("# ").strip()
    out = REPORT / "report.html"
    out.write_text(build_report.wrap(build_report.render(text, values), title))
    print(f"wrote {out}; {build_report.print_pdf(out, REPORT / 'report.pdf')}")
    return out


if __name__ == "__main__":
    main()
