"""The spend governor, the persistent ledger and cache, and the budget tripwires."""

import asyncio
import gzip
import re
from pathlib import Path

import pytest
import yaml

from autoagentnet.budget import BudgetExceeded, BudgetRules, Phase, SpendGovernor, effective_run_cap
from autoagentnet.cache import CallCache
from autoagentnet.meter import CallRecord, Ledger, LedgerMissing
from autoagentnet.pricing import Price, PriceBook
from conftest import ROOT, make_executor

# A priced fake model: free to run, but the governor sees real-looking costs.
PRICED = PriceBook({"fake-model": Price(input=100.0, output=500.0)})


def rules(cap: float, phase_total: float | None = None, run_cap: float = 1e9) -> BudgetRules:
    phases = {"p": Phase(total_usd=phase_total, max_run_usd=run_cap)} if phase_total else {}
    return BudgetRules(hard_caps_usd={"fake": cap}, safety_multiplier=1.15,
                       phase="p" if phase_total else None, phases=phases)


def test_hard_cap_holds_even_with_parallel_calls(network, registry, fake, tasks):
    ledger = Ledger()
    governor = SpendGovernor(ledger, rules(cap=3.0))
    executor = make_executor(network, registry, pricebook=PRICED, governor=governor, max_concurrency=8)
    with pytest.raises(BudgetExceeded, match="hard cap"):
        asyncio.run(executor.run(tasks[0]))
    assert 0 < ledger.spent_usd("fake") and ledger.spent_usd("fake") * 1.15 <= 3.0


def test_phase_cap_and_run_cap(network, registry, fake, tasks):
    phase_limited = SpendGovernor(Ledger(), rules(cap=1e6, phase_total=2.0))
    with pytest.raises(BudgetExceeded, match="phase"):
        asyncio.run(make_executor(network, registry, pricebook=PRICED, governor=phase_limited).run(tasks[0]))
    run_limited = SpendGovernor(Ledger(), rules(cap=1e6), run_cap_usd=1.0)
    with pytest.raises(BudgetExceeded, match="run cap"):
        asyncio.run(make_executor(network, registry, pricebook=PRICED, governor=run_limited).run(tasks[0]))


def test_paid_calls_need_a_capped_account_and_a_governor(network, registry, fake, tasks):
    registry.models["fake"] = registry.config("fake").model_copy(update={"account": "uncapped"})
    governor = SpendGovernor(Ledger(), rules(cap=100))
    with pytest.raises(BudgetExceeded, match="no hard cap"):
        asyncio.run(make_executor(network, registry, pricebook=PRICED, governor=governor).run(tasks[0]))
    with pytest.raises(RuntimeError, match="without a spend governor"):
        asyncio.run(make_executor(network, registry, pricebook=PRICED).run(tasks[0]))
    assert fake.calls == 0


def test_ledger_fails_closed_and_survives_restarts(tmp_path):
    with pytest.raises(LedgerMissing):
        Ledger(tmp_path / "ledger.jsonl", must_exist=True)
    path = tmp_path / "ledger.jsonl"
    path.touch()
    governor = SpendGovernor(Ledger(path, must_exist=True), rules(cap=100))
    from autoagentnet.meter import CallRecord

    record = CallRecord(run_id="r", account="fake", provider="x", model="m", input_tokens=1,
                        cache_write_tokens=0, cache_read_tokens=0, output_tokens=1, cost_usd=0.5, latency_s=0.1)
    governor.settle(governor.reserve("fake", 0.6), record)
    assert Ledger(path, must_exist=True).spent_usd("fake") == pytest.approx(0.5)


def test_cache_shards_persist_and_compress(tmp_path):
    cache = CallCache(tmp_path / "cache", shard_prefix="run1")
    cache.put("a", "1")
    cache.rotate()
    cache.put("b", "2")  # left uncompressed, as after a crash
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == ["run1-000.jsonl.gz", "run1-001.jsonl"]
    with gzip.open(tmp_path / "cache" / "run1-000.jsonl.gz", "rt") as f:
        assert '"key": "a"' in f.read()
    reloaded = CallCache(tmp_path / "cache")
    assert reloaded.get("a") == "1" and reloaded.get("b") == "2"


