"""The evidence plan's run schedule and drop orders (steps 0.13-0.14, 1.2). Writes research/v3/evidence/budget.md.

    python -m analysis.evidence_budget

For every config in configs/experiments/evidence/, the worst case of each item (every call on it at the
dearest input rate and the full max_tokens of output) is summed in the config's item order, and the list is
cut greedily into consecutive slices whose worst case stays at or under CHUNK_USD = $4 / 1.15 = $3.48. Each
slice is one paid run: `aan run <config> --task-offset <offset> --task-limit <limit>`. The plan's expected
spend (list prices, typical tokens) is far below the worst case; the probe (1.1) replaces it.
A config whose model has no price yet (gpt-6.1-sol and gpt-6-astra before Kevin's pricing edit) is listed as
"needs pricing".
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from autoagentnet.agents.agent import prompt_text
from autoagentnet.evidence.panel import PanelConfig, requests_for, select_items
from autoagentnet.pricing import PriceBook, UnknownPrice
from autoagentnet.providers.base import estimate_tokens
from autoagentnet.providers.registry import ProviderRegistry

ROOT = Path(__file__).resolve().parents[1]
NAMES = {"anthropic": "Anthropic", "openai": "OpenAI"}
CONFIGS = ROOT / "configs/experiments/evidence"
OUT = ROOT / "research/v3/evidence/budget.md"
CHUNK_USD = 4.0 / 1.15

PLAN = {  # expected new spend per step in Kevin's D5 order (session E3), Anthropic / OpenAI ($, list prices)
    "1.1 probes": (0.55, 0.79), "1.3 BBEH panel": (6.82, 8.70), "1.4 ForecastBench panel": (3.52, 4.53),
    "2.2 prompt variety": (0.64, 0.65), "2.2b aggregator": (0.36, 0.36), "2.3 more reasoning": (1.10, 1.14),
    "3C pruning lockbox (200 BBEH + 200 ForecastBench)": (6.08, 7.56), "2.4 Opus on BBEH (150 items)": (4.27, 0.0),
}
DROPPED = ("Dropped or deferred by Kevin in session E3: step 1.4b (243 extra market questions, about $2.3 / $2.9), "
           "MathArena 2.5 (deferred to Phase 4 with reasoning on, about $4.24 / $6.34) and Opus on ForecastBench (about $2.25).")

DROP = """## Drop orders (session E3; regenerated after Kevin's D1-D5, to be confirmed by Kevin)

