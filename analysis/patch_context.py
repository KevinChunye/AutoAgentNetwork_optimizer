"""Patch-based inference for agent networks: context and input dollars per stage from the pilot's real messages
(session M1, addendum 2, 8.3 and 8.4; $0; research/v4/measurement/patching.md has the theory).

Plain words first.
  message (L)      what one agent passes downstream: its reply. Its length is the reply's output tokens.
  base context (B) what every agent of a stage reads besides the upstream messages: system prompt, task and the
                   stage's instruction. Measured per call as context tokens minus the upstream messages it read.
  full             every agent reads all n upstream messages: context B + sum of L.
  fan-in f         agent i reads f messages, the circular window upstream_indices(i, n, f) (network/spec.py):
                   context B + the window's messages. Neighbouring windows overlap by f - 1 messages.
  compressed       every agent reads all n messages cut to the answer plus a short reason: context B + sum of cL.
                   Measured cut: each reply's last two paragraphs (its concluding statement and the ANSWER line, which
                   is how these replies end), their share of the reply's characters times the reply's tokens.
                   Placeholder cut: 80 tokens per message.
  peak context     per stage, the largest context of any agent (mean over tasks).
  input dollars    per stage, with prompt caching (w = cache-write price, r = cache-read price per token, m agents),
                   the stylized model of patching.md: full (B + nL)(w + (m-1)r); patched B(w + (m-1)r) + w x the
                   windows' tokens summed over agents (windows share no prefix, so each is written once and never
                   read); compressed (B + n cL)(w + (m-1)r). Haiku: w = $0.125, r = $0.01 per million tokens.
                   The executor itself (audit M1-1) sends a non-shared prefix uncached: under fan-in, only the
                   system prompt (S tokens) stays a cached shared prefix, and each agent pays the task and its
                   window at the input price p: S(w + (m-1)r) + p x sum over agents of (B - S + window). Column
                   input_usd_executor; full and compressed reading are the same in both models.
  output tokens and accuracy of a patched or compressed network need new calls: a communicating network's later
  stages read different inputs, so it cannot be replayed from the cache. Only context and input dollars are computed.

Data: the dense 6-6-6-1 runs of the pilot (p2_bbeh_dense, p3_bbeh_dense, p3_bbeh_dense_b and the dense config of the
P4 grid; Haiku with thinking off), replayed exactly from the call cache (the replay refuses any uncached call).
8.4 (agent loops): the market sessions' turns.csv (results/m*/turns.csv), each trader's context per turn.

Outputs: research/v4/measurement/tables/patch_context.csv, patch_messages.csv, loop_context.csv,
instruction_share.csv (8.5a: the shared-instruction share of the base context per task family) and the numbers
section of patching.md (between the markers <!-- numbers --> and <!-- /numbers -->).
"""

from __future__ import annotations

import asyncio
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from analysis.stage_balance import CacheOnly, md_table  # noqa: E402
from autoagentnet.cache import CallCache  # noqa: E402
from autoagentnet.experiment import ExperimentConfig, select_tasks  # noqa: E402
from autoagentnet.network.executor import NetworkExecutor  # noqa: E402
from autoagentnet.network.spec import NetworkSpec, upstream_indices  # noqa: E402
from autoagentnet.pricing import PriceBook  # noqa: E402
from autoagentnet.providers.registry import ProviderRegistry  # noqa: E402

OUT = ROOT / "research/v4/measurement"
RUNS = ["pilot/p2_bbeh_dense", "pilot/p3_bbeh_dense", "pilot/p3_bbeh_dense_b"] + \
       [f"pilot/p4_bbeh_grid_{x}" for x in "abcdefghijklmnop"]
W, R, P_IN = 0.125e-6, 0.01e-6, 0.10e-6  # Haiku 5.5 cache write, cache read and input, dollars per token (configs/pricing.yaml)
PLACEHOLDER = 80
RHO = 0.43  # the pilot's error correlation of Haiku proposers (reports/pilot/report.md, H6)


