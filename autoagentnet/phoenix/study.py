"""Generate draft preregistered study configs. This never runs their experiments."""
from __future__ import annotations

import json
import random
from pathlib import Path

import yaml

from .data import DATASETS
from .prompts import parse_json
from .run import POLICIES, PhoenixConfig, frozen_inputs
from .store import atomic_json, file_sha


def matrix(root, data_root, checkpoint_root, capability_table, results_root="results"):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    configs, cases = [], []

    def write(case, experiment, policy, budget, fault, fixed_pool=None):
        name = f"{experiment}_{case['id']}_{policy}_{fault}_{int(budget*100):02d}"
        raw = {"kind": "phoenix", "name": name, "checkpoint": case["checkpoint"],
               "capability_table": str(capability_table), "policy": policy, "fault": fault,
               "withdrawn_model": case["withdrawn_model"], "seed": case["seed"],
               "api_budget_usd": budget, "out_dir": str(results_root),
               "prereg": {"question": "Can dependency-constrained recovery improve final quality and future cost?",
                           "prediction": "The full heuristic may reduce redundant work; no advantage is guaranteed.",
                           "kill": "Stop on input/hash, availability, budget, provenance or test-isolation violations.",
                           "decision": "Report all paired outcomes; do not change cases, budgets or repeats after reading results."}}
        if fixed_pool:
            raw["fixed_proposals"] = str(fixed_pool)
        cfg = PhoenixConfig.model_validate(raw)
        path = root / (name+".yaml")
        path.write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False))
        configs.append({"name": name, "config": str(path), "case_id": case["id"], "experiment": experiment,
                        "policy": policy, "fault": fault, "budget": budget,
                        "frozen": str(Path(results_root) / name / "frozen.json"),
                        "sealed_test": str(Path(data_root) / case["dataset"] / "sealed_test.npz")})

    for dataset in DATASETS:
        for template in ("T1", "T2"):
            for seed in (101, 102, 103):
                case = {"id": f"{dataset}_{template}_{seed}", "dataset": dataset, "template": template,
                        "seed": seed, "checkpoint": str(Path(checkpoint_root) / f"{dataset}_{template}_{seed}"),
                        "withdrawn_model": ("sonnet_low", "sol61_low")[len(cases) % 2]}
                cases.append(case)
                for policy in POLICIES:
                    for budget in (0.05, 0.20):
                        write(case, "E1", policy, budget, "F1")
                for fault, experiment in (("F0", "E2"), ("healthy", "E3")):
                    for policy in ("fixed", "full"):
                        write(case, experiment, policy, 0.20, fault)
                pool = root / "pools" / (case["id"]+".json")
                for policy in ("full", "no_dependency", "no_cost", "llm"):
                    write(case, "E4", policy, 0.20, "F1", pool)
    assert len(cases) == 18 and len(configs) == 360
    order = [r["config"] for r in configs]
    random.Random(2026).shuffle(order)
    manifest = {"schema": 1, "status": "draft_not_frozen", "cases": cases, "branches": configs,
                "run_order": order, "capability_table": str(capability_table),
                "note": "Prepare checkpoints/calibration first; freeze and commit each config before paid runs."}
    atomic_json(root / "study_manifest.json", manifest)
    return manifest


def freeze_config(path):
    cfg = PhoenixConfig.from_yaml(path)
    cfg.frozen_hashes = frozen_inputs(cfg)
    Path(path).write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False))
    return cfg.frozen_hashes


def calibration_configs(root, data_root, results_root="results"):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    paths = [str(Path(data_root) / dataset / f"calibration_{seed}.npz")
             for dataset in DATASETS for seed in (1, 2, 3)]
    configs = []
    for model in ("luna_low_ev", "sol61_low", "sonnet_low"):
        cfg = PhoenixConfig(name="phoenix_calibration_"+model, mode="calibrate", calibration_model=model,
            calibration_data=paths, max_calls=30, max_tools=1000, cpu_budget_s=600,
            api_budget_usd=3.0, out_dir=str(results_root),
            prereg={"question": "Estimate development-only action quality, completion and cost.",
                    "prediction": "Calibration describes model/action behavior; it is not a held-out result.",
                    "kill": "Stop on data leakage, transport uncertainty, inaccessible models or caps.",
                    "decision": "Freeze observed statistics, including failures and zeros; never insert test outcomes."})
        path = root / (cfg.name+".yaml")
        path.write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False))
        configs.append(str(path))
    return configs


