"""Offline tests of scripts/review_runs.py's pure functions (no git, no data/external, no model calls)."""

import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import review_runs as R  # noqa: E402


def panel_calls() -> pd.DataFrame:
    """Four calls of two sources on two items: one cache hit, one truncated and unparsed, one refusal."""
    return pd.DataFrame({
        "item": ["a", "a", "b", "b"], "source": ["h:base", "s:base", "h:base", "s:base"],
        "parsed": [True, False, "True", False], "truncated": [False, True, False, False],
        "from_cache": [False, False, True, "False"], "cost_usd": [0.001, 0.010, 0.001, 0.012],
        "stop_reason": ["end_turn", "max_tokens", "end_turn", "refusal"],
        "model_version": ["h-1", "s-1", "h-1", "s-2"]})


def test_run_name_strips_the_unix_seconds_only():
    assert R.run_name("e51_sol_math_low-1793031312") == "e51_sol_math_low"
    assert R.run_name("e51_sol_math-1793026760") == "e51_sol_math"
    assert R.run_name("no_suffix") == "no_suffix"


def test_prereg_needs_all_four_fields():
    full = {"prereg": {"question": "q", "prediction": "p", "kill": "k", "decision": "d"}}
    assert R.prereg_ok(full)
    assert not R.prereg_ok({"prereg": {"question": "q", "prediction": "p", "kill": "", "decision": "d"}})
    assert not R.prereg_ok({})
    assert not R.prereg_ok(None)


def test_source_table_rates_stop_mix_and_drift():
    t = R.source_table(panel_calls()).set_index("src")
    assert t.loc["h:base", "calls"] == 2 and t.loc["h:base", "cache_hits"] == 1 and t.loc["h:base", "live"] == 1
    assert t.loc["h:base", "unparsed"] == 0 and t.loc["h:base", "versions"] == 1
    assert t.loc["s:base", "truncated"] == 0.5 and t.loc["s:base", "unparsed"] == 1.0
    assert t.loc["s:base", "refused"] == 1 and t.loc["s:base", "versions"] == 2  # drift
    assert t.loc["s:base", "stop_reasons"] in ("max_tokens 50.0%, refusal 50.0%", "refusal 50.0%, max_tokens 50.0%")


def test_desk_calls_use_role_and_model_as_the_source():
    desk = pd.DataFrame({"event_id": ["s1-e000", "s1-e001"], "role": ["trader", "trader"], "model": ["h", "h"],
                         "parsed": [True, False], "truncated": [False, True], "from_cache": [False, False],
                         "cost_usd": [0.001, 0.002]})
    t = R.source_table(desk)
    assert list(t["src"]) == ["trader:h"] and t["stop_reasons"].iloc[0] == "" and t["truncated"].iloc[0] == 0.5
    assert list(R.with_source(desk)["agent"]) == ["trader", "trader"]


def test_ledger_match_counts_unmatched_records_and_replays():
    calls = panel_calls()
    ledger = pd.DataFrame({"run_id": ["x-1", "x-1", "x-2", "x-2"], "task_id": ["a", "a", "b", "b"],
                           "agent_id": ["h.base", "s.base", "h.base", "s.base"],
                           "cost_usd": [0.001, 0.010, 0.001, 0.012]})
    m = R.ledger_match(calls, ledger)
    # row b/h.base was paid in attempt x-2 and is now a cache hit: matched, and counted as replayed dollars
    assert m["unmatched_ledger"] == 0 and m["unledgered_live"] == 0 and m["attempts"] == 2
    assert abs(m["ledger_usd"] - 0.024) < 1e-12 and abs(m["live_usd"] - 0.023) < 1e-12
    assert abs(m["replayed_usd"] - 0.001) < 1e-12
    extra = pd.concat([ledger, ledger.iloc[[0]]])  # a paid call with no row
    assert R.ledger_match(calls, extra)["unmatched_ledger"] == 1
    missing = ledger.iloc[1:]  # a live row (a/h.base) with no ledger record
    assert R.ledger_match(calls, missing)["unledgered_live"] == 1


