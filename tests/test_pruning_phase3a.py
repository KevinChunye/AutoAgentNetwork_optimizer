"""Phase 3A (analysis/pruning_phase3a.py) on the cached calls: the inputs it builds and the headline numbers
of research/v3/pruning/phase3a.md, pinned (a regression test; offline, $0)."""

import numpy as np
import pytest

from analysis import pruning_phase3a as A
from autoagentnet.evidence.calibration import two_folds
from autoagentnet.pruning import search as S
from autoagentnet.pruning.replay import Panel, predict


def test_flat_panel_is_the_80_items_with_five_haiku_calls_and_one_sonnet_call():
    panel = Panel.from_calls(A.flat_calls())
    assert panel.n == 80 and panel.m == 6 and not panel.dropped
    assert panel.units["unit"].tolist() == [f"haiku:{k}" for k in range(5)] + ["sonnet:0"]
    Z = panel.correct_matrix()
    assert Z[:, 5].mean() == pytest.approx(0.7125)
    assert Z[:, :5].mean() == pytest.approx(0.525)
    assert predict(panel, S.mask_of(panel, range(5)))["correct"].mean() == pytest.approx(0.5625)
    cascade = S.h7_cascade(panel, range(5), 5, 3)
    assert cascade["correct"].mean() == pytest.approx(0.7125)
    assert cascade["dollars"].mean() / panel.cost[:, 5].mean() == pytest.approx(0.567, abs=0.001)


def test_grid_headlines():
    grid = A.load_grid()
    panel = Panel.from_calls(A.flat_calls())
    assert set(grid.items) == set(panel.items)
    pts = grid.points().set_index("design")
    assert len(pts) == 27 and pts.loc["k6-6-6-1", "accuracy"] == pytest.approx(0.625)
    assert pts.loc["k1-1-1-1", "accuracy"] == pytest.approx(0.45)
    folds = two_folds(panel.n, seed=0, strata=A.task_of(panel.items))
    a = A.grid_part(grid, np.asarray(folds), {})
    assert a["pooled"]["estimate"] == pytest.approx(0.0092, abs=0.0001)
    assert a["phi_designs"] == pytest.approx(0.65, abs=0.005)
    assert a["netadapt"]["design"].tolist()[:3] == ["k6-6-6-1", "k3-6-6-1", "k3-6-3-1"]
