"""The response table shared by the Atlas (session E5) and the open-weight testbed (session T1).

Plain words first. One row is one call: one system answering one item once. A "system" is everything that decides
how an answer is produced (model, reasoning setting, precision, scaffold); repeats of the same system on the same item
are told apart by `call`. Every source (our API panels, public leaderboards, the GPU testbed) is converted into this
one table, stored as Parquet, so that the factor model and every composition (votes, cascades, judges) read one format.

Columns (name: type, nullable?, meaning)
  benchmark      str,   no   benchmark or task family, e.g. "bbeh/boolean_expressions", "swebench_verified"
  item           str,   no   item id, unique within the benchmark
  system         str,   no   the configuration's name, unique within the benchmark (e.g. "haiku_nothink")
  family         str,   no   vendor or model family ("anthropic", "openai", "qwen3.5"); "unknown" if not known
  model          str,   no   model id as served (e.g. "claude-haiku-5-5", "Qwen/Qwen3.5-4B")
  size_b         float, yes  parameters in billions (open weights); missing for API models
  precision      str,   no   bits per weight: bf16, fp16, fp32, fp8, w8, w4, w3, w2, mxfp4; "api" for a closed
                             API model; "unknown"
  reasoning      str,   no   "off", "effort:<level>" (e.g. effort:low), "budget:<tokens>" (e.g. budget:4096), or
                             "unknown"
  scaffold       str,   no   how the model was driven: "direct" (one prompt, one answer), an agent scaffold name
                             ("mini-swe-agent"), a judge or checker role ("judge", "self_check")
  call           int,   no   repeat index of this system on this item, from 0
  answer         str,   yes  the parsed answer; missing when unparsed or not public
  correct        float, yes  1.0 right, 0.0 wrong (an unparsed answer is wrong); missing only while a run is blind
  cost_usd       float, yes  dollars billed for the call (0 for local GPU runs, which record gpu_seconds instead)
  gpu_seconds    float, yes  accelerator seconds spent on the call (local runs)
  input_tokens   int,   yes  prompt tokens
  output_tokens  int,   yes  generated tokens, thinking included
  latency_s      float, yes  wall-clock seconds for the call
  signal_*       float, yes  optional label-free signals, one column each: signal_logprob_mean, signal_entropy,
                             signal_steps, signal_self_check, signal_judge_pick, ...
  source         str,   no   where the row came from (a run name, a repository path, a dataset id)
  licence        str,   no   the licence the source's data is under ("internal" for our own runs)

Key: (benchmark, item, system, call) is unique.

Version 2 (session M1) adds optional, nullable timing and context columns. A table may carry any of them; none is
ever added to a table that lacks it, so a version-1 table validates and round-trips unchanged.
  context_tokens     int,   everything the model read: input + cache-write + cache-read tokens
  ttft_s             float, seconds to the first token of any kind, thinking included
  ttfat_s            float, seconds to the first visible answer token
  t_first_thinking_s float, seconds to the first thinking event
  decode_tok_s       float, output tokens / streaming window (providers/timing.py has the two bases)
  e2e_tok_s          float, output tokens / total seconds
  retries            int,   HTTP attempts after the first
  retry_s            float, seconds lost to retries
  concurrency        int,   calls in flight when this one was sent
  streamed           bool,  the reply was streamed (so the stamps above exist)
  timing_source      str,   "measured", "estimated" (inferred from totals), or missing (a cache hit)
  local GPU only (open-weight testbed):
  prefill_s          float, seconds from submit to the first token of each phase, summed over the call's phases
                            (queueing included; the server's queue time is in vllm_queue_s when the server reports it)
  decode_s           float, seconds from each phase's first to its last token, summed over the phases
  tpot_s             float, time per output token after the first: decode_s / (output tokens - phases)
  vllm_queue_s, vllm_prefill_s, vllm_decode_s  float, the server's own per-request timing (vLLM's
                            --enable-per-request-metrics), summed over the phases; missing when not reported
  kv_bytes_est       float, estimated KV-cache bytes of the call: (prompt + output tokens) x the model's KV bytes per
                            token (testbed/kv.py)
  energy_j           float, joules apportioned to the call from the shard's measured GPU energy by its share of
                            decode-token units (an apportionment, not a measurement)

Use: `coerce(frame)` casts a frame to these types; `problems(frame)` lists every violation (empty = valid);
`check(frame)` raises on the first list; `write(frame, path)` and `read(path)` validate on the way through.
"""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

SCHEMA_VERSION = 2

