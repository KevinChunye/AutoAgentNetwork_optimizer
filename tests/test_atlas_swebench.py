"""The SWE-bench Verified loader (autoagentnet/atlas/swebench.py) on a small in-memory repository. Offline."""

import json

import yaml

from autoagentnet.atlas import schema
from autoagentnet.atlas.swebench import PREFIX, load

IDS = ["a__x-1", "a__x-2", "b__y-3", "b__y-4"]


def repo():
    files = {}

    def add(name, meta, details=None, resolved=None):
        files[f"{PREFIX}{name}/metadata.yaml"] = yaml.safe_dump(meta)
        if details is not None:
            files[f"{PREFIX}{name}/per_instance_details.json"] = json.dumps(details)
        if resolved is not None:
            files[f"{PREFIX}{name}/results/results.json"] = json.dumps({"resolved": resolved, "no_generation": []})

    add("20260101_mini_model-a", {"info": {"name": "A", "resolved": 50.0}, "tags": {"model": ["model-a"], "org": "OrgA",
        "agent": "mini-SWE-agent", "reasoning_effort": "high"}},
        details={i: {"resolved": k % 2 == 0, "cost": 0.1 * (k + 1), "api_calls": 10 + k} for k, i in enumerate(IDS)})
    add("20260102_other_model-b", {"info": {"name": "B", "resolved": 25.0}, "tags": {"model": ["model-b"], "org": "OrgB"}},
        resolved=["b__y-3"])
    add("20260226_mini_bad", {"info": {"name": "Bad", "resolved": 90.0}, "tags": {"model": ["bad"], "org": "OrgC"}},
        details={i: {"resolved": False, "cost": 0.1, "api_calls": 5} for i in IDS})
    return files


def test_loader_builds_a_valid_response_table_and_drops_contradictions():
    files = repo()
    out = load(files.get, sorted(files))
    t = schema.check(out["table"])
    assert out["universe"] == sorted(IDS)
    assert set(t["system"]) == {"20260101_mini_model-a", "20260102_other_model-b"}
    assert list(out["dropped"]["system"]) == ["20260226_mini_bad"]
    a = t[t["system"] == "20260101_mini_model-a"].set_index("item")
    assert a.loc["a__x-1", "correct"] == 1.0 and a.loc["a__x-2", "correct"] == 0.0
    assert a.loc["b__y-4", "signal_steps"] == 13 and a.loc["a__x-2", "cost_usd"] == 0.2
    assert a["reasoning"].iloc[0] == "effort:high" and a["family"].iloc[0] == "orga"
    b = t[t["system"] == "20260102_other_model-b"]
    assert b["correct"].sum() == 1 and b["cost_usd"].isna().all()
