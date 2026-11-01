"""The testbed's configs: which checkpoint, which thinking budget, which sampling seed.

Terms (plain words first):
  family     a series of models trained together (Qwen3.5 small dense; gpt-oss in stage 2).
  size_b     parameters, in billions.
  precision  bits per weight: "bf16" (16, the reference), "w8" (8-bit round-to-nearest, per output channel),
             "w4" (4-bit AWQ, group 128), "w3" (3-bit GPTQ, group 128), "w4gptq" (4-bit GPTQ, group 128; the method
             contrast of stage 2). Accuracy runs use fake quantization: the weights are quantized, then stored again
             in BF16, so every precision runs on the same vLLM code path and only the weights differ.
  budget     the most thinking tokens per call (0 = thinking off); see budget_forcing.py. For gpt-oss the budget is
             its reasoning effort ("low", "medium", "high") and `effort` holds it.
  checkpoint one set of weights = (family, size, precision); one vLLM server serves one checkpoint.
  config     a checkpoint plus a budget: the unit every sample, vote and checker is defined on.
  sample j   the j-th of k independent samples of a config on an item (temperature > 0), with its own seed. Seeds
             differ across configs too, so no two calls share random numbers (shared seeds would make a W4 and a
             BF16 sample of the same item look more alike than independent samples are).
  weight memory  size_b x bits / 8 GB: 4 copies of W4, 2 of W8 and 1 of BF16 hold the same memory (T2).
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path

import yaml

from ..providers.registry import ModelConfig, ProviderRegistry

BITS = {"bf16": 16, "w8": 8, "w4": 4, "w4gptq": 4, "w4rtn": 4, "w3": 3, "mxfp4": 4}
MODELS_YAML = Path(__file__).resolve().parents[2] / "configs/testbed/models.yaml"


@dataclass(frozen=True)
class Config:
    family: str
    size_b: float
    precision: str
    budget: int = 0
    effort: str | None = None  # reasoning effort, for families that take one instead of a token budget

    @property
    def checkpoint(self) -> str:
        """The served model name, e.g. "qwen3.5-4b-w4"."""
        return f"{self.family}-{self.size_b:g}b-{self.precision}"

    @property
    def reasoning(self) -> str:
        """The atlas schema's reasoning field: "off", "budget:<tokens>" or "effort:<level>"."""
        if self.effort:
            return f"effort:{self.effort}"
        return f"budget:{self.budget}" if self.budget else "off"

    @property
    def label(self) -> str:
        """The config's name in every table (the atlas `system`), e.g. "qwen3.5-4b:w4:budget:1024"."""
        return f"{self.family}-{self.size_b:g}b:{self.precision}:{self.reasoning}"

    @property
    def schema_precision(self) -> str:
        """The atlas schema's precision field: bits only, so W4 GPTQ is "w4" (the method shows in `system`)."""
        return {"w4gptq": "w4", "w4rtn": "w4"}.get(self.precision, self.precision)

    @classmethod
    def from_label(cls, label: str) -> "Config":
        name, precision, reasoning = label.split(":", 2)
        family, size = name.rsplit("-", 1)
        kind, _, value = reasoning.partition(":")
        return cls(family, float(size.removesuffix("b")), precision, int(value) if kind == "budget" else 0,
                   value if kind == "effort" else None)

    @property
    def bits(self) -> int:
        return BITS[self.precision]

    @property
    def weight_gb(self) -> float:
        return self.size_b * self.bits / 8

    def ref(self, sample: int) -> str:
        """Model ref of sample j: one ref per sample so each carries its own seed in request_options."""
        return f"{self.label}:s{sample}"


def seed_of(label: str, sample: int, salt: str = "") -> int:
    """A sampling seed that differs across configs and samples, reproducible from the names alone. `salt` gives a
    stage its own seeds (the pilot uses "pilot", so stage 1 draws fresh samples on the pilot's items)."""
    key = f"{salt}|{label}|{sample}" if salt else f"{label}|{sample}"
    return int(hashlib.sha256(key.encode()).hexdigest()[:8], 16) & 0x7FFFFFFF


def load_models(path: Path = MODELS_YAML) -> dict:
    """configs/testbed/models.yaml: per family, the Hugging Face repo per size, the pinned revision, sampling
    parameters from the model card and the thinking markers."""
    return yaml.safe_load(Path(path).read_text())["families"]


