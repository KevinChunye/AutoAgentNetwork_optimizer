"""Panel configs (`kind: panel`): every item goes to a list of sources, each called n times (step 0.7).

`aan estimate`, `aan check` and `aan run` accept these files. A paid panel run uses the same ledger,
call cache, spend governor (hard caps, the phase's account caps and total, the run cap), prereg gate
and status.json as every other run; it checkpoints state/ after every chunk of items and stops on a
missed expectation.

Terms:
  item     one question (a task in the task file), in the order of the run's id list (`items`).
  source   one model ref at one setting with one prompt, e.g. haiku_nothink with the base prompt. Its
           label in the output is "<ref>:<prompt>".
  call     one answer of a source to an item, indexed from `first_call`; the index is the call cache's
           replicate number, so call 1 of a source is a new sample and call 0 is shared with any other
           run that asked the same source the same item. A second mid-size call on 100 items is a
           source entry with `first_call: 1, calls: 1, items: <the 100-id list>`.
  vendor   the billed account of a ref. One run may only call one vendor ("runs are split by vendor"),
           so a rate-limited vendor never stalls the other.

Prompts: `base`, a persona (`careful`, `contrarian`, `quick`), `aggregator`, `judge` or `self_check`. An
aggregator source reads the panel's answers to the item from `panel_results` (calls.csv files of earlier runs;
only the sources in `panel_sources`) and returns one answer and a confidence (prompts.py). A judge source reads the
same answers but sees only the distinct ones (equal under the task's grader), with no counts, and must pick one; a
self_check source reads the call-0 answer of the source named in its `checks` field and returns a verdict
("correct" or "incorrect") and a confidence; its row's `correct` says whether the verdict was right, beside the
checked answer and whether that answer was right (`checked_answer`, `checked_correct`). Items whose checked answer is
unparsed are not self-checked. Verification rows record prompts.VERIFY_HASH as their template hash.

Output in results/<name>/ (rows of other items already there are kept, so slices add up): calls.csv, one
row per call: item, task kind and item meta, source, ref, model, setting (the request options), prompt,
call index, reply, parsed answer, parsed flag, correct (bbeh and math) or outcome (forecast), probability
(forecast, or the aggregator's confidence), tokens (output tokens include hidden reasoning), dollars,
seconds, the model version the API reported, stop reason, truncation and cache flags; and status.json.
Session M1 appends the per-call timing and context columns (latency.TIMING_COLUMNS: TTFT, TTFAT, first thinking,
decode speed, end-to-end rate, total seconds, retries, concurrency at submit, streamed, context tokens,
timing_source, ...) after the existing ones, and writes run_card.json (latency.run_card).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from typing import Literal

import pandas as pd
import yaml
from pydantic import BaseModel, ConfigDict

from ..agents.agent import prompt_text
from ..agents.spec import AgentInput, AgentRequest, AgentSpec
from ..budget import BudgetExceeded, BudgetRules, SpendGovernor
from ..cache import CallCache
from ..experiment import Prereg, gate_problems
from ..latency import call_columns, run_card
from ..market.caller import MarketCaller
from ..meter import Ledger
from ..persist import code_version, git_checkpoint
from ..pricing import PriceBook
from ..providers.base import TRUNCATED_STOP_REASONS, LLMRequest, LLMResponse, estimate_tokens
from ..providers.fake import FakeClient
from ..providers.registry import ProviderRegistry
from ..runtime.local import LocalRuntime
from ..runtime.maritime import MaritimeRuntime
from ..tasks import Task, answers_match, load_tasks, parse_answer as math_parse
from . import prompts as P
from .mathread import abstained, math_read

TaskKind = Literal["bbeh", "forecast", "math", "code"]  # code: study CD (session E6), graded at the read


class PanelSource(BaseModel):
    """One source of the panel. max_tokens caps every generated token, hidden reasoning included."""

    model_config = ConfigDict(extra="forbid")
    ref: str
    calls: int = 1
    first_call: int = 0
    prompt: str = "base"
    max_tokens: int = 4000
    items: str | None = None  # optional id-list file: this source answers only these items
    checks: str | None = None  # self_check only: the label ("<ref>:<prompt>") whose call 0 this source checks

    @property
    def label(self) -> str:
        return f"{self.ref}:{self.prompt}"


class PanelExpect(BaseModel):
    """Stop rules checked after every chunk, per source, once a source has `min_calls` live calls
    (the plan's step 1.5):
      max_unparsed_rate    share of a source's replies the parser cannot read
      max_truncation_rate  share cut off by max_tokens
      usd_per_call         the probe's measured dollars per call, by ref; a source whose mean live cost per
                           call passes max_cost_ratio times it stops the run
      max_missing_price    share of market questions without a freeze price (checked before the run)"""

    model_config = ConfigDict(extra="forbid")
    min_calls: int = 20
    max_unparsed_rate: float | None = 0.05
    max_truncation_rate: float | None = 0.05
    usd_per_call: dict[str, float] = {}
    max_cost_ratio: float = 1.5
    max_missing_price: float = 0.10


class PanelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["panel"]
    name: str
    task_kind: TaskKind
    tasks: str  # task JSONL (data/external/evidence/*.jsonl)
    items: str  # id list, one id per line (research/v3/evidence/sealed/*.txt): the run's items, in order
    sources: list[PanelSource]
    prereg: Prereg | None = None
    phase: str = "evidence"  # the budget phase this run belongs to; a paid run refuses under any other active phase
    panel_results: list[str] = []  # calls.csv files an aggregator source reads
    panel_sources: dict[str, int] = {}  # source label -> calls 0..n-1 of it shown to the aggregator (empty = every base-prompt call)
    requires: list[str] = []  # files that must exist and be committed before a paid run (e.g. a frozen selection)
    blind: bool = False  # collected blind (K4, audit 52): no grade or outcome is written; the committed read regrades
    parser: Literal["v1", "v2"] = "v1"  # answer parser version (prompts.parse_answer; v2 for the API anchor only)
    stop_over_config: bool = False  # check the stop rules over every slice's calls so far, not this run's alone
    task_offset: int = 0
    task_limit: int | None = None
    model_override: str | None = None
    max_usd: float | None = None  # optional run cap for this config; None = only the phase and hard caps apply
    chunk_size: int = 25
    max_concurrency: int = 8
    timing: bool = False  # session M1: true streams every API request and records TTFT, TTFAT, decode speed (transport
    # only). New configs set it to true; the default stays false (audit M1-1) until the timing probe has run with no
    # stream failure, since a stream cut mid-reply raises StreamCut and is not retried
    expect: PanelExpect = PanelExpect()
    runtime: Literal["local", "maritime"] = "local"
    maritime: str = "configs/runtime/maritime.yaml"
    providers: str = "configs/providers.yaml"
    pricing: str = "configs/pricing.yaml"
    budget: str = "configs/budget.yaml"
    ledger: str = "state/ledger.jsonl"
    cache: str = "state/cache"
    require_ledger: bool = True
    git_checkpoint: bool = True
    out_dir: str = "results"

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PanelConfig":
        return cls(**yaml.safe_load(Path(path).read_text()))

    def model_override_resolved(self) -> str | None:
        return self.model_override or os.getenv("AAN_MODEL_OVERRIDE")


def is_panel_config(path: str | Path) -> bool:
    raw = yaml.safe_load(Path(path).read_text())
    return isinstance(raw, dict) and raw.get("kind") == "panel"


def read_ids(path: str | Path) -> list[str]:
    return [line.strip() for line in Path(path).read_text().splitlines() if line.strip() and not line.startswith("#")]


def select_items(cfg: PanelConfig) -> list[Task]:
    """The run's items: the id list in its order, sliced by task_offset/task_limit."""
    by_id = {t.id: t for t in load_tasks(cfg.tasks)}
    ids = read_ids(cfg.items)
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"{len(missing)} ids of {cfg.items} are not in {cfg.tasks}, e.g. {missing[0]}")
    ids = ids[cfg.task_offset:]
    ids = ids[: cfg.task_limit] if cfg.task_limit else ids
    return [by_id[i] for i in ids]


