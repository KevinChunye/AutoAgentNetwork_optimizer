"""Self-or-social pruning: freeze the policy on the calibration (dev) items, then read the test items once.

  python analysis/self_or_social.py freeze --dev results/sos_dev/calls.csv
      Fits every policy and control on dev only and writes research/self_or_social/frozen.json:
        policy          the main policy, with (lam, use_family) picked by two-fold cross-fitting on dev (rule below);
        self_only       the same fit restricted to stop and reflect;
        forced_social   the main fit with stop removed (one revision per member);
        fixed_peers     each receiver's best directed peer; smartest_peers: each receiver's most accurate other member;
        order           the vote's tie-break order: members by dev first-answer accuracy, best first.
      Rule for (lam, use_family): fit on one half of dev, score the policy's team accuracy on the other half and
      back, average; take the highest cross-fitted accuracy; among settings within 0.005 of it, the largest lam
      (the cheapest), then use_family False. Also prints the dev tables (directed gains, action outcomes).

  python analysis/self_or_social.py read --test results/sos_test/calls.csv [--single results/e51_sonnet_bbeh/calls.csv]
      Scores every method on the test items with the committed frozen.json (refuses an uncommitted one unless
      --allow-uncommitted, for dry runs) and writes reports/self_or_social/: per_item.csv, summary.csv,
      contrasts.csv, edges.csv, summary.md and frontier.png. Every read also writes refusals.csv (provider
      refusals per member and action). --refusal-fallback (LAB-Bench prereg note 10, a secondary read): a refused
      revision counts as the member's first answer.

Terms are those of autoagentnet/self_or_social (score.py lists the methods). Accuracy is the share of items whose
voted answer is right; cost is the logical deployment dollars per item (every first answer counted, reused or not);
new spend is what the runs added to the ledger (live calls only). Intervals are 95% paired item bootstraps.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoagentnet.evidence.panel import uncommitted  # noqa: E402
from autoagentnet.self_or_social.policy import (Policy, branch_table, fit, fixed_peers, smartest_peers,  # noqa: E402
                                                social_net_gain)
from autoagentnet.self_or_social.score import full_review_items, paired_bootstrap, score_items  # noqa: E402

FROZEN = ROOT / "research/self_or_social/frozen.json"
REPORT = ROOT / "reports/self_or_social"
LAMS = [0.0, 3.0, 10.0, 30.0, 100.0]  # points of P per dollar x 0.01: lam 30 prices $0.001 at 0.03 of P
SHRINK = 5.0
SEED = 2026  # the preregistered bootstrap seed (audit SC-12: the read had used the function default, 0)
CORE_BASELINES = ["vote", "all_reflect", "fixed_peer", "random_matched", "strong_single", "full_review"]


def md_table(frame: pd.DataFrame, index: bool = True) -> str:
    """A GitHub markdown table of a small frame (no extra dependency)."""
    frame = frame.reset_index() if index else frame
    cols = [str(c) for c in frame.columns]
    fmt = lambda v: f"{v:.4g}" if isinstance(v, float) else str(v)  # noqa: E731
    lines = ["| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
    lines += ["| " + " | ".join(fmt(v) for v in row) + " |" for row in frame.itertuples(index=False)]
    return "\n".join(lines)


def load(path: str) -> pd.DataFrame:
    return pd.read_csv(path, dtype={"answer": str, "reply": str})


REFUSALS = ("refusal", "content_filter", "invalid_prompt")
TEXT_REFUSAL_STOPS = ("stop", "end_turn")  # the model finished the reply itself (OpenAI "stop", Anthropic "end_turn")
FALLBACK_COLUMNS = ("answer", "parsed", "correct", "prob", "format_ok")


def refused_mask(calls: pd.DataFrame) -> pd.Series:
    """LAB-Bench note 16: a refused call is a provider refusal or block (stop_reason in REFUSALS) or a text refusal,
    i.e. a reply the model finished itself (not cut off) that the parser cannot read, such as "I can't help with
    that". The text rule is mechanical, so it also counts the rare unreadable answer that is not a refusal."""
    provider = calls["stop_reason"].isin(REFUSALS)
    text = ~calls["parsed"].astype(bool) & calls["stop_reason"].isin(TEXT_REFUSAL_STOPS)
    return provider | text


