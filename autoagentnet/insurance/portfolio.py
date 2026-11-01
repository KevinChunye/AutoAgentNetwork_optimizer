"""Monte Carlo of an insurer's book of agent policies: losses, tail, capital and premium.

The book is a list of insureds. Each insured deploys agents on one foundation model in one
context and runs a known number of episodes a year. A simulated year has 12 months; in each
month every insured's defaults are drawn, priced through the policy terms, and summed.

Three sources of randomness, from most to least diversifiable:
  1. episode noise     which episodes default, given the month's rate (Poisson counts) and how
                       much each default costs (exposure resampled from data, times a random LGD)
  2. insured drift     an insured's rate for the year differs from the rated rate because its task
                       mix differs from the benchmark's (multiplicative, mean 1, coefficient of
                       variation `insured_cv`). Independent across insureds.
  3. model shock       an event that raises the default rate of every agent on one foundation
                       model at once: a bad release, a new jailbreak or injection technique, an
                       upstream outage that agents handle badly. Events arrive at `rate_per_year`
                       per model, multiply default rates by `multiplier`, and last `months`.
                       This is the accumulation risk that cannot be diversified within a model.

Controls and terms applied per default (commission defaults only carry dollar exposure):
  approval_usd   writes touching more than this go to a human first; the human catches a wrong
                 one with probability `approval_catch` (0 disables the control)
  deductible     the insured keeps the first `deductible` dollars of each claim
  limit          the most paid per claim
  aggregate      the most paid per insured per year

Outputs: the insurer's annual loss distribution, its mean, VaR and TVaR at `level`, the capital
held (TVaR minus mean), the gross premium (actuarial.loaded_premium), and each insured's share
of that capital by co-TVaR (its mean loss in the years the book is in its tail, minus its mean).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .actuarial import LossAssumptions, loaded_premium


@dataclass
class Insured:
    name: str
    model: str
    context: str
    episodes_per_year: float
    p_commission: float          # per-episode commission default rate (rated, before shocks)
    p_omission: float = 0.0      # per-episode omission + communication default rate
    architecture_multiplier: float = 1.0  # e.g. contagion.network_multiplier for a pipeline


@dataclass
class Controls:
    approval_usd: float = float("inf")
    approval_catch: float = 0.0


@dataclass
class PolicyTerms:
    deductible: float = 0.0
    limit: float = float("inf")
    aggregate: float = float("inf")


@dataclass
class ShockModel:
    rate_per_year: float = 1.0
    multiplier: float = 3.0
    months: int = 1


@dataclass
class SimConfig:
    n_sims: int = 20000
    level: float = 0.995
    insured_cv: float = 0.30
    lgd_concentration: float = 4.0   # Beta(a, b) with a + b = this; higher = LGD closer to its mean
    exact_claims_below: int = 400    # draw claims one by one below this count, else normal approx
    seed: int = 0
    shocks: ShockModel = field(default_factory=ShockModel)
    controls: Controls = field(default_factory=Controls)
    terms: PolicyTerms = field(default_factory=PolicyTerms)


def net_claim(exposure: np.ndarray, lgd: np.ndarray, cfg: SimConfig, floor_usd: float,
              rng: np.random.Generator) -> np.ndarray:
    """Insurer's payment for each commission default after control, deductible and limit."""
    gross = np.where(exposure > 0, exposure * lgd, floor_usd)
    c = cfg.controls
    if c.approval_catch > 0:
        caught = (exposure > c.approval_usd) & (rng.random(len(exposure)) < c.approval_catch)
        gross = np.where(caught, 0.0, gross)
    return np.clip(gross - cfg.terms.deductible, 0.0, cfg.terms.limit)


def draw_lgd(mean: float, concentration: float, size: int, rng: np.random.Generator) -> np.ndarray:
    """Loss given default per claim: Beta with the given mean and a + b = concentration.
    A mean of 0 or 1 is taken as fixed (every claim loses nothing, or everything)."""
    if mean <= 0 or mean >= 1:
        return np.full(size, float(np.clip(mean, 0.0, 1.0)))
    a = mean * concentration
    return rng.beta(a, concentration - a, size=size)


def claim_moments(exposures: np.ndarray, cfg: SimConfig, assumptions: LossAssumptions,
                  n: int = 200000, seed: int = 1) -> tuple[float, float]:
    """Mean and variance of one commission claim, for the normal approximation."""
    rng = np.random.default_rng(seed)
    e = rng.choice(exposures, size=n, replace=True)
    lgd = draw_lgd(assumptions.lgd, cfg.lgd_concentration, n, rng)
    x = net_claim(e, lgd, cfg, assumptions.commission_floor_usd, rng)
    return float(x.mean()), float(x.var())


