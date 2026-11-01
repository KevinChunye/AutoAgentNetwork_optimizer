"""A one-page replay of the self-or-social team on recorded items (no API call): first answers, each member's
state and frozen action, the consult edges actually used, the revisions, the vote, and the dollars.

  python analysis/sos_demo.py --calls results/sos_test/calls.csv [--summary reports/self_or_social/summary.csv]
      writes reports/self_or_social/demo.html

Every number on the page comes from the calls.csv rows (recorded replies, grades and dollars) and the committed
frozen policy; the actions are recomputed from the first answers exactly as the deployed policy decides them.
Items are shown in this order: those where the policy consulted a peer and the team's answer changed, then the
other consult items, then the rest.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoagentnet.self_or_social.policy import Policy, branch_table  # noqa: E402
from autoagentnet.self_or_social.protocol import STOP, peer_of, vote  # noqa: E402

POS = [(110, 40), (40, 160), (180, 160)]  # node centres for up to three members


def svg(team: list[str], actions: dict[str, str], right: dict[str, bool]) -> str:
    parts = ['<svg width="230" height="200" viewBox="0 0 230 200">',
             '<defs><marker id="arr" markerWidth="8" markerHeight="8" refX="7" refY="3" orient="auto">'
             '<path d="M0,0 L7,3 L0,6 z" fill="#d9480f"/></marker></defs>']
    at = {r: POS[i % 3] for i, r in enumerate(team)}
    for r in team:
        peer = peer_of(actions[r])
        if peer is not None:
            (x1, y1), (x2, y2) = at[peer], at[r]
            dx, dy = x2 - x1, y2 - y1
            n = max((dx * dx + dy * dy) ** 0.5, 1)
            parts.append(f'<line x1="{x1 + dx / n * 26:.0f}" y1="{y1 + dy / n * 26:.0f}" x2="{x2 - dx / n * 28:.0f}" '
                         f'y2="{y2 - dy / n * 28:.0f}" stroke="#d9480f" stroke-width="3" marker-end="url(#arr)"/>')
    for r in team:
        x, y = at[r]
        kind = actions[r].split(":")[0]
        fill = {"stop": "#e9ecef", "reflect": "#d0ebff", "consult": "#ffe8cc"}[kind]
        ring = "#2b8a3e" if right[r] else "#c92a2a"
        parts.append(f'<circle cx="{x}" cy="{y}" r="24" fill="{fill}" stroke="{ring}" stroke-width="3"/>')
        parts.append(f'<text x="{x}" y="{y + 5}" text-anchor="middle" font-size="16" font-weight="bold">{r}</text>')
        if kind == "reflect":
            parts.append(f'<text x="{x}" y="{y - 30}" text-anchor="middle" font-size="11">&#8635; reflect</text>')
        elif kind == "stop":
            parts.append(f'<text x="{x}" y="{y - 30}" text-anchor="middle" font-size="11">stop</text>')
    parts.append("</svg>")
    return "".join(parts)


def short(text, n=60) -> str:
    t = "" if text is None or (isinstance(text, float) and pd.isna(text)) else str(text)
    return html.escape(t if len(t) <= n else t[: n - 1] + "…")


def build(calls_path: str, frozen_path: str, out_path: str, items: int = 8, summary: str | None = None) -> None:
    calls = pd.read_csv(calls_path, dtype={"answer": str, "reply": str})
    frozen = json.loads(Path(frozen_path).read_text())
    team, order = frozen["team"], frozen["order"]
    policy = Policy(**frozen["policy"])
    table = branch_table(calls)
    graders = dict(calls.drop_duplicates("item")[["item", "grader"]].itertuples(index=False, name=None))
    fake = calls["model_version"].astype(str).str.contains("fake").any()
    cards = []
    for item, group in table.groupby("item", sort=False):
        rows = {(r, a): row for r, a, row in zip(group["receiver"], group["action"], group.to_dict("records"))}
        family = str(group["family"].iloc[0])
        state = {r: rows[(r, STOP)]["state"] for r in team}
        actions = {r: policy.choose(r, state[r], family) for r in team}
        if not all((r, actions[r]) in rows for r in team):
            continue
        first = [rows[(r, STOP)] for r in team]
        final = [rows[(r, actions[r])] for r in team]
        v0, w0 = vote([f["answer"] if isinstance(f["answer"], str) else None for f in first], graders[item], order)
        v1, w1 = vote([f["answer"] if isinstance(f["answer"], str) else None for f in final], graders[item], order)
        ok0 = w0 is not None and first[w0]["correct"] == 1.0
        ok1 = w1 is not None and final[w1]["correct"] == 1.0
        consulted = any(peer_of(a) for a in actions.values())
        rank = 0 if consulted and ok0 != ok1 else 1 if consulted else 2
        cost0 = float(group["initial_cost"].iloc[0])
        cost1 = cost0 + sum(float(f["extra_cost"]) for f in final)
        member_rows = "".join(
            f"<tr><td><b>{r}</b></td><td>{short(state[r])}</td><td>{short(f0['answer'])} {'✔' if f0['correct'] == 1 else '✘'}</td>"
            f"<td><b>{html.escape(actions[r])}</b></td><td>{short(f1['answer'])} {'✔' if f1['correct'] == 1 else '✘'}</td></tr>"
            for r, f0, f1 in zip(team, first, final))
        cards.append((rank, f"""
