"""Grid, seeds, sealing, the GPU ledger's stop rule, fake quantization, task selection and the schema check."""

import base64
import json
import pickle
import zlib

import numpy as np
import pandas as pd
import pytest

from autoagentnet.testbed import gpu_ledger, grid, quantize, seal, tasks
from autoagentnet.testbed.table import validate
from autoagentnet.tasks import Task


def test_stage_grids_and_labels():
    s1 = grid.stage1()
    assert len(s1) == 36 and len({c.label for c in s1}) == 36 and len(grid.checkpoints(s1)) == 12
    assert len(grid.pilot()) == 4 and {c.size_b for c in grid.pilot()} == {4}
    c = grid.Config("qwen3.5", 4, "w4", 1024)
    assert (c.checkpoint, c.label, c.ref(2)) == ("qwen3.5-4b-w4", "qwen3.5-4b:w4:budget:1024", "qwen3.5-4b:w4:budget:1024:s2")
    assert c.weight_gb == 2.0


def test_seeds_differ_across_configs_and_samples_and_are_reproducible():
    seeds = {grid.seed_of(c.label, j) for c in grid.stage1() for j in range(6)}
    assert len(seeds) == 36 * 6 and grid.seed_of("x", 1) == grid.seed_of("x", 1)


def test_registry_gives_each_sample_its_seed_and_the_card_sampling():
    configs = [grid.Config("qwen3.5", 4, "bf16", 1024), grid.Config("qwen3.5", 4, "bf16", 0)]
    reg = grid.registry_for(configs, 6, "http://h:1")
    opts = reg.options_of(configs[0].ref(3))
    assert opts["seed"] == grid.seed_of(configs[0].label, 3) and opts["thinking_budget"] == 1024
    assert opts["presence_penalty"] == 1.5 and reg.options_of(configs[1].ref(0))["thinking_budget"] == 0
    assert reg.provider_of(configs[0].ref(0)) == "vllm_local"


def test_estimate_puts_stage_one_near_the_brief_prior():
    est = grid.stage_estimate("stage1", 363)
    assert 5 < est["hours"] < 20 and est["usd"] == pytest.approx(est["hours"] * 5.45, abs=0.05)
    assert grid.stage_estimate("pilot", 50)["usd"] < 10


def test_seal_writes_hashes_and_unseals_once(tmp_path):
    items = [f"i{j:03d}" for j in range(100)]
    info = seal.seal(items, tmp_path)
    assert info["fit"] == 70 and info["heldout"] == 30
    fit = seal.fit_items(tmp_path)
    with pytest.raises(PermissionError):
        seal.heldout(tmp_path)
    held = seal.heldout(tmp_path, unseal=True, reason="test")
    assert set(fit) | set(held) == set(items) and not set(fit) & set(held)
    with pytest.raises(PermissionError):
        seal.heldout(tmp_path, unseal=True)
    assert seal.heldout(tmp_path, unseal=True, again=True) == held
    assert "AGAIN" in (tmp_path / "UNSEAL_LOG.md").read_text()
    with pytest.raises(FileExistsError):
        seal.seal(items, tmp_path)
    (tmp_path / "fit.txt").write_text("\n".join(fit[1:]) + "\n")
    with pytest.raises(ValueError):
        seal.fit_items(tmp_path)


def test_gpu_ledger_bills_wall_clock_and_stops_before_a_cap(tmp_path, monkeypatch):
    ledger, clock = tmp_path / "gpu_ledger.csv", tmp_path / "clock.json"
    now = [1000.0]
    monkeypatch.setattr(gpu_ledger.time, "time", lambda: now[0])
    gpu_ledger.start("studio-1", "H100", 5.0, clock)
    now[0] += 3600  # one hour
    row = gpu_ledger.tick("pilot", "setup", ledger=ledger, clock=clock)
    assert row["hours"] == 1.0 and row["usd"] == 5.0
    assert gpu_ledger.guard("pilot", 0.9, ledger=ledger, clock=clock)["next_usd"] == 4.5
    with pytest.raises(gpu_ledger.GPUBudgetExceeded, match="pilot"):
        gpu_ledger.guard("pilot", 1.1, ledger=ledger, clock=clock)  # 5 + 5.5 > 10
    now[0] += 3600  # an unbilled hour counts too
    with pytest.raises(gpu_ledger.GPUBudgetExceeded):
        gpu_ledger.guard("pilot", 0.1, ledger=ledger, clock=clock)
    gpu_ledger.tick("stage1", "big", ledger=ledger, clock=clock)
    now[0] += 3600 * 14
    gpu_ledger.tick("stage1", "bigger", ledger=ledger, clock=clock)  # $80 spent in all
    with pytest.raises(gpu_ledger.GPUBudgetExceeded, match="stage 2 needs"):
        gpu_ledger.guard("stage2", 0.1, ledger=ledger, clock=clock)
    with pytest.raises(gpu_ledger.GPUBudgetExceeded, match="hard stop"):
        gpu_ledger.guard("stage1", 2.1, ledger=ledger, clock=clock)
    assert gpu_ledger.spent(ledger) == pytest.approx(80.0)


