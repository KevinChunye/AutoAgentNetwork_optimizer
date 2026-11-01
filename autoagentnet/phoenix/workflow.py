"""Compile a bounded pipeline/ensemble DSL to actual, typed computation dependencies."""
from __future__ import annotations

import numpy as np

from .data import SearchData
from .types import Graph, Operation, PipelineSpec, Plan, Proposal, Resources


def add_pipeline(graph: Graph, spec: PipelineSpec, seed: int) -> str:
    feature = graph.add(Operation(kind="prepare", context=graph.context,
                                  params={"scaler": spec.scaler, "pca": spec.pca}))
    model = graph.add(Operation(kind="fit", context=graph.context, parents=[feature],
                               params={**spec.parameters(), "seed": seed}))
    pred = graph.add(Operation(kind="predict", context=graph.context, parents=[model]))
    return graph.add(Operation(kind="validate", context=graph.context, parents=[pred]))


def add_ensemble(graph: Graph, targets: list[str], weight=0.5) -> str:
    if len(targets) != 2 or targets[0] == targets[1]:
        raise ValueError("ensemble needs two different predictors")
    predictions = []
    for key in targets:
        op = graph.operations[key]
        if op.kind != "validate":
            raise ValueError("ensemble members must have validation targets")
        predictions.append(op.parents[0])
    pred = graph.add(Operation(kind="ensemble", context=graph.context, parents=predictions,
                               params={"weight": weight}))
    return graph.add(Operation(kind="validate", context=graph.context, parents=[pred]))


def compile_proposal(graph: Graph, proposal: Proposal, resources: Resources, seed: int) -> Plan:
    """Compile in a clone, so rejected proposals cannot mutate the authoritative DAG."""
    draft = graph.model_copy(deep=True)
    if proposal.action in ("INHERIT", "VERIFY", "RECOMPUTE", "ABANDON"):
        if proposal.target not in draft.operations or draft.operations[proposal.target].kind != "validate":
            raise ValueError("target is not an existing deliverable")
        target = proposal.target
        if proposal.action == "ABANDON" and target == draft.incumbent:
            raise ValueError("cannot abandon incumbent")
    else:
        if proposal.model and proposal.model not in resources.models:
            raise ValueError("unavailable execution model")
        if not proposal.pipelines:
            target = draft.add(Operation(kind="design", context=draft.context, model=proposal.model,
                                          params={"reason": proposal.reason, "seed": seed}))
        else:
            targets = [add_pipeline(draft, s, seed) for s in proposal.pipelines]
            target = targets[0] if len(targets) == 1 else add_ensemble(draft, targets, proposal.weight)
    check_types(draft)
    graph.operations = draft.operations
    return Plan(action=proposal.action, target=target, reason=proposal.reason)


def check_types(graph: Graph):
    graph.audit()
    for op in graph.operations.values():
        kinds = [graph.operations[p].kind for p in op.parents]
        valid = ((op.kind == "prepare" and not kinds)
                 or (op.kind == "fit" and kinds == ["prepare"])
                 or (op.kind == "predict" and kinds == ["fit"])
                 or (op.kind == "validate" and len(kinds) == 1 and kinds[0] in ("predict", "ensemble"))
                 or (op.kind == "ensemble" and len(kinds) == 2 and all(k in ("predict", "ensemble") for k in kinds))
                 or (op.kind == "design" and all(k == "validate" for k in kinds)))
        if not valid:
            raise ValueError(f"invalid typed parents for {op.kind}")


def probabilities(value):
    p = np.asarray(value["probabilities"])
    classes = np.asarray(value["classes"])
    if (p.ndim != 2 or p.shape[1] != len(classes) or not len(p) or len(classes) < 2
            or len(set(classes.tolist())) != len(classes) or not np.isfinite(p).all()
            or (p < -1e-10).any() or not np.allclose(p.sum(axis=1), 1.0, atol=1e-6)):
        raise ValueError("invalid class probabilities")
    return p, classes


