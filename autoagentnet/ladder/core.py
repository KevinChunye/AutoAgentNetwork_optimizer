"""Data-source ladders (research/v3/program.md, "Data-source ladder protocol").

Each workstream ranks its data sources best first; one source is a "rung". A session tests the
rungs top-down and uses the first that passes every check. probe() runs the free checks on one
rung, in order, and stops at the first failure:

  1 reachable   the download works from this session; a blocked host is recorded by name
  2 licensed    the licence allows research use, and gated terms are accepted (HF_TOKEN present)
  3 gradable    golds pass the plan's filter, the grader matches every gold against itself (100%),
                and ten golds are set aside for a hand check
  4 big enough  at least the rung's minimum number of items after the filter
  5 fresh       at least the minimum number of items dated after the model's training cutoff,
                or the source carries a canary string (then every item counts as fresh)

Check 6 (in band: one Haiku call scores inside the target band on 20 calibration items x 5
samples) costs money, so it runs only through `aan run` with a prereg, never from here.

Software rungs (W3 part b, W4) have their own four checks: reachable, licensed, installs, and a
2-agent offline smoke test that drives one agent through our caller.

Every result is an Evidence record: which checks passed, the one that failed, and why (blocked
host, HTTP status, licence text, item count, date range, grader self-check). run_ladder() never
falls through silently: every rung it tries leaves a record.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import date
from typing import Callable
from urllib.parse import urlparse

import httpx
import pandas as pd

from ..tasks import answers_match

DATA_CHECKS = ("reachable", "licensed", "gradable", "big enough", "fresh")
SOFTWARE_CHECKS = ("reachable", "licensed", "installs", "smoke test")
HAND_CHECK_SIZE = 10

# Licences that allow research use. Non-commercial (NC) licences allow it too: this is research.
RESEARCH_LICENCES = {
    "mit", "apache-2.0", "bsd-2-clause", "bsd-3-clause", "cc0-1.0", "cc-by-4.0", "cc-by-sa-4.0",
    "cc-by-nc-4.0", "cc-by-nc-sa-4.0", "cc-by-nc-nd-4.0", "odc-by", "public domain",
    "project code",  # code in this repository (W3b rung 3, W4 rungs 2-3)
}


class Unreachable(Exception):
    """Check 1 failed: the host is blocked, or the download answered with an HTTP error."""

    def __init__(self, host: str, status: int | None, message: str):
        super().__init__(f"{host}: HTTP {status}: {message}" if status else f"{host}: {message}")
        self.host, self.status, self.message = host, status, message


class GatedRefused(Exception):
    """Check 2 failed: the source is gated and no token is set, or the token is not authorized."""

    def __init__(self, host: str, status: int | None, message: str):
        super().__init__(f"{host}: HTTP {status}: {message}" if status else f"{host}: {message}")
        self.host, self.status, self.message = host, status, message


class CheckFailed(Exception):
    """A software check (installs, smoke test) failed; the message is the evidence."""


class Net:
    """HTTP downloads that classify failures for check 1 and check 2. Tests replace it with a fake.

    A request that never gets an answer (DNS, proxy refusal, timeout) or answers 403 from the
    session's GitHub scope is a blocked host. A 401 or 403 from Hugging Face on a gated dataset is
    a refused licence gate. Any other HTTP error is an unreachable download with its status."""

    def __init__(self, hf_token: str | None = None, timeout: float = 120, retry_wait_s: float = 20):
        self.hf_token = hf_token
        self.timeout = timeout
        self.retry_wait_s = retry_wait_s  # one retry after an HTTP 429 (rate limit), then it counts

    def get(self, url: str, gated: bool = False, params: dict | None = None) -> httpx.Response:
        host = urlparse(url).hostname or url
        headers = {}
        if self.hf_token and host.endswith("huggingface.co"):
            headers["Authorization"] = f"Bearer {self.hf_token}"
        for attempt in range(2):
            try:
                response = httpx.get(url, params=params, headers=headers, timeout=self.timeout, follow_redirects=True)
            except httpx.HTTPError as error:
                raise Unreachable(host, None, f"blocked or no answer ({type(error).__name__}: {error})") from error
            if response.status_code != 429 or attempt == 1:
                break
            time.sleep(self.retry_wait_s)
        if response.status_code == 200:
            return response
        message = response.text[:300].replace("\n", " ")
        if gated and response.status_code in (401, 403):
            raise GatedRefused(host, response.status_code, message)
        raise Unreachable(host, response.status_code, message)

    def json(self, url: str, gated: bool = False, params: dict | None = None):
        return self.get(url, gated, params).json()

    def content(self, url: str, gated: bool = False) -> bytes:
        return self.get(url, gated).content


@dataclass
class Pull:
    """What a data loader returns.

    items    one row per item after download, before the plan's filter. Columns: id, answer
             (the gold, as text), date (when the item was published or resolved, a datetime.date
             or None), plus any source fields the filter needs.
    licence  the licence as the source states it (an SPDX-style id when there is one), or ""
    version  the dataset revision, release date or commit, so a rebuild can be checked
    canary   the source's canary string, when it carries one
    notes    anything the record should show (set names, revisions, excluded parts)
    """

    items: pd.DataFrame
    licence: str
    version: str
    canary: str | None = None
    notes: list[str] = field(default_factory=list)


@dataclass
class Rung:
    """One data source on a workstream's ladder.

    workstream  "W1", "W2-B", ...
    rank        1 is the plan's first choice
    name, link  how the record names the source
    loader      downloads the items: loader(net) -> Pull; raises Unreachable or GatedRefused
    licence     the licence the plan expects (the record shows what the source states)
    min_items   the workstream's minimum item count after the filter (checks 4 and 5)
    fresh_after an item is fresh when its date is after this day (the model's training cutoff)
    band        target band for check 6, as fractions (low, high), or None when the plan sets none
    grader      how answers are checked: a tasks.Grader name, or "binary" for 0/1 outcomes
    item_filter the plan's filter on golds (returns the kept rows); None keeps every row
    licence_ok  a verdict for sources whose terms are not a standard licence (API terms of
                use), read by hand and cited in research/lit/v3_sources.md; None means "decide
                from the stated licence id"
    """

    workstream: str
    rank: int
    name: str
    link: str
    loader: Callable[[Net], Pull]
    licence: str
    min_items: int
    fresh_after: date
    band: tuple[float, float] | None = None
    grader: str = "exact"
    item_filter: Callable[[pd.DataFrame], pd.DataFrame] | None = None
    licence_ok: tuple[bool, str] | None = None


@dataclass
class SoftwareRung:
    """One implementation on a software ladder (W3 part b, W4).

    fetch    clones or downloads the code: fetch() -> (licence text or id, version); raises
             Unreachable when the host is blocked
    install  installs it in a scratch environment; returns a short note or raises CheckFailed
    smoke    runs the 2-agent offline smoke test with one agent driven by our caller (the fake
             provider); returns a short note or raises CheckFailed
    """

    workstream: str
    rank: int
    name: str
    link: str
    licence: str
    fetch: Callable[[], tuple[str, str]]
    install: Callable[[], str]
    smoke: Callable[[], str]


@dataclass
class Evidence:
    workstream: str
    rank: int
    name: str
    link: str
    passed: list[str] = field(default_factory=list)
    failed: str | None = None
    detail: str = ""  # why the failed check failed, in words
    licence: str = ""
    version: str = ""
    blocked_host: str | None = None
    http_status: int | None = None
    n_items: int | None = None
    n_fresh: int | None = None
    date_range: str = ""
    self_check: str = ""
    hand_check_ids: list[str] = field(default_factory=list)
    hand_check_golds: list[str] = field(default_factory=list)
    canary: str | None = None
    notes: list[str] = field(default_factory=list)
    chosen: bool = False

    @property
    def ok(self) -> bool:
        return self.failed is None


def licence_verdict(stated: str, override: tuple[bool, str] | None = None) -> tuple[bool, str]:
    """Does the licence allow research use? An unstated or unknown licence does not. A source made
    of several parts ("cc-by-nc-sa-4.0 / cc-by-sa-4.0") needs every part to allow it."""
    if override is not None:
        return override
    parts = [part.strip().lower() for part in (stated or "").split(" / ") if part.strip()]
    if not parts:
        return False, "no licence stated on the source"
    refused = [part for part in parts if part not in RESEARCH_LICENCES]
    if refused:
        return False, f"licence '{' / '.join(refused)}' is not on the research-use list"
    return True, f"{stated} allows research use"


def date_range(dates: pd.Series) -> str:
    known = dates.dropna()
    if known.empty:
        return "no dates"
    return f"{min(known)} to {max(known)}"


def _fail(ev: Evidence, check: str, detail: str) -> Evidence:
    ev.failed, ev.detail = check, detail
    return ev


def self_matches(answer: str, grader: str) -> bool:
    """The grader accepts the gold as an answer to itself (check 3)."""
    if grader == "binary":
        return str(answer) in ("0", "1")
    return answers_match(str(answer), str(answer), grader)


def probe(rung: Rung | SoftwareRung, net: Net | None = None) -> Evidence:
    """Run the free checks on one rung, in order, and stop at the first failure."""
    if isinstance(rung, SoftwareRung):
        return probe_software(rung)
    net = net or Net(os.environ.get("HF_TOKEN"))
    ev = Evidence(rung.workstream, rung.rank, rung.name, rung.link)

    # 1 reachable (and 2, when a licence gate refuses the download)
    try:
        pull = rung.loader(net)
    except Unreachable as error:
        ev.blocked_host, ev.http_status = error.host, error.status
        return _fail(ev, "reachable", str(error))
    except GatedRefused as error:
        ev.passed.append("reachable")
        ev.blocked_host, ev.http_status = None, error.status
        return _fail(ev, "licensed", f"gated: {error}")
    except Exception as error:  # a download that arrives but cannot be read is recorded, never a crash (audit 38)
        return _fail(ev, "reachable", f"download unusable: {type(error).__name__}: {error}")
    ev.passed.append("reachable")
    ev.licence, ev.version, ev.canary, ev.notes = pull.licence, pull.version, pull.canary, list(pull.notes)
    items = pull.items
    ev.date_range = date_range(items["date"]) if "date" in items else "no dates"

    # 2 licensed
    allowed, why = licence_verdict(pull.licence, rung.licence_ok)
    if not allowed:
        return _fail(ev, "licensed", why)
    ev.passed.append("licensed")

    # 3 gradable
    try:
        kept = rung.item_filter(items) if rung.item_filter else items
        kept = kept[kept["answer"].notna()]
    except Exception as error:
        return _fail(ev, "gradable", f"the plan's filter failed on the download: {type(error).__name__}: {error}")
    if kept.empty:
        ev.n_items = 0
        return _fail(ev, "gradable", f"no item has a gold the plan's filter keeps ({len(items)} downloaded)")
    matches = kept["answer"].map(lambda a: self_matches(a, rung.grader))
    ev.self_check = f"{int(matches.sum())}/{len(kept)} golds match themselves under the {rung.grader} grader"
    if not matches.all():
        bad = kept.loc[~matches, "id"].head(5).tolist()
        return _fail(ev, "gradable", f"{ev.self_check}; first misses: {bad}")
    # ten golds for the hand check, drawn from the items the workstream would use (fresh ones when the
    # source has no canary), with a fixed seed so the record can be re-drawn
    fresh = kept["date"].map(lambda d: d is not None and not pd.isna(d) and d > rung.fresh_after)
    pool = kept if pull.canary or fresh.sum() < HAND_CHECK_SIZE else kept[fresh]
    sample = pool.sample(n=min(HAND_CHECK_SIZE, len(pool)), random_state=0)
    ev.hand_check_ids = sample["id"].astype(str).tolist()
    ev.hand_check_golds = sample["answer"].astype(str).tolist()
    ev.passed.append("gradable")

    # 4 big enough
    ev.n_items = len(kept)
    if len(kept) < rung.min_items:
        return _fail(ev, "big enough", f"{len(kept)} items after the filter; the minimum is {rung.min_items}")
    ev.passed.append("big enough")

    # 5 fresh
    if pull.canary:
        ev.n_fresh = len(kept)
        ev.passed.append("fresh")
        ev.notes.append(f"fresh by canary (items dated {ev.date_range}, cutoff {rung.fresh_after})")
        return ev
    ev.n_fresh = int(fresh.sum())
    fresh_dates = kept.loc[fresh, "date"]
    if ev.n_fresh < rung.min_items:
        return _fail(ev, "fresh", f"{ev.n_fresh} of {len(kept)} items dated after the cutoff {rung.fresh_after} "
                                  f"(items dated {ev.date_range}); the minimum is {rung.min_items}; no canary")
    ev.notes.append(f"{ev.n_fresh} fresh items dated {date_range(fresh_dates)}")
    ev.passed.append("fresh")
    return ev


def probe_software(rung: SoftwareRung) -> Evidence:
    ev = Evidence(rung.workstream, rung.rank, rung.name, rung.link)
    try:
        licence, ev.version = rung.fetch()
    except Unreachable as error:
        ev.blocked_host, ev.http_status = error.host, error.status
        return _fail(ev, "reachable", str(error))
    except CheckFailed as error:
        return _fail(ev, "reachable", str(error))
    ev.passed.append("reachable")
    ev.licence = licence
    allowed, why = licence_verdict(licence)
    if not allowed:
        return _fail(ev, "licensed", why)
    ev.passed.append("licensed")
    for check, step in (("installs", rung.install), ("smoke test", rung.smoke)):
        try:
            ev.notes.append(f"{check}: {step()}")
        except CheckFailed as error:
            return _fail(ev, check, str(error))
        ev.passed.append(check)
    return ev


@dataclass
class LadderResult:
    workstream: str
    evidence: list[Evidence]
    chosen: Evidence | None

    @property
    def skipped(self) -> bool:
        return self.chosen is None

    def summary(self) -> str:
        if self.chosen is None:
            return f"{self.workstream}: every rung failed, so the workstream is skipped"
        return f"{self.workstream}: rung {self.chosen.rank} ({self.chosen.name}) passed every free check"


def run_ladder(rungs: list, net: Net | None = None, probe_all: bool = False) -> LadderResult:
    """Probe rungs top-down. The first rung that passes is chosen; a data ladder may probe the rest
    too (probe_all), because check 6 can still fail the chosen rung and the next passing rung is
    then band-checked. Every rung tried leaves an Evidence record."""
    ordered = sorted(rungs, key=lambda r: r.rank)
    evidence, chosen = [], None
    for rung in ordered:
        if chosen is not None and not probe_all:
            break
        ev = probe(rung, net)
        evidence.append(ev)
        if ev.ok and chosen is None:
            ev.chosen = True
            chosen = ev
    workstream = ordered[0].workstream if ordered else "?"
    return LadderResult(workstream, evidence, chosen)


def evidence_table(results: list[LadderResult]) -> pd.DataFrame:
    """One row per rung tried, in the columns research/v3/data_sources.md uses."""
    rows = []
    for result in results:
        for ev in result.evidence:
            facts = []
            if ev.blocked_host:
                facts.append(f"host {ev.blocked_host}" + (f" HTTP {ev.http_status}" if ev.http_status else ""))
            if ev.n_items is not None:
                facts.append(f"{ev.n_items} items")
            if ev.n_fresh is not None:
                facts.append(f"{ev.n_fresh} fresh")
            if ev.date_range and ev.date_range != "no dates":
                facts.append(f"dated {ev.date_range}")
            if ev.self_check:
                facts.append(ev.self_check)
            rows.append({
                "workstream": ev.workstream, "rung": ev.rank, "source": f"[{ev.name}]({ev.link})",
                "version": ev.version, "licence": ev.licence or "-",
                "checks passed": ", ".join(ev.passed) or "none", "failed check": ev.failed or "-",
                "evidence": "; ".join(([ev.detail] if ev.detail else []) + facts + ev.notes),
                "chosen": "yes" if ev.chosen else "no",
            })
    table = pd.DataFrame(rows)
    return table.sort_values(["workstream", "rung"]) if not table.empty else table


def markdown_table(table: pd.DataFrame) -> str:
    """A GitHub markdown table (pandas' to_markdown needs the tabulate package, which we do not use)."""
    def cell(value) -> str:
        return str(value).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(table.columns) + " |", "|" + " --- |" * len(table.columns)]
    lines += ["| " + " | ".join(cell(v) for v in row) + " |" for row in table.itertuples(index=False)]
    return "\n".join(lines)