def vendor_of(cfg: PanelConfig, registry: ProviderRegistry) -> str:
    """The one account every source bills (checked on the refs as written, before any override)."""
    accounts = sorted({registry.account_of(s.ref) for s in cfg.sources})
    if len(accounts) != 1:
        raise ValueError(f"a panel run calls one vendor; {cfg.name} mixes {accounts}. Split it by vendor.")
    return accounts[0]


PLACEHOLDER = "x" * 40  # an answer of 40 characters, for estimates made before the panel has run


def panel_answers(cfg: PanelConfig) -> dict[str, list[str | None]]:
    """Item -> the panel's parsed answers (in a fixed order: source label, then call), for aggregators.
    Before the panel has run (its calls.csv files are missing) every item gets 12 placeholder answers of
    40 characters, so an estimate is still an upper bound for typical answers; a run refuses instead."""
    if not cfg.panel_results:
        return {}
    if not all(Path(p).exists() for p in panel_files(cfg)):
        return {t.id: [PLACEHOLDER] * 12 for t in select_items(cfg)}
    calls = pd.concat([pd.read_csv(p, dtype={"answer": str}) for p in panel_files(cfg)], ignore_index=True)
    if cfg.panel_sources:
        limit = calls["source"].map(cfg.panel_sources)
        calls = calls[limit.notna() & (calls["call"] < limit.fillna(0))]
    else:
        calls = calls[calls["prompt"] == "base"]
    calls = calls.sort_values(["item", "source", "call"], kind="stable")
    out: dict[str, list[str | None]] = {}
    for item, group in calls.groupby("item"):
        out[item] = [None if pd.isna(a) else str(a) for a in group["answer"]]
    return out