# name: (pandas dtype, nullable)
COLUMNS: dict[str, tuple[str, bool]] = {
    "benchmark": ("string", False),
    "item": ("string", False),
    "system": ("string", False),
    "family": ("string", False),
    "model": ("string", False),
    "size_b": ("Float64", True),
    "precision": ("string", False),
    "reasoning": ("string", False),
    "scaffold": ("string", False),
    "call": ("Int64", False),
    "answer": ("string", True),
    "correct": ("Float64", True),
    "cost_usd": ("Float64", True),
    "gpu_seconds": ("Float64", True),
    "input_tokens": ("Int64", True),
    "output_tokens": ("Int64", True),
    "latency_s": ("Float64", True),
    "source": ("string", False),
    "licence": ("string", False),
}
# version 2: optional columns (name: pandas dtype), cast when present and never added; numeric ones are non-negative
OPTIONAL: dict[str, str] = {
    "context_tokens": "Int64", "ttft_s": "Float64", "ttfat_s": "Float64", "t_first_thinking_s": "Float64",
    "decode_tok_s": "Float64", "e2e_tok_s": "Float64", "retries": "Int64", "retry_s": "Float64",
    "concurrency": "Int64", "streamed": "boolean", "timing_source": "string", "prefill_s": "Float64",
    "decode_s": "Float64", "tpot_s": "Float64", "vllm_queue_s": "Float64", "vllm_prefill_s": "Float64",
    "vllm_decode_s": "Float64", "kv_bytes_est": "Float64", "energy_j": "Float64",
}
TIMING_SOURCES = {"measured", "estimated"}
KEY = ["benchmark", "item", "system", "call"]
SIGNAL_PREFIX = "signal_"
PRECISIONS = {"bf16", "fp16", "fp32", "fp8", "w8", "w4", "w3", "w2", "mxfp4", "api", "unknown"}
REASONING_RE = re.compile(r"^(off|unknown|effort:[a-z_]+|budget:\d+)$")
NON_NEGATIVE = ["cost_usd", "gpu_seconds", "input_tokens", "output_tokens", "latency_s", "size_b",
                *[c for c, dtype in OPTIONAL.items() if dtype in ("Int64", "Float64")]]


def signal_columns(frame: pd.DataFrame) -> list[str]:
    return [c for c in frame.columns if c.startswith(SIGNAL_PREFIX)]


def empty() -> pd.DataFrame:
    """A table with every column and no rows."""
    return pd.DataFrame({name: pd.Series(dtype=dtype) for name, (dtype, _) in COLUMNS.items()})


def coerce(frame: pd.DataFrame) -> pd.DataFrame:
    """Cast known columns to their types and signal columns to float; missing nullable columns are added empty.
    Columns that are neither known nor signals are kept, so `problems` can report them."""
    out = frame.copy()
    for name, (dtype, nullable) in COLUMNS.items():
        if name not in out and nullable:
            out[name] = pd.Series(pd.NA, index=out.index, dtype=dtype)
        elif name in out:
            out[name] = out[name].astype(dtype)
    for name, dtype in OPTIONAL.items():
        if name in out:
            out[name] = out[name].astype(dtype)
    for name in signal_columns(out):
        out[name] = out[name].astype("Float64")
    return out


def problems(frame: pd.DataFrame) -> list[str]:
    """Every way the frame breaks the schema, in plain words; an empty list means valid."""
    found = []
    missing = [c for c, (_, nullable) in COLUMNS.items() if c not in frame and not nullable]
    if missing:
        return [f"missing required columns: {missing}"]
    unknown = [c for c in frame.columns if c not in COLUMNS and c not in OPTIONAL and not c.startswith(SIGNAL_PREFIX)]
    if unknown:
        found.append(f"unknown columns (not in the schema and not signal_*): {unknown}")
    try:
        frame = coerce(frame)
    except (TypeError, ValueError) as exc:
        return found + [f"a column cannot be cast to its type: {exc}"]
    for name, (_, nullable) in COLUMNS.items():
        if not nullable and frame[name].isna().any():
            found.append(f"{name}: {int(frame[name].isna().sum())} missing values in a required column")
    bad = ~frame["correct"].isna() & ~frame["correct"].isin([0.0, 1.0])
    if bad.any():
        found.append(f"correct: {int(bad.sum())} values other than 0, 1 or missing")
    if (frame["call"].dropna() < 0).any():
        found.append("call: negative repeat index")
    for name in NON_NEGATIVE:
        if name in frame and (frame[name].dropna() < 0).any():
            found.append(f"{name}: negative values")
    bad_precision = sorted(set(frame["precision"].dropna()) - PRECISIONS)
    if bad_precision:
        found.append(f"precision: values outside {sorted(PRECISIONS)}: {bad_precision}")
    bad_reasoning = sorted({r for r in frame["reasoning"].dropna() if not REASONING_RE.match(r)})
    if bad_reasoning:
        found.append(f"reasoning: values not of the form off / effort:<level> / budget:<tokens>: {bad_reasoning}")
    if "timing_source" in frame:
        bad_source = sorted(set(frame["timing_source"].dropna()) - TIMING_SOURCES)
        if bad_source:
            found.append(f"timing_source: values outside {sorted(TIMING_SOURCES)}: {bad_source}")
    dupes = frame.duplicated(KEY).sum()
    if dupes:
        found.append(f"key (benchmark, item, system, call): {int(dupes)} duplicated rows")
    return found


def check(frame: pd.DataFrame) -> pd.DataFrame:
    """The coerced frame if it is valid; otherwise ValueError listing every problem."""
    found = problems(frame)
    if found:
        raise ValueError("response table is invalid:\n- " + "\n- ".join(found))
    return coerce(frame)


def write(frame: pd.DataFrame, path: str | Path) -> Path:
    """Validate, then write Parquet (columns in schema order, then the version-2 columns present, signals last)."""
    frame = check(frame)
    order = list(COLUMNS) + [c for c in OPTIONAL if c in frame] + sorted(signal_columns(frame))
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    frame[order].to_parquet(path, index=False)
    return path


def read(path: str | Path) -> pd.DataFrame:
    """Read one Parquet file, or every *.parquet file under a directory (shards), and validate."""
    path = Path(path)
    files = sorted(path.rglob("*.parquet")) if path.is_dir() else [path]
    if not files:
        raise FileNotFoundError(f"no parquet files at {path}")
    return check(pd.concat([pd.read_parquet(f) for f in files], ignore_index=True))
