"""Our panel runs as response-table rows (autoagentnet/atlas/panels.py). Offline, a calls frame built in memory."""

import pandas as pd

from autoagentnet.atlas import panels, schema


def calls():
    base = {"task_kind": "bbeh", "meta_task": "word sorting", "outcome": None, "prob": None, "cache_write_tokens": 0,
            "cache_read_tokens": 5, "visible_output_tokens": 1, "seconds": 1.0, "model_version": "v",
            "stop_reason": "end_turn", "truncated": False, "from_cache": False, "template_hash": "h", "reply": "r"}
    rows = [
        {"item": "i1", "source": "haiku_nothink:base", "ref": "haiku_nothink", "model": "claude-haiku-5-5",
         "setting": '{"thinking": {"type": "disabled"}}', "prompt": "base", "call": 0, "answer": "(A)", "parsed": True,
         "correct": 1.0},
        {"item": "i1", "source": "haiku_nothink:base", "ref": "haiku_nothink", "model": "claude-haiku-5-5",
         "setting": '{"thinking": {"type": "disabled"}}', "prompt": "base", "call": 1, "answer": "(a)", "parsed": True,
         "correct": 1.0},
        {"item": "i1", "source": "sol61_low:base", "ref": "sol61_low", "model": "gpt-6.1-sol",
         "setting": '{"reasoning_effort": "low"}', "prompt": "base", "call": 0, "answer": None, "parsed": False,
         "correct": None},
        {"item": "i2", "source": "luna_none:critic", "ref": "luna_none", "model": "gpt-6-luna",
         "setting": '{"reasoning_effort": "none"}', "prompt": "critic", "call": 0, "answer": "B", "parsed": True,
         "correct": 0.0},
    ]
    return pd.DataFrame([{**base, **r, "input_tokens": 10, "output_tokens": 3, "cost_usd": 0.001} for r in rows])


def test_panel_rows_validate_and_carry_classes_reasoning_and_family():
    t = schema.check(panels.load(calls(), "e00_test"))
    assert t["benchmark"].unique().tolist() == ["bbeh/word sorting"]
    i1 = t[t["item"] == "i1"].set_index(["system", "call"])
    assert i1.loc[("haiku_nothink", 0), "answer"] == i1.loc[("haiku_nothink", 1), "answer"] == "c0"  # (A) = (a)
    assert pd.isna(i1.loc[("sol61_low", 0), "answer"]) and i1.loc[("sol61_low", 0), "correct"] == 0.0
    assert set(t["reasoning"]) == {"off", "effort:low"}
    assert set(t["family"]) == {"anthropic", "openai"}
    assert t.loc[t["item"] == "i2", "system"].iloc[0] == "luna_none:critic"
    assert t["input_tokens"].iloc[0] == 15


def test_reasoning_of():
    assert panels.reasoning_of('{"thinking": {"type": "between_tools"}}') == "off"
    assert panels.reasoning_of('{"output_config": {"effort": "high"}}') == "effort:high"
    assert panels.reasoning_of("") == "unknown"
