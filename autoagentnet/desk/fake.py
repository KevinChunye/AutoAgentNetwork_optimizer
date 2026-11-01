"""Offline fake desk agents for tests and dry runs (`--model-override fake`).

It wraps the project's FakeClient (same simulated caching, usage and latency) but answers desk
prompts in the desk reply formats. The answer depends only on the request, so reruns are identical.

Rule, from a number `roll` in 0-99 hashed from the request:
  roll < 1     an unreadable reply (unparsed)
  otherwise    the trader and members read the base rate and clues, compute the Bayesian probability,
               and push it a little toward certainty (an overconfident fake); the trader buys the side
               that probability favours over the price and stakes a share of it; the risk manager
               stakes a share of the trader's edge
"""

from __future__ import annotations

import hashlib
import re

from ..providers.base import LLMRequest, LLMResponse, estimate_tokens
from ..providers.fake import FakeClient
from .events import kelly_signed, logit, sigmoid

BASE_RE = re.compile(r"Base rate: events like this happen (\d+)%")
CLUE_RE = re.compile(r"Points to (YES|NO)\. Accuracy (\d+)%")
PRICE_RE = re.compile(r"Market price: YES \$(\d\.\d\d)")
TRADER_P_RE = re.compile(r"Trader's probability that the event happens: (\d\.\d\d)")


def bayes(text: str) -> float | None:
    base = BASE_RE.search(text)
    if not base:
        return None
    x = logit(int(base.group(1)) / 100)
    for side, acc in CLUE_RE.findall(text):
        x += (1 if side == "YES" else -1) * logit(int(acc) / 100)
    return sigmoid(1.3 * x)


def fake_desk_reply(system: str, text: str, digest: str) -> str | None:
    """The reply for a desk prompt, or None when the prompt is not one."""
    roll = int(digest[:8], 16) % 100
    price_match = PRICE_RE.search(text)
    if not price_match:
        return None
    if roll < 1:
        return "I would rather not say."
    price = float(price_match.group(1))
    jitter = (int(digest[8:12], 16) % 21 - 10) / 100
    if "risk manager" in system:
        trader_p = TRADER_P_RE.search(text)
        edge = abs(kelly_signed(float(trader_p.group(1)), price)) if trader_p else 0.0
        return f"REASON: I trim the trader's edge.\nSTAKE: {max(0.0, min(1.0, 0.4 * edge + jitter / 4)):.2f}"
    p = bayes(text)
    if p is None:
        return None
    p = min(0.99, max(0.01, p + jitter / 2))
    if "committee" in system:
        return f"REASON: I weigh the clues.\nPROBABILITY: {p:.2f}"
    k = kelly_signed(p, price)
    side = "YES" if k > 0.02 else "NO" if k < -0.02 else "NONE"
    stake = 0.0 if side == "NONE" else min(1.0, abs(k) * (0.8 + abs(jitter)))
    return f"REASON: The clues and the price disagree.\nPROBABILITY: {p:.2f}\nSIDE: {side}\nSTAKE: {stake:.2f}"


class FakeDeskClient(FakeClient):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await super().complete(request)
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        reply = fake_desk_reply(request.system or "", request.blocks[-1].text if request.blocks else "", digest)
        if reply is None:
            return response
        usage = response.usage.model_copy(update={"output_tokens": estimate_tokens(reply)})
        return response.model_copy(update={"text": reply, "usage": usage})

