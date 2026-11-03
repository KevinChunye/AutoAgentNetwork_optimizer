"""Every number in the paper (paper/) and the HTML record (reports/v4/story.html), read from committed files.

Session W1. Nothing here is typed by hand: each number is read from a committed table, read, ledger of findings or
run status file, and carries
  value    the number as read (rates as shares, dollars as dollars);
  display  how the paper and the page print it (rates in points, e.g. 0.123 -> "12.3");
  status   one of the findings ledger's words (research/v3/findings.md):
             confirmatory               a preregistered test with a Holm family, read once on sealed items;
             preregistered-descriptive  a preregistered quantity read once on sealed items, no pass/fail test;
             exploratory                on sealed items, but not preregistered as a test;
             post hoc                   chosen after the data were read, or on data not sealed for it (all the
                                        public Atlas data and the session W1 extensions);
           and three bookkeeping words: record (spend, counts, dates, audit verdicts), design (a preregistered
           design quantity such as power, not a result) and cited (another paper's number, from research/lit/);
           pending marks a number that waits for another session (E6's CD read);
  source   the committed file it was read from.

Outputs:
  paper/numbers.tex           \\nm{key} prints a number, \\nmst{key} its status (an unknown key prints ??key)
  paper/numbers_table.tex     every number with its status and source, for the appendix
  reports/v4/story_data.json  the same numbers plus the series the page draws (charts, timeline, runs, findings)

Usage: python scripts/build_numbers.py
"""

from __future__ import annotations

import glob
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.atlas_extend import read_table  # noqa: E402

ATLAS = ROOT / "research/v4/atlas/tables"
EXT = ATLAS / "extend"
READ = ROOT / "research/v4/anchor/read.md"
FINDINGS = ROOT / "research/v3/findings.md"
HANDBACK = ROOT / "research/v4/handback_e5.md"
CD_READ = ROOT / "research/v4/cd/read.md"  # session E6; numbers stay "pending" until it is on main
RUNS_REVIEW = ROOT / "research/v4/runs_review.md"
STATUSES = {"confirmatory", "preregistered-descriptive", "exploratory", "post hoc", "record", "design", "cited",
            "pending"}

NUMBERS: dict[str, dict] = {}


def fmt(value, kind: str, digits: int) -> str:
    """Display text: pct = a share printed in points; signed = points with a sign; usd = dollars; int; num; text."""
    if kind == "text":
        return str(value)
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return "n/a"
    if kind == "pct":
        return f"{100 * value:.{digits}f}"
    if kind == "signed":
        return f"{100 * value:+.{digits}f}"
    if kind == "usd":
        return f"${value:,.{digits}f}"
    if kind == "int":
        return f"{int(round(value)):,}"
    return f"{value:.{digits}f}"


def put(key: str, value, status: str, source, kind: str = "num", digits: int = 2, note: str = "") -> None:
    """Register one number; a key may be set once."""
    if status not in STATUSES:
        raise ValueError(f"{key}: unknown status {status}")
    if key in NUMBERS:
        raise ValueError(f"{key} set twice")
    value = value.item() if hasattr(value, "item") else value
    NUMBERS[key] = {"value": value, "display": fmt(value, kind, digits), "status": status,
                    "source": str(Path(source).relative_to(ROOT)) if isinstance(source, Path) else str(source),
                    "kind": kind, "note": note}


def csv(name: str, folder: Path = EXT) -> pd.DataFrame:
    return pd.read_csv(folder / f"{name}.csv")


def grab(text: str, pattern: str) -> float:
    """The first number captured by `pattern` (one group) in `text`; fails loudly when absent."""
    m = re.search(pattern, text)
    if not m:
        raise ValueError(f"pattern not found: {pattern}")
    return float(m.group(1).replace(",", ""))


def finding(fid: str, column: int = 2) -> str:
    """One cell of one row of the findings ledger (2: the number, 3: n)."""
    for line in FINDINGS.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if cells and cells[0] == fid:
            return cells[column]
    raise KeyError(fid)


# ---------------------------------------------------------------------------------------------------------
# Atlas (session E5; public data, post hoc by the ledger's definition)

def design_numbers() -> None:
    """Design constants of the W1 analyses and the roadmap's targets, read from the code and from research/v4/roadmap.md."""
    import inspect

    from analysis import atlas_extend as X
    from autoagentnet.atlas import factor as F

    src = ROOT / "analysis/atlas_extend.py"
    put("design.boot", X.N_BOOT, "design", src, "int")
    put("design.halves", 2 * X.N_HALVES, "design", src, "int")
    put("design.gainpoints", 100 * X.GAIN_POINTS, "design", src, "int")
    put("design.weak.lo", X.WEAK[0], "design", src, "num", 1)
    put("design.weak.hi", X.WEAK[1], "design", src, "num", 1)
    put("design.p4.top", X.P4_TOP, "design", src, "num", 2)
    for j, v in enumerate(X.P4_GRID["others"]):
        put(f"design.p4.others{j}", v, "design", src, "num", 1)
    for j, v in enumerate(X.P4_GRID["systems"]):
        put(f"design.p4.systems{j}", v, "design", src, "int")
    for j, v in enumerate(X.P4_GRID["sd_b"]):
        put(f"design.p4.share{j}", v ** 2 / (v ** 2 + F.LOGISTIC_VAR), "design", src, "num", 2)
    put("design.p4.items", X.P4_ITEMS, "design", src, "int")
    put("design.near", X.NEAR_DOLLARS, "design", src, "num", 1)
    a5 = csv("a5_coverage", ATLAS)
    put("design.sets.lo", int(a5.loc[a5["k"] >= 2, "k"].min()), "design", ATLAS / "a5_coverage.csv", "int")
    put("design.sets.hi", int(a5["k"].max()), "design", ATLAS / "a5_coverage.csv", "int")
    power = (ROOT / "research/v4/anchor/power.md").read_text()
    put("design.power.min", grab(power, r"power under ([\d.]+) at the chosen n"), "design",
        ROOT / "research/v4/anchor/power.md", "num", 2)
    lit = (ROOT / "research/lit/w1_related_work.md").read_text()
    put("cited.cofailure.under", grab(lit, r"by about ([\d.]+) times on open-ended mathematics"), "cited",
        ROOT / "research/lit/w1_related_work.md", "num", 1)
    put("design.p4.reps", X.P4_REPS, "design", src, "int")
    put("design.ridge", inspect.signature(F.fit).parameters["l2"].default, "design", ROOT / "autoagentnet/atlas/factor.py",
        "num", 1)
    t8 = csv("p8_tail")
    ma = t8[t8["benchmark"].str.startswith("matharena")]
    put("design.p8.ma.items.lo", ma["test items"].min(), "record", EXT / "p8_tail.csv", "int")
    put("design.p8.ma.items.hi", ma["test items"].max(), "record", EXT / "p8_tail.csv", "int")
    road = (ROOT / "research/v4/roadmap.md").read_text()
    put("plan.items", grab(road, r"to ([\d,]+)\+ across"), "design", ROOT / "research/v4/roadmap.md", "int")
    put("plan.families", grab(road, r"across (\d+)\+ task families"), "design", ROOT / "research/v4/roadmap.md", "int")
    put("plan.pilot.lo", grab(road, r"(\d+)-\d+ item pilot"), "design", ROOT / "research/v4/roadmap.md", "int")
    put("plan.pilot.hi", grab(road, r"\d+-(\d+) item pilot"), "design", ROOT / "research/v4/roadmap.md", "int")


def atlas_numbers() -> None:
    a1 = csv("a1_systematic_share", ATLAS)
    whole = a1[a1["family"] == "(all)"].set_index("source")
    names = {"swebench_verified": "swe", "matharena": "ma", "livebench": "lb", "bbeh_phase1": "bbeh"}
    for src, short in names.items():
        put(f"atlas.{short}.items", whole.loc[src, "items"], "record", ATLAS / "a1_systematic_share.csv", "int")
        put(f"atlas.{short}.systems", whole.loc[src, "systems"], "record", ATLAS / "a1_systematic_share.csv", "int")
        put(f"atlas.{short}.share", whole.loc[src, "share_L0"], "post hoc", ATLAS / "a1_systematic_share.csv",
            digits=2)
    public = int(whole.loc[["swebench_verified", "matharena", "livebench"], "systems"].sum())
    put("atlas.public.systems", public, "record", ATLAS / "a1_systematic_share.csv", "int")
    put("atlas.public.items", int(whole.loc[["swebench_verified", "matharena", "livebench"], "items"].sum()),
        "record", ATLAS / "a1_systematic_share.csv", "int")
    put("atlas.ma.sets", a1[(a1["source"] == "matharena") & (a1["family"] != "(all)")].shape[0], "record",
        ATLAS / "a1_systematic_share.csv", "int")

    f17 = csv("f17_numbers", ATLAS).set_index("quantity")["value"]
    src = ATLAS / "f17_numbers.csv"
    for key, q, kind, d in [("f17.systems", "systems", "int", 0), ("f17.allwrong.obs", "all-wrong observed", "pct", 1),
                            ("f17.allwrong.indep", "all-wrong independent", "pct", 1),
                            ("f17.allwrong.l1", "all-wrong L1", "pct", 1), ("f17.allwrong.l0", "all-wrong L0", "pct", 1),
                            ("f17.allwrong.copula", "all-wrong copula", "pct", 1),
                            ("f17.difficulty.share", "share explained by difficulty alone", "pct", 0),
                            ("f17.corr.obs", "mean observed failure correlation", "num", 3),
                            ("f17.corr.l0", "mean L0-implied failure correlation", "num", 3),
                            ("f17.samecompany", "same-company excess", "num", 3),
                            ("f17.share", "systematic share (L0)", "num", 2),
                            ("f18.cover2", "coverage@2 (best pair)", "pct", 1), ("f18.cover39", "coverage@39", "pct", 1),
                            ("f18.best", "best single", "pct", 1), ("f18.stepauroc", "step AUROC median", "num", 2)]:
        put(key, float(f17[q]), "record" if kind == "int" else "post hoc", src, kind, d)

    prices = csv("f18_prices", ATLAS).set_index("system")
    for key, system in (("f18.minimax", "20260217_mini-v2.0.0_minimax-2-5-high"),
                        ("f18.opus", "20260217_mini-v2.0.0_claude-4-5-opus-high")):
        put(f"{key}.acc", prices.loc[system, "accuracy"], "post hoc", ATLAS / "f18_prices.csv", "pct", 1)
        put(f"{key}.usd", prices.loc[system, "usd"], "post hoc", ATLAS / "f18_prices.csv", "usd", 3)
    put("f18.price.ratio", prices.loc["20260217_mini-v2.0.0_claude-4-5-opus-high", "usd"] /
        prices.loc["20260217_mini-v2.0.0_minimax-2-5-high", "usd"], "post hoc", ATLAS / "f18_prices.csv", "num", 0)

    a5 = csv("a5_coverage", ATLAS)
    sw = a5[(a5["benchmark"] == "swebench_verified") & (a5["k"] >= 2)]
    put("a5.swe.model.lo", sw["model MAE"].min(), "post hoc", ATLAS / "a5_coverage.csv", "pct", 1)
    put("a5.swe.model.hi", sw["model MAE"].max(), "post hoc", ATLAS / "a5_coverage.csv", "pct", 1)
    put("a5.swe.indep.lo", sw["independent MAE"].min(), "post hoc", ATLAS / "a5_coverage.csv", "pct", 0)
    put("a5.swe.indep.hi", sw["independent MAE"].max(), "post hoc", ATLAS / "a5_coverage.csv", "pct", 0)
    other = a5[(a5["benchmark"] != "swebench_verified") & (a5["k"] >= 2)]
    wins = other.groupby("benchmark").apply(lambda g: bool((g["model MAE"] < g["independent MAE"]).all()))
    put("a5.other.benchmarks", len(wins), "record", ATLAS / "a5_coverage.csv", "int")
    put("a5.other.modelwins", int(wins.sum()), "post hoc", ATLAS / "a5_coverage.csv", "int")

    a6 = csv("a6_depth", ATLAS)
    put("a6.pairs", int(a6["delta a"].notna().sum()), "record", ATLAS / "a6_depth.csv", "int")


