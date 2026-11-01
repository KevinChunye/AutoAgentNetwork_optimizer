"""Offline tests of the v3 data-source ladders (research/v3/program.md): mocked downloads, so a
network failure always falls through to the next rung with a record of why."""

from __future__ import annotations

import io
import json
from datetime import date

import httpx
import pandas as pd
import pytest

from autoagentnet.ladder import (CheckFailed, GatedRefused, Net, Pull, Rung, SoftwareRung, Unreachable, evidence_table,
                                 licence_verdict, probe, run_ladder)
from autoagentnet.ladder import rungs as R
from autoagentnet.ladder.software import smoke_engine

CUTOFF = date(2026, 6, 30)


def items(n: int, when: date = date(2026, 8, 1), answer: str = "1") -> pd.DataFrame:
    return pd.DataFrame({"id": [f"q{i}" for i in range(n)], "answer": [answer] * n, "date": [when] * n})


def rung(rank: int, loader, licence_ok=None, min_items: int = 50, grader: str = "binary") -> Rung:
    return Rung(workstream="W9", rank=rank, name=f"source {rank}", link=f"https://example.org/{rank}", loader=loader,
                licence="mit", min_items=min_items, fresh_after=CUTOFF, grader=grader, licence_ok=licence_ok)


def good(net) -> Pull:
    return Pull(items(60), "mit", "v1")


def blocked(net) -> Pull:
    raise Unreachable("github.com", 403, "access to this repository is not enabled for this session")


class FakeNet(Net):
    """Serves fixed responses by URL; an Exception value is raised as the download's failure."""

    def __init__(self, routes: dict, hf_token: str | None = None):
        super().__init__(hf_token)
        self.routes = routes

    def get(self, url, gated=False, params=None):
        value = self.routes[url]
        if isinstance(value, Exception):
            raise value
        body = value if isinstance(value, bytes) else json.dumps(value).encode()
        return httpx.Response(200, content=body)


def parquet(frame: pd.DataFrame) -> bytes:
    buffer = io.BytesIO()
    frame.to_parquet(buffer)
    return buffer.getvalue()


# ---------------------------------------------------------------- the six required fall-throughs


def test_blocked_host_falls_through_to_the_next_rung_and_names_the_host():
    result = run_ladder([rung(1, blocked), rung(2, good)])
    first, second = result.evidence
    assert first.failed == "reachable" and first.blocked_host == "github.com" and first.http_status == 403
    assert first.passed == [] and not first.chosen
    assert second.ok and second.chosen and result.chosen is second


def test_gated_source_without_a_token_fails_the_licence_check():
    routes = {"https://huggingface.co/api/datasets/cais/hle": {"sha": "abc", "gated": "auto", "cardData": {"license": "mit"}}}
    hle = R.w1_rungs(CUTOFF)[2]
    ev = probe(hle, FakeNet(routes, hf_token=None))
    assert ev.passed == ["reachable"] and ev.failed == "licensed"
    assert "HF_TOKEN is not set" in ev.detail


def test_gated_source_that_refuses_the_token_fails_the_licence_check():
    meta = {"sha": "abc", "gated": "auto", "cardData": {"license": "mit"}}
    refused = GatedRefused("huggingface.co", 403, "you are not in the authorized list")
    routes = {"https://huggingface.co/api/datasets/cais/hle": meta,
              "https://huggingface.co/api/datasets/cais/hle/parquet": refused}
    ev = probe(R.w1_rungs(CUTOFF)[2], FakeNet(routes, hf_token="token"))
    assert ev.failed == "licensed" and ev.http_status == 403 and "authorized list" in ev.detail


def test_licence_refusal_falls_through():
    def proprietary(net):
        return Pull(items(60), "proprietary, no research use", "v1")

    result = run_ladder([rung(1, proprietary), rung(2, good)])
    assert result.evidence[0].failed == "licensed" and "not on the research-use list" in result.evidence[0].detail
    assert result.chosen.rank == 2


