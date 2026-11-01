"""Summary of the PHOENIX science-table study (step A10). Reads the folder written by
`python -m autoagentnet.phoenix report` (branches.csv, with test_balanced_accuracy after the sealed evaluation)
and the study manifest, and writes summary.md. It reads no test labels itself.

Terms (per branch unless said otherwise):
- test balanced accuracy: mean recall over classes of the branch's frozen predictor on the sealed test rows, in
  points (1 point = 0.01).
- dollars: logical API dollars of the branch's own model calls (logical_api_usd; a cached call counts at its
  price, so a branch's cost does not depend on which branch happened to pay first).
- paired difference full - X: in one case (same dataset, template, seed, fault and budget), PHOENIX full's value
  minus method X's value.
- 95% paired bootstrap: resample the cases with replacement 10,000 times (seed 2026), take the mean paired
  difference each time; the interval is the 2.5th to 97.5th percentile of those means. "not resolved" when it
  includes 0; otherwise the sign is reported.
- redundant recompute CPU: CPU seconds spent recomputing an artifact that was already VALID at the checkpoint and
  still usable (metrics.py); verification is not counted as redundant.
- planning overhead: the share of a branch's dollars spent on planning calls (propose, recover, select).
- win / tie / loss: number of cases where the paired difference is > 0, = 0, < 0.
Pilot branches (experiment == "pilot") are never evidence and are excluded from every table except the pilot one.

Usage: python analysis/phoenix_science.py --report reports/phoenix_science/report --manifest <study_manifest.json>
       --out reports/phoenix_science/summary.md
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

RESAMPLES, SEED = 10_000, 2026


def md_table(frame: pd.DataFrame) -> str:
    """A markdown table without the optional `tabulate` dependency."""
    head = "| " + " | ".join(str(c) for c in frame.columns) + " |"
    rule = "|" + "---|" * len(frame.columns)
    body = ["| " + " | ".join(str(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join([head, rule, *body])


def bootstrap(differences, resamples=RESAMPLES, seed=SEED):
    """Mean paired difference and its 95% bootstrap interval over cases."""
    d = np.asarray(differences, dtype=float)
    d = d[~np.isnan(d)]
    if len(d) == 0:
        return np.nan, np.nan, np.nan, 0
    rng = np.random.default_rng(seed)
    means = d[rng.integers(0, len(d), size=(resamples, len(d)))].mean(axis=1)
    return float(d.mean()), float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975)), len(d)


def verdict(lo, hi):
    if np.isnan(lo):
        return "no data"
    if lo > 0:
        return "positive"
    if hi < 0:
        return "negative"
    return "not resolved"


def branch_calls(frozen_path):
    """Model calls a branch made: the length of the `calls` list in the state.json beside its frozen.json; None when
    the branch never ran (no state.json)."""
    if not frozen_path:
        return None
    state = Path(frozen_path).with_name("state.json")
    return len(json.loads(state.read_text())["calls"]) if state.exists() else None


def load(report_dir, manifest_path):
    """branches.csv joined with the manifest(s): `manifest_path` is one path or a list (main study + family arms).
    `draw` is the replicate draw (0 for the main study, which has one draw per case)."""
    frame = pd.read_csv(Path(report_dir) / "branches.csv")
    paths = manifest_path if isinstance(manifest_path, (list, tuple)) else [manifest_path]
    branches = [b for p in paths for b in json.loads(Path(p).read_text())["branches"]]
    extra = pd.DataFrame(branches)
    if "draw" not in extra:
        extra["draw"] = 0
    extra["draw"] = extra["draw"].fillna(0).astype(int)
    if "calls" not in frame:
        # calls = model calls the branch made (len of state.json's calls; audit SC-14: branches.csv has no such
        # column, and Amendment 7's "call limit reached" label needs it); missing when the branch has no state.json
        extra["calls"] = [branch_calls(b.get("frozen")) for b in branches]
    keep = ["name", "dataset", "template", "withdrawn_model", "draw"] + (["calls"] if "calls" in extra else [])
    extra = extra[keep]
    frame = frame.drop(columns=[c for c in ("dataset", "template", "withdrawn_model", "draw") if c in frame])
    frame = frame.merge(extra, on="name", how="left", validate="one_to_one")
    frame["test_points"] = 100 * frame["test_balanced_accuracy"]
    return frame


def paired(frame, experiment, metric, comparator):
    """Per case: full's metric minus comparator's, within one experiment. With several draws per case (family
    arms), each method's value in a case is the mean over its draws."""
    part = frame[frame.experiment == experiment]
    wide = part.pivot_table(index=["case_id", "dataset", "withdrawn_model"], columns="policy", values=metric,
                            aggfunc="mean", dropna=False)
    if "full" not in wide or comparator not in wide:
        return pd.DataFrame(columns=["case_id", "dataset", "withdrawn_model", "difference"])
    # dropna=False keeps a case whose method did not run (its pair is dropped here), but it also creates every
    # combination of the index levels (case x dataset x withdrawn model), so rows without a difference are dropped
    # (audit SC-14 follow-up: they inflated `nonzero`)
    return (wide["full"] - wide[comparator]).rename("difference").reset_index().dropna(subset=["difference"])