# ---------------------------------------------------------------------------------------------------------
# W1 extensions (post hoc: public data, chosen after the Atlas and the anchor were read)

def extension_numbers() -> None:
    s1 = csv("p1_summary")
    src = EXT / "p1_summary.csv"
    for scope, tag in (("all cells", "all"), ("predicted gain >= 3 points", "pred"), ("observed gain >= 3 points", "obs")):
        r = s1[(s1["k"] == 3) & (s1["scope"] == scope)].iloc[0]
        put(f"p1.{tag}.cells", r["cells"], "record", src, "int")
        for col, key in (("rule gain MAE", "rule"), ("zero-gain gain MAE", "zero"), ("mean observed gain", "obsgain"),
                         ("mean predicted gain", "predgain")):
            put(f"p1.{tag}.{key}", r[col], "post hoc", src, "pct", 1)
        msd = "gain MSE, zero-gain minus rule (points^2)"
        for suffix, key in (("", "msed"), (" lo", "msedlo"), (" hi", "msedhi")):
            put(f"p1.{tag}.{key}", r[msd + suffix], "post hoc", src, "num", 1)
        lev = "level MSE, zero-gain minus rule (points^2)"
        for suffix, key in (("", "levmsed"), (" lo", "levmsedlo"), (" hi", "levmsedhi")):
            put(f"p1.{tag}.{key}", r[lev + suffix], "post hoc", src, "num", 1)
        put(f"p1.{tag}.levrule", r["rule level MAE"], "post hoc", src, "pct", 1)
        put(f"p1.{tag}.levzero", r["zero-gain level MAE"], "post hoc", src, "pct", 1)
        put(f"p1.{tag}.corr", r["corr(predicted, observed gain)"], "post hoc", src, "num", 2)
    put("p1.all.sets", s1[(s1["k"] == 3) & (s1["scope"] == "all cells")]["sets"].iloc[0], "record", src, "int")
    an = csv("p1_anchor")
    put("p1.anchor.rule", an["rule_gain_error"].abs().mean(), "exploratory", EXT / "p1_anchor.csv", "pct", 1)
    put("p1.anchor.zero", an["zero_gain_gain_error"].abs().mean(), "exploratory", EXT / "p1_anchor.csv", "pct", 1)
    put("p1.anchor.maxgain", an["observed_gain"].max(), "exploratory", EXT / "p1_anchor.csv", "pct", 1)

    p2 = csv("p2_pairs")
    put("p2.pairs", len(p2), "record", EXT / "p2_pairs.csv", "int")
    put("p2.models", p2["model"].nunique(), "record", EXT / "p2_pairs.csv", "int")
    put("p2.modelbench", p2[["source", "model"]].drop_duplicates().shape[0], "record", EXT / "p2_pairs.csv", "int")
    pooled = csv("p2_pooled")
    for scope, tag in (("all adjacent pairs", "all"), ("one pair per model", "one")):
        for q, key, kind, d in (("delta a", "da", "num", 2), ("delta beta", "db", "num", 2),
                                ("refit a and beta minus shift", "slope", "num", 4),
                                ("base rate minus shift", "base", "num", 3), ("low as is minus shift", "none", "num", 3),
                                ("low's own items + one shift minus shift", "own", "num", 3)):
            r = pooled[(pooled["scope"] == scope) & (pooled["quantity"] == q)].iloc[0]
            for part in ("pooled", "lo", "hi"):
                put(f"p2.{tag}.{key}.{part}", r[part], "post hoc", EXT / "p2_pooled.csv", kind, d)
            put(f"p2.{tag}.{key}.tau", r["tau2"], "post hoc", EXT / "p2_pooled.csv", "num", 2)
    put("p2.dbeta.ciexcl0", int(((p2["delta beta lo"] > 0) | (p2["delta beta hi"] < 0)).sum()), "post hoc",
        EXT / "p2_pairs.csv", "int")
    excl = csv("p2_excluded")
    put("p2.excluded", len(excl), "record", EXT / "p2_excluded.csv", "int")
    put("p2.excluded.db.lo", excl["delta beta"].min(), "post hoc", EXT / "p2_excluded.csv", "num", 2)
    put("p2.excluded.db.hi", excl["delta beta"].max(), "post hoc", EXT / "p2_excluded.csv", "num", 2)

    p3 = csv("p3_pairs")
    ok = p3[p3["difference"].notna()]
    put("p3.pairs", len(ok), "record", EXT / "p3_pairs.csv", "int")
    put("p3.positive", int((ok["difference lo"] > 0).sum()), "post hoc", EXT / "p3_pairs.csv", "int")
    pp = csv("p3_pooled")
    from analysis.atlas_extend import NEAR_DOLLARS

    for scope, tag in (("all pairs", "all"), (f"dollars within a factor of {NEAR_DOLLARS}", "near")):
        r = pp[(pp["scope"] == scope) & (pp["quantity"] == "difference")].iloc[0]
        put(f"p3.{tag}.k", r["k"], "record", EXT / "p3_pooled.csv", "int")
        for part in ("pooled", "lo", "hi"):
            put(f"p3.{tag}.{part}", r[part], "post hoc", EXT / "p3_pooled.csv", "pct", 1)
    for name, model in (("opus", "opus 5.5"), ("geminimed", "gemini-3.1-pro")):
        r = ok[ok["model"] == model].iloc[-1]
        put(f"p3.{name}.diff", r["difference"], "post hoc", EXT / "p3_pairs.csv", "signed", 1)

    m = csv("p4_map")
    lone = m[(m["others"] == 0.3) & (m["repeats"] == 1)]
    put("p4.sim.lone.ds.inv", lone["Dawid-Skene inverts"].mean(), "post hoc", EXT / "p4_map.csv", "pct", 0)
    put("p4.sim.lone.fixed.inv", lone["pooled Dawid-Skene, fixed labels inverts"].mean(), "post hoc",
        EXT / "p4_map.csv", "pct", 0)
    put("p4.sim.lone.fixed.loss", -lone["pooled Dawid-Skene, fixed labels gain"].mean(), "post hoc",
        EXT / "p4_map.csv", "pct", 1)
    comp = m[(m["others"] == 0.7) & (m["sd_b"] == 0.5)]
    put("p4.sim.comp.lowshare.gain", comp["plurality gain"].mean(), "post hoc", EXT / "p4_map.csv", "signed", 1)
    comp2 = m[(m["others"] == 0.7) & (m["sd_b"] == 2.0)]
    put("p4.sim.comp.highshare.gain", comp2["plurality gain"].mean(), "post hoc", EXT / "p4_map.csv", "signed", 1)
    ps = csv("p4_panels_summary")
    lone0 = ps[(ps["kind"] == "lone strong") & (ps["calls"] == "call 0")]
    lone4 = ps[(ps["kind"] == "lone strong") & (ps["calls"] == "all 4 calls")]
    comp4 = ps[(ps["kind"] == "many competent") & (ps["calls"] == "all 4 calls")]
    put("p4.ma.lone.loss.min", -lone0[["plurality gain", "Dawid-Skene gain", "pooled Dawid-Skene gain",
                                       "pooled Dawid-Skene, fixed labels gain"]].max().max(), "post hoc",
        EXT / "p4_panels_summary.csv", "pct", 0)
    put("p4.ma.lone.loss.max", -lone0[["plurality gain", "Dawid-Skene gain", "pooled Dawid-Skene gain",
                                       "pooled Dawid-Skene, fixed labels gain"]].min().min(), "post hoc",
        EXT / "p4_panels_summary.csv", "pct", 0)
    put("p4.ma.lone.inv.lo", lone0["Dawid-Skene inverts"].min(), "post hoc", EXT / "p4_panels_summary.csv", "pct", 0)
    put("p4.ma.lone.inv.hi", lone0["Dawid-Skene inverts"].max(), "post hoc", EXT / "p4_panels_summary.csv", "pct", 0)
    put("p4.ma.lone4.ds.gain", lone4["Dawid-Skene gain"].max(), "post hoc", EXT / "p4_panels_summary.csv", "signed", 1)
    put("p4.ma.lone4.plur.gain", lone4["plurality gain"].min(), "post hoc", EXT / "p4_panels_summary.csv", "signed", 1)
    put("p4.ma.comp4.gain", comp4["plurality gain"].mean(), "post hoc", EXT / "p4_panels_summary.csv", "signed", 1)
    put("p4.ma.lone.fixedinv.lo", lone0["pooled Dawid-Skene, fixed labels inverts"].min(), "post hoc",
        EXT / "p4_panels_summary.csv", "pct", 0)
    put("p4.ma.lone.fixedinv.hi", lone0["pooled Dawid-Skene, fixed labels inverts"].max(), "post hoc",
        EXT / "p4_panels_summary.csv", "pct", 0)
    for kind, tag in (("lone strong", "lone"), ("many competent", "comp")):
        r = ps[(ps["kind"] == kind) & (ps["calls"] == "call 0") & (ps["systems"] == 3)].iloc[0]
        put(f"p4.ma.match.{tag}.own", r["best system's own vote, same calls"], "post hoc", EXT / "p4_panels_summary.csv",
            "pct", 1)
        for name, key in (("plurality", "plur"), ("Dawid-Skene", "ds"), ("pooled Dawid-Skene, fixed labels", "fixed")):
            put(f"p4.ma.match.{tag}.{key}", r[f"{name} minus best system's own vote"], "post hoc",
                EXT / "p4_panels_summary.csv", "signed", 1)

    s5 = csv("p5_summary")
    sw = s5[s5["source"] == "swebench_verified"].set_index("k")
    src = EXT / "p5_summary.csv"
    put("p5.swe.room2", sw.loc[2, "room"], "post hoc", src, "pct", 1)
    put("p5.swe.room5", sw.loc[5, "room"], "post hoc", src, "pct", 1)
    put("p5.swe.price2", sw.loc[2, "extra usd per point of room"], "post hoc", src, "usd", 3)
    put("p5.swe.price5", sw.loc[5, "extra usd per point of room"], "post hoc", src, "usd", 3)
    put("p5.swe.beat.sol", sw["above top at its dollars, eta sol_low bbeh (0.70)"].max(), "post hoc", src, "pct", 0)
    put("p5.swe.beat.perfect", sw["above top at its dollars, eta 1 (perfect selector)"].max(), "post hoc", src, "pct", 0)
    ma = s5[s5["source"].str.startswith("matharena")]
    put("p5.ma.room.lo", ma["room"].min(), "post hoc", src, "pct", 1)
    put("p5.ma.room.hi", ma["room"].max(), "post hoc", src, "pct", 1)
    lb = s5[s5["source"].str.startswith("livebench")]
    put("p5.lb.room.hi", lb["room"].max(), "post hoc", src, "pct", 1)

    p6 = csv("p6_shares")
    src = EXT / "p6_shares.csv"
    for name, short in (("swebench_verified", "swe"), ("matharena", "ma"), ("livebench", "lb"), ("bbeh_phase1", "bbeh"),
                        ("swebench_verified (39 with details)", "swe39")):
        r = p6[(p6["source"] == name) & (p6["quantity"] == "(all) L0")]
        if r.empty:
            continue
        r = r.iloc[0]
        for col, part in (("share", "est"), ("item lo", "ilo"), ("item hi", "ihi"), ("half-split min", "hmin"),
                          ("half-split max", "hmax")):
            put(f"p6.{short}.{part}", r[col], "post hoc", src, "num", 2)
    fam = p6[(p6["quantity"] != "(all) L0") & (p6["quantity"] != "(all) L1 median")]
    put("p6.families", len(fam), "record", src, "int")

    s7 = csv("p7_summary").set_index("k")
    src = EXT / "p7_summary.csv"
    for k in (3, 5):
        put(f"p7.k{k}.panels", s7.loc[k, "panels"], "record", src, "int")
        put(f"p7.k{k}.gain", s7.loc[k, "mean observed vote"] - s7.loc[k, "mean member accuracy (zero-gain)"],
            "post hoc", src, "pct", 1)
        for col, key in (("MAE factor model", "model"), ("bias factor model", "bias"), ("MAE zero-gain", "zero"),
                         ("MAE independence", "indep"), ("MAE zero-gain minus factor model", "dz"),
                         ("MAE independence minus factor model", "di"), ("bias zero-gain", "zbias"),
                         ("bias independence", "ibias")):
            put(f"p7.k{k}.{key}", s7.loc[k, col], "post hoc", src, "pct", 1)
        for name, key in (("zero-gain", "setszero"), ("independence", "setsindep")):
            put(f"p7.k{k}.{key}", s7.loc[k, f"sets where the factor model beats {name}"], "post hoc", src, "int")
        put(f"p7.k{k}.sets", s7.loc[k, "sets"], "record", src, "int")
    put("p7.sets", s7.loc[3, "sets"], "record", src, "int")

    t8 = csv("p8_tail")
    src = EXT / "p8_tail.csv"
    sw8 = t8[(t8["benchmark"] == "swebench_verified") & (t8["k"].astype(str) == "all")].iloc[0]
    put("p8.swe.members", sw8["members"], "record", src, "int")
    put("p8.swe.items", sw8["test items"], "record", src, "int")
    put("p8.swe.n", sw8["all-wrong items"], "record", src, "int")
    for col, key, d in (("observed all-wrong", "obs", 1), ("factor model", "model", 1), ("copula", "copula", 1),
                        ("independence", "indep", 2), ("observed lo (Clopper-Pearson)", "cplo", 1),
                        ("observed hi (Clopper-Pearson)", "cphi", 1),
                        ("factor model, test-item difficulty", "modelitem", 1),
                        ("fit systems all wrong on the test items", "others", 1)):
        put(f"p8.swe.{key}", sw8[col], "post hoc", src, "pct", d)
    for col, key in (("observed / factor model", "rmodel"), ("observed / factor model lo", "rmodello"),
                     ("observed / factor model hi", "rmodelhi"), ("observed / copula", "rcopula"),
                     ("observed / copula lo", "rcopulalo"), ("observed / copula hi", "rcopulahi")):
        put(f"p8.swe.{key}", sw8[col], "post hoc", src, "num", 2)
    sw20 = t8[(t8["benchmark"] == "swebench_verified") & (t8["k"].astype(str) == "20")].iloc[0]
    for col, key in (("observed all-wrong", "obs20"), ("factor model", "model20"), ("copula", "copula20")):
        put(f"p8.swe.{key}", sw20[col], "post hoc", src, "pct", 1)
    m5 = t8[t8["benchmark"].str.startswith("matharena") & (t8["k"].astype(str) == "5")]
    put("p8.ma.sets", len(m5), "record", src, "int")
    put("p8.ma.model.under", int((m5["observed minus factor model lo"] > 0).sum()), "post hoc", src, "int")
    put("p8.ma.copula.under", int((m5["observed minus copula lo"] > 0).sum()), "post hoc", src, "int")
    ratios = m5["observed / factor model"].dropna()
    put("p8.ma.rmodel.max", ratios.max(), "post hoc", src, "num", 1)
    lb5 = t8[t8["benchmark"].str.startswith("livebench") & t8["k"].astype(str).isin(["5", "10"])]
    put("p8.lb.rmodel.lo", lb5["observed / factor model"].min(), "post hoc", src, "num", 2)
    put("p8.lb.rmodel.hi", lb5["observed / factor model"].max(), "post hoc", src, "num", 2)


