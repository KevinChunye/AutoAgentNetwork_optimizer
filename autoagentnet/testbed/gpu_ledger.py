"""The GPU-hour ledger and its stop rule ($100 of Lightning credit for the whole testbed).

Ledger: research/v4/testbed/gpu_ledger.csv, one row per runbook step: date, machine, gpu_type, hours,
rate_usd_per_h, usd (= rate x hours), stage, step, note. Hours are wall-clock since the previous row (or since
`start`), so idle time between steps is billed too, as Lightning bills it (by the second while the Studio runs).
The clock lives in runs/testbed/clock.json on the Studio's disk (outside git).

Stop rule (`guard`, run before every step; the step does not start when it fails):
  pilot    pilot spend + the next step's estimate <= $10
  stage1   stage-1 spend + estimate <= $55
  stage2   may start only while at least $30 of the $100 remains; stage-2 spend + estimate <= the remainder
  always   total spend + estimate <= $90 (the hard stop; the last $10 is buffer)
These limits are the brief's and live in code on purpose: changing one is a reviewed change.
"""

from __future__ import annotations

import csv
import json
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "research/v4/testbed/gpu_ledger.csv"
CLOCK = ROOT / "runs/testbed/clock.json"
FIELDS = ["date", "machine", "gpu_type", "hours", "rate_usd_per_h", "usd", "stage", "step", "note"]
TOTAL_USD = 100.0
HARD_STOP_USD = 90.0
STAGE_CAPS = {"pilot": 10.0, "stage1": 55.0}
STAGE2_MIN_REMAINING = 30.0


class GPUBudgetExceeded(RuntimeError):
    pass


def rows(ledger: Path = LEDGER) -> list[dict]:
    if not Path(ledger).exists():
        return []
    with Path(ledger).open() as f:
        return list(csv.DictReader(f))


def spent(ledger: Path = LEDGER, stage: str | None = None) -> float:
    return sum(float(r["usd"]) for r in rows(ledger) if stage is None or r["stage"] == stage)


def start(machine: str, gpu_type: str, rate_usd_per_h: float, clock: Path = CLOCK) -> dict:
    """Start (or restart) the clock when the Studio boots; rate from Lightning's live rate card."""
    state = {"machine": machine, "gpu_type": gpu_type, "rate": float(rate_usd_per_h), "last": time.time()}
    Path(clock).parent.mkdir(parents=True, exist_ok=True)
    Path(clock).write_text(json.dumps(state))
    return state


def _clock(clock: Path) -> dict:
    if not Path(clock).exists():
        raise RuntimeError(f"no GPU clock at {clock}: run `python -m autoagentnet.testbed ledger start ...` first")
    return json.loads(Path(clock).read_text())


def unbilled_usd(clock: Path = CLOCK) -> float:
    state = _clock(clock)
    return (time.time() - state["last"]) / 3600 * state["rate"]


def tick(stage: str, step: str, note: str = "", ledger: Path = LEDGER, clock: Path = CLOCK) -> dict:
    """Append the hours since the last tick, billed to `stage`."""
    state = _clock(clock)
    now = time.time()
    hours = (now - state["last"]) / 3600
    row = {"date": datetime.now(timezone.utc).isoformat(timespec="seconds"), "machine": state["machine"],
           "gpu_type": state["gpu_type"], "hours": round(hours, 4), "rate_usd_per_h": state["rate"],
           "usd": round(hours * state["rate"], 4), "stage": stage, "step": step, "note": note}
    new = not Path(ledger).exists()
    Path(ledger).parent.mkdir(parents=True, exist_ok=True)
    with Path(ledger).open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)
    state["last"] = now
    Path(clock).write_text(json.dumps(state))
    return row


def guard(stage: str, next_hours: float, rate_usd_per_h: float | None = None, ledger: Path = LEDGER,
          clock: Path = CLOCK) -> dict:
    """Raise GPUBudgetExceeded unless the next step (estimated hours) fits every limit; counts unbilled time."""
    rate = rate_usd_per_h if rate_usd_per_h is not None else _clock(clock)["rate"]
    pending = unbilled_usd(clock) if Path(clock).exists() else 0.0
    total = spent(ledger) + pending
    estimate = next_hours * rate
    if total + estimate > HARD_STOP_USD:
        raise GPUBudgetExceeded(f"total ${total:.2f} + next ${estimate:.2f} passes the ${HARD_STOP_USD:.0f} hard stop")
    if stage in STAGE_CAPS:
        mine = spent(ledger, stage) + pending
        if mine + estimate > STAGE_CAPS[stage]:
            raise GPUBudgetExceeded(f"{stage} ${mine:.2f} + next ${estimate:.2f} passes its ${STAGE_CAPS[stage]:.0f} cap")
    elif stage == "stage2":
        before = total - spent(ledger, "stage2") - pending
        if TOTAL_USD - before < STAGE2_MIN_REMAINING:
            raise GPUBudgetExceeded(f"stage 2 needs ${STAGE2_MIN_REMAINING:.0f} left at its start; ${TOTAL_USD - before:.2f} was")
    else:
        raise ValueError(f"unknown stage {stage!r}")
    return {"stage": stage, "total_usd": round(total, 2), "next_usd": round(estimate, 2),
            "room_usd": round(HARD_STOP_USD - total - estimate, 2)}
