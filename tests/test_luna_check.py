"""The Luna check's read (analysis/luna_check.py) on made-up calls; offline."""

import pandas as pd
import pytest

from analysis.luna_check import exact_interval, shape, tables


def test_reply_shapes_and_accuracy_table():
    calls = pd.DataFrame({
        "item": ["bbeh-dyck_languages-1", "bbeh-web_of_lies-2", "bbeh-dyck_languages-3", "bbeh-web_of_lies-4"],
        "ref": ["luna_none", "luna_none", "luna_low_ev", "luna_low_ev"],
        "reply": ["46", "I'm not sure.", "Work.\nANSWER: 12", "x"],
        "stop_reason": ["stop", "stop", "stop", "content_filter"],
        "correct": [1.0, 0.0, 1.0, 0.0], "cost_usd": [0.0001] * 4, "output_tokens": [5, 9, 400, 3]})
    acc, by_task, shapes = tables(calls)
    assert acc.set_index("ref").loc["luna_none", "accuracy"] == 0.5
    s = shapes.set_index("ref")
    assert s.loc["luna_none", "bare answer"] == 1 and s.loc["luna_none", "unparsed"] == 1
    assert s.loc["luna_low_ev", "ANSWER line"] == 1 and s.loc["luna_low_ev", "refused"] == 1
    assert shape("<yes, no, yes>", "stop") == "bare answer"


def test_exact_interval():
    lo, hi = exact_interval(0, 40)
    assert lo == 0 and hi == pytest.approx(1 - 0.025 ** (1 / 40))
    lo, hi = exact_interval(20, 40)
    assert lo < 0.5 < hi and hi - lo == pytest.approx(0.32, abs=0.02)
