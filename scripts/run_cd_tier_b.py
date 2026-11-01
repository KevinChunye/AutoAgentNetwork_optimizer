"""Run study CD's tier B in its declared order (session E6; research/v4/cd/prereg.md, tier B).

    python scripts/run_cd_tier_b.py [--minutes M]

Plain words. In order: the judge on BBEH and on code; the second Sonnet max call on BBEH and on code; then Opus at max
and at medium in alternating blocks (4 BBEH items, max then medium, over the first 40 BBEH tier A items; then 2 code
items at a time over the code tier A items). Before every step and every slice, tiers A and B together must have spent
less than TIER_B_CAP (scripts/run_cd.py --tier-cap); the first step that does not fit ends tier B. Configs resume at
their first item without a call (run_cd_tier_a.run), and an invocation ends between slices after M minutes.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import run_cd_tier_a as T  # noqa: E402

TIER_B_CAP = 50.0  # tiers A and B together (ledger rows of e60_cd_ runs that are not probe runs)
OPUS_BBEH, OPUS_BLOCK_BBEH, OPUS_BLOCK_CODE = 40, 4, 2


def steps(n_code: int) -> list[tuple[str, int, int]]:
    out = [("e60_cd_judge_bbeh", 0, T.n_items("e60_cd_judge_bbeh")), ("e60_cd_judge_code", 0, n_code),
           ("e60_cd_sonnet_max2_bbeh", 0, T.n_items("e60_cd_sonnet_max2_bbeh")), ("e60_cd_sonnet_max2_code", 0, n_code)]
    for k in range(0, OPUS_BBEH, OPUS_BLOCK_BBEH):
        out += [(f"e60_cd_{r}_bbeh", k, k + OPUS_BLOCK_BBEH) for r in ("opus_max", "opus_med")]
    for k in range(0, n_code, OPUS_BLOCK_CODE):
        out += [(f"e60_cd_{r}_code", k, min(k + OPUS_BLOCK_CODE, n_code)) for r in ("opus_max", "opus_med")]
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=float, default=95.0)
    args = parser.parse_args()
    T.HARD_CAP, T.UNTIL = TIER_B_CAP, time.time() + 60 * args.minutes
    for name, start, end in steps(T.n_items("e60_cd_judge_code")):
        if T.tier_a_spent() >= TIER_B_CAP:
            print(f"TIER B ENDS before {name} {start}-{end}: tiers A and B have spent ${T.tier_a_spent():.2f}", flush=True)
            return 0
        if not T.run(name, start, end):
            return 1
    print(f"tier B: every step ran; tiers A and B spent ${T.tier_a_spent():.2f}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