def refusal_counts(calls: pd.DataFrame) -> pd.DataFrame:
    """Refused calls per member and action (note 16): calls, provider refusals or blocks, text refusals, both, share."""
    frame = calls.assign(provider=calls["stop_reason"].isin(REFUSALS), refused=refused_mask(calls))
    frame = frame.assign(text=frame["refused"] & ~frame["provider"])
    return (frame.groupby(["receiver", "ref", "action"])
            .agg(calls=("refused", "size"), provider=("provider", "sum"), text=("text", "sum"), refused=("refused", "sum"))
            .assign(share=lambda d: d["refused"] / d["calls"]).reset_index())


def refusal_fallback(calls: pd.DataFrame) -> pd.DataFrame:
    """The secondary read of LAB-Bench prereg note 10: a refused revision counts as the member's own first answer
    (the deployment keeps its answer); its dollars stay as billed. First answers and other rows are unchanged."""
    out = calls.copy()
    cols = [c for c in FALLBACK_COLUMNS if c in out]
    first = out[out["action"] == "initial"].set_index(["item", "receiver"])[cols]
    refused = (out["action"] != "initial") & refused_mask(out)
    keys = pd.MultiIndex.from_frame(out.loc[refused, ["item", "receiver"]])
    out.loc[refused, cols] = first.reindex(keys).to_numpy()
    return out


def team_of(calls: pd.DataFrame) -> list[str]:
    first = calls[calls["action"] == "initial"].drop_duplicates("receiver").sort_values("position")
    return first["receiver"].tolist()


def graders_of(calls: pd.DataFrame) -> dict[str, str]:
    return dict(calls.drop_duplicates("item")[["item", "grader"]].itertuples(index=False, name=None))


def fold_of(item: str) -> int:
    return int(hashlib.sha256(f"sos-fold:{item}".encode()).hexdigest(), 16) % 2


def policy_accuracy(table: pd.DataFrame, team: list[str], graders: dict, pol: Policy, order: list[int]) -> tuple[float, float]:
    per_item = score_items(table, team, graders, {"policy": pol}, {r: team[0] for r in team},
                           {r: team[0] for r in team}, order=order, draws=1)
    mine = per_item[per_item["method"] == "policy"]
    return float(mine["correct"].mean()), float(mine["cost"].mean())


def tie_order(table: pd.DataFrame, team: list[str]) -> list[int]:
    acc = table[table["kind"] == "stop"].groupby("receiver")["correct"].mean()
    ranked = pd.DataFrame({"receiver": team, "pos": range(len(team))}).assign(acc=lambda d: d["receiver"].map(acc))
    return ranked.sort_values(["acc", "pos"], ascending=[False, True])["pos"].tolist()


