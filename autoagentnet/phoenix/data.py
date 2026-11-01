"""Prepare public datasets once; the search loader cannot return held-out labels.

The study runs on three science tables (docs/PHOENIX_SCIENCE_ADDENDUM.md):
- covtype: forest cover type of 30 m cells from cartographic variables (sklearn fetch_covtype; 7 classes);
- miniboone: electron vs muon neutrino events in the MiniBooNE detector (OpenML 41150; 2 classes);
- higgs: Higgs-boson signal vs background collision events (OpenML 23512; 2 classes).
The original toy sets (breast_cancer, wine, digits; bundled with scikit-learn) stay available for offline tests.

Preparation, in this fixed order: load the raw table; drop rows with a missing or non-finite value and, for
MiniBooNE, rows holding the -999 sentinel (deterministic, order kept, count recorded); map labels to 0..K-1;
take ONE stratified subsample of N rows (random_state=42); then the unchanged 60/20/20 split and calibration folds.
"""
from __future__ import annotations

import hashlib
import importlib.metadata
import io
from pathlib import Path

import numpy as np
from pydantic import Field

from .store import atomic_json
from .types import Strict, digest

SCIENCE_DATASETS = ("covtype", "miniboone", "higgs")
TOY_DATASETS = ("breast_cancer", "wine", "digits")  # offline tests only
DATASETS = SCIENCE_DATASETS  # the study's datasets (matrix and calibration configs iterate over these)
OPENML_IDS = {"miniboone": 41150, "higgs": 23512}
SENTINELS = {"miniboone": -999.0}  # a whole-row placeholder for a missing event record
SUBSAMPLE_SEED = 42


class SearchData(Strict):
    model_config = {"extra": "forbid", "arbitrary_types_allowed": True}
    x_train: np.ndarray
    y_train: np.ndarray
    x_val: np.ndarray
    y_val: np.ndarray
    signature: str
    dataset: str
    partition: str = "search"


def array_hash(*arrays):
    h = hashlib.sha256()
    for a in arrays:
        a = np.ascontiguousarray(a)
        h.update(str(a.dtype).encode())
        h.update(str(a.shape).encode())
        h.update(a.tobytes())
    return h.hexdigest()


def from_arrays(x_train, y_train, x_val, y_val, dataset="test_fixture", partition="search"):
    arrays = [np.asarray(a) for a in (x_train, y_train, x_val, y_val)]
    if arrays[0].ndim != 2 or arrays[2].shape[1:] != arrays[0].shape[1:]:
        raise ValueError("feature schema mismatch")
    if len(arrays[0]) != len(arrays[1]) or len(arrays[2]) != len(arrays[3]):
        raise ValueError("row/label alignment mismatch")
    return SearchData(x_train=arrays[0], y_train=arrays[1], x_val=arrays[2], y_val=arrays[3],
                      signature=digest({"data": array_hash(*arrays), "partition": partition}),
                      dataset=dataset, partition=partition)


def save_search(path: Path, data: SearchData):
    path.parent.mkdir(parents=True, exist_ok=True)
    # numpy receives a file object so it does not append a hidden .npz suffix.
    temporary = path.with_suffix(".pending")
    with temporary.open("wb") as f:
        np.savez_compressed(f, x_train=data.x_train, y_train=data.y_train,
                            x_val=data.x_val, y_val=data.y_val,
                            dataset=data.dataset, partition=data.partition, signature=data.signature)
    temporary.replace(path)


def load_search(path: str | Path) -> SearchData:
    with np.load(path, allow_pickle=False) as d:
        expected = {"x_train", "y_train", "x_val", "y_val", "dataset", "partition", "signature"}
        if set(d.files) != expected:
            raise ValueError("search file must contain only train/validation fields")
        out = from_arrays(d["x_train"], d["y_train"], d["x_val"], d["y_val"],
                          str(d["dataset"]), str(d["partition"]))
        if out.signature != str(d["signature"]):
            raise ValueError("search data checksum mismatch")
        return out


def context(data: SearchData) -> str:
    sources = {}
    for name in ("types.py", "data.py", "workflow.py", "worker.py"):
        p = Path(__file__).with_name(name)
        sources[name] = hashlib.sha256(p.read_bytes()).hexdigest()
    versions = {p: importlib.metadata.version(p) for p in ("scikit-learn", "numpy", "scipy", "joblib")}
    return digest({"data": data.signature, "sources": sources, "versions": versions})


def load_raw(name: str):
    """The raw table as (features as float64, labels as given by the source, source description).
    Downloads go to scikit-learn's data cache; tests never call this for the science tables."""
    from sklearn import datasets
    if name in TOY_DATASETS:
        raw = getattr(datasets, "load_" + name)()
        return np.asarray(raw.data, dtype=float), np.asarray(raw.target), {"loader": f"sklearn.datasets.load_{name}"}
    if name == "covtype":
        raw = datasets.fetch_covtype()
        return np.asarray(raw.data, dtype=float), np.asarray(raw.target), {"loader": "sklearn.datasets.fetch_covtype"}
    if name in OPENML_IDS:
        raw = datasets.fetch_openml(data_id=OPENML_IDS[name], as_frame=True, parser="auto")
        if raw.target is None or len(raw.target_names) != 1:
            raise ValueError(f"{name}: expected exactly one OpenML target, got {raw.target_names}")
        x = raw.data.apply(lambda column: column.astype(float))  # numeric features only; a non-number fails here
        y = raw.target.astype("object").to_numpy()
        return x.to_numpy(dtype=float), y, {"loader": "sklearn.datasets.fetch_openml", "openml_id": OPENML_IDS[name],
                                            "openml_name": raw.details.get("name"), "openml_version": raw.details.get("version"),
                                            "target": raw.target_names[0]}
    raise ValueError("unsupported dataset")