def extract_proposal_pool(source_run, out):
    """E4's predeclared source: FIRST E1/full/$0.20 proposal, never the best-looking one."""
    source = Path(source_run)
    state = json.loads((source / "state.json").read_text())
    calls = [r for r in state["calls"] if r["purpose"] == "propose"]
    if not calls:
        payload = {"proposals": [], "unavailable": True, "reason": "source has no first proposal",
                   "logical_proposal_cost_usd": 0, "proposal_calls": 0, "source_case_id": state["case_id"]}
        atomic_json(out, payload)
        return payload
    unavailable = False
    try:
        raw = parse_json(calls[0]["output"]["content"])
        if set(raw) != {"proposals"} or not isinstance(raw["proposals"], list) or len(raw["proposals"]) > 3:
            raise ValueError("invalid first proposal")
    except (ValueError, TypeError):
        raw, unavailable = {"proposals": []}, True
    payload = {"proposals": raw["proposals"], "logical_proposal_cost_usd": calls[0]["logical_cost_usd"],
               "proposal_calls": 1, "source_state_sha256": file_sha(source / "state.json"),
               "source_request_hash": calls[0]["request_hash"], "source_case_id": state["case_id"],
               "unavailable": unavailable}
    atomic_json(out, payload)
    return payload


# ---------------------------------------------------------------------------------------------------------------
# Science-table study (docs/PHOENIX_SCIENCE_ADDENDUM.md): trimmed matrix, balanced withdrawal, pilot cases.

SCIENCE_EXPERIMENTS = {"E1": (("fixed", "llm", "full"), "F1"),       # main: shutdown + model withdrawal
                       "E2": (("fixed", "full"), "F0"),              # negative control: identity shutdown only
                       "E1b": (("no_dependency", "no_cost"), "F1")}  # ablations, only if pilot and room allow
SCIENCE_BUDGET = 0.20


def withdrawn_models(cases, models, candidates=None):
    """The model withdrawn under F1 in each case. With sonnet_low in the pool: alternate within each template over
    the (dataset, seed) order, T1 starting with sonnet_low and T2 with sol61_low, so each template loses each model
    4 or 5 times out of 9 and each dataset loses each model 3 times out of 6 (the original alternation over the whole
    case list put sonnet_low in 6 of 9 T1 cases and sol61_low in 6 of 9 T2 cases). OpenAI-only pool: sol61_low.
    `candidates` (family arms): the two non-planner models, alternated the same way (T1 starts with the first)."""
    if candidates is None:
        candidates = ("sonnet_low", "sol61_low") if "sonnet_low" in models else ("sol61_low", "sol61_low")
    out = {}
    for t, template in enumerate(("T1", "T2")):
        group = [c for c in cases if c["template"] == template]
        for i, case in enumerate(group):
            out[case["id"]] = candidates[(i + t) % 2]
    return out


def science_cases(checkpoint_root, models, candidates=None):
    """The 18 science cases (3 datasets x T1/T2 x seeds 101-103) with their F1 withdrawn model, the run order (a fixed
    random permutation, seed 2026) and the first case per dataset in that order (the main study's pilot cases)."""
    cases = [{"id": f"{d}_{t}_{s}", "dataset": d, "template": t, "seed": s,
              "checkpoint": str(Path(checkpoint_root) / f"{d}_{t}_{s}")}
             for d in DATASETS for t in ("T1", "T2") for s in (101, 102, 103)]
    withdrawn = withdrawn_models(cases, models, candidates)
    for case in cases:
        case["withdrawn_model"] = withdrawn[case["id"]]
    order = [c["id"] for c in cases]
    random.Random(2026).shuffle(order)
    first = [next(cid for cid in order if cid.startswith(d + "_")) for d in DATASETS]
    return cases, order, first