def fit_frozen(table: pd.DataFrame, team: list[str], graders: dict) -> dict:
    """Every policy and control fitted on one branch table (the freeze's rule, module docstring): the tie order, the
    cross-fitted (lam, use_family), the main policy, self_only, forced_social, the lam curve, the fixed and smartest
    peers and the policy hash. `freeze` writes it with the dev file's name; analysis/sos_crossfit.py fits it per fold."""
    order = tie_order(table, team)
    cv = []
    for use_family in (False, True):
        for lam in LAMS:
            accs, costs = [], []
            for k in (0, 1):
                train = table[table["item"].map(fold_of) != k]
                held = table[table["item"].map(fold_of) == k]
                pol = fit(train, team, lam=lam, shrink=SHRINK, use_family=use_family)
                a, c = policy_accuracy(held, team, graders, pol, order)
                accs.append(a)
                costs.append(c)
            cv.append({"lam": lam, "use_family": use_family, "cv_acc": sum(accs) / 2, "cv_cost": sum(costs) / 2})
    cv = pd.DataFrame(cv)
    best = cv["cv_acc"].max()
    pick = cv[cv["cv_acc"] >= best - 0.005].sort_values(["lam", "use_family"], ascending=[False, True]).iloc[0]
    lam, use_family = float(pick["lam"]), bool(pick["use_family"])
    main = fit(table, team, lam=lam, shrink=SHRINK, use_family=use_family)
    frozen = {
        "team": team, "order": order,
        "lam_grid": LAMS, "shrink": SHRINK, "cv": cv.to_dict("records"), "picked": {"lam": lam, "use_family": use_family},
        "policy": json.loads(main.to_json()),
        "self_only": json.loads(fit(table, team, lam=lam, shrink=SHRINK, use_family=use_family,
                                    kinds=["stop", "reflect"]).to_json()),
        "forced_social": json.loads(fit(table, team, lam=lam, shrink=SHRINK, use_family=use_family,
                                        allow_stop=False).to_json()),
        "lam_curve": {str(x): json.loads(fit(table, team, lam=x, shrink=SHRINK, use_family=use_family).to_json())
                      for x in LAMS},
        "fixed_peers": fixed_peers(table), "smartest_peers": smartest_peers(table),
    }
    frozen["policy_hash"] = main.hash()
    return frozen


def freeze(args) -> None:
    calls = load(args.dev)
    team, graders = team_of(calls), graders_of(calls)
    table = branch_table(calls)
    frozen = {"dev": str(args.dev), "dev_items": int(table["item"].nunique()), **fit_frozen(table, team, graders)}
    order, cv = frozen["order"], pd.DataFrame(frozen["cv"])
    lam, use_family = frozen["picked"]["lam"], frozen["picked"]["use_family"]
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(frozen, indent=1, sort_keys=True))
    pd.set_option("display.width", 200)
    print(f"dev items {frozen['dev_items']}; team {team}; vote order {order}")
    print("cross-fitted policy accuracy and cost on dev:\n" + cv.round(4).to_string(index=False))
    print(f"picked lam {lam}, use_family {use_family}; policy hash {frozen['policy_hash']}")
    print("directed gains on dev (consult J vs reflect, receiver i):\n" + social_net_gain(table).round(3).to_string(index=False))
    outcomes = table.groupby(["receiver", "action"]).agg(n=("correct", "size"), acc=("correct", "mean"),
                                                         usd=("extra_cost", "mean")).reset_index()
    print("dev outcome of each action:\n" + outcomes.round(5).to_string(index=False))
    print(f"wrote {out}")


def strong_single(path: str, source: str, items: set[str]) -> pd.DataFrame:
    calls = pd.read_csv(path, usecols=["item", "meta_task", "source", "call", "correct", "cost_usd"])
    mine = calls[(calls["source"] == source) & (calls["call"] == 0) & calls["item"].isin(items)]
    return pd.DataFrame({"item": mine["item"], "family": mine["meta_task"], "method": "strong_single",
                         "answer": None, "correct": mine["correct"].astype(float), "cost": mine["cost_usd"],
                         "calls": 1, "actions": source})


def member_singles(table: pd.DataFrame, calls: pd.DataFrame) -> pd.DataFrame:
    """Each member alone: its first answer, at its own first-answer dollars (audit SC-12: the earlier version split
    the team's first-answer cost evenly, so every single showed the same cost)."""
    first = table[table["kind"] == "stop"]
    own = calls[calls["action"] == "initial"].groupby(["item", "receiver"])["cost_usd"].sum().rename("own_cost")
    first = first.merge(own.reset_index(), on=["item", "receiver"], how="left")
    return pd.DataFrame({"item": first["item"], "family": first["family"], "method": "single_" + first["receiver"],
                         "answer": first["answer"], "correct": first["correct"].astype(float),
                         "cost": first["own_cost"], "calls": 1, "actions": "first answer"})


