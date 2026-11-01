"""A review of every run so far (session E6, section 3; $0, no model calls). Writes research/v4/runs_review.md.

    python scripts/review_runs.py            # per-run and per-source tables, anomalies, reads, corrections
    python scripts/review_runs.py --verify   # reproduce every read from its frozen commit (slow; one at a time)
    python scripts/review_runs.py --numbers research/v3/findings.md   # numbers not found in their sources

`--verify` checks out each read's frozen commit as a detached git worktree in a temporary directory (data/external
symlinked in), runs the read there at low priority with every API key removed from the environment, and compares
each output with the committed one. Everything it runs writes inside that temporary directory (outputs, diffs and
logs stay there); the only file it writes in the repository is the summary table research/v4/runs_review_repro.csv,
which the default mode renders. `--only` reruns some reads and keeps the other rows.

Plain words for what this script counts.
  run              a results/<name>/ folder with a calls.csv: one config, possibly run as many attempts and slices.
  config           configs/**/<name>.yaml; "prereg" is a prereg block with a question, prediction, kill and decision,
                   both in the config today and in the config at the commit every attempt ran on (status.json code).
  attempt          one `aan run`: one run id "<name>-<unix seconds>" in the ledger or in a committed status.json.
  slice            the items [start, end) an attempt covered (status.json "items"; desk runs: "events").
  item             one question (calls.csv "item"; desk runs: one market event, "event_id").
  source           one model ref at one setting with one prompt, "ref:prompt" (desk runs: "role:model").
  live row         a calls.csv row with from_cache False: its call was paid by the attempt that last wrote the row.
  cache hit        a calls.csv row with from_cache True: served free from state/cache in the attempt that wrote it (its
                   call was paid earlier, by this run or another one, or the attempt was a $0 replay).
  ledger dollars   cost_usd summed over state/ledger.jsonl records whose run id is "<name>-<digits>".
  live dollars     cost_usd summed over the live rows.
  replayed dollars ledger dollars minus live dollars: calls this run paid in one attempt and a later attempt (a resume
                   or a $0 regrade) served from the cache, which marks their rows as cache hits.
  matched          a ledger record and a calls.csv row with the same item, source and cost (to 1e-9 dollars), counted
                   as multisets; "unmatched ledger" are paid calls with no row, "unledgered live" live rows with no
                   ledger record.
  truncated        the reply hit its output ceiling (calls.csv truncated; stop reason max_tokens or length).
  unparsed         the parser read no answer (parsed False); refusals are unparsed too.
  refused          stop reason refusal, content_filter or invalid_prompt (the panel runner's REFUSAL_STOP_REASONS).
  drift            more than one model_version reported under one source.
  failed attempt   an attempt whose committed status.json says state is not "completed" (a stop rule or an error).
  repeated slice   two attempts of one run whose slices overlap and which both made live calls (a resume after a stop,
                   or the same slice paid twice).
  read             a committed analysis output written once from frozen code (READS below). For each read: "once"
                   means the output did not exist before the commit that wrote it and no later commit changed it (for
                   read.md, a later block only appends); "frozen" means that between the frozen commit and the writing
                   commit only the outputs (and prose, .md files) changed; "inputs kept" means every calls.csv it reads
                   is byte-identical at HEAD and at the writing commit (no rows added after the read).
  reproduced       the read rerun from its frozen commit writes byte-identical outputs; otherwise the number of
                   differing lines and the first ones. The anchor reads grade math with math-verify under a wall-clock
                   limit, so their timeout counts can differ between runs of the same code.
  network run      a pilot-style run without a calls.csv (P0-P4, W0, W1): results.csv has one row per config, task and
                   replicate with its calls and live_calls; it is reconciled row by row with the ledger records of the
                   attempt its status.json names.
  market run       a market-town run (M1-M4): turns.csv has one row per trader turn; turns with a call_model made a
                   call, matched to the ledger on (session, trader, cost).
  paid twice       across runs: a state/cache key written by two paid calls. Every paid call writes one cache line and
                   a key already cached is served, not paid, so duplicate keys, or a run id whose cache lines and
                   ledger records differ in number, would show one.
"""

from __future__ import annotations

import argparse
import difflib
import glob
import gzip
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pandas as pd
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autoagentnet.ladder.core import markdown_table  # noqa: E402
from autoagentnet.meter import Ledger  # noqa: E402

RESULTS = ROOT / "results"
OUT_MD = ROOT / "research/v4/runs_review.md"
REPRO_CSV = ROOT / "research/v4/runs_review_repro.csv"
CORRECTIONS_CSV = ROOT / "research/v4/runs_review_corrections.csv"
EXTERNAL = Path(os.environ.get("AAN_EXTERNAL", str(ROOT / "data/external")))
REFUSALS = ("refusal", "content_filter", "invalid_prompt")
TRUNCATIONS = ("max_tokens", "length")
RATE_FLAG = 0.05  # a source's truncation or unparsed share above this is listed (the panel runner's default stop rule)
USD_TOLERANCE = 0.001  # ledger and live dollars are "equal" within this

TIER1 = ["e51_haiku_bbeh", "e51_sonnet_bbeh", "e51_luna_bbeh", "e51_sol_bbeh", "e51_haiku_off_math",
         "e51_haiku_low_math12", "e51_sonnet_math_t30", "e51_luna_math", "e51_sol_math_low"]
VERIFY = ["e51_verify_anth_bbeh", "e51_verify_open_bbeh", "e51_judge_open_bbeh", "e51_verify_anth_math",
          "e51_verify_open_math", "e51_judge_open_math"]
PHASE1 = ["e13_bbeh_anth", "e13_bbeh_open", "e14_forecast_anth", "e14_forecast_open"]
TIER2 = ["e51_tier2_anth_bbeh", "e51_tier2_anth_math"]  # the Astra (OpenAI) tier-2 configs were closed unrun (D1)

# Every read, its frozen commit (the code it ran on; the writing commit's parent unless the log names one), the
# commit that wrote its output, the command, its outputs and the runs whose calls.csv it reads (research/log.md:
# G2a "run once at bc5e884", G2b "at d93b59c", Phase 2 "at 653d07a", lockbox "selection frozen at 84cbcf9, read at
# 1a5f001", anchor blocks "frozen code at 831b2e6 / b651158 / f160a31", Atlas 343f50e and its frozen model a398a46).
READS = [
    {"read": "Phase 1 G2a", "written": "bc5e884", "cmd": ["analysis.evidence_phase1", "--block", "bbeh"],
     "outputs": ["research/v3/evidence/phase1_bbeh.md"], "runs": PHASE1[:2]},
    {"read": "Phase 1 G2b", "written": "d93b59c", "cmd": ["analysis.evidence_phase1", "--block", "forecast"],
     "outputs": ["research/v3/evidence/phase1_forecast.md"], "runs": PHASE1[2:]},
    {"read": "Phase 2", "written": "653d07a", "cmd": ["analysis.evidence_phase2"],
     "outputs": ["research/v3/evidence/phase2.md"],
     "runs": PHASE1 + ["e22_persona_bbeh_anth", "e22_persona_forecast_anth", "e22b_aggregator_bbeh_anth",
                       "e22b_aggregator_forecast_anth", "e23_reasoning_bbeh_anth"]},
    {"read": "Forecast selection", "written": "84cbcf9", "cmd": ["analysis.pruning_cascade", "select-forecast"],
     "outputs": ["research/v3/pruning/selected_forecast.json"], "runs": PHASE1[2:]},
    {"read": "Forecast lockbox", "written": "1a5f001", "cmd": ["analysis.pruning_cascade", "lockbox", "forecast"],
     "outputs": ["research/v3/pruning/lockbox_forecast.md"],
     "runs": ["e31_lockbox_forecast_anth", "e31_lockbox_forecast_open"]},
    {"read": "Anchor block 1", "frozen": "831b2e6", "written": "40f4854", "cmd": ["analysis.anchor_read", "block1"],
     "outputs": ["research/v4/anchor/read.md"], "runs": TIER1, "append": False},
    {"read": "Anchor block 2", "frozen": "b651158", "written": "37b615b", "cmd": ["analysis.anchor_read", "block2"],
     "outputs": ["research/v4/anchor/read.md"], "runs": VERIFY + TIER1, "append": True},
    {"read": "Anchor block 3", "frozen": "f160a31", "written": "6252e0b", "cmd": ["analysis.anchor_read", "block3"],
     "outputs": ["research/v4/anchor/read.md"], "runs": TIER2 + TIER1, "append": True},
    {"read": "Atlas", "written": "343f50e", "cmd": ["analysis.atlas_analyses"],
     "outputs": ["research/v4/atlas/atlas.md", "research/v4/atlas/tables/"], "runs": PHASE1[:2],
     "via": "research/v4/atlas/data/panels_phase1_bbeh.parquet"},
    {"read": "Atlas frozen model", "written": "a398a46", "cmd": ["analysis.atlas_freeze"],
     "outputs": ["research/v4/atlas/frozen_model.json"], "runs": PHASE1[:2],
     "via": "research/v4/atlas/data/panels_phase1_bbeh.parquet"},
]
REPLACED = "stopped or dropped; replaced by a fallback run (process facts only)"
NOT_READ = {"e15_sol_probe_anth": "sol_probe.md (not reproduced)",
            "e15_sol_probe_open": "sol_probe.md (not reproduced)",
            "e12_luna_check_bbeh_open": "luna_check.md (not reproduced)", "e51_haiku_math": REPLACED,
            "e51_haiku_low_math36": REPLACED, "e51_sonnet_math": REPLACED, "e51_sol_math": REPLACED}