# ---------------------------------------------------------------------------------------------------------
# Phase 1-3 (findings ledger) and the API anchor (read.md, hand-back)

def phase1_numbers() -> None:
    src = FINDINGS
    f1, f2, f3, f4 = finding("F1"), finding("F2"), finding("F3"), finding("F4")
    put("f1.rho", grab(f1, r"rho ([\d.]+)"), "preregistered-descriptive", src, "num", 2)
    put("f1.neff5", grab(f1, r"5 calls are worth ([\d.]+)"), "preregistered-descriptive", src, "num", 2)
    put("f2.neff12", grab(f2, r"n_eff ([\d.]+)"), "preregistered-descriptive", src, "num", 2)
    put("f3.sol.acc", grab(f3, r"Sol low ([\d.]+)%") / 100, "preregistered-descriptive", src, "pct", 1)
    put("f3.sol.usd", grab(f3, r"Sol low [\d.]+% at \$([\d.]+)"), "preregistered-descriptive", src, "usd", 4)
    put("f3.sonnet.acc", grab(f3, r"Sonnet off ([\d.]+)%") / 100, "preregistered-descriptive", src, "pct", 1)
    put("f3.sonnet.usd", grab(f3, r"Sonnet off [\d.]+% at \$([\d.]+)"), "preregistered-descriptive", src, "usd", 4)
    put("f3.haiku.acc", grab(f3, r"Haiku off ([\d.]+)%") / 100, "preregistered-descriptive", src, "pct", 1)
    put("f3.luna.acc", grab(f3, r"Luna none ([\d.]+)%") / 100, "preregistered-descriptive", src, "pct", 1)
    put("f4.haiku5", grab(f4, r"Haiku x5 plurality ([\d.]+)%") / 100, "exploratory", src, "pct", 1)
    put("f4.panel12", grab(f4, r"12-call plurality ([\d.]+)%") / 100, "exploratory", src, "pct", 1)
    put("f4.cascades", grab(f4, r"0 of (\d+) cascade"), "post hoc", src, "int")
    f5 = finding("F5")
    put("f5.diff", grab(f5, r"^(-?[\d.]+) points"), "confirmatory", src, "num", 1)
    put("f5.escalates", grab(f5, r"escalates (\d+)%") / 100, "confirmatory", src, "pct", 0)
    put("phase1.items", grab(finding("F1", 3), r"BBEH (\d+)"), "record", src, "int")
    put("f4.within", grab(f4, r"within (\d+) points"), "post hoc", src, "int")
    put("f4.panel.calls", grab(f4, r"(\d+)-call plurality"), "record", src, "int")
    put("f1.calls", grab(f1, r"(\d+) calls are worth"), "record", src, "int")
    put("f4.dollars", grab(f4, r"at ([\d.]+)x Sol"), "post hoc", src, "num", 1)
    f7 = finding("F7")
    put("f7.perturbed", grab(f7, r"(\d+)/\d+"), "preregistered-descriptive", src, "int")
    put("f7.of", grab(f7, r"\d+/(\d+)"), "preregistered-descriptive", src, "int")
    f10 = finding("F10")
    put("f10.on", grab(f10, r"([\d.]+)% at") / 100, "exploratory", src, "pct", 0)
    put("f10.off", grab(f10, r"vs ([\d.]+)% off") / 100, "exploratory", src, "pct", 0)
    f11 = finding("F11")
    put("f11.sol.est", grab(f11, r"Sol estimated ([\d.]+)%") / 100, "exploratory", src, "pct", 1)
    put("f11.sol.true", grab(f11, r"true ([\d.]+)%") / 100, "exploratory", src, "pct", 1)
    f12 = finding("F12")
    put("f12.agg", grab(f12, r"BBEH Brier ([\d.]+)"), "exploratory", src, "num", 3)
    put("f12.vote", grab(f12, r"vote share ([\d.]+)"), "exploratory", src, "num", 3)
    f16 = finding("F16")
    put("f16.fake", grab(f16, r"\+([\d.]+) points"), "record", src, "num", 1)
    f9 = finding("F9")
    put("f9.diff", grab(f9, r"\+([\d.]+) Brier"), "exploratory", src, "num", 4)