def conclusion_share(text: str, paragraphs: int = 2) -> float:
    """Characters of the reply's last `paragraphs` paragraphs (its conclusion and the ANSWER line) over the reply's
    characters."""
    parts = [p for p in re.split(r"\n\s*\n", text.strip()) if p.strip()]
    return sum(len(p) for p in parts[-paragraphs:]) / max(len(text.strip()), 1) if parts else 1.0


async def dense_runs(cache: CallCache) -> list:
    registry = ProviderRegistry.from_yaml(ROOT / "configs/providers.yaml")
    pricebook = PriceBook.from_yaml(ROOT / "configs/pricing.yaml")
    results, seen = [], set()
    for run in RUNS:
        cfg = ExperimentConfig.from_yaml(ROOT / f"configs/experiments/{run}.yaml")
        network = NetworkSpec.from_yaml(ROOT / cfg.network)
        executor = NetworkExecutor(network, CacheOnly(), registry, pricebook=pricebook, cache=cache,
                                   model_override=cfg.model_override, warm_cache_first=cfg.warm_cache_first,
                                   run_id="replay")
        for task in select_tasks(cfg.model_copy(update={"tasks": str(ROOT / cfg.tasks)})):
            if task.id in seen:
                continue
            seen.add(task.id)
            results.append(await executor.run(task))
    return results


def messages_table(results) -> pd.DataFrame:
    """One row per call: task, stage, agent index, context, output tokens (L), measured compressed length (cL)."""
    rows = []
    for res in results:
        for s, trace in enumerate(res.stages):
            for i, o in enumerate(trace.outputs):
                rows.append({"task_id": res.task_id, "stage_index": s, "stage": trace.stage, "agent": i,
                             "context": o.usage.prompt_tokens, "L": o.usage.output_tokens,
                             "cL": o.usage.output_tokens * conclusion_share(o.content)})
    return pd.DataFrame(rows)


def system_tokens() -> dict[int, float]:
    """Tokens of each stage's system prompt in the pilot network (estimate_tokens at 4 characters per token)."""
    from autoagentnet.providers.base import estimate_tokens

    network = NetworkSpec.from_yaml(ROOT / "configs/networks/dense_3x6.yaml")
    return {s: float(estimate_tokens(stage.system, 4.0)) for s, stage in enumerate(network.stages)}


def stage_variants(msgs: pd.DataFrame, system: dict[int, float] | None = None) -> pd.DataFrame:
    """Per task and reading stage: peak context, total input tokens and input dollars of each variant (stylized and
    as the executor would bill them)."""
    system = system if system is not None else system_tokens()
    rows = []
    for (task, s), part in msgs[msgs["stage_index"] > 0].groupby(["task_id", "stage_index"]):
        up = msgs[(msgs["task_id"] == task) & (msgs["stage_index"] == s - 1)].sort_values("agent")
        L, cL = up["L"].to_numpy(float), up["cL"].to_numpy(float)
        n, m = len(L), len(part)
        B = float(np.median(part["context"] - L.sum()))
        share = W + (m - 1) * R
        variants = {"full": [L.sum()] * m, "compressed (measured)": [cL.sum()] * m,
                    f"compressed ({PLACEHOLDER} tokens)": [PLACEHOLDER * n] * m}
        for f in (1, 2, 3):
            variants[f"fan-in {f}"] = [L[upstream_indices(i, n, f)].sum() for i in range(m)]
        for name, reads in variants.items():
            reads = np.asarray(reads, float)
            if name.startswith("fan-in"):
                usd = B * share + W * reads.sum()
                S = min(system.get(s, 0.0), B)
                executor = S * share + P_IN * ((B - S) * m + reads.sum())
            else:
                usd = executor = (B + reads[0]) * share
            rows.append({"task_id": task, "stage_index": s, "stage": part["stage"].iloc[0], "variant": name, "n": n,
                         "m": m, "B": B, "peak_context": B + reads.max(), "input_tokens": (B + reads).sum(),
                         "input_usd": usd, "input_usd_executor": executor})
    return pd.DataFrame(rows)


