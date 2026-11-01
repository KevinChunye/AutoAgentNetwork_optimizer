"""Self-or-social, two-fold cross-fitted read of one branch table (the ArXivMath prereg,
research/self_or_social_shortlist/prereg_arxivmath.md).

  python analysis/sos_crossfit.py --calls results/sos_math/calls.csv --tasks data/external/evidence/math.jsonl \
      --items research/v3/evidence/sealed/math_all.txt --pilot 5 --name arxivmath

Plain words.
  evidence items  the items of the frozen order (`--items`) after the first `--pilot` (the pilot is never evidence)
                  that have rows in the calls.
  fold            an item's fold from its question text: the last hex digit of sha256(text) even gives fold 0, odd 1.
  cross-fitting   for each fold k: fit every policy and control on the items of the other fold only, with the BBEH
                  study's freeze (analysis/self_or_social.fit_frozen: cells shrunk to coarser cells, U = P - lam x
                  dollars, the lam grid, the tie rules, fixed directed and smartest peers, the ablations), then score
                  them on fold k's items (score_frozen). Both folds' scored items are pooled; no item is scored by a
                  policy fitted on it.
  accuracy        share of items whose voted answer is right; unparsed and truncated answers are wrong and cast no
                  vote (protocol.grade_reply, policy.voting_answers).
  cost            logical deployment dollars per item: every first answer (reused or not) plus the chosen revisions.
  decision rule   the policy beats all-reflect iff (a) its mean cost per item is below all-reflect's and (b) the lower
                  end of the 95% paired item bootstrap interval of (policy - all-reflect) accuracy is above -3 points
                  (2,000 draws, seed 2026); otherwise "not resolved". Every control is reported as such an interval;
                  an interval that holds 0 is "not resolved", never "equal".
Diagnostics (reported, not tested):
  herding         among items where at least two members consult under the policy, the share where all of them
                  consult the same teammate;
  categories      accuracy per method by the item's category (task meta "task", "subset" or "set");
  edges           per sender -> receiver consult edge (and each receiver's reflect, sender "self"), over the evidence
                  items' branch table: corrections (first answer wrong, revision right) and contaminations (first answer
                  right, revision wrong); and how often the policy chose each edge;
  actions         the share of each action kind the policy chose;
  calls           unparsed and truncated shares per member and phase (initial, branch, full).
Writes <out>/<name>_summary.md, <name>_per_item.csv, <name>_summary.csv and <name>_contrasts.csv.
"""

from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis import self_or_social as A  # noqa: E402
from autoagentnet.evidence.panel import read_ids  # noqa: E402
from autoagentnet.self_or_social.policy import branch_table  # noqa: E402
from autoagentnet.self_or_social.protocol import CONSULT, REFLECT, STOP, kind_of, peer_of  # noqa: E402
from autoagentnet.self_or_social.score import paired_bootstrap  # noqa: E402
from autoagentnet.tasks import load_tasks  # noqa: E402

OUT = ROOT / "reports/self_or_social_shortlist"
BOOT, SEED, MARGIN = 2000, 2026, -0.03
CONTROLS = ["all_reflect", "vote", "fixed_peer", "smartest_peer", "random_matched", "full_review", "self_only",
            "forced_social"]


def question_fold(text: str) -> int:
    """0 when the last hex digit of sha256(question text) is even, 1 when it is odd."""
    return int(hashlib.sha256(text.encode()).hexdigest()[-1], 16) % 2


def category_of(meta: dict) -> str:
    """The item's category: its task meta "task" (BBEH), "subset" (LAB-Bench) or "set" (ArXivMath), else "all"."""
    for key in ("task", "subset", "set"):
        if meta.get(key):
            return str(meta[key])
    return "all"


def evidence_items(items_file: str, pilot: int) -> list[str]:
    """The frozen order without its first `pilot` items."""
    return read_ids(items_file)[pilot:]


