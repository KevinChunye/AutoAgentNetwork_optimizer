"""The response-table schema (autoagentnet/atlas/schema.py): valid tables pass and round-trip through Parquet;
each kind of violation is reported in plain words. Offline."""

import pandas as pd
import pytest

from autoagentnet.atlas import schema as S


def table(n=4):
    return pd.DataFrame({
        "benchmark": ["bbeh/boolean_expressions"] * n, "item": [f"i{k // 2}" for k in range(n)],
        "system": ["qwen3.5-4b:w4:budget:1024"] * n, "family": ["qwen3.5"] * n, "model": ["Qwen/Qwen3.5-4B"] * n,
        "size_b": [4.0] * n, "precision": ["w4"] * n, "reasoning": ["budget:1024"] * n, "scaffold": ["direct"] * n,
        "call": [k % 2 for k in range(n)], "answer": ["(A)", None, "(B)", "(B)"], "correct": [1.0, 0.0, None, 1.0],
        "cost_usd": [0.0] * n, "gpu_seconds": [0.5] * n, "input_tokens": [100] * n, "output_tokens": [900] * n,
        "latency_s": [2.0] * n, "signal_logprob_mean": [-0.2, -1.5, -0.4, -0.3], "source": ["testbed/pilot"] * n,
        "licence": ["internal"] * n,
    })


def test_valid_table_passes_and_round_trips(tmp_path):
    t = table()
    assert S.problems(t) == []
    path = S.write(t, tmp_path / "shard.parquet")
    back = S.read(tmp_path)
    assert list(back.columns) == list(S.COLUMNS) + ["signal_logprob_mean"]
    assert back["correct"].isna().sum() == 1 and back["call"].dtype == "Int64"
    assert path.exists()


def test_optional_columns_may_be_absent():
    t = table().drop(columns=["size_b", "gpu_seconds", "latency_s", "answer", "signal_logprob_mean"])
    assert S.problems(t) == []
    assert "size_b" in S.check(t).columns


@pytest.mark.parametrize("change, message", [
    (lambda t: t.drop(columns=["licence"]), "missing required columns"),
    (lambda t: t.assign(extra=1), "unknown columns"),
    (lambda t: t.assign(correct=[1.0, 0.5, 0.0, 1.0]), "correct"),
    (lambda t: t.assign(precision=["int4"] * 4), "precision"),
    (lambda t: t.assign(reasoning=["high"] * 4), "reasoning"),
    (lambda t: t.assign(call=[0, 0, 0, 0]), "duplicated"),
    (lambda t: t.assign(cost_usd=[-1.0, 0, 0, 0]), "cost_usd"),
    (lambda t: t.assign(family=[None, "qwen3.5", "qwen3.5", "qwen3.5"]), "family"),
])
def test_each_violation_is_reported(change, message):
    found = S.problems(change(table()))
    assert any(message in p for p in found), found
    with pytest.raises(ValueError):
        S.check(change(table()))


def test_empty_table_has_every_column():
    assert list(S.empty().columns) == list(S.COLUMNS) and S.problems(S.empty()) == []