READS_PANEL = ("aggregator", "judge")
VERIFY_PROMPTS = ("judge", "self_check")


def distinct_answers(answers: list[str | None], grader: str) -> list[str]:
    """The parsed answers, one per class of answers equal under the grader, in first-seen order."""
    out: list[str] = []
    for a in answers:
        if a is not None and not any(answers_match(b, a, grader) for b in out):
            out.append(a)
    return out


def shown_candidates(answers: list[str | None], grader: str, seed: str) -> list[str]:
    """The candidates a judge is shown, in the order it sees them (Candidate 1 first): the distinct parsed answers of
    the panel's calls, ordered by prompts.judge_order (the order judge_task prints)."""
    candidates = distinct_answers(answers, grader)
    return [candidates[i] for i in P.judge_order(len(candidates), seed)]


def items_in(path: str | Path) -> int:
    """The number of distinct items in a calls.csv."""
    return int(pd.read_csv(path, usecols=["item"])["item"].nunique())


def t30_of(path: str | Path) -> Path:
    """`<run>_t30/calls.csv` for `<run>/calls.csv`: the run's pre-declared truncation fallback."""
    p = Path(path)
    return p.parent.with_name(p.parent.name + "_t30") / p.name


def fallback_file(path: str) -> str:
    """The calls.csv to read for a run (audits 77, 78): its `_t30` fallback when that file exists and holds at least
    the run's items (the fallback replays the earlier calls from the cache, so it normally holds more), else the run's
    own file. The anchor's read uses the same rule (analysis/anchor_read.fallback), so a run and the read agree."""
    alt = t30_of(path)
    if not alt.exists():
        return path
    return str(alt) if not Path(path).exists() or items_in(alt) >= items_in(path) else path


def panel_files(cfg: PanelConfig) -> list[str]:
    """The calls.csv files a judge, aggregator or self-check reads: each of panel_results through fallback_file."""
    return [fallback_file(p) for p in cfg.panel_results]


def panel_file_problems(cfg: PanelConfig) -> list[str]:
    """Why a paid run may not read its panel files (audit 78): a file that is not committed (an untracked or stale
    file would be read without a flag), or a `_t30` fallback that holds fewer items than its run (it would lose items)."""
    problems = [f"{p} must be committed before a run reads it" for p in uncommitted(panel_files(cfg))]
    problems += [f"{t30_of(p)} holds fewer items than {p}: a fallback that stopped earlier than its run goes to an "
                 "audit first" for p in cfg.panel_results if t30_of(p).exists() and fallback_file(p) == p]
    return problems


def checked_answers(cfg: PanelConfig, label: str) -> dict[str, str]:
    """Item -> the parsed call-0 answer of source `label` in panel_results (unparsed items are absent). Before the
    panel has run (a dry run's estimate), every item gets a placeholder answer of 40 characters."""
    if not all(Path(p).exists() for p in panel_files(cfg)):
        return {t.id: PLACEHOLDER for t in select_items(cfg)}
    calls = pd.concat([pd.read_csv(p, dtype={"answer": str}) for p in panel_files(cfg)], ignore_index=True)
    mine = calls[(calls["source"] == label) & (calls["call"] == 0) & calls["parsed"].astype(bool)]
    return dict(zip(mine["item"], mine["answer"].astype(str)))