def science_matrix(root, data_root, checkpoint_root, capability_table, models, limits, prereg,
                   results_root="results", experiments=("E1", "E2", "E1b")):
    """Write the trimmed science matrix as DRAFT branch configs plus batch manifests and a study manifest.
    Nothing runs. Cases are 3 datasets x T1/T2 x seeds 101-103, ordered once by a fixed random permutation (seed
    2026). The pilot is, for each dataset, its first case in that order, run under the three E1 methods (9
    branches); pilot cases are never used as evidence, so E1, E2 and E1b run on the other 15 cases.
    `limits` holds the frozen per-branch limits (cpu_budget_s, max_calls, max_tools, wall_s, tool_timeout_s)."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cases, order, pilot = science_cases(checkpoint_root, models)
    by_id = {c["id"]: c for c in cases}
    branches = []

    def write(case, experiment, policy, fault, pilot_flag):
        name = f"sci_{experiment}_{case['id']}_{policy}_{fault}_{int(SCIENCE_BUDGET * 100):02d}"
        raw = {"kind": "phoenix", "name": name, "checkpoint": case["checkpoint"], "capability_table": str(capability_table),
               "policy": policy, "fault": fault, "withdrawn_model": case["withdrawn_model"], "seed": case["seed"],
               "models": list(models), "api_budget_usd": SCIENCE_BUDGET, "out_dir": str(results_root),
               "prereg": prereg, **limits}
        cfg = PhoenixConfig.model_validate(raw)
        path = root / (name + ".yaml")
        path.write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False))
        branches.append({"name": name, "config": str(path), "case_id": case["id"], "dataset": case["dataset"],
                         "template": case["template"], "experiment": "pilot" if pilot_flag else experiment,
                         "policy": policy, "fault": fault, "budget": SCIENCE_BUDGET,
                         "withdrawn_model": case["withdrawn_model"] if fault == "F1" else None,
                         "frozen": str(Path(results_root) / name / "frozen.json"),
                         "sealed_test": str(Path(data_root) / case["dataset"] / "sealed_test.npz")})

    for cid in order:
        case = by_id[cid]
        for experiment in experiments:
            policies, fault = SCIENCE_EXPERIMENTS[experiment]
            if cid in pilot and experiment != "E1":
                continue
            for policy in policies:
                write(case, experiment, policy, fault, cid in pilot)
    manifests = {}
    for label in ("pilot",) + tuple(experiments):
        paths = [b["config"] for b in branches if b["experiment"] == label]
        if not paths:
            continue
        batch = {"kind": "phoenix_batch", "name": f"sci_batch_{label}", "prereg": prereg, "branches": paths,
                 "concurrency": 4, "out_dir": str(results_root)}
        manifests[label] = str(root / f"batch_{label}.yaml")
        Path(manifests[label]).write_text(yaml.safe_dump(batch, sort_keys=False))
    manifest = {"schema": 1, "status": "draft_not_frozen", "cases": cases, "run_order": order, "pilot_cases": pilot,
                "branches": branches, "batch_manifests": manifests, "capability_table": str(capability_table),
                "models": list(models), "limits": limits}
    atomic_json(root / "study_manifest.json", manifest)
    return manifest


def science_calibration_configs(root, data_root, models, limits, prereg, results_root="results"):
    """One 30-task calibration config per model on the nine training-internal folds (3 datasets x seeds 1-3); only
    the time limits (cpu_budget_s, wall_s, tool_timeout_s) come from `limits`.
    Tasks 0-9 are design, 10-19 diagnose, 20-29 plan (calibrate.py); the calibration pilot is tasks 0, 10 and 20."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    paths = [str(Path(data_root) / d / f"calibration_{s}.npz") for d in DATASETS for s in (1, 2, 3)]
    out = []
    for model in models:
        timing = {k: limits[k] for k in ("cpu_budget_s", "wall_s", "tool_timeout_s") if k in limits}
        cfg = PhoenixConfig(name="sci_cal_" + model, mode="calibrate", calibration_model=model,
                            calibration_data=paths, models=list(models), max_calls=30, max_tools=1000,
                            api_budget_usd=3.0, out_dir=str(results_root), prereg=prereg, **timing)
        path = root / (cfg.name + ".yaml")
        path.write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False))
        out.append(str(path))
    return out


# Family arms (research/phoenix_science/prereg.md, section "Family arms"; Kevin, 2026-11-01): the same 18 cases and
# the three E1 methods, with one vendor family per arm and its strongest model as the planner. Each arm is calibrated
# on its own (calibration prompts list the pool, so a table is specific to it) with the arm's output ceiling.
# There is no separate pilot: the first slice of the calibration and the first batch of the matrix (the first case
# per dataset) are the start of the real run, checked by a fixed gate before the rest continues; since nothing
# changes after the gate, every case is evidence.

GATE_TASKS = (0, 10, 20)   # the first task of each calibration family (design, diagnose, plan)


def _write(path, cfg):
    Path(path).write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True), sort_keys=False))
    return str(path)


