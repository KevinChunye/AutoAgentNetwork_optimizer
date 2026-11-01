"""Draw k samples per item per config through the executor and write the response table as Parquet shards.

Every generation goes through NetworkExecutor -> LocalRuntime -> the vllm_local provider, the same path an API model
takes, with a call cache on local disk (runs/testbed/cache, outside git: these calls cost GPU time, not dollars, and
the texts are too large to commit). A config is a one-stage network of width k whose agent j uses the model ref of
sample j, which carries sample j's seed (grid.registry_for).

Response table (one row per item, config and sample; E5's atlas schema, autoagentnet/atlas/schema.py; table.py lists
the testbed's conventions):
  benchmark, item      "bbeh/<task>", "math/<competition>" or "code/lcb_v6", and the item id
  system               the config label, e.g. "qwen3.5-4b:w4:budget:1024"
  family, model, size_b, precision   the checkpoint (model = the Hugging Face repo of the source weights)
  reasoning            "off", "budget:<tokens>" or "effort:<level>"
  scaffold             "direct": one sample, no aggregation (compositions are replayed later)
  call                 the sample index j (0..k-1)
  answer, correct      the extracted answer (code: the program's behaviour class; missing when unparsed) and
                       1.0 / 0.0 (unparsed = 0)
  cost_usd             0 (GPU time is metered in gpu_seconds and the GPU ledger)
  gpu_seconds          measured: the shard's wall-clock x the number of GPUs, shared out over its calls in proportion
                       to their tokens (output + 0.1 x input: prefill costs about a tenth of decoding per token). A
                       shard holds one config, so a config's total is measured exactly. Missing when any call of the
                       shard came from the cache. Used to measure throughput; the analyses compare costs in tokens
                       (compose.cost_tokens) or real-kernel seconds (analysis.kernel_seconds), since fake-quantized
                       checkpoints run at BF16 speed.
  input_tokens, output_tokens, latency_s
  signal_*             white-box signals (logprob_mean, entropy, margin), thinking_tokens, forced (budget forcing
                       fired), truncated (the answer phase hit its cap), exec_visible (code: passes every public test)
  source, licence      provenance
Sidecar (*.texts.parquet, not in the schema): seed, stop_reason, text (the answer phase's reply).

Session M1 (schema version 2, optional columns; definitions in providers/vllm_local.py, testbed/kv.py and
testbed/sidecar.py): per live call ttft_s, ttfat_s, t_first_thinking_s, prefill_s, decode_s, tpot_s, decode_tok_s,
e2e_tok_s, streamed, vllm_queue_s, vllm_prefill_s, vllm_decode_s, context_tokens, timing_source ("measured"; missing
with every timing column for a cache hit), kv_bytes_est (prompt + output tokens x the checkpoint's KV bytes per token,
when its config.json is known) and energy_j (the shard's measured GPU energy apportioned by decode-token units, when
the GPU trace ran). The trace itself goes to <shard>.gpu_trace.parquet (sidecar.py).
"""

from __future__ import annotations

import asyncio
import os
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pandas as pd

from ..cache import CallCache
from ..network.executor import NetworkExecutor
from ..network.spec import NetworkSpec, StageSpec
from ..pricing import PriceBook
from ..providers.registry import ProviderRegistry
from ..runtime.local import LocalRuntime
from ..tasks import Task, extract_answer, is_correct
from . import checkers
from .grid import Config, load_models, sampling_options
from .sidecar import Sidecar, apportion_energy, energy_joules
from .table import validate

SYSTEM = "You are a careful expert problem solver."
INSTRUCTION = "Solve the task. End your reply with one final line of the form\nANSWER: <your final answer>"
CODE_INSTRUCTION = ("Solve the programming task in Python 3. Put the complete program in one ```python code block "
                    "(read standard input and write standard output, or define the requested function). After the "
                    "code block, end with the line\nANSWER: see code")
