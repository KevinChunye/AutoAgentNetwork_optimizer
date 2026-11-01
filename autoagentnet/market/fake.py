"""Offline fake trader for tests and dry runs (`--model-override fake`).

It wraps the project's FakeClient (same simulated prompt caching, usage and latency) but answers a
trader prompt in the trader reply format, so a dry run exercises the whole market: quotes, trades,
rejections and an occasional unreadable reply. The reply depends only on the request.

Rule, from a number `roll` in 0-99 hashed from the request:
  roll < 2           an unreadable reply (unparsed, counts as PASS)
  roll < 40 and the other side's quote is within the budget rule   ACCEPT
  roll < 85          a quote between the limit and 60 cents away from it (may fail quote improvement)
  otherwise          PASS
"""

from __future__ import annotations

import hashlib
import re

from ..providers.base import LLMRequest, LLMResponse, estimate_tokens
from ..providers.fake import FakeClient

ROLE_RE = re.compile(r"You are (buyer|seller) \S+\. Your (?:value|cost): \$(\d+\.\d\d)")
BOOK_RE = re.compile(r"Best bid: (none|\$\d+\.\d\d).*?Best ask: (none|\$\d+\.\d\d)")


def fake_trader_reply(text: str, digest: str) -> str | None:
    """The reply for a trader prompt, or None when `text` is not one."""
    role = ROLE_RE.search(text)
    book = BOOK_RE.search(text)
    if not (role and book):
        return None
    buyer = role.group(1) == "buyer"
    limit = round(float(role.group(2)) * 100)
    bid, ask = (None if q == "none" else round(float(q[1:]) * 100) for q in book.groups())
    roll = int(digest[:8], 16) % 100
    if roll < 2:
        return "I am not sure what to do."
    standing = ask if buyer else bid
    if roll < 40 and standing is not None and (standing <= limit if buyer else standing >= limit):
        return "REASON: The standing quote is profitable for me.\nACTION: ACCEPT"
    if roll < 85:
        step = int(digest[8:12], 16) % 61
        price = limit - step if buyer else limit + step
        return f"REASON: I quote {step} cents inside my limit.\nACTION: {'BID' if buyer else 'ASK'} {price / 100:.2f}"
    return "REASON: I wait for a better price.\nACTION: PASS"


class FakeTraderClient(FakeClient):
    async def complete(self, request: LLMRequest) -> LLMResponse:
        response = await super().complete(request)
        digest = hashlib.sha256(request.model_dump_json().encode()).hexdigest()
        reply = fake_trader_reply(request.blocks[-1].text if request.blocks else "", digest)
        if reply is None:
            return response
        usage = response.usage.model_copy(update={"output_tokens": estimate_tokens(reply)})
        return response.model_copy(update={"text": reply, "usage": usage})
