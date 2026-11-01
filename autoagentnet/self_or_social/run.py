"""Self-or-social configs (`kind: self_or_social`): the branch table of a team on a list of items of one task kind
(`task_kind`: bbeh, the default; math; mcq; protocol.py describes each).

`aan estimate`, `aan check` and `aan run` accept these files. A paid run uses the same ledger, call cache, spend
governor (hard caps, the phase's account caps and total, the run cap), prereg gate and status.json as the panel
runs (evidence/panel.py, whose plumbing this follows); it checkpoints state/ after every chunk of items and stops
on a missed expectation (evidence/panel.PanelExpect, per receiver and phase).

Per item the run makes, for a team of n members:
  initial  each member's first answer: the panel's base request for its ref and task kind (protocol.initial_request).
           When a `reuse_first` calls.csv already holds that answer, the stored reply is used and no call is made; its
           recorded dollars still count as the deployment's cost. A reuse_first file is a panel calls.csv (source
           "<ref>:base", call = the member's `call`) or a self-or-social calls.csv (action "initial", same receiver id
           and ref). A missing file holds nothing; in a dry run, a missing results/<x> file is read from runs/dry/<x>.
  branch   (branches: true) every reflect and consult revision: n + n(n-1) calls, all reading the frozen snapshot;
  full     (full_review: true) every member's full review: n calls.
No decision is made here, so nothing here reads a gold answer except the grading of each row after its call.

One run calls one vendor (as panel runs do, so a rate-limited vendor never stalls the other). A team whose members
bill different vendors is run once per vendor (`vendor`): each run makes only the calls of its vendor's members (their
first answers when not reused, and their revisions) and reads the other members' first answers from `reuse_first`,
so every revision still reads the whole first-round snapshot. Both runs may share a `name`: their rows have
different (item, receiver, action) keys, so they add up in one calls.csv. When the first answers are new (no earlier
run holds them), each vendor first runs `first_answers_only: true` (its members' first answers, no revision); the
revision runs then name those calls.csv files in `reuse_first`.

Output in results/<name>/ (rows of other items already there are kept, so slices add up): calls.csv, one row per
(item, receiver, action): item, family (the item's task meta, the BBEH task), grader, position and receiver (team
member), ref, action (initial, reflect, consult:J, full), sender (J for consult), phase, task kind, reply, parsed
answer, parsed flag, correct, tokens, dollars, seconds, model version, stop reason, truncation, cache and reuse flags,
prompt hash; and status.json.
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
from pydantic import BaseModel, ConfigDict, model_validator

from ..agents.agent import prompt_text
from ..agents.spec import AgentOutput
from ..budget import BudgetExceeded, BudgetRules, SpendGovernor
from ..cache import CallCache
from ..evidence import prompts as P
from ..evidence.panel import PanelExpect, dry_panel_results, expectation_misses, read_ids, uncommitted
from ..experiment import Prereg, gate_problems
from ..market.caller import MarketCaller, cache_key
from ..meter import Ledger
from ..persist import code_version, git_checkpoint
from ..pricing import PriceBook
from ..providers.base import TRUNCATED_STOP_REASONS, Usage, estimate_tokens
from ..providers.fake import FakeClient
from ..providers.registry import ProviderRegistry
from ..runtime.local import LocalRuntime
from ..runtime.maritime import MaritimeRuntime
from ..tasks import Task, load_tasks
from .engine import branch_actions, first_replies, revisions
from .protocol import (CONSULT, CONSULT_INSTRUCTION, FULL_INSTRUCTION, GRADER_OF, MCQ_SYSTEM, REFLECT,
                       REFLECT_INSTRUCTION, Agent, base_instruction, format_ok, grade_reply, initial_request, peer_of,
                       revision_instruction, revision_request, system_of)

TEMPLATE_HASH = hashlib.sha256(json.dumps([P.TEMPLATE_HASH, REFLECT_INSTRUCTION, CONSULT_INSTRUCTION, FULL_INSTRUCTION]
                                          ).encode()).hexdigest()[:16]
KEYS = ["item", "receiver", "action"]
TaskKind = Literal["bbeh", "math", "mcq"]  # protocol.KINDS


def template_hash(kind: str = "bbeh") -> str:
    """The hash of every prompt a run of this task kind sends, recorded on each row and in status.json, so a changed
    prompt is visible. bbeh's is TEMPLATE_HASH, unchanged since before the kinds were added; another kind's also covers
    its system text and base instruction."""
    if kind == "bbeh":
        return TEMPLATE_HASH
    texts = [P.TEMPLATE_HASH, system_of(kind), base_instruction(kind)]
    texts += [revision_instruction(a, kind) for a in (REFLECT, CONSULT, "full")]
    return hashlib.sha256(json.dumps(texts).encode()).hexdigest()[:16]


class SelfOrSocialConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: Literal["self_or_social"]
    name: str
    tasks: str  # task JSONL (data/external/bbeh_all.jsonl; data/external/evidence/math.jsonl for math)
    items: str  # id list, one id per line: the run's items, in order
    team: list[Agent]
    task_kind: TaskKind = "bbeh"  # the prompts, parser and grader of every call (protocol.py)
    vendor: str | None = None  # the one account this run calls; set it only for a team that mixes vendors (docstring)
    reuse_first: list[str] = []  # panel calls.csv files whose first answers are reused (no call is made)
    branches: bool = True  # every reflect and consult revision
    full_review: bool = False  # every member reads both others and revises (the full-review control)
    first_answers_only: bool = False  # stage 1 of a new mixed-vendor team: only this vendor's first answers (docstring)
    single_member: bool = False  # allow a one-member team: first answers alone, or its own self-check (handoff study)
    parser: Literal["v1", "v2"] = "v2"  # evidence/prompts.parse_answer version, for first answers and revisions alike
    disjoint_from: list[str] = []  # id lists that must share no item id and no question text with `items`
    requires: list[str] = []  # files that must exist and be committed before a paid run (e.g. the frozen policy)
    prereg: Prereg | None = None
    phase: str = "evidence"  # the budget phase this run belongs to; a paid run refuses under any other active phase
    task_offset: int = 0
    task_limit: int | None = None
    model_override: str | None = None
    max_usd: float | None = None  # optional run cap for this config; None = only the phase and hard caps apply
    chunk_size: int = 10
    max_concurrency: int = 8
    expect: PanelExpect = PanelExpect()
    # Which calls the stop rules read after each chunk: "run" = this run's live calls (the default); "cumulative" =
    # every call of this config so far, all slices and replays, each counted as live (LAB-Bench Amendment 5)
    stop_scope: Literal["run", "cumulative"] = "run"
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

    @model_validator(mode="after")
    def _team_is_valid(self) -> "SelfOrSocialConfig":
        ids = [a.id for a in self.team]
        # one member only on request (single_member: true) and only where it is well defined: first answers alone, or
        # its own reflect (self-check) with no peers and no full review (research/handoff_completeness/prereg.md)
        least = 1 if self.single_member and (self.first_answers_only or not self.full_review) else 2
        if len(ids) < least or len(set(ids)) != len(ids) or any(":" in i or "|" in i or " " in i for i in ids):
            raise ValueError(f"a team needs at least {least} member(s) with distinct ids without ':', '|' or spaces; got {ids}")
        if not (self.branches or self.full_review or self.first_answers_only):
            raise ValueError("a run makes branches, full reviews or both (or only first answers: first_answers_only)")
        return self

    @classmethod
    def from_yaml(cls, path: str | Path) -> "SelfOrSocialConfig":
        return cls(**yaml.safe_load(Path(path).read_text()))

    def model_override_resolved(self) -> str | None:
        return self.model_override or os.getenv("AAN_MODEL_OVERRIDE")


def is_sos_config(path: str | Path) -> bool:
    raw = yaml.safe_load(Path(path).read_text())
    return isinstance(raw, dict) and raw.get("kind") == "self_or_social"


def select_items(cfg: SelfOrSocialConfig) -> list[Task]:
    """The run's items: the id list in its order, sliced by task_offset/task_limit."""
    by_id = {t.id: t for t in load_tasks(cfg.tasks)}
    ids = read_ids(cfg.items)
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise KeyError(f"{len(missing)} ids of {cfg.items} are not in {cfg.tasks}, e.g. {missing[0]}")
    ids = ids[cfg.task_offset:]
    ids = ids[: cfg.task_limit] if cfg.task_limit else ids
    return [by_id[i] for i in ids]