def sampling_options(config: Config, models: dict | None = None) -> tuple[float | None, dict]:
    """(temperature, request_options) for a config, from the model card values in models.yaml: the thinking-mode
    values when the budget is above 0, the non-thinking ones when it is off."""
    family = (models or load_models())[config.family]
    mode = "thinking" if (config.budget > 0 or config.effort) else "non_thinking"
    params = dict(family["sampling"][mode])
    temperature = params.pop("temperature", None)
    options = {**params, "thinking_budget": config.budget, "answer_max_tokens": family.get("answer_max_tokens", 1024),
               "think_start": family.get("think_start", "<think>"), "think_end": family.get("think_end", "</think>"),
               "logprobs": family.get("logprobs", 5)}
    if config.effort:
        options["chat_template_kwargs"] = {"reasoning_effort": config.effort}
        options["thinking_budget"] = 0  # gpt-oss thinks inside one completion; its effort sets the depth
    return temperature, options


SEED_SALT = {"pilot": "pilot", "smoke": "smoke", "scan": "scan"}  # stages whose samples must not be reused later


def registry_for(configs: list[Config], k: int, base_url: str, models: dict | None = None,
                 seed_salt: str = "") -> ProviderRegistry:
    """One model ref per (config, sample), all served at base_url (one checkpoint at a time on the GPU node), each
    with its own seed."""
    refs = {}
    for config in configs:
        _, options = sampling_options(config, models)
        for j in range(k):
            refs[config.ref(j)] = ModelConfig(provider="vllm_local", model=config.checkpoint, base_url=base_url,
                                              request_options={**options, "seed": seed_of(config.label, j, seed_salt)})
    return ProviderRegistry(refs)


# ------------------------------------------------------------------------------------------------------------
# stages

QWEN = "qwen3.5"
SIZES = (2, 4, 9)
PRECISIONS = ("bf16", "w8", "w4", "w3")
BUDGETS = (0, 1024, 4096)


def pilot() -> list[Config]:
    """4B, BF16 and W4, thinking off and 1k (50 items, k = 6)."""
    return [Config(QWEN, 4, p, b) for p in ("bf16", "w4") for b in (0, 1024)]


SCOPE_YAML = Path(__file__).resolve().parents[2] / "configs/testbed/scope.yaml"


def scope(path: Path | None = None) -> dict:
    """The stage-1 scope: precisions dropped by the pre-registered drop rule, and whether the kernel run happens."""
    path = Path(path or SCOPE_YAML)
    raw = yaml.safe_load(path.read_text()) if path.exists() else {}
    return {"drop_precisions": list(raw.get("drop_precisions") or []), "kernel_run": bool(raw.get("kernel_run", True))}


def stage1(drop_precisions: tuple | list | None = None) -> list[Config]:
    """3 sizes x 4 precisions x 3 budgets = 36 configs, minus any precision the scope drops."""
    drop = scope()["drop_precisions"] if drop_precisions is None else list(drop_precisions)
    return [Config(QWEN, s, p, b) for s in SIZES for p in PRECISIONS for b in BUDGETS if p not in drop]


def stage2() -> list[Config]:
    """gpt-oss-20b at three reasoning efforts (BF16 upcast reference and its native MXFP4), the W4 GPTQ contrast on
    the 9B, and a 16k budget for math on the 9B (BF16 and W4; math items only, see tasks.py)."""
    oss = [Config("gpt-oss", 20, p, 0, e) for p in ("bf16", "mxfp4") for e in ("low", "medium", "high")]
    gptq = [Config(QWEN, 9, "w4gptq", b) for b in BUDGETS]
    deep = [Config(QWEN, 9, p, 16384) for p in ("bf16", "w4")]
    return oss + gptq + deep


def scan() -> list[Config]:
    """The pilot's math scan: 4B BF16 at a 4k budget on 30 math items (is math in the 20-80% band?)."""
    return [Config(QWEN, 4, "bf16", 4096)]


STAGES = {"smoke": pilot, "pilot": pilot, "scan": scan, "stage1": stage1, "stage2": stage2}


def checkpoints(configs: list[Config]) -> list[Config]:
    """One config per distinct checkpoint (budget 0), in first-seen order: what the GPU node serves in turn."""
    seen, out = set(), []
    for c in configs:
        if c.checkpoint not in seen:
            seen.add(c.checkpoint)
            out.append(replace(c, budget=0, effort=None))
    return out


# ------------------------------------------------------------------------------------------------------------
# GPU-hour estimate (a prior; the pilot replaces the throughputs and fill rates with measured ones)

# Output tokens per second on one H100 with vLLM at high concurrency, BF16 weights (fake-quantized checkpoints run
# at BF16 speed). Rough priors from public vLLM benchmarks of similar sizes, not measured on Qwen3.5's hybrid layers;
# the pilot measures the 4B and the runbook rescales the rest. Rate: Lightning's H100 was $5.45/h on 2026-10-26
# (research/lit/ow_testbed_sources.md); the runbook records the live rate of the machine actually used.
TOKENS_PER_S = {2: 25_000, 4: 15_000, 9: 8_000, 20: 10_000}
ANSWER_TOKENS = 400  # visible answer, on average
PREFILL_EQUIV = 150  # 0.1 x a ~1,500-token prompt: prefill in decode-token units (compose.cost_tokens)
FILL = {0: 0.0, 1024: 0.85, 4096: 0.6, 16384: 0.4}  # share of the thinking budget used, on average
EFFORT_TOKENS = {"low": 600, "medium": 2000, "high": 5000}