def requests_for(cfg: PanelConfig, items: list[Task], ref_of: dict[str, str]) -> list[tuple[Task, PanelSource, int, AgentRequest]]:
    """Every (item, source, call index, request) of the run. `ref_of` maps a source's ref to the ref
    actually called (the fake model in a dry run). The agent id names the ref as written and the prompt,
    so a dry run and a paid run of the same source never share cache keys with another source."""
    kind = cfg.task_kind
    answers = panel_answers(cfg) if any(s.prompt in READS_PANEL for s in cfg.sources) else {}
    checked = {s.checks: checked_answers(cfg, s.checks) for s in cfg.sources if s.prompt == "self_check"}
    out = []
    for source in cfg.sources:
        allowed = set(read_ids(source.items)) if source.items else None
        for item in items:
            if allowed is not None and item.id not in allowed:
                continue
            task, text = item.prompt, None
            if source.prompt == "aggregator":
                panel = answers.get(item.id, [None] * 12)
                task, text = P.aggregator_task(kind, item.prompt, panel, seed=item.id)
            elif source.prompt == "judge":
                candidates = distinct_answers(answers.get(item.id, []), item.grader)
                if not candidates:
                    continue
                task, text = P.judge_task(kind, item.prompt, candidates, seed=item.id)
            elif source.prompt == "self_check":
                own = checked[source.checks].get(item.id)
                if own is None:
                    continue
                task, text = P.self_check_task(kind, item.prompt, own)
            spec = AgentSpec(agent_id=f"{source.ref}.{source.prompt}", stage=f"panel_{kind}", index=0,
                             model=ref_of[source.ref], system=P.SYSTEMS[kind],
                             instruction=text if text is not None else P.instruction(kind, source.prompt),
                             max_tokens=source.max_tokens, temperature=None)
            request = AgentRequest(spec=spec, input=AgentInput(task_id=item.id, task=task, shared_prefix=True))
            for c in range(source.first_call, source.first_call + source.calls):
                out.append((item, source, c, request))
    return out


REFUSAL_STOP_REASONS = ("refusal", "content_filter", "invalid_prompt")  # a safety decline: Anthropic's stop reason;
# OpenAI's finish_reason; OpenAI's prompt filter (a 400 the provider turns into an empty reply, providers/openai_compat.py)


def grade(kind: str, prompt: str, item: Task, reply: str, stop_reason: str | None = None,
          checked: str | None = None, parser: str = "v1", labels: list[str] | None = None,
          shown: list[str] | None = None) -> dict:
    """Parsed answer, parsed flag, correct (bbeh, math), probability (forecast; aggregator and judge confidence). A
    reply that stopped on a safety decline is unparsed whatever text it carries (audit 51): it is counted as refused.
    A self-check's answer is its verdict; `correct` is whether the verdict matches the checked answer's grade. A
    judge's answer is read through prompts.judge_reply when the candidates it was shown are given (audit 75)."""
    if stop_reason in REFUSAL_STOP_REASONS:
        return {"answer": None, "parsed": False, "correct": 0.0 if kind in ("bbeh", "math") else None, "prob": None}
    if prompt == "self_check":
        verdict, prob = P.parse_verdict(reply), P.parse_confidence(reply)
        truth = answers_match(item.answer, checked, item.grader)
        parsed = verdict is not None and prob is not None
        return {"answer": verdict, "parsed": parsed, "prob": prob,
                "correct": float(parsed and (verdict == "correct") == truth),
                "checked_answer": checked, "checked_correct": float(truth)}
    picked = P.judge_reply(kind, reply, shown) if prompt == "judge" and shown is not None else reply
    answer = P.parse_answer(kind, picked, parser, labels)
    confident = prompt in READS_PANEL
    prob = P.parse_probability(reply) if kind == "forecast" else P.parse_confidence(reply) if confident else None
    # math under v2 (the anchor): parsed as the read parses it (mathread.math_read, audit 83), so the stop rules and
    # self-check eligibility count what the read can grade; the stored answer stays raw
    readable = math_read(answer, item.answer) if answer is not None and kind == "math" and parser == "v2" else answer
    parsed = answer is not None and (kind != "math" or len(math_parse(readable)) > 0)
    if confident and kind != "forecast":
        parsed = parsed and prob is not None
    correct = None
    if kind in ("bbeh", "math"):
        right = answers_match(item.answer, answer, item.grader)
        if parser == "v2" and kind == "bbeh" and not right and item.answer is not None:
            # v2 strips qualifiers from answers; the gold is compared stripped the same way (a gold of "sweet (adj.)")
            right = answers_match(P.strip_qualifier(item.answer), answer, item.grader)
        if parser == "v2.1" and kind == "bbeh" and not right and item.answer is not None:
            gold = P.normalize_marks(item.answer)
            right = (answers_match(gold, answer, item.grader)
                     or answers_match(P.strip_qualifier_v21(item.answer, labels), answer, item.grader))
        correct = float(parsed and right)
    return {"answer": answer, "parsed": parsed, "correct": correct, "prob": prob}


