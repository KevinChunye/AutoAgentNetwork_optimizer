"""Separate held-out evaluator. Never imported by the recovery engine or planner."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from .store import ArtifactStore, atomic_json, file_sha
from .types import Graph, Status, digest
from .workflow import check_types


def validate_frozen(path):
    path = Path(path)
    raw = json.loads(path.read_text())
    graph = Graph.model_validate(raw["graph"])
    check_types(graph)
    from .data import context, load_search
    search = load_search(path.parent / "search.npz")
    if context(search) != graph.context or search.signature != raw["search_signature"]:
        raise ValueError("frozen data/code/dependency context changed")
    if digest(graph.model_dump()) != raw["graph_hash"] or raw["target"] != graph.incumbent:
        raise ValueError("frozen graph changed")
    store = ArtifactStore(path.parent / "artifacts")
    for name, sha in raw["artifact_inventory"].items():
        key, suffix = name.rsplit(".", 1)
        if suffix not in ("json", "joblib") or file_sha(store.path(key, "."+suffix)) != sha:
            raise ValueError("frozen artifact changed")
    target = graph.operations[raw["target"]]
    if target.kind != "validate" or store.status(target, graph) != Status.VALID:
        raise ValueError("final result is not a validated predictor")
    report = store.load(target, graph)
    if report["score"] != raw["validation_score"]:
        raise ValueError("frozen score differs from receipt")
    return raw, graph, store


def predict(graph, store, key, x):
    op = graph.operations[key]
    store.load(op, graph)  # validate checksums/provenance before using a stored predictor
    if op.kind == "validate":
        return predict(graph, store, op.parents[0], x)
    if op.kind == "predict":
        fit_op = graph.operations[op.parents[0]]
        fit = store.load(fit_op, graph)
        features = store.load(graph.operations[fit_op.parents[0]], graph)
        transformer = features["transformer"]
        xt = transformer.transform(x) if transformer is not None else x
        return fit["estimator"].predict_proba(xt), fit["estimator"].classes_
    if op.kind == "ensemble":
        a, ca = predict(graph, store, op.parents[0], x)
        b, cb = predict(graph, store, op.parents[1], x)
        if not np.array_equal(ca, cb) or a.shape != b.shape:
            raise ValueError("test prediction class alignment changed")
        w = op.params["weight"]
        return w*a+(1-w)*b, ca
    raise ValueError("node cannot be delivered as a predictor")


def evaluate_frozen(frozen_path, sealed_test_path):
    """Explicit API for final scoring only; it does not refit or select anything."""
    from sklearn.metrics import balanced_accuracy_score
    raw, graph, store = validate_frozen(frozen_path)
    with np.load(sealed_test_path, allow_pickle=False) as sealed:
        if str(sealed["search_signature"]) != raw["search_signature"]:
            raise ValueError("test partition belongs to another training/validation split")
        p, classes = predict(graph, store, raw["target"], sealed["x_test"])
        labels = sealed["y_test"]
        if p.shape != (len(labels), len(classes)) or not np.isfinite(p).all():
            raise ValueError("invalid test predictions")
        score = float(balanced_accuracy_score(labels, classes[p.argmax(axis=1)]))
    return {"case_id": raw["case_id"], "test_balanced_accuracy": score,
            "validation_score": raw["validation_score"], "frozen_sha256": file_sha(Path(frozen_path)),
            "offline_fixture": raw["offline_fixture"]}


def seal_evaluation(branches, path):
    """Require every listed branch to be frozen before reading any test labels."""
    rows = []
    for branch in branches:
        frozen = Path(branch["frozen"])
        validate_frozen(frozen)
        if not Path(branch["sealed_test"]).is_file():
            raise ValueError("missing sealed test partition")
        rows.append({**branch, "frozen_sha256": file_sha(frozen),
                     "sealed_sha256": file_sha(Path(branch["sealed_test"]))})
    manifest = {"schema": 1, "branches": rows}
    atomic_json(path, manifest)
    return manifest


def evaluate_manifest(path, out_path):
    import pandas as pd
    manifest = json.loads(Path(path).read_text())
    # Validate ALL frozen/test hashes before evaluating the first branch.
    for row in manifest["branches"]:
        if file_sha(Path(row["frozen"])) != row["frozen_sha256"] or file_sha(Path(row["sealed_test"])) != row["sealed_sha256"]:
            raise ValueError("sealed evaluation input changed")
    results = [{**row, **evaluate_frozen(row["frozen"], row["sealed_test"])} for row in manifest["branches"]]
    frame = pd.DataFrame(results)
    target = Path(out_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target, index=False)
    return frame