NOT_READ_PREFIX = {"e11_": "cost probe (sets the guards; no read)",
                   "e50_": "scan (exploratory; research/v4/anchor/scan_read.md, not reproduced)",
                   "e52_": "scan (exploratory; logged, no read file)",
                   "e60_": "study CD probe (running at this review's commit; no read yet)",
                   "w2a_": "desk run (v3 track; analysis/desk.py, not reproduced)"}


def not_read(name: str) -> str:
    """What the review says about a run that none of READS uses."""
    if name in NOT_READ:
        return NOT_READ[name]
    return next((v for k, v in NOT_READ_PREFIX.items() if name.startswith(k)), "no frozen read")


# ---------------------------------------------------------------------------------------------------------------
# pure functions (tests/test_review_runs.py)

def run_name(run_id: str) -> str:
    """The config name of a run id "<name>-<unix seconds>"."""
    head, _, tail = str(run_id).rpartition("-")
    return head if tail.isdigit() else str(run_id)


def prereg_ok(cfg: dict | None) -> bool:
    """True when the config has a prereg block with a non-empty question, prediction, kill and decision."""
    pre = (cfg or {}).get("prereg")
    if not isinstance(pre, dict):
        return False
    return all(str(pre.get(k) or "").strip() for k in ("question", "prediction", "kill", "decision"))


def with_source(calls: pd.DataFrame) -> pd.DataFrame:
    """calls with a `src` column (panel: its source; desk: role:model), an `item_id` column and `agent`, the ledger's
    agent_id for the row (panel: "ref.prompt"; desk: the role)."""
    if "source" in calls:
        src, item = calls["source"].astype(str), calls["item"].astype(str)
        agent = src.str.replace(":", ".", regex=False)
    else:
        src, item = calls["role"].astype(str) + ":" + calls["model"].astype(str), calls["event_id"].astype(str)
        agent = calls["role"].astype(str)
    return calls.assign(src=src, item_id=item, agent=agent)


def as_bool(values: pd.Series) -> pd.Series:
    """A True/False column read from CSV (bools, or the strings "True"/"False")."""
    return values.astype(str).str.lower().isin(["true", "1", "1.0"])


def stop_mix(reasons: pd.Series) -> str:
    """The stop reasons of one source as "reason share, ..." (largest first); empty when not recorded."""
    if reasons.isna().all():
        return ""
    shares = reasons.fillna("none").value_counts(normalize=True).sort_values(ascending=False)
    return ", ".join(f"{r} {s:.1%}" for r, s in shares.items())


def source_table(calls: pd.DataFrame) -> pd.DataFrame:
    """Per source: calls, live rows, cache hits, truncated, unparsed and refused shares, stop reasons and model
    versions."""
    c = with_source(calls)
    stop = c["stop_reason"] if "stop_reason" in c else pd.Series(None, index=c.index, dtype=object)
    trunc = as_bool(c["truncated"])
    c = c.assign(live=~as_bool(c["from_cache"]), hit=as_bool(c["from_cache"]), trunc=trunc,
                 unparsed=~as_bool(c["parsed"]), refused=stop.isin(REFUSALS), stop=stop,
                 mismatch=stop.notna() & (trunc != stop.isin(TRUNCATIONS)),
                 version=c["model_version"] if "model_version" in c else None)
    g = c.groupby("src")
    out = g.agg(calls=("src", "size"), live=("live", "sum"), cache_hits=("hit", "sum"), truncated=("trunc", "mean"),
                unparsed=("unparsed", "mean"), refused=("refused", "sum"), trunc_mismatch=("mismatch", "sum"))
    out["stop_reasons"] = g["stop"].apply(stop_mix)
    out["versions"] = g["version"].nunique() if "model_version" in c else 0
    out["version_list"] = g["version"].apply(lambda v: " ".join(sorted(v.dropna().astype(str).unique())))
    return out.reset_index().sort_values("src")


def ledger_match(calls: pd.DataFrame, ledger: pd.DataFrame) -> dict:
    """Ledger records of one run against its calls.csv rows, matched as multisets on (item, source, cost to 1e-9 $):
    paid calls with no row, live rows with no ledger record, and the ledger, live and replayed dollars."""
    c = with_source(calls)
    live = ~as_bool(c["from_cache"])
    unmatched, unledgered = match_counts(c["item_id"] + "|" + c["agent"] + "|" + nano(c["cost_usd"]), live,
                                         ledger_keys(ledger))
    ledger_usd, live_usd = float(ledger["cost_usd"].sum()), float(c.loc[live, "cost_usd"].sum())
    return {"ledger_calls": len(ledger), "ledger_usd": ledger_usd, "live_rows": int(live.sum()), "live_usd": live_usd,
            "replayed_usd": ledger_usd - live_usd, "attempts": int(ledger["run_id"].nunique()) if len(ledger) else 0,
            "all_rows_usd": float(c["cost_usd"].sum()), "unmatched_ledger": unmatched, "unledgered_live": unledgered}


def nano(usd: pd.Series) -> pd.Series:
    """Dollars as whole nano-dollars (text), so equal costs compare equal."""
    return (usd.astype(float) * 1e9).round().astype("int64").astype(str)


def ledger_keys(ledger: pd.DataFrame) -> pd.Series:
    """One key per ledger record: its item (task_id), agent and cost."""
    return ledger["task_id"].astype(str) + "|" + ledger["agent_id"].astype(str) + "|" + nano(ledger["cost_usd"])


def match_counts(row_keys: pd.Series, live: pd.Series, led_keys: pd.Series) -> tuple[int, int]:
    """Rows against ledger records as multisets of keys: (ledger records with no row, live rows with no record)."""
    counts = pd.concat([led_keys.value_counts().rename("ledger"), row_keys.value_counts().rename("rows"),
                        row_keys[live].value_counts().rename("live")], axis=1).fillna(0)
    return (int((counts["ledger"] - counts["rows"]).clip(lower=0).sum()),
            int((counts["live"] - counts["ledger"]).clip(lower=0).sum()))