def test_unstated_licence_and_unread_terms_are_refusals():
    assert licence_verdict("") == (False, "no licence stated on the source")
    assert licence_verdict("cc-by-nc-sa-4.0 / cc-by-sa-4.0")[0]
    assert not licence_verdict("cc-by-nc-sa-4.0 / custom")[0]
    ev = probe(rung(1, good, licence_ok=(False, "terms unread")))
    assert ev.failed == "licensed" and ev.detail == "terms unread"


def test_too_few_items_fails_big_enough():
    def small(net):
        return Pull(items(12), "mit", "v1")

    ev = probe(rung(1, small))
    assert ev.passed == ["reachable", "licensed", "gradable"] and ev.failed == "big enough"
    assert ev.n_items == 12 and "minimum is 50" in ev.detail


def test_stale_dates_fail_fresh_unless_a_canary_protects_the_source():
    def stale(net):
        return Pull(items(60, when=date(2025, 2, 26)), "apache-2.0", "v1")

    def canary(net):
        return Pull(items(60, when=date(2025, 2, 26)), "apache-2.0", "v1", canary="BENCHMARK DATA SHOULD NEVER APPEAR")

    ev = probe(rung(1, stale))
    assert ev.failed == "fresh" and ev.n_fresh == 0 and "2025-02-26" in ev.detail
    protected = probe(rung(2, canary))
    assert protected.ok and protected.n_fresh == 60 and any("canary" in note for note in protected.notes)


def test_every_rung_failing_skips_the_workstream_with_a_record_per_rung():
    def stale(net):
        return Pull(items(60, when=date(2026, 6, 30)), "mit", "v1")  # the cutoff day itself is not fresh

    result = run_ladder([rung(1, blocked), rung(2, stale), rung(3, lambda net: Pull(items(3), "mit", "v1"))],
                        probe_all=True)
    assert result.skipped and result.chosen is None
    assert [ev.failed for ev in result.evidence] == ["reachable", "fresh", "big enough"]
    assert "skipped" in result.summary()
    table = evidence_table([result])
    assert len(table) == 3 and set(table["chosen"]) == {"no"}


# ---------------------------------------------------------------- the rest of the ladder logic


def test_a_malformed_download_is_recorded_and_the_ladder_moves_on():
    def malformed(net):
        raise ValueError("Parquet magic bytes not found")

    result = run_ladder([rung(1, malformed), rung(2, good)])
    assert result.evidence[0].failed == "reachable" and "download unusable" in result.evidence[0].detail
    assert "Parquet magic bytes" in result.evidence[0].detail and result.chosen.rank == 2


def test_grader_self_check_must_match_every_gold():
    ev = probe(rung(1, lambda net: Pull(items(60, answer="0.5"), "mit", "v1")))  # not a 0/1 outcome
    assert ev.failed == "gradable" and ev.self_check.startswith("0/60")


def test_hand_check_sample_is_ten_fresh_golds():
    def mixed(net):
        frame = pd.concat([items(40, when=date(2026, 1, 1)), items(60, when=date(2026, 9, 1))], ignore_index=True)
        frame["id"] = [f"q{i}" for i in range(100)]
        return Pull(frame, "mit", "v1")

    ev = probe(rung(1, mixed))
    assert ev.ok and len(ev.hand_check_ids) == 10
    assert all(int(i[1:]) >= 40 for i in ev.hand_check_ids)  # only items dated after the cutoff


def test_probe_all_keeps_going_after_the_first_pass_but_chooses_the_first():
    result = run_ladder([rung(2, good), rung(1, good)], probe_all=True)
    assert [ev.rank for ev in result.evidence] == [1, 2]
    assert [ev.chosen for ev in result.evidence] == [True, False]


def test_net_classifies_blocked_hosts_gates_and_http_errors(monkeypatch):
    def fake_get(url, **kwargs):
        if "blocked" in url:
            raise httpx.ConnectError("proxy refused")
        if "gated" in url:
            return httpx.Response(403, text="restricted")
        if "limited" in url:
            return httpx.Response(429, text="too many requests")
        return httpx.Response(404, text="not found")

    monkeypatch.setattr(httpx, "get", fake_get)
    net = Net(retry_wait_s=0)
    with pytest.raises(Unreachable) as blocked_error:
        net.get("https://blocked.example/x")
    assert blocked_error.value.host == "blocked.example" and blocked_error.value.status is None
    with pytest.raises(GatedRefused):
        net.get("https://huggingface.co/gated", gated=True)
    with pytest.raises(Unreachable) as missing:
        net.get("https://huggingface.co/missing")
    assert missing.value.status == 404
    with pytest.raises(Unreachable) as limited:
        net.get("https://api.example/limited")
    assert limited.value.status == 429