def tokens_per_call(config: Config, measured_tokens: dict | None = None) -> float:
    """Cost per call in decode-token units (output + 0.1 x input, compose.cost_tokens): the pilot's measured mean for
    the budget when known (throughput.json), else the prior PREFILL_EQUIV + ANSWER_TOKENS + FILL x budget."""
    if measured_tokens and str(config.effort or config.budget) in measured_tokens:
        return float(measured_tokens[str(config.effort or config.budget)])
    if config.effort:
        return PREFILL_EQUIV + ANSWER_TOKENS + EFFORT_TOKENS[config.effort]
    return PREFILL_EQUIV + ANSWER_TOKENS + FILL.get(config.budget, 0.5) * config.budget


def generation_hours(configs: list[Config], items: int, k: int, tokens_per_s: dict | None = None,
                     overhead: float = 1.0, measured_tokens: dict | None = None) -> float:
    """GPU-hours to draw k samples of every config on `items` items: output tokens / throughput, times overhead."""
    rate = tokens_per_s or TOKENS_PER_S
    seconds = sum(items * k * tokens_per_call(c, measured_tokens) / rate[int(c.size_b)] for c in configs)
    return seconds * overhead / 3600


# Lightning machines on 2026-10-26 (research/lit/ow_testbed_sources.md): $/h and decode speed relative to an H100.
# Priors, deliberately conservative after audit T1-1: with ~256 requests in flight decoding is closer to
# compute-bound than bandwidth-bound, so the A100 is put at 0.32 of an H100 (not its 0.6 bandwidth ratio) and the
# H200, which has the H100's compute, at 1.1 (not its 1.43 bandwidth ratio). The pilot measures the real figure.
MACHINES = {"H100": (5.45, 1.0), "H200": (4.50, 1.1), "A100-80GB": (1.85, 0.32)}
ENV_SETUP_H = 0.3  # boot, model and data download per stage session (installs run on a CPU machine, step 1)
MIN_OVERHEAD = 1.5  # idle time, restarts and server start-ups on top of pure generation
STEP_FLOOR_H = 0.25  # no sampling step is guarded or timed out below 15 minutes (pilot throughput is unmeasured)


def quantize_hours(config: Config) -> float:
    """Calibration time prior: RTN takes minutes; AWQ / GPTQ about 0.04 h per billion parameters on one GPU."""
    if config.precision in ("bf16", "mxfp4"):
        return 0.0
    return 0.05 if config.precision == "w8" else 0.04 * config.size_b + 0.03


THROUGHPUT_JSON = Path(__file__).resolve().parents[2] / "research/v4/testbed/throughput.json"


def measured(path: Path | None = None) -> dict:
    """What the pilot measured (pilot-report writes it): scale (measured / prior throughput on the machine used),
    tokens_per_call by budget, overhead (ledger hours / estimated pure hours of the pilot) and the machine. Empty
    before the pilot."""
    import json

    path = Path(path or THROUGHPUT_JSON)
    return json.loads(path.read_text()) if path.exists() else {}


def measured_scale(path: Path | None = None) -> float:
    return float(measured(path).get("scale", 1.0))


def default_machine() -> str:
    """The machine the GPU clock was started on (gpu_ledger), else the pilot's, else H100."""
    from .gpu_ledger import CLOCK

    if CLOCK.exists():
        import json

        gpu = json.loads(CLOCK.read_text()).get("gpu_type", "")
        if gpu in MACHINES:
            return gpu
    return measured().get("machine", "H100")


def _speeds(machine: str | None, scale: float | None) -> tuple[str, dict]:
    machine = machine or default_machine()
    factor = MACHINES[machine][1] * (measured_scale() if scale is None else scale)
    return machine, {sz: r * factor for sz, r in TOKENS_PER_S.items()}


