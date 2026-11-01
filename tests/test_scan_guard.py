"""The K2 scan's running stop (scripts/scan_guard.py): expected dollars of a slice. Offline."""

import importlib.util
from pathlib import Path

from autoagentnet.evidence.panel import PanelConfig

spec = importlib.util.spec_from_file_location("scan_guard", Path(__file__).resolve().parents[1] / "scripts/scan_guard.py")
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)


def test_expected_counts_each_source_on_its_own_items_in_the_slice(tmp_path):
    items = tmp_path / "items.txt"
    items.write_text("".join(f"x{i}\n" for i in range(10)))
    high = tmp_path / "high.txt"
    high.write_text("x0\nx1\nx8\n")
    cfg = PanelConfig(kind="panel", name="e50_scan_test", task_kind="bbeh", tasks="t.jsonl", items=str(items),
                      sources=[{"ref": "a", "calls": 2}, {"ref": "b", "items": str(high)}],
                      expect={"usd_per_call": {"a": 0.01, "b": 0.1}})
    assert abs(guard.expected_usd(cfg) - (10 * 2 * 0.01 + 3 * 0.1)) < 1e-12
    sliced = cfg.model_copy(update={"task_offset": 0, "task_limit": 5})
    assert abs(guard.expected_usd(sliced) - (5 * 2 * 0.01 + 2 * 0.1)) < 1e-12