def score_frozen(calls: pd.DataFrame, table: pd.DataFrame, team: list[str], graders: dict, frozen: dict,
                 draws: int = 20, seed: int = 0) -> pd.DataFrame:
    """Per item and method, every policy and control of `frozen` (fit_frozen) scored on these items' branch table
    (score.score_items), plus each member alone (member_singles) and the full-review control (score.full_review_items)."""
    policies = {name: Policy(**frozen[name]) for name in ("policy", "self_only", "forced_social")}
    policies.update({f"policy_lam{k}": Policy(**v) for k, v in frozen["lam_curve"].items()})
    per_item = score_items(table, team, graders, policies, frozen["fixed_peers"], frozen["smartest_peers"],
                           order=frozen["order"], draws=draws, seed=seed)
    parts = [per_item, member_singles(table, calls), full_review_items(calls, team, graders, frozen["order"])]
    return pd.concat([p for p in parts if not p.empty], ignore_index=True)


def read(args) -> None:
    frozen_path = Path(args.frozen)
    if not args.allow_uncommitted and uncommitted([str(frozen_path.relative_to(ROOT)) if frozen_path.is_absolute()
                                                   else str(frozen_path)]):
        raise SystemExit(f"{frozen_path} must be committed before the test is read (freeze first, commit, then read)")
    frozen = json.loads(frozen_path.read_text())
    calls = load(args.test)
    team, graders = team_of(calls), graders_of(calls)
    if team != frozen["team"]:
        raise SystemExit(f"test team {team} is not the frozen team {frozen['team']}")
    dev_ids = set(load(frozen["dev"])["item"]) if Path(frozen["dev"]).exists() else set()
    overlap = dev_ids & set(calls["item"])
    if overlap:
        raise SystemExit(f"{len(overlap)} test items are dev items, e.g. {sorted(overlap)[0]}")
    refusals = refusal_counts(calls)
    if getattr(args, "refusal_fallback", False):
        calls = refusal_fallback(calls)
    table = branch_table(calls)
    parts = [score_frozen(calls, table, team, graders, frozen, args.draws)]
    if args.single:
        parts.append(strong_single(args.single, args.single_source, set(table["item"])))
    per_item = pd.concat([p for p in parts if not p.empty], ignore_index=True)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    per_item.to_csv(out / "per_item.csv", index=False)
    refusals.to_csv(out / "refusals.csv", index=False)
    summary = per_item.groupby("method").agg(items=("item", "nunique"), accuracy=("correct", "mean"),
                                             usd_per_item=("cost", "mean"), calls_per_item=("calls", "mean"))
    summary = summary.sort_values(["accuracy", "usd_per_item"], ascending=[False, True])
    summary.to_csv(out / "summary.csv")
    baselines = [b for b in CORE_BASELINES if b != "strong_single" or args.single]
    baselines += ["self_only", "forced_social", "smartest_peer"] + ["single_" + r for r in team]
    seed = getattr(args, "seed", SEED)
    rows = [paired_bootstrap(per_item, "policy", b, draws=args.boot, seed=seed) for b in baselines]
    rows.append(paired_bootstrap(per_item, "fixed_peer", "all_reflect", draws=args.boot, seed=seed))  # H4
    contrasts = pd.DataFrame(rows)
    contrasts.to_csv(out / "contrasts.csv", index=False)

    pol_rows = per_item[per_item["method"] == "policy"]
    acts = pol_rows["actions"].str.split(" ").explode().str.split("=", n=1, expand=True)
    acts.columns = ["receiver", "action"]
    shares = acts["action"].map(lambda a: a.split(":")[0]).value_counts(normalize=True).rename("share")
    edges = acts[acts["action"].str.startswith("consult:")].assign(sender=lambda d: d["action"].str.split(":").str[1])
    edges = edges.groupby(["sender", "receiver"]).size().rename("count").reset_index()
    edges.to_csv(out / "edges.csv", index=False)

    new_spend = float(calls.loc[~calls["from_cache"].astype(bool), "cost_usd"].sum())
    fake = calls["model_version"].astype(str).str.contains("fake").any()
    dev_calls = load(frozen["dev"]) if Path(frozen["dev"]).exists() else pd.DataFrame()
    calib = float(dev_calls["cost_usd"].sum()) if not dev_calls.empty else float("nan")
    pol_cost = float(summary.loc["policy", "usd_per_item"])
    lines = ["# Self-or-social pruning: test read", ""]
    if fake:
        lines += ["**DRY RUN on the fake model: these numbers test the pipeline and are not results.**", ""]
    lines += [f"Test items: {table['item'].nunique()} (`{args.test}`). Frozen policy `{frozen['policy_hash']}` "
              f"(lam {frozen['picked']['lam']}, use_family {frozen['picked']['use_family']}), fitted on "
              f"{frozen['dev_items']} dev items. Team {team}; vote tie order {frozen['order']}.", "",
              "## Accuracy and cost per method", "", md_table(summary.round(4)), "",
              "## Policy minus each control (95% paired item bootstrap)", "",
              md_table(contrasts.round(4), index=False), "",
              "## What the policy did", "", md_table(shares.round(3).to_frame()), "",
              md_table(edges, index=False) if not edges.empty else "No consult edges.", "",
              "## Money", "",
              f"- New spend of the test runs (live calls): ${new_spend:.4f}.",
              f"- Calibration's logical dollars (every dev call, first answers included): ${calib:.4f}.",
              f"- Deploying the policy on T items costs calibration + T x ${pol_cost:.5f}.", ""]
    (out / "summary.md").write_text("\n".join(lines))
    frontier(summary, out / "frontier.png", fake)
    print("\n".join(lines))