def stage_estimate(stage: str, items: int, k: int = 6, tokens_per_s: dict | None = None, overhead: float | None = None,
                   rate_usd: float | None = None, machine: str | None = None, drop_precisions=None,
                   kernel_run: bool | None = None, scale: float | None = None) -> dict:
    """Hours and dollars of a stage: generation, self-check (3 of k samples re-read by the same config, about half a
    generation's tokens each), the cross-model judge (one 9B BF16 call at 4k per item and config, plus one per W8
    config with 2 candidates), quantization (quantize_hours), server start-up (0.05 h per checkpoint), the real-kernel
    run (0.1 h per size, stage 1, if the scope keeps it) and set-up, all times the overhead: max(1.5, the pilot's
    measured overhead). Throughput: tokens_per_s (H100 figures) x the machine's speed x the pilot's measured scale;
    tokens per call: the pilot's measurement when known."""
    m = measured()
    machine, tps = _speeds(machine, scale)
    if tokens_per_s is not None:
        tps = {s: r * MACHINES[machine][1] for s, r in tokens_per_s.items()}
    overhead = max(MIN_OVERHEAD, float(m.get("overhead", 0.0))) if overhead is None else overhead
    rate_usd = MACHINES[machine][0] if rate_usd is None else rate_usd
    tokens = m.get("tokens_per_call")
    configs = stage1(drop_precisions) if stage == "stage1" else STAGES[stage]()
    kernel_run = scope()["kernel_run"] if kernel_run is None else kernel_run
    gen = generation_hours(configs, items, k, tps, 1.0, tokens)
    self_check = 0.0 if stage == "pilot" else generation_hours(configs, items, 3, tps, 1.0, tokens) * 0.5
    judge_cfg = Config(QWEN, 9, "bf16", 4096)
    n_judged = len(configs) + sum(c.precision == "w8" for c in configs)
    judge = 0.0 if stage == "pilot" else generation_hours([judge_cfg] * n_judged, items, 1, tps, 1.0, tokens)
    setup = sum(quantize_hours(c) for c in checkpoints(configs)) + 0.05 * len(checkpoints(configs)) + ENV_SETUP_H
    kernel = 0.1 * len({c.size_b for c in configs}) if stage == "stage1" and kernel_run else 0.0
    hours = (gen + self_check + judge + setup + kernel) * overhead
    return {"stage": stage, "machine": machine, "configs": len(configs), "items": items, "k": k,
            "generation_h": round(gen, 2), "self_check_h": round(self_check, 2), "judge_h": round(judge, 2),
            "setup_h": round(setup, 2), "kernel_h": round(kernel, 2), "overhead": round(overhead, 2),
            "hours": round(hours, 2), "usd": round(hours * rate_usd, 2), "rate_usd_per_h": rate_usd}


def checkpoint_hours(stage: str, checkpoint: str, items: int, k: int = 6, machine: str | None = None,
                     overhead: float | None = None, scale: float | None = None) -> float:
    """Guard estimate for one served checkpoint: its configs' k samples on `items` items plus self-checks (3 of k,
    at half the tokens), at the measured throughput and tokens per call, times the overhead."""
    m = measured()
    _, tps = _speeds(machine, scale)
    overhead = max(MIN_OVERHEAD, float(m.get("overhead", 0.0))) if overhead is None else overhead
    configs = [c for c in STAGES[stage]() if c.checkpoint == checkpoint]
    tokens = m.get("tokens_per_call")
    hours = generation_hours(configs, items, k, tps, 1.0, tokens) + 0.5 * generation_hours(configs, items, 3, tps, 1.0, tokens)
    return round(max(STEP_FLOOR_H, hours * overhead + 0.05), 2)


def judge_hours(stage: str, items: int, machine: str | None = None, overhead: float | None = None,
                scale: float | None = None) -> float:
    """Guard estimate for the judge step: one 9B BF16 4k call per item and config, plus one per W8 config."""
    m = measured()
    _, tps = _speeds(machine, scale)
    overhead = max(MIN_OVERHEAD, float(m.get("overhead", 0.0))) if overhead is None else overhead
    configs = STAGES[stage]()
    n = len(configs) + sum(c.precision == "w8" for c in configs)
    return round(generation_hours([Config(QWEN, 9, "bf16", 4096)] * n, items, 1, tps, 1.0, m.get("tokens_per_call"))
                 * overhead + 0.05, 2)


def recommended_scope(items: int, limit_usd: float = 45.0, cap_usd: float = 55.0, **kw) -> dict:
    """The pre-registered drop rule: keep everything if stage 1 fits `limit_usd`; else drop W3; else also the kernel
    run; if still above `cap_usd`, stop."""
    steps = [([], True), (["w3"], True), (["w3"], False)]
    for drop, kernel in steps:
        est = stage_estimate("stage1", items, drop_precisions=drop, kernel_run=kernel, **kw)
        if est["usd"] <= limit_usd:
            return {"drop_precisions": drop, "kernel_run": kernel, "estimate": est, "decision": "run"}
    return {"drop_precisions": drop, "kernel_run": kernel, "estimate": est,
            "decision": "run" if est["usd"] <= cap_usd else "stop and hand back"}