def crossfit(calls: pd.DataFrame, folds: dict[str, int], draws: int = 20) -> tuple[pd.DataFrame, dict[int, dict]]:
    """Per item and method, every method scored on each fold by the policies fitted on the other fold (module
    docstring); returns (pooled per-item rows with their fold, the frozen dict of each fold)."""
    team, graders = A.team_of(calls), A.graders_of(calls)
    table = branch_table(calls)
    fold_of_item = table["item"].map(folds)
    parts, frozen = [], {}
    for k in (0, 1):
        held = set(table.loc[fold_of_item == k, "item"])
        frozen[k] = A.fit_frozen(table[fold_of_item != k], team, graders)
        scored = A.score_frozen(calls[calls["item"].isin(held)], table[table["item"].isin(held)], team, graders,
                                frozen[k], draws)
        parts.append(scored.assign(fold=k))
    return pd.concat(parts, ignore_index=True), frozen


def method_intervals(per_item: pd.DataFrame, draws: int = BOOT, seed: int = SEED) -> pd.DataFrame:
    """Per method: items, accuracy with a 95% item bootstrap interval, dollars and calls per item."""
    rng = np.random.default_rng(seed)
    rows = []
    for method, group in per_item.groupby("method"):
        acc = group["correct"].to_numpy(dtype=float)
        boot = acc[rng.integers(0, len(acc), size=(draws, len(acc)))].mean(axis=1)
        rows.append({"method": method, "items": len(acc), "accuracy": acc.mean(), "acc_lo": np.quantile(boot, 0.025),
                     "acc_hi": np.quantile(boot, 0.975), "usd_per_item": group["cost"].mean(),
                     "calls_per_item": group["calls"].mean()})
    return pd.DataFrame(rows).sort_values(["accuracy", "usd_per_item"], ascending=[False, True]).reset_index(drop=True)


def contrasts(per_item: pd.DataFrame, team: list[str], draws: int = BOOT, seed: int = SEED) -> pd.DataFrame:
    """Policy minus each control: mean accuracy and cost differences with 95% paired item bootstrap intervals."""
    out = pd.DataFrame([paired_bootstrap(per_item, "policy", b, draws=draws, seed=seed)
                        for b in CONTROLS + [f"single_{m}" for m in team]])
    resolved = (out["d_acc_lo"] > 0) | (out["d_acc_hi"] < 0)
    return out.assign(reading=np.where(resolved, np.where(out["d_acc_lo"] > 0, "policy higher", "policy lower"),
                                       "not resolved"))


def decision(per_item: pd.DataFrame, draws: int = BOOT, seed: int = SEED) -> dict:
    """The prereg's primary rule: (a) policy cost per item < all-reflect's, (b) lower 95% bound of the accuracy
    difference > -3 points."""
    c = paired_bootstrap(per_item, "policy", "all_reflect", draws=draws, seed=seed)
    if c["n"] == 0:
        return {**c, "cheaper": False, "within_margin": False, "verdict": "not resolved (no paired items)"}
    cheaper, within = c["d_cost"] < 0, c["d_acc_lo"] > MARGIN
    verdict = "policy beats all-reflect" if cheaper and within else "not resolved"
    return {**c, "cheaper": bool(cheaper), "within_margin": bool(within), "verdict": verdict}


def policy_actions(per_item: pd.DataFrame) -> pd.DataFrame:
    """One row per (item, receiver) of the policy's choices: item, receiver, action, kind, sender."""
    pol = per_item[per_item["method"] == "policy"][["item", "actions"]]
    acts = pol.assign(pair=pol["actions"].str.split(" ")).explode("pair")
    split = acts["pair"].str.split("=", n=1, expand=True)
    acts = acts.assign(receiver=split[0], action=split[1])[["item", "receiver", "action"]]
    return acts.assign(kind=acts["action"].map(kind_of), sender=acts["action"].map(peer_of))