def anchor_numbers() -> None:
    src = READ
    fam = read_table(["test", "estimate", "void", "p", "passes"], READ).set_index("test")
    ah2 = read_table(["vendor", "k", "difference", "lo", "hi", "p"], READ).set_index("vendor")
    for v in ("haiku", "luna"):
        for col, key in (("difference", "diff"), ("lo", "lo"), ("hi", "hi")):
            put(f"ah2.{v}.{key}", ah2.loc[v, col], "confirmatory", src, "pct", 1)
        put(f"ah2.{v}.k", ah2.loc[v, "k"], "confirmatory", src, "int")
        put(f"ah2.{v}.vs3", ah2.loc[v, "difference_vs_3vote"], "exploratory", src, "pct", 1)
        put(f"ah2.{v}.vs3lo", ah2.loc[v, "lo_3vote"], "exploratory", src, "pct", 1)
        put(f"ah2.{v}.vs3hi", ah2.loc[v, "hi_3vote"], "exploratory", src, "pct", 1)
    put("ah2.p", fam.loc["AH2", "p"], "confirmatory", src, "num", 3)
    ah3 = read_table(["test", "estimate", "upper", "gain_estimate", "gain_upper"], READ).iloc[0]
    for col, key in (("estimate", "mae"), ("upper", "upper"), ("gain_estimate", "gain"), ("gain_upper", "gainupper")):
        put(f"ah3.{key}", ah3[col], "confirmatory", src, "pct", 1)
    arms = read_table(["arm", "q", "predicted", "observed", "predicted_gain"], READ)
    put("ah3.gain.lo", arms["observed_gain"].min(), "confirmatory", src, "pct", 1)
    put("ah3.gain.hi", arms["observed_gain"].max(), "confirmatory", src, "pct", 1)
    ah1 = read_table(["test", "estimate", "gap_points", "void", "p", "lo", "hi"], READ).iloc[0]
    put("ah1.r", ah1["estimate"], "exploratory", src, "num", 2)
    put("ah1.lo", ah1["lo"], "exploratory", src, "num", 2)
    put("ah1.hi", ah1["hi"], "exploratory", src, "num", 2)
    put("ah1.gap", ah1["gap_points"] / 100, "exploratory", src, "pct", 1)
    ah4 = read_table(["test", "estimate", "eta_easy", "eta_hard", "p", "lo", "hi"], READ).iloc[0]
    for col, key in (("eta_easy", "easy"), ("eta_hard", "hard"), ("estimate", "diff"), ("lo", "lo"), ("hi", "hi")):
        put(f"ah4.{key}", ah4[col], "exploratory", src, "num", 2)
    width = read_table(["items", "arm", "k", "n", "accuracy"], READ)

    def arm(items, name, k=1):
        return width[(width["items"] == items) & (width["arm"] == name) & (width["k"] == k)].iloc[0]

    put("anchor.items.bbeh", arm("bbeh", "sol_low")["n"], "record", src, "int")
    put("anchor.items.math", arm("math", "sol_low")["n"], "record", src, "int")
    put("anchor.items.all", arm("all", "sol_low")["n"], "record", src, "int")
    for items in ("bbeh", "math", "all"):
        put(f"anchor.sol.{items}", arm(items, "sol_low")["accuracy"], "exploratory", src, "pct", 1)
        put(f"anchor.sol3.{items}", arm(items, "sol_low", 3)["accuracy"], "exploratory", src, "pct", 1)
    put("anchor.solmed.bbeh", arm("bbeh", "sol_med")["accuracy"], "exploratory", src, "pct", 1)
    put("anchor.sol.bbeh.usd", arm("bbeh", "sol_low")["dollars_per_item"], "exploratory", src, "usd", 4)
    put("anchor.sol.math.usd", arm("math", "sol_low")["dollars_per_item"], "exploratory", src, "usd", 3)
    put("anchor.sol3.math.usd", arm("math", "sol_low", 3)["dollars_per_item"], "exploratory", src, "usd", 3)
    judges = read_table(["judge", "items", "n", "judge_accuracy"], READ)
    j = judges[(judges["judge"] == "sol_low_judge") & (judges["items"] == "bbeh")].iloc[0]
    for col, key, kind in (("judge_accuracy", "acc", "pct"), ("eta", "eta", "num"), ("eta_lo", "etalo", "num"),
                           ("eta_hi", "etahi", "num"), ("vs_best", "vsbest", "pct"), ("vs_best_lo", "vsbestlo", "pct"),
                           ("vs_best_hi", "vsbesthi", "pct"), ("vs_plurality", "vsplur", "pct"),
                           ("best_single", "bestpool", "pct"), ("coverage", "coverage", "pct")):
        put(f"judge.sol.bbeh.{key}", j[col], "exploratory", src, kind, 1 if kind == "pct" else 2)
    jm = judges[(judges["judge"] == "sol_low_judge") & (judges["items"] == "math")].iloc[0]
    put("judge.sol.math.vsbest", jm["vs_best"], "exploratory", src, "pct", 1)
    put("judge.sol.math.coverage", jm["coverage"], "exploratory", src, "pct", 1)
    put("judge.sol.bbeh.usd", j["judge_dollars"] + j["pool_dollars"], "exploratory", src, "usd", 4)
    checks = read_table(["check", "items", "n", "no_verdict"], READ)
    for name, key in (("sol_low_check", "sol"), ("haiku_low_check", "haiku")):
        r = checks[(checks["check"] == name) & (checks["items"] == "all")].iloc[0]
        put(f"check.{key}.accept", r["accept_rate"], "exploratory", src, "pct", 0)
        put(f"check.{key}.auroc", r["auroc"], "exploratory", src, "num", 2)
        put(f"check.{key}.n", r["n"], "record", src, "int")
    lf = read_table(["method", "arm", "true_accuracy", "estimate"], READ)
    son = lf[(lf["method"] == "pooled") & (lf["arm"] == "sonnet_off")].iloc[0]
    put("lf.sonnet.est", son["estimate"], "exploratory", src, "pct", 0)
    put("lf.sonnet.true", son["true_accuracy"], "exploratory", src, "pct", 0)
    put("lf.answer", son["label_free_answer"], "exploratory", src, "pct", 1)
    tail = read_table(["k", "observed", "independent", "L0", "L1", "copula", "rho", "items"], READ)
    for items in ("bbeh", "math", "all"):
        put(f"anchor.share.{items}", tail[tail["items"] == items]["systematic_share_L0"].iloc[0], "exploratory", src,
            "num", 2)
    # auditor post-read numbers, quoted in the hand-back (audit 96's wording)
    text = HANDBACK.read_text()
    # computed by the auditor after both blocks were read: post hoc by the ledger's definition (audit W1-1, item 8)
    put("judge.sol.vsown", -grab(text, r"It is ([\d.]+) below one Sol low call") / 100, "post hoc", HANDBACK,
        "pct", 1, "auditor post-read")
    put("judge.sol.vsown.lo", grab(text, r"one Sol low call \((-[\d.]+) to") / 100, "post hoc", HANDBACK, "pct", 1)
    put("judge.sol.vsown.hi", grab(text, r"one Sol low call \(-[\d.]+ to (-[\d.]+)\)") / 100, "post hoc", HANDBACK,
        "pct", 1)
    put("judge.sol.vsown.ratio", grab(text, r"one Sol low call \(-[\d.]+ to -[\d.]+\) at ([\d.]+)x"), "post hoc",
        HANDBACK, "num", 1)
    put("judge.haiku.vsown", -grab(text, r"Haiku high judge was ([\d.]+) below") / 100, "post hoc", HANDBACK,
        "pct", 1, "auditor post-read")
    # the same gaps as positive numbers, for sentences that say "below"
    put("judge.sol.below", grab(text, r"It is ([\d.]+) below one Sol low call") / 100, "post hoc", HANDBACK, "pct", 1)
    put("judge.haiku.below", grab(text, r"Haiku high judge was ([\d.]+) below") / 100, "post hoc", HANDBACK, "pct", 1)
    # AH2's dollars per item (the read prints them rounded to 3 decimals; the hand-back gives them to 5)
    deep_h = grab(text, r"one effort-low call \(\$([\d.]+) per item[;)]")  # E6's run review added a note after ";"
    wide_h = grab(text, r"Haiku-off 2-vote \(\$([\d.]+)\)")
    deep_l = grab(text, r"one low call \(\$([\d.]+)\)")
    wide_l = grab(text, r"Luna-none 3-vote \(\$([\d.]+)\)")
    put("ah2.haiku.ratio", deep_h / wide_h, "confirmatory", HANDBACK, "num", 2)
    put("ah2.luna.ratio", deep_l / wide_l, "confirmatory", HANDBACK, "num", 2)
    put("ah2.p.holm", grab(text, r"passes Holm at 5%, p = ([\d.]+)"), "confirmatory", HANDBACK, "num", 3)


