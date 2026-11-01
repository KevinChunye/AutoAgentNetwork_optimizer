"""Science-table preparation (covtype, MiniBooNE, HIGGS) on small synthetic arrays; no downloads."""
import json

import numpy as np
import pytest

from autoagentnet.phoenix.data import (DATASETS, SCIENCE_DATASETS, clean_and_encode, load_search, prepare_from_raw,
                                       subsample_indices)


def synthetic(rows=600, features=6, seed=0, labels=("False", "True")):
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(rows, features))
    y = np.array([labels[i % len(labels)] for i in range(rows)], dtype=object)
    return x, y


def test_the_study_uses_the_three_science_tables():
    assert DATASETS == SCIENCE_DATASETS == ("covtype", "miniboone", "higgs")


def test_cleaning_drops_missing_and_sentinel_rows_in_order_and_maps_labels():
    x, y = synthetic(rows=10)
    x[2, 0] = np.nan           # a missing feature
    x[5, :] = -999.0           # MiniBooNE's whole-row sentinel
    y[7] = None                # a missing label
    xc, yc, kept, dropped, label_map = clean_and_encode("miniboone", x, y)
    assert kept.tolist() == [0, 1, 3, 4, 6, 8, 9] and dropped == 3
    assert label_map == {"False": 0, "True": 1} and yc.tolist() == [0, 1, 1, 0, 0, 0, 1]
    # The sentinel rule applies only to MiniBooNE; elsewhere -999 is an ordinary value.
    assert clean_and_encode("higgs", x, y)[3] == 2


def test_numeric_labels_keep_numeric_order():
    x = np.zeros((4, 2))
    _, y, _, _, label_map = clean_and_encode("covtype", x, np.array([10, 2, 7, 2]))
    assert label_map == {"2": 0, "7": 1, "10": 2} and y.tolist() == [2, 0, 1, 0]


def test_subsample_is_fixed_stratified_and_sorted():
    y = np.array([0] * 900 + [1] * 100)
    a, b = subsample_indices(y, 200), subsample_indices(y, 200)
    assert np.array_equal(a, b) and len(a) == 200 and np.all(np.diff(a) > 0)
    assert np.bincount(y[a]).tolist() == [180, 20]
    assert len(subsample_indices(y, None)) == len(subsample_indices(y, 5000)) == 1000


def test_prepare_from_raw_subsamples_before_the_unchanged_split(tmp_path):
    x, y = synthetic(rows=1200)
    x[0, :] = -999.0
    manifest = prepare_from_raw("miniboone", x, y, tmp_path, n_rows=500, source={"openml_id": 41150})
    assert manifest["dropped_rows"] == 1 and manifest["raw_rows"] == 1200 and manifest["subsample_rows"] == 500
    assert len(manifest["subsample_indices"]) == 500 and manifest["source"]["openml_id"] == 41150
    sizes = {k: len(v) for k, v in manifest["indices"].items()}
    assert sizes == {"train": 300, "validation": 100, "test": 100}
    search = load_search(tmp_path / "miniboone" / "search.npz")
    assert search.partition == "search" and len(search.y_train) == 300 and len(search.y_val) == 100
    with np.load(tmp_path / "miniboone" / "sealed_test.npz") as sealed:
        assert len(sealed["y_test"]) == 100 and str(sealed["search_signature"]) == search.signature
    for seed in (1, 2, 3):
        fold = load_search(tmp_path / "miniboone" / f"calibration_{seed}.npz")
        assert fold.partition == "calibration" and len(fold.y_train) + len(fold.y_val) == 300
    # The same inputs give the same files: the subsample and the split are fixed.
    again = prepare_from_raw("miniboone", x, y, tmp_path / "again", n_rows=500)
    assert again["search_signature"] == manifest["search_signature"]
    assert json.loads((tmp_path / "miniboone" / "manifest.json").read_text())["label_map"] == {"False": 0, "True": 1}


def test_a_single_class_after_cleaning_is_refused():
    x, y = synthetic(rows=10, labels=("only",))
    with pytest.raises(ValueError):
        clean_and_encode("higgs", x, y)