def test_slice_problems_finds_failed_attempts_and_overlapping_paid_slices():
    attempts = pd.DataFrame({"run_id": ["r-1", "r-2", "r-3", "r-4"], "state": ["completed", "failed", "completed",
                                                                              "completed"],
                             "reason": ["", "APIConnectionError", "", ""], "start": [0, 8, 11, 16],
                             "end": [8, 16, 12, 24], "live": [24, 23, 1, 0]})
    p = R.slice_problems(attempts)
    assert p["failed"] == ["8-16 failed: APIConnectionError"]
    assert p["repeated"] == ["11-12"]  # the resume of the failed slice; r-4 made no live call (a replay)
    assert p["replays"] == 1


def test_diff_summary():
    assert R.diff_summary("a\nb\n", "a\nb\n") == "identical"
    s = R.diff_summary("a\nx = 1\n\nc\n", "a\nx = 2\n\nc\n")
    assert s.startswith("1 committed lines differ (1 reproduced)") and "`x = 1` -> `x = 2`" in s


def test_number_tokens_and_matching_across_forms():
    assert R.number_tokens("Sol 97.3% at $0.0062 (1,063 tokens; -0.7 points)") == ["97.3", "0.0062", "1063", "0.7"]
    source = "| Sol | 0.97333 | 1062.6 | -0.007 |"
    assert R.unmatched_numbers("97.3% and 1,063 and 0.7 points", source) == []  # share, rounding, percentage
    assert R.unmatched_numbers("43.3%", source) == ["43.3"]


def test_anomaly_lines_report_every_flag():
    runs = pd.DataFrame({"run": ["r1", "r2"], "live_rows": [0, 5], "ledger_usd": [1.0, 2.0],
                         "replayed_usd": [1.0, 0.5], "unmatched_ledger": [0, 0], "unledgered_live": [0, 0],
                         "prereg": [True, True], "prereg_at_run": ["yes", "n/a"], "failed": ["", "0-5 stopped: x"],
                         "repeated": ["", "0-5"], "dirty": ["", ""],
                         "unrecorded": ["", "r2-9 (3 calls, $0.010)"]})
    sources = pd.DataFrame({"run": ["r1"], "src": ["h:base"], "truncated": [0.2], "unparsed": [0.0],
                            "refused": [0], "versions": [1], "version_list": ["h-1"], "trunc_mismatch": [0]})
    reads = pd.DataFrame({"read": ["G"], "once": [True], "frozen_ok": [True], "inputs_kept": [False], "note": [""],
                          "reproduced": ["1 committed lines differ"]})
    text = "\n".join(R.anomaly_lines(runs, sources, reads))
    for expected in ("1 runs have no live row", "r2 $0.500", "Every ledger record matches", "r1 h:base 20.0%",
                     "No model_version drift", "r2 [0-5]", "no call was paid twice", "agrees with the stop reason",
                     "G: inputs changed after the read", "G does not reproduce", "r2-9 (3 calls"):
        assert expected in text


def test_truncation_flag_is_checked_against_the_stop_reason():
    calls = panel_calls().assign(truncated=[False, False, False, False])  # max_tokens without the flag
    assert R.source_table(calls).set_index("src").loc["s:base", "trunc_mismatch"] == 1


def test_unrecorded_names_ledger_attempts_without_a_status():
    ledger = pd.DataFrame({"run_id": ["x-1", "x-2", "x-2"], "cost_usd": [0.5, 0.01, 0.02]})
    assert R.unrecorded(ledger, {"x-1"}) == "x-2 (2 calls, $0.030)"
    assert R.unrecorded(ledger, {"x-1", "x-2"}) == ""


