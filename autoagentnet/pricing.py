"""Turns token usage into dollars and (where possible) FLOPs.

Prices live in ``configs/pricing.yaml`` in USD per 1M tokens, keyed by model ID.
A real model with no price raises ``UnknownPrice`` so a run can never spend
money it cannot count.
"""

from __future__ import annotations

from pathlib import Path

import yaml
from pydantic import BaseModel

from .providers.base import FREE_PROVIDERS, Usage


class UnknownPrice(KeyError):
    pass


class Price(BaseModel):
    """USD per 1M tokens.

    cache_write / cache_read default to the input price when a provider has no
    separate rate. active_params_b is the number of parameters (in billions)
    used per token; it is only published for open-weight models and is used for
    the FLOP estimate.
    """

    input: float
    output: float
    cache_write: float | None = None
    cache_read: float | None = None
    active_params_b: float | None = None


class PriceBook:
    def __init__(self, prices: dict[str, Price]):
        self.prices = prices

    @classmethod
    def from_yaml(cls, path: str | Path) -> "PriceBook":
        raw = yaml.safe_load(Path(path).read_text()) or {}
        return cls({model: Price(**p) for model, p in raw.items()})

    def price(self, model: str, provider: str) -> Price:
        if model in self.prices:
            return self.prices[model]
        if provider in FREE_PROVIDERS:
            return Price(input=0.0, output=0.0)
        raise UnknownPrice(f"no price for model {model!r}; add it to configs/pricing.yaml")

    def cost_usd(self, model: str, provider: str, usage: Usage) -> float:
        p = self.price(model, provider)
        cache_write = p.cache_write if p.cache_write is not None else p.input
        cache_read = p.cache_read if p.cache_read is not None else p.input
        return (
            usage.input_tokens * p.input
            + usage.cache_write_tokens * cache_write
            + usage.cache_read_tokens * cache_read
            + usage.output_tokens * p.output
        ) / 1_000_000

    def worst_case_usd(self, model: str, provider: str, prompt_tokens: int, max_tokens: int) -> float:
        """Most a call can cost: every prompt token at the dearest input rate (a cache
        write costs more than plain input) and the full max_tokens of output."""
        p = self.price(model, provider)
        input_rate = max(p.input, p.cache_write if p.cache_write is not None else p.input)
        return (prompt_tokens * input_rate + max_tokens * p.output) / 1_000_000

    def flops(self, model: str, provider: str, usage: Usage) -> float | None:
        """Forward-pass FLOPs ~= 2 x active parameters x tokens processed (Kaplan et al. 2020).

        Cached prompt tokens are counted too (the provider computed them once);
        divide by 2 for multiply-accumulates (MACs). None when the model does
        not publish an active parameter count.
        """
        p = self.price(model, provider)
        if p.active_params_b is None:
            return None
        return 2 * p.active_params_b * 1e9 * usage.total_tokens
