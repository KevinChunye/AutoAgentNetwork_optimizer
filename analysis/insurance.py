"""Agent insurance study: every table and figure in reports/insurance/ comes from this script.

Inputs (all free; no model calls):
  research/insurance/tau2_episodes.csv   episode table built from the public tau2-bench
                                         trajectories (4 models x airline, retail, telecom,
                                         4 trials per task). Rebuild it with --tau2 <dir>, where
                                         <dir> is tau2-bench's data/tau2/results/final
  results/m*/turns.csv                   market-town traders (Haiku 5.5, Sonnet 5.5)
  results/p*/agents.csv, results.csv     pilot networks (Haiku 5.5 dense 3x6, single agents)
  configs/insurance/assumptions.yaml     underwriting assumptions

Run: python -m analysis.insurance [--tau2 DIR] [--sims N]
"""

from __future__ import annotations

import argparse
import json
from dataclasses import replace
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import yaml

from autoagentnet.insurance import actuarial as ac
from autoagentnet.insurance import contagion as cg
from autoagentnet.insurance import events as ev
from autoagentnet.insurance import portfolio as pf

from .common import PALETTE, SERIES

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports" / "insurance"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"
EPISODES = ROOT / "research" / "insurance" / "tau2_episodes.csv"
CONFIG = ROOT / "configs" / "insurance" / "assumptions.yaml"
MODEL_LABEL = {"claude-3-7-sonnet": "Claude 3.7 Sonnet", "gpt-4.1": "GPT-4.1",
               "gpt-4.1-mini": "GPT-4.1 mini", "o4-mini": "o4-mini"}


def load_tau2(tau2_dir: str | None) -> pd.DataFrame:
    if tau2_dir:
        t = ev.tau2_dir(tau2_dir, "*_default_*.json")
        t = pd.concat([t, ev.tau2_dir(tau2_dir, "gpt-4.1-mini*_base_*.json")], ignore_index=True)
        t["model"] = t["model"].str.replace(r"-20\d\d-?\d\d-?\d\d$", "", regex=True)
        EPISODES.parent.mkdir(parents=True, exist_ok=True)
        t.to_csv(EPISODES, index=False)
    t = pd.read_csv(EPISODES, dtype={"task_id": str})
    t["commission"] = t["kind"].eq("commission").astype(int)
    return t


def save(df: pd.DataFrame, name: str) -> None:
    df.to_csv(TABLES / f"{name}.csv", index=False)


def fig_rates(freq: pd.DataFrame, name: str, ylabel: str) -> None:
    fig, ax = plt.subplots(figsize=(7.5, 3.6))
    contexts = list(freq["context"].unique())
    models = list(freq["model"].unique())
    width = 0.8 / len(models)
    for j, m in enumerate(models):
        g = freq[freq["model"].eq(m)].set_index("context").reindex(contexts)
        x = np.arange(len(contexts)) + (j - (len(models) - 1) / 2) * width
        ax.bar(x, g["raw_rate"], width, color=PALETTE[SERIES[j]], label=MODEL_LABEL.get(m, m))
        ax.errorbar(x, g["raw_rate"], yerr=[g["raw_rate"] - g["ci_lo"], g["ci_hi"] - g["raw_rate"]],
                    fmt="none", ecolor="#333333", elinewidth=0.8, capsize=2)
    ax.set_xticks(np.arange(len(contexts)), contexts)
    ax.set_ylabel(ylabel)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8, ncol=4, loc="upper center", bbox_to_anchor=(0.5, 1.15))
    fig.tight_layout()
    fig.savefig(FIGURES / f"{name}.png", dpi=200)
    plt.close(fig)


def fig_passk(passk: pd.DataFrame) -> None:
    fig, axes = plt.subplots(1, 3, figsize=(8, 2.8), sharey=True)
    for ax, (ctx, g) in zip(axes, passk.groupby("context")):
        for j, (m, h) in enumerate(g.groupby("model")):
            h = h.sort_values("k")
            ax.plot(h["k"], h["pass_k"], marker="o", color=PALETTE[SERIES[j]], label=MODEL_LABEL.get(m, m))
        ax.set_title(ctx, fontsize=9)
        ax.set_xticks([1, 2, 3, 4])
        ax.set_xlabel("k trials")
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].set_ylabel("pass^k")
    axes[-1].legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGURES / "pass_k.png", dpi=200)
    plt.close(fig)