def question_hash(text: str) -> str:
    """The hash of a question's text with case and whitespace normalized, to catch one question under two ids."""
    return hashlib.sha256(" ".join(text.lower().split()).encode()).hexdigest()[:16]


def reused_outputs(paths: list[str], team: list[Agent], kind: str | None = None) -> dict[tuple[str, str], AgentOutput]:
    """(item, member id) -> the stored first reply of that member in earlier runs: a panel calls.csv row of its ref
    and call (source "<ref>:base"), or a self-or-social calls.csv row of its first answer (action "initial", the same
    receiver id and ref). With `kind`, only rows of that task kind are read (when the files record one), so a reply to
    another kind is never reused. A path that does not exist holds nothing."""
    frames = [pd.read_csv(p, dtype={"answer": str, "reply": str}) for p in paths if Path(p).exists()]
    if not frames:
        return {}
    calls = pd.concat(frames, ignore_index=True)
    if kind is not None and "task_kind" in calls:
        calls = calls[calls["task_kind"] == kind]
    out: dict[tuple[str, str], AgentOutput] = {}
    for agent in team:
        keep = pd.Series(False, index=calls.index)
        if "call" in calls:  # panel rows
            keep |= (calls["source"] == f"{agent.ref}:base") & (calls["call"] == agent.call)
        if "action" in calls:  # self-or-social rows
            keep |= (calls["action"] == "initial") & (calls["receiver"] == agent.id) & (calls["ref"] == agent.ref)
        for row in calls[keep].itertuples(index=False):
            usage = Usage(input_tokens=int(row.input_tokens), cache_write_tokens=int(row.cache_write_tokens),
                          cache_read_tokens=int(row.cache_read_tokens), output_tokens=int(row.output_tokens))
            out[(row.item, agent.id)] = AgentOutput(
                agent_id=f"{agent.ref}.base", content="" if pd.isna(row.reply) else str(row.reply), usage=usage,
                provider="reused", model=str(row.model_version), latency_s=float(row.seconds),
                stop_reason=None if pd.isna(row.stop_reason) else str(row.stop_reason), from_cache=True,
                cost_usd=float(row.cost_usd))
    return out


