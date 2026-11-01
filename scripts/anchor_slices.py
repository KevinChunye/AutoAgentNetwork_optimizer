"""Plan an anchor config's slices so that every run's worst case fits the run cap (session E5, step 5.3). $0.

    python scripts/anchor_slices.py <config.yaml>      # prints one "offset limit worst-case" line per slice

Plain words. `aan check` refuses a run whose worst case (every prompt token at the dearest rate plus the full
max_tokens of output, times the safety multiplier) would pass the run cap ($4). The anchor's ceilings are generous on
purpose (truncation is not part of an arm), so its worst cases are large next to its expected cost; this script walks
the config's items in order and cuts a new slice whenever the next item's worst case would push the slice past
FILL x the run cap. It only estimates; it never calls a model.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoagentnet.agents.agent import prompt_text  # noqa: E402
from autoagentnet.budget import BudgetRules, effective_run_cap  # noqa: E402
from autoagentnet.evidence.panel import PanelConfig, requests_for, select_items  # noqa: E402
from autoagentnet.pricing import PriceBook  # noqa: E402
from autoagentnet.providers.base import estimate_tokens  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402

FILL = 0.95


def per_item_worst(cfg: PanelConfig) -> list[float]:
    """Worst-case dollars x safety of each item of the config, in order (the same pricing as estimate_panel)."""
    registry = ProviderRegistry.from_yaml(ROOT / cfg.providers)
    pricebook = PriceBook.from_yaml(ROOT / cfg.pricing)
    safety = BudgetRules.from_yaml(ROOT / cfg.budget).safety_multiplier
    items = select_items(cfg)
    worst = {t.id: 0.0 for t in items}
    for item, source, _, request in requests_for(cfg, items, {s.ref: s.ref for s in cfg.sources}):
        worst[item.id] += pricebook.worst_case_usd(registry.model_id(source.ref), registry.provider_of(source.ref),
                                                   estimate_tokens(prompt_text(request.spec, request.input)),
                                                   request.spec.max_tokens)
    return [worst[t.id] * safety for t in items]


def slices(worst: list[float], cap: float) -> list[tuple[int, int, float]]:
    out, start, total = [], 0, 0.0
    for k, w in enumerate(worst):
        if total + w > FILL * cap and k > start:
            out.append((start, k - start, total))
            start, total = k, 0.0
        total += w
    out.append((start, len(worst) - start, total))
    return out


def main(path: str) -> None:
    cfg = PanelConfig.from_yaml(path)
    rules = BudgetRules.from_yaml(ROOT / cfg.budget)
    cap = effective_run_cap(rules, cfg.max_usd)
    for offset, limit, total in slices(per_item_worst(cfg), cap):
        print(offset, limit, f"{total:.2f}")


if __name__ == "__main__":
    main(sys.argv[1])