def fig_adoption(curve: pd.DataFrame) -> None:
    fig, ax = plt.subplots(figsize=(4.8, 3.4))
    ax.plot([0, 1], [0, 1], color="#999999", lw=0.8, ls="--", label="pass-through (y = w)")
    for j, (stage, g) in enumerate(curve.groupby("stage")):
        ax.plot(g["mean_w"], g["p_wrong"], marker="o", color=PALETTE[SERIES[j]], label=stage)
    ax.set_xlabel("share of the 6 proposers wrong (w)")
    ax.set_ylabel("P(downstream agent wrong)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "adoption_curve.png", dpi=200)
    plt.close(fig)


def build_book(freq: pd.DataFrame, cfg: dict, level: float, models: list[str], n: int,
               multiplier: float = 1.0, omission: pd.DataFrame | None = None) -> list[pf.Insured]:
    """n insureds, cycling through models and then contexts, at the given rate level."""
    contexts = cfg["book"]["contexts"]
    book = []
    for i in range(n):
        m = models[i % len(models)]
        c = contexts[(i // len(models)) % len(contexts)]
        p = float(freq[(freq["model"].eq(m)) & (freq["context"].eq(c))]["credible_rate"].iloc[0]) * level
        p_om = 0.0
        if omission is not None:
            p_om = float(omission[(omission["model"].eq(m)) & (omission["context"].eq(c))]["credible_rate"].iloc[0]) * level
        book.append(pf.Insured(f"{m}/{c}/{i}", m, c, cfg["book"]["episodes_per_year"], p, p_om, multiplier))
    return book


def sim_config(cfg: dict, n_sims: int, **changes) -> pf.SimConfig:
    s = pf.SimConfig(n_sims=n_sims, level=cfg["sim"]["level"], insured_cv=cfg["sim"]["insured_cv"],
                     seed=cfg["sim"]["seed"], shocks=pf.ShockModel(**cfg["shocks"]),
                     controls=pf.Controls(), terms=pf.PolicyTerms(**cfg["terms"]))
    return replace(s, **changes)


def row(name: str, r: dict, episodes: float) -> dict:
    """One scenario's headline numbers. capital_charge_share = cost of capital x capital as a share
    of the risk premium (expected loss + that charge), i.e. the part of the price paid for the tail."""
    return {"scenario": name, "expected_loss": r["mean"], "sd": r["sd"], "var_995": r["var"],
            "tvar_995": r["tvar"], "capital": r["capital"], "gross_premium": r["premium"],
            "premium_per_1k_episodes": 1000 * r["premium"] / episodes,
            "capital_charge_share": r["capital_charge_share"],
            "capital_to_expected_loss": r["capital"] / r["mean"] if r["mean"] else np.nan}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tau2", help="tau2-bench data/tau2/results/final (rebuilds the episode table)")
    parser.add_argument("--sims", type=int, default=None)
    args = parser.parse_args()
    for d in (TABLES, FIGURES):
        d.mkdir(parents=True, exist_ok=True)
    cfg = yaml.safe_load(CONFIG.read_text())
    n_sims = args.sims or cfg["sim"]["n_sims"]
    A = ac.LossAssumptions(**cfg["loss"])

    # 1. Frequency, clustering and severity from tau2-bench.
    t = load_tau2(args.tau2)
    t["non_commission"] = t["kind"].isin(["omission", "communication"]).astype(int)
    f_def = ac.frequency_table(t, "default")
    f_com = ac.frequency_table(t, "commission")
    f_non = ac.frequency_table(t, "non_commission")
    sev = ac.severity_table(t)
    kinds = t.groupby(["context", "model"])["kind"].value_counts(normalize=True).unstack().fillna(0).reset_index()
    esc = t.groupby(["context", "model"], as_index=False).agg(escalation_rate=("escalated", "mean"),
                                                              writes_per_episode=("n_writes", "mean"),
                                                              agent_cost_usd=("cost_usd", "mean"))
    passk = pd.concat([ac.pass_hat_k(t, k) for k in [1, 2, 3, 4]], ignore_index=True)
    pure = ac.pure_premium_table(t, A)
    # Relativities: each cell's credible commission rate against its context's pooled rate.
    rel = f_com[["model", "context", "credible_rate", "pool_rate", "Z"]].copy()
    rel["relativity"] = rel["credible_rate"] / rel["pool_rate"]
    for name, df in [("frequency_default", f_def), ("frequency_commission", f_com), ("severity", sev),
                     ("default_kinds", kinds), ("escalation", esc), ("pass_k", passk),
                     ("pure_premium_benchmark", pure), ("relativities", rel)]:
        save(df, name)
    fig_rates(f_def, "default_rates", "default rate (tau2, 95% CI)")
    fig_rates(f_com, "commission_rates", "wrong-write rate (95% CI)")
    fig_passk(passk)

    # 2. Market town: attempted mandate breaches by model, and what the hard limit check stopped.
    acts = ev.market_actions(ROOT / "results")
    mk = acts.groupby(["model", "role"], as_index=False).agg(
        orders=("breach", "size"), breaches=("breach", "sum"), rate=("breach", "mean"),
        mean_overshoot=("overshoot_usd", lambda x: float(x[x > 0].mean()) if (x > 0).any() else 0.0),
        mean_limit=("limit_usd", "mean"))
    # 95% upper bound for zero-event cells by the rule of three (3 / n).
    mk["rate_upper_95"] = np.where(mk["breaches"].eq(0), 3 / mk["orders"], np.nan)
    mk["overshoot_share_of_limit"] = mk["mean_overshoot"] / mk["mean_limit"]
    save(mk, "market_breaches")

    # 3. Contagion through the pilot network.
    agents = ev.network_agents(ROOT / "results")
    curve = cg.adoption_curve(agents)
    mono = cg.monoculture(agents)
    net = ev.network_episodes(ROOT / "results")
    mult = cg.network_multiplier(net)
    save(curve, "adoption_curve")
    save(mult, "network_multiplier")
    (TABLES / "monoculture.json").write_text(json.dumps(mono, indent=2))
    fig_adoption(curve)

    # 4. Portfolio simulation.
    exposures = {c: g["exposure_usd"].to_numpy() for c, g in t[t["kind"].eq("commission")].groupby("context")}
    models4 = list(MODEL_LABEL)
    n_ins = cfg["book"]["insureds"]
    eps = cfg["book"]["episodes_per_year"]
    base = cfg["levels"]["production"]
    pipe = float(mult["multiplier"].iloc[0]) if not mult.empty else 1.0
    scen = []
    runs = {}

    def run(name, models, level=base, multiplier=1.0, n=n_ins, **changes):
        book = build_book(f_com, cfg, level, models, n, multiplier, f_non)
        r = pf.simulate(book, exposures, A, sim_config(cfg, n_sims, **changes))
        runs[name] = r
        scen.append(row(name, r, n * eps))
        return r

    run("base: 4 models, no controls", models4)
    run("concentrated: 1 model (GPT-4.1)", ["gpt-4.1"])
    run("pipeline (dense 3x6 multiplier)", models4, multiplier=pipe)
    run("approval gate >$500 (80% catch)", models4, controls=pf.Controls(**cfg["controls"]))
    run("no deductible, no limit", models4, terms=pf.PolicyTerms())
    run("severe shocks (10x, 2/yr)", models4, shocks=pf.ShockModel(rate_per_year=2.0, multiplier=10.0, months=1))
    run("severe shocks, 1 model", ["gpt-4.1"], shocks=pf.ShockModel(rate_per_year=2.0, multiplier=10.0, months=1))
    run("no model shocks", models4, shocks=pf.ShockModel(rate_per_year=0.0))
    scen_df = pd.DataFrame(scen)
    save(scen_df, "portfolio_scenarios")

    # Level sweep: how the premium splits between expected loss and capital as rates fall.
    lv = []
    for lname, lvl in cfg["levels"].items():
        r = pf.simulate(build_book(f_com, cfg, lvl, models4, n_ins, 1.0, f_non), exposures, A, sim_config(cfg, n_sims))
        lv.append({"level": lname, "scale": lvl, **row(lname, r, n_ins * eps)})
    save(pd.DataFrame(lv), "level_sweep")

    # Diversification: capital per insured as the book grows, one model vs four.
    dv = []
    for n in [8, 16, 32, 64, 128, 256]:
        for label, models in [("1 model", ["gpt-4.1"]), ("4 models", models4)]:
            r = pf.simulate(build_book(f_com, cfg, base, models, n, 1.0, f_non), exposures, A,
                            sim_config(cfg, max(n_sims // 4, 2000)))
            dv.append({"insureds": n, "book": label, "capital_per_insured": r["capital"] / n,
                       "expected_loss_per_insured": r["mean"] / n,
                       "capital_to_expected_loss": r["capital"] / r["mean"]})
    dv = pd.DataFrame(dv)
    save(dv, "diversification")

    # Sensitivity of the base-case premium to each assumption.
    sens = []
    base_prem = runs["base: 4 models, no controls"]["premium"]
    for label, A2, changes in [
        ("LGD 0.10", replace(A, lgd=0.10), {}), ("LGD 0.50", replace(A, lgd=0.50), {}),
        ("LGD 1.00", replace(A, lgd=1.00), {}),
        ("cost of capital 6%", replace(A, cost_of_capital=0.06), {}),
        ("cost of capital 15%", replace(A, cost_of_capital=0.15), {}),
        ("insured drift cv 0.6", A, {"insured_cv": 0.6}),
        ("shock multiplier 5x", A, {"shocks": pf.ShockModel(rate_per_year=1.0, multiplier=5.0, months=1)}),
        ("shock lasts 3 months", A, {"shocks": pf.ShockModel(rate_per_year=1.0, multiplier=3.0, months=3)}),
    ]:
        r = pf.simulate(build_book(f_com, cfg, base, models4, n_ins, 1.0, f_non), exposures, A2,
                        sim_config(cfg, max(n_sims // 2, 2000), **changes))
        sens.append({"change": label, "gross_premium": r["premium"], "vs_base": r["premium"] / base_prem - 1,
                     "capital": r["capital"]})
    save(pd.DataFrame(sens), "sensitivity")

    per = runs["base: 4 models, no controls"]["per_insured"]
    per_g = per.groupby(["model", "context"], as_index=False).agg(
        premium_per_1k=("premium_per_1k", "mean"), capital_charge_share=("capital_charge_share", "mean"))
    save(per_g, "premium_by_cell")

    # Figures for the portfolio.
    fig, ax = plt.subplots(figsize=(6, 3.4))
    for j, name in enumerate(["base: 4 models, no controls", "concentrated: 1 model (GPT-4.1)",
                              "approval gate >$500 (80% catch)"]):
        x = np.sort(runs[name]["total"]) / 1e6
        ax.plot(x, 1 - np.arange(1, len(x) + 1) / len(x), color=PALETTE[SERIES[j]], label=name)
    ax.set_yscale("log")
    ax.set_xlabel("annual book loss ($M)")
    ax.set_ylabel("P(loss > x)")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=7)
    fig.tight_layout()
    fig.savefig(FIGURES / "loss_exceedance.png", dpi=200)
    plt.close(fig)

    fig, ax = plt.subplots(figsize=(5, 3.2))
    for j, (label, g) in enumerate(dv.groupby("book")):
        ax.plot(g["insureds"], g["capital_to_expected_loss"], marker="o", color=PALETTE[SERIES[j]], label=label)
    ax.set_xscale("log", base=2)
    ax.set_xlabel("insureds in the book")
    ax.set_ylabel("capital / expected loss")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(frameon=False, fontsize=8)
    fig.tight_layout()
    fig.savefig(FIGURES / "diversification.png", dpi=200)
    plt.close(fig)
    print(scen_df.round(2).to_string())


if __name__ == "__main__":
    main()