def frontier(summary: pd.DataFrame, path: Path, fake: bool) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    main = summary[~summary.index.str.startswith("policy_lam")]
    curve = summary[summary.index.str.startswith("policy_lam")].sort_values("usd_per_item")
    fig, ax = plt.subplots(figsize=(7, 4.5))
    ax.plot(curve["usd_per_item"] * 1000, curve["accuracy"], color="0.6", marker=".", lw=1, label="policy, lam grid")
    for name, row in main.iterrows():
        mark = "o" if name == "policy" else "s"
        ax.scatter(row["usd_per_item"] * 1000, row["accuracy"], marker=mark, s=60 if name == "policy" else 30,
                   color="C3" if name == "policy" else "C0")
        ax.annotate(name, (row["usd_per_item"] * 1000, row["accuracy"]), fontsize=8, xytext=(4, 2),
                    textcoords="offset points")
    ax.set_xlabel("dollars per item (x 1/1000)")
    ax.set_ylabel("team accuracy")
    ax.set_title("Self-or-social: accuracy vs cost" + (" (FAKE DRY RUN)" if fake else ""))
    ax.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    f = sub.add_parser("freeze")
    f.add_argument("--dev", required=True)
    f.add_argument("--out", default=str(FROZEN))
    r = sub.add_parser("read")
    r.add_argument("--test", required=True)
    r.add_argument("--frozen", default=str(FROZEN))
    r.add_argument("--single", default=None, help="calls.csv of the strong single control (call 0 of --single-source)")
    r.add_argument("--single-source", default="sonnet_low:base")
    r.add_argument("--out", default=str(REPORT))
    r.add_argument("--draws", type=int, default=20)
    r.add_argument("--boot", type=int, default=2000)
    r.add_argument("--seed", type=int, default=SEED, help="bootstrap seed (preregistered: 2026)")
    r.add_argument("--allow-uncommitted", action="store_true")
    r.add_argument("--refusal-fallback", action="store_true",
                   help="secondary read: a refused revision counts as the member's first answer (use another --out)")
    args = parser.parse_args()
    freeze(args) if args.command == "freeze" else read(args)


if __name__ == "__main__":
    main()