def reuse_paths(cfg: SelfOrSocialConfig) -> list[str]:
    """The reuse_first files this run reads: as written, except that a dry run reads a missing results/<x> file from
    runs/dry/<x> (where the dry run of the earlier stage wrote it; evidence/panel.dry_panel_results)."""
    if not is_free(cfg, ProviderRegistry.from_yaml(cfg.providers)):
        return list(cfg.reuse_first)
    return [p if Path(p).exists() or Path(p).parts[0] != "results" else dry_panel_results([p])[0] for p in cfg.reuse_first]


def reused_for(cfg: SelfOrSocialConfig) -> dict[tuple[str, str], AgentOutput]:
    """The run's reused first answers: reused_outputs of reuse_paths, for the config's team and task kind."""
    return reused_outputs(reuse_paths(cfg), cfg.team, cfg.task_kind)


def first_answer_readiness(cfg: SelfOrSocialConfig, cache: CallCache) -> pd.DataFrame:
    """Whether the run's first answers are already paid for, before any call (read only; nothing is written).

    One row per (item, member) of the run's slice, on the refs as written (no override):
      reused      the member's first reply is in a reuse_first calls.csv (source "<ref>:base", call = its `call`);
      key         the call cache key of the member's first-answer request (protocol.initial_request; market.caller's
                  cache_key, with the member's `call` as replicate), the key a live first answer would be looked up by;
      cached      the call cache holds that key (a live first answer would be free);
      same_reply  reused and cached, and the cached reply is the stored one word for word."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    reused = reused_outputs(cfg.reuse_first, cfg.team, cfg.task_kind)
    rows = []
    for item in select_items(cfg):
        for agent in cfg.team:
            key = cache_key(registry, initial_request(agent, item, agent.ref, cfg.task_kind), agent.call)
            hit, stored = cache.get(key), reused.get((item.id, agent.id))
            same = hit is not None and stored is not None and AgentOutput.model_validate_json(hit).content == stored.content
            rows.append({"item": item.id, "member": agent.id, "ref": agent.ref, "reused": stored is not None,
                         "key": key, "cached": hit is not None, "same_reply": same})
    return pd.DataFrame(rows, columns=["item", "member", "ref", "reused", "key", "cached", "same_reply"])


def vendor_of(cfg: SelfOrSocialConfig, registry: ProviderRegistry) -> str:
    """The one account this run calls: `vendor` when set (some member must bill it), else the account every member
    bills (checked on the refs as written, before any override)."""
    if cfg.vendor is not None:
        if not callers(cfg, registry):
            raise ValueError(f"no member of {cfg.name}'s team bills vendor {cfg.vendor!r}")
        return cfg.vendor
    accounts = sorted({registry.account_of(a.ref) for a in cfg.team})
    if len(accounts) != 1:
        raise ValueError(f"a run calls one vendor; {cfg.name} mixes {accounts}. Split it by vendor (set `vendor`, one "
                         "run per vendor).")
    return accounts[0]


def callers(cfg: SelfOrSocialConfig, registry: ProviderRegistry) -> list[Agent]:
    """The members this run calls: every member, or (with `vendor`) the members whose ref bills that vendor."""
    return [a for a in cfg.team if cfg.vendor is None or registry.account_of(a.ref) == cfg.vendor]


def unreused_others(cfg: SelfOrSocialConfig, registry: ProviderRegistry, items: list[Task],
                    reused: dict[tuple[str, str], AgentOutput]) -> list[tuple[str, str]]:
    """(item, member id) of each first answer this run needs but may not make: a member billed to another vendor
    (with `vendor`) whose first answer is not in `reuse_first`. A first-answers-only run needs none."""
    if cfg.first_answers_only:
        return []
    mine = {a.id for a in callers(cfg, registry)}
    return [(t.id, a.id) for t in items for a in cfg.team if a.id not in mine and (t.id, a.id) not in reused]


def item_problems(cfg: SelfOrSocialConfig) -> list[str]:
    """Checks before any call: one vendor (the other vendors' first answers all reused), items of the config's task
    kind (each task names the kind's grader), and no item (id or question text) shared with a `disjoint_from` list."""
    problems = []
    registry = ProviderRegistry.from_yaml(cfg.providers)
    try:
        vendor_of(cfg, registry)
    except ValueError as exc:
        problems.append(str(exc))
    if cfg.vendor is not None:
        missing = unreused_others(cfg, registry, select_items(cfg), reused_for(cfg))
        if missing:
            problems.append(f"{len(missing)} first answers of members billed to another vendor are not in reuse_first "
                            f"(a {cfg.vendor} run only reads them), e.g. {missing[0]}")
    graders = sorted({t.grader for t in select_items(cfg)} - {GRADER_OF[cfg.task_kind]})
    if graders:
        problems.append(f"task_kind {cfg.task_kind!r} needs items graded {GRADER_OF[cfg.task_kind]!r}; {cfg.tasks} has "
                        f"items graded {graders}")
    if cfg.disjoint_from:
        tasks = {t.id: t for t in load_tasks(cfg.tasks)}
        mine = read_ids(cfg.items)
        mine_hashes = {question_hash(tasks[i].prompt) for i in mine if i in tasks}
        for path in cfg.disjoint_from:
            other = read_ids(path)
            shared = sorted(set(mine) & set(other))
            if shared:
                problems.append(f"{len(shared)} items of {cfg.items} are also in {path}, e.g. {shared[0]}")
            same_text = [i for i in other if i in tasks and question_hash(tasks[i].prompt) in mine_hashes and i not in mine]
            if same_text:
                problems.append(f"{len(same_text)} items of {path} repeat a question of {cfg.items}, e.g. {same_text[0]}")
    return problems


def is_free(cfg: SelfOrSocialConfig, registry: ProviderRegistry) -> bool:
    override = cfg.model_override_resolved()
    return bool(override) and registry.provider_of(override) == "fake"


def planned_actions(cfg: SelfOrSocialConfig, receivers: set[str] | None = None):
    """(receiver, team position, action) of every revision the run makes (none in a first-answers-only run); with
    `receivers`, only theirs."""
    if cfg.first_answers_only:
        return []
    actions = branch_actions(cfg.team, cfg.full_review) if cfg.branches else \
        [(a, i, "full") for i, a in enumerate(cfg.team)]
    return [x for x in actions if receivers is None or x[0].id in receivers]


def estimate_sos(cfg: SelfOrSocialConfig) -> pd.DataFrame:
    """Worst case: every call the run would make (first answers not reused, every revision; with `vendor`, only that
    vendor's members' calls), with its prompt at the dearest input rate and the full max_tokens of output. A first
    reply not yet known is taken as max_tokens long, so the revisions that read it are upper bounds too. Cached calls
    are not subtracted."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    pricebook = PriceBook.from_yaml(cfg.pricing)
    override = cfg.model_override_resolved()
    model_of = {a.ref: override or a.ref for a in cfg.team}
    reused = reused_for(cfg)
    mine = {a.id for a in callers(cfg, registry)}
    kind = cfg.task_kind
    rows = []

    def add(request):
        ref = request.spec.model
        model, provider = registry.model_id(ref), registry.provider_of(ref)
        rows.append({"account": registry.account_of(ref), "model": model, "worst_case_usd": pricebook.worst_case_usd(
            model, provider, estimate_tokens(prompt_text(request.spec, request.input)), request.spec.max_tokens)})

    for item in select_items(cfg):
        snapshot = {}
        for agent in cfg.team:
            hit = reused.get((item.id, agent.id))
            if hit is None and agent.id in mine:  # a first answer this run makes
                add(initial_request(agent, item, model_of[agent.ref], kind))
            snapshot[agent.id] = hit.content if hit is not None else "x" * (4 * agent.max_tokens)
        for agent, i, action in planned_actions(cfg, mine):
            add(revision_request(agent, i, action, item, snapshot, model_of[agent.ref], kind))
    if not rows:
        return pd.DataFrame(columns=["calls", "worst_case_usd", "worst_case_x_safety"],
                            index=pd.MultiIndex.from_tuples([], names=["account", "model"]))
    table = pd.DataFrame(rows).groupby(["account", "model"]).agg(calls=("worst_case_usd", "size"),
                                                                worst_case_usd=("worst_case_usd", "sum"))
    table["worst_case_x_safety"] = table["worst_case_usd"] * BudgetRules.from_yaml(cfg.budget).safety_multiplier
    return table


def preflight_sos(cfg: SelfOrSocialConfig, config_path: str | Path) -> tuple[list[str], pd.DataFrame | None]:
    if is_free(cfg, ProviderRegistry.from_yaml(cfg.providers)):
        return item_problems(cfg), None
    problems = item_problems(cfg)
    active = BudgetRules.from_yaml(cfg.budget).phase
    if active != cfg.phase:
        problems.append(f"this run belongs to budget phase {cfg.phase!r} but the active phase is {active!r}: "
                        "stop and ask Kevin (only he changes the budget rules)")
    problems += [f"{p} must exist and be committed before this run" for p in uncommitted(cfg.requires + cfg.reuse_first
                                                                                         + [cfg.items] + cfg.disjoint_from)]
    table = estimate_sos(cfg)
    return problems + gate_problems(cfg, config_path, table), table


def call_row(item: Task, position: int, agent: Agent, action: str, out: AgentOutput, parser: str,
             request_hash: str | None, kind: str = "bbeh") -> dict:
    graded = grade_reply(kind, item, out.content or "", out.stop_reason, parser=parser)
    phase = "initial" if action == "initial" else "full" if action == "full" else "branch"
    return {
        "item": item.id, "family": item.meta.get("task"), "grader": item.grader, "position": position,
        "receiver": agent.id, "ref": agent.ref, "action": action, "sender": peer_of(action), "phase": phase,
        "source": f"{agent.id}:{phase}", "task_kind": kind, "parser": parser, **graded,
        "format_ok": format_ok(kind, out.content or ""),
        "input_tokens": out.usage.input_tokens, "cache_write_tokens": out.usage.cache_write_tokens,
        "cache_read_tokens": out.usage.cache_read_tokens, "output_tokens": out.usage.output_tokens,
        "thinking_tokens": out.usage.thinking_tokens, "cost_usd": out.cost_usd, "seconds": out.latency_s,
        "model_version": out.model, "stop_reason": out.stop_reason,
        "truncated": out.stop_reason in TRUNCATED_STOP_REASONS, "from_cache": out.from_cache,
        "reused": out.provider == "reused", "prompt_hash": request_hash, "template_hash": template_hash(kind),
        "reply": out.content,
    }


def judged_calls(rows: list[dict], table: pd.DataFrame, scope: str) -> pd.DataFrame:
    """The calls the stop rules read after a chunk. scope "run": this run's calls (expectation_misses keeps the live
    ones). scope "cumulative" (LAB-Bench Amendment 5): `table`, every call of this config so far (earlier slices,
    replays of a failed attempt and this run), each counted as live, so a run cut into slices is judged as one
    uninterrupted run would be."""
    if scope == "cumulative" and not table.empty:
        return table.assign(from_cache=False)
    return pd.DataFrame(rows)


def merge_write(path: Path, new: pd.DataFrame) -> pd.DataFrame:
    """Write `new`, keeping rows already in the file whose (item, receiver, action) `new` does not cover."""
    if path.exists() and path.stat().st_size > 0 and not new.empty:
        old = pd.read_csv(path, dtype={"answer": str, "reply": str})
        old = old[~old.set_index(KEYS).index.isin(new.set_index(KEYS).index)]
        new = pd.concat([old, new], ignore_index=True)
    if not new.empty:
        new = new.sort_values(["item", "position", "phase", "action"], kind="stable")
        new.to_csv(path, index=False)
    return new


def request_hash(request) -> str:
    return hashlib.sha256(request.model_dump_json().encode()).hexdigest()[:16]


class FakeSosClient(FakeClient):
    """The fake model of a dry run: FakeClient's reply, except that on an mcq request (MCQ_SYSTEM) a numeric answer
    becomes an option letter (0 -> A, 1 -> B, ...), so an mcq dry run parses. bbeh and math replies are FakeClient's."""

    def _answer(self, request, digest: str) -> str:
        answer = super()._answer(request, digest)
        return "ABCD"[int(answer) % 4] if request.system == MCQ_SYSTEM and answer.isdigit() else answer


async def run_sos(cfg: SelfOrSocialConfig) -> tuple[pd.DataFrame, dict]:
    """Make the run's slice of items. Returns (this run's rows, status)."""
    registry = ProviderRegistry.from_yaml(cfg.providers)
    vendor = vendor_of(cfg, registry)
    run_id = f"{cfg.name}-{int(time.time())}"
    override = cfg.model_override_resolved()
    free = is_free(cfg, registry)
    if free:  # nothing is spent, so nothing tracked is touched; dry runs go to runs/dry
        out_dir = "runs/dry" if cfg.out_dir == "results" else cfg.out_dir
        cfg = cfg.model_copy(update={"git_checkpoint": False, "out_dir": out_dir})
        ledger, cache = Ledger(), CallCache()
        registry.set_client(override, FakeSosClient())
    else:
        ledger = Ledger(cfg.ledger, must_exist=cfg.require_ledger)
        cache = CallCache(cfg.cache, shard_prefix=run_id)
    governor = SpendGovernor(ledger, BudgetRules.from_yaml(cfg.budget), run_cap_usd=cfg.max_usd)
    runtime = LocalRuntime(registry) if cfg.runtime == "local" else MaritimeRuntime.from_yaml(cfg.maritime)
    caller = MarketCaller(runtime, registry, pricebook=PriceBook.from_yaml(cfg.pricing), cache=cache, governor=governor,
                          run_id=run_id, market=cfg.name, condition="self_or_social", purpose="self_or_social")
    out = Path(cfg.out_dir) / cfg.name
    out.mkdir(parents=True, exist_ok=True)
    items = select_items(cfg)
    kind = cfg.task_kind
    model_of = {a.ref: override or a.ref for a in cfg.team}
    reused = reused_for(cfg)
    calling = {a.id for a in callers(cfg, registry)}
    missing = unreused_others(cfg, registry, items, reused)
    if missing:  # never call another vendor's member: its first answer must come from reuse_first
        raise ValueError(f"{len(missing)} first answers of members billed to another vendor are not reused, e.g. {missing[0]}")
    answering = [a for a in cfg.team if a.id in calling] if cfg.first_answers_only else cfg.team  # whose first answers
    position = {a.id: i for i, a in enumerate(cfg.team)}
    status = {"run_id": run_id, "state": "completed", "reason": "", "vendor": vendor, "task_kind": kind,
              "items": [cfg.task_offset, cfg.task_offset + len(items)], "team": [a.model_dump() for a in cfg.team],
              "receivers": [a.id for a in cfg.team if a.id in calling], "first_answers_only": cfg.first_answers_only,
              "branches": cfg.branches, "full_review": cfg.full_review, "template_hash": template_hash(kind),
              "code": code_version(), "checkpoints": []}
    rows: list[dict] = []
    gate = asyncio.Semaphore(cfg.max_concurrency)

    async def governed(request, replicate):
        async with gate:
            return await caller.call(request, replicate=replicate)

    async def do_item(item: Task) -> tuple[list[dict], list[BaseException]]:
        mine = {a.id: reused[(item.id, a.id)] for a in answering if (item.id, a.id) in reused}
        try:
            replies = await first_replies(governed, answering, item, model_of, mine, kind)
        except BaseException as exc:  # a failed first answer: no revision of this item is made
            return [], [exc]
        item_rows = []
        for agent in answering:
            req = None if agent.id in mine else initial_request(agent, item, model_of[agent.ref], kind)
            item_rows.append(call_row(item, position[agent.id], agent, "initial", replies[agent.id], cfg.parser,
                                      request_hash(req) if req is not None else None, kind))
        snapshot = {k: v.content or "" for k, v in replies.items()}
        done = await revisions(governed, item, replies, model_of, planned_actions(cfg, calling), kind)
        errors = []
        for agent, action, output in done:
            if isinstance(output, BaseException):
                errors.append(output)
                continue
            req = revision_request(agent, position[agent.id], action, item, snapshot, model_of[agent.ref], kind)
            item_rows.append(call_row(item, position[agent.id], agent, action, output, cfg.parser, request_hash(req),
                                      kind))
        return item_rows, errors

    try:
        for first in range(0, len(items), cfg.chunk_size):
            chunk = items[first: first + cfg.chunk_size]
            outcomes = await asyncio.gather(*(do_item(t) for t in chunk))
            errors = []
            for item_rows, item_errors in outcomes:
                rows += item_rows
                errors += item_errors
            cache.rotate()
            if cfg.git_checkpoint:
                status["checkpoints"].append(git_checkpoint(
                    [cfg.ledger, cfg.cache], f"state: {run_id} items {cfg.task_offset + first}-{cfg.task_offset + first + len(chunk) - 1}"))
            table = merge_write(out / "calls.csv", pd.DataFrame(rows))
            budget_errors = [e for e in errors if isinstance(e, BudgetExceeded)]
            if budget_errors:
                status.update(state="stopped", reason=f"budget: {budget_errors[0]}")
                break
            if errors:
                status.update(state="failed", reason=f"{type(errors[0]).__name__}: {errors[0]}")
                break
            misses = expectation_misses(judged_calls(rows, table, cfg.stop_scope), cfg.expect)
            if misses:
                status.update(state="stopped", reason="expectation missed: " + "; ".join(misses))
                break
    finally:
        await runtime.aclose()
        frame = pd.DataFrame(rows)
        status["calls"] = len(rows)
        status["live_calls"] = caller.live_calls
        if not frame.empty:
            live = frame[~frame["from_cache"].astype(bool)]
            status["new_spend_usd"] = round(float(live["cost_usd"].sum()), 5)
            status["logical_cost_usd"] = round(float(frame["cost_usd"].sum()), 5)
            status["by_source"] = frame.groupby("source").agg(
                calls=("parsed", "size"), parsed=("parsed", "mean"), truncated=("truncated", "mean"),
                usd=("cost_usd", "sum"), live=("from_cache", lambda x: int((~x.astype(bool)).sum()))).round(5).to_dict("index")
        status["budget"] = governor.status()
        status["rate_limits"] = registry.rate_limits()
        (out / "status.json").write_text(json.dumps(status, indent=2, default=str))
    return pd.DataFrame(rows), status