def herding(acts: pd.DataFrame) -> dict:
    """Among items with at least two consulting members, the share whose consulters all chose the same teammate."""
    cons = acts[acts["kind"] == CONSULT]
    per = cons.groupby("item").agg(consulters=("sender", "size"), senders=("sender", "nunique"))
    multi = per[per["consulters"] >= 2]
    return {"items_with_2plus_consults": len(multi), "herded": int((multi["senders"] == 1).sum()),
            "rate": float((multi["senders"] == 1).mean()) if len(multi) else float("nan"),
            "items_with_any_consult": len(per)}


def edges(table: pd.DataFrame, acts: pd.DataFrame) -> pd.DataFrame:
    """Per receiver and revision (reflect: sender "self"; consult:J: sender J): items, corrections (first answer
    wrong, revision right), contaminations (first right, revision wrong), net, and how often the policy chose it."""
    first = table[table["kind"] == STOP][["item", "receiver", "correct"]].rename(columns={"correct": "first"})
    rev = table[table["kind"].isin([REFLECT, CONSULT])][["item", "receiver", "action", "correct"]]
    paired = rev.merge(first, on=["item", "receiver"], how="inner")
    paired = paired.assign(sender=paired["action"].map(lambda a: peer_of(a) or "self"),
                           correction=(paired["first"] < 0.5) & (paired["correct"] > 0.5),
                           contamination=(paired["first"] > 0.5) & (paired["correct"] < 0.5))
    out = paired.groupby(["sender", "receiver"]).agg(items=("item", "size"), corrections=("correction", "sum"),
                                                    contaminations=("contamination", "sum")).reset_index()
    chosen = acts[acts["kind"].isin([REFLECT, CONSULT])].assign(sender=lambda d: d["sender"].fillna("self"))
    chosen = chosen.groupby(["sender", "receiver"]).size().rename("policy_chose").reset_index()
    out = out.merge(chosen, on=["sender", "receiver"], how="left").fillna({"policy_chose": 0})
    out = out.assign(net=out["corrections"] - out["contaminations"], policy_chose=out["policy_chose"].astype(int))
    return out.sort_values(["receiver", "sender"]).reset_index(drop=True)


def call_rates(calls: pd.DataFrame) -> pd.DataFrame:
    """Unparsed and truncated shares per member and phase, over every row (reused first answers included)."""
    return calls.groupby(["receiver", "ref", "phase"]).agg(
        calls=("parsed", "size"), unparsed=("parsed", lambda x: float((~x.astype(bool)).mean())),
        truncated=("truncated", lambda x: float(x.fillna(False).astype(bool).mean()))).reset_index()