def network_reconcile(results: pd.DataFrame, last: pd.DataFrame) -> dict:
    """A pilot-style network run (results.csv: one row per config, task and replicate, with its calls and live_calls)
    against the ledger records of the attempt its status.json names (`last`): the rows whose live_calls differ from
    that attempt's ledger count for the same config and task, and the (config, task) pairs the ledger bills but
    results.csv lacks."""
    billed = last.groupby(["config_id", "task_id"]).size().rename("ledger")
    live = results.groupby(["config_id", "task_id"])["live_calls"].sum().rename("live")
    both = pd.concat([billed, live], axis=1).fillna(0)
    return {"calls": int(results["calls"].sum()), "live": int(results["live_calls"].sum()),
            "mismatched": int((both["ledger"] != both["live"]).sum()),
            "outside": int((~billed.index.isin(live.index)).sum()),
            "truncated": float(results["truncated_calls"].sum() / max(results["calls"].sum(), 1)),
            "unparsed": float(1 - results["parsed"].astype(float).mean())}


def market_reconcile(turns: pd.DataFrame, ledger: pd.DataFrame) -> dict:
    """A market run (turns.csv: one row per trader turn; turns with a call_model made a model call) against all its
    ledger records, matched as multisets on (session "s<seed>", trader, cost)."""
    t = turns[turns["call_model"].notna()]
    live = ~as_bool(t["from_cache"])
    keys = "s" + t["seed"].astype(str) + "|" + t["trader"].astype(str) + "|" + nano(t["cost_usd"])
    unmatched, unledgered = match_counts(keys, live, ledger_keys(ledger))
    return {"calls": len(t), "live": int(live.sum()), "mismatched": unmatched + unledgered, "outside": 0,
            "truncated": float(as_bool(t["truncated"]).mean()) if len(t) else 0.0}


def paid_stops(ledger: pd.DataFrame) -> dict:
    """From one run's ledger records (every paid call): the truncated share (stop reason max_tokens or length) and
    the refusals."""
    stop = ledger["stop_reason"].fillna("")
    return {"paid_truncated": float(stop.isin(TRUNCATIONS).mean()) if len(stop) else 0.0,
            "paid_refused": int(stop.isin(REFUSALS).sum())}


def duplicate_paid(cache_entries: pd.DataFrame, ledger: pd.DataFrame) -> dict:
    """Across every run: cache keys written by more than one paid call (the same request paid twice) and run ids
    whose number of cache entries differs from their number of ledger records. `cache_entries` has one row per
    state/cache line (run_id, key); every paid call writes one."""
    per = pd.concat([cache_entries.groupby("run_id").size().rename("cache"),
                     ledger.groupby("run_id").size().rename("ledger")], axis=1).fillna(0)
    return {"entries": len(cache_entries), "duplicate_keys": int(cache_entries["key"].duplicated().sum()),
            "run_ids": len(per), "count_mismatch": int((per["cache"] != per["ledger"]).sum())}


def slice_problems(attempts: pd.DataFrame) -> dict:
    """From one run's attempts (columns run_id, state, reason, start, end, live): the failed attempts and the
    repeated slices (overlapping slices of two attempts that both made live calls)."""
    a = attempts.sort_values(["start", "run_id"]).reset_index(drop=True)
    failed = a[a["state"].fillna("") != "completed"]
    paid = a[a["live"].fillna(0) > 0]
    repeated = []
    for i in range(len(paid)):
        for j in range(i + 1, len(paid)):
            x, y = paid.iloc[i], paid.iloc[j]
            if x["start"] < y["end"] and y["start"] < x["end"]:
                repeated.append((int(max(x["start"], y["start"])), int(min(x["end"], y["end"]))))
    return {"failed": [f"{r.start}-{r.end} {r.state}: {str(r.reason)[:60]}" for r in failed.itertuples()],
            "repeated": [f"{s}-{e}" for s, e in sorted(set(repeated))],
            "replays": int((a["live"].fillna(0) == 0).sum())}


def unrecorded(ledger: pd.DataFrame, recorded: set[str]) -> str:
    """The run ids of one run's ledger records that no committed status.json names, with their calls and dollars."""
    rest = ledger[~ledger["run_id"].isin(recorded)]
    g = rest.groupby("run_id")["cost_usd"].agg(["size", "sum"]).sort_index()
    return ", ".join(f"{r} ({int(n)} calls, ${usd:.3f})" for r, (n, usd) in g.iterrows())


def diff_summary(committed: str, reproduced: str, show: int = 2) -> str:
    """"identical", or how many lines differ and the first `show` changed lines (committed -> reproduced)."""
    if committed == reproduced:
        return "identical"
    lines = [d for d in difflib.unified_diff(committed.splitlines(), reproduced.splitlines(), lineterm="", n=0)
             if d[:1] in "+-" and not d.startswith(("+++", "---")) and d[1:].strip()]
    removed, added = [d for d in lines if d[0] == "-"], [d for d in lines if d[0] == "+"]
    first = "; ".join(f"`{r[1:].strip()[:90]}` -> `{a[1:].strip()[:90]}`" for r, a in zip(removed[:show], added[:show]))
    return f"{len(removed)} committed lines differ ({len(added)} reproduced); first: {first}"


NUMBER = re.compile(r"(?<![\w.])[-+]?\$?\d[\d,]*(?:\.\d+)?%?")


def number_tokens(text: str) -> list[str]:
    """The numbers written in a text ("43.3%", "$0.0062", "-0.7", "1,063"), without signs, $, % or commas."""
    out = []
    for tok in NUMBER.findall(text):
        clean = tok.lstrip("+-").replace("$", "").replace(",", "").rstrip("%")
        if clean and clean not in out:
            out.append(clean)
    return out


def source_values(sources: str, most_decimals: int = 4) -> set[tuple[int, float]]:
    """Every number of a source text as (decimals, value rounded to them), for 0..most_decimals decimals, also as
    a percentage (x 100) and a share (/ 100), so 0.43012 matches a claim of 0.430 or 43.0 and 0.433 one of 43.3%."""
    out = set()
    for tok in number_tokens(sources):
        x = float(tok)
        for d in range(most_decimals + 1):
            out |= {(d, round(x, d)), (d, round(x * 100, d)), (d, round(x / 100, d))}
    return out


def unmatched_numbers(claim: str, sources: str) -> list[str]:
    """The numbers of a claim that no number of the source text equals once rounded to the claim's decimals
    (directly, as a percentage or as a share)."""
    values = source_values(sources)
    out = []
    for tok in number_tokens(claim):
        d = len(tok.split(".")[1]) if "." in tok else 0
        if (d, round(float(tok), d)) not in values:
            out.append(tok)
    return out


