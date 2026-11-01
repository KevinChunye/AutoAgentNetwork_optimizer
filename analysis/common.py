"""Shared helpers for the analysis scripts: confidence intervals, figure style, paths.

Every table and figure in reports/pilot/ is written by a script in this folder from
results/*/results.csv (plus the ledger for spend), so every number traces to code.

Terms:
  bootstrap CI   resample tasks with replacement many times, recompute the statistic,
                 and take the 2.5th and 97.5th percentiles (a 95% interval). Tasks are
                 the unit of resampling because they are the independent draws.
  paired         both systems answered the same tasks, so the per-task difference is
                 resampled; this removes task difficulty from the noise.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "reports" / "pilot"
FIGURES = REPORT / "figures"
TABLES = REPORT / "tables"

N_BOOT = 2000
SEED = 0

# Okabe-Ito palette: distinguishable with the common forms of colour blindness.
PALETTE = {
    "black": "#000000",
    "orange": "#E69F00",
    "sky": "#56B4E9",
    "green": "#009E73",
    "yellow": "#F0E442",
    "blue": "#0072B2",
    "vermillion": "#D55E00",
    "purple": "#CC79A7",
}
SERIES = ["blue", "orange", "green", "vermillion", "purple", "sky", "black"]


def bootstrap_mean_ci(values, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float, float]:
    """Mean of `values` and its 95% bootstrap interval (NaNs dropped)."""
    x = np.asarray(values, dtype=float)
    x = x[~np.isnan(x)]
    if len(x) == 0:
        return (np.nan, np.nan, np.nan)
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    return (float(x.mean()), float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def paired_bootstrap_diff(a, b, n_boot: int = N_BOOT, seed: int = SEED) -> tuple[float, float, float]:
    """Mean of (a - b) over paired items and its 95% bootstrap interval.
    a and b are aligned per task (for example dense and single correctness)."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    return bootstrap_mean_ci(d, n_boot, seed)


def task_bootstrap_indices(n_tasks: int, n_boot: int = N_BOOT, seed: int = SEED) -> np.ndarray:
    """Resampled task positions, shape (n_boot, n_tasks); reuse one draw across configs
    so that comparisons between configs stay paired."""
    return np.random.default_rng(seed).integers(0, n_tasks, size=(n_boot, n_tasks))


def save_figure(fig, name: str, folder: Path | None = None) -> list[Path]:
    """Vector PDF plus PNG (in reports/pilot/figures unless `folder` is given)."""
    import matplotlib.pyplot as plt

    folder = folder or FIGURES
    folder.mkdir(parents=True, exist_ok=True)
    paths = [folder / f"{name}.pdf", folder / f"{name}.png"]
    fig.savefig(paths[0], bbox_inches="tight")
    fig.savefig(paths[1], bbox_inches="tight", dpi=200)
    plt.close(fig)
    return paths


def save_table(table: pd.DataFrame, name: str, folder: Path | None = None, index: bool = False) -> Path:
    folder = folder or TABLES
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{name}.csv"
    table.to_csv(path, index=index)
    return path


def style():
    """Matplotlib with a plain, print-friendly style; returns the pyplot module."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    plt.rcParams.update(
        {
            "figure.figsize": (5.0, 3.4),
            "font.size": 9,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.grid": True,
            "grid.alpha": 0.3,
            "pdf.fonttype": 42,
        }
    )
    return plt


def color(i: int) -> str:
    return PALETTE[SERIES[i % len(SERIES)]]