PREFILL_WEIGHT = 0.1
GRADING_THREADS = max(4, (os.cpu_count() or 4) - 2)


def network(config: Config, k: int, code: bool = False, models: dict | None = None,
            name: str | None = None, instruction: str | None = None, refs: list[str] | None = None) -> NetworkSpec:
    temperature, options = sampling_options(config, models)
    refs = refs or [config.ref(j) for j in range(k)]
    return NetworkSpec(
        name=name or f"tb-{config.label}", default_model=refs[0], default_temperature=temperature,
        default_max_tokens=int(options["answer_max_tokens"]),
        stages=[StageSpec(name="answer", width=len(refs), system=SYSTEM, agent_models=refs,
                          instruction=instruction or (CODE_INSTRUCTION if code else INSTRUCTION))])


def executor(net: NetworkSpec, registry: ProviderRegistry, cache: CallCache | None, concurrency: int) -> NetworkExecutor:
    """No governor: vllm_local calls are free (FREE_PROVIDERS) and stay out of the spend ledger."""
    return NetworkExecutor(net, LocalRuntime(registry), registry, pricebook=PriceBook({}), cache=cache,
                           max_concurrency=concurrency, warm_cache_first=False, run_id=net.name)


def is_code(task: Task) -> bool:
    return task.meta.get("benchmark") == "code" or task.meta.get("kind") == "code"


def benchmark_of(task: Task) -> str:
    """The schema's benchmark field: "bbeh/<task>", "math/<competition>", "code/lcb_v6" ("<b>/synthetic" in tests)."""
    bench = task.meta.get("benchmark", "bbeh")
    sub = task.meta.get("subtask") or task.meta.get("competition") or ("lcb_v6" if bench == "code" else "synthetic")
    return f"{bench}/{sub}"


def model_of(config: Config, models: dict | None = None) -> str:
    """The Hugging Face repo the weights come from (the checkpoint name when the family is not in models.yaml)."""
    try:
        family = (models or load_models())[config.family]
    except (KeyError, FileNotFoundError):
        return config.checkpoint
    size = int(config.size_b) if float(config.size_b).is_integer() else config.size_b
    if config.precision == "bf16" and "bf16_repo" in family:
        return family["bf16_repo"]
    return family["repos"].get(size, config.checkpoint)


def grade(task: Task, text: str, sandbox: dict | None = None, defer_code: bool = False) -> dict:
    """answer (None when unparsed), correct (1.0 / 0.0) and, for code, signal_exec_visible of one reply. With
    defer_code a program is left ungraded (all three missing) for grade_shards to run later, off the GPU clock."""
    if is_code(task) and defer_code:
        return {"answer": None, "correct": None, "signal_exec_visible": None}
    if is_code(task):
        code = checkers.extract_code(text)
        public, private = task.meta.get("public_tests", []), task.meta.get("private_tests", [])
        fn = task.meta.get("fn_name")
        hidden = checkers.run_tests(code, private, fn, stop_on_fail=True, **(sandbox or {}))
        visible = checkers.run_tests(code, public, fn, **(sandbox or {}))
        return {"answer": None if code is None else checkers.behaviour(code, public, fn, **(sandbox or {})),
                "correct": float(bool(hidden) and all(hidden)),
                "signal_exec_visible": float(bool(visible) and all(visible))}
    answer = extract_answer(text)
    return {"answer": answer, "correct": float(bool(is_correct(text, task.answer, task.grader))),
            "signal_exec_visible": None}


SIDECAR = ["seed", "stop_reason", "text"]  # per-call metadata outside the schema (*.texts.parquet)
NOT_SHARDS = (".texts.parquet", ".gpu_trace.parquet")  # files next to the shards that are not response tables
TIMING = ["ttft_s", "ttfat_s", "t_first_thinking_s", "prefill_s", "decode_s", "tpot_s", "decode_tok_s", "e2e_tok_s",
          "streamed", "vllm_queue_s", "vllm_prefill_s", "vllm_decode_s"]