def blinded(graded: dict, blind: bool) -> dict:
    """A blind run keeps the parsed answer and probability but drops the grade (K4: nothing on disk says whether a
    lockbox call was right until the committed read regrades it)."""
    return {**graded, "correct": None} if blind else graded


def call_row(cfg: PanelConfig, registry: ProviderRegistry, item: Task, source: PanelSource, c: int, out,
             checked: str | None = None, shown: list[str] | None = None) -> dict:
    meta = {k: item.meta.get(k) for k in ("task", "position", "source", "market", "question_id", "set") if k in item.meta}
    return {
        "item": item.id, "task_kind": cfg.task_kind, **{f"meta_{k}": v for k, v in meta.items()},
        "outcome": int(item.answer) if cfg.task_kind == "forecast" and not cfg.blind else None,
        "source": source.label, "ref": source.ref, "model": registry.model_id(source.ref),
        "setting": json.dumps(registry.options_of(source.ref), sort_keys=True), "prompt": source.prompt, "call": c,
        **blinded(grade(cfg.task_kind, source.prompt, item, out.content, out.stop_reason, checked, cfg.parser,
                        shown=shown), cfg.blind),
        "parser": cfg.parser, "format_ok": P.format_ok(cfg.task_kind, out.content),
        "input_tokens": out.usage.input_tokens, "cache_write_tokens": out.usage.cache_write_tokens,
        "cache_read_tokens": out.usage.cache_read_tokens, "output_tokens": out.usage.output_tokens,
        "thinking_tokens": out.usage.thinking_tokens,
        "visible_output_tokens": estimate_tokens(out.content, 4.0), "cost_usd": out.cost_usd,
        "seconds": out.latency_s, "model_version": out.model, "stop_reason": out.stop_reason,
        "truncated": out.stop_reason in TRUNCATED_STOP_REASONS, "from_cache": out.from_cache,
        "template_hash": P.VERIFY_HASH if source.prompt in VERIFY_PROMPTS
        else P.CODE_HASH if cfg.task_kind == "code" else P.TEMPLATE_HASH, "reply": out.content,
        **call_columns(out),
    }


class FakePanelClient(FakeClient):
    """Offline replies in the panel's formats, for dry runs. The reply depends only on the request:
    a number `roll` hashed from it picks the answer ("yes"/"no" lists, a small integer, a probability);
    about 1 in 200 replies has no final line, so the parse path is exercised without tripping the 5% stop rule."""

    async def complete(self, request: LLMRequest) -> LLMResponse:
        base = await super().complete(request)
        digest = hashlib.sha256((request.system + "".join(b.text for b in request.blocks) + request.model).encode()).hexdigest()
        roll = int(digest[:8], 16)
        aggregator = "CONFIDENCE" in request.blocks[-1].text or "Combine them" in request.blocks[-1].text
        if roll % 200 == 0:
            text = "I am not sure."
        elif "VERDICT" in request.blocks[-1].text:
            return base.model_copy(update={"text": f"Checked.\nVERDICT: {['correct', 'incorrect'][roll % 2]}\n"
                                                    f"CONFIDENCE: {0.3 + (roll % 70) / 100:.2f}"})
        elif request.system == P.FORECAST_SYSTEM:
            text = f"Weighing it up.\nProbability: {0.05 + (roll % 90) / 100:.2f}"
        elif request.system == P.MATH_SYSTEM:
            text = f"Compute.\n\\boxed{{{roll % 7}}}"
        elif request.system == P.CODE_SYSTEM:
            text = f"Plan.\n```python\nprint({roll % 7})\n```"
        else:
            text = f"Reasoning.\nANSWER: {['yes', 'no', '(A)', '3'][roll % 4]}"
        if aggregator and request.system != P.FORECAST_SYSTEM:
            text += f"\nCONFIDENCE: {0.3 + (roll % 70) / 100:.2f}"
        return base.model_copy(update={"text": text})