def simulate(book: list[Insured], exposures: dict[str, np.ndarray], assumptions: LossAssumptions,
             cfg: SimConfig) -> dict:
    """Simulate `cfg.n_sims` years of the book. `exposures[context]` is the empirical exposure
    sample for commission defaults in that context (zeros allowed: they pay the floor)."""
    rng = np.random.default_rng(cfg.seed)
    S, I = cfg.n_sims, len(book)
    models = sorted({b.model for b in book})
    # Model shock calendar: months affected, per sim and model.
    shock = {}
    for m in models:
        mult = np.ones((S, 12))
        n_events = rng.poisson(cfg.shocks.rate_per_year, size=S)
        for s in np.nonzero(n_events)[0]:
            for _ in range(n_events[s]):
                start = rng.integers(0, 12)
                mult[s, start:start + cfg.shocks.months] = cfg.shocks.multiplier
        shock[m] = mult
    moments = {}
    for ctx in {b.context for b in book}:
        moments[ctx] = claim_moments(np.asarray(exposures[ctx], dtype=float), cfg, assumptions)
    small_claim = max(assumptions.omission_usd - cfg.terms.deductible, 0.0)
    losses = np.zeros((S, I))
    for i, ins in enumerate(book):
        # Insured drift: lognormal with mean 1 and the given coefficient of variation.
        sig2 = np.log(1 + cfg.insured_cv ** 2)
        drift = rng.lognormal(-sig2 / 2, np.sqrt(sig2), size=S)
        rate = ins.p_commission * ins.architecture_multiplier * drift[:, None] * shock[ins.model]
        lam = rate * ins.episodes_per_year / 12
        counts = rng.poisson(lam)                       # (S, 12) commission defaults
        n = counts.sum(axis=1)
        mu, var = moments[ins.context]
        total = np.zeros(S)
        exact = n < cfg.exact_claims_below
        ex_pool = np.asarray(exposures[ins.context], dtype=float)
        owner = np.repeat(np.arange(S)[exact], n[exact])  # which simulated year each claim is in
        if len(owner):
            e = rng.choice(ex_pool, size=len(owner), replace=True)
            lgd = draw_lgd(assumptions.lgd, cfg.lgd_concentration, len(owner), rng)
            claims = net_claim(e, lgd, cfg, assumptions.commission_floor_usd, rng)
            total += np.bincount(owner, weights=claims, minlength=S)
        big = ~exact
        total[big] = np.maximum(rng.normal(n[big] * mu, np.sqrt(n[big] * var)), 0.0)
        if small_claim > 0 and ins.p_omission > 0:
            om_rate = ins.p_omission * drift[:, None] * shock[ins.model]
            total += rng.poisson(om_rate * ins.episodes_per_year / 12).sum(axis=1) * small_claim
        losses[:, i] = np.minimum(total, cfg.terms.aggregate)
    return summarize(book, losses, assumptions, cfg)


def summarize(book: list[Insured], losses: np.ndarray, assumptions: LossAssumptions, cfg: SimConfig) -> dict:
    total = losses.sum(axis=1)
    mean = float(total.mean())
    var_level = float(np.quantile(total, cfg.level))
    tail = total >= var_level
    tvar = float(total[tail].mean())
    capital = max(tvar - mean, 0.0)
    premium = loaded_premium(mean, capital, assumptions)
    per = pd.DataFrame({
        "insured": [b.name for b in book], "model": [b.model for b in book],
        "context": [b.context for b in book], "episodes": [b.episodes_per_year for b in book],
        "mean_loss": losses.mean(axis=0),
        "co_tvar": losses[tail].mean(axis=0) - losses.mean(axis=0)})
    per["capital_share"] = per["co_tvar"] / per["co_tvar"].sum() if per["co_tvar"].sum() > 0 else 0.0
    per["premium"] = (per["mean_loss"] + assumptions.cost_of_capital * per["co_tvar"]) / (1 - assumptions.expense_ratio)
    per["premium_per_1k"] = 1000 * per["premium"] / per["episodes"]
    charge = assumptions.cost_of_capital * per["co_tvar"]
    per["capital_charge_share"] = charge / (per["mean_loss"] + charge).where(per["mean_loss"] + charge > 0)
    return {"total": total, "losses": losses, "mean": mean, "sd": float(total.std()),
            "var": var_level, "tvar": tvar, "capital": capital, "premium": premium,
            "loss_ratio": mean / premium if premium > 0 else float("nan"),
            "capital_charge_share": (assumptions.cost_of_capital * capital
                                     / (mean + assumptions.cost_of_capital * capital)) if mean + capital > 0 else float("nan"),
            "capital_to_premium": capital / premium if premium > 0 else float("nan"),
            "per_insured": per}