def largest_case_share(differences) -> float:
    """Prereg Amendment 7 item 4: the largest single case's share of the total absolute paired difference
    (max |d_i| / sum |d_i|); 1.0 means one case carries the whole contrast, nan when every difference is 0."""
    d = np.abs(np.asarray(differences, dtype=float))
    d = d[~np.isnan(d)]
    return float(d.max() / d.sum()) if len(d) and d.sum() > 0 else np.nan


def contrast_rows(frame, experiment, comparator, metric, by=None):
    """Pooled (and per `by` group) mean paired difference, interval, verdict, win/tie/loss, the number of non-zero
    cases and the largest single case's share (Amendment 7)."""
    table = paired(frame, experiment, metric, comparator)
    groups = [("all", table)] + ([] if by is None else
                                 [(name, part) for name, part in table.groupby(by)])
    rows = []
    for name, part in groups:
        mean, lo, hi, n = bootstrap(part["difference"])
        rows.append({"experiment": experiment, "comparison": f"full - {comparator}", "metric": metric,
                     "group": name, "cases": n, "mean": mean, "ci_low": lo, "ci_high": hi, "verdict": verdict(lo, hi),
                     "wins": int((part["difference"] > 0).sum()), "ties": int((part["difference"] == 0).sum()),
                     "losses": int((part["difference"] < 0).sum()),
                     "nonzero": int((part["difference"] != 0).sum()),
                     "largest_case_share": largest_case_share(part["difference"])})
    return rows


def arm_vs_main(frame, arm, policies=("full", "llm", "fixed"), metric="test_points"):
    """Family arm minus the main study's E1, per method, paired by case over the main study's evidence cases
    (the arm's value in a case is the mean of its draws). This is the effect of the whole arm (pool, planner, budget,
    ceiling), not of the planner alone (prereg, Family arms)."""
    rows = []
    for policy in policies:
        a = frame[(frame.experiment == arm) & (frame.policy == policy)].groupby("case_id")[metric].mean()
        m = frame[(frame.experiment == "E1") & (frame.policy == policy)].groupby("case_id")[metric].mean()
        d = (a - m).dropna()
        mean, lo, hi, n = bootstrap(d)
        rows.append({"arm": arm, "comparison": f"{arm} {policy} - E1 {policy}", "metric": metric, "cases": n,
                     "mean": mean, "ci_low": lo, "ci_high": hi, "verdict": verdict(lo, hi),
                     "nonzero": int((d != 0).sum()), "largest_case_share": largest_case_share(d)})
    return pd.DataFrame(rows)