def anomaly_lines(runs: pd.DataFrame, sources: pd.DataFrame, reads: pd.DataFrame,
                  orphans: list[str] | None = None) -> list[str]:
    """The short list at the top of the review: every flag the tables raise, one line each. `orphans` are ledger run
    names with no results/ folder."""
    out = []
    if orphans is not None:
        out.append("Every ledger run id belongs to a results/ folder." if not orphans else
                   "Ledger runs with no results/ folder: " + ", ".join(orphans) + ".")
    zero = runs[(runs["live_rows"] == 0) & (runs["ledger_usd"] > 0)]
    if len(zero):
        out.append(f"{len(zero)} runs have no live row although the ledger bills them (a later $0 replay or regrade "
                   f"rewrote every row as a cache hit; their spend is only in the ledger): " +
                   ", ".join(zero["run"]) + ".")
    part = runs[(runs["replayed_usd"].abs() > USD_TOLERANCE) & (runs["live_rows"] > 0)]
    if len(part):
        out.append("Ledger above live dollars (calls paid in an earlier attempt, replayed from the cache by a "
                   "resume): " +
                   ", ".join(f"{r.run} ${r.replayed_usd:.3f}" for r in part.itertuples()) + ".")
    bad = runs[(runs["unmatched_ledger"] > 0) | (runs["unledgered_live"] > 0)]
    out.append("Every ledger record matches a calls.csv row of its run (item, source, cost) and every live row a "
               "ledger record." if bad.empty else "Ledger and calls.csv do not match: " +
               ", ".join(f"{r.run} ({r.unmatched_ledger} paid calls without a row, {r.unledgered_live} live rows "
                         f"without a record)" for r in bad.itertuples()) + ".")
    if (~runs["prereg"]).any() or (runs["prereg_at_run"] == "no").any():
        out.append("Prereg missing: " + ", ".join(runs.loc[~runs["prereg"] | (runs["prereg_at_run"] == "no"), "run"]))
    else:
        out.append("Every config has a prereg block (question, prediction, kill, decision), today and at the commit of "
                   "each attempt that recorded one (desk runs record none).")
    mism = sources[sources["trunc_mismatch"] > 0]
    out.append("The truncated flag agrees with the stop reason (max_tokens or length) on every row that records one."
               if mism.empty else "Truncated flag and stop reason disagree: " +
               ", ".join(f"{r.run} {r.src} {int(r.trunc_mismatch)}" for r in mism.itertuples()) + ".")
    trunc = sources[sources["truncated"] > RATE_FLAG]
    if len(trunc):
        out.append(f"Truncation above {RATE_FLAG:.0%} of a source's calls: " +
                   ", ".join(f"{r.run} {r.src} {r.truncated:.1%}" for r in trunc.itertuples()) + ".")
    unp = sources[sources["unparsed"] > RATE_FLAG]
    if len(unp):
        out.append(f"Unparsed above {RATE_FLAG:.0%}: " +
                   ", ".join(f"{r.run} {r.src} {r.unparsed:.1%}" for r in unp.itertuples()) + ".")
    ref = sources[sources["refused"] > 0]
    if len(ref):
        out.append("Refusals: " + ", ".join(f"{r.run} {r.src} {int(r.refused)}" for r in ref.itertuples()) + ".")
    drift = sources[sources["versions"] > 1]
    out.append("No model_version drift (one version per source in every run)." if drift.empty else
               "Model version drift: " + ", ".join(f"{r.run} {r.src} ({r.version_list})" for r in drift.itertuples()))
    failed = runs[runs["failed"] != ""]
    if len(failed):
        out.append(f"{len(failed)} runs had failed or stopped attempts (listed in the per-run table): " +
                   ", ".join(failed["run"]) + ".")
    rep = runs[runs["repeated"] != ""]
    if len(rep):
        out.append("Repeated slices (two attempts with live calls on overlapping items): " +
                   ", ".join(f"{r.run} [{r.repeated}]" for r in rep.itertuples()) + "." +
                   (" In each the later attempt took the earlier one's calls from the cache: no call was paid twice "
                    "(the ledger has no record beyond its run's rows)." if bad.empty else ""))
    dirty = runs[runs["dirty"] != ""]
    if len(dirty):
        out.append("Attempts started on a dirty tree (status.json code.dirty; the changed paths are recorded only "
                   "since audit 75): " + ", ".join(f"{r.run} ({r.dirty})" for r in dirty.itertuples()) + ".")
    norec = runs[runs["unrecorded"] != ""]
    if len(norec):
        out.append("Ledger run ids that no committed status.json names (an attempt whose status was overwritten "
                   "before a commit): " + ", ".join(f"{r.run}: {r.unrecorded}" for r in norec.itertuples()) + ".")
    checks = (("once", "not written once"), ("frozen_ok", "code changed between frozen and written"),
              ("inputs_kept", "inputs changed after the read"))
    for r in reads.itertuples():
        problems = [text for column, text in checks if not getattr(r, column)]
        if problems:
            out.append(f"{r.read}: " + "; ".join(problems) + (f" ({r.note})" if r.note else "") + ".")
        if r.reproduced not in ("identical", "not run"):
            timeouts = getattr(r, "committed_timeouts", "") or ""
            note = (f" (math-verify timeouts: the committed read counted {timeouts}, the reproduction "
                    f"{r.math_verify_timeouts})" if timeouts and timeouts != r.math_verify_timeouts else "")
            out.append(f"{r.read} does not reproduce: {r.reproduced}{note}.")
    if len(reads):
        clean = reads["once"] & reads["frozen_ok"] & reads["inputs_kept"]
        same = reads["reproduced"] == "identical"
        out.append(f"Reads: {int(clean.sum())} of {len(reads)} were written once from frozen code with their inputs "
                   f"unchanged since; {int(same.sum())} of {len(reads)} reproduce byte-identical from their frozen "
                   "commit.")
    return out


# ---------------------------------------------------------------------------------------------------------------
# git and file access

def git(*args: str, cwd: Path = ROOT, check: bool = True) -> str:
    done = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {done.stderr.strip()}")
    return done.stdout


def git_ok(*args: str) -> bool:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True).returncode == 0


def show(commit: str, path: str) -> str | None:
    done = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True, text=True)
    return done.stdout if done.returncode == 0 else None


def config_path(name: str) -> str | None:
    found = sorted(glob.glob(str(ROOT / "configs" / "**" / f"{name}.yaml"), recursive=True))
    return str(Path(found[0]).relative_to(ROOT)) if found else None


def status_history() -> pd.DataFrame:
    """Every committed version of every results/*/status*.json, one row per attempt (its latest version)."""
    log = git("log", "--format=@%H %ct", "--name-only", "--", "results/*/status*.json")
    rows, commit, stamp = [], None, 0
    for line in log.splitlines():
        if line.startswith("@"):
            commit, stamp = line[1:].split()
            continue
        if not line.strip():
            continue
        text = show(commit, line.strip())
        try:
            s = json.loads(text or "")
        except json.JSONDecodeError:
            continue
        span = s.get("items") or s.get("events") or [0, 0]
        code = s.get("code") or {}
        rows.append({"run": line.split("/")[1], "run_id": s.get("run_id"), "stamp": int(stamp),
                     "state": s.get("state"), "reason": s.get("reason") or "", "start": int(span[0]),
                     "end": int(span[1]), "live": s.get("live_calls") or 0, "commit": code.get("commit"),
                     "dirty": bool(code.get("dirty")), "dirty_paths": " ".join(code.get("dirty_paths") or [])})
    frame = pd.DataFrame(rows)
    return frame.sort_values("stamp").drop_duplicates("run_id", keep="last")


def frozen_model_kept(commits: list[str]) -> str:
    """Whether autoagentnet/atlas/factor.py and the Phase 1 response table at each commit (the anchor reads) still
    have the sha256 that research/v4/atlas/frozen_model.json recorded when the Atlas model was frozen."""
    frozen = json.loads((ROOT / "research/v4/atlas/frozen_model.json").read_text())
    want = {"autoagentnet/atlas/factor.py": frozen["factor_py_sha256"],
            "research/v4/atlas/data/panels_phase1_bbeh.parquet": frozen["table_sha256"]}
    moved = []
    for commit in commits:
        for path, sha in want.items():
            blob = subprocess.run(["git", "show", f"{commit}:{path}"], cwd=ROOT, capture_output=True).stdout
            if hashlib.sha256(blob).hexdigest() != sha:
                moved.append(f"{path} at {commit}")
    return ("factor.py and the response table match frozen_model.json's sha256 at " + ", ".join(commits)) if not \
        moved else "changed since the freeze: " + ", ".join(moved)


