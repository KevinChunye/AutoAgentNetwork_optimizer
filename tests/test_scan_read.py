"""The scan's task-choice rule (analysis/scan_read.py). Offline, frames built in memory."""

import pandas as pd

from analysis import scan_read as S


def test_choose_takes_one_task_per_group_then_fills():
    t = pd.DataFrame({"task": ["a", "b", "c", "d", "e", "f"], "eligible": [True, True, True, True, True, False],
                      "headroom": [0.9, 0.8, 0.7, 0.6, 0.5, 1.0], "fresh_after_scan": [100] * 6,
                      "group": ["g1", "g1", "g2", "g3", "g1", "g4"]})
    out = S.choose(t)
    assert out.loc[out["chosen"], "task"].tolist() == ["a", "b", "c", "d"]  # g1, g2, g3 first; then b fills
    assert "f" not in out["task"].tolist()


def test_choose_breaks_ties_by_fresh_items_then_name():
    t = pd.DataFrame({"task": ["y", "x", "z"], "eligible": True, "headroom": 0.5, "fresh_after_scan": [100, 100, 150],
                      "group": ["g1", "g2", "g3"]})
    assert S.choose(t)["task"].tolist() == ["z", "x", "y"]


def test_final_line():
    assert S.final_line("reasoning\n\nANSWER: 1,0,0\n") == "ANSWER: 1,0,0"
    assert S.final_line("") == ""