def family_calibration_configs(root, data_root, arm, results_root="results"):
    """Calibration configs for one arm, sliced so that state is pushed after each slice and the gate comes first.
    `arm`: prefix, models, planner_model, withdraw (two non-planner models), max_tokens, calibration_limits,
    calibration_budget_usd, calibration_prereg. Writes per model one config per slice (same run name, so the slices
    fill one results directory; finished tasks are skipped) and one batch per slice holding every model's slice:
    gate slices g1-g3 (tasks 0, 10, 20), then s1-s6 (tasks 0-4, 5-9, ..., 25-29). Returns the batch paths in run
    order."""
    root = Path(root)
    (root / "slices").mkdir(parents=True, exist_ok=True)
    paths = [str(Path(data_root) / d / f"calibration_{s}.npz") for d in DATASETS for s in (1, 2, 3)]
    timing = {k: arm["calibration_limits"][k] for k in ("cpu_budget_s", "wall_s", "tool_timeout_s")}
    slices = [(f"g{i + 1}", task, 1) for i, task in enumerate(GATE_TASKS)] + \
             [(f"s{i + 1}", 5 * i, 5) for i in range(6)]
    batches = []
    for label, offset, limit in slices:
        branch_paths = []
        for model in arm["models"]:
            cfg = PhoenixConfig(name=f"{arm['prefix']}_cal_{model}", mode="calibrate", calibration_model=model,
                                calibration_data=paths, models=list(arm["models"]), planner_model=arm["planner_model"],
                                withdrawn_model=arm["withdraw"][0], max_calls=30, max_tools=1000,
                                max_tokens=arm["max_tokens"], api_budget_usd=arm["calibration_budget_usd"],
                                task_offset=offset, task_limit=limit, out_dir=str(results_root),
                                prereg=arm["calibration_prereg"], **timing)
            branch_paths.append(_write(root / "slices" / f"{cfg.name}_{label}.yaml", cfg))
        batch = {"kind": "phoenix_batch", "name": f"{arm['prefix']}_cal_batch_{label}",
                 "prereg": arm["calibration_prereg"], "branches": branch_paths, "concurrency": len(arm["models"]),
                 "out_dir": str(results_root)}
        path = root / "slices" / f"batch_{label}.yaml"
        path.write_text(yaml.safe_dump(batch, sort_keys=False))
        batches.append(str(path))
    return batches


def family_matrix(root, data_root, checkpoint_root, capability_table, arm, limits, results_root="results"):
    """The arm's E1 branches (fixed, llm, full under F1) on all 18 cases x the arm's draws (fresh replicate draws of
    the model calls), as draft configs plus two batches: the gate (the first case per dataset in run order, first draw
    only: 9 branches) and the rest. Same cases, run order, checkpoints and per-branch limits as the main study; the
    arm sets the pool, planner, withdrawn models, output ceiling, budget and draws.
    Nothing runs; freeze and commit before any paid call."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    cases, order, gate = science_cases(checkpoint_root, arm["models"], arm["withdraw"])
    by_id = {c["id"]: c for c in cases}
    budget = arm["budget_usd"]
    draws = list(arm["draws"])
    branches = []
    for draw in draws:
        for cid in order:
            case = by_id[cid]
            for policy in SCIENCE_EXPERIMENTS["E1"][0]:
                name = f"{arm['prefix']}_E1_{cid}_{policy}_F1_{int(round(budget * 100)):03d}_d{draw}"
                cfg = PhoenixConfig.model_validate({
                    "kind": "phoenix", "name": name, "checkpoint": case["checkpoint"],
                    "capability_table": str(capability_table), "policy": policy, "fault": "F1",
                    "withdrawn_model": case["withdrawn_model"], "seed": case["seed"], "draw": draw,
                    "models": list(arm["models"]), "planner_model": arm["planner_model"],
                    "max_tokens": arm["max_tokens"], "api_budget_usd": budget, "out_dir": str(results_root),
                    "prereg": arm["prereg"], **limits})
                path = _write(root / (name + ".yaml"), cfg)
                branches.append({"name": name, "config": path, "case_id": cid, "dataset": case["dataset"],
                                 "template": case["template"], "experiment": arm["prefix"], "policy": policy,
                                 "fault": "F1", "budget": budget, "planner_model": arm["planner_model"],
                                 "withdrawn_model": case["withdrawn_model"], "draw": draw,
                                 "gate": cid in gate and draw == draws[0],
                                 "frozen": str(Path(results_root) / name / "frozen.json"),
                                 "sealed_test": str(Path(data_root) / case["dataset"] / "sealed_test.npz")})
    manifests = {}
    for label, members in (("gate", [b for b in branches if b["gate"]]), ("rest", [b for b in branches if not b["gate"]])):
        batch = {"kind": "phoenix_batch", "name": f"{arm['prefix']}_batch_{label}", "prereg": arm["prereg"],
                 "branches": [b["config"] for b in members], "concurrency": 4, "out_dir": str(results_root)}
        manifests[label] = str(root / f"batch_{label}.yaml")
        Path(manifests[label]).write_text(yaml.safe_dump(batch, sort_keys=False))
    manifest = {"schema": 1, "status": "draft_not_frozen", "arm": arm["prefix"], "cases": cases, "run_order": order,
                "gate_cases": gate, "branches": branches, "batch_manifests": manifests,
                "capability_table": str(capability_table), "models": list(arm["models"]),
                "planner_model": arm["planner_model"], "limits": limits, "max_tokens": arm["max_tokens"],
                "budget_usd": budget, "draws": draws}
    atomic_json(root / "study_manifest.json", manifest)
    return manifest