def arm_vs_arm(frame, arm_a, arm_b, policies=("full", "llm", "fixed"), metric="test_points"):
    """Provider comparison (prereg P10, descriptive): arm_a minus arm_b per method, paired by case over the cases both
    ran, each arm's value in a case being the mean of its draws. The arms differ in pool and planner as a whole."""
    rows = []
    for policy in policies:
        a = frame[(frame.experiment == arm_a) & (frame.policy == policy)].groupby("case_id")[metric].mean()
        b = frame[(frame.experiment == arm_b) & (frame.policy == policy)].groupby("case_id")[metric].mean()
        d = (a - b).dropna()
        mean, lo, hi, n = bootstrap(d)
        rows.append({"comparison": f"{arm_a} {policy} - {arm_b} {policy}", "metric": metric, "cases": n, "mean": mean,
                     "ci_low": lo, "ci_high": hi, "verdict": verdict(lo, hi), "nonzero": int((d != 0).sum()),
                     "largest_case_share": largest_case_share(d)})
    return pd.DataFrame(rows)


def draw_noise(frame, arm, metric="test_points"):
    """Draw-to-draw noise within each method of an arm: per case, draw 1 minus draw 2 (or the first two draws);
    mean absolute difference and the number of cases whose two draws differ."""
    part = frame[frame.experiment == arm]
    rows = []
    for policy, group in part.groupby("policy"):
        wide = group.pivot_table(index="case_id", columns="draw", values=metric, aggfunc="first")
        if wide.shape[1] < 2:
            continue
        d = (wide.iloc[:, 0] - wide.iloc[:, 1]).dropna()
        rows.append({"arm": arm, "policy": policy, "metric": metric, "cases": len(d),
                     "mean_abs_difference": float(d.abs().mean()), "cases_that_differ": int((d != 0).sum()),
                     "max_abs_difference": float(d.abs().max())})
    return pd.DataFrame(rows)


def reported_status(frame, call_limit=8):
    """Amendment 7 item 1: fixed branches that used all their model calls are reported as "call limit reached"
    (the engine stamps no_positive_feasible_plan, its normal stop). Needs a `calls` column; unchanged without it."""
    status = frame["status"].copy()
    if "calls" in frame:
        hit = (frame["policy"] == "fixed") & (frame["calls"] >= call_limit) & (status == "no_positive_feasible_plan")
        status[hit] = "call limit reached"
    return status


def fault_contrast(frame):
    """Per policy present in both E1 (F1) and E2 (F0): F0 minus F1 test points, paired by case."""
    rows = []
    for policy in ("fixed", "full"):
        f1 = frame[(frame.experiment == "E1") & (frame.policy == policy)].set_index("case_id")["test_points"]
        f0 = frame[(frame.experiment == "E2") & (frame.policy == policy)].set_index("case_id")["test_points"]
        mean, lo, hi, n = bootstrap((f0 - f1).dropna())
        rows.append({"policy": policy, "comparison": "F0 - F1 (test points)", "cases": n, "mean": mean,
                     "ci_low": lo, "ci_high": hi, "verdict": verdict(lo, hi)})
    return pd.DataFrame(rows)