def clean_and_encode(name: str, x, y):
    """Drop rows that cannot be used (any non-finite feature, a missing label, or for MiniBooNE any -999 sentinel),
    keeping row order, then map the label values to 0..K-1 in sorted order of their text form.
    Returns (x, y as int64, kept row indices into the raw table, dropped-row count, label map)."""
    x = np.asarray(x, dtype=float)
    labels = np.asarray(y, dtype=object)
    missing_label = np.array([v is None or (isinstance(v, float) and np.isnan(v)) for v in labels])
    keep = np.isfinite(x).all(axis=1) & ~missing_label
    if name in SENTINELS:
        keep &= ~(x == SENTINELS[name]).any(axis=1)
    kept = np.flatnonzero(keep)
    text = np.array([str(v) for v in labels[kept]])
    distinct = sorted(set(text.tolist()))
    try:  # numeric labels (covtype's 1..7) keep numeric order; text labels ("True"/"False") sort as text
        classes = [distinct[i] for i in np.argsort([float(c) for c in distinct], kind="stable")]
    except ValueError:
        classes = distinct
    if len(classes) < 2:
        raise ValueError(f"{name}: fewer than two classes after cleaning")
    code = {c: i for i, c in enumerate(classes)}
    return x[kept], np.array([code[t] for t in text], dtype=np.int64), kept, int(len(labels) - len(kept)), code


def subsample_indices(y, n_rows: int | None, seed: int = SUBSAMPLE_SEED):
    """One fixed stratified subsample of n_rows rows (sorted indices), or every row when n_rows is None or too large."""
    from sklearn.model_selection import train_test_split
    if n_rows is None or n_rows >= len(y):
        return np.arange(len(y))
    chosen, _ = train_test_split(np.arange(len(y)), train_size=n_rows, stratify=y, random_state=seed)
    return np.sort(chosen)


def split_indices(y):
    """The original split, unchanged: stratified 20% sealed test, then 25% of the rest as validation
    (60/20/20, random_state=42). Returns (train, validation, test) row indices."""
    from sklearn.model_selection import train_test_split
    indices = np.arange(len(y))
    train_val, test = train_test_split(indices, test_size=0.2, stratify=y, random_state=42)
    train, val = train_test_split(train_val, test_size=0.25, stratify=y[train_val], random_state=42)
    assert not (set(train) & set(val) or set(train) & set(test) or set(val) & set(test))
    return train, val, test


def build_dataset(name: str, x, y, root: str | Path, extra_manifest: dict | None = None) -> dict:
    """Split (split_indices), write the search file, the sealed test file and three training-internal 80/20
    calibration folds (seeds 1-3)."""
    from sklearn.model_selection import train_test_split
    train, val, test = split_indices(y)
    root = Path(root) / name
    root.mkdir(parents=True, exist_ok=True)
    search = from_arrays(x[train], y[train], x[val], y[val], name)
    save_search(root / "search.npz", search)
    # Only the final evaluator opens this file. Never include this path in a model request.
    np.savez_compressed(root / "sealed_test.npz", x_test=x[test], y_test=y[test],
                        search_signature=search.signature)
    for seed in (1, 2, 3):
        a, b = train_test_split(train, test_size=0.2, stratify=y[train], random_state=seed)
        save_search(root / f"calibration_{seed}.npz",
                    from_arrays(x[a], y[a], x[b], y[b], name, "calibration"))
    manifest = {"dataset": name, "raw_hash": array_hash(x, y), "search_signature": search.signature,
                "indices": {"train": train.tolist(), "validation": val.tolist(), "test": test.tolist()},
                "split_seed": 42, "sklearn": importlib.metadata.version("scikit-learn"), **(extra_manifest or {})}
    atomic_json(root / "manifest.json", manifest)
    return manifest


def prepare_from_raw(name: str, x_raw, y_raw, root: str | Path, n_rows: int | None = None, source: dict | None = None) -> dict:
    """Clean, encode and subsample a raw table, then split it. `raw_hash` in the manifest is the hash of the
    table actually split (the subsample); `source_raw_hash` is the hash of the full raw table as loaded."""
    x_raw = np.asarray(x_raw, dtype=float)
    source_raw_hash = array_hash(x_raw, np.array([str(v) for v in np.asarray(y_raw, dtype=object)]))
    x, y, kept, dropped, label_map = clean_and_encode(name, x_raw, y_raw)
    chosen = subsample_indices(y, n_rows)
    extra = {"source": source or {}, "source_raw_hash": source_raw_hash, "raw_rows": int(len(x_raw)),
             "dropped_rows": dropped, "drop_rule": "non-finite feature, missing label"
             + (f", any feature == {SENTINELS[name]}" if name in SENTINELS else ""),
             "label_map": label_map, "subsample_rows": int(len(chosen)), "subsample_seed": SUBSAMPLE_SEED,
             "subsample_indices": chosen.tolist(),  # indices into the cleaned table
             "class_counts": np.bincount(y[chosen]).tolist()}
    return build_dataset(name, x[chosen], y[chosen], root, extra)


def prepare_dataset(name: str, root: str | Path, n_rows: int | None = None) -> dict:
    """Explicit preparation command, never called on package import or by a planner."""
    if name not in SCIENCE_DATASETS + TOY_DATASETS:
        raise ValueError("unsupported dataset")
    x, y, source = load_raw(name)
    return prepare_from_raw(name, x, y, root, n_rows, source)
