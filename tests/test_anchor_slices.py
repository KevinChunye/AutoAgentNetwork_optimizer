"""Slice planning under the run cap (scripts/anchor_slices.py). Offline."""

import pytest
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("anchor_slices", Path(__file__).resolve().parents[1] / "scripts/anchor_slices.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def test_slices_cover_every_item_once_and_fit_the_cap():
    worst = [0.3, 0.3, 0.3, 1.0, 0.2, 0.9, 0.9, 0.1]
    out = S.slices(worst, cap=1.0)
    assert sum(n for _, n, _ in out) == len(worst)
    assert [o for o, _, _ in out] == sorted(o for o, _, _ in out)
    assert all(total <= 0.95 or n == 1 for _, n, total in out)  # a single item may exceed the fill alone


def test_run_anchor_keeps_the_slices_between_two_offsets():
    """Audit 84: a long config runs in several invocations that each end between slices."""
    spec = importlib.util.spec_from_file_location("run_anchor", Path(__file__).resolve().parents[1] / "scripts/run_anchor.py")
    run_anchor = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(run_anchor)
    plan = [(k * 10, 10, 3.0) for k in range(44)]
    parts = [run_anchor.between(plan, a, b) for a, b in ((0, 110), (110, 220), (220, 330), (330, None))]
    assert [len(p) for p in parts] == [11, 11, 11, 11] and sum(parts, []) == plan
    assert run_anchor.between(plan, 215) == plan[22:]


@pytest.mark.needs_external("bbeh_all.jsonl", "evidence/math.jsonl")
def test_cache_proof_counts_the_keys_the_runner_would_hit():
    """Audit 87: scripts/cache_proof.py makes the runner's keys (MarketCaller's formula over requests_for) and counts
    the cached ones; here one of the slice's three calls is put in an in-memory cache."""
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("cache_proof", root / "scripts/cache_proof.py")
    proof = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(proof)
    cfg = proof.PanelConfig.from_yaml(root / "configs/experiments/v4/e51_sol_math_low.yaml").model_copy(
        update={"task_limit": 1})
    registry = proof.ProviderRegistry.from_yaml(root / cfg.providers)
    cache = proof.CallCache()
    item, source, c, request = proof.requests_for(cfg, proof.select_items(cfg), {"sol61_low": "sol61_low"})[1]
    cache.put(proof.make_key(request.spec.model_dump(), registry.model_id("sol61_low"), registry.options_of("sol61_low"),
                             request.input.model_dump(), c), "{}")
    table = proof.cache_hits(cfg, cache, registry)
    assert table.to_dict("records") == [{"source": "sol61_low:base", "calls": 3, "hits": 1}]


def test_verification_checks_names_every_verification_config():
    """scripts/verification_checks.py (audit 94) checks every anchor verification config, each of which exists."""
    ROOT = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location("verification_checks", ROOT / "scripts/verification_checks.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # defines main() only; nothing runs at import
    assert set(mod.CONFIGS) == {"e51_verify_anth_bbeh", "e51_verify_anth_math", "e51_verify_open_bbeh",
                                "e51_judge_open_bbeh", "e51_verify_open_math", "e51_judge_open_math"}
    assert all((ROOT / f"configs/experiments/v4/{n}.yaml").exists() for n in mod.CONFIGS) and callable(mod.main)