# ---------------------------------------------------------------------------------------------------------
# the CD read (session E6): placeholders until research/v4/cd/read.md is on main

CD_KEYS = ["cd.status"]


def cd_numbers() -> None:
    if CD_READ.exists():
        put("cd.status", "read", "record", CD_READ, "text")
    else:
        put("cd.status", "pending", "pending", "research/v4/cd/read.md (session E6, not yet on main)", "text")


# ---------------------------------------------------------------------------------------------------------
# the open-weight testbed design (session T1)

def testbed_numbers() -> None:
    power = pd.read_csv(ROOT / "research/v4/testbed/power.csv")
    src = ROOT / "research/v4/testbed/power.csv"
    pw = power[power["role"] == "power"]
    for prefix, key in (("T1 primary", "t1"), ("T2 primary", "t2"), ("T3 primary", "t3"), ("T4 primary", "t4"),
                        ("T5 primary:", "t5"), ("T1 secondary: shared", "t1shock")):
        put(f"testbed.power.{key}", pw[pw["test"].str.startswith(prefix)]["rate"].iloc[0], "design", src, "num", 2)
    tasks = json.loads((ROOT / "research/v4/anchor/tasks.json").read_text())
    cfg = yaml.safe_load((ROOT / "configs/testbed/tasks.yaml").read_text())
    put("testbed.items.bbeh", len(tasks["t1_bbeh"]), "design", ROOT / "research/v4/anchor/tasks.json", "int")
    put("testbed.items.math", cfg["math"]["n"], "design", ROOT / "configs/testbed/tasks.yaml", "int")
    put("testbed.items.code", cfg["code"]["n"], "design", ROOT / "configs/testbed/tasks.yaml", "int")
    put("testbed.items.all", len(tasks["t1_bbeh"]) + cfg["math"]["n"] + cfg["code"]["n"], "design",
        ROOT / "configs/testbed/tasks.yaml", "int")
    est = read_table(["machine ($/h on 2026-10-26)", "pilot"], ROOT / "research/v4/testbed/README.md")
    h200 = est[est["machine ($/h on 2026-10-26)"].str.startswith("H200")].iloc[0]
    put("testbed.gpu.pilot", grab(h200["pilot"], r"\$([\d.]+)"), "design", ROOT / "research/v4/testbed/README.md",
        "usd", 1)
    put("testbed.gpu.stage1", grab(h200["stage 1 after the drop rule"], r"\$([\d.]+)"), "design",
        ROOT / "research/v4/testbed/README.md", "usd", 0)


# ---------------------------------------------------------------------------------------------------------
# process: runs, spend per session, audits

SESSION_RULES = [  # (run-name pattern, session); first match wins
    (r"^p0_calib_(luna_low|gpt_small)$", "Pilot, session 3"),
    (r"^p[0-4]w?_", "Pilot, session 4"),
    (r"^(m\d_|market_)", "Market town, session 5"),
    (r"^w\d", "v3, session S1"),
    (r"^e[1-3]\d", "Evidence, session E4"),
    (r"^e5\d", "v4, session E5"),
]


def session_of(run: str) -> str:
    for pattern, name in SESSION_RULES:
        if re.search(pattern, run):
            return name
    return "other"


def runs_table() -> pd.DataFrame:
    """One row per run folder with a status file: state, stop reason, date, and the run's spend as the difference of
    the cumulative spend the status files record, in order of that total (runs are mostly sequential; a status time shared by several runs is one
    group whose spend is booked on its first run). Runs whose status records no spend total (the free market
    simulation) are booked at $0."""
    rows = []
    for f in sorted(glob.glob(str(ROOT / "results/*/status.json"))):
        d = json.loads(Path(f).read_text())
        m = re.search(r"-(\d+)$", d.get("run_id", ""))
        total = (d.get("budget") or {}).get("spent_total_usd")
        rows.append({"run": Path(f).parent.name, "state": d.get("state"), "reason": d.get("reason") or "",
                     "time": int(m.group(1)) if m else None, "total": total})
    t = pd.DataFrame(rows)
    # ordered by the cumulative total each status records (the ledger only grows), so runs that overlapped in time
    # (two parallel pipelines) never book a negative difference; the sum is still the last total
    priced = t[t["total"].fillna(0) > 0].sort_values(["total", "time", "run"])
    priced = priced.assign(spend=priced["total"].diff().fillna(priced["total"]))
    t = t.merge(priced[["run", "spend"]], on="run", how="left")
    t["spend"] = t["spend"].fillna(0.0)
    t["date"] = pd.to_datetime(t["time"], unit="s").dt.strftime("%Y-%m-%d")
    t["session"] = t["run"].map(session_of)
    return t.sort_values(["time", "run"]).reset_index(drop=True)


def process_numbers(runs: pd.DataFrame) -> None:
    src = "results/*/status.json"
    put("spend.total", runs["spend"].sum(), "record", src, "usd", 2)
    put("runs.count", len(runs), "record", src, "int")
    put("runs.stopped", int((runs["state"] == "stopped").sum()), "record", src, "int")
    put("runs.failed", int((runs["state"] == "failed").sum()), "record", src, "int")
    by = runs.groupby("session")["spend"].sum()
    for name, key in (("Pilot, session 3", "s3"), ("Pilot, session 4", "s4"), ("Market town, session 5", "s5"),
                      ("v3, session S1", "s1"), ("Evidence, session E4", "e4"), ("v4, session E5", "e5")):
        put(f"spend.{key}", by.get(name, 0.0), "record", src, "usd", 2)
    audit = (ROOT / "research/audit_log.md").read_text()
    # one verdict per audit entry ("## " heading): its "VERDICT: X" line, else the first GO/ADJUST/STOP word of its
    # opening lines (later entries open with "ADJUST; ..."); entries without a verdict (smoke reports) count as audits
    entries = [b for b in re.split(r"\n(?=## )", audit) if b.startswith("## ")]
    verdicts = []
    for entry in entries:
        m = re.search(r"VERDICT: (GO|ADJUST|STOP)", entry) or re.search(r"\b(GO|ADJUST|STOP)\b", "\n".join(entry.split("\n")[1:6]))
        if m:
            verdicts.append(m.group(1))
    counts = pd.Series(verdicts).value_counts()
    put("audits.count", len(entries), "record", ROOT / "research/audit_log.md", "int")
    for v in ("GO", "ADJUST", "STOP"):
        put(f"audits.{v.lower()}", int(counts.get(v, 0)), "record", ROOT / "research/audit_log.md", "int")


# ---------------------------------------------------------------------------------------------------------
# series for the page and the figures

def series(runs: pd.DataFrame) -> dict:
    prices = csv("f18_prices", ATLAS).dropna(subset=["usd"]).sort_values("usd")
    frontier = set(csv("a7_frontier", ATLAS).query("benchmark == 'swebench_verified'")["system"])
    t8 = csv("p8_tail")
    tail = t8[t8["benchmark"] == "swebench_verified"][["members", "observed all-wrong", "factor model", "copula",
                                                        "independence"]]
    a2 = csv("a2_tail", ATLAS).query("benchmark == 'swebench_verified'")[["k", "observed", "independent", "L1"]]
    p2 = csv("p2_pairs")
    p3 = csv("p3_pairs").dropna(subset=["difference"])
    ah2 = read_table(["vendor", "k", "difference", "lo", "hi", "p"], READ)
    judges = read_table(["judge", "items", "n", "judge_accuracy"], READ)
    width = read_table(["items", "arm", "k", "n", "accuracy"], READ)
    m = csv("p4_map")
    comp = m.groupby(["others", "sd_b", "repeats"])[["plurality gain", "Dawid-Skene gain",
                                                    "pooled Dawid-Skene, fixed labels gain",
                                                    "Dawid-Skene inverts"]].mean().reset_index()
    sessions = runs.groupby("session").agg(first=("date", "min"), last=("date", "max"), runs=("run", "size"),
                                           spend=("spend", "sum")).reset_index()
    findings = []
    for line in FINDINGS.read_text().splitlines():
        cells = [c.strip() for c in line.strip("|").split("|")]
        if len(cells) >= 7 and re.fullmatch(r"F\d+", cells[0]):
            findings.append({"id": cells[0], "finding": cells[1], "number": cells[2], "n": cells[3],
                             "status": cells[4], "source": cells[5], "caveat": cells[6]})
    prices_cfg = yaml.safe_load((ROOT / "configs" / "pricing.yaml").read_text())
    return {
        "frontier": [{"system": r.system.split("_", 2)[-1], "accuracy": r.accuracy, "usd": r.usd,
                      "frontier": r.system in frontier} for r in prices.itertuples()],
        "tail_heldout": tail.rename(columns={"observed all-wrong": "observed", "factor model": "model"}).to_dict("records"),
        "tail_insample": a2.to_dict("records"),
        "depth_pairs": p2[["source", "model", "low", "high", "items", "acc low", "acc high", "delta a", "delta a lo",
                           "delta a hi", "delta beta", "delta beta lo", "delta beta hi"]].to_dict("records"),
        "depth_vs_width": p3[["model", "low", "high", "items", "deep acc", "wide acc", "deep / wide dollars",
                              "difference", "difference lo", "difference hi"]].to_dict("records"),
        "ah2": ah2[["vendor", "k", "difference", "lo", "hi"]].to_dict("records"),
        "judges": judges[["judge", "items", "judge_accuracy", "best_single", "coverage", "eta"]].to_dict("records"),
        "width_table": width.to_dict("records"),
        "label_free_map": comp.to_dict("records"),
        "sessions": sessions.to_dict("records"),
        "runs": runs.assign(audits=run_audits(runs))[["run", "session", "date", "state", "reason", "spend",
                                                      "audits"]].to_dict("records"),
        "findings": findings,
        "prices": {k: v for k, v in prices_cfg.items() if isinstance(v, dict)},
        "one_item": one_item(),
        "timeline": timeline(runs),
        "page_findings": page_findings(),
        "roadmap": (ROOT / "research/v4/roadmap.md").read_text(),
    }