def is_shard(path: Path) -> bool:
    return not path.name.endswith(NOT_SHARDS) and path.parent.name != "checks"


def timing_of(o) -> dict:
    """The schema's timing columns of one output; all missing (with timing_source) for a cache hit."""
    x = o.extra or {}
    if o.from_cache:
        return {**{c: None for c in TIMING}, "timing_source": None}
    return {**{c: x.get(c) for c in TIMING}, "timing_source": "measured"}


def rows_of(config: Config, task: Task, outputs: list, source: str, model: str, defer_code: bool = False,
            kv_per_token: int | None = None) -> list[dict]:
    rows = []
    for j, o in enumerate(outputs):
        x = o.extra or {}
        rows.append({
            "benchmark": benchmark_of(task), "item": task.id, "system": config.label, "family": config.family,
            "model": model, "size_b": config.size_b, "precision": config.schema_precision,
            "reasoning": config.reasoning, "scaffold": "direct", "call": j, **grade(task, o.content, defer_code=defer_code),
            "cost_usd": 0.0, "gpu_seconds": 0.0, "input_tokens": o.usage.prompt_tokens,
            "output_tokens": o.usage.output_tokens, "latency_s": o.latency_s,
            "signal_logprob_mean": x.get("signal_logprob_mean"), "signal_entropy": x.get("signal_entropy"),
            "signal_margin": x.get("signal_margin"), "signal_thinking_tokens": x.get("thinking_tokens"),
            "signal_forced": float(bool(x.get("forced"))), "signal_truncated": float(o.stop_reason == "length"),
            "source": source, "licence": "internal", **timing_of(o), "context_tokens": o.usage.prompt_tokens,
            "kv_bytes_est": None if kv_per_token is None else (o.usage.prompt_tokens + o.usage.output_tokens) * kv_per_token,
            "seed": x.get("seed"), "stop_reason": o.stop_reason, "text": o.content})
    return rows


def share_gpu_seconds(frame: pd.DataFrame, wall_s: float, gpus: int) -> pd.Series:
    weight = frame["output_tokens"] + PREFILL_WEIGHT * frame["input_tokens"]
    return wall_s * gpus * weight / max(float(weight.sum()), 1.0)


async def sample_config(config: Config, tasks: list[Task], k: int, registry: ProviderRegistry,
                        cache: CallCache | None = None, concurrency: int = 256, gpus: int = 1,
                        source: str = "testbed", models: dict | None = None, defer_code: bool = False,
                        sidecar: Sidecar | None = None, kv_per_token: int | None = None) -> pd.DataFrame:
    """k samples of one config on `tasks`; one shard's rows, with the SIDECAR columns (seed, stop_reason, text).
    With a sidecar, the GPU trace runs while the shard samples and each call gets its apportioned energy_j."""
    nets = {code: network(config, k, code, models) for code in (False, True)}
    execs = {code: executor(net, registry, cache, concurrency) for code, net in nets.items()}
    start = time.perf_counter()
    if sidecar is not None:
        async with sidecar:
            results = await asyncio.gather(*(execs[is_code(t)].run(t) for t in tasks))
    else:
        results = await asyncio.gather(*(execs[is_code(t)].run(t) for t in tasks))
    wall_s = time.perf_counter() - start
    model = model_of(config, models)
    with ThreadPoolExecutor(max_workers=GRADING_THREADS) as pool:  # code grading runs programs: in parallel
        per_task = list(pool.map(lambda tr: rows_of(config, tr[0], tr[1].stages[0].outputs, source, model, defer_code,
                                                     kv_per_token), zip(tasks, results)))
    rows = [r for part in per_task for r in part]
    frame = pd.DataFrame(rows)
    cached = any(o.from_cache for res in results for o in res.stages[0].outputs)
    # a shard with any cached call has a wall-clock that is not its calls' GPU time: leave gpu_seconds missing
    frame["gpu_seconds"] = None if cached else share_gpu_seconds(frame, wall_s, gpus)
    energy = energy_joules(sidecar.frame()) if sidecar is not None else None
    frame["energy_j"] = None if cached else apportion_energy(frame["output_tokens"] + PREFILL_WEIGHT * frame["input_tokens"], energy)
    return frame


