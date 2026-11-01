"""Power for paired accuracy comparisons (two configs, or dense vs single, on the same tasks).

Terms:
  n            tasks both systems answer
  discordance  share of tasks where exactly one of the two is right (only these move the difference)
  SE           standard error of the accuracy difference, about sqrt(discordance / n) when the
               difference itself is small (normal approximation to McNemar's test)
  MDE          minimum detectable difference: the true gap a two-sided test at 5% detects with
               80% power, (1.96 + 0.84) x SE
  n_for_5pt    tasks needed for an MDE of 5 points at that discordance

Usage: python -m analysis.power
"""

from __future__ import annotations

import math

import pandas as pd

from .common import save_table

Z = 1.96 + 0.84


def power_table(ns=(20, 40, 60, 100, 200, 300, 600), discordances=(0.1, 0.2, 0.3)) -> pd.DataFrame:
    rows = []
    for d in discordances:
        for n in ns:
            se = math.sqrt(d / n)
            rows.append({"discordance": d, "n": n, "se_points": 100 * se, "mde_points": 100 * Z * se,
                         "n_for_5pt": math.ceil(d * (Z / 0.05) ** 2)})
    return pd.DataFrame(rows)


def main() -> pd.DataFrame:
    table = power_table().round(1)
    save_table(table, "power")
    print(table.pivot(index="n", columns="discordance", values="mde_points").to_string())
    return table


if __name__ == "__main__":
    main()
