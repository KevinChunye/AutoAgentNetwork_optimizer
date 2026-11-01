"""Our own panel runs (results/<run>/calls.csv) as response-table rows (Atlas source 4.2b).

Plain words. A panel run writes one row per call: the item, the source (model ref and prompt), the call index, the
parsed answer, whether it was right, tokens, dollars and seconds. One response-table row per call here:
  benchmark  "<task kind>/<task>" for BBEH ("bbeh/boolean expressions"), else the task kind ("math", "forecast")
  system     the model ref ("haiku_nothink"), with ":<prompt>" appended for any prompt other than the base one
  family     the vendor: "anthropic" for claude-* models, "openai" for gpt-* models
  reasoning  from the request settings the run recorded: thinking disabled, Sonnet's "between_tools" (no thinking
             outside tool use, so none on a direct prompt) and reasoning_effort "none" are "off"; an effort level is
             "effort:<level>"
  answer     the parsed answer's class on its item ("c0", "c1", ... in order of first appearance; answers equal
             under the task's grader share a class; unparsed is missing), so votes and coincidences can be computed
             without the answer text
  input_tokens  prompt tokens including cache writes and reads
Rows with an unparsed answer count as wrong (correct 0), as everywhere else in this project.
"""

from __future__ import annotations

import json

import pandas as pd

from autoagentnet.evidence.labelfree import candidates
from autoagentnet.tasks import answers_match

LICENCE = "internal"


def reasoning_of(setting: str) -> str:
    s = json.loads(setting) if isinstance(setting, str) and setting else {}
    thinking = (s.get("thinking") or {}).get("type")
    effort = s.get("reasoning_effort") or (s.get("output_config") or {}).get("effort")
    if effort and effort != "none":
        return f"effort:{effort}"
    if thinking in ("disabled", "between_tools") or effort == "none":
        return "off"
    return "unknown"


def family_of(model: str) -> str:
    m = str(model).lower()
    return "anthropic" if m.startswith("claude") else "openai" if m.startswith("gpt") else "unknown"


def classes(calls: pd.DataFrame, grader: str) -> pd.Series:
    """Each call's answer class on its item under the grader (missing when unparsed)."""
    out = pd.Series(pd.NA, index=calls.index, dtype="string")
    for _, g in calls.groupby("item"):
        answers = [a if (p and isinstance(a, str)) else None for a, p in zip(g["answer"], g["parsed"].astype(bool))]
        _, idx = candidates(answers, lambda a, b: answers_match(a, b, grader))
        out.loc[g.index] = [None if k is None else f"c{k}" for k in idx]
    return out


def load(calls: pd.DataFrame, run: str, items: set[str] | None = None) -> pd.DataFrame:
    """Response-table rows of one run's calls (optionally only the listed items)."""
    c = calls if items is None else calls[calls["item"].isin(items)]
    c = c.reset_index(drop=True)
    kind = c["task_kind"].astype(str)
    benchmark = kind.where(kind != "bbeh", "bbeh/" + c["meta_task"].astype(str))
    system = c["ref"].astype(str).where(c["prompt"] == "base", c["ref"].astype(str) + ":" + c["prompt"].astype(str))
    answer = pd.concat([classes(g, k) for k, g in c.groupby(kind)]).reindex(c.index)
    tokens_in = c[["input_tokens", "cache_write_tokens", "cache_read_tokens"]].fillna(0).sum(axis=1)
    return pd.DataFrame({
        "benchmark": benchmark, "item": c["item"].astype(str), "system": system,
        "family": c["model"].map(family_of), "model": c["model"].astype(str), "size_b": None, "precision": "api",
        "reasoning": c["setting"].map(reasoning_of),
        "scaffold": c["prompt"].astype(str).where(c["prompt"] != "base", "direct"),
        "call": c["call"].astype(int), "answer": answer,
        "correct": c["correct"].astype(float).where(c["parsed"].astype(bool), 0.0),
        "cost_usd": c["cost_usd"], "gpu_seconds": None, "input_tokens": tokens_in.astype(int),
        "output_tokens": c["output_tokens"], "latency_s": c["seconds"], "source": f"results/{run}/calls.csv",
        "licence": LICENCE,
    })
