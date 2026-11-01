"""Spending rules and the governor that enforces them on every paid call.

Terms:
  account       who is billed ("anthropic", "openai"); each model ref names one.
  hard cap      lifetime project limit per account (configs/budget.yaml, $100 each).
  phase cap     lifetime limit on the summed spend of all accounts while a phase is
                active (pilot: $20, then stop and report).
  account cap   optional lifetime limit per account while a phase is active
                (`account_caps_usd` on the phase); it sits below the hard cap, so
                one vendor cannot use up the whole phase total.
  run cap       the most one `aan run` may spend (the smaller of the experiment's
                max_usd and the phase's max_run_usd).
  worst case    the most a call can cost before it is made: every prompt token at
                the dearest input rate plus the full max_tokens of output.
  safety multiplier  estimated spend is multiplied by this before any comparison,
                so an error of that size in the price table cannot breach a cap.

Before a call the governor reserves its worst case and refuses if
  (spent + reserved + worst case) x safety multiplier
would exceed any cap that applies. After the call it records the actual cost in
the ledger and releases the reservation. Reserving the worst case means calls
running in parallel cannot overshoot a cap together. Calls that cost nothing
(the fake model) are always allowed; paid calls to an account with no hard cap
are always refused.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from .meter import CallRecord, Ledger
from .providers.base import FREE_PROVIDERS


class BudgetExceeded(RuntimeError):
    pass


class Phase(BaseModel):
    total_usd: float  # lifetime spend of all accounts at which this phase stops
    max_run_usd: float  # most a single run may spend
    account_caps_usd: dict[str, float] = {}  # lifetime spend per account at which this phase stops that account


class BudgetRules(BaseModel):
    hard_caps_usd: dict[str, float] = {}
    safety_multiplier: float = 1.15
    phase: str | None = None
    phases: dict[str, Phase] = {}

    @classmethod
    def from_yaml(cls, path: str | Path) -> "BudgetRules":
        return cls(**yaml.safe_load(Path(path).read_text()))

    @property
    def active_phase(self) -> Phase | None:
        return self.phases[self.phase] if self.phase else None


def effective_run_cap(rules: BudgetRules, config_cap: float | None = None) -> float | None:
    """The run cap that applies to one run: the smaller of the config's own `max_usd` and the active
    phase's `max_run_usd`. A missing value (None) is no cap, so it is skipped; None means neither exists."""
    phase = rules.active_phase
    caps = [c for c in (config_cap, phase.max_run_usd if phase else None) if c is not None]
    return min(caps) if caps else None


class Reservation(BaseModel):
    account: str
    amount_usd: float


class SpendGovernor:
    def __init__(self, ledger: Ledger, rules: BudgetRules, run_cap_usd: float | None = None):
        self.ledger = ledger
        self.rules = rules
        self.run_cap_usd = effective_run_cap(rules, run_cap_usd)
        self.run_spent_usd = 0.0
        self._reserved: dict[str, float] = {}

    def _reserved_total(self) -> float:
        return sum(self._reserved.values())

    def check(self, account: str, worst_case_usd: float) -> None:
        """Raise BudgetExceeded if a call of this worst case could break a cap."""
        if worst_case_usd <= 0:
            return
        self.ledger.refresh()   # spend another paid process appended since the last check
        m = self.rules.safety_multiplier
        if account not in self.rules.hard_caps_usd:
            raise BudgetExceeded(f"account {account!r} has no hard cap in configs/budget.yaml; paid calls refused")
        account_after = self.ledger.spent_usd(account) + self._reserved.get(account, 0.0) + worst_case_usd
        if account_after * m > self.rules.hard_caps_usd[account]:
            raise BudgetExceeded(
                f"{account}: spent ${self.ledger.spent_usd(account):.2f}; this call could pass the "
                f"${self.rules.hard_caps_usd[account]:.0f} hard cap (safety x{m})"
            )
        phase = self.rules.active_phase
        if phase and account in phase.account_caps_usd and account_after * m > phase.account_caps_usd[account]:
            raise BudgetExceeded(
                f"{account}: spent ${self.ledger.spent_usd(account):.2f}; this call could pass the "
                f"${phase.account_caps_usd[account]:.0f} account cap of phase {self.rules.phase!r} (safety x{m}). "
                "Stop and report to Kevin."
            )
        total_after = self.ledger.spent_usd() + self._reserved_total() + worst_case_usd
        if phase and total_after * m > phase.total_usd:
            raise BudgetExceeded(
                f"phase {self.rules.phase!r}: total spent ${self.ledger.spent_usd():.2f}; this call could pass "
                f"the ${phase.total_usd:.0f} phase cap. Stop and report to Kevin."
            )
        run_after = self.run_spent_usd + self._reserved_total() + worst_case_usd
        if self.run_cap_usd is not None and run_after * m > self.run_cap_usd:
            raise BudgetExceeded(f"this run spent ${self.run_spent_usd:.2f}; next call could pass the ${self.run_cap_usd:.2f} run cap")

    def reserve(self, account: str, worst_case_usd: float) -> Reservation:
        self.check(account, worst_case_usd)
        self._reserved[account] = self._reserved.get(account, 0.0) + worst_case_usd
        return Reservation(account=account, amount_usd=worst_case_usd)

    def release(self, reservation: Reservation) -> None:
        self._reserved[reservation.account] = self._reserved.get(reservation.account, 0.0) - reservation.amount_usd

    def settle(self, reservation: Reservation, record: CallRecord) -> None:
        """Record the actual cost. Free calls (fake model, local GPU) stay out of the ledger."""
        self.release(reservation)
        if record.cost_usd > 0 or record.provider not in FREE_PROVIDERS:
            self.ledger.record(record)
        self.run_spent_usd += record.cost_usd

    def room_by_account(self) -> dict[str, float]:
        """New estimated spend each account can still take before its tightest cap (hard cap, account
        cap, phase total), after the safety multiplier: cap / multiplier - spent."""
        self.ledger.refresh()
        m = self.rules.safety_multiplier
        phase = self.rules.active_phase
        room = {}
        for account, hard in self.rules.hard_caps_usd.items():
            limits = [hard / m - self.ledger.spent_usd(account)]
            if phase and account in phase.account_caps_usd:
                limits.append(phase.account_caps_usd[account] / m - self.ledger.spent_usd(account))
            if phase:
                limits.append(phase.total_usd / m - self.ledger.spent_usd())
            room[account] = round(min(limits), 4)
        return room

    def status(self) -> dict:
        phase = self.rules.active_phase
        return {
            "spent_by_account": {a: round(self.ledger.spent_usd(a), 4) for a in self.rules.hard_caps_usd},
            "hard_caps_usd": self.rules.hard_caps_usd,
            "phase": self.rules.phase,
            "phase_total_usd": phase.total_usd if phase else None,
            "account_caps_usd": phase.account_caps_usd if phase else {},
            "room_by_account_usd": self.room_by_account(),
            "spent_total_usd": round(self.ledger.spent_usd(), 4),
            "run_spent_usd": round(self.run_spent_usd, 4),
            "run_cap_usd": self.run_cap_usd,
            "safety_multiplier": self.rules.safety_multiplier,
        }