def test_budget_file_tripwire():
    """Fails if a hard cap changes without this test changing too, or if a billed account is added.
    Kevin set Anthropic to $275 and kept OpenAI at $100 on 2026-10-31 for his new $150 / $50 credit."""
    raw = yaml.safe_load((ROOT / "configs/budget.yaml").read_text())
    budget = BudgetRules(**raw)
    assert budget.hard_caps_usd == {"anthropic": 275, "openai": 100}
    assert budget.safety_multiplier >= 1.1
    assert budget.active_phase is not None
    assert budget.active_phase.total_usd <= sum(budget.hard_caps_usd.values())
    assert budget.active_phase.max_run_usd <= budget.active_phase.total_usd
    for account, cap in budget.active_phase.account_caps_usd.items():  # an account cap never lifts a hard cap
        assert account in budget.hard_caps_usd and cap <= budget.hard_caps_usd[account]


def test_account_cap_of_the_phase_holds_per_vendor():
    """A phase may cap each account's lifetime spend below its hard cap (step 0.2 of the evidence plan):
    a call is refused when (account spend + reserved + worst case) x 1.15 passes the account cap,
    while another account keeps spending."""
    phase = Phase(total_usd=1e6, max_run_usd=1e6, account_caps_usd={"anthropic": 10.0})
    budget = BudgetRules(hard_caps_usd={"anthropic": 100, "openai": 100}, safety_multiplier=1.15,
                         phase="evidence", phases={"evidence": phase})
    governor = SpendGovernor(Ledger(), budget)
    first = governor.reserve("anthropic", 8.0)  # 8 x 1.15 = 9.2 fits under 10
    with pytest.raises(BudgetExceeded, match="account cap"):
        governor.reserve("anthropic", 0.8)  # (8 + 0.8) x 1.15 = 10.12 does not
    governor.reserve("openai", 50.0)  # no account cap: only the hard cap applies
    governor.release(first)
    governor.reserve("anthropic", 0.8)
    status = governor.status()
    assert status["account_caps_usd"] == {"anthropic": 10.0}
    assert status["room_by_account_usd"]["anthropic"] == pytest.approx(10 / 1.15, abs=1e-3)
    assert status["room_by_account_usd"]["openai"] == pytest.approx(100 / 1.15, abs=1e-3)


def test_account_cap_counts_lifetime_spend_in_the_ledger():
    ledger = Ledger()
    ledger.record(CallRecord(run_id="r", account="openai", provider="openai_compat", model="m", input_tokens=0,
                             cache_write_tokens=0, cache_read_tokens=0, output_tokens=0, cost_usd=5.0, latency_s=0))
    phase = Phase(total_usd=1e6, max_run_usd=1e6, account_caps_usd={"openai": 7.0})
    governor = SpendGovernor(ledger, BudgetRules(hard_caps_usd={"openai": 100}, phase="e", phases={"e": phase}))
    governor.check("openai", 1.0)  # (5 + 1) x 1.15 = 6.9
    with pytest.raises(BudgetExceeded, match="account cap"):
        governor.check("openai", 1.1)  # (5 + 1.1) x 1.15 = 7.015


def test_vendor_sdks_only_in_providers():
    """Every paid call must pass through the governed provider layer."""
    pattern = re.compile(r"^\s*(import|from)\s+(anthropic|openai)\b", re.MULTILINE)
    offenders = [
        str(path.relative_to(ROOT))
        for folder in ("autoagentnet", "scripts")
        for path in (ROOT / folder).rglob("*.py")
        if "providers" not in path.parts and pattern.search(path.read_text())
    ]
    assert offenders == []


def test_project_ledger_is_tracked_and_present():
    assert (ROOT / "state/ledger.jsonl").exists()
    assert "state" not in Path(ROOT / ".gitignore").read_text().split()


