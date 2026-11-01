"""Latency card per arm and the configuration map (session M1, sections 5.1 and 5.2; exploratory, $0).

Plain words first.
  configuration    one way to answer an item from calls already paid for, replayed exactly from the anchor's cached
                   calls (analysis/anchor_read.py, the tier-1 panel, every reply regraded with parser v2.1 as in the
                   anchor read):
                     single   one call of an arm (its expected accuracy over the arm's calls)
                     vote@k   the plurality of an arm's first k calls (k = 2, 3), run in parallel
                     cascade  a cheap arm's 3-vote; when its three answers are not unanimous, one call of a stronger
                              arm is made after it and answers instead
  dollars          mean dollars per item, as billed.
  latency          seconds as measured: a single call's own seconds (its p95 is over every call of the arm, audit
                   107); a vote's slowest call (parallel); a cascade's slowest cheap call plus, on escalated items,
                   the strong call. p95 = the 95th percentile (an interactive budget must hold on nearly every item).
  TTFAT            time to the first answer token, estimated per call (no stream measurement exists for these calls):
                   seconds - answer tokens / the arm's decode speed (from analysis/latency_backfill.py), floored at
                   the arm's overhead. OpenAI reasoning arms (Luna low and medium, Sol): their reasoning is hidden and
                   these runs recorded no reasoning tokens, so their TTFAT is their total seconds (an upper bound;
                   audit M1-1). A vote's TTFAT is its slowest call's (the voted answer exists only then); a cascade's
                   escalated items add the strong call's TTFAT after the cheap stage's slowest call.
  cell             a dollar budget D x a latency budget L. The cell's winner is the most accurate configuration with
                   dollars <= D and p95 latency (or TTFAT p95) <= L.
  held-out regret  items split in two random halves, 100 times (seed 0); winners chosen on one half are scored on
                   the other: regret = accuracy of the best configuration feasible on the scoring half minus the
                   accuracy of the chosen one there, both directions; picks over a budget on the scoring half are
                   left out of the regret and counted apart (audit M1-1). The scoring half's own best is an in-sample
                   maximum, so the regret is biased up (conservative).
  stability        share of 200 item-bootstrap resamples (seed 0) in which a cell's winner is the full-sample winner.
  A third map uses mean total seconds, the measure of the first-pass prototype, so the two can be compared; budgets
  are set on p95 and TTFAT p95 because a latency budget must hold on nearly every item.

Study CD's grades are not read (E6's single read owns them); the map uses the anchor's tier-1 arms only.
Outputs: research/v4/measurement/latency_card.md, config_map.md, tables/latency_card.csv, tables/config_map.csv,
tables/configurations.csv. Run after analysis/latency_backfill.py.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import anchor_read as A  # noqa: E402
from autoagentnet.pruning import cascade as C  # noqa: E402

OUT = ROOT / "research/v4/measurement"
USD_BUDGETS = [0.0002, 0.0005, 0.001, 0.0025, 0.005, 0.01, 0.025]
P95_BUDGETS = [3, 5, 8, 15, 30, 60, 120, 300]
TTFAT_BUDGETS = [1, 2, 3, 5, 8, 15, 30, 60]
B, SEED = 200, 0
STRONG = ["sonnet_off", "sonnet_low", "sol_low", "luna_med"]  # cascade escalation targets: one call of these


def matrices(calls: dict[str, pd.DataFrame], panel) -> tuple[np.ndarray, np.ndarray]:
    """items x units arrays of output and thinking tokens, aligned with the panel."""
    frame = pd.concat(calls.values(), ignore_index=True)
    frame = frame.assign(unit=frame["source"] + ":" + frame["call"].astype(int).astype(str))
    out = np.zeros((panel.n, panel.m))
    think = np.zeros((panel.n, panel.m))
    for name, target in (("output_tokens", out), ("thinking_tokens", think)):
        if name not in frame:
            continue
        table = frame.pivot_table(index="item", columns="unit", values=name, aggfunc="first")
        table = table.reindex(index=panel.items, columns=list(panel.units["unit"]))
        target[:] = table.fillna(0).to_numpy(float)
    return out, think


def hidden_reasoning_refs(path=ROOT / "configs/providers.yaml") -> set[str]:
    """Model refs whose reasoning the provider hides and whose reasoning tokens these runs did not record: OpenAI
    refs with a reasoning effort other than none. Their first answer token comes after the hidden reasoning, which
    the totals cannot separate, so their TTFAT is taken as the call's total seconds (an upper bound; audit M1-1)."""
    import yaml

    models = yaml.safe_load(Path(path).read_text())["models"]
    return {ref for ref, cfg in models.items() if cfg.get("provider") == "openai_compat"
            and (cfg.get("request_options") or {}).get("reasoning_effort") not in (None, "none")}


