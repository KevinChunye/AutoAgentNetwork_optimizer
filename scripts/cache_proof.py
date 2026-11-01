"""Before a paid run that should replay earlier calls: how many of a config slice's calls are already in the cache
(audit 87). Read-only and offline: nothing is called and nothing is written.

    python scripts/cache_proof.py <config.yaml> [--task-offset N] [--task-limit M]

Plain words. The runner looks a call up by a key made of the agent spec, the model id, the ref's options, the input and
the call index (market/caller.MarketCaller.call). This script builds the slice's requests exactly as the runner does
(evidence/panel.requests_for), makes the same keys, and counts how many the cache (the config's `cache` folder) holds.
It prints "hits of calls" per source and in total.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from autoagentnet.cache import CallCache, make_key  # noqa: E402
from autoagentnet.evidence.panel import PanelConfig, requests_for, select_items  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402


def cache_hits(cfg: PanelConfig, cache: CallCache, registry: ProviderRegistry) -> pd.DataFrame:
    """Per source label: the slice's calls and how many of their keys the cache holds."""
    ref_of = {s.ref: s.ref for s in cfg.sources}
    rows = []
    for item, source, c, request in requests_for(cfg, select_items(cfg), ref_of):
        ref = request.spec.model
        key = make_key(request.spec.model_dump(), registry.model_id(ref), registry.options_of(ref),
                       request.input.model_dump(), c)
        rows.append({"source": source.label, "hit": cache.get(key) is not None})
    frame = pd.DataFrame(rows)
    return frame.groupby("source").agg(calls=("hit", "size"), hits=("hit", "sum")).reset_index()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("config")
    parser.add_argument("--task-offset", type=int, default=0)
    parser.add_argument("--task-limit", type=int, default=None)
    args = parser.parse_args()
    cfg = PanelConfig.from_yaml(args.config).model_copy(update={"task_offset": args.task_offset,
                                                                 "task_limit": args.task_limit})
    table = cache_hits(cfg, CallCache(ROOT / cfg.cache), ProviderRegistry.from_yaml(ROOT / cfg.providers))
    for row in table.itertuples():
        print(f"{row.source}: {row.hits} of {row.calls} in the cache")
    print(f"total: {table['hits'].sum()} of {table['calls'].sum()} in the cache")
    return 0


if __name__ == "__main__":
    sys.exit(main())