def tex(display: str) -> str:
    """A display string made safe for LaTeX text (dollar and percent signs escaped, a leading minus as a minus)."""
    out = display.replace("$", "\\$").replace("%", "\\%")
    # a leading minus sign typeset as a minus (in text and in math), not a hyphen
    return re.sub(r"^(\\\$)?-(?=[\d.])", lambda m: (m.group(1) or "") + "\\ensuremath{-}", out)


def one_item() -> dict:
    """The page's "follow one item" walk-through, from the anchor's BBEH call files (run-time grades; the read regraded
    against gold and differs by up to a point): the six calls of the two cheap pools (Haiku off and Luna low, three
    each), their plurality, a consensus exit at 4 of 6 agreeing calls, the Sol low judge's pick among the pools'
    distinct answers, and one Sol low call answering alone. The item is the first (by id) where the pools disagree,
    their plurality is wrong, the judge is wrong and Sol alone is right: the failure the paper describes. Run-time
    grades put the judge about 4 points below the read, so no rate is computed from them here; the page cites the
    read's rates."""
    def calls(run: str, ref: str) -> pd.DataFrame:
        c = pd.read_csv(ROOT / f"results/{run}/calls.csv", usecols=["item", "ref", "prompt", "call", "answer", "parsed",
                                                                    "correct", "cost_usd", "meta_task"])
        return c[(c["ref"] == ref) & (c["prompt"] == "base")]

    haiku, luna = calls("e51_haiku_bbeh", "haiku_nothink"), calls("e51_luna_bbeh", "luna_low_ev")
    sol = calls("e51_sol_bbeh", "sol61_low")
    sol = sol[sol["call"] == 0].set_index("item")
    judge = pd.read_csv(ROOT / "results/e51_judge_open_bbeh/calls.csv", usecols=["item", "answer", "correct", "cost_usd"])
    judge = judge.set_index("item")
    pool = pd.concat([haiku.assign(arm="Haiku off"), luna.assign(arm="Luna low")])
    pool = pool[pool["call"] < 3]
    rows = []
    for item, g in pool.groupby("item"):
        if item not in judge.index or item not in sol.index:
            continue
        parsed = g[g["parsed"] == True]  # noqa: E712 (a nullable column)
        counts = parsed["answer"].astype(str).value_counts()
        top = counts[counts == counts.max()].index if len(counts) else []
        right = parsed.groupby(parsed["answer"].astype(str))["correct"].max()
        rows.append({"item": item, "task": g["meta_task"].iloc[0], "candidates": len(counts),
                     "agree": int(counts.max()) if len(counts) else 0,
                     "plurality": float(np.mean([right[a] for a in top])) if len(top) else 0.0,
                     "judge": float(judge.loc[item, "correct"]), "sol": float(sol.loc[item, "correct"])})
    t = pd.DataFrame(rows)
    pick = t[(t["candidates"] >= 2) & (t["plurality"] == 0) & (t["judge"] == 0) & (t["sol"] == 1)].sort_values("item")
    item = pick["item"].iloc[0]
    g = pool[pool["item"] == item].sort_values(["arm", "call"])

    def short(a) -> str:
        a = "" if pd.isna(a) else str(a)
        return a if len(a) <= 60 else a[:57] + "..."

    return {"item": item, "task": t.set_index("item").loc[item, "task"], "items": len(t),
            "calls": [{"arm": r.arm, "call": int(r.call), "answer": short(r.answer), "parsed": bool(r.parsed),
                       "correct": float(r.correct), "usd": float(r.cost_usd)} for r in g.itertuples()],
            "exit_rule": 4, "agree": int(t.set_index("item").loc[item, "agree"]),
            "judge": {"answer": short(judge.loc[item, "answer"]), "correct": float(judge.loc[item, "correct"]),
                      "usd": float(judge.loc[item, "cost_usd"])},
            "sol": {"answer": short(sol.loc[item, "answer"]), "correct": float(sol.loc[item, "correct"]),
                    "usd": float(sol.loc[item, "cost_usd"])},
            "grades": "run-time grades from results/e51_*_bbeh/calls.csv"}


# (id, name, the log header that opens it, what it did, the question it worked on); dates come from the header and
# spend from the run files (SESSION_RULES), so only the words are written here
SESSIONS = [
    ("1", "Pilot, session 1", r"session 1: pilot start", "Pilot set-up: tasks, configs, the spend governor, the guard "
     "hook; free work while API keys were blocked.", "pruning"),
    ("2", "Pilot, session 2", r"session 2: protocol v2", "Protocol v2: the question became where a network's accuracy "
     "comes from; a factorial grid replaced the full landscape.", "pruning"),
    ("3", "Pilot, session 3", r"session 3: keys present", "First paid calls: the P0 calibration.", "pruning"),
    ("4", "Pilot, session 4", r"session 4: Anthropic access restored", "Pilot P0-P4 on Omni-MATH and BBEH: the gate, "
     "dense against single, the senior-model control, the factorial grid.", "pruning"),
    ("5", "Market town, session 5", r"session 5: market town", "A side study: LLM traders in a double auction.",
     "pruning"),
    ("S1", "v3, session S1", r"v3 session S1", "Data-source ladders, the W0 band check and the W2-A conviction desk.",
     "evidence"),
    ("ins", "Agent insurance", r"Session: agent insurance", "A free side study on insuring agent errors.", "evidence"),
    ("E1", "Evidence, session E1", r"evidence session E1", "Phase 0 groundwork for evidence per dollar.", "evidence"),
    ("E2", "Evidence, session E2", r"evidence session E2", "Kevin's decisions; free work only.", "evidence"),
    ("E3", "Evidence, session E3", r"evidence session E3", "Overnight, unattended: sealing and preregistrations.",
     "evidence"),
    ("E4", "Evidence, session E4", r"evidence session E4", "Phase 1-3 paid runs on BBEH and ForecastBench; the "
     "lockbox; cascades.", "evidence"),
    ("E5", "v4, session E5", r"E5 section 2", "The Atlas on public data, two landscape scans and the API anchor "
     "(AH1-AH4), read once.", "v4"),
    ("T1", "Open-weight testbed, session T1", r"session T1", "The open-weight testbed built and tested offline, its "
     "preregistration and the GPU runbook.", "v4"),
    ("W1", "Paper and record, session W1", r"session W1", "Atlas extensions P1-P8, the paper draft, this record and "
     "the roadmap.", "v4"),
    ("E6", "Depth review, session E6", None, "The CD read and a review of every run (in progress on depth_review).",
     "v4"),
]
SPEND_SESSION = {"Pilot, session 3": "3", "Pilot, session 4": "4", "Market town, session 5": "5",
                 "v3, session S1": "S1", "Evidence, session E4": "E4", "v4, session E5": "E5"}
MONTHS = {"Oct": "10", "Nov": "11"}


def timeline(runs: pd.DataFrame) -> list[dict]:
    headers = [line for line in (ROOT / "research/log.md").read_text().splitlines() if line.startswith("## ")]
    spend = runs.groupby(runs["session"].map(SPEND_SESSION))["spend"].sum()
    count = runs.groupby(runs["session"].map(SPEND_SESSION))["run"].size()
    out = []
    for sid, name, pattern, what, question in SESSIONS:
        date = "pending"
        if pattern is not None:
            line = next(h for h in headers if re.search(pattern, h))
            m = re.search(r"(\d{4}-\d{2}-\d{2})", line) or re.search(r"(Oct|Nov) (\d+)", line)
            date = m.group(1) if m.lastindex == 1 else f"2026-{MONTHS[m.group(1)]}-{int(m.group(2)):02d}"
        out.append({"id": sid, "name": name, "date": date, "what": what, "question": question,
                    "spend": float(spend.get(sid, 0.0)), "runs": int(count.get(sid, 0)),
                    "status": "pending" if pattern is None else "done"})
    return out


def run_audits(runs: pd.DataFrame) -> pd.Series:
    """Per run: the audits whose heading names it (research/audit_log.md)."""
    heads = re.findall(r"^## [^\n]*?audit ([\w-]+): ([^\n]*)$", (ROOT / "research/audit_log.md").read_text(), re.M)
    return runs["run"].map(lambda r: ", ".join(n for n, text in heads if re.search(rf"\b{re.escape(r)}\b", text)))


def n(key: str) -> str:
    return NUMBERS[key]["display"]