def shard_path(out_dir: Path, config: Config, offset: int) -> Path:
    return Path(out_dir) / config.label / f"{offset:05d}.parquet"


async def run_shards(config: Config, tasks: list[Task], k: int, registry: ProviderRegistry, out_dir: Path,
                     cache: CallCache | None = None, chunk: int = 100, trace=None, **kw) -> list[Path]:
    """Sample a config chunk by chunk; a chunk whose shard exists is skipped (resume after a crash or a stop).
    Each shard is the response table (answers, no texts); the texts go to a sibling *.texts.parquet.
    trace: a function returning a fresh Sidecar per shard (None: no GPU trace); its rows go to *.gpu_trace.parquet."""
    written = []
    for offset in range(0, len(tasks), chunk):
        path = shard_path(out_dir, config, offset)
        if path.exists():
            written.append(path)
            continue
        sidecar = trace() if trace is not None else None
        frame = await sample_config(config, tasks[offset: offset + chunk], k, registry, cache, sidecar=sidecar, **kw)
        path.parent.mkdir(parents=True, exist_ok=True)
        if sidecar is not None:
            sidecar.frame().to_parquet(path.with_name(path.name.replace(".parquet", ".gpu_trace.parquet")), index=False)
        frame[["item", "system", "call", *SIDECAR]].to_parquet(path.with_suffix(".texts.parquet"), index=False)
        validate(frame.drop(columns=SIDECAR)).to_parquet(path, index=False)
        written.append(path)
    return written


def grade_shards(out_dir: Path, tasks: list[Task]) -> int:
    """Grade every deferred code row under out_dir (correct missing) from its sidecar text, in parallel, and rewrite
    the shards. Run on a CPU machine after sampling (RUN_GPU.md); returns the number of rows graded."""
    by_id = {t.id: t for t in tasks}
    graded = 0
    for path in sorted(p for p in Path(out_dir).rglob("*.parquet") if is_shard(p)):
        frame = pd.read_parquet(path)
        todo = frame["benchmark"].astype(str).str.startswith("code") & frame["correct"].isna()
        if not todo.any():
            continue
        texts = pd.read_parquet(path.with_suffix(".texts.parquet"))[["item", "system", "call", "text"]]
        rows = frame[todo].merge(texts, on=["item", "system", "call"], how="left")
        with ThreadPoolExecutor(max_workers=GRADING_THREADS) as pool:
            results = list(pool.map(lambda r: grade(by_id[r[0]], str(r[1] or "")), zip(rows["item"], rows["text"])))
        for col in ("answer", "correct", "signal_exec_visible"):
            frame[col] = frame[col].astype(object)
            frame.loc[todo, col] = [r[col] for r in results]
        validate(frame).to_parquet(path, index=False)
        graded += len(results)
    return graded


def read_table(out_dir: Path) -> pd.DataFrame:
    """Every response-table shard under out_dir (texts excluded)."""
    paths = sorted(p for p in Path(out_dir).rglob("*.parquet") if is_shard(p))
    return validate(pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True)) if paths else pd.DataFrame()


def read_traces(out_dir: Path) -> pd.DataFrame:
    """Every GPU trace under out_dir, with its shard's system (the config label) and offset."""
    paths = sorted(Path(out_dir).rglob("*.gpu_trace.parquet"))
    frames = [pd.read_parquet(p).assign(system=p.parent.name, shard=p.name.split(".")[0]) for p in paths]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def read_texts(out_dir: Path) -> pd.DataFrame:
    paths = sorted(Path(out_dir).rglob("*.texts.parquet"))
    return pd.concat([pd.read_parquet(p) for p in paths], ignore_index=True) if paths else pd.DataFrame()


