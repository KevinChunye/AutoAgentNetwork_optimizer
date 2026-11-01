"""Study CD (session E6): the frozen tests, the power simulation, the seal's lists, the probe configs and the probe's
cost table, offline. Made-up panels; the seal and configs are the committed files."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
from conftest import ROOT

from analysis import cd_power, cd_probe
from analysis import cd_read as R
from autoagentnet.evidence.panel import PanelConfig, read_ids
from autoagentnet.pruning.replay import Panel

SEALED = ROOT / "research/v4/cd/sealed"


def panel_of(columns: dict[str, np.ndarray], costs: dict[str, float]) -> Panel:
    """A choice panel from per-unit 0/1 correctness (a right call answers 0, a wrong one 1)."""
    names = list(columns)
    Z = np.column_stack([columns[n] for n in names]).astype(float)
    A = np.where(Z == 1, 0, 1)
    cost = np.column_stack([np.full(len(Z), costs[n.split(":")[0]]) for n in names])
    return Panel.from_arrays(A, Z, cost, sources=[n.rsplit(":", 1)[0] for n in names],
                             calls=[int(n.rsplit(":", 1)[1]) for n in names], items=[f"x{i}" for i in range(len(Z))])


def test_cd1_is_the_share_of_the_vendor_gap_that_depth_closes():
    n = 100
    off, deep, sol = np.zeros(n), np.zeros(n), np.zeros(n)
    off[:40], deep[:50], sol[:60] = 1, 1, 1  # off 40%, deep 50%, sol 60%: R = 10 / 20 = 0.5
    p = panel_of({"off:base:0": off, "deep:base:0": deep, "sol:base:0": sol}, {"off": 1, "deep": 1, "sol": 1})
    fams = np.array(["bbeh"] * 50 + ["math"] * 50)
    out = R.cd1(p, fams, ["off:base:0"], ["deep:base:0"], ["sol:base:0"])
    assert out["estimate"] == pytest.approx(0.5) and out["gap_points"] == pytest.approx(20) and not out["void"]
    # bbeh (items 0-49): off 80%, deep and sol 100%, so R = 1; math (50-99): only sol is right, on 10 of 50, so R = 0
    assert out["R_bbeh"] == pytest.approx(1.0) and out["R_math"] == pytest.approx(0.0)
    small = R.cd1(p, fams, ["off:base:0"], ["deep:base:0"], ["deep:base:0"])  # a 10-point gap is fine; 0 is void
    assert not small["void"] and R.cd1(p, fams, ["off:base:0"], ["deep:base:0"], ["off:base:0"])["void"]


def test_cd2_matches_the_odd_vote_nearest_in_dollars():
    n = 60
    cols = {f"wide:base:{c}": (np.arange(n) % 2 == 0).astype(float) for c in range(5)}
    cols["deep:base:0"] = np.ones(n)
    p = panel_of(cols, {"wide": 1.0, "deep": 2.6})
    assert R.nearest_odd_k(p, ["deep:base:0"], [f"wide:base:{c}" for c in range(5)]) == 3  # 3 x $1 nearest $2.6
    out = R.cd2(p, np.array(["code"] * n), ["deep:base:0"], [f"wide:base:{c}" for c in range(5)])
    assert out["k"] == 3 and out["estimate"] == pytest.approx(0.5) and out["p"] == 0.0


def test_family_table_runs_holm_over_the_confirmatory_tests_only():
    results = [{"test": "CD1", "p": 0.01, "estimate": 0.8, "void": False}, {"test": "CD2", "p": 0.2, "estimate": 0.01}]
    t = R.family_table(results, ["CD1"])
    assert t.set_index("test").loc["CD1", "passes"] and np.isnan(t.set_index("test").loc["CD2", "threshold"])


def test_power_simulation_runs_the_frozen_tests():
    row = cd_power.scenario({"bbeh": 20, "math": 20, "code": 20}, 1.0, 0.04, 1.5, 3.0, 0.2, sims=3)
    assert row["items"] == 60 and row["k"] == 3 and 0 <= row["power_CD1"] <= 1


def test_seal_lists_are_disjoint_from_every_earlier_list_and_match_the_manifest():
    lists = {p.stem: read_ids(p) for p in SEALED.glob("*.txt")}
    assert {k: len(v) for k, v in lists.items() if k.endswith("_core")} == {"bbeh_core": 57, "math_core": 60,
                                                                            "code_core": 50}
    mine = [i for v in lists.values() for i in v]
    assert len(mine) == len(set(mine))
    earlier = set()
    for path in (ROOT / "research").rglob("*.txt"):
        if SEALED.parent not in path.parents:
            earlier |= set(read_ids(path))
    assert not (set(mine) - set(lists["bbeh_probe"])) & earlier
    manifest = (SEALED / "MANIFEST.md").read_text()
    import hashlib

    for name in lists:
        assert hashlib.sha256((SEALED / f"{name}.txt").read_bytes()).hexdigest() in manifest


def test_probe_configs_load_with_a_prereg_and_a_guard_per_arm():
    configs = sorted((ROOT / "configs/experiments/v4").glob("e60_cd_probe_*.yaml"))
    assert len(configs) == 12
    for path in configs:
        cfg = PanelConfig.from_yaml(path)
        assert cfg.prereg is not None and cfg.items.endswith("_probe.txt") and cfg.task_kind in R.FAMILIES
        assert set(cfg.expect.usd_per_call) == {s.ref for s in cfg.sources}


@pytest.mark.needs_external("cd/bbeh.jsonl", "cd/math.jsonl", "cd/code.jsonl")
def test_probe_slices_fit_the_run_cap_and_a_dry_run_works(tmp_path):
    sys.path.insert(0, str(ROOT / "scripts"))
    import anchor_slices as S

    for path in sorted((ROOT / "configs/experiments/v4").glob("e60_cd_probe_*.yaml")):
        cfg = PanelConfig.from_yaml(path)
        assert all(w <= 0.95 * 4.0 for _, _, w in S.slices(S.per_item_worst(cfg), 4.0))
    run = subprocess.run(["aan", "run", "configs/experiments/v4/e60_cd_probe_haiku_code.yaml", "--model-override", "fake",
                          "--task-limit", "2"], cwd=ROOT, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr[-500:]
    calls = pd.read_csv(ROOT / "runs/dry/e60_cd_probe_haiku_code/calls.csv")
    assert len(calls) == 12 and calls["correct"].isna().all() and "thinking_tokens" in calls


def test_probe_table_reads_costs_and_sets_ceilings():
    calls = pd.DataFrame({"item": ["a", "b", "c", "a"], "task_kind": ["math"] * 4, "source": ["s:base"] * 3 + ["t:base"],
                          "ref": ["s", "s", "s", "t"], "call": 0, "parsed": [True, True, False, True],
                          "output_tokens": [1000, 2000, 30000, 500], "thinking_tokens": [800, 1500, 29000, 0],
                          "cost_usd": [0.01, 0.02, 0.3, 0.001], "seconds": 1.0, "truncated": [False, False, True, False]})
    t = cd_probe.table(calls).set_index("ref")
    assert t.loc["s", "calls"] == 3 and t.loc["s", "truncated"] == pytest.approx(1 / 3)
    assert t.loc["s", "ceiling_main"] == cd_probe.ceiling(t.loc["s", "output_p99"]) and t.loc["t", "ceiling_main"] == 4096
    assert cd_probe.ceiling(30000) == 45056


def test_read_regrades_every_family_and_runs_the_tests_on_made_up_runs(tmp_path, monkeypatch):
    """The read end to end on made-up calls: BBEH by parser v2.1, math by E5's reader, code by running each program on
    its hidden tests (graded once, then kept by the reply's hash), truncated calls wrong; then CD1, CD2 and the tables."""
    import json as J

    data, res = tmp_path / "cd", tmp_path / "results"
    data.mkdir()
    rng = np.random.default_rng(0)
    n = 12
    bbeh = [{"id": f"bbeh-word_sorting-{i}", "prompt": "Sort.", "answer": "a b", "grader": "bbeh",
             "meta": {"task": "word sorting"}} for i in range(n)]
    math = [{"id": f"arxivcs-0826-{i}", "prompt": "2+2?", "answer": "4", "grader": "math",
             "meta": {"kind": "math", "set": "arxivcs-0826"}} for i in range(n)]
    code = [{"id": f"lcb-x-{i}", "prompt": "Print 1.", "answer": None, "grader": "exact",
             "meta": {"kind": "code", "fn_name": None}} for i in range(n)]
    for name, rows in (("bbeh", bbeh), ("math", math), ("code", code)):
        (data / f"{name}.jsonl").write_text("".join(J.dumps(r) + "\n" for r in rows))
    test = [{"input": "", "output": "1\n", "testtype": "stdin"}]
    (data / "code_tests.jsonl").write_text("".join(J.dumps({"id": r["id"], "public_tests": test, "private_tests": test})
                                                   + "\n" for r in code))
    monkeypatch.setattr(R, "CD_DATA", data)
    monkeypatch.setattr(R, "BBEH_GOLDS", (data / "bbeh.jsonl",))
    replies = {"bbeh": ("Sorted.\nANSWER: a b", "ANSWER: b a"), "math": ("so \\boxed{4}", "so \\boxed{5}"),
               "code": ("```python\nprint(1)\n```", "```python\nprint(2)\n```")}
    p_right = {"sonnet_nothink": 0.3, "sonnet_max": 0.6, "sol61_low": 0.8, "haiku_max": 0.7, "haiku_xhigh": 0.5,
               "opus_max": 0.9, "opus_med": 0.8}
    rows = []
    for fam, items in (("bbeh", bbeh), ("math", math), ("code", code)):
        for t in items:
            for src, calls in (("sonnet_nothink", 1), ("sonnet_max", 2), ("sol61_low", 1), ("haiku_max", 3),
                               ("haiku_xhigh", 3), ("opus_max", 1), ("opus_med", 1)):
                if src.startswith("opus") and (fam != "bbeh" or int(t["id"].rsplit("-", 1)[1]) >= n // 2):
                    continue  # Opus on half the BBEH items only
                for c in range(calls):
                    right = rng.random() < p_right[src]
                    rows.append({"item": t["id"], "task_kind": fam, "meta_set": t["meta"].get("set"),
                                 "source": f"{src}:base", "ref": src, "call": c, "prompt": "base",
                                 "reply": replies[fam][0 if right else 1], "stop_reason": "end_turn", "truncated": False,
                                 "answer": None, "parsed": True, "correct": None, "cost_usd": 0.01 if src != "haiku_max"
                                 else 0.025, "seconds": 1.0, "output_tokens": 100, "thinking_tokens": 50 + c})
    rows[0] = {**rows[0], "truncated": True, "reply": replies["bbeh"][0]}  # a cut call is wrong whatever it says
    (res / "e60_cd_test_all").mkdir(parents=True)
    pd.DataFrame(rows).to_csv(res / "e60_cd_test_all/calls.csv", index=False)
    # the judge (Sonnet off over Haiku max's three calls) picks a right call whenever there is one: its eta is 1; the
    # stored answer is the pick as the run read it (BBEH: the answer; code: the picked program)
    frame = pd.DataFrame(rows)
    hm = frame[frame["source"] == "haiku_max:base"].assign(
        right=lambda d: d["reply"].isin([v[0] for v in replies.values()]))
    for fam, pick in (("bbeh", ("a b", "b a")), ("code", ("print(1)", "print(2)"))):
        any_right = hm[hm["task_kind"] == fam].groupby("item")["right"].any()
        judge = pd.DataFrame({"item": any_right.index, "task_kind": fam, "source": "sonnet_nothink:judge",
                              "prompt": "judge", "call": 0, "answer": [pick[0] if r else pick[1] for r in any_right],
                              "parsed": True, "correct": None, "stop_reason": "end_turn", "truncated": False,
                              "cost_usd": 0.005})
        (res / f"e60_cd_judge_{fam}").mkdir()
        judge.to_csv(res / f"e60_cd_judge_{fam}/calls.csv", index=False)
    import functools

    grades = res / "e60_cd_code_grades.csv"
    monkeypatch.setattr(R, "grade_code", functools.partial(GRADE_CODE, grades_file=grades, workers=2))
    out = R.read(res)
    calls = out["calls"]
    truth = pd.DataFrame(rows).assign(right=lambda d: d["reply"].isin([v[0] for v in replies.values()]))
    merged = calls.merge(truth[["item", "source", "call", "right"]], on=["item", "source", "call"])
    cut = merged["truncated"].astype(bool)
    assert (merged.loc[~cut, "correct"] == merged.loc[~cut, "right"].astype(float)).all() and merged.loc[cut, "correct"].eq(0).all()
    assert len(pd.read_csv(grades)) == 2 * n  # one grade per distinct (item, program): right and wrong per item
    before = grades.stat().st_mtime_ns
    R.grade_code(R.main_calls(res).query("task_kind == 'code'"))  # a second read reuses every grade
    assert grades.stat().st_mtime_ns == before
    assert out["CD2"]["k"] == 3 and out["CD1"]["gap_points"] > 0
    assert set(out["depth_curve"]["family"]) == {"bbeh", "math", "code", "all"}
    assert "post-cutoff math" in set(out["cd1_subsets"]["items"])
    assert set(out["CD1"]) >= {"R_bbeh", "R_code"} and "R_math" not in out["CD1"]  # CD1 on BBEH and code
    assert set(out["cd2_by_family"]["family"]) == {"bbeh", "math", "code"}
    judge = out["judge"].set_index(["family", "selection"])
    for fam in ("bbeh", "code"):
        assert judge.loc[(fam, "judge"), "eta"] == pytest.approx(1.0)
        assert judge.loc[(fam, "judge"), "accuracy"] == pytest.approx(judge.loc[(fam, "oracle"), "accuracy"])
        assert judge.loc[(fam, "judge"), "dollars_per_item"] == pytest.approx(3 * 0.025 + 0.005)
    assert judge.loc[("code", "execution"), "eta"] == pytest.approx(1.0)  # public tests = hidden tests here
    assert ("bbeh", "execution") not in judge.index
    assert set(out["opus"].query("family == 'bbeh'")["items"]) == {n // 2}
    sample = out["grader_sample"]
    assert sample.groupby(["family", "correct"]).size().max() <= 10 and set(sample["correct"]) == {0.0, 1.0}
    text = R.read_md(out)
    assert "## CD1 (BBEH and code) and CD2 (every family)" in text and "## Verification" in text


GRADE_CODE = R.grade_code


def probe_table(scale: dict[str, float]) -> pd.DataFrame:
    """A made-up probe table: every tier-A ref on every family at scale[model] dollars per call."""
    from analysis import cd_plan as PL

    refs = list(PL.HAIKU) + ["haiku_xhigh"] + list(PL.SONNET)
    rows = [{"ref": r, "task_kind": f, "usd_mean": scale[r.split("_")[0]] * (3.0 if r.endswith("max") else 1.0),
             "output_p99": 2000.0} for r in refs for f in PL.FAMILIES]
    t = pd.DataFrame(rows)
    return t.assign(ceiling_main=t["output_p99"].map(cd_probe.ceiling), guard_main=1.5 * t["usd_mean"])


def test_plan_adds_items_when_cheap_and_shrinks_the_sonnet_ladder_when_dear():
    from analysis import cd_plan as PL

    cheap = PL.plan(probe_table({"haiku": 0.001, "sonnet": 0.01}))
    assert cheap["k_probe"] == 3 and cheap["calls"]["haiku_xhigh"] == 5  # max costs 3x xhigh
    assert cheap["shares"] == {"sonnet_middle": 1.0, "haiku_middle": 1.0, "core": 1.0}
    assert cheap["projected_tier_a_usd"] <= PL.PLAN_A
    order = PL.reserve_order()
    taken = len(cheap["added"]["math"]) + len(cheap["added"]["code"])
    assert taken > 0 and [i for _, i in order[:taken]] == [i for f, i in order[:taken]]
    assert order[0][0] == "math" and order[1][0] == "code"
    assert cheap["projected_bridge_usd"] <= PL.PLAN_BRIDGE and cheap["ceilings"]["sonnet_max"]["math"] == 4096
    for dearer in (0.03, 0.06, 0.15):  # the ladder shrinks first, then Haiku's middle, then the core itself
        dear = PL.plan(probe_table({"haiku": 0.001, "sonnet": dearer}))
        assert dear["added"] == {"math": [], "code": []} and dear["shares"]["sonnet_middle"] < 1.0
        assert dear["projected_tier_a_usd"] <= PL.PLAN_A
    assert dear["shares"]["core"] < 1.0


def test_tier_a_configs_put_the_test_arms_on_every_item_and_the_ladder_on_its_share(tmp_path, monkeypatch):
    from analysis import cd_plan as PL

    sys.path.insert(0, str(ROOT / "scripts"))
    import make_cd_configs as M

    monkeypatch.setattr(M, "LISTS", tmp_path)
    plan = PL.plan(probe_table({"haiku": 0.001, "sonnet": 0.03}))  # the Sonnet ladder on 60% of the core
    configs = M.tier_a_configs(plan)
    assert {"e60_cd_haiku_math", "e60_cd_sonnet_lo_math", "e60_cd_sonnet_max_math", "e60_cd_sonnet_high_math"} <= set(configs)
    for name, cfg in configs.items():
        PanelConfig.model_validate(cfg)
        assert cfg["expect"]["max_truncation_rate"] == 0.02 and cfg["prereg"] == M.TIER_A_PREREG
    middle = read_ids(tmp_path / "math_sonnet_middle.txt")
    assert len(middle) == round(0.6 * 60) and middle == read_ids(SEALED / "math_core.txt")[: len(middle)]
    haiku = {(s["ref"], s.get("first_call", 0)): s for s in configs["e60_cd_haiku_code"]["sources"]}
    assert haiku[("haiku_max", 0)].get("items") is None and haiku[("haiku_max", 1)]["calls"] == 2
    assert haiku[("haiku_xhigh", 0)]["calls"] == plan["calls"]["haiku_xhigh"]


def test_run_cd_cuts_slices_at_the_stage_boundary():
    sys.path.insert(0, str(ROOT / "scripts"))
    import run_cd

    assert run_cd.clip([(0, 10, 1.0)], 0, 3) == [(0, 3, pytest.approx(0.3))]
    assert run_cd.clip([(0, 10, 1.0)], 3) == [(3, 7, pytest.approx(0.7))]
    assert [s[:2] for s in run_cd.clip([(0, 2, 1.0), (2, 2, 1.0), (4, 2, 1.0)], 3, 5)] == [(3, 1), (4, 1)]


def test_stage2_takes_the_cheapest_cells_up_to_the_cap():
    t = pd.DataFrame({"ref": ["a", "b", "c"], "task_kind": "math", "usd_mean": [0.01, 0.2, 0.05]})
    cells = cd_probe.stage2_cells(t, spent=1.0, cap=2.0)
    assert list(cells["ref"]) == ["a", "c", "b"] and list(cells["taken"]) == [True, True, False]  # 1.07, 1.42, 2.82


def test_stage2_configs_keep_only_the_taken_arms():
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_cd_configs as M

    out = M.probe_stage2_configs([("haiku_low", "math"), ("sonnet_nothink", "code")])
    assert set(out) == {"e60_cd_probe2_haiku_math", "e60_cd_probe2_sonnet_code"}
    assert [s["ref"] for s in out["e60_cd_probe2_haiku_math"]["sources"]] == ["haiku_low"]
    assert set(out["e60_cd_probe2_sonnet_code"]["expect"]["usd_per_call"]) == {"sonnet_nothink"}


def test_plan_v3_ceilings_prices_and_blocks(tmp_path, monkeypatch):
    """Audit 100: thinking arms on math and code at 128,000; off arms and BBEH at 1.5 x the longest call seen in the
    probe or E5 (a ref E5 did not run borrows its model's highest effort), at least 8,192; prices the larger of the
    probe's (cut calls at the ceiling) and E5's; blocks alternate math and code."""
    from analysis import cd_plan as PL

    sys.path.insert(0, str(ROOT / "scripts"))
    import make_cd_configs as M

    rows = []
    for ref in PL.CALLS_V3:
        for fam in PL.FAMILIES:
            for k in range(3):
                cut = ref == "sonnet_max" and fam == "math" and k > 0
                out = 65536 if cut else 1000
                rows.append({"item": f"x{k}", "task_kind": fam, "ref": ref, "output_tokens": out, "truncated": cut,
                             "cost_usd": out * (10 if ref.startswith("sonnet") else 0.5) / 1e6, "from_cache": False})
    e5 = pd.DataFrame({"ref": ["haiku_high", "sonnet_high"], "task_kind": ["bbeh", "math"],
                       "output_tokens": [18432, 36864], "cost_usd": [0.001, 0.17]})
    plan = PL.plan_v3(pd.DataFrame(rows), e5)
    c = plan["ceilings"]
    assert c["sonnet_low"]["math"] == c["haiku_low"]["code"] == PL.MODEL_MAX and c["sonnet_nothink"]["math"] == 8192
    assert c["haiku_max"]["bbeh"] == PL.MODEL_MAX and c["sonnet_max"]["bbeh"] == PL.MODEL_MAX  # audits 101, 102
    assert c["sonnet_high"]["bbeh"] == 16384
    assert c["haiku_nothink"]["bbeh"] == 8192
    assert plan["usd"]["sonnet_high"]["math"] == pytest.approx(0.17)  # E5's dearer price wins
    assert plan["usd"]["sonnet_max"]["math"] > (0.01 + 2 * 1.28) / 3 - 1e-9  # cut calls priced at 128,000
    assert [b[0] for b in PL.blocks()[:4]] == ["math", "code", "math", "code"] and PL.blocks()[0][1:] == (0, PL.BLOCK)
    post = [i for i in read_ids(SEALED / "math_core.txt") if i.startswith(PL.POST_CUTOFF)]
    assert plan["items"]["math"][: len(post)] == post and plan["expected_items"]["projected_usd"] <= PL.TIER_A_CAP
    monkeypatch.setattr(M, "LISTS", tmp_path)
    configs = M.tier_a_configs_v3(plan)
    assert configs["e60_cd_sonnet_max_math"]["expect"]["max_truncation_rate"] == 1.0
    assert configs["e60_cd_sonnet_off_math"]["expect"]["max_truncation_rate"] == 0.02
    assert configs["e60_cd_sonnet_bbeh"]["expect"]["max_truncation_rate"] == 0.02
    assert configs["e60_cd_haiku_think_bbeh"]["expect"]["max_truncation_rate"] == 1.0
    top = configs["e60_cd_sonnet_max_bbeh"]  # audit 102: Sonnet's top arms on BBEH at 128,000, on the sealed prefix
    assert top["expect"]["max_truncation_rate"] == 1.0 and top["sources"][0]["max_tokens"] == PL.MODEL_MAX
    assert read_ids(tmp_path / "bbeh_top_prefix.txt") == plan["items"]["bbeh"][: M.BBEH_TOP_PREFIX]
    assert {s["ref"] for s in configs["e60_cd_sonnet_bbeh"]["sources"]} == {
        "sonnet_nothink", "sonnet_low", "sonnet_med", "sonnet_high"}
    for cfg in configs.values():
        PanelConfig.model_validate(cfg)


def test_tier_a_runner_covers_items_by_their_calls_and_starts_at_the_first_gap(tmp_path, monkeypatch):
    """Audit 102: an item is covered when calls.csv has every call of every source of the config (a slice that stopped
    after making all its calls counts), and a config resumes at its first uncovered item, so nothing is replayed."""
    import shutil

    sys.path.insert(0, str(ROOT / "scripts"))
    import run_cd_tier_a as T
    from autoagentnet.evidence.panel import PanelConfig

    name = "e60_cd_sonnet_off_math"
    cfg = PanelConfig.from_yaml(ROOT / f"configs/experiments/v4/{name}.yaml")
    ids = read_ids(ROOT / cfg.items)
    (tmp_path / "configs/experiments/v4").mkdir(parents=True)
    shutil.copy(ROOT / f"configs/experiments/v4/{name}.yaml", tmp_path / f"configs/experiments/v4/{name}.yaml")
    (tmp_path / Path(cfg.items).parent).mkdir(parents=True)
    shutil.copy(ROOT / cfg.items, tmp_path / cfg.items)
    (tmp_path / "results" / name).mkdir(parents=True)
    pd.DataFrame({"item": ids[:3] + [ids[4]], "source": "sonnet_nothink:base", "call": 0}).to_csv(
        tmp_path / "results" / name / "calls.csv", index=False)
    monkeypatch.setattr(T, "ROOT", tmp_path)
    monkeypatch.setattr(T, "CONFIGS", tmp_path / "configs/experiments/v4")
    assert T.covered(name) == {0, 1, 2, 4} and T.done(name, 0, 3) and not T.done(name, 0, 5)
    started = []
    monkeypatch.setattr(T.subprocess, "run", lambda args, **kw: started.append(args) or
                        type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})())
    assert T.run(name, 0, 3) and started == []  # covered: nothing runs
    assert T.run(name, 0, 6) and started[0][started[0].index("--from-offset") + 1] == "3"


def test_no_truncation_stop_means_cut_calls_do_not_trip_the_unparsed_stop(tmp_path, monkeypatch):
    """Audit 101: a config that declares no truncation stop (max_truncation_rate 1.0, arms at the model maximum) runs on
    when a quarter of its calls are cut (they would otherwise count as unparsed); with the 2% stop it stops. Fake model;
    the config's providers, prices and budget are the repository defaults (paths relative to the repository root)."""
    import asyncio
    import json as J

    from autoagentnet.evidence import panel as PN

    monkeypatch.chdir(ROOT)
    tasks = tmp_path / "code.jsonl"
    tasks.write_text("".join(J.dumps({"id": f"c{i}", "prompt": "Print 1.", "answer": None, "grader": "exact",
                                      "meta": {"kind": "code"}}) + "\n" for i in range(8)))
    (tmp_path / "items.txt").write_text("".join(f"c{i}\n" for i in range(8)))
    original = PN.FakePanelClient.complete
    count = {"n": 0}

    async def cut_every_fourth(self, request):
        out = await original(self, request)
        count["n"] += 1
        return out.model_copy(update={"text": "Thinking...", "stop_reason": "max_tokens"}) if count["n"] % 4 == 0 else out

    monkeypatch.setattr(PN.FakePanelClient, "complete", cut_every_fourth)

    def run(rate: float) -> dict:
        cfg = PN.PanelConfig(kind="panel", name=f"cut_{rate}", task_kind="code", tasks=str(tasks),
                             items=str(tmp_path / "items.txt"), parser="v2", out_dir=str(tmp_path / "out"),
                             sources=[{"ref": "haiku_max", "calls": 3, "max_tokens": 128000}], model_override="fake",
                             expect={"min_calls": 20, "max_unparsed_rate": 0.05, "max_truncation_rate": rate})
        return asyncio.run(PN.run_panel(cfg))[1]

    assert run(1.0)["state"] == "completed"
    count["n"] = 0
    stopped = run(0.02)
    assert stopped["state"] == "stopped" and "truncated" in stopped["reason"]



def test_tier_a_runner_finishes_a_started_block_without_a_second_spend_test(tmp_path, monkeypatch):
    """Audit 104: a block whose range already has calls (a resume after a time limit) is finished whatever the $36
    projection says; an unstarted block that would pass $36 ends tier A."""
    import json as J

    sys.path.insert(0, str(ROOT / "scripts"))
    import run_cd_tier_a as T

    plan = {"items": {"bbeh": []}, "per_item_usd": {"math": 10.0, "code": 10.0}, "tier_a_cap": 36.0}
    monkeypatch.setattr(T.cd_plan, "PLAN_JSON", tmp_path / "plan.json")
    (tmp_path / "plan.json").write_text(J.dumps(plan))
    monkeypatch.setattr(T, "GROUPS", {"bbeh": [], "other": ["a", "b"]})
    monkeypatch.setattr(T, "tier_a_spent", lambda: 30.0)
    monkeypatch.setattr(T.cd_plan, "blocks", lambda: [("math", 0, 2), ("code", 0, 2)])
    have = {"e60_cd_a_math": {0, 1}}  # block 0 started: config a ran, config b did not
    monkeypatch.setattr(T, "covered", lambda name: have.get(name, set()))
    ran = []
    monkeypatch.setattr(T, "run", lambda name, start, end: ran.append(name) or True)
    monkeypatch.setattr(T.sys, "argv", ["run_cd_tier_a.py"])
    assert T.main() == 0
    assert ran == ["e60_cd_a_math", "e60_cd_b_math"]  # block 0 finished; block 1 ($20 more) would pass $36


def test_tier_b_configs_and_order(tmp_path, monkeypatch):
    """Tier B: the judge reads Haiku max's three calls; the second Sonnet max call is call 1; Opus runs in alternating
    blocks (max, then medium) after the judge and the second Sonnet call."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_cd_configs as M
    import run_cd_tier_b as B

    monkeypatch.setattr(M, "LISTS", tmp_path)
    configs = M.tier_b_configs(10)
    judge = configs["e60_cd_judge_code"]
    assert judge["sources"][0]["prompt"] == "judge" and judge["panel_sources"] == {"haiku_max:base": 3}
    assert configs["e60_cd_sonnet_max2_bbeh"]["sources"][0]["first_call"] == 1
    assert len(read_ids(tmp_path / "tier_b_bbeh_sonnet2.txt")) == M.SONNET2_BBEH
    for cfg in configs.values():
        PanelConfig.model_validate(cfg)
    monkeypatch.setattr(B.T, "n_items", lambda name: 57 if "judge_bbeh" in name else 17)
    order = B.steps(10)
    assert [s[0] for s in order[:4]] == ["e60_cd_judge_bbeh", "e60_cd_judge_code", "e60_cd_sonnet_max2_bbeh",
                                         "e60_cd_sonnet_max2_code"]
    assert order[4] == ("e60_cd_opus_max_bbeh", 0, 4) and order[5] == ("e60_cd_opus_med_bbeh", 0, 4)
    assert order[-1] == ("e60_cd_opus_med_code", 8, 10)


def test_bridge_configs_put_sol_low_first_in_its_own_config(tmp_path, monkeypatch):
    """The OpenAI bridge (audit 105): per family, Sol low alone in a config of its own on the tier A items, then Sol
    medium and Luna low x3 in a second config; math and code at OpenAI's documented 128,000 with no truncation stop,
    BBEH at 32,768 with the 2% stop."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import make_cd_configs as M

    monkeypatch.setattr(M, "LISTS", tmp_path)
    configs = M.bridge_configs({"bbeh": 57, "math": 10, "code": 10})
    for f in M.FAMILIES:
        low, rest = configs[f"e60_cd_open_sollow_{f}"], configs[f"e60_cd_open_{f}"]
        assert [s["ref"] for s in low["sources"]] == ["sol61_low"]
        assert [(s["ref"], s["calls"]) for s in rest["sources"]] == [("sol61_med", 1), ("luna_low_ev", 3)]
        assert {s["max_tokens"] for c in (low, rest) for s in c["sources"]} == ({32768} if f == "bbeh" else {128000})
        assert low["expect"]["max_truncation_rate"] == (0.02 if f == "bbeh" else 1.0)
        for cfg in (low, rest):
            PanelConfig.model_validate(cfg)
    assert [len(read_ids(tmp_path / f"bridge_{f}.txt")) for f in M.FAMILIES] == [57, 10, 10]


def test_code_calls_keep_their_own_hidden_test_grades():
    """Audit 106: programs with the same outputs on the public tests can differ on the hidden tests. Each code call
    keeps its own grade, the programs still vote together, and a winning class is scored by the arm's first call in it."""
    from analysis.anchor_read import per_call_accuracy

    grades = {"sonnet_nothink": 0.0, "sonnet_max": 1.0, "sol61_low": 1.0}
    xhigh = {"y0": (0.0, 1.0, 1.0), "y1": (1.0, 0.0, 0.0)}
    rows = [{"item": item, "task_kind": "code", "source": f"{src}:base", "call": c, "answer": "out:1", "parsed": True,
             "correct": g, "cost_usd": 0.01, "seconds": 1.0}
            for item in xhigh
            for src, c, g in [(s, 0, grades[s]) for s in grades] + [("haiku_xhigh", k, xhigh[item][k]) for k in range(3)]]
    units = ["sonnet_nothink:base:0", "sonnet_max:base:0", "sol61_low:base:0"]
    p, fams = R.panel_of(pd.DataFrame(rows), units + R.units("haiku_xhigh", 3))
    assert [per_call_accuracy(p, [u]).mean() for u in units] == [0.0, 1.0, 1.0]
    assert list(R.vote_cd(p, R.units("haiku_xhigh", 3))) == [0.0, 1.0]  # one public-output class: its first call
    assert R.cd1(p, fams, *[[u] for u in units])["estimate"] == pytest.approx(1.0)


def test_the_code_judge_takes_the_picked_programs_own_grade():
    """Audit 108: the judge's code pick (the stored program) takes the grade of the Haiku max call that wrote it, not a
    second run of the program (here the second run says 0 and the call's own grade 1)."""
    rows = []
    for item, grades in (("y0", (0.0, 1.0, 0.0)), ("y1", (1.0, 1.0, 1.0))):
        rows += [{"item": item, "task_kind": "code", "source": "haiku_max:base", "call": c, "answer": f"h{c}",
                  "parsed": True, "correct": g, "code": f"print({c})\n", "exec_visible": 0.0, "truncated": False,
                  "cost_usd": 0.01, "seconds": 1.0} for c, g in enumerate(grades)]
        rows.append({"item": item, "task_kind": "code", "source": "sonnet_nothink:base", "call": 0, "answer": "s",
                     "parsed": True, "correct": 0.0, "code": "pass", "exec_visible": 0.0, "truncated": False,
                     "cost_usd": 0.02, "seconds": 1.0})
    judges = pd.DataFrame({"item": ["y0", "y1"], "task_kind": "code", "pick": ["print(1)", "print(2)"],
                           "answer": ["h1", "h2"], "correct": [0.0, 0.0], "cost_usd": 0.005, "truncated": False})
    out = R.judge_read(pd.DataFrame(rows), judges).set_index("selection")
    assert out.loc["judge", "accuracy"] == pytest.approx(1.0)  # both picks' own grades are 1
    assert out.loc["judge", "eta"] == pytest.approx(1.0) and out.loc["oracle", "accuracy"] == pytest.approx(1.0)