def page_findings() -> list[dict]:
    """The page's list of findings beyond the ledger's F1-F18: the anchor's tests and the Atlas with its W1
    extensions, each a sentence built from the numbers above (status from the numbers it cites)."""
    return [
        {"id": "AH2", "status": "confirmatory", "finding": "The first effort step for cheap models beat the nearest-dollar vote (anchor)",
         "number": f"Haiku low beat the Haiku-off {n('ah2.haiku.k')}-vote by {n('ah2.haiku.diff')} points "
                   f"({n('ah2.haiku.lo')} to {n('ah2.haiku.hi')}); Luna low beat the Luna-none {n('ah2.luna.k')}-vote by "
                   f"{n('ah2.luna.diff')} ({n('ah2.luna.lo')} to {n('ah2.luna.hi')}); passes Holm, p = {n('ah2.p.holm')}",
         "source": "research/v4/anchor/read.md"},
        {"id": "AH3", "status": "confirmatory", "finding": "The factor model's vote rule (anchor)",
         "number": f"3-vote error {n('ah3.mae')} points (upper {n('ah3.upper')}); gain error {n('ah3.gain')}; gains "
                   f"were only {n('ah3.gain.lo')} to {n('ah3.gain.hi')} points, and zero-gain also meets the limits",
         "source": "research/v4/anchor/read.md"},
        {"id": "AH1", "status": "exploratory", "finding": "Reasoning does not explain the vendor gap (anchor)",
         "number": f"R = {n('ah1.r')} ({n('ah1.lo')} to {n('ah1.hi')}) of a {n('ah1.gap')}-point gap; no claim",
         "source": "research/v4/anchor/read.md"},
        {"id": "AH4", "status": "exploratory", "finding": "The judge weakens on hard items (anchor)",
         "number": f"eta {n('ah4.easy')} easy against {n('ah4.hard')} hard (difference {n('ah4.diff')}, {n('ah4.lo')} "
                   f"to {n('ah4.hi')}); no claim without a new prereg", "source": "research/v4/anchor/read.md"},
        {"id": "J", "status": "post hoc", "finding": "The judge test was capped by its pools (anchor)",
         "number": f"Sol judge {n('judge.sol.bbeh.acc')}% against Sol alone {n('anchor.sol.bbeh')}% "
                   f"({n('judge.sol.vsown')} points, {n('judge.sol.vsown.lo')} to {n('judge.sol.vsown.hi')}, at "
                   f"{n('judge.sol.vsown.ratio')}x the dollars); the pools covered only {n('judge.sol.bbeh.coverage')}%, "
                   f"so even a perfect selector over them would lose to Sol alone", "source": "research/v4/handback_e5.md"},
        {"id": "A1", "status": "post hoc", "finding": "Failures are mostly shared (Atlas)",
         "number": f"systematic share {n('p6.swe.est')} SWE-bench (item interval {n('p6.swe.ilo')} to {n('p6.swe.ihi')}), "
                   f"{n('p6.ma.est')} MathArena, {n('p6.lb.est')} LiveBench", "source": "research/v4/atlas/extend.md"},
        {"id": "P1", "status": "post hoc", "finding": "The vote rule ranks vote gains but overstates them",
         "number": f"{n('p1.all.cells')} cells: gain error {n('p1.all.rule')} against {n('p1.all.zero')} points for "
                   f"zero-gain, but 3-vote level error {n('p1.all.levrule')} against {n('p1.all.levzero')}; where it "
                   f"predicts 3+ points it predicts {n('p1.pred.predgain')}, observes {n('p1.pred.obsgain')}",
         "source": "research/v4/atlas/extend.md"},
        {"id": "P2", "status": "post hoc", "finding": "Depth moves ability, not the failure pattern",
         "number": f"{n('p2.pairs')} pairs: ability {n('p2.all.da.pooled')} logits ({n('p2.all.da.lo')} to "
                   f"{n('p2.all.da.hi')}), failure slope {n('p2.all.db.pooled')} ({n('p2.all.db.lo')} to "
                   f"{n('p2.all.db.hi')})", "source": "research/v4/atlas/extend.md"},
        {"id": "P3", "status": "post hoc", "finding": "One deeper call beats the nearest-dollar vote",
         "number": f"{n('p3.all.pooled')} points ({n('p3.all.lo')} to {n('p3.all.hi')}) over {n('p3.all.k')} "
                   f"MathArena pairs; about 0 at the top of a model's range ({n('p3.geminimed.diff')}, "
                   f"{n('p3.opus.diff')})", "source": "research/v4/atlas/extend.md"},
        {"id": "P4", "status": "post hoc", "finding": "Label-free selection fails beside a lone strong system",
         "number": f"MathArena, one call each: every policy loses {n('p4.ma.lone.loss.min')} to "
                   f"{n('p4.ma.lone.loss.max')} points to the strong system; at matched calls, 3 competent systems "
                   f"against the best one's own 3-vote: plurality {n('p4.ma.match.comp.plur')} points",
         "source": "research/v4/atlas/extend.md"},
        {"id": "P5", "status": "post hoc", "finding": "Verification over cheap sets rarely beats the top system",
         "number": f"SWE-bench: room {n('p5.swe.room2')} to {n('p5.swe.room5')} points; beats the top at its "
                   f"dollars in at most {n('p5.swe.beat.sol')}% of sets", "source": "research/v4/atlas/extend.md"},
        {"id": "P7", "status": "post hoc", "finding": "Mixed weak panels: the factor model prices the vote",
         "number": f"5-system panels gain {n('p7.k5.gain')} points; factor model bias {n('p7.k5.bias')}, absolute error "
                   f"{n('p7.k5.dz')} points below zero-gain's, smaller in {n('p7.k5.setszero')} of {n('p7.k5.sets')} sets",
         "source": "research/v4/atlas/extend.md"},
        {"id": "P8", "status": "post hoc", "finding": "The held-out all-wrong tail",
         "number": f"SWE-bench, {n('p8.swe.members')} held-out systems, same information for both models: "
                   f"{n('p8.swe.obs')}% observed, factor model {n('p8.swe.model')}%, copula {n('p8.swe.copula')}%; "
                   f"the small math sets stay unresolved",
         "source": "research/v4/atlas/extend.md"},
    ]


def write_tex(path: Path) -> None:
    lines = ["% Generated by scripts/build_numbers.py; do not edit. \\nm{key} prints a number, \\nmst{key} its status.",
             "\\makeatletter"]
    for key, rec in sorted(NUMBERS.items()):
        lines.append(f"\\expandafter\\def\\csname nm@{key}\\endcsname{{{tex(rec['display'])}}}")
        lines.append(f"\\expandafter\\def\\csname nmst@{key}\\endcsname{{{rec['status']}}}")
    lines += ["\\makeatother",
              "\\newcommand{\\nm}[1]{\\ifcsname nm@#1\\endcsname\\csname nm@#1\\endcsname\\else\\textbf{??#1}\\fi}",
              "\\newcommand{\\nmst}[1]{\\ifcsname nmst@#1\\endcsname\\csname nmst@#1\\endcsname\\else\\textbf{??#1}\\fi}"]
    path.write_text("\n".join(lines) + "\n")


def write_table(path: Path) -> None:
    def esc(s: str) -> str:
        return s.replace("\\", "\\textbackslash{}").replace("_", "\\_").replace("&", "\\&").replace("%", "\\%") \
            .replace("#", "\\#").replace("$", "\\$")

    rows = [f"\\texttt{{{esc(k)}}} & {tex(r['display'])} & {r['status']} & "
            f"\\texttt{{{esc(r['source'])}}} \\\\" for k, r in sorted(NUMBERS.items())]
    path.write_text("% Generated by scripts/build_numbers.py; do not edit.\n"
                    "\\begin{longtable}{@{}p{0.30\\linewidth}p{0.09\\linewidth}p{0.17\\linewidth}p{0.36\\linewidth}@{}}\n"
                    "\\toprule key & value & status & source \\\\ \\midrule \\endhead\n" + "\n".join(rows) +
                    "\n\\bottomrule\n\\end{longtable}\n")


def write_runs(path: Path, runs: pd.DataFrame) -> None:
    """The appendix's list of runs (from results/*/status.json)."""
    def esc(x: str) -> str:
        return str(x).replace("_", "\\_").replace("%", "\\%").replace("&", "\\&").replace("$", "\\$")

    rows = [f"\\texttt{{{esc(r.run)}}} & {esc(r.session)} & {r.date} & {esc(r.state)} & {tex(fmt(r.spend, 'usd', 2))} \\\\"
            for r in runs.itertuples()]
    path.write_text("% Generated by scripts/build_numbers.py; do not edit.\n"
                    "\\begin{longtable}{@{}lllll@{}}\n\\caption{Every run with a status file: session, date, end state and "
                    "API spend (differences of the cumulative spend the status files record).}\\label{tab:runs}\\\\\n"
                    "\\toprule run & session & date & state & spend \\\\ \\midrule \\endhead\n" + "\n".join(rows) +
                    "\n\\bottomrule\n\\end{longtable}\n")


# ---------------------------------------------------------------------------------------------------------
# Team studies (session SC and the pilot): the 19-agent pilot, the LAB-Bench teams and the cross-provider panel,
# PHOENIX recovery, and the budget allocator's map. Every value is read or recomputed from a committed file.


def half_up(value: float, digits: int) -> float:
    """value rounded half away from zero at `digits` decimals of its displayed form (points), as the study summaries
    print it (Python's round and format round half to even on binary floats: -6.25 would show as -6.2)."""
    from decimal import ROUND_HALF_UP, Decimal

    q = Decimal(str(round(100 * float(value), 6))).quantize(Decimal(1).scaleb(-digits), ROUND_HALF_UP)
    return float(q) / 100