They apply if a vendor projects past $27 of new spend after the probe (1.1), or if the Oct 31 Anthropic deadline is at
risk. Apply in this order, one step at a time, re-estimating after each. The rule that generated them: drop the work
scheduled last first (Kevin's D5 order), and never the confirmatory parts (the Phase 1 panel, which carries H5-H7).
Since session E4 the Phase 3C lockbox carries no confirmatory test (C1 and C2 are exploratory by power; Kevin's
K4 collects it blind), so it is the first candidate to drop if a vendor runs short.

- **Anthropic:** (1) Opus on BBEH cut to 100 items (`e24_opus_bbeh_anth --task-limit 100`, saving about $1.4);
  (2) Opus on BBEH dropped (about $2.8 more); (3) the Haiku half of 2.3 (`e23_reasoning_*_anth`, $1.10);
  (4) the Haiku aggregator 2.2b (`e22b_aggregator_*_anth`, $0.36).
- **OpenAI:** (1) Astra (2.4b, gated, not run before G2); (2) the Luna half of 2.3 (`e23_reasoning_*_open`, $1.14);
  (3) the Luna aggregator 2.2b (`e22b_aggregator_*_open`, $0.36).
- The persona arms (2.2) stay: Phase 3 searches over them and the lockbox repeats them.
- **Astra** (2.4b) runs only if OpenAI new spend after the lockbox is at most $26, and only after G2.

Order of work (Kevin's D5): probes -> e13 BBEH -> e14 ForecastBench -> persona, aggregator and more-reasoning arms ->
Phase 3C lockbox -> Opus BBEH (Anthropic, by Oct 31); the same order for OpenAI by Nov 5. One paid run at a time.
"""


def item_worst_cases(cfg: PanelConfig) -> pd.Series:
    registry = ProviderRegistry.from_yaml(ROOT / cfg.providers)
    book = PriceBook.from_yaml(ROOT / cfg.pricing)
    costs: dict[str, float] = {}
    for item, source, _, request in requests_for(cfg, select_items(cfg), {s.ref: s.ref for s in cfg.sources}):
        ref = source.ref
        usd = book.worst_case_usd(registry.model_id(ref), registry.provider_of(ref),
                                  estimate_tokens(prompt_text(request.spec, request.input)), request.spec.max_tokens)
        costs[item.id] = costs.get(item.id, 0.0) + usd
    return pd.Series(costs)[[t.id for t in select_items(cfg)]]


def expected_usd(cfg: PanelConfig) -> float | None:
    """Expected spend of a config at the probe's measured dollars per call: the number of calls of each ref
    times its `expect.usd_per_call`. None when a ref has no measured cost (it was not probed)."""
    calls: dict[str, int] = {}
    for _, source, _, _ in requests_for(cfg, select_items(cfg), {s.ref: s.ref for s in cfg.sources}):
        calls[source.ref] = calls.get(source.ref, 0) + 1
    if any(ref not in cfg.expect.usd_per_call for ref in calls):
        return None
    return sum(n * cfg.expect.usd_per_call[ref] for ref, n in calls.items())


def slices(worst: pd.Series, cap: float = CHUNK_USD) -> list[tuple[int, int, float]]:
    out, start, total = [], 0, 0.0
    for i, usd in enumerate(worst.to_numpy()):
        if total + usd > cap and i > start:
            out.append((start, i - start, total))
            start, total = i, 0.0
        total += usd
    out.append((start, len(worst) - start, total))
    return out


def schedule() -> pd.DataFrame:
    rows = []
    for path in sorted(CONFIGS.glob("*.yaml")):
        cfg = PanelConfig.from_yaml(path)
        vendor = "anthropic" if path.stem.endswith("_anth") else "openai"
        try:
            worst = item_worst_cases(cfg)
        except UnknownPrice as exc:
            rows.append({"config": path.stem, "vendor": vendor, "items": None, "runs": None, "worst_usd": None,
                         "slices": f"needs pricing ({exc.args[0].split(';')[0]})"})
            continue
        except FileNotFoundError:
            rows.append({"config": path.stem, "vendor": vendor, "items": None, "runs": None, "worst_usd": None,
                         "slices": "needs the Phase 1 panel results"})
            continue
        cut = slices(worst)
        expected = expected_usd(cfg)
        rows.append({"config": path.stem, "vendor": vendor, "items": len(worst), "runs": len(cut),
                     "expected_usd": None if expected is None else round(expected, 2),
                     "worst_usd": round(float(worst.sum()), 2),
                     "slices": ", ".join(f"{o}+{n}" for o, n, _ in cut)})
    return pd.DataFrame(rows)


def remaining(table: pd.DataFrame) -> dict[str, float]:
    """Expected new spend per vendor still to come: every config not yet run (the step 1.1 probes are done and
    the math probes skipped under K6) at the probe's measured costs, plus the plan's figure for the
    more-reasoning arms (2.3), whose settings were not probed."""
    todo = table[~table["config"].str.startswith("e11_")]
    known = todo.groupby("vendor")["expected_usd"].sum()
    a, o = PLAN["2.3 more reasoning"]
    return {"anthropic": float(known.get("anthropic", 0.0)) + a, "openai": float(known.get("openai", 0.0)) + o}


def caps_text(table: pd.DataFrame) -> str:
    """The active phase's caps and the room left, read from the budget rules and the ledger (never hard-coded)."""
    from autoagentnet.budget import BudgetRules, Ledger, SpendGovernor

    rules = BudgetRules.from_yaml(ROOT / "configs" / "budget.yaml")
    phase = rules.phases.get(rules.phase)
    status = SpendGovernor(Ledger(ROOT / "state" / "ledger.jsonl"), rules).status()
    room = status["room_by_account_usd"]
    expected = remaining(table)
    caps = ", ".join(f"{NAMES.get(k, k)} ${v:.0f}" for k, v in (phase.account_caps_usd if phase else {}).items())
    head = ", ".join(f"{NAMES.get(k, k)} ${room[k] - expected[k]:.1f}" for k in expected if k in room)
    return (f"Caps (the budget rules on main): active phase `{rules.phase}`, total ${phase.total_usd:.0f}, run "
            f"${phase.max_run_usd:.0f}, account caps {caps or 'none'}, all lifetime, compared after "
            f"x{rules.safety_multiplier}. Spent so far ${status['spent_total_usd']:.2f}; room left for new estimated "
            "spend: " + ", ".join(f"{NAMES.get(k, k)} ${v:.2f}" for k, v in room.items())
            + ". Expected new spend still to come at the probe's measured costs (2.3 at the plan's figure): "
            + ", ".join(f"{NAMES.get(k, k)} ${v:.2f}" for k, v in expected.items())
            + f", which leaves {head} of headroom.")


def main() -> pd.DataFrame:
    table = schedule()
    lines = ["# Evidence plan: budget, run schedule and drop orders", "",
             "Written by `python -m analysis.evidence_budget`. Worst cases assume every call uses its full max_tokens at the "
             f"dearest input rate; each slice's worst case is at most ${CHUNK_USD:.2f} ($4 run cap / 1.15). A slice "
             "\"o+n\" is `--task-offset o --task-limit n`.", "",
             "## The plan's expected spend (list prices, before the probe; kept for comparison)", "",
             "| step | Anthropic $ | OpenAI $ |", "|---|---|---|",
             *[f"| {k} | {a:.2f} | {o:.2f} |" for k, (a, o) in PLAN.items()],
             f"| **total** | **{sum(a for a, _ in PLAN.values()):.2f}** | **{sum(o for _, o in PLAN.values()):.2f}** |", "",
             DROPPED, "",
             caps_text(table), "",
             "## Run schedule", "",
             "Expected $ is the config's calls at the probe's measured dollars per call (blank: a ref not probed).", "",
             "| config | vendor | items | runs | expected $ | worst case $ | slices |", "|---|---|---|---|---|---|---|",
             *[f"| {r.config} | {r.vendor} | {'' if pd.isna(r.items) else int(r.items)} | {'' if pd.isna(r.runs) else int(r.runs)} | "
               f"{'' if pd.isna(r.expected_usd) else f'{r.expected_usd:.2f}'} | "
               f"{'' if pd.isna(r.worst_usd) else r.worst_usd} | {r.slices} |" for r in table.itertuples()], "", DROP]
    OUT.write_text("\n".join(lines))
    print("\n".join(lines))
    return table


if __name__ == "__main__":
    main()
