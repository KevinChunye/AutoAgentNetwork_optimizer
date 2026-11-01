"""The automatic Self-or-Social gate (scripts/sos_gate.py) on synthetic slices (offline, no model)."""
import importlib.util
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("sos_gate", ROOT / "scripts" / "sos_gate.py")
sos_gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sos_gate)


def slice_rows(items, bad_first=0, cost=0.01, kind="mcq", answer="B"):
    """15 rows per item: 3 first answers, 9 branches, 3 full reviews; `bad_first` unparsed first answers of A."""
    rows = []
    for n, item in enumerate(items):
        for member, ref in (("A", "haiku_low"), ("B", "sonnet_low"), ("C", "opus_med")):
            for phase, count in (("initial", 1), ("branch", 3), ("full", 1)):
                for _ in range(count):
                    bad = phase == "initial" and member == "A" and n < bad_first
                    rows.append({"item": item, "ref": ref, "phase": phase, "task_kind": kind,
                                 "answer": None if bad else answer, "parsed": not bad, "correct": False if bad else True,
                                 "truncated": False, "stop_reason": "end_turn", "from_cache": False, "reused": False,
                                 "cost_usd": cost})
    return pd.DataFrame(rows)


STATUS = {"state": "completed", "checkpoints": ["committed and pushed"]}


def test_gate_passes_a_clean_slice():
    items = [f"i{k}" for k in range(8)]
    out = sos_gate.verdict(slice_rows(items), STATUS, items, expected_item_usd=0.15, projected_items=288,
                           room_usd=149.0, rows_per_item=15)
    assert out["go"] and out["usd_per_item"] == 0.15   # 15 rows x $0.01


def test_gate_fails_on_each_rule():
    items = [f"i{k}" for k in range(8)]
    one_bad = sos_gate.verdict(slice_rows(items, bad_first=1), STATUS, items, 0.15, 288, 149.0, 15)
    assert not one_bad["rules"]["1_failed_share"]           # 1 of 8 first answers = 12.5% > 10%
    dear = sos_gate.verdict(slice_rows(items, cost=0.03), STATUS, items, 0.15, 288, 149.0, 15)
    assert not dear["rules"]["2_cost_per_item"]             # $0.45 per item > 2 x $0.15
    short = sos_gate.verdict(slice_rows(items)[:-1], STATUS, items, 0.15, 288, 149.0, 15)
    assert not short["rules"]["3_end_to_end"]
    unpushed = sos_gate.verdict(slice_rows(items), {"state": "completed", "checkpoints": ["committed; PUSH FAILED"]},
                                items, 0.15, 288, 149.0, 15)
    assert not unpushed["rules"]["4_completed_and_pushed"]
    tight = sos_gate.verdict(slice_rows(items), STATUS, items, 0.15, 288, 50.0, 15)
    assert not tight["rules"]["5_projection_fits_room"]     # 0.15 x 288 x 1.3 = $56.16 > $50
    assert not any(v["go"] for v in (one_bad, dear, short, unpushed, tight))


def test_math_abstention_is_not_a_failure():
    items = [f"i{k}" for k in range(8)]
    rows = slice_rows(items, kind="math", answer="\\boxed{42}")
    abstain = "\\boxed{\\text{unknown; conjectured } 3}"
    first_a = rows.index[(rows["ref"] == "haiku_low") & (rows["phase"] == "initial")][0]
    rows.loc[first_a, ["parsed", "answer"]] = [False, abstain]
    rates = sos_gate.failed_rates(rows)
    flagged = rates[(rates["ref"] == "haiku_low") & (rates["phase2"] == "initial")]["failed"].iloc[0]
    from autoagentnet.evidence.mathread import abstained
    assert flagged == (0.0 if abstained(abstain) else 1 / 8)