def exploration(run_dir) -> dict:
    """How much a branch actually explored (prereg Amendment 6), from its own logs:
    - design_calls_<model>: design calls made with each model;
    - copied_designs: design replies whose pipeline already existed (a checkpoint or earlier operation; pipelines are
      content-addressed, so a copy returns an existing target);
    - copied_design_usd: dollars of those copied design calls (cost added between the call's intent and its result);
    - new_pipelines_completed: validated plans whose target was not in the checkpoint;
    - refused_calls_<model>: model calls the provider refused (stop_reason refusal, an empty reply the engine scores
      as invalid; audit SC-10), from calls.jsonl, so a refusal is never read as low plan quality;
    - model_new_pipelines (audit SC-13, the P7 measure): completed pipelines the model itself brought in, either the
      target of a model proposal whose action is REROUTE or SPLIT, or the output of a design call that did not copy an
      existing pipeline. Finishing pending work or a template's planned variant does not count. Event targets are
      truncated to 40 characters, so targets are compared on that prefix;
    - ran_model_pipeline (audit SC-14): 1 if model_new_pipelines > 0, else 0, so its mean over branches is the share of
      branches that ran a model-brought pipeline (P7 is about branches, and arms differ in branch counts)."""
    run = Path(run_dir)
    state = json.loads((run / "state.json").read_text())
    events = [json.loads(x) for x in (run / "events.jsonl").read_text().splitlines() if x]
    seen = set(state["checkpoint_operations"])
    seen_prefix = {k[:40] for k in seen}
    out = {"copied_designs": 0, "copied_design_usd": 0.0, "new_pipelines_completed": 0}
    last_intent_usd = 0.0
    proposed = {e["plan_id"] for e in events if e["event"] == "proposal"
                and (e.get("plan") or {}).get("action") in ("REROUTE", "SPLIT")}
    proposed_targets = {e["target"][:40] for e in events if e["event"] == "plan_selected" and e.get("plan_id") in proposed}
    designed_new = set()
    for e in events:
        if e["event"] == "call_intent":
            last_intent_usd = e["api_usd"]
            if e.get("purpose") == "design":
                key = "design_calls_" + e.get("model", "unknown")
                out[key] = out.get(key, 0) + 1
        elif e["event"] == "design_completed":
            if e["target"] in seen or e["target"][:40] in seen_prefix:
                out["copied_designs"] += 1
                out["copied_design_usd"] += e["api_usd"] - last_intent_usd
            else:
                designed_new.add(e["target"][:40])
            seen.add(e["target"])
            seen_prefix.add(e["target"][:40])
        elif e["event"] == "plan_completed" and e["target"] not in state["checkpoint_operations"]:
            out["new_pipelines_completed"] += 1
    completed = {e["target"][:40] for e in events if e["event"] == "plan_completed"}
    out["model_new_pipelines"] = len(completed & (designed_new | (proposed_targets - {k[:40] for k in
                                                                                    state["checkpoint_operations"]})))
    out["ran_model_pipeline"] = int(out["model_new_pipelines"] > 0)
    if (run / "calls.jsonl").exists():
        for line in (run / "calls.jsonl").read_text().splitlines():
            call = json.loads(line) if line else None
            if call and call["output"].get("stop_reason") in ("refusal", "content_filter"):
                key = "refused_calls_" + call.get("model_ref", "unknown")
                out[key] = out.get(key, 0) + 1
    return out


def exploration_table(manifest_path) -> pd.DataFrame:
    """exploration() for every branch that ran, with its experiment and policy."""
    manifest = json.loads(Path(manifest_path).read_text())
    rows = []
    for b in manifest["branches"]:
        run = Path(b["frozen"]).parent
        if (run / "state.json").exists():
            rows.append({"name": b["name"], "experiment": b["experiment"], "policy": b["policy"], **exploration(run)})
    frame = pd.DataFrame(rows).fillna(0)
    numeric = [c for c in frame.columns if c not in ("name", "experiment", "policy")]
    return frame.groupby(["experiment", "policy"])[numeric].mean().round(4).reset_index()


def method_table(frame):
    evidence = frame[frame.experiment != "pilot"]
    return (evidence.groupby(["experiment", "policy", "fault"])
            .agg(branches=("name", "size"), scored=("test_points", "count"), test_points=("test_points", "mean"),
                 dollars=("logical_api_usd", "mean"), redundant_cpu_s=("redundant_compute_cpu_s", "mean"),
                 planning_share=("planning_cost_fraction", "mean"), cpu_s=("cpu_s", "mean"),
                 calls=("calls", "mean"))
            .reset_index().sort_values(["experiment", "policy"]))


def status_table(frame):
    frame = frame.assign(status=reported_status(frame))
    return (frame.groupby(["experiment", "status"]).size().rename("branches").reset_index()
            .sort_values(["experiment", "branches"], ascending=[True, False]))