def test_effective_run_cap_skips_a_missing_config_cap():
    """A config's max_usd is optional (None = no cap of its own): the phase's max_run_usd then applies alone,
    a smaller config cap still wins, and with neither there is no run cap. The scripts that slice CD and
    anchor runs use this too, so a config without max_usd no longer raises TypeError there."""
    phased = BudgetRules(hard_caps_usd={"openai": 100}, phase="p", phases={"p": Phase(total_usd=50, max_run_usd=20)})
    assert effective_run_cap(phased, None) == 20
    assert effective_run_cap(phased, 4.0) == 4.0
    assert effective_run_cap(BudgetRules(hard_caps_usd={"openai": 100}), None) is None
    assert SpendGovernor(Ledger(), phased).run_cap_usd == 20
    for script in ("run_cd.py", "run_anchor.py", "anchor_slices.py"):
        assert "min(cfg.max_usd" not in (ROOT / "scripts" / script).read_text()


def _paid(cost: float, run_id: str = "r", account: str = "openai") -> CallRecord:
    return CallRecord(run_id=run_id, account=account, provider="openai_compat", model="m", input_tokens=0,
                      cache_write_tokens=0, cache_read_tokens=0, output_tokens=0, cost_usd=cost, latency_s=0)


def test_two_processes_on_one_ledger_see_each_others_spend(tmp_path):
    """Two paid processes share state/ledger.jsonl (Kevin, 2026-11-01). Each Ledger reads the other's appended
    lines before a governor check, never reads its own lines twice, and the file holds every record once."""
    path = tmp_path / "ledger.jsonl"
    path.write_text(_paid(1.0, "old").model_dump_json() + "\n")
    a, b = Ledger(path, must_exist=True), Ledger(path, must_exist=True)
    a.record(_paid(2.0, "a"))
    b.record(_paid(4.0, "b"))       # b reads a's line first, then appends its own
    assert b.spent_usd() == 7.0
    assert a.spent_usd() == 3.0     # a has not looked yet
    assert a.refresh() == 1 and a.spent_usd() == 7.0
    assert a.refresh() == 0 and b.refresh() == 0
    a.record(_paid(8.0, "a"))
    assert b.refresh() == 1 and a.spent_usd() == b.spent_usd() == 15.0
    assert Ledger(path, must_exist=True).spent_usd() == 15.0
    assert len(path.read_text().splitlines()) == 4
    phase = Phase(total_usd=1e6, max_run_usd=1e6, account_caps_usd={"openai": 20.0})
    rules = BudgetRules(hard_caps_usd={"openai": 100}, phase="e", phases={"e": phase})
    governor_a = SpendGovernor(a, rules)
    governor_a.check("openai", 2.0)            # (15 + 2) x 1.15 = 19.55 fits under 20
    b.record(_paid(1.0, "b"))                  # the other process spends
    with pytest.raises(BudgetExceeded, match="account cap"):
        governor_a.check("openai", 2.0)        # (16 + 2) x 1.15 = 20.7: refused because a saw b's spend


def test_ledger_reads_a_whole_record_without_its_newline_and_waits_for_a_partial_one(tmp_path):
    path = tmp_path / "ledger.jsonl"
    whole = _paid(1.0).model_dump_json()
    path.write_text(whole)                     # no trailing newline
    ledger = Ledger(path, must_exist=True)
    assert ledger.spent_usd() == 1.0
    ledger.record(_paid(2.0))
    assert [CallRecord.model_validate_json(x).cost_usd for x in path.read_text().splitlines()] == [1.0, 2.0]
    with path.open("a") as f:
        f.write(_paid(4.0).model_dump_json()[:20])   # another process mid-write
    assert ledger.refresh() == 0 and ledger.spent_usd() == 3.0
    with path.open("a") as f:
        f.write(_paid(4.0).model_dump_json()[20:] + "\n")
    assert ledger.refresh() == 1 and ledger.spent_usd() == 7.0
