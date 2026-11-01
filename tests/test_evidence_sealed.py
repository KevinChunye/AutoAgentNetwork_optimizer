"""The sealed id lists (step 0.12) are unchanged since they were committed: each file's sha256 matches
research/v3/evidence/sealed/MANIFEST.md, and the nesting rules of the draw hold."""

import pytest
import hashlib
import re

import pandas as pd

from conftest import ROOT

SEALED = ROOT / "research/v3/evidence/sealed"


def ids(name):
    return [x for x in (SEALED / f"{name}.txt").read_text().splitlines() if x]


def test_every_sealed_file_matches_its_manifest_hash():
    rows = re.findall(r"\| (\S+\.txt) \| (\d+) \| `([0-9a-f]{64})` \|", (SEALED / "MANIFEST.md").read_text())
    assert len(rows) == 18
    for name, n, digest in rows:
        data = (SEALED / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == digest, name
        assert len(data.decode().split()) == int(n)


def test_sealed_lists_nest_and_probes_stay_outside():
    sealed = set(ids("bbeh_sealed"))
    assert len(sealed) == 300 and set(ids("bbeh_phase2")) <= sealed and set(ids("bbeh_opus")) <= set(ids("bbeh_phase2"))
    assert set(ids("bbeh_second_call")) <= sealed and not set(ids("probe_bbeh")) & sealed
    fsealed = set(ids("forecast_sealed"))
    assert len(fsealed) == 200 and not fsealed & set(ids("forecast_fit"))
    for sub in ("forecast_second_call", "forecast_opus", "forecast_astra"):
        assert set(ids(sub)) <= fsealed
    question = lambda i: i.split("@")[0]
    assert len({question(i) for i in ids("forecast_all")}) == 300
    assert not {question(i) for i in ids("probe_forecast")} & {question(i) for i in ids("forecast_all")}
    assert not set(ids("probe_math")) & set(ids("math_all")) and set(ids("math_second_call")) <= set(ids("math_all"))


def test_market_extra_holds_every_other_resolved_market_question_once():
    """Session E2 (Kevin's B7): the 243 market questions not among the 300, one instance each; the probe's 5 market
    questions keep the probe's instance."""
    extra = ids("forecast_market_extra")
    question = lambda i: i.split("@")[0]
    assert len(extra) == 243 and len({question(i) for i in extra}) == 243
    assert not {question(i) for i in extra} & {question(i) for i in ids("forecast_all")}
    probe_market = [i for i in ids("probe_forecast") if question(i) in {question(x) for x in extra}]
    assert len(probe_market) == 5 and set(probe_market) <= set(extra)


@pytest.mark.needs_external("evidence/forecast.jsonl", "evidence/bbeh.jsonl")
def test_lockbox_lists_use_no_item_or_question_of_any_other_list():
    """Session E3 (Phase 3C): 200 BBEH items at positions 140+ and 200 data-series questions, all new."""
    question = lambda i: i.split("@")[0]
    others = [p.stem for p in SEALED.glob("*.txt") if not p.stem.startswith("lockbox")]
    bbeh = ids("lockbox_bbeh")
    assert len(bbeh) == len(set(bbeh)) == 200
    assert not set(bbeh) & {i for o in others for i in ids(o)}
    fc = ids("lockbox_forecast")
    assert len(fc) == 200 and len({question(i) for i in fc}) == 200
    assert not {question(i) for i in fc} & {question(i) for o in others for i in ids(o)}
    from autoagentnet.tasks import load_tasks
    meta = {t.id: t.meta for t in load_tasks(ROOT / "data/external/evidence/forecast.jsonl")}
    assert all(not meta[i]["market"] for i in fc)
    tasks = {t.id: t.meta for t in load_tasks(ROOT / "data/external/evidence/bbeh.jsonl")}
    assert all(tasks[i]["position"] >= 140 for i in bbeh)
    per_task = pd.Series([tasks[i]["task"] for i in bbeh]).value_counts()
    assert len(per_task) == 4 and (per_task == 50).all()
