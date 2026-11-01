"""MathArena and LiveBench loaders (autoagentnet/atlas/matharena.py, livebench.py) on frames built in memory.
Offline."""

import pandas as pd

from autoagentnet.atlas import livebench, matharena, schema


def raw_matharena():
    return pd.DataFrame({
        "problem_idx": [1, 1, 1, 2, 2, 2],
        "model_name": ["A", "A", "B", "A", "A", "B"],
        "model_config": ["openai/a", "openai/a", "Google/b", "openai/a", "openai/a", "Google/b"],
        "idx_answer": [0, 1, 0, 0, 0, 0],
        "parsed_answer": ["5", None, "5", "7", "7", "8"],
        "correct": [True, False, True, False, False, True],
        "cost": [0.1, 0.1, 0.2, 0.1, 0.1, -1.0],
        "input_tokens": [10, 10, 10, 10, 10, 10],
        "output_tokens": [100, 100, -5, 100, 100, 50],
    })


def test_matharena_drops_negative_tokens_and_duplicates_and_validates():
    out = matharena.load(lambda name: raw_matharena(), sets=["aime_2026"])
    t = schema.check(out["table"])
    counts = out["sets"].iloc[0]
    assert counts["negative_tokens"] == 1 and counts["duplicates"] == 1 and len(t) == 4
    assert set(t["family"]) == {"openai", "google"} and t["benchmark"].iloc[0] == "matharena/aime_2026"
    assert t.loc[t["system"] == "openai/a", "call"].max() == 1
    assert t["answer"].isna().sum() == 1
    # answers become classes per problem: on problem 2, "7" and "8" are c0 and c1
    p2 = t[t["item"] == "2"].set_index("system")["answer"]
    assert p2["openai/a"] == "c0" and p2["Google/b"] == "c1"
    assert t.loc[t["system"] == "Google/b", "cost_usd"].isna().all()  # the negative cost became missing


def test_matharena_never_loads_the_sealed_anchor_sets():
    assert not set(matharena.SETS) & {"arxivmath-0826", "arxivmath-0926"}
    assert {"arxivmath-0826", "arxivmath-0926"} <= set(matharena.EXCLUDED)
    assert matharena.licence_of("arxivmath-0626") == "cc-by-sa-4.0"
    assert matharena.licence_of("aime_2025") == "cc-by-nc-sa-4.0"


def test_livebench_keeps_binary_tasks_and_the_latest_repeat():
    raw = pd.DataFrame({
        "question_id": ["q1", "q1", "q1", "q2", "q3"],
        "task": ["typos", "typos", "typos", "typos", "connections"],
        "model": ["Claude-3-opus", "claude-3-opus", "gpt-4o", "gpt-4o", "gpt-4o"],
        "score": [0.0, 1.0, 1.0, 0.0, 0.5],
        "turn": 1, "tstamp": [1.0, 2.0, 1.0, 1.0, 1.0], "category": "language",
    })
    out = livebench.load(raw)
    t = schema.check(out["table"])
    assert len(t) == 3 and out["repeats"] == 1
    assert t.loc[(t["item"] == "q1") & (t["system"] == "claude-3-opus"), "correct"].iloc[0] == 1.0
    assert out["dropped_tasks"]["task"].tolist() == ["connections"]


def test_livebench_family_rules():
    cases = {"deepseek-r1-distill-qwen-32b": "qwen", "deepseek-r1-distill-llama-70b": "meta", "deepseek-v3": "deepseek",
             "o1-2024-12-17-high": "openai", "o3-mini-2025-01-31-low": "openai", "chatgpt-4o-latest-2025-01-29": "openai",
             "azerogpt": "unknown", "gemma-2-9b-it": "google", "claude-3-5-haiku-20241022": "anthropic",
             "olmo-2-1124-13b-instruct": "allenai", "zephyr-7b-beta": "mistral", "phi-4": "microsoft"}
    for name, fam in cases.items():
        assert livebench.family_of(name) == fam, name
