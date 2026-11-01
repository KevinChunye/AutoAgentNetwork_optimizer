"""The analysis recovers what the synthetic world puts in (T1-T5), and tells planted alternatives apart.

Each world is a fixed draw (named salt), 300 items (200 BBEH-like, 100 math-like), 2B/4B/9B x BF16/W4 x thinking
off/1k, k = 6. research/v4/testbed/power.csv repeats these checks over many draws at the full stage-1 design."""

from dataclasses import replace

import numpy as np
import pytest

from autoagentnet.testbed import analysis, compose, grid, power
from autoagentnet.testbed.world import World

CONFIGS = [grid.Config(grid.QWEN, s, p, b) for s in (2, 4, 9) for p in ("bf16", "w4") for b in (0, 1024)]
JUDGE = grid.Config(grid.QWEN, 9, "bf16", 4096)
WORLDS = power.worlds()


def make(params, salt="recovery"):
    world = World({"bbeh": 200, "math": 100}, params, salt=salt)
    table = compose.add_classes(world.table(CONFIGS, 6), {"bbeh": "exact", "math": "exact"})
    return world, table, compose.Samples.from_table(table)


@pytest.fixture(scope="module")
def default():
    return make(WORLDS["default"])


def test_t1_a_strong_shared_quantization_shock_is_detected():
    _, table, s = make(WORLDS["strong"])
    r = analysis.t1(table, s, n_boot=300)
    for name in ("primary", "shared_shock", "concentration"):
        assert r[name]["supported"], name
    assert r["literal"]["counts"] and r["literal"]["supported"]  # 6 W4 copies stay below 1 BF16 on hard items
    assert (r["cells"]["disattenuated_r"] < 1).mean() > 0.8  # per cell; one cell may scatter above 1


def test_t1_a_pure_shift_is_not_mistaken_for_a_shared_shock(default):
    _, table, s = make(WORLDS["pure_shift"])
    shift = analysis.t1(table, s, n_boot=300)
    _, table2, s2 = make(WORLDS["strong"])
    strong = analysis.t1(table2, s2, n_boot=300)
    assert not shift["shared_shock"]["supported"] and shift["shared_shock"]["low"] < 0 < shift["shared_shock"]["high"]
    assert shift["shared_shock"]["estimate"] < strong["shared_shock"]["estimate"]
    _, t3, s3 = default
    mild = analysis.t1(t3, s3, n_boot=300)
    assert not mild["literal"]["supported"]  # at the default's small W4 loss, 6 W4 copies are not below 1 BF16


def test_t3_depth_and_width_both_directions(default):
    _, table, s = default
    deep = analysis.t3(table, s, pairs=((1024, 0),))
    assert deep["primary"]["supported"] and deep["primary"]["estimate"] > 0
    _, flat, sf = make(replace(WORLDS["default"], gamma=0.0))  # thinking adds nothing: width must win
    wide = analysis.t3(flat, sf, pairs=((1024, 0),))
    assert wide["primary"]["supported"] and wide["primary"]["estimate"] < 0
    assert (wide["cells"]["k_high"] >= 3).all()  # the wide arm mixes odd votes, never a 2-vote


def test_t2_equal_memory_cells_and_judge_columns(default):
    world, table, s = default
    w8 = [grid.Config(grid.QWEN, sz, "w8", b) for sz in (2, 4, 9) for b in (0, 1024)]
    t = compose.add_classes(world.table(CONFIGS + w8, 6), {"bbeh": "exact", "math": "exact"})
    checks, picks = world.checks(t, JUDGE, candidates={c.label: 2 for c in w8})
    r = analysis.t2(t, compose.Samples.from_table(t), picks, JUDGE.label)
    cells = r["cells"]
    assert len(cells) == 6 and {"vote_4xw4", "single_w8", "single_bf16", "judge_4xw4", "judge_2xw8"} <= set(cells)
    assert (cells["judge_4xw4"] >= cells["vote_4xw4"] - 0.02).all()  # a skilled judge beats a vote of 4