# ------------------------------------------------------------------------------------------------------------
# model checkers, through the same executor

def shown_answer(benchmark: str, answer) -> str:
    """The answer a checker is shown: the extracted answer, or "see code" for a program (its behaviour hash means
    nothing to a reader); "(none)" when unparsed."""
    if str(benchmark).startswith("code"):
        return "see code"
    return "(none)" if answer is None or pd.isna(answer) else str(answer)


async def self_checks(config: Config, tasks: list[Task], table: pd.DataFrame, texts: pd.DataFrame,
                      registry: ProviderRegistry, cache: CallCache | None = None, concurrency: int = 256,
                      models: dict | None = None) -> pd.DataFrame:
    """The config re-reads samples 0..2 of its own answers: rows system, item, call, verdict (1 yes, 0 no, None
    unparsed). Sample j's check uses sample j's ref (its seed) on a new prompt."""
    t = table[(table["system"] == config.label) & table["call"].isin(checkers.SELF_CHECK_SAMPLES)]
    t = t.merge(texts, on=["item", "system", "call"], how="left")
    by_id = {task.id: task for task in tasks}
    execs = {j: executor(network(config, 1, models=models, name=f"tb-selfcheck-{config.label}-s{j}",
                                 instruction=checkers.SELF_CHECK_INSTRUCTION, refs=[config.ref(j)]),
                         registry, cache, concurrency) for j in checkers.SELF_CHECK_SAMPLES}
    jobs = []
    for row in t.itertuples():
        prompt = checkers.self_check_prompt(by_id[row.item].prompt, shown_answer(row.benchmark, row.answer),
                                            str(row.text or ""))
        jobs.append((row, execs[row.call], Task(id=f"{row.item}|selfcheck|{row.call}", prompt=prompt)))
    results = await asyncio.gather(*(ex.run(task) for _, ex, task in jobs))
    return pd.DataFrame([{"system": row.system, "item": row.item, "call": row.call,
                          "verdict": checkers.parse_verdict(res.stages[0].outputs[0].content)}
                         for (row, _, _), res in zip(jobs, results)])


async def judge(judge_config: Config, systems: list[str], tasks: list[Task], table: pd.DataFrame, texts: pd.DataFrame,
                registry: ProviderRegistry, cache: CallCache | None = None, concurrency: int = 256,
                models: dict | None = None, n: int = checkers.JUDGE_CANDIDATES) -> pd.DataFrame:
    """The judge reads the first n samples of each (system, item) and picks one: rows system, item, judge,
    candidates (= n), pick (0-based call, None if unparsed). T2 also asks it with n = 2 on the W8 configs."""
    t = table[table["system"].isin(systems) & (table["call"] < n)].merge(texts, on=["item", "system", "call"], how="left")
    by_id = {task.id: task for task in tasks}
    net = network(judge_config, 1, models=models, name=f"tb-judge-{judge_config.label}",
                  instruction=checkers.JUDGE_INSTRUCTION, refs=[judge_config.ref(0)])
    ex = executor(net, registry, cache, concurrency)
    jobs = []
    for (system, item), part in t.sort_values("call").groupby(["system", "item"]):
        candidates = [(shown_answer(b, a), str(x or "")) for b, a, x in zip(part["benchmark"], part["answer"], part["text"])]
        jobs.append((system, item, len(candidates),
                     Task(id=f"{item}|judge|{system}", prompt=checkers.judge_prompt(by_id[item].prompt, candidates))))
    results = await asyncio.gather(*(ex.run(task) for *_, task in jobs))
    return pd.DataFrame([{"system": s, "item": i, "judge": judge_config.label, "candidates": n,
                          "pick": checkers.parse_choice(res.stages[0].outputs[0].content, m)}
                         for (s, i, m, _), res in zip(jobs, results)])
