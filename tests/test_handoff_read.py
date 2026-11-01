"""Offline tests for analysis/handoff_read.py: architecture assembly (one call, vote of three with ties to call 0,
complete + self-check), R(f), f80 and the paired contrast. Synthetic stored calls; no model call."""
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "analysis"))
import handoff_read as H  # noqa: E402


def calls(rows, action="initial"):
    return pd.DataFrame([{"item": i, "receiver": r, "action": action, "answer": a, "parsed": a is not None,
                          "correct": c, "cost_usd": 0.001, "grader": "exact"} for i, r, a, c in rows])


def test_vote_of_three_and_self_check_are_assembled_per_item_and_f():
    copies = calls([("bbeh-x-1~f050", "A", "p", 0.0), ("bbeh-x-1~f050", "B", "q", 1.0), ("bbeh-x-1~f050", "C", "q", 1.0),
                    ("bbeh-x-1~f000", "A", "p", 0.0), ("bbeh-x-1~f000", "B", "r", 0.0), ("bbeh-x-1~f000", "C", None, 0.0)])
    check = calls([("bbeh-x-1~f050", "A", "q", 1.0)], action="reflect")
    out = H.architectures(copies, check).set_index(["arch", "f"])
    assert out.loc[("a", 0.5), "correct"] == 0.0
    assert out.loc[("b", 0.5), "correct"] == 1.0 and out.loc[("b", 0.5), "cost"] == pytest.approx(0.003)
    assert out.loc[("b", 0.0), "answer"] == "p"  # a tie goes to completion 0
    assert out.loc[("c", 0.5), "correct"] == 1.0 and out.loc[("c", 0.5), "cost"] == pytest.approx(0.002)


def test_r_curve_and_f80():
    acc = pd.Series({0.0: 0.4, 0.25: 0.5, 0.5: 0.6, 0.75: 0.7, 1.0: 0.8})
    r = H.r_curve(acc, 0.8)
    assert r[0.0] == 0 and r[1.0] == pytest.approx(1.0) and r[0.5] == pytest.approx(0.5)
    assert H.f80(r) == pytest.approx(0.8)
    assert pd.isna(H.f80(H.r_curve(pd.Series({0.0: 0.4, 0.25: 0.4, 0.5: 0.4, 0.75: 0.4, 1.0: 0.5}), 0.8)))


def test_paired_contrast_in_points():
    arch = pd.DataFrame([{"base": f"i{k}", "f": f, "arch": a, "correct": float(a == "b" or f == 1.0)}
                         for k in range(10) for f in (0.0, 1.0) for a in ("a", "b")])
    d = H.paired(arch, ("b", 0.0), ("a", 0.0))
    assert d["n"] == 10 and d["d"] == pytest.approx(100.0)