def ttfat_matrix(panel, out_tokens, think_tokens, arms: dict, speed: dict, overhead: dict,
                 hidden: set[str] | None = None) -> np.ndarray:
    """Estimated TTFAT per call: seconds - answer tokens / decode speed, floored at the arm's overhead; total seconds
    for an arm whose reasoning is hidden and unrecorded (`hidden`, by the arm's ref)."""
    hidden = hidden or set()
    t = panel.seconds.astype(float).copy()
    for arm, units in arms.items():
        pos = C.unit_positions(panel, units)
        if units[0].split(":")[0] in hidden:
            continue
        answer = np.maximum(out_tokens[:, pos] - think_tokens[:, pos], 0)
        if arm in speed and speed[arm]:
            t[:, pos] = np.maximum(panel.seconds[:, pos] - answer / speed[arm], overhead.get(arm, 0.0))
    return t


def configurations(panel, arms: dict, ttfat: np.ndarray) -> list[dict]:
    """Every configuration as arrays over items: correct (expected), usd, and the latency samples `seconds` and
    `ttfat`. A single call's latency samples are all of the arm's calls (items x calls), so its p95 is a per-call
    p95; a vote's or cascade's are one per item. A vote's answer exists once its slowest call has answered, so its
    seconds and TTFAT are the slowest call's (audit M1-1)."""
    out = []
    for arm, units in arms.items():
        pos = C.unit_positions(panel, units)
        out.append({"name": f"{arm} single", "family": "single", "correct": A.per_call_accuracy(panel, units),
                    "usd": panel.cost[:, pos].mean(axis=1), "seconds": panel.seconds[:, pos], "ttfat": ttfat[:, pos]})
        for k in range(2, len(units) + 1):
            p = pos[:k]
            out.append({"name": f"{arm} vote@{k}", "family": "vote", "correct": A.vote_expected(panel, units[:k]),
                        "usd": panel.cost[:, p].sum(axis=1), "seconds": panel.seconds[:, p].max(axis=1),
                        "ttfat": ttfat[:, p].max(axis=1)})
    for cheap, units in arms.items():
        if len(units) < 3:
            continue
        pos = C.unit_positions(panel, units[:3])
        V = panel.votes[:, pos]
        unanimous = (V[:, 0] >= 0) & (V == V[:, :1]).all(axis=1)
        vote = A.vote_expected(panel, units[:3])
        for strong in STRONG:
            if strong not in arms or strong == cheap:
                continue
            s = C.unit_positions(panel, arms[strong][:1])[0]
            right = panel.correct_matrix()[:, s]
            first = panel.seconds[:, pos].max(axis=1)
            out.append({"name": f"{cheap} vote@3 -> {strong}", "family": "cascade",
                        "correct": np.where(unanimous, vote, right),
                        "usd": panel.cost[:, pos].sum(axis=1) + np.where(unanimous, 0.0, panel.cost[:, s]),
                        "seconds": first + np.where(unanimous, 0.0, panel.seconds[:, s]),
                        "ttfat": np.where(unanimous, ttfat[:, pos].max(axis=1), first + ttfat[:, s]),
                        "escalated": float((~unanimous).mean())})
    return out