def family_markdown(frame) -> list[str]:
    """Sections for each family arm present (experiment names starting with fam_), then the provider comparison."""
    lines = []
    arms = sorted(e for e in frame.experiment.dropna().unique() if str(e).startswith("fam_"))
    for arm in arms:
        rows = []
        for comparator in ("fixed", "llm"):
            for metric in ("test_points", "logical_api_usd"):
                rows += contrast_rows(frame, arm, comparator, metric, by="dataset")
        versus = pd.concat([arm_vs_main(frame, arm), arm_vs_main(frame, arm, metric="logical_api_usd")])
        part = frame[frame.experiment == arm]
        by_designer = pd.DataFrame(contrast_rows(part, arm, "fixed", "test_points", by="withdrawn_model")[1:])
        by_designer = by_designer.rename(columns={"group": "withdrawn_model (fixed's designer is the other cheap model)"})
        lines += [f"## Family arm {arm}: paired contrasts (mean of two draws per case)", "",
                  md_table(pd.DataFrame(rows).round(4)), "",
                  f"## Family arm {arm} minus main E1 (main study's evidence cases)", "", md_table(versus.round(4)), "",
                  f"## Family arm {arm}: full - fixed by withdrawn model (audit SC-13: fixed's designer differs)", "",
                  md_table(by_designer.round(4)) if len(by_designer) else "no data", "",
                  f"## Family arm {arm}: draw-to-draw noise", "", md_table(draw_noise(frame, arm).round(4)), ""]
    if len(arms) == 2:
        both = pd.concat([arm_vs_arm(frame, arms[0], arms[1]),
                          arm_vs_arm(frame, arms[0], arms[1], metric="logical_api_usd")])
        lines += [f"## Provider comparison: {arms[0]} minus {arms[1]} (P10, descriptive)", "", md_table(both.round(4)), ""]
    return lines


def summary_markdown(frame, exploration_frame=None) -> str:
    evidence = frame[frame.experiment != "pilot"]
    contrasts = []
    for comparator in ("fixed", "llm"):
        for metric in ("test_points", "logical_api_usd"):
            contrasts += contrast_rows(evidence, "E1", comparator, metric, by="dataset")
    for comparator in ("no_dependency", "no_cost"):
        e1b = pd.concat([evidence[evidence.experiment == "E1b"],
                         evidence[(evidence.experiment == "E1") & (evidence.policy == "full")].assign(experiment="E1b")])
        contrasts += contrast_rows(e1b, "E1b", comparator, "test_points")
    contrast = pd.DataFrame(contrasts)
    by_withdrawn = pd.DataFrame(contrast_rows(evidence, "E1", "fixed", "test_points", by="withdrawn_model")[1:])
    lines = ["# PHOENIX on science tables: summary", "",
             "Generated by analysis/phoenix_science.py from the sealed evaluation; every number below comes from "
             "reports/phoenix_science/report/branches.csv. Pilot branches are excluded from every table but the last.",
             "Paired differences are in test balanced-accuracy points (1 point = 0.01) or dollars; 95% intervals are "
             "paired bootstraps over cases (10,000 resamples, seed 2026). 'not resolved' = the interval includes 0.", "",
             "## Branch outcomes", "", md_table(status_table(frame)), "",
             "## Methods (evidence branches)", "", md_table(method_table(frame).round(4)), "",
             "## Paired contrasts (E1: F1 shutdown + model withdrawal, $0.20; E1b: ablations)", "",
             md_table(contrast.round(4)), "",
             "## F0 vs F1 (E2 vs E1, same cases)", "", md_table(fault_contrast(evidence).round(4)), "",
             "## full - fixed by withdrawn model (E1, test points)", "",
             md_table(by_withdrawn.round(4)) if len(by_withdrawn) else "no data", "",
             "## Exploration (mean per branch; prereg Amendment 6)", "",
             md_table(exploration_frame) if exploration_frame is not None and len(exploration_frame) else "no data", "",
             *family_markdown(evidence),
             "## Pilot (not evidence)", "",
             md_table(frame[frame.experiment == "pilot"][["name", "status", "test_points", "logical_api_usd"]]
                      .round(4)), ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--manifest", required=True, nargs="+", help="study manifest(s): main study, family arms")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    frame = load(args.report, args.manifest)
    exploration_frame = pd.concat([exploration_table(m) for m in args.manifest], ignore_index=True)
    Path(args.out).write_text(summary_markdown(frame, exploration_frame))
    print(args.out)


if __name__ == "__main__":
    main()