def test_rtn_fake_quantization():
    rng = np.random.default_rng(0)
    W = rng.standard_normal((8, 256)).astype(np.float32)
    w8, w4, w3 = quantize.rtn(W, 8), quantize.rtn(W, 4, 128), quantize.rtn(W, 3, 128)
    err = lambda a: np.linalg.norm(a - W) / np.linalg.norm(W)
    assert err(w8) < 0.01 < err(w4) < err(w3) < 0.4
    assert np.array_equal(quantize.rtn(w4, 4, 128), w4)  # idempotent: already on the grid
    for g in range(2):  # at most 2^b levels per group
        assert len(np.unique(w3[0, g * 128:(g + 1) * 128])) <= 8
    with pytest.raises(ValueError):
        quantize.rtn(W[:, :100], 4, 128)


def test_export_rtn_touches_only_the_quantized_layers(tmp_path):
    rng = np.random.default_rng(1)
    names = ["model.language_model.layers.0.mlp.down_proj.weight", "model.language_model.layers.0.self_attn.q_proj.weight",
             "model.language_model.layers.1.linear_attn.in_proj_qkvz.weight", "model.language_model.embed_tokens.weight",
             "lm_head.weight", "model.language_model.layers.0.input_layernorm.weight", "model.visual.blocks.0.mlp.fc1.weight"]
    src = {n: rng.standard_normal((4, 128) if "norm" not in n else (128,)).astype(np.float32) for n in names}
    store = {}
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "model.safetensors").write_text("x")
    (tmp_path / "src" / "config.json").write_text("{}")
    meta = quantize.export_rtn(tmp_path / "src", tmp_path / "dst", 4, 128, load=lambda p: src,
                               save=lambda arrays, p: store.update(arrays))
    report = quantize.compare(src, store)
    assert meta["quantized_tensors"] == 2 and report["changed"] == 2 and report["unexpected"] == []
    assert (tmp_path / "dst" / "config.json").exists() and (tmp_path / "dst" / "quantization.json").exists()


def bbeh_task(name, j):
    return Task(id=f"bbeh-{name}-{j:04d}", prompt="q", answer="a", grader="bbeh")


def test_bbeh_items_skip_sealed_ids_and_draw_by_salted_hash():
    pool = [bbeh_task(n, j) for n in ("web_of_lies", "word_sorting") for j in range(30)]
    sealed = {f"bbeh-web_of_lies-{j:04d}" for j in range(10)}
    picked = tasks.bbeh_items(pool, ["web_of_lies", "word_sorting"], sealed, 15, "s")
    assert len(picked) == 30 and not {t.id for t in picked} & sealed
    assert {t.meta["subtask"] for t in picked} == {"web_of_lies", "word_sorting"}
    assert [t.id for t in picked] == [t.id for t in tasks.bbeh_items(pool[::-1], ["web_of_lies", "word_sorting"], sealed, 15, "s")]
    with pytest.raises(ValueError):
        tasks.bbeh_items(pool, ["web_of_lies"], sealed, 25, "s")


def test_read_anchor_accepts_e5s_announced_shape_and_older_ones(tmp_path):
    path = tmp_path / "tasks.json"
    path.write_text(json.dumps({"tasks": ["web of lies", "boardgame qa"], "groups": [], "rule": "r",
                                "sealed_bbeh": ["bbeh-web_of_lies-0001"], "t1_bbeh": ["bbeh-web_of_lies-0002"]}))
    assert tasks.read_anchor(path) == (["web_of_lies", "boardgame_qa"], {"bbeh-web_of_lies-0001"},
                                       {"bbeh-web_of_lies-0002"})
    path.write_text(json.dumps({"tasks": ["web of lies", {"name": "dyck languages", "sealed_ids": ["x1"]}],
                                "sealed": ["x2"]}))
    assert tasks.read_anchor(path) == (["web_of_lies", "dyck_languages"], {"x1", "x2"}, set())
    path.write_text(json.dumps({"tasks": ["a"], "sealed_bbeh": ["x"], "t1_bbeh": ["x"]}))
    with pytest.raises(ValueError, match="both reserved"):
        tasks.read_anchor(path)
    path.write_text(json.dumps({"other": 1}))
    with pytest.raises(ValueError):
        tasks.read_anchor(path)


def test_lcb_tests_decode_and_a_tampered_pickle_is_refused():
    tests = [{"input": "1", "output": "2", "testtype": "stdin"}]
    packed = base64.b64encode(zlib.compress(pickle.dumps(json.dumps(tests)))).decode()
    assert tasks.decode_tests(packed) == tests and tasks.decode_tests(json.dumps(tests)) == tests
    evil = base64.b64encode(zlib.compress(pickle.dumps(pd.Timestamp(0)))).decode()
    with pytest.raises(pickle.UnpicklingError):
        tasks.decode_tests(evil)