def read_checks(read: dict) -> dict:
    """Once, frozen and inputs-kept checks of one read (definitions in the module docstring)."""
    written = read["written"]
    parent = git("rev-parse", "--short", f"{written}^").strip()
    frozen = read.get("frozen", parent)
    outputs = read["outputs"]
    notes = []
    if git("rev-parse", frozen).strip() != git("rev-parse", parent).strip():
        notes.append(f"frozen commit {frozen} is not the writing commit's parent {parent}")
    besides = [p for p in git("diff", "--name-only", frozen, written).split()
               if not any(p == o or (o.endswith("/") and p.startswith(o)) for o in outputs)]
    changed = [p for p in besides if not p.endswith(".md")]  # code or inputs; prose (.md) cannot change a read
    if besides:
        notes.append("also changed with the output: " + ", ".join(besides))
    once = True
    for out in outputs:
        existed = bool(git("ls-tree", "-r", "--name-only", f"{written}^", "--", out).split())
        if read.get("append") is not None:  # read.md: each block appends, so the text at the writing commit must
            # still open today's file, and the block's heading must be absent before
            block = read["cmd"][-1][-1]
            once &= (ROOT / out).read_text().startswith(show(written, out) or "\0") and \
                f"## Block {block}:" not in (show(f"{written}^", out) or "")
        else:
            once &= not existed and not git("log", "--format=%h", f"{written}..HEAD", "--", out).split()
    inputs = [f"results/{r}/calls.csv" for r in read["runs"]] + ([read["via"]] if read.get("via") else [])
    changed_inputs = [p for p in inputs if not git_ok("diff", "--quiet", written, "HEAD", "--", p)]
    if read["read"] == "Atlas frozen model":
        notes.append(frozen_model_kept([r.get("frozen", r["written"]) for r in READS if r["read"].startswith("Anchor")]
                                       + ["HEAD"]))
    return {"read": read["read"], "frozen": frozen, "written": written, "outputs": ", ".join(outputs),
            "once": once, "frozen_ok": not changed, "inputs_kept": not changed_inputs,
            "changed_inputs": ", ".join(p.split("/")[1] if p.startswith("results/") else p for p in changed_inputs),
            "note": "; ".join(notes), "changed_code": ", ".join(changed)}


# ---------------------------------------------------------------------------------------------------------------
# verify mode: each read reproduced from its frozen commit in a temporary worktree

def timeout_count(text: str, read: str) -> str:
    """The math-verify timeout count an anchor block's text reports for itself ("Math-verify timeouts during the whole
    block-<n> read ...: N"), or "" when the read is not an anchor block or its text has no such line (block 3)."""
    block = read[-1] if read.startswith("Anchor block") else None
    pattern = rf"[Mm]ath-verify timeouts during the whole block-{block} read[^:]*: (\d+)"
    found = re.findall(pattern, text) if block else []
    return found[-1] if found else ""


def clean_env(worktree: Path) -> dict:
    """The environment for a reproduction: no API key of any kind, the worktree first on the import path."""
    env = {k: v for k, v in os.environ.items() if "API_KEY" not in k}
    env["PYTHONPATH"] = str(worktree)
    return env


def output_files(read: dict) -> list[str]:
    files = []
    for out in read["outputs"]:
        if out.endswith("/"):
            files += git("ls-tree", "-r", "--name-only", read["written"], "--", out).split()
        else:
            files.append(out)
    return files


def reproduce(read: dict, tmp: Path) -> dict:
    """Run one read at its frozen commit in a worktree under `tmp` and compare every output with the committed one."""
    frozen = read.get("frozen") or git("rev-parse", "--short", f"{read['written']}^").strip()
    tree = tmp / ("wt_" + re.sub(r"\W+", "_", read["read"].lower()))
    git("worktree", "add", "--detach", str(tree), frozen)
    try:
        (tree / "data").mkdir(exist_ok=True)
        if not (tree / "data/external").exists():
            (tree / "data/external").symlink_to(EXTERNAL)
        start = time.time()
        done = subprocess.run(["nice", "-n", "10", sys.executable, "-m", *read["cmd"]], cwd=tree,
                              env=clean_env(tree), capture_output=True, text=True, timeout=3 * 3600)
        seconds = time.time() - start
        (tmp / f"{tree.name}.log").write_text(done.stdout + "\n--- stderr ---\n" + done.stderr)
        results = []
        for path in output_files(read):
            committed = show(read["written"], path) or ""
            mine = (tree / path).read_text() if (tree / path).exists() else ""
            kept = tmp / tree.name / path  # the reproduced output, kept beside its diff
            kept.parent.mkdir(parents=True, exist_ok=True)
            kept.write_text(mine)
            (tmp / f"{tree.name}.{Path(path).name}.diff").write_text("\n".join(difflib.unified_diff(
                committed.splitlines(), mine.splitlines(), "committed", "reproduced", lineterm="")))
            results.append((path, diff_summary(committed, mine) if mine else "no output written"))
        same = all(r == "identical" for _, r in results)
        detail = "identical" if same else "; ".join(f"{Path(p).name}: {r}" for p, r in results if r != "identical")
        return {"read": read["read"], "frozen": frozen, "written": read["written"],
                "outputs": len(results), "reproduced": detail, "exit": done.returncode, "seconds": round(seconds),
                "math_verify_timeouts": timeout_count(done.stdout, read["read"])}
    finally:
        git("worktree", "remove", "--force", str(tree), check=False)


def verify(only: list[str] | None = None) -> pd.DataFrame:
    tmp = Path(tempfile.mkdtemp(prefix="runs_review_verify_"))
    rows = []
    for read in READS:
        if only and read["read"] not in only:
            continue
        print(f"reproducing {read['read']} ...", flush=True)
        rows.append(reproduce(read, tmp))
        print(f"  {rows[-1]['reproduced'][:200]} ({rows[-1]['seconds']} s)", flush=True)
    frame = pd.DataFrame(rows)
    if only and REPRO_CSV.exists():
        old = pd.read_csv(REPRO_CSV, dtype=str, keep_default_na=False)
        frame = pd.concat([old[~old["read"].isin(frame["read"])], frame.astype(str)])
        frame = frame.set_index("read").loc[[r["read"] for r in READS if r["read"] in set(frame["read"])]]
        frame = frame.reset_index()
    frame.to_csv(REPRO_CSV, index=False)
    print(f"wrote {REPRO_CSV} (diffs and logs in {tmp})")
    return frame


# ---------------------------------------------------------------------------------------------------------------
# the review

def review() -> dict:
    """Every table of the review: runs (with a calls.csv), sources, reads, other (runs without one) and the
    cross-run duplicate check (paid)."""
    ledger = Ledger(ROOT / "state/ledger.jsonl", must_exist=True).to_frame()
    ledger = ledger.assign(name=ledger["run_id"].map(run_name))
    history = status_history()
    read_rows = pd.DataFrame([read_checks(r) for r in READS])
    cols = ["read", "reproduced", "math_verify_timeouts", "seconds", "exit"]
    repro = pd.read_csv(REPRO_CSV, dtype=str, keep_default_na=False) if REPRO_CSV.exists() else pd.DataFrame(
        columns=cols)
    repro = repro.reindex(columns=cols).fillna("")
    read_rows = read_rows.merge(repro, on="read", how="left").fillna("").replace({"reproduced": {"": "not run"}})
    read_rows["committed_timeouts"] = [timeout_count(show(r["written"], r["outputs"][0]) or "", r["read"])
                                       for r in READS]
    runs, sources = [], []
    for path in sorted(RESULTS.glob("*/calls.csv")):
        name = path.parent.name
        calls = pd.read_csv(path, dtype={"answer": str}, low_memory=False)
        cfg_path = config_path(name)
        cfg = yaml.safe_load((ROOT / cfg_path).read_text()) if cfg_path else None
        mine = history[history["run"] == name]
        at_run = []
        for commit in sorted(set(mine["commit"].dropna())):
            text = show(commit, cfg_path) if cfg_path else None
            at_run.append(prereg_ok(yaml.safe_load(text)) if text else False)
        match = ledger_match(calls, ledger[ledger["name"] == name])
        probs = slice_problems(mine) if len(mine) else {"failed": [], "repeated": [], "replays": 0}
        current = sorted(p.name for p in path.parent.glob("status*.json")
                         if json.loads(p.read_text()).get("state") != "completed")
        uses = [r["read"] for r in READS if name in r["runs"]]
        table = source_table(calls).assign(run=name)
        sources.append(table)
        runs.append({"run": name, "config": cfg_path or "missing", "prereg": prereg_ok(cfg),
                     "prereg_at_run": ("yes" if all(at_run) else "no") if at_run else "n/a",
                     "items": with_source(calls)["item_id"].nunique(), "calls": len(calls), **match,
                     "cache_hits": int(as_bool(calls["from_cache"]).sum()),
                     "max_truncated": table["truncated"].max(), "max_unparsed": table["unparsed"].max(),
                     "refused": int(table["refused"].sum()), "drift": int((table["versions"] > 1).sum()),
                     "failed": "; ".join(probs["failed"]), "status_not_completed": ", ".join(current),
                     "repeated": ", ".join(probs["repeated"]), "replays": probs["replays"],
                     "unrecorded": unrecorded(ledger[ledger["name"] == name], set(mine["run_id"])),
                     "dirty": "; ".join(f"{r.start}-{r.end}: {r.dirty_paths or 'dirty'}" for r in mine.itertuples()
                                        if r.dirty),
                     "reads": ", ".join(uses) or not_read(name)})
    return {"runs": pd.DataFrame(runs), "sources": pd.concat(sources, ignore_index=True), "reads": read_rows,
            "other": other_runs(ledger, history), "paid": duplicate_paid(cache_entries(), ledger)}


