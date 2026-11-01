"""Self-or-social end to end, offline on the fake model: calibration run, freeze, test run, read, demo page."""

import asyncio
import json

import pandas as pd

import analysis.self_or_social as A
import analysis.sos_demo as D
from autoagentnet.self_or_social import run as R
from test_self_or_social_run import TEAM, config


def test_calibration_freeze_test_read(tmp_path, monkeypatch):
    from autoagentnet.tasks import Task

    tasks = [Task(id=f"bbeh-w-{i}", prompt=f"Puzzle {i}", answer=str(i % 3), grader="bbeh",
                  meta={"task": ["word sorting", "nycc"][i % 2]}) for i in range(16)]
    (tmp_path / "tasks.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    (tmp_path / "dev.txt").write_text("".join(t.id + "\n" for t in tasks[:10]))
    (tmp_path / "test.txt").write_text("".join(t.id + "\n" for t in tasks[10:]))
    dev = config(tmp_path, name="dev", items=str(tmp_path / "dev.txt"))
    test = config(tmp_path, name="test", items=str(tmp_path / "test.txt"), full_review=True,
                  disjoint_from=[str(tmp_path / "dev.txt")])
    assert R.item_problems(test) == []
    asyncio.run(R.run_sos(dev))
    asyncio.run(R.run_sos(test))
    dev_csv, test_csv = tmp_path / "out/dev/calls.csv", tmp_path / "out/test/calls.csv"
    frozen = tmp_path / "frozen.json"
    A.freeze(type("Args", (), {"dev": str(dev_csv), "out": str(frozen)}))
    saved = json.loads(frozen.read_text())
    assert saved["team"] == ["A", "B", "C"] and saved["policy"]["lam"] in A.LAMS
    assert "bbeh-w-" not in json.dumps(saved["policy"])  # the policy stores counts per cell, no item ids
    out = tmp_path / "report"
    A.read(type("Args", (), {"test": str(test_csv), "frozen": str(frozen), "single": None, "single_source": "",
                             "out": str(out), "draws": 5, "boot": 100, "allow_uncommitted": True}))
    summary = pd.read_csv(out / "summary.csv", index_col=0)
    assert {"vote", "all_reflect", "fixed_peer", "random_matched", "policy", "self_only", "forced_social",
            "smartest_peer", "full_review", "single_A"} <= set(summary.index)
    assert (summary["items"] == 6).all()
    assert "DRY RUN" in (out / "summary.md").read_text() and (out / "frontier.png").exists()
    page = tmp_path / "demo.html"
    D.build(str(test_csv), str(frozen), str(page), items=3, summary=str(out / "summary.csv"))
    html = page.read_text()
    assert "replay" in html.lower() and "FAKE" in html and html.count('class="item"') == 3
