"""Generate real artifact checkpoints and verify immutable branch starting points."""
from __future__ import annotations

import json
import random
import os
import shutil
from pathlib import Path

from .data import context, load_search
from .planner import Step, closure
from .store import ArtifactStore, atomic_json, file_sha
from .tools import ToolRunner
from .types import Graph, PipelineSpec, Status, WorkTask
from .workflow import add_pipeline


def create_checkpoint(data_path, out_dir, seed=101, template="T1", tool_factory=ToolRunner):
    if template not in ("T1", "T2"):
        raise ValueError("checkpoint template must be T1 or T2")
    data = load_search(data_path)
    out = Path(out_dir)
    if (out / "checkpoint.json").exists():
        existing = read_checkpoint(out)
        if (existing["seed"], existing["template"], existing["search_signature"]) != (seed, template, data.signature):
            raise ValueError("checkpoint path already contains a different case")
        return existing
    out.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(data_path, out / "search.npz")
    graph = Graph(context=context(data))
    rng = random.Random(seed)
    scale = rng.choice(["none", "standard", "minmax"])
    first = PipelineSpec(scaler=scale, classifier="logistic", c=rng.choice([0.1, 1.0, 10.0]))
    second = PipelineSpec(scaler=scale if template == "T2" else rng.choice(["standard", "minmax"]),
                          classifier="forest", trees=50, depth=rng.choice(["5", "10", "none"]))
    incumbent = add_pipeline(graph, first, seed)
    pending = add_pipeline(graph, second, seed)
    store = ArtifactStore(out / "artifacts")
    tool = tool_factory(out / "search.npz", store.root, out / "tool_work")
    receipts = []
    for step in closure(graph, incumbent, store)[0]:
        receipts.append(tool.run(graph, step))
    graph.incumbent = incumbent
    graph.score = store.load(graph.operations[incumbent], graph)["score"]
    pred = graph.operations[pending].parents[0]
    fit = graph.operations[pred].parents[0]
    for step in closure(graph, fit, store)[0]:
        receipts.append(tool.run(graph, step))
    if template == "T2":
        receipts.append(tool.run(graph, Step(operation=pred, mode="compute"), stage_only=True))
    graph.tasks["unfinished"] = WorkTask(id="unfinished", target=pending, owner="A")
    inventory = {p.name: file_sha(p) for p in store.root.iterdir() if p.is_file()}
    checkpoint = {"schema": 1, "seed": seed, "template": template, "dataset": data.dataset,
                  "search_signature": data.signature, "graph": graph.model_dump(), "inventory": inventory,
                  "initial_artifacts": list(graph.operations),
                  "checkpoint_cpu_s": sum(r["cpu_s"] for r in receipts),
                  "checkpoint_api_usd": 0.0, "checkpoint_tools": len(receipts)}
    atomic_json(out / "checkpoint.json", checkpoint)
    return checkpoint


def read_checkpoint(path, verify_files=True):
    root = Path(path)
    raw = json.loads((root / "checkpoint.json").read_text())
    data = load_search(root / "search.npz")
    graph = Graph.model_validate(raw["graph"])
    graph.audit()
    if graph.context != context(data) or raw["search_signature"] != data.signature:
        raise ValueError("checkpoint was produced with different data/code/dependencies")
    store = ArtifactStore(root / "artifacts")
    if verify_files:
        for filename, expected in raw["inventory"].items():
            # The only allowable checkpoint files are hash-addressed payloads and receipts.
            stem, suffix = filename.rsplit(".", 1)
            if suffix not in ("joblib", "json"):
                raise ValueError("invalid checkpoint artifact name")
            actual = store.path(stem, "."+suffix)
            if not actual.is_file() or file_sha(actual) != expected:
                raise ValueError("checkpoint artifact missing or changed")
    if not graph.incumbent or store.status(graph.operations[graph.incumbent], graph) != Status.VALID:
        raise ValueError("checkpoint needs a validated executable incumbent")
    if graph.score != store.load(graph.operations[graph.incumbent], graph)["score"]:
        raise ValueError("checkpoint score differs from the actual validation receipt")
    return raw


def link_or_copy(source, target):
    """Hard-link an immutable file into a branch (no extra disk on the science tables, where one fitted forest can
    be hundreds of MB), or copy it when linking is not possible. Safe because the store never writes into an
    existing file: ArtifactStore.put writes a temporary file and os.replace swaps the directory entry, so a branch
    that writes the same key gets a new file and the checkpoint's copy is untouched."""
    target = Path(target)
    if target.exists():
        target.unlink()
    try:
        os.link(source, target)
    except OSError:
        shutil.copyfile(source, target)


def branch_checkpoint(source, target):
    """Link (or copy) only immutable starting artifacts; subsequent branches never share mutable stores."""
    raw = read_checkpoint(source)
    target = Path(target)
    target.mkdir(parents=True, exist_ok=True)
    link_or_copy(Path(source) / "search.npz", target / "search.npz")
    store = ArtifactStore(target / "artifacts")
    for name in raw["inventory"]:
        link_or_copy(Path(source) / "artifacts" / name, store.root / name)
    return raw