def test_matharena_loader_pools_2026_sets_and_dates_arxiv_items_by_month():
    hf = "https://huggingface.co/api/datasets"
    listing = [{"id": "MathArena/aime_2026", "createdAt": "2026-02-13T00:00:00Z"},
               {"id": "MathArena/aime_2026_I", "createdAt": "2026-02-06T00:00:00Z"},
               {"id": "MathArena/aime_2026_outputs", "createdAt": "2026-02-13T00:00:00Z"},
               {"id": "MathArena/arxivmath-0826", "createdAt": "2026-09-13T00:00:00Z"},
               {"id": "MathArena/hmmt_feb_2025", "createdAt": "2025-04-16T00:00:00Z"}]
    aime = pd.DataFrame({"problem_idx": [1, 2], "answer": [277, 62], "problem": ["p1", "p2"]})
    arxiv = pd.DataFrame({"problem_idx": [1, 2], "answer": ["\\frac{1}{2}", "a long answer with words in it"],
                          "problem": ["p", "q"], "source": ["2608.00234", "2606.01817"]})
    routes = {hf: listing}
    for name, frame in (("aime_2026", aime), ("arxivmath-0826", arxiv)):
        shard = f"{hf}/MathArena/{name}/parquet/default/train/0.parquet"
        routes[f"{hf}/MathArena/{name}"] = {"sha": "0123456789", "cardData": {"license": "cc-by-nc-sa-4.0"}}
        routes[f"{hf}/MathArena/{name}/parquet"] = {"default": {"train": [shard]}}
        routes[shard] = parquet(frame)
    pull = R.load_matharena(FakeNet(routes))
    assert sorted(pull.items["set"].unique()) == ["aime_2026", "arxivmath-0826"]  # no _I part, no outputs, no 2025
    dates = dict(zip(pull.items["id"], pull.items["date"]))
    assert dates["aime_2026-1"] == date(2026, 2, 13)
    assert dates["arxivmath-0826-1"] == date(2026, 8, 1) and dates["arxivmath-0826-2"] == date(2026, 6, 1)
    kept = R.math_golds(pull.items)
    assert set(kept["id"]) == {"aime_2026-1", "aime_2026-2", "arxivmath-0826-1"}
    assert pull.licence == "cc-by-nc-sa-4.0"


def test_polymarket_outcome_reads_only_settled_markets():
    assert R.polymarket_outcome('["1", "0"]') == "1"
    assert R.polymarket_outcome('["0", "1"]') == "0"
    assert R.polymarket_outcome('["0.4", "0.6"]') is None
    assert R.polymarket_outcome(None) is None


def test_software_ladder_stops_at_the_first_rung_that_passes():
    def fail_smoke():
        raise CheckFailed("smoke test failed")

    def unreachable():
        raise Unreachable("github.com", 403, "blocked")

    calls = []
    ladder = [SoftwareRung("W9", 1, "blocked", "x", "mit", unreachable, lambda: "ok", lambda: "ok"),
              SoftwareRung("W9", 2, "broken", "x", "mit", lambda: ("mit", "v1"), lambda: "ok", fail_smoke),
              SoftwareRung("W9", 3, "works", "x", "mit", lambda: ("bsd-3-clause", "v1"), lambda: "ok", lambda: "ok"),
              SoftwareRung("W9", 4, "never tried", "x", "mit", lambda: calls.append(4) or ("mit", "v1"),
                           lambda: "ok", lambda: "ok")]
    result = run_ladder(ladder)
    assert [ev.failed for ev in result.evidence] == ["reachable", "smoke test", None]
    assert result.chosen.rank == 3 and calls == []


def test_our_engine_smoke_test_runs_offline():
    assert "1 LLM buyer" in smoke_engine()