def summary(table: pd.DataFrame) -> pd.DataFrame:
    mean = table.groupby(["stage_index", "stage", "variant"]).agg(
        tasks=("task_id", "nunique"), B=("B", "mean"), peak_context=("peak_context", "mean"),
        input_tokens=("input_tokens", "mean"), input_usd=("input_usd", "mean"),
        input_usd_executor=("input_usd_executor", "mean")).reset_index()
    full = mean[mean["variant"] == "full"].set_index("stage_index")
    mean["peak_vs_full"] = mean["peak_context"] / mean["stage_index"].map(full["peak_context"]) - 1
    mean["usd_vs_full"] = mean["input_usd"] / mean["stage_index"].map(full["input_usd"]) - 1
    mean["executor_usd_vs_full"] = (mean["input_usd_executor"]
                                    / mean["stage_index"].map(full["input_usd_executor"]) - 1)
    order = {"full": 0, "fan-in 3": 1, "fan-in 2": 2, "fan-in 1": 3, "compressed (measured)": 4,
             f"compressed ({PLACEHOLDER} tokens)": 5}
    return mean.assign(o=mean["variant"].map(order)).sort_values(["stage_index", "o"]).drop(columns="o")


def n_eff(f: int, rho: float = RHO) -> float:
    """Independent proposals f messages are worth when their errors correlate at rho."""
    return f / (1 + (f - 1) * rho)


def loop_context(results_dir: Path = ROOT / "results") -> pd.DataFrame:
    """8.4: per market session and trader, context tokens by turn (each turn a step of the trader's loop)."""
    frames = []
    for path in sorted(results_dir.glob("m*/turns.csv")):
        t = pd.read_csv(path, usecols=lambda c: c in {"seed", "period", "round", "turn", "trader", "input_tokens",
                                                       "cache_write_tokens", "cache_read_tokens", "output_tokens"})
        t = t.assign(run=path.parent.name, context=t["input_tokens"] + t["cache_write_tokens"] + t["cache_read_tokens"])
        t["step"] = t.groupby(["run", "seed", "trader"]).cumcount()
        frames.append(t)
    if not frames:
        return pd.DataFrame()
    t = pd.concat(frames, ignore_index=True)
    return t.groupby(["run", "step"]).agg(calls=("context", "size"), context_mean=("context", "mean"),
                                          context_max=("context", "max")).reset_index()


FAMILIES = {"bbeh": "data/external/bbeh_all.jsonl", "math": "data/external/evidence/math.jsonl",
            "forecast": "data/external/evidence/forecast.jsonl", "code": "data/external/cd/code.jsonl"}


def instruction_share() -> pd.DataFrame:
    """8.5(a): per task family, the share of a single call's base context that is shared instructions (system prompt
    plus instruction, identical for every item) rather than the item itself, in characters (the same tokenizer reads
    both, so the character share is the token share up to tokenizer noise). Batching several items into one call
    amortises only this share. The pilot network's stages are listed too (their instructions per stage)."""
    from autoagentnet.evidence import prompts as P
    from autoagentnet.tasks import load_tasks

    rows = []
    for family, path in FAMILIES.items():
        if not (ROOT / path).exists():
            continue
        tasks = load_tasks(ROOT / path)
        system = P.CODE_SYSTEM if family == "code" else P.SYSTEMS[family]
        instruction = P.CODE_INSTRUCTION if family == "code" else P.INSTRUCTIONS[family]
        item = np.array([len(t.prompt) for t in tasks], float)
        shared = len(system) + len(instruction)
        rows.append({"family": family, "items": len(tasks), "shared_chars": shared, "item_chars_median": float(np.median(item)),
                     "instruction_share": float(np.median(shared / (shared + item)))})
    network = NetworkSpec.from_yaml(ROOT / "configs/networks/dense_3x6.yaml")
    bbeh = load_tasks(ROOT / FAMILIES["bbeh"]) if (ROOT / FAMILIES["bbeh"]).exists() else []
    item = float(np.median([len(t.prompt) for t in bbeh])) if bbeh else float("nan")
    for stage in network.stages:
        if stage.kind == "vote":
            continue
        shared = len(stage.system) + len(stage.instruction)
        rows.append({"family": f"pilot network: {stage.name} (task only, before upstream messages)", "items": len(bbeh),
                     "shared_chars": shared, "item_chars_median": item, "instruction_share": shared / (shared + item)})
    return pd.DataFrame(rows)