def test_network_reconcile_compares_live_calls_with_the_attempt_ledger():
    results = pd.DataFrame({"config_id": ["k1", "k2"], "task_id": ["t", "t"], "calls": [4, 19], "live_calls": [4, 3],
                            "truncated_calls": [0, 1], "parsed": [1.0, 0.0]})
    last = pd.DataFrame({"config_id": ["k1"] * 4 + ["k2"] * 3, "task_id": ["t"] * 7})
    r = R.network_reconcile(results, last)
    assert (r["calls"], r["live"], r["mismatched"], r["outside"]) == (23, 7, 0, 0)
    assert abs(r["truncated"] - 1 / 23) < 1e-12 and r["unparsed"] == 0.5
    extra = pd.concat([last, pd.DataFrame({"config_id": ["k9"], "task_id": ["t"]})])  # billed outside results.csv
    r2 = R.network_reconcile(results, extra)
    assert r2["mismatched"] == 1 and r2["outside"] == 1


def test_market_reconcile_matches_turns_by_session_trader_and_cost():
    turns = pd.DataFrame({"seed": [11, 11, 11], "trader": ["B1", "S2", "B1"], "call_model": ["m", "m", None],
                          "cost_usd": [0.001, 0.002, 0.0], "from_cache": [False, True, False],
                          "truncated": [False, False, False]})
    ledger = pd.DataFrame({"task_id": ["s11", "s11"], "agent_id": ["B1", "S2"], "cost_usd": [0.001, 0.002]})
    r = R.market_reconcile(turns, ledger)
    assert (r["calls"], r["live"], r["mismatched"]) == (2, 1, 0)  # the turn without a call_model made no call
    assert R.market_reconcile(turns, ledger.iloc[:1])["mismatched"] == 0  # the cached turn may come from elsewhere
    assert R.market_reconcile(turns, ledger.iloc[1:])["mismatched"] == 1  # the live B1 turn has no record
    extra = pd.concat([ledger, ledger.iloc[:1]])
    assert R.market_reconcile(turns, extra)["mismatched"] == 1  # a paid record with no turn


def test_paid_stops_and_duplicate_paid():
    ledger = pd.DataFrame({"run_id": ["a-1", "a-1", "b-2"], "stop_reason": ["max_tokens", "refusal", "end_turn"]})
    s = R.paid_stops(ledger)
    assert abs(s["paid_truncated"] - 1 / 3) < 1e-12 and s["paid_refused"] == 1
    cache = pd.DataFrame({"run_id": ["a-1", "a-1", "b-2"], "key": ["k1", "k2", "k3"]})
    assert R.duplicate_paid(cache, ledger) == {"entries": 3, "duplicate_keys": 0, "run_ids": 2, "count_mismatch": 0}
    twice = pd.DataFrame({"run_id": ["a-1", "a-1", "b-2", "b-2"], "key": ["k1", "k2", "k3", "k1"]})
    d = R.duplicate_paid(twice, ledger)
    assert d["duplicate_keys"] == 1 and d["count_mismatch"] == 1


def test_timeout_count_reads_only_the_blocks_own_line():
    text = ("Math-verify timeouts during the whole block-1 read (all grading, vote classes included): 1.\n"
            "Math-verify timeouts during the whole block-2 read: 0.\n")
    assert R.timeout_count(text, "Anchor block 1") == "1"
    assert R.timeout_count(text, "Anchor block 2") == "0"
    assert R.timeout_count(text, "Anchor block 3") == ""  # block 3 prints no count
    assert R.timeout_count(text, "Phase 2") == ""


def test_notes_name_the_cross_run_replays_and_the_timeout_count():
    runs = pd.DataFrame({"run": ["x", "y"], "all_rows_usd": [1.5, 1.0], "ledger_usd": [1.0, 1.0]})
    reads = pd.DataFrame({"read": ["Anchor block 1"], "reproduced": ["3 committed lines differ"],
                          "committed_timeouts": ["1"], "math_verify_timeouts": ["0"]})
    paid = {"entries": 10, "duplicate_keys": 0, "run_ids": 3, "count_mismatch": 0}
    text = "\n".join(R.notes(runs, reads, paid))
    for expected in ("the committed read counted 1, the reproduction 0", "by $0.50 in all: x +$0.500",
                     "no request was paid twice", "F8's Haiku 0.137"):
        assert expected in text