def summarize(configs: list[dict], rows) -> pd.DataFrame:
    """Accuracy, mean dollars, p50/p95 and mean latency and TTFAT p95 of every configuration on the item rows."""
    out = []
    for c in configs:
        sec, tt = np.ravel(c["seconds"][rows]), np.ravel(c["ttfat"][rows])
        out.append({"name": c["name"], "family": c["family"], "accuracy": float(c["correct"][rows].mean()),
                    "usd": float(c["usd"][rows].mean()), "p50_s": float(np.quantile(sec, 0.5)),
                    "p95_s": float(np.quantile(sec, 0.95)), "mean_s": float(sec.mean()),
                    "ttfat_p95_s": float(np.quantile(tt, 0.95))})
    return pd.DataFrame(out)


def winners(table: pd.DataFrame, latency: str, budgets: list[float]) -> pd.DataFrame:
    """Per cell (dollar budget x latency budget): the most accurate feasible configuration (ties: cheaper first)."""
    ranked = table.sort_values(["accuracy", "usd"], ascending=[False, True])
    names, acc = ranked["name"].to_numpy(), ranked["accuracy"].to_numpy(float)
    usd, lat = ranked["usd"].to_numpy(float), ranked[latency].to_numpy(float)
    rows = []
    for d in USD_BUDGETS:
        for b in budgets:
            ok = np.flatnonzero((usd <= d) & (lat <= b))
            rows.append({"usd_budget": d, "latency_budget": b, "winner": names[ok[0]] if len(ok) else None,
                         "accuracy": float(acc[ok[0]]) if len(ok) else None})
    return pd.DataFrame(rows)


SPLITS = 100