def test_t4_coupling_is_found_only_where_it_was_planted(default):
    world, table, _ = default
    checks, picks = world.checks(table, JUDGE)
    r = analysis.t4(table, checks, picks, [JUDGE.label])
    assert r["primary"]["supported"] and r["primary"]["estimate"] > 0.1
    eta = r["eta"]
    overall = eta[(eta["tercile"] == "all") & (eta["m"] == "all")].set_index("checker")["eta"]
    assert overall["margin"] > 0.2 and overall["self_check"] > 0  # signals carry information
    flat_world, flat_table, _ = make(WORLDS["flat_judge"])
    c2, p2 = flat_world.checks(flat_table, JUDGE)
    flat = analysis.t4(flat_table, c2, p2, [JUDGE.label])
    assert not flat["primary"]["supported"]
    cfg_world, cfg_table, _ = make(WORLDS["config_judge"])  # skill set by the candidates' model size, not difficulty
    c3, p3 = cfg_world.checks(cfg_table, JUDGE)
    assert not analysis.t4(cfg_table, c3, p3, [JUDGE.label])["primary"]["supported"]
    bench_world, bench_table, _ = make(replace(WORLDS["bench_judge"], judge_d_by_bench={"bbeh": 2.5, "math": 1.0},
                                               bench_mean={"bbeh": 0.0, "math": 2.0}))  # skill by benchmark only
    c4, p4 = bench_world.checks(bench_table, JUDGE)
    assert not analysis.t4(bench_table, c4, p4, [JUDGE.label])["primary"]["supported"]


def test_t4_eta_rises_with_right_candidates_even_for_a_constant_judge():
    """The arithmetic audit T1-1 found: eta grows with the number of right candidates m for a judge of fixed skill,
    which is why T4 compares terciles within m."""
    flat_world, flat_table, _ = make(WORLDS["flat_judge"])
    c2, p2 = flat_world.checks(flat_table, JUDGE)
    eta = analysis.t4(flat_table, c2, p2, [JUDGE.label])["eta"]
    by_m = eta[eta["checker"].str.startswith("judge") & (eta["tercile"] == "all")].set_index("m")["eta"]
    assert by_m["1"] < by_m["2"] < by_m["3"]


def t5_at_full_design(world_name):
    world = World(power.ITEMS, WORLDS[world_name], salt="t5a")
    table = compose.add_classes(world.table(grid.stage1([]), 6), power.GRADERS)
    items = np.random.default_rng(0).permutation(sorted(table["item"].unique()))
    cut = int(0.7 * len(items))
    return analysis.t5(table, list(items[:cut]), list(items[cut:]), escalate=JUDGE.label, draws=200)


def test_t5_predicts_held_out_compositions_without_seeing_them():
    """Fit on call 0 of the held-out items, scored on calls 1-5 (no circularity), at the stage-1 design (36 configs,
    363 items). Against the answer-space-adapted baseline the model's edge is small and not reliable in the synthetic
    world (power.csv), so T5 is exploratory; this checks the machinery and the error level."""
    r = t5_at_full_design("default")
    p, comps = r["primary"], r["compositions"]
    assert set(comps["kind"]) == {"vote", "mixprec", "mixsize", "cascade"}
    votes = comps[comps["kind"] == "vote"]
    assert not votes["composition"].str.endswith("x6").any()  # calls 1-5 only: at most 5 samples of one config
    assert comps[["predicted", "baseline"]].notna().all().all() and p["mae"] < 0.03 and p["baseline_mae"] < 0.03


def test_t3_wide_arm_mixes_neighbouring_odd_votes(default):
    _, table, s = default
    system = "qwen3.5-4b:bf16:off"
    mixed, (lo, hi, w) = analysis.odd_mixture(s, system, 2.0, 5)
    assert (lo, hi, w) == (1, 3, 0.5)
    expected = 0.5 * compose.expected_vote(s, [(system, 1)]) + 0.5 * compose.expected_vote(s, [(system, 3)])
    assert np.allclose(mixed, expected)
    assert analysis.odd_mixture(s, system, 3.0, 5)[1] == (3, 3, 1.0)


def test_votes_and_cascades_replay_exactly():
    # item 0: classes 0 0 1 (class 0 right); item 1: 0 1 2 tie (class 2 right); item 2: unparsed only
    C = np.array([[0, 0, 1], [0, 1, 2], [-1, -1, -1]])
    right = np.array([[1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 0]], dtype=float)
    R = np.array([[1, 1, 0], [0, 0, 1], [0, 0, 0]], dtype=float)
    assert compose.vote_credit(C, R, 4).tolist() == [1.0, pytest.approx(1 / 3), 0.0]
    # code: one behaviour class whose two members differ on hidden tests scores their mean, not a pooled rate
    assert compose.vote_credit(np.array([[0, 0, 1]]), np.array([[1.0, 0.0, 0.0]]), 2).tolist() == [0.5]
    s = compose.Samples(["a", "b", "c"], 3, {"x": C, "e": np.zeros((3, 3), dtype=int)},
                        {"x": (C == 0).astype(float) * [[1], [0], [0]], "e": np.ones((3, 3))},
                        {"x": np.ones((3, 3)), "e": 10 * np.ones((3, 3))}, right)
    credit, seconds = compose.expected_cascade(s, [("x", 3)], "e", 2 / 3)
    assert credit.tolist() == [1.0, 1.0, 1.0] and seconds.tolist() == [3.0, 13.0, 13.0]