def test_world_tables_pass_the_atlas_schema_and_labels_round_trip():
    from autoagentnet.testbed.world import World

    t = World(5).table(grid.pilot(), 2)
    v = validate(t)
    assert set(v["reasoning"]) == {"off", "budget:1024"} and set(v["benchmark"]) == {"bbeh/synthetic"}
    with pytest.raises(ValueError, match="missing required"):
        validate(t.drop(columns="licence"))
    with pytest.raises(ValueError, match="unknown columns"):
        validate(t.assign(extra=1))
    for c in grid.stage1() + grid.stage2():
        assert grid.Config.from_label(c.label) == c


def test_drop_rule_and_scope(tmp_path, monkeypatch):
    monkeypatch.setattr(grid, "SCOPE_YAML", tmp_path / "scope.yaml")
    (tmp_path / "scope.yaml").write_text("drop_precisions: [w3]\nkernel_run: false\n")
    assert len(grid.stage1()) == 27 and grid.scope()["kernel_run"] is False
    monkeypatch.setattr(grid, "THROUGHPUT_JSON", tmp_path / "throughput.json")  # no pilot yet: priors
    full = grid.stage_estimate("stage1", 363, machine="H200", drop_precisions=[], kernel_run=True)
    plan = grid.recommended_scope(363, machine="H200")
    assert full["usd"] > 45 >= plan["estimate"]["usd"] and plan["drop_precisions"] == ["w3"]
    tight = grid.recommended_scope(363, machine="H100", limit_usd=1, cap_usd=2)
    assert tight["decision"] == "stop and hand back"


def test_pilot_measurements_drive_the_estimates(tmp_path, monkeypatch):
    monkeypatch.setattr(grid, "THROUGHPUT_JSON", tmp_path / "throughput.json")
    before = grid.checkpoint_hours("stage1", "qwen3.5-4b-bf16", 363, machine="H100")
    (tmp_path / "throughput.json").write_text(json.dumps(
        {"scale": 0.5, "tokens_per_call": {"0": 800, "1024": 1600, "4096": 4500}, "overhead": 2.0}))
    after = grid.checkpoint_hours("stage1", "qwen3.5-4b-bf16", 363, machine="H100")
    assert after > 3 * before  # half the speed, more tokens, a larger overhead


def test_pilot_seeds_differ_from_stage_one_seeds():
    c = grid.Config(grid.QWEN, 4, "bf16", 1024)
    pilot = grid.registry_for([c], 2, "http://h", seed_salt=grid.SEED_SALT["pilot"])
    stage1 = grid.registry_for([c], 2, "http://h")
    assert pilot.options_of(c.ref(0))["seed"] != stage1.options_of(c.ref(0))["seed"]


def test_power_calibration_recovers_the_pilot_world():
    from dataclasses import replace

    from autoagentnet.testbed import power
    from autoagentnet.testbed.world import World, WorldParams

    truth = replace(WorldParams(), a0=0.5, gamma=1.5, delta={**WorldParams().delta, "w4": 0.4})
    pilot = World(400, truth, salt="pilot-truth").table(grid.pilot(), 6)
    fitted = power.calibrate(pilot, grid_a0=np.arange(0, 1.01, 0.25), grid_gamma=np.arange(0.5, 2.51, 0.5),
                             grid_delta=np.arange(0.0, 0.81, 0.2), items=400)
    step = 0.2 + 1e-9  # within one grid step of the truth (ability and the W4 shift partly trade off)
    assert abs(fitted["a0"] - 0.5) <= 0.25 + 1e-9 and abs(fitted["gamma"] - 1.5) <= 0.5 and abs(fitted["delta_w4"] - 0.4) <= step


def test_e5_anchor_lists_match_their_manifest_and_t1_uses_the_reserved_ids():
    import hashlib
    import re

    from conftest import ROOT

    anchor = ROOT / "research/v4/anchor"
    manifest = (anchor / "sealed/MANIFEST.md").read_text()
    for name in ("t1_bbeh.txt", "sealed/bbeh_anchor.txt"):
        digest = re.search(rf"\| {re.escape(name)} \| \d+ \| `([0-9a-f]{{64}})`", manifest).group(1)
        assert hashlib.sha256((anchor / name).read_bytes()).hexdigest() == digest, name
    names, sealed, reserved = tasks.read_anchor(anchor / "tasks.json")
    assert names == ["linguini", "nycc", "word_sorting", "causal_understanding"]
    assert len(reserved) == 200 and not reserved & sealed and not reserved & tasks.scan_ids(anchor)
    pool = [Task(id=i, prompt="q", answer="a", grader="bbeh") for i in sorted(reserved | sealed)]
    picked = tasks.bbeh_items([t for t in pool if t.id in reserved], names, sealed, 50, "ow-testbed-v1")
    assert {t.id for t in picked} == reserved