def numbers_md(s: pd.DataFrame, msgs: pd.DataFrame, loops: pd.DataFrame, shares: pd.DataFrame | None = None) -> str:
    tasks = msgs["task_id"].nunique()
    prop = msgs[msgs["stage_index"] == 0]
    lines = [f"Pilot dense runs replayed from the cache: {tasks} BBEH gate items, Haiku thinking off "
             "(`analysis/patch_context.py`; $0). Mean over tasks.", "",
             f"Messages: propose replies average {prop['L'].mean():.0f} output tokens; their last two paragraphs "
             f"(the measured answer-plus-reason cut: the concluding statement and the ANSWER line) {prop['cL'].mean():.0f} tokens (median "
             f"{prop['cL'].median():.0f}), i.e. c = {prop['cL'].sum() / prop['L'].sum():.2f}.", "",
             "Input $ is the note's stylized model (windows at the cache-write price); executor $ is what the executor "
             "would bill (a non-shared prefix is sent uncached at the input price; audit M1-1).", "",
             "| stage | variant | peak context | vs full | input tokens (stage) | input $ (stylized) | vs full | "
             "executor $ | vs full |", "|---|---|---|---|---|---|---|---|---|"]
    for r in s.itertuples():
        lines.append(f"| {r.stage} | {r.variant} | {r.peak_context:,.0f} | {r.peak_vs_full:+.0%} | "
                     f"{r.input_tokens:,.0f} | {r.input_usd:.6f} | {r.usd_vs_full:+.0%} | {r.input_usd_executor:.6f} | "
                     f"{r.executor_usd_vs_full:+.0%} |")
    lines += ["", f"Evidence kept (rho = {RHO}): " + ", ".join(f"f = {f}: n_eff {n_eff(f):.2f}" for f in (1, 2, 3, 6)) +
              f"; f = 2 keeps {n_eff(2) / n_eff(6):.0%} of all six's n_eff.", ""]
    if shares is not None and not shares.empty:
        lines += ["Batching (8.5a): share of a call's base context that is shared instructions (median over items):", "",
                  md_table(shares.round(3)), ""]
    if not loops.empty:
        lines += ["Agent loops (8.4): market traders' context by step (turns.csv; each turn shows the current book, "
                  "not the trader's history):", "", md_table(loops.groupby("run").agg(
                      steps=("step", "max"), first_context=("context_mean", "first"),
                      last_context=("context_mean", "last"), peak_context=("context_max", "max")).reset_index().round(0)), ""]
    return "\n".join(lines)


def main() -> None:
    cache = CallCache(ROOT / "state/cache")  # read only
    results = asyncio.run(dense_runs(cache))
    msgs = messages_table(results)
    table = stage_variants(msgs)
    s = summary(table)
    loops = loop_context()
    shares = instruction_share()
    (OUT / "tables").mkdir(parents=True, exist_ok=True)
    shares.to_csv(OUT / "tables/instruction_share.csv", index=False)
    s.to_csv(OUT / "tables/patch_context.csv", index=False)
    msgs.to_csv(OUT / "tables/patch_messages.csv", index=False)
    loops.to_csv(OUT / "tables/loop_context.csv", index=False)
    note = OUT / "patching.md"
    if note.exists():
        text = note.read_text()
        start, end = "<!-- numbers -->", "<!-- /numbers -->"
        if start in text and end in text:
            head, rest = text.split(start, 1)
            note.write_text(head + start + "\n" + numbers_md(s, msgs, loops, shares) + "\n" + end + rest.split(end, 1)[1])
    print(s.round(3).to_string())


if __name__ == "__main__":
    main()