def ledger_total() -> float:
    return float(Ledger(ROOT / "state/ledger.jsonl", must_exist=True).spent_usd())


# Runs without a calls.csv (the pilot, the market town, W0 and W1): Phase 3A (F14, F15) reads these results.csv files.
PHASE3A = {"output": "research/v3/pruning/phase3a.md",
           "runs": [f"p4_bbeh_grid_{c}" for c in "abcdefghijklmnop"] + ["w0_haiku5", "p3_bbeh_single_sonnet",
                                                                        "p4_bbeh_single_sonnet_held"]}
OTHER_READS = {"p0_": "P0 calibration (logged; not reproduced)", "p2_": "pilot gate (reports/pilot; not reproduced)",
               "p3": "pilot gate (reports/pilot; not reproduced)", "p4_": "pilot P4 (reports/pilot; not reproduced)",
               "m": "market town (analysis/market.py; not reproduced)", "w1_": "W1 band check (logged; not reproduced)",
               "w0_": "W0 (logged; not reproduced)"}


def phase3a_check() -> str:
    """How often Phase 3A's output was written, and whether the results.csv files it reads are unchanged at HEAD since
    its last write (it is exploratory and was regenerated after audits 49-50, so it is not a once-read)."""
    commits = git("log", "--format=%h", "--", PHASE3A["output"]).split()
    paths = [f"results/{r}/results.csv" for r in PHASE3A["runs"]]
    changed = [p for p in paths if not git_ok("diff", "--quiet", commits[0], "HEAD", "--", p)]
    return (f"Phase 3A (phase3a.md, F14/F15; exploratory, written {len(commits)} times, last {commits[0]}; inputs "
            + ("unchanged since)" if not changed else "changed since: " + ", ".join(changed) + ")"))


def cache_entries() -> pd.DataFrame:
    """Every line of every state/cache shard as (run_id, key), read without loading values. A shard is named
    "<run id>-<nnn>.jsonl[.gz]"; the cache writes one line per paid call."""
    rows = []
    for path in sorted((ROOT / "state/cache").glob("*.jsonl*")):
        opener = gzip.open if path.suffix == ".gz" else open
        run_id = path.name.split(".jsonl")[0].rsplit("-", 1)[0]
        with opener(path, "rt") as f:
            rows += [(run_id, json.loads(line)["key"]) for line in f if line.strip()]
    return pd.DataFrame(rows, columns=["run_id", "key"])


def other_runs(ledger: pd.DataFrame, history: pd.DataFrame) -> pd.DataFrame:
    """One row per results/ folder without a calls.csv: config and prereg, tasks, calls and live calls from its own
    files, the ledger's calls and dollars (all attempts, and the attempt its status.json names), the reconciliation
    of rows against the ledger, paid-call truncation and refusals, final-answer unparsed share, failed attempts."""
    phase3a = phase3a_check()
    rows = []
    for folder in sorted(p for p in RESULTS.iterdir() if p.is_dir() and not (p / "calls.csv").exists()):
        name = folder.name
        status = json.loads((folder / "status.json").read_text())
        mine, cfg_path = ledger[ledger["name"] == name], config_path(name)
        last = mine[mine["run_id"] == status.get("run_id")]
        row = {"run": name, "config": cfg_path or "missing",
               "prereg": prereg_ok(yaml.safe_load((ROOT / cfg_path).read_text())) if cfg_path else False,
               "ledger_calls": len(mine), "ledger_usd": float(mine["cost_usd"].sum()),
               "attempts": int(mine["run_id"].nunique()), "last_calls": len(last),
               "last_usd": float(last["cost_usd"].sum()),
               "status_usd": float((status.get("budget") or {}).get("run_spent_usd") or 0.0), **paid_stops(mine),
               "failed": "; ".join(f"{r.state}: {r.reason[:60]}" for r in history[history["run"] == name].itertuples()
                                   if r.state != "completed"),
               "unrecorded": len(set(mine["run_id"]) - set(history["run_id"])),
               "unparsed": None, "tasks": 0}
        if (folder / "results.csv").exists():
            res = pd.read_csv(folder / "results.csv", low_memory=False)
            row.update(kind="network", tasks=int(res["task_id"].nunique()), **network_reconcile(res, last))
        elif (folder / "turns.csv").exists():
            turns, sessions = pd.read_csv(folder / "turns.csv", low_memory=False), pd.read_csv(folder / "sessions.csv")
            row.update(kind="market", tasks=int(sessions["seed"].nunique()), **market_reconcile(turns, mine),
                       unparsed=float(sessions["unparsed"].sum() / max(sessions["turns"].sum(), 1)))
        else:
            row.update(kind="market (no model calls)", calls=0, live=0, mismatched=0, outside=0, truncated=0.0)
        row["reads"] = phase3a if name in PHASE3A["runs"] else next(
            (v for k, v in OTHER_READS.items() if name.startswith(k)), "no read")
        rows.append(row)
    return pd.DataFrame(rows)


def other_anomaly_lines(other: pd.DataFrame) -> list[str]:
    """The flags of the runs without a calls.csv, one line each."""
    out = [f"{len(other)} results/ folders have no calls.csv: {int((other['ledger_calls'] > 0).sum())} ledgered runs, "
           f"${other['ledger_usd'].sum():.2f} (pilot, market town, W0, W1; table below)."]
    off = other[(other["status_usd"] - other["last_usd"]).abs() > 1e-4]
    out.append("For every one, the attempt its status.json names has ledger dollars equal to the status's run spend."
               if off.empty else "Status run spend differs from its attempt's ledger dollars: " +
               ", ".join(f"{r.run} ${r.status_usd:.4f} vs ${r.last_usd:.4f}" for r in off.itertuples()) + ".")
    bad = other[(other["mismatched"] > 0) | (other["outside"] > 0)]
    out.append("Network runs: in every results.csv row, live_calls equals that attempt's ledger records for the same "
               "config and task, and the ledger bills no config or task outside results.csv. Market runs: every "
               "ledger record matches a turns.csv row (session, trader, cost) and every live turn a record."
               if bad.empty else "Rows that do not reconcile with the ledger: " +
               ", ".join(f"{r.run} {int(r.mismatched)} (+{int(r.outside)} outside)" for r in bad.itertuples()) + ".")
    replay = other[(other["live"] == 0) & (other["ledger_calls"] > 0)]
    if len(replay):
        out.append(f"{len(replay)} of them were last rewritten by a $0 replay (no live call in their files; their "
                   "spend is only in the ledger): " + ", ".join(replay["run"]) + ".")
    multi = other[other["attempts"] > 1]
    if len(multi):
        out.append("Runs with more than one attempt (each of these folders keeps one committed status, so the "
                   "earlier attempts are seen only in the ledger, and their calls as cache hits in the files): " +
                   ", ".join(f"{r.run} {int(r.attempts)} attempts" for r in multi.itertuples()) + ".")
    trunc = other[other["paid_truncated"] > RATE_FLAG]
    if len(trunc):
        out.append(f"Paid calls truncated (ledger stop reason) above {RATE_FLAG:.0%}: " +
                   ", ".join(f"{r.run} {r.paid_truncated:.1%}" for r in trunc.itertuples()) + ".")
    unp = other[other["unparsed"].fillna(0) > RATE_FLAG]
    if len(unp):
        out.append(f"Final answers (network) or turns (market) unparsed above {RATE_FLAG:.0%}: " +
                   ", ".join(f"{r.run} {r.unparsed:.1%}" for r in unp.itertuples()) + ".")
    ref = other[other["paid_refused"] > 0]
    if len(ref):
        out.append("Refusals among paid calls: " + ", ".join(f"{r.run} {int(r.paid_refused)}" for r in ref.itertuples())
                   + ".")
    miss = other[~other["prereg"]]
    if len(miss):
        out.append("No config or no prereg: " + ", ".join(f"{r.run} ({r.config}, ${r.ledger_usd:.2f})"
                                                       for r in miss.itertuples()) + ".")
    failed = other[other["failed"] != ""]
    out.append("No committed status of these runs is failed or stopped; model_version is not recorded in their files."
               if failed.empty else "Failed or stopped: " + ", ".join(f"{r.run} ({r.failed})" for r in
                                                                       failed.itertuples()) + ".")
    return out