<div class="item"><h3>{html.escape(item)} <span class="fam">{html.escape(family)}</span></h3>
<div class="row">{svg(team, actions, {r: f['correct'] == 1 for r, f in zip(team, final)})}
<div><table><tr><th>member</th><th>first-round state</th><th>first answer</th><th>action (frozen policy)</th><th>final answer</th></tr>
{member_rows}</table>
<p>Vote of first answers: <b>{short(v0)}</b> {'✔' if ok0 else '✘'} at ${cost0:.5f} &nbsp;→&nbsp;
self-or-social: <b>{short(v1)}</b> {'✔' if ok1 else '✘'} at ${cost1:.5f}
({sum(a != STOP for a in actions.values())} revision calls)</p></div></div></div>"""))
    cards = [c for _, c in sorted(cards, key=lambda rc: rc[0])][:items]
    table_html = ""
    if summary and Path(summary).exists():
        s = pd.read_csv(summary, index_col=0)
        s = s[~s.index.str.startswith("policy_lam")].round(4)
        table_html = "<h2>All methods on the test items</h2>" + s.to_html(classes="summary")
    banner = '<p class="fake">FAKE MODEL DRY RUN: pipeline check only, not results.</p>' if fake else ""
    page = f"""<!DOCTYPE html><html><head><meta charset="utf-8"><title>Self-or-social replay</title>
<style>body{{font-family:system-ui,sans-serif;max-width:1000px;margin:24px auto;color:#212529}}
.item{{border:1px solid #dee2e6;border-radius:8px;padding:10px 16px;margin:14px 0}}.row{{display:flex;gap:18px;align-items:center}}
table{{border-collapse:collapse;font-size:14px}}td,th{{border-bottom:1px solid #e9ecef;padding:4px 8px;text-align:left}}
.fam{{font-size:13px;color:#868e96;font-weight:normal}}.fake{{background:#fff3bf;padding:8px;font-weight:bold}}
.legend span{{display:inline-block;padding:2px 8px;border-radius:4px;margin-right:6px}}</style></head><body>
<h1>Learn when to think alone, and when to ask whom</h1>
<p><b>Replay</b> of recorded calls from <code>{html.escape(calls_path)}</code>: no API call is made on this page.
Each member keeps its first answer (stop), re-checks it alone (reflect), or reads one teammate's first answer
(consult; arrow from the teammate read). Policy <code>{frozen['policy_hash']}</code>, fitted on dev and frozen
before the test. Ring colour: final answer right (green) or wrong (red).</p>
<p class="legend"><span style="background:#e9ecef">stop</span><span style="background:#d0ebff">reflect</span>
<span style="background:#ffe8cc">consult</span></p>{banner}
{''.join(cards)}{table_html}</body></html>"""
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(page)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--calls", required=True)
    parser.add_argument("--frozen", default=str(ROOT / "research/self_or_social/frozen.json"))
    parser.add_argument("--summary", default=None)
    parser.add_argument("--items", type=int, default=8)
    parser.add_argument("--out", default=str(ROOT / "reports/self_or_social/demo.html"))
    args = parser.parse_args()
    build(args.calls, args.frozen, args.out, args.items, args.summary)
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