def pilot_numbers() -> None:
    """The pilot's 19-agent Haiku team on the 80 grid questions (reports/pilot/tables), against one Sonnet call; stage
    accuracy and effective size n / (1 + (n - 1) rho); and, from the stored proposer answers
    (results/p4_bbeh_grid_*/agents.csv, team k6-6-6-1): a plurality vote of k of the six proposers averaged over every
    set of k (ties split evenly), the coverage of k (at least one right), and team accuracy by how many proposers were
    right."""
    import itertools

    src = ROOT / "reports/pilot/tables/headline.csv"
    h = pd.read_csv(src)
    r = h[(h["comparison"] == "single Sonnet minus dense") & (h["items"] == "20-99")].iloc[0]
    put("pilot.items", r["n"], "record", src, "int")
    put("pilot.team.acc", half_up(r["acc_b"], 1), "exploratory", src, "pct", 1)
    put("pilot.sonnet.acc", half_up(r["acc_a"], 1), "exploratory", src, "pct", 1)
    put("pilot.team.usd", r["cost_b"], "record", src, "usd", 4)
    put("pilot.sonnet.usd", r["cost_a"], "record", src, "usd", 4)
    put("pilot.diff", half_up(r["diff_points"] / 100, 1), "exploratory", src, "signed", 1)
    put("pilot.diff.lo", half_up(r["lo"] / 100, 1), "exploratory", src, "signed", 1)
    put("pilot.diff.hi", half_up(r["hi"] / 100, 1), "exploratory", src, "signed", 1)
    src = ROOT / "reports/pilot/tables/econ_effective_team_size.csv"
    e = pd.read_csv(src).set_index("stage")
    put("pilot.rho", e.loc["propose", "error_correlation"], "exploratory", src, "num", 2)
    put("pilot.neff", e.loc["propose", "effective_team_size"], "exploratory", src, "num", 1)
    for stage in ("propose", "critique", "refine", "aggregate"):
        put(f"pilot.stage.{stage}", e.loc[stage, "accuracy"], "exploratory", src, "pct", 1)
    files = sorted(glob.glob(str(ROOT / "results/p4_bbeh_grid_[a-p]/agents.csv")))
    agents = pd.concat([pd.read_csv(f) for f in files])
    agents = agents[agents["config_id"] == "k6-6-6-1"]
    prop = agents[agents["stage"] == "propose"].assign(norm=lambda d: d["answer"].astype(str).str.strip().str.lower())
    src = "results/p4_bbeh_grid_*/agents.csv (k6-6-6-1)"
    ids = sorted(prop["agent_id"].unique())
    for k in (1, 6):
        accs, covs = [], []
        for subset in itertools.combinations(ids, k):
            q = prop[prop["agent_id"].isin(subset)]
            acc = 0.0
            for _, g in q.groupby("task_id"):
                g = g[g["answer"].notna() & (g["answer"].astype(str).str.len() > 0)]
                if g.empty:
                    continue
                counts = g.groupby("norm").agg(n=("correct", "size"), right=("correct", "max"))
                acc += counts[counts["n"] == counts["n"].max()]["right"].mean()
            accs.append(acc / q["task_id"].nunique())
            covs.append(q.groupby("task_id")["correct"].max().mean())
        put(f"pilot.vote.k{k}", float(np.mean(accs)), "exploratory", src, "pct", 1)
        put(f"pilot.cover.k{k}", float(np.mean(covs)), "exploratory", src, "pct", 1)
    p1 = prop.groupby("task_id")["correct"].mean().mean()
    put("pilot.cover.indep", 1 - (1 - p1) ** 6, "exploratory", src, "pct", 0,
        note="coverage of six independent proposers at the mean single accuracy")
    right = prop.groupby("task_id")["correct"].sum()
    team = agents[agents["stage"] == "aggregate"].set_index("task_id")["correct"]
    for name, mask in (("zero", right == 0), ("low", right.between(1, 2))):
        put(f"pilot.rescue.{name}.n", int(mask.sum()), "exploratory", src, "int")
        put(f"pilot.rescue.{name}.acc", float(team.reindex(right[mask].index).mean()), "exploratory", src, "pct", 1)


def lab_numbers() -> None:
    """LAB-Bench, 144 test questions (reports/self_or_social_shortlist): each team's methods, the preregistered
    contrasts, post hoc team-minus-single intervals (95% paired item bootstrap, 2,000 draws, seed 2026), and the
    cross-provider vote panel."""
    from autoagentnet.self_or_social.score import paired_bootstrap

    base = ROOT / "reports/self_or_social_shortlist"
    for team, folder in (("claude", "labbench_claude2"), ("gpt", "labbench_gpt")):
        summ = pd.read_csv(base / folder / "summary.csv").set_index("method")
        src = base / folder / "summary.csv"
        for m, key in (("fixed_peer", "peer"), ("full_review", "review"), ("all_reflect", "reflect"), ("vote", "vote"),
                       ("policy", "policy"), ("single_B", "single")):
            put(f"lab.{team}.{key}.acc", summ.loc[m, "accuracy"], "preregistered-descriptive", src, "pct", 1)
            put(f"lab.{team}.{key}.usd", summ.loc[m, "usd_per_item"], "record", src, "usd", 3)
        con = pd.read_csv(base / folder / "contrasts.csv")
        src = base / folder / "contrasts.csv"
        for (m, b), key, status in ((("policy", "all_reflect"), "primary", "confirmatory"),
                                    (("fixed_peer", "all_reflect"), "h4", "confirmatory"),
                                    (("policy", "random_matched"), "random", "preregistered-descriptive")):
            row = con[(con["method"] == m) & (con["baseline"] == b)].iloc[0]
            for suffix, col in (("", "d_acc"), (".lo", "d_acc_lo"), (".hi", "d_acc_hi")):
                put(f"lab.{team}.{key}{suffix}", half_up(row[col], 1), status, src, "signed", 1)
        per = pd.read_csv(base / folder / "per_item.csv")
        src = base / folder / "per_item.csv"
        if team == "claude":
            put("lab.items", per["item"].nunique(), "record", src, "int")
            put("lab.claude.review.ratio", summ.loc["full_review", "usd_per_item"] / summ.loc["single_B", "usd_per_item"],
                "record", base / folder / "summary.csv", "num", 1)
        for m, key in (("full_review", "review"), ("fixed_peer", "peer"), ("vote", "vote"), ("all_reflect", "reflect")):
            r = paired_bootstrap(per, m, "single_B", draws=2000, seed=2026)
            for suffix, col in (("", "d_acc"), (".lo", "d_acc_lo"), (".hi", "d_acc_hi")):
                put(f"lab.{team}.{key}minus{suffix}", half_up(r[col], 1), "post hoc", src, "signed", 1)
    src = base / "cross_provider/contrasts.csv"
    con = pd.read_csv(src)
    for b, key in (("gpt_vote", "gpt"), ("claude_vote", "claude")):
        row = con[(con["method"] == "panel_X") & (con["baseline"] == b)].iloc[0]
        for suffix, col in (("", "d_acc"), (".lo", "d_acc_lo"), (".hi", "d_acc_hi")):
            put(f"lab.mix.{key}{suffix}", half_up(row[col], 1), "confirmatory", src, "signed", 1)
    summ = pd.read_csv(base / "cross_provider/summary.csv").set_index("method")
    put("lab.mix.acc", summ.loc["panel_X", "accuracy"], "confirmatory", base / "cross_provider/summary.csv", "pct", 1)
    put("lab.mix.usd", summ.loc["panel_X", "usd_per_item"], "record", base / "cross_provider/summary.csv", "usd", 3)


def phoenix_numbers() -> None:
    """PHOENIX recovery on three science tables (reports/phoenix_science/report/branches.csv): sealed test balanced
    accuracy in points, paired by case (each arm case the mean of its two draws), with the study's own bootstrap
    (analysis/phoenix_science.py)."""
    sys.path.insert(0, str(ROOT / "analysis"))
    import phoenix_science as PS

    src = ROOT / "reports/phoenix_science/report/branches.csv"
    b = pd.read_csv(src)
    f = b.assign(test_points=100 * b["test_balanced_accuracy"], dataset=b["case_id"].str.split("_").str[0],
                 withdrawn_model="-")
    put("phx.cases", int(f[f["experiment"] == "fam_claude"]["case_id"].nunique()), "record", src, "int")
    put("phx.recoveries", int(f["test_points"].notna().sum()),
        "record", src, "int")
    for exp, comp, key in (("E1", "fixed", "main"), ("fam_claude", "fixed", "claude"), ("fam_claude", "llm", "rule"),
                           ("fam_gpt", "fixed", "gpt")):
        r = PS.contrast_rows(f, exp, comp, "test_points")[0]
        for suffix, col in (("", "mean"), (".lo", "ci_low"), (".hi", "ci_high")):
            put(f"phx.{key}{suffix}", r[col] / 100, "confirmatory", src, "signed", 2)
    w = f[f["experiment"] == "fam_claude"].pivot_table(index="case_id", columns="policy", values="test_points", aggfunc="mean")
    mean, lo, hi, _ = PS.bootstrap((w["llm"] - w["fixed"]).dropna())
    for suffix, v in (("", mean), (".lo", lo), (".hi", hi)):
        put(f"phx.planner{suffix}", v / 100, "post hoc", src, "signed", 2)
    usd = f[f["experiment"] == "fam_claude"].groupby("policy")["logical_api_usd"].mean()
    put("phx.usd.full", usd["full"], "record", src, "usd", 3)
    put("phx.usd.llm", usd["llm"], "record", src, "usd", 3)
    arms = f[f["experiment"].isin(["fam_claude", "fam_gpt"])]
    draws = arms.pivot_table(index=["experiment", "case_id", "policy"], columns="draw", values="test_points")
    put("phx.drawnoise", float((draws.max(axis=1) - draws.min(axis=1)).max()), "exploratory", src, "num", 2)


def allocator_numbers() -> None:
    """The budget map on the 440 BBEH questions (research/v4/measurement/tables/config_map.csv, p95 total latency):
    how many budget cells have a winner and how many winners are one call; held-out regret per latency measure."""
    src = ROOT / "research/v4/measurement/tables/config_map.csv"
    m = pd.read_csv(src)
    bb = m[m["benchmark"] == "bbeh"]
    cells = bb[(bb["latency"] == "p95 total") & bb["winner"].notna()]
    put("map.cells", len(cells), "exploratory", src, "int")
    put("map.single", int(cells["winner"].str.endswith("single").sum()), "exploratory", src, "int")
    put("map.vote", int(cells["winner"].str.contains("vote").sum()), "exploratory", src, "int")
    regret = bb.groupby("latency")["regret"].mean()
    put("map.regret.lo", regret.min() * 100, "exploratory", src, "num", 1)
    put("map.regret.hi", regret.max() * 100, "exploratory", src, "num", 1)


def main() -> None:
    atlas_numbers()
    extension_numbers()
    design_numbers()
    phase1_numbers()
    anchor_numbers()
    cd_numbers()
    testbed_numbers()
    pilot_numbers()
    lab_numbers()
    phoenix_numbers()
    allocator_numbers()
    runs = runs_table()
    process_numbers(runs)
    (ROOT / "paper").mkdir(exist_ok=True)
    write_tex(ROOT / "paper/numbers.tex")
    write_table(ROOT / "paper/numbers_table.tex")
    write_runs(ROOT / "paper/runs_table.tex", runs)
    out = ROOT / "reports/v4/story_data.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    data = {"generated_by": "scripts/build_numbers.py", "numbers": NUMBERS, "series": series(runs)}
    text = json.dumps(data, indent=1, default=lambda x: x.item() if hasattr(x, "item") else str(x))
    out.write_text(text)
    template = ROOT / "reports/v4/story_template.html"
    if template.exists():  # the page carries its data inline (one self-contained file)
        page = template.read_text().replace("/*STORY_DATA*/", text.replace("</", "<\\/"))
        (ROOT / "reports/v4/story.html").write_text(page)
    print(f"{len(NUMBERS)} numbers -> paper/numbers.tex, paper/numbers_table.tex, {out.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