HAND_CHECKED = [
    "F1-F18: every number of every row was read against the cited file by hand, not only those `--numbers` lists.",
    "Recomputed from calls.csv: F3 (e13_bbeh_*: Sol low call 0 $0.0062, 92.0-100% per task, 404 output tokens; "
    "Sonnet $0.0139, 1,063 tokens; Haiku and Luna over calls 0-4) and F10 (e23 and e13: 75.0%, $0.00183 per call, "
    "40.0% off on the same 20 items, 15% truncated).",
    "Recomputed with the Atlas code: the F17 corrections note's 38-system all-wrong rates.",
    "From the ledger: the hand-back's spend lines, the K3 parts and the failure-window token counts.",
    "Against research/audit_log.md (audit 96, 'auditor post-read'): the hand-back's AH1 low-vs-off interval, the "
    "senior-control gaps and dollar ratios, the zero-gain AH3 check and the per-task AH2 effects.",
]


def notes(runs: pd.DataFrame, reads: pd.DataFrame, paid: dict) -> list[str]:
    """The audit-99 notes: the block-1 timeout count, cross-run cache replays and paid-twice checks, the hand checks."""
    out = ["", "## Notes on the checks (audit 99, item 3)", ""]
    b1 = reads[reads["read"] == "Anchor block 1"].iloc[0]
    if b1["reproduced"] != "identical" and b1["committed_timeouts"] != b1["math_verify_timeouts"]:
        out += [f"(a) Anchor block 1's reproduction differs only in its math-verify timeout count: the committed read "
                f"counted {b1['committed_timeouts']}, the reproduction {b1['math_verify_timeouts']} (in two "
                "reproductions). No grade changes: Sol low's math parse rates stay 0.627 at run time and 0.638 at the "
                "read, and arxivmath-0826-39 call 0 is wrong either way (a timeout reads as no match; regraded without "
                "one by `anchor_read.regrade_math`, it is still 0.0). Every accuracy, test and table value is "
                "identical, and audit 91's frozen sensitivity rule, which counts the timed-out rows correct, already "
                "found no confirmatory decision that differs. It is a nondeterministic wall-clock count, not a "
                "correction.", ""]
    cross = runs[runs["all_rows_usd"] - runs["ledger_usd"] > USD_TOLERANCE].sort_values("run")
    extra = cross["all_rows_usd"] - cross["ledger_usd"]
    out += ["(b) Cross-run cache replays. Some runs' calls.csv rows include calls another run paid for (served from "
            "the shared cache, priced on the row, billed to the other run). Cost over all rows exceeds the run's own "
            f"ledger dollars by ${extra.sum():.2f} in all: " +
            ", ".join(f"{r} +${x:.3f}" for r, x in zip(cross["run"], extra)) + ". \"No call was paid twice\" is "
            "checked within each run (every ledger record matches a row of its run, as multisets). Across runs it is "
            f"checked by cache key: the {paid['entries']:,} lines of state/cache hold "
            f"{paid['entries'] - paid['duplicate_keys']:,} distinct keys ({paid['duplicate_keys']} written twice), "
            f"and for {paid['run_ids'] - paid['count_mismatch']} of {paid['run_ids']} run ids the number of cache "
            "lines equals the number of ledger records. A paid "
            "call writes one cache line, and a key already in the cache is served instead of paid, so no request was "
            "paid twice." if paid["duplicate_keys"] == 0 and paid["count_mismatch"] == 0 else
            f"{paid['duplicate_keys']} cache keys were written more than once and {paid['count_mismatch']} run ids "
            "have more or fewer cache lines than ledger records.", ""]
    out += ["(c) Hand checks and the matcher's limit. `--numbers` lists the numbers of a claim that no number in its "
            "cited files equals once rounded to the claim's decimals (directly, as a percentage or as a share). It "
            "accepts any number in the file that rounds the same, whatever row it comes from, so a right number "
            "under the wrong label passes: F8's Haiku 0.137 and Luna 0.143 matched the pooled rows (0.1370, 0.1429) "
            "although the finding sets them beside single calls (per call 0.1377 and 0.1489). It is a screen for "
            "missing numbers only. Checked by hand:", ""]
    out += [f"- {line}" for line in HAND_CHECKED] + [""]
    return out


def render_other(other: pd.DataFrame) -> list[str]:
    """The table of runs without a calls.csv."""
    o = other.sort_values("run")
    return ["## Runs without a calls.csv", "",
            "Network runs (pilot P0-P4, W0, W1) are read from results.csv (one row per config, task and replicate, "
            "with its calls and live calls); market runs from turns.csv (one row per trader turn) and sessions.csv. "
            "\"last attempt\" is the run id its status.json names. Truncated is the share of paid calls (ledger "
            "records) that stopped on max_tokens or length; unparsed is the share of final answers (network) or "
            "turns (market) without a readable answer.", "",
            markdown_table(pd.DataFrame({
                "run": o["run"], "kind": o["kind"],
                "config": o["config"].str.replace("configs/experiments/", "", regex=False),
                "prereg": o["prereg"].map({True: "yes", False: "NO"}), "tasks": o["tasks"], "calls": o["calls"],
                "live": o["live"], "ledger calls ($, attempts)": o["ledger_calls"].astype(str) + " ($" +
                o["ledger_usd"].map("{:.4f}".format) + ", " + o["attempts"].astype(str) + ")",
                "last attempt: ledger calls / $ / status $": o["last_calls"].astype(str) + " / " +
                o["last_usd"].map("{:.4f}".format) + " / " + o["status_usd"].map("{:.4f}".format),
                "rows not reconciled": o["mismatched"].astype(int) + o["outside"].astype(int),
                "truncated (paid)": o["paid_truncated"].map("{:.1%}".format),
                "unparsed": o["unparsed"].map(lambda x: "" if pd.isna(x) else f"{x:.1%}"),
                "refused": o["paid_refused"], "failed": o["failed"].replace("", "-"), "read": o["reads"]})), ""]


def read_status(name: str, reads: pd.DataFrame) -> str:
    """The per-run read column: each read that uses the run, with "ok" when it was written once from frozen code with
    its inputs kept and reproduced identically, else what failed."""
    parts = []
    for r in reads.itertuples():
        if name not in next(x["runs"] for x in READS if x["read"] == r.read):
            continue
        bad = [w for w, ok in (("not once", r.once), ("not frozen", r.frozen_ok),
                               ("inputs changed", name not in r.changed_inputs.split(", "))) if not ok]
        if r.reproduced != "identical":
            timeouts = r.committed_timeouts != r.math_verify_timeouts
            bad.append("reproduction " + ("not run" if r.reproduced == "not run" else
                                          "differs" + (" (math-verify timeout count, note a)" if timeouts else "")))
        parts.append(f"{r.read}: " + (", ".join(bad) if bad else "ok"))
    return "; ".join(parts)


