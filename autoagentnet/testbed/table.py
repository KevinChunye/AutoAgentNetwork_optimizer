"""The response table: E5's atlas schema (autoagentnet/atlas/schema.py), shared by the Atlas and the testbed.

Testbed conventions inside that schema:
  benchmark   "bbeh/<task>", "math/<competition>", "code/lcb_v6" (synthetic world: "bbeh/synthetic", ...)
  system      Config.label, e.g. "qwen3.5-4b:w4:budget:1024"
  model       the Hugging Face repo of the weights' source (synthetic world: the checkpoint name)
  precision   bits only (W4 GPTQ is "w4"; the method shows in `system`)
  reasoning   "off", "budget:<tokens>" or "effort:<level>"
  scaffold    "direct"
  answer      missing when unparsed (code: the program's behaviour class)
  signal_*    logprob_mean, entropy, margin, thinking_tokens, forced, exec_visible, truncated
Per-call metadata the schema has no column for (seed, finish reason, the answer text) goes to a sidecar
*.texts.parquet next to each shard.
"""

from __future__ import annotations

import pandas as pd

from ..atlas import schema
from .grid import Config

GRADERS = {"bbeh": "bbeh", "math": "math", "code": "code"}


def validate(frame: pd.DataFrame) -> pd.DataFrame:
    """The frame coerced to the schema's types; ValueError listing every problem otherwise."""
    return schema.check(frame)


def family_of(benchmark: str) -> str:
    """"bbeh/web_of_lies" -> "bbeh"."""
    return str(benchmark).split("/", 1)[0]


def budget_of(reasoning: str) -> int:
    kind, _, value = str(reasoning).partition(":")
    return int(value) if kind == "budget" else 0


def configs(frame: pd.DataFrame) -> pd.DataFrame:
    """One row per system: system, family, size_b, precision (the method tag, e.g. w4gptq), budget, effort."""
    rows = []
    for system in frame["system"].drop_duplicates():
        c = Config.from_label(system)
        rows.append({"system": system, "family": c.family, "size_b": c.size_b, "precision": c.precision,
                     "budget": c.budget, "effort": c.effort})
    return pd.DataFrame(rows)