def report(calls: pd.DataFrame, tasks: dict, items_file: str, pilot: int, name: str, out: Path,
           draws: int = 20, boot: int = BOOT) -> dict:
    """Run the cross-fitted read and write the report files; returns the decision."""
    evidence = [i for i in evidence_items(items_file, pilot) if i in set(calls["item"])]
    calls = calls[calls["item"].isin(evidence)]
    folds = {i: question_fold(tasks[i].prompt) for i in evidence}
    team = A.team_of(calls)
    per_item, frozen = crossfit(calls, folds, draws)
    category = {i: category_of(tasks[i].meta) for i in evidence}
    per_item = per_item.assign(category=per_item["item"].map(category))
    summary = method_intervals(per_item, boot)
    contrast = contrasts(per_item, team, boot)
    rule = decision(per_item, boot)
    acts = policy_actions(per_item)
    herd = herding(acts)
    table = branch_table(calls)
    edge = edges(table, acts)
    shares = acts["kind"].value_counts(normalize=True).rename("share").reset_index()
    by_cat = per_item[~per_item["method"].str.startswith("policy_lam")].groupby(["category", "method"]).agg(
        items=("item", "nunique"), accuracy=("correct", "mean"), usd_per_item=("cost", "mean")).reset_index()
    rates = call_rates(calls)
    fake = calls["model_version"].astype(str).str.contains("fake").any()

    out.mkdir(parents=True, exist_ok=True)
    per_item.to_csv(out / f"{name}_per_item.csv", index=False)
    summary.to_csv(out / f"{name}_summary.csv", index=False)
    contrast.to_csv(out / f"{name}_contrasts.csv", index=False)
    picked = {k: f"lam {f['picked']['lam']}, use_family {f['picked']['use_family']}, order {f['order']}, fixed peers "
                 f"{f['fixed_peers']}, policy {f['policy_hash']}" for k, f in frozen.items()}
    lines = [f"# Self-or-social, cross-fitted read: {name}", ""]
    if fake:
        lines += ["**DRY RUN on the fake model (some rows): these numbers test the pipeline and are not results.**", ""]
    lines += [f"Evidence items: {len(evidence)} (`{items_file}` after the first {pilot} pilot items); fold 0: "
              f"{sum(1 for v in folds.values() if v == 0)}, fold 1: {sum(1 for v in folds.values() if v == 1)}. "
              f"Team {team}. Folds by sha256 of the question text (last hex digit even / odd).", "",
              *[f"- Fitted on fold {1 - k}, scored on fold {k}: {picked[k]}" for k in (0, 1)], "",
              "## Primary decision (prereg)", "",
              f"**{rule['verdict']}.** Policy minus all-reflect over {rule['n']} paired items: accuracy "
              f"{rule.get('d_acc', float('nan')):+.3f} (95% CI {rule.get('d_acc_lo', float('nan')):+.3f} to "
              f"{rule.get('d_acc_hi', float('nan')):+.3f}; margin -0.030), cost per item "
              f"{rule.get('d_cost', float('nan')):+.5f} dollars. (a) cheaper: {rule['cheaper']}; (b) lower bound above "
              f"-3 points: {rule['within_margin']}.", "",
              "## Accuracy and cost per method (95% item bootstrap)", "", A.md_table(summary.round(4), index=False), "",
              f"## Policy minus each control (95% paired item bootstrap, {boot:,} draws, seed {SEED})", "",
              A.md_table(contrast.round(4), index=False), "",
              "## Diagnostics", "",
              f"- Herding: {herd['herded']} of {herd['items_with_2plus_consults']} items with two or more consulting "
              f"members had all of them consult the same teammate (rate {herd['rate']:.3f}); "
              f"{herd['items_with_any_consult']} items had any consult.", "",
              "Action shares under the policy:", "", A.md_table(shares.round(3), index=False), "",
              "Corrections and contaminations per edge (all evidence items' branches; policy_chose: times the policy "
              "took it):", "", A.md_table(edge, index=False), "",
              "Per category:", "", A.md_table(by_cat.round(4), index=False), "",
              "Unparsed and truncated shares per member and phase:", "", A.md_table(rates.round(3), index=False), ""]
    (out / f"{name}_summary.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return rule


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calls", required=True, nargs="+", help="calls.csv of the branch table (both vendor halves)")
    parser.add_argument("--tasks", required=True, help="task JSONL (question text for the folds, meta for categories)")
    parser.add_argument("--items", required=True, help="the id list in frozen order")
    parser.add_argument("--pilot", type=int, default=5, help="leading items of the frozen order that are not evidence")
    parser.add_argument("--name", default="arxivmath")
    parser.add_argument("--out", default=str(OUT))
    parser.add_argument("--draws", type=int, default=20, help="random_matched draws per item")
    parser.add_argument("--boot", type=int, default=BOOT)
    args = parser.parse_args()
    calls = pd.concat([A.load(p) for p in args.calls], ignore_index=True)
    calls = calls.drop_duplicates(["item", "receiver", "action"], keep="last")
    tasks = {t.id: t for t in load_tasks(args.tasks)}
    report(calls, tasks, args.items, args.pilot, args.name, Path(args.out), args.draws, args.boot)


if __name__ == "__main__":
    main()