def render(tables: dict) -> str:
    runs, sources, reads, other = (tables["runs"].sort_values("run"), tables["sources"], tables["reads"],
                                   tables["other"])
    data_commit = git("log", "-1", "--format=%h", "--", "results", "state").strip()
    lines = ["# Review of every run so far (session E6, section 3)", "",
             f"Written by `python scripts/review_runs.py` from results/*/calls.csv ({len(runs)} runs), "
             "results/*/status*.json (every committed version), state/ledger.jsonl and configs/, as of commit "
             f"{data_commit} (the last change to results/ or state/); the reproduction table comes from "
             "`python scripts/review_runs.py --verify` (research/v4/runs_review_repro.csv). $0: no model calls. "
             "Definitions are in the script's docstring. Facts only: nothing here is a conclusion about a research "
             "question.", "", "## Anomalies", "", "Runs with a calls.csv, and the reads:", ""]
    names = Ledger(ROOT / "state/ledger.jsonl", must_exist=True).to_frame()["run_id"].map(run_name).unique()
    orphans = sorted(n for n in names if not (RESULTS / n).is_dir())
    first = anomaly_lines(runs, sources, reads, orphans)
    lines += [f"{i}. {a}" for i, a in enumerate(first, 1)]
    lines += ["", "Runs without a calls.csv (audit 99, item 2):", ""]
    lines += [f"{i}. {a}" for i, a in enumerate(other_anomaly_lines(other), len(first) + 1)]
    lines += notes(runs, reads, tables["paid"])
    table = pd.DataFrame({
        "run": runs["run"], "config": runs["config"].str.replace("configs/experiments/", "", regex=False),
        "prereg (now / at run)": runs["prereg"].map({True: "yes", False: "NO"}) + " / " + runs["prereg_at_run"],
        "items": runs["items"], "calls": runs["calls"],
        "ledger $ (attempts)": runs["ledger_usd"].map("{:.4f}".format) + " (" + runs["attempts"].astype(str) + ")",
        "live $ (rows)": runs["live_usd"].map("{:.4f}".format) + " (" + runs["live_rows"].astype(str) + ")",
        "cache hits": runs["cache_hits"],
        "max trunc / unparsed": runs["max_truncated"].map("{:.1%}".format) + " / " +
        runs["max_unparsed"].map("{:.1%}".format),
        "refused": runs["refused"], "drift": runs["drift"],
        "failed or stopped attempts (every committed status)": runs["failed"].replace("", "-"),
        "status*.json not completed (today)": runs["status_not_completed"].replace("", "-"),
        "repeated slices": runs["repeated"].replace("", "-"),
        "read (once, frozen, inputs kept, reproduced)": [read_status(n, reads) or other for n, other in
                                                          zip(runs["run"], runs["reads"])]})
    lines += ["", "## Per run", "", markdown_table(table), "",
              "Ledger $ counts every attempt of the run; live $ only the rows the last attempt paid for. Where they "
              "differ, every ledger record still matches a row (see anomalies): the difference is calls replayed "
              "from the cache by a later attempt. These runs hold "
              f"${runs['ledger_usd'].sum():.2f} of the ledger's ${ledger_total():.2f}; the runs without a calls.csv "
              f"hold ${other['ledger_usd'].sum():.2f} (next sections).", "",
              "## Per source", ""]
    src = sources.sort_values(["run", "src"])
    lines += [markdown_table(pd.DataFrame({
        "run": src["run"], "source": src["src"], "calls": src["calls"], "live": src["live"],
        "cache hits": src["cache_hits"], "truncated": src["truncated"].map("{:.1%}".format),
        "unparsed": src["unparsed"].map("{:.1%}".format), "refused": src["refused"],
        "stop reasons": src["stop_reasons"].replace("", "not recorded"), "model versions": src["version_list"]})), ""]
    lines += render_other(other)
    lines += ["## Reads: once, frozen, reproduced", "",
              "Each read was reproduced by `--verify` from its frozen commit in a temporary git worktree "
              "(data/external symlinked in, every API key removed) and its outputs compared byte for byte with the "
              "committed ones. Anchor block 3 (tier 2) was read at 6252e0b, after this review began; it was added "
              "after audit 99 and reproduced the same way.", ""]
    rt = reads.assign(once=reads["once"].map({True: "yes", False: "NO"}),
                      frozen_ok=reads["frozen_ok"].map({True: "yes", False: "NO"}),
                      inputs_kept=reads["inputs_kept"].map({True: "yes", False: "NO"}))
    lines += [markdown_table(pd.DataFrame({
        "read": rt["read"], "frozen commit": rt["frozen"], "written at": rt["written"], "output": rt["outputs"],
        "written once": rt["once"], "code unchanged, frozen to written": rt["frozen_ok"],
        "inputs unchanged since the read": rt["inputs_kept"], "reproduction": rt["reproduced"],
        "notes": rt["note"].replace("", "-")})), ""]
    ran = reads[reads["reproduced"] != "not run"]
    if len(ran):
        lines += ["Reproduction runs: " + "; ".join(
            f"{r.read} {r.seconds} s, exit {r.exit}" + (
                f", math-verify timeouts {r.math_verify_timeouts} (the committed read counted "
                f"{r.committed_timeouts or '?'})" if r.math_verify_timeouts else "")
            for r in ran.itertuples()) + ". math-verify grades each math answer under a wall-clock limit, so its "
            "timeout count can differ between two runs of the same code on the same rows.", ""]
    lines += ["## Corrections to research/v3/findings.md (F1-F18) and research/v4/handback_e5.md", ""]
    if CORRECTIONS_CSV.exists():
        corr = pd.read_csv(CORRECTIONS_CSV, dtype=str, keep_default_na=False)
        lines += [markdown_table(corr) if len(corr) else "None.", "",
                  "Every number of F1-F18 and of the E5 hand-back was checked against the file it cites "
                  "(research/v4/runs_review_corrections.csv; `--numbers` lists the numbers not found verbatim in "
                  "their sources, which were then checked by hand).", ""]
    return "\n".join(lines)


def cited_files(line: str, default: list[str]) -> list[Path]:
    """The text files a claim cites: repo paths, or bare names found under research/ (calls.csv files are left
    out: their numbers are computed, not written); `default` when it cites none."""
    found = []
    for c in re.findall(r"[\w./*-]+\.(?:md|csv|json)", line):
        c = c.rstrip(".,;)")
        if c.endswith("calls.csv"):
            continue
        hits = glob.glob(str(ROOT / c)) or glob.glob(str(ROOT / "research" / "**" / Path(c).name), recursive=True)
        found += [Path(h) for h in hits if Path(h).is_file()]
    return found or [ROOT / d for d in default]


def numbers_main(claims_file: str, default: list[str]) -> None:
    """Print, per table row or bullet of a claims file, the numbers not found in the files the row cites."""
    for line in (ROOT / claims_file).read_text().splitlines():
        files = cited_files(line, default)
        missing = unmatched_numbers(line, "\n".join(f.read_text(errors="ignore") for f in files))
        if missing and line.strip():
            print(f"{line[:70]!r} [{', '.join(f.name for f in files)}]: not found {missing}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--only", nargs="*", default=None, help="with --verify: reproduce only these reads")
    parser.add_argument("--numbers", default=None, help="a claims file whose numbers are looked up in its sources")
    parser.add_argument("--sources", nargs="*", default=[], help="with --numbers: files for lines that cite none")
    args = parser.parse_args(argv)
    if args.numbers:
        numbers_main(args.numbers, args.sources)
        return 0
    if args.verify:
        verify(args.only)
        return 0
    OUT_MD.write_text(render(review()) + "\n")
    print(f"wrote {OUT_MD}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
