"""Freeze the Atlas model for the Phase 1 sources before the anchor read (session E5, section 4.4 gate). $0.

    python -m analysis.atlas_freeze    # writes research/v4/atlas/frozen_model.json

Plain words. The frozen file holds, for the four Phase 1 sources (Haiku off, Luna none, Sonnet off, Sol low on the
300 sealed BBEH items, every base-prompt call), the L0 and L1 fits of the factor model (autoagentnet/atlas/factor.py):
each source's ability a and failure beta, each item's difficulty b, the systematic share, held-out log loss against
the base rate, and the L3 dispersion of repeat counts; plus the sha256 of the response table it was fitted on and of
factor.py, so a later read can check that nothing moved. With four sources the item difficulties lean on Haiku's and
Luna's repeats, and L1 does not beat the base rate on held-out items; the file says so and names L0 as the level a
read may use.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from analysis.atlas_analyses import DATA, pooled
from autoagentnet.atlas import factor as F
from autoagentnet.atlas import schema

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v4/atlas/frozen_model.json"
TABLE = DATA / "panels_phase1_bbeh.parquet"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze() -> dict:
    t = pooled(schema.read(TABLE))
    out = {"table": str(TABLE.relative_to(ROOT)), "table_sha256": sha(TABLE),
           "factor_py_sha256": sha(ROOT / "autoagentnet/atlas/factor.py"), "levels": {}}
    for level in ("L0", "L1"):
        m = F.fit(t, level)
        h = F.held_out(t, level, by="item")
        out["levels"][level] = {
            "a": m["a"].round(6).to_dict(), "beta": m["beta"].round(6).to_dict(),
            "b": m["b"].round(6).to_dict(), "systematic_share": F.systematic_share(m["b"]),
            "held_out_log_loss": h["log_loss"], "held_out_log_loss_base_rate": h["log_loss_base_rate"],
            "dispersion_L3": F.dispersion(t, m)["dispersion"]}
    beats = {lv: v["held_out_log_loss"] < v["held_out_log_loss_base_rate"] for lv, v in out["levels"].items()}
    out["usable_levels"] = [lv for lv, ok in beats.items() if ok]
    out["note"] = ("four sources; item difficulties lean on Haiku's and Luna's repeats; a read uses only the levels in "
                   "usable_levels (held-out log loss below the base rate)")
    OUT.write_text(json.dumps(out, indent=1) + "\n")
    return out


if __name__ == "__main__":
    o = freeze()
    print({lv: {k: v[k] for k in ("systematic_share", "held_out_log_loss", "held_out_log_loss_base_rate")}
           for lv, v in o["levels"].items()}, o["usable_levels"])
