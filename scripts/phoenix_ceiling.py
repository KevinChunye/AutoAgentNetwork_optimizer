"""A3 ceiling and timing check for the PHOENIX science tables (free, CPU only; never reads the sealed test rows).

For each dataset and each subsample size N, this runs the whole PHOENIX configuration space (workflow.py's
trusted operators: 3 scalers x 4 PCA settings x 12 classifier settings = 144 pipelines) on the training rows and
scores each on the validation rows, exactly as prepared by data.prepare_from_raw (same cleaning, subsample and
split). Definitions used in the report:
- validation balanced accuracy: mean recall over classes on the validation rows (the study's selection metric);
- spread = max - median of that accuracy over the 144 pipelines, in points (1 point = 0.01). A spread under
  2 points means recovery choices barely matter on that dataset: NO-GO for that dataset;
- operation seconds: CPU seconds of ONE operation (prepare, fit or predict) in this process, single-threaded as in
  the tool worker. The slowest single operation must be <= 50% of the tool timeout that will be frozen.

Usage: python scripts/phoenix_ceiling.py --rows 20000 40000 60000 --jobs 3 --out reports/phoenix_science
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from itertools import product
from pathlib import Path

for _key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    os.environ[_key] = "1"  # single-threaded, as the tool worker runs

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from autoagentnet.phoenix.data import (SCIENCE_DATASETS, clean_and_encode, from_arrays, load_raw,  # noqa: E402
                                       split_indices, subsample_indices)
from autoagentnet.phoenix.types import Operation, PipelineSpec  # noqa: E402
from autoagentnet.phoenix.workflow import calculate  # noqa: E402

SCALERS = ("none", "standard", "minmax")
PCAS = ("none", "0.90", "0.95", "0.99")
CLASSIFIERS = ([{"classifier": "logistic", "c": c} for c in (0.1, 1.0, 10.0)]
               + [{"classifier": "forest", "trees": t, "depth": d} for t in (50, 100) for d in ("none", "5", "10")]
               + [{"classifier": "knn", "neighbors": k} for k in (3, 5, 11)])


def search_file(name, x, y, n_rows, folder: Path) -> Path:
    """Train and validation rows of the prepared subsample (the sealed test rows are dropped here)."""
    chosen = subsample_indices(y, n_rows)
    xs, ys = x[chosen], y[chosen]
    train, val, _ = split_indices(ys)
    path = folder / f"{name}_{len(chosen)}.npz"
    np.savez_compressed(path, x_train=xs[train], y_train=ys[train], x_val=xs[val], y_val=ys[val])
    return path


def one_prepare(path: str, dataset: str, rows: int, scaler: str, pca: str) -> list[dict]:
    """One prepare operation, then the 12 classifier settings on its features: fit, predict, validate."""
    with np.load(path) as d:
        data = from_arrays(d["x_train"], d["y_train"], d["x_val"], d["y_val"], dataset)
    clock = time.process_time
    t = clock()
    features = calculate(Operation(kind="prepare", context="ceiling", params={"scaler": scaler, "pca": pca}), [], data)
    prepare_s = clock() - t
    rows_out = []
    for spec in CLASSIFIERS:
        params = {**PipelineSpec(scaler=scaler, pca=pca, **spec).parameters(), "seed": 101}
        t = clock()
        fit = calculate(Operation(kind="fit", context="ceiling", parents=["f"], params=params), [features], data)
        fit_s = clock() - t
        predict_op = Operation(kind="predict", context="ceiling", parents=["m"])
        t = clock()
        prediction = calculate(predict_op, [fit, features], data)
        predict_s = clock() - t
        score = calculate(Operation(kind="validate", context="ceiling", parents=[predict_op.id]),
                          [prediction], data)["score"]
        rows_out.append({"dataset": dataset, "rows": rows, "scaler": scaler, "pca": pca,
                         "classifier": spec["classifier"], "setting": str(spec), "prepare_s": prepare_s,
                         "fit_s": fit_s, "predict_s": predict_s, "validation_bacc": score,
                         "features_after_prepare": int(np.asarray(features["x_train"]).shape[1])})
    return rows_out


def summarise(frame: pd.DataFrame, timeout_s: float) -> pd.DataFrame:
    """Per dataset and N: accuracy distribution over the 144 pipelines and the slowest operations."""
    frame = frame.assign(slowest_op_s=frame[["prepare_s", "fit_s", "predict_s"]].max(axis=1))
    out = frame.groupby(["dataset", "rows"]).agg(
        pipelines=("validation_bacc", "size"),
        median_bacc=("validation_bacc", "median"),
        p90_bacc=("validation_bacc", lambda s: s.quantile(0.9)),
        max_bacc=("validation_bacc", "max"),
        fit_s_median=("fit_s", "median"), fit_s_max=("fit_s", "max"),
        predict_s_median=("predict_s", "median"), predict_s_max=("predict_s", "max"),
        prepare_s_max=("prepare_s", "max"), slowest_op_s=("slowest_op_s", "max")).reset_index()
    out["spread_points"] = 100 * (out.max_bacc - out.median_bacc)
    out["fits_half_timeout"] = out.slowest_op_s <= 0.5 * timeout_s
    return out.sort_values(["dataset", "rows"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--datasets", nargs="+", default=list(SCIENCE_DATASETS))
    parser.add_argument("--rows", nargs="+", type=int, default=[20000, 40000, 60000])
    parser.add_argument("--jobs", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=60.0, help="tool timeout (s) planned for freezing")
    parser.add_argument("--work", default="/tmp/phoenix_ceiling")
    parser.add_argument("--out", default="reports/phoenix_science")
    args = parser.parse_args()
    from joblib import Parallel, delayed
    work, out = Path(args.work), Path(args.out)
    work.mkdir(parents=True, exist_ok=True)
    out.mkdir(parents=True, exist_ok=True)
    jobs, cleaning = [], []
    for name in args.datasets:
        x_raw, y_raw, source = load_raw(name)
        x, y, kept, dropped, label_map = clean_and_encode(name, x_raw, y_raw)
        cleaning.append({"dataset": name, "raw_rows": len(x_raw), "dropped_rows": dropped, "clean_rows": len(y),
                         "features": x.shape[1], "classes": len(label_map),
                         "class_counts": np.bincount(y).tolist(), "source": source})
        for n in args.rows:
            path = search_file(name, x, y, n, work)
            jobs += [(str(path), name, min(n, len(y)), s, p) for s, p in product(SCALERS, PCAS)]
    rows = Parallel(n_jobs=args.jobs, verbose=5)(delayed(one_prepare)(*job) for job in jobs)
    frame = pd.DataFrame([r for chunk in rows for r in chunk])
    frame.to_csv(out / "ceiling_runs.csv", index=False)
    summary = summarise(frame, args.timeout)
    summary.to_csv(out / "ceiling_summary.csv", index=False)
    pd.DataFrame(cleaning).to_csv(out / "ceiling_cleaning.csv", index=False)
    print(pd.DataFrame(cleaning).drop(columns=["source"]).to_string(index=False))
    print(summary.round(4).to_string(index=False))


if __name__ == "__main__":
    main()