def check_payload(op: Operation, value, data: SearchData | None = None):
    from sklearn.utils.validation import check_is_fitted
    if not isinstance(value, dict):
        raise ValueError("tool payload must be a dict")
    if op.kind == "prepare":
        for key in ("x_train", "x_val"):
            if np.asarray(value[key]).ndim != 2 or not np.isfinite(value[key]).all():
                raise ValueError("invalid transformed features")
        if data is not None and (len(value["x_train"]) != len(data.y_train) or
                                 len(value["x_val"]) != len(data.y_val)):
            raise ValueError("transformed row/split alignment mismatch")
        if value["transformer"] is not None:
            check_is_fitted(value["transformer"])
    elif op.kind == "fit":
        check_is_fitted(value["estimator"])
        if value["feature_id"] != op.parents[0]:
            raise ValueError("model feature lineage mismatch")
    elif op.kind in ("predict", "ensemble"):
        p, classes = probabilities(value)
        if data is not None and (len(p) != len(data.y_val) or not np.array_equal(classes, np.unique(data.y_train))):
            raise ValueError("prediction row/class/split alignment mismatch")
        if value["predictor_id"] != op.id:
            raise ValueError("predictor lineage mismatch")
    elif op.kind == "validate":
        score = value["score"]
        if not isinstance(score, (int, float)) or not np.isfinite(score) or not 0 <= score <= 1:
            raise ValueError("invalid validation score")
        if value["predictor_id"] != op.parents[0]:
            raise ValueError("report lineage mismatch")
    else:
        PipelineSpec.model_validate(value["pipeline"])


def calculate(op: Operation, parents: list[dict], data: SearchData) -> dict:
    """Trusted CPU operators. No arbitrary code or test-set access is supported."""
    from sklearn.decomposition import PCA
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import balanced_accuracy_score
    from sklearn.neighbors import KNeighborsClassifier
    from sklearn.pipeline import Pipeline
    from sklearn.preprocessing import MinMaxScaler, StandardScaler

    p = op.params
    if op.kind == "prepare":
        steps = []
        scaler = p.get("scaler", "none")
        if scaler == "standard":
            steps.append(("scale", StandardScaler()))
        elif scaler == "minmax":
            steps.append(("scale", MinMaxScaler()))
        elif scaler != "none":
            raise ValueError("unknown scaler")
        if p.get("pca", "none") != "none":
            if p["pca"] not in ("0.90", "0.95", "0.99"):
                raise ValueError("unknown PCA option")
            steps.append(("pca", PCA(n_components=float(p["pca"]), svd_solver="full")))
        transformer = Pipeline(steps) if steps else None
        # Fit statistics only on training rows.
        xt = transformer.fit_transform(data.x_train) if transformer else data.x_train.copy()
        xv = transformer.transform(data.x_val) if transformer else data.x_val.copy()
        return {"transformer": transformer, "x_train": xt, "x_val": xv}
    if op.kind == "fit":
        spec = PipelineSpec.model_validate({k: v for k, v in p.items() if k != "seed"})
        if spec.classifier == "logistic":
            est = LogisticRegression(C=spec.c, max_iter=1000, random_state=p["seed"])
        elif spec.classifier == "forest":
            est = RandomForestClassifier(n_estimators=spec.trees, max_depth=None if spec.depth == "none" else int(spec.depth),
                                         n_jobs=1, random_state=p["seed"])
        else:
            est = KNeighborsClassifier(n_neighbors=spec.neighbors, n_jobs=1)
        est.fit(parents[0]["x_train"], data.y_train)
        return {"estimator": est, "feature_id": op.parents[0]}
    if op.kind == "predict":
        # The worker supplies the fit's feature payload as a second read, not a new computation.
        fit, features = parents
        return {"probabilities": fit["estimator"].predict_proba(features["x_val"]),
                "classes": fit["estimator"].classes_, "predictor_id": op.id}
    if op.kind == "ensemble":
        a, ca = probabilities(parents[0])
        b, cb = probabilities(parents[1])
        if a.shape != b.shape or not np.array_equal(ca, cb):
            raise ValueError("unaligned ensemble predictions")
        weight = p["weight"]
        if weight not in (0.25, 0.5, 0.75):
            raise ValueError("invalid ensemble weight")
        return {"probabilities": weight * a + (1-weight) * b, "classes": ca, "predictor_id": op.id}
    if op.kind == "validate":
        prob, classes = probabilities(parents[0])
        if len(prob) != len(data.y_val):
            raise ValueError("prediction/split alignment mismatch")
        return {"score": float(balanced_accuracy_score(data.y_val, classes[prob.argmax(axis=1)])),
                "predictor_id": op.parents[0]}
    raise ValueError("design operations must use the governed model path")