def estimate_panel(cfg: PanelConfig) -> pd.DataFrame:
    """Worst case: every call with its prompt at the dearest input rate and the full max_tokens of output.
    Cached calls are ignored, so it is an upper bound."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    pricebook = PriceBook.from_yaml(cfg.pricing)
    override = cfg.model_override_resolved()
    ref_of = {s.ref: override or s.ref for s in cfg.sources}
    rows = []
    for item, source, c, request in requests_for(cfg, select_items(cfg), ref_of):
        ref = ref_of[source.ref]
        model, provider = registry.model_id(ref), registry.provider_of(ref)
        rows.append({"account": registry.account_of(ref), "model": model, "worst_case_usd": pricebook.worst_case_usd(
            model, provider, estimate_tokens(prompt_text(request.spec, request.input)), request.spec.max_tokens)})
    table = pd.DataFrame(rows).groupby(["account", "model"]).agg(calls=("worst_case_usd", "size"),
                                                                worst_case_usd=("worst_case_usd", "sum"))
    table["worst_case_x_safety"] = table["worst_case_usd"] * BudgetRules.from_yaml(cfg.budget).safety_multiplier
    return table


def is_free(cfg: PanelConfig, registry: ProviderRegistry) -> bool:
    override = cfg.model_override_resolved()
    return bool(override) and registry.provider_of(override) == "fake"


def item_problems(cfg: PanelConfig) -> list[str]:
    """Checks on the items before any call: one vendor per run, and the freeze price on market questions."""
    problems = []
    try:
        vendor_of(cfg, ProviderRegistry.from_yaml(cfg.providers))
    except ValueError as exc:
        problems.append(str(exc))
    if cfg.task_kind == "forecast":
        markets = [t for t in select_items(cfg) if t.meta.get("market")]
        missing = sum(1 for t in markets if t.meta.get("freeze_value") in (None, "", "N/A"))
        if markets and missing / len(markets) > cfg.expect.max_missing_price:
            problems.append(f"{missing} of {len(markets)} market questions lack the freeze price (stop rule 1.5)")
    if any(s.prompt in READS_PANEL + ("self_check",) for s in cfg.sources):
        missing = [p for p in cfg.panel_results if not Path(p).exists()]
        if not cfg.panel_results or missing:
            problems.append(f"an aggregator, judge or self-check source needs the panel's calls.csv files; missing: "
                            f"{missing or 'panel_results'}")
    problems += [f"self_check source {s.label} must name the source it checks (checks: <ref>:<prompt>)"
                 for s in cfg.sources if s.prompt == "self_check" and not s.checks]
    return problems


def preflight_panel(cfg: PanelConfig, config_path: str | Path) -> tuple[list[str], pd.DataFrame | None]:
    if is_free(cfg, ProviderRegistry.from_yaml(cfg.providers)):
        if cfg.out_dir == "results":
            cfg = cfg.model_copy(update={"panel_results": dry_panel_results(cfg.panel_results)})
        return item_problems(cfg), None
    problems = item_problems(cfg)
    active = BudgetRules.from_yaml(cfg.budget).phase
    if active != cfg.phase:
        problems.append(f"this run belongs to budget phase {cfg.phase!r} but the active phase is {active!r}: "
                        "stop and ask Kevin (only he changes the budget rules)")
    problems += [f"{p} must exist and be committed before this run: it freezes what the run tests"
                 for p in uncommitted(cfg.requires)]
    if any(s.prompt in READS_PANEL + ("self_check",) for s in cfg.sources):
        problems += panel_file_problems(cfg)
    table = estimate_panel(cfg)
    return problems + gate_problems(cfg, config_path, table), table


def uncommitted(paths: list[str]) -> list[str]:
    """The paths that are missing, untracked, or changed since the last commit."""
    import subprocess

    out = []
    for p in paths:
        tracked = subprocess.run(["git", "ls-files", "--error-unmatch", p], capture_output=True).returncode == 0
        clean = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", p], capture_output=True).returncode == 0
        if not (Path(p).exists() and tracked and clean):
            out.append(p)
    return out


def expectation_misses(calls: pd.DataFrame, expect: PanelExpect) -> list[str]:
    """The stop rules of PanelExpect on this run's live calls, per source.

    Audit 88: an unparsed math answer that says the value is not known (mathread.abstained, form only) is an
    abstention, not a format failure. The unparsed rate is the share of live calls that are unparsed and not such an
    abstention; abstentions are reported apart, as refusals are, and the read still grades them wrong.
    Audit 101: a config that declares no truncation stop (max_truncation_rate 1.0 or more: study CD's arms at the
    model's maximum output) does not count its cut calls as unparsed either, or the unparsed stop would stop on
    truncation after all; the cut share is still computed and reported, and the read grades cut calls wrong."""
    live = calls[~calls["from_cache"].astype(bool)] if not calls.empty else calls
    if live.empty:
        return []
    if "stop_reason" not in live:
        live = live.assign(stop_reason=None)
    if "answer" not in live:
        live = live.assign(answer=None)
    if "task_kind" not in live:
        live = live.assign(task_kind=None)
    refused = live["stop_reason"].isin(REFUSAL_STOP_REASONS)
    unparsed = ~live["parsed"].astype(bool)
    abstain = unparsed & (live["task_kind"] == "math") & live["answer"].map(abstained)
    no_cut_stop = expect.max_truncation_rate is None or expect.max_truncation_rate >= 1.0
    cut = live["truncated"].fillna(False).astype(bool) if no_cut_stop else pd.Series(False, index=live.index)
    live = live.assign(other_unparsed=unparsed & ~refused, answered=~refused, abstain=abstain,
                       counted=unparsed & ~abstain & ~cut)
    rates = live.groupby(["source", "ref"]).agg(calls=("parsed", "size"), unparsed=("counted", "mean"),
                                                truncated=("truncated", "mean"), usd=("cost_usd", "mean"),
                                                refused=("stop_reason", lambda x: int(x.isin(REFUSAL_STOP_REASONS).sum())),
                                                other=("other_unparsed", "sum"), answered=("answered", "sum"),
                                                abstained=("abstain", "sum")).reset_index()
    misses = []
    for r in rates[rates["calls"] >= expect.min_calls].itertuples():
        if expect.max_unparsed_rate is not None and r.unparsed > expect.max_unparsed_rate:
            other = r.other / r.answered if r.answered else 0.0
            misses.append(f"{r.unparsed:.1%} of {r.source} replies unparsed (limit {expect.max_unparsed_rate:.0%}; "
                          f"{r.refused} of {r.calls} refused or blocked; {other:.1%} unparsed without them; "
                          f"{int(r.abstained)} math abstentions not counted)")
        if expect.max_truncation_rate is not None and r.truncated > expect.max_truncation_rate:
            misses.append(f"{r.truncated:.1%} of {r.source} replies truncated (limit {expect.max_truncation_rate:.0%})")
        if r.ref in expect.usd_per_call and r.usd > expect.max_cost_ratio * expect.usd_per_call[r.ref]:
            misses.append(f"{r.source} costs ${r.usd:.5f} per call, above {expect.max_cost_ratio}x the probe's "
                          f"${expect.usd_per_call[r.ref]:.5f}")
    return misses


def merge_write(path: Path, new: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Write `new`, keeping rows already in the file whose keys `new` does not cover; return the whole table."""
    if path.exists() and path.stat().st_size > 0 and not new.empty:
        old = pd.read_csv(path, dtype={"answer": str})
        old = old[~old.set_index(keys).index.isin(new.set_index(keys).index)]
        new = pd.concat([old, new], ignore_index=True)
    if not new.empty:
        new = new.sort_values(["item", "source", "call"], kind="stable")
        new.to_csv(path, index=False)
    return new


def dry_panel_results(paths: list[str]) -> list[str]:
    """In a dry run, an aggregator reads the panel's dry-run outputs: results/<name>/ becomes runs/dry/<name>/."""
    return [str(Path("runs/dry") / Path(p).relative_to("results")) if Path(p).parts[0] == "results" else p for p in paths]


async def run_panel(cfg: PanelConfig) -> tuple[pd.DataFrame, dict]:
    """Ask every item of the run's slice. Returns (this run's call rows, status)."""
    if is_free(cfg, ProviderRegistry.from_yaml(cfg.providers)) and cfg.out_dir == "results":
        cfg = cfg.model_copy(update={"panel_results": dry_panel_results(cfg.panel_results)})
    if any(s.prompt in READS_PANEL + ("self_check",) for s in cfg.sources) and not all(Path(p).exists() for p in cfg.panel_results):
        raise FileNotFoundError(f"{cfg.name}: the panel results it reads are missing: {cfg.panel_results}")
    registry = ProviderRegistry.from_yaml(cfg.providers)
    registry.set_timing(cfg.timing)
    vendor = vendor_of(cfg, registry)
    run_id = f"{cfg.name}-{int(time.time())}"
    override = cfg.model_override_resolved()
    free = is_free(cfg, registry)
    if free:  # nothing is spent, so nothing tracked is touched; dry runs go to runs/dry
        out_dir = "runs/dry" if cfg.out_dir == "results" else cfg.out_dir
        cfg = cfg.model_copy(update={"git_checkpoint": False, "out_dir": out_dir})
        ledger, cache = Ledger(), CallCache()
        registry.set_client(override, FakePanelClient())
    else:
        ledger = Ledger(cfg.ledger, must_exist=cfg.require_ledger)
        cache = CallCache(cfg.cache, shard_prefix=run_id)
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    runtime = LocalRuntime(registry) if cfg.runtime == "local" else MaritimeRuntime.from_yaml(cfg.maritime)
    caller = MarketCaller(runtime, registry, pricebook=PriceBook.from_yaml(cfg.pricing), cache=cache, governor=governor,
                          run_id=run_id, market=cfg.name, condition=cfg.task_kind, purpose="panel")
    out = Path(cfg.out_dir) / cfg.name
    out.mkdir(parents=True, exist_ok=True)
    items = select_items(cfg)
    ref_of = {s.ref: override or s.ref for s in cfg.sources}
    status = {"run_id": run_id, "state": "completed", "reason": "", "vendor": vendor, "task_kind": cfg.task_kind,
              "items": [cfg.task_offset, cfg.task_offset + len(items)], "sources": [s.model_dump() for s in cfg.sources],
              "template_hash": P.CODE_HASH if cfg.task_kind == "code" else P.TEMPLATE_HASH, "code": code_version(), "panel_files": panel_files(cfg), "checkpoints": []}
    rows: list[dict] = []
    gate = asyncio.Semaphore(cfg.max_concurrency)

    checked_of = {s.label: checked_answers(cfg, s.checks) for s in cfg.sources if s.prompt == "self_check"}
    answers = panel_answers(cfg) if any(s.prompt == "judge" for s in cfg.sources) else {}
    shown_of = {t.id: shown_candidates(answers.get(t.id, []), t.grader, t.id) for t in items} if answers else {}

    async def ask(item, source, c, request):
        async with gate:
            output = await caller.call(request, replicate=c)
        checked = checked_of[source.label].get(item.id) if source.prompt == "self_check" else None
        shown = shown_of.get(item.id) if source.prompt == "judge" else None
        return call_row(cfg, registry, item, source, c, output, checked, shown)

    try:
        for first in range(0, len(items), cfg.chunk_size):
            chunk = items[first: first + cfg.chunk_size]
            jobs = requests_for(cfg, chunk, ref_of)
            outcomes = await asyncio.gather(*(ask(*job) for job in jobs), return_exceptions=True)
            rows += [o for o in outcomes if isinstance(o, dict)]
            errors = [o for o in outcomes if isinstance(o, BaseException)]
            cache.rotate()
            if cfg.git_checkpoint:
                status["checkpoints"].append(git_checkpoint(
                    [cfg.ledger, cfg.cache], f"state: {run_id} items {cfg.task_offset + first}-{cfg.task_offset + first + len(chunk) - 1}"))
            written = merge_write(out / "calls.csv", pd.DataFrame(rows), ["item", "source", "call"])
            budget_errors = [e for e in errors if isinstance(e, BudgetExceeded)]
            if budget_errors:
                status.update(state="stopped", reason=f"budget: {budget_errors[0]}")
                break
            if errors:
                status.update(state="failed", reason=f"{type(errors[0]).__name__}: {errors[0]}")
                break
            # stop rules over this run's calls, or (stop_over_config) over every call of the config so far: every
            # earlier slice's live calls too, so sources with few calls per slice are still checked (audit 71)
            misses = expectation_misses(written if cfg.stop_over_config else pd.DataFrame(rows), cfg.expect)
            if misses:
                status.update(state="stopped", reason="expectation missed: " + "; ".join(misses))
                break
    finally:
        await runtime.aclose()
        frame = pd.DataFrame(rows)
        status["calls"] = len(rows)
        status["live_calls"] = caller.live_calls
        if not frame.empty:
            status["by_source"] = frame.groupby("source").agg(
                calls=("parsed", "size"), parsed=("parsed", "mean"), truncated=("truncated", "mean"),
                usd=("cost_usd", "sum"), live=("from_cache", lambda x: int((~x.astype(bool)).sum())),
                refused=("stop_reason", lambda x: int(x.isin(REFUSAL_STOP_REASONS).sum()))).round(5).to_dict("index")
            status["model_versions"] = sorted(frame["model_version"].astype(str).unique())
        status["budget"] = governor.status()
        status["rate_limits"] = registry.rate_limits()
        (out / "status.json").write_text(json.dumps(status, indent=2, default=str))
        card = run_card(run_id=run_id, timing=cfg.timing, max_concurrency=cfg.max_concurrency,
                        model_ids=[registry.model_id(ref) for ref in registry.built_refs()],
                        model_versions=list(frame["model_version"]) if not frame.empty else [], runtime=cfg.runtime)
        (out / "run_card.json").write_text(json.dumps(card, indent=2))
    return pd.DataFrame(rows), status