def held_out(configs: list[dict], rows: np.ndarray, latency: str, budgets: list[float], seed: int = SEED,
             splits: int = SPLITS) -> pd.DataFrame:
    """Per cell, over `splits` random halvings (both directions each): regret = accuracy on the scoring half of the
    best configuration feasible there minus that of the configuration chosen on the other half, counted only when
    the chosen one is also feasible on the scoring half (a pick over a budget there is counted apart, in
    `violates`). The best is the scoring half's own best, so regret is biased up (a conservative figure). Reported:
    mean regret and its 2.5-97.5 percentiles over splits, and the share of picks over a budget."""
    rng = np.random.default_rng(seed)
    records = []
    for split in range(splits):
        perm = rng.permutation(rows)
        halves = [perm[: len(perm) // 2], perm[len(perm) // 2:]]
        tables = [summarize(configs, h) for h in halves]
        picks = [winners(t, latency, budgets) for t in tables]
        for choose, score in ((0, 1), (1, 0)):
            table = tables[score].set_index("name")
            for (_, p), (_, b) in zip(picks[choose].iterrows(), picks[score].iterrows()):
                rec = {"split": split, "usd_budget": p["usd_budget"], "latency_budget": p["latency_budget"],
                       "regret": np.nan, "violates": np.nan}
                if isinstance(p["winner"], str) and isinstance(b["winner"], str):
                    got = table.loc[p["winner"]]
                    over = bool(got["usd"] > p["usd_budget"] or got[latency] > p["latency_budget"])
                    rec["violates"] = float(over)
                    if not over:
                        rec["regret"] = b["accuracy"] - got["accuracy"]
                records.append(rec)
    frame = pd.DataFrame(records)
    per_split = frame.groupby(["usd_budget", "latency_budget", "split"])["regret"].mean().reset_index()
    out = per_split.groupby(["usd_budget", "latency_budget"])["regret"].agg(
        regret="mean", regret_lo=lambda x: x.quantile(0.025), regret_hi=lambda x: x.quantile(0.975)).reset_index()
    viol = frame.groupby(["usd_budget", "latency_budget"])["violates"].mean().reset_index()
    return out.merge(viol, on=["usd_budget", "latency_budget"])


def stability(configs: list[dict], rows: np.ndarray, latency: str, budgets: list[float], full: pd.DataFrame,
              b: int = B, seed: int = SEED) -> pd.Series:
    rng = np.random.default_rng(seed)
    same = np.zeros(len(full))
    for _ in range(b):
        w = winners(summarize(configs, rng.choice(rows, len(rows))), latency, budgets)
        same += (w["winner"].fillna("").to_numpy() == full["winner"].fillna("").to_numpy())
    return pd.Series(same / b, index=full.index)


def family_rows(panel) -> dict[str, np.ndarray]:
    kind = np.array(["math" if i.startswith("arxivmath") else "bbeh" for i in panel.items])
    return {k: np.flatnonzero(kind == k) for k in ("bbeh", "math")}


def card(arms_table: pd.DataFrame, calls: pd.DataFrame | None = None) -> pd.DataFrame:
    """Latency card per arm (5.1): estimated overhead (TTFT plus network), estimated TTFAT (overhead + mean thinking
    tokens / decode speed), decode speed, p50/p95 total, thinking tokens, context, dollars; measured TTFT, TTFAT and
    decode speed beside them where timed calls exist (calls.csv with timing_source "measured")."""
    t = arms_table.copy()
    t["ttft_est_s"] = t["overhead_s"]
    t["ttfat_est_s"] = t["overhead_s"] + t["thinking_tokens_mean"] / t["decode_tok_s"]
    hidden = t["arm"].isin(hidden_reasoning_refs())
    # audit M1-1: these runs recorded no reasoning tokens for OpenAI reasoning arms, so neither their thinking nor their
    # TTFAT can be estimated from totals; the decode estimate counts their hidden reasoning as output
    t.loc[hidden, ["thinking_tokens_mean", "ttfat_est_s"]] = np.nan
    t.loc[hidden, "flag"] = (t.loc[hidden, "flag"].fillna("") + " hidden reasoning, not recorded: no TTFAT estimate").str.strip()
    for col in ("ttft_measured_p50_s", "ttfat_measured_p50_s", "decode_measured_p50"):
        t[col] = None
    if calls is not None and "timing_source" in calls:
        measured = calls[calls["timing_source"] == "measured"]
        for arm, part in measured.groupby("ref"):
            mask = t["arm"] == arm
            t.loc[mask, "ttft_measured_p50_s"] = part["ttft_s"].median()
            t.loc[mask, "ttfat_measured_p50_s"] = part["ttfat_s"].median()
            t.loc[mask, "decode_measured_p50"] = part["decode_tok_s"].median()
    keep = ["arm", "model", "calls", "ttft_est_s", "ttft_measured_p50_s", "ttfat_est_s", "ttfat_measured_p50_s",
            "decode_tok_s", "decode_lo", "decode_hi", "decode_measured_p50", "p50_s", "p95_s", "thinking_tokens_mean",
            "context_tokens_p50", "usd_per_call", "flag"]
    return t[keep]


def measured_calls() -> pd.DataFrame | None:
    """Every calls.csv row with measured timing (none before session M1's instrumentation ran)."""
    frames = []
    for path in sorted((ROOT / "results").glob("*/calls.csv")):
        head = pd.read_csv(path, nrows=0).columns
        if "timing_source" in head:
            frames.append(pd.read_csv(path, usecols=["ref", "timing_source", "ttft_s", "ttfat_s", "decode_tok_s"]))
    return pd.concat(frames, ignore_index=True) if frames else None


def md_grid(cells: pd.DataFrame, value: str, budgets: list[float]) -> list[str]:
    head = "| $ per item \\ latency | " + " | ".join(f"<= {b} s" for b in budgets) + " |"
    lines = [head, "|" + "---|" * (len(budgets) + 1)]
    for d in USD_BUDGETS:
        part = cells[cells["usd_budget"] == d].set_index("latency_budget")
        cells_txt = []
        for b in budgets:
            v = part.loc[b, value] if b in part.index else None
            cells_txt.append("" if v is None or (isinstance(v, float) and np.isnan(v)) else
                             (f"{v:.2f}" if isinstance(v, float) else str(v)))
        lines.append(f"| <= {d} | " + " | ".join(cells_txt) + " |")
    return lines


def main() -> None:
    arms_table = pd.read_csv(OUT / "tables/latency_by_arm.csv")
    card_table = card(arms_table, measured_calls())
    card_table.to_csv(OUT / "tables/latency_card.csv", index=False)

    calls = A.tier1_calls()
    arms = A.complete_arms(calls)
    panel = A.anchor_panel(arms=arms, calls=calls)
    refs = {arm: units[0].split(":")[0] for arm, units in arms.items()}
    by_ref = arms_table.set_index("arm")
    speed = {arm: by_ref.loc[ref, "decode_tok_s"] for arm, ref in refs.items() if ref in by_ref.index}
    overhead = {arm: by_ref.loc[ref, "overhead_s"] for arm, ref in refs.items() if ref in by_ref.index}
    out_tokens, think_tokens = matrices(calls, panel)
    ttfat = ttfat_matrix(panel, out_tokens, think_tokens, arms, speed, overhead, hidden_reasoning_refs())
    configs = configurations(panel, arms, ttfat)

    tables, cells, lines = [], [], []
    for fam, rows in family_rows(panel).items():
        table = summarize(configs, rows).assign(benchmark=fam, items=len(rows))
        tables.append(table)
        for latency, budgets, label in (("p95_s", P95_BUDGETS, "p95 total"), ("ttfat_p95_s", TTFAT_BUDGETS, "TTFAT p95"),
                                        ("mean_s", P95_BUDGETS, "mean total (the first pass's measure)")):
            full = winners(table, latency, budgets)
            full["stability"] = stability(configs, rows, latency, budgets, full)
            full = full.merge(held_out(configs, rows, latency, budgets), on=["usd_budget", "latency_budget"])
            full = full.assign(benchmark=fam, latency=label)
            cells.append(full)
            lines += [f"### {fam.upper()} ({len(rows)} items), latency = {label}", "",
                      "Winner per cell (accuracy):", ""]
            shown = full.assign(cell=[f"{w} ({a:.2f})" if isinstance(w, str) else "" for w, a in zip(full["winner"], full["accuracy"].fillna(0))])
            lines += md_grid(shown, "cell", budgets)
            lines += ["", f"Held-out regret (accuracy points lost by choosing on the other half; mean [2.5, 97.5 "
                      f"percentiles] over {SPLITS} halvings) and bootstrap stability of the winner:", ""]
            shown = full.assign(cell=[("" if pd.isna(r) else f"{r * 100:.1f} [{lo * 100:.1f}, {hi * 100:.1f}] pt, {s:.0%}")
                                      for r, lo, hi, s in zip(full["regret"], full["regret_lo"], full["regret_hi"],
                                                              full["stability"])])
            lines += md_grid(shown, "cell", budgets)
            filled = full[full["winner"].notna()]
            lines += ["", f"Mean held-out regret over the {len(filled)} non-empty cells ({SPLITS} random halvings, both "
                      f"directions; over-budget picks left out): {filled['regret'].mean() * 100:.2f} points (cell means "
                      f"up to {filled['regret'].max() * 100:.1f}; the largest cell's 97.5th percentile over splits "
                      f"{filled['regret_hi'].max() * 100:.1f}); picks over a budget on the scoring half: "
                      f"{filled['violates'].mean():.0%}; median stability "
                      f"{filled['stability'].median():.0%}. Cascades win {int(filled['winner'].str.contains('->', regex=False).sum())} "
                      "cells.", ""]
    pd.concat(tables).to_csv(OUT / "tables/configurations.csv", index=False)
    pd.concat(cells).to_csv(OUT / "tables/config_map.csv", index=False)
    (OUT / "config_map.md").write_text(map_md(pd.concat(tables), lines, arms))
    (OUT / "latency_card.md").write_text(card_md(card_table))
    print(pd.concat(cells).groupby(["benchmark", "latency"])[["regret", "stability"]].mean())


def map_md(tables: pd.DataFrame, lines: list[str], arms: dict) -> str:
    head = ["# Configuration map: accuracy under a dollar and a latency budget (session M1, exploratory)", "",
            "Made by `analysis/latency_map.py`. Exact replay of the API anchor's cached tier-1 calls (regraded with "
            "parser v2.1, as in the anchor read); exploratory, not a preregistered read. Definitions are in the "
            "script's docstring. Latency is measured seconds per call under each run's concurrency and the agent "
            "proxy path; TTFAT is an estimate (no stream measurement exists for these calls).", "",
            f"Arms: {', '.join(arms)}. Configurations: {len(tables['name'].unique())} (single calls, k-votes up to 3, "
            "cascades from a cheap 3-vote to one call of a stronger arm when the vote is not unanimous). Study CD's "
            "arms are left out: their grades belong to E6's single read.", "",
            "## Configurations (accuracy, $ per item, latency)", "",
            "| benchmark | configuration | accuracy | $ per item | p50 s | p95 s | TTFAT p95 s |", "|---|---|---|---|---|---|---|"]
    for r in tables.sort_values(["benchmark", "usd"]).itertuples():
        head.append(f"| {r.benchmark} | {r.name} | {r.accuracy:.3f} | {r.usd:.5f} | {r.p50_s:.1f} | {r.p95_s:.1f} | "
                    f"{r.ttfat_p95_s:.1f} |")
    return "\n".join(head + ["", "## Maps", ""] + lines) + "\n"


def card_md(t: pd.DataFrame) -> str:
    def f(x, d=1):
        return "" if x is None or (isinstance(x, float) and np.isnan(x)) else f"{x:,.{d}f}"

    lines = ["# Latency card per arm (session M1)", "",
             "Made by `analysis/latency_map.py` from `tables/latency_by_arm.csv` (the backfill). est = estimated from "
             "total seconds by median regression (TTFT est = the overhead; TTFAT est = overhead + mean thinking tokens "
             "/ decode speed); measured = from streamed calls (timing_source \"measured\"), side by side where both "
             "exist. No measured column is filled until a timed run has been made. OpenAI reasoning arms recorded no "
             "reasoning tokens in these runs, so their thinking and TTFAT are left blank (audit M1-1).", "",
             "| arm | model | calls | TTFT est s | TTFT meas | TTFAT est s | TTFAT meas | decode tok/s est [95%] | "
             "decode meas | p50 s | p95 s | thinking tok | context p50 | $/call | flag |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in t.itertuples():
        lines.append(f"| {r.arm} | {r.model if isinstance(r.model, str) else ''} | {r.calls:,} | {f(r.ttft_est_s, 2)} | "
                     f"{f(r.ttft_measured_p50_s, 2)} | {f(r.ttfat_est_s, 1)} | {f(r.ttfat_measured_p50_s, 1)} | "
                     f"{f(r.decode_tok_s, 0)} [{f(r.decode_lo, 0)}, {f(r.decode_hi, 0)}] | {f(r.decode_measured_p50, 0)} | "
                     f"{f(r.p50_s)} | {f(r.p95_s)} | {f(r.thinking_tokens_mean, 0)} | {f(r.context_tokens_p50, 0)} | "
                     f"{r.usd_per_call:.5f} | {r.flag if isinstance(r.flag, str) else ''} |")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    main()
