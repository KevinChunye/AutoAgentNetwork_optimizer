"""The four desk structures of W2-A (S5, the market, is for a later session).

  S1 solo       the trader states a probability p, a side and a stake, and the desk does what it says
  S2 risk       the same trader's p and side; a risk manager sets the stake from p, the price and the
                trader's track record (it never sees the clues or the news item)
  S3 half-Kelly the same trader's p; the side is the one p favours over the price, and the stake is
                half the Kelly stake at p (mechanical, no extra call)
  S4 committee  six members state probabilities (member 1 is the S1 trader call, members 2-6 have
                their own ways of working); the desk pools them by averaging log-odds and sizes the
                pooled p at half Kelly, as S3 does

S1, S2 and S3 share the trader's call, so they differ only in how the stake is set; S4 adds five calls.
Twin (audit 40): on every event with a news item, a second trader call sees the same event without the
item. Its decision is stored as structure "S1_twin", so the item's effect is measured on the same event
(paired), not only between halves.
Every structure sees the same clues for an event, so they differ in how they use the information,
not in what they know. The trader's and members' calls never depend on the bankroll, so every call
of a sequence can run in parallel and the wealth path is computed afterwards (metrics.py).

A reply the parser cannot read, or one cut off by max_tokens (its final lines may be missing or cut
mid-number; the market town's audit 30 rule), is "unparsed": the desk then stays out of that event
(stake 0) and the event is left out of the belief measures for that structure.
"""

from __future__ import annotations

import asyncio
import math
from dataclasses import dataclass, replace

from ..agents.spec import AgentInput, AgentOutput, AgentRequest, AgentSpec
from .events import Event, kelly_signed, logit, sigmoid
from .prompts import (RISK_SYSTEM, RULES, TRADER_SYSTEM, TrackRecord, event_text, member_system, parse_member,
                      parse_risk, parse_trader, risk_text)

STRUCTURES = ("S1", "S2", "S3", "S4")
MEMBERS = (2, 3, 4, 5, 6)
TRUNCATED = {"max_tokens", "length"}


@dataclass
class DeskSettings:
    """model: model ref of every role; kelly_fraction: the mechanical stake of S3 and S4 as a share of
    the Kelly stake (one half, fixed by the plan); p_clip: probabilities are clipped to
    [p_clip, 1 - p_clip] before log-odds pooling, so one member's 0 or 1 cannot decide alone."""

    model: str = "haiku_nothink"
    max_tokens: int = 400
    temperature: float | None = 1.0
    kelly_fraction: float = 0.5
    p_clip: float = 0.01


def request(event: Event, role: str, index: int, system: str, instruction: str, s: DeskSettings) -> AgentRequest:
    """The shared rules are the cached task block; the role's own text follows."""
    spec = AgentSpec(agent_id=role, stage="desk", index=index, model=s.model, system=system, instruction=instruction,
                     max_tokens=s.max_tokens, temperature=s.temperature)
    return AgentRequest(spec=spec, input=AgentInput(task_id=event.event_id, task=RULES, shared_prefix=True))


def trader_request(event: Event, s: DeskSettings) -> AgentRequest:
    return request(event, "trader", 1, TRADER_SYSTEM, event_text(event), s)


def member_request(event: Event, k: int, s: DeskSettings) -> AgentRequest:
    return request(event, f"member{k}", k, member_system(k), event_text(event), s)


def without_item(event: Event) -> Event:
    """The same event with its news item removed (the salient flag and the item's side are kept for analysis)."""
    return replace(event, story="")


def twin_request(event: Event, s: DeskSettings) -> AgentRequest:
    return request(event, "twin", 8, TRADER_SYSTEM, event_text(without_item(event)), s)


def twin_rows(event: Event, call: "Call", s: DeskSettings) -> list[dict]:
    """The twin's S1 decision on the event without its item, as structure "S1_twin"."""
    return [{**row, "structure": "S1_twin"} for row in decisions(event, {"trader": call}, s, ("S1",))]


def risk_request(event: Event, p: float, side: str, record: TrackRecord, s: DeskSettings) -> AgentRequest:
    return request(event, "risk", 7, RISK_SYSTEM, risk_text(event, p, side, record), s)


def track_record(events: list[Event], trader: dict[str, "Call"], before: int) -> TrackRecord:
    """The trader's bets on the events of the sequence before index `before` (outcomes are known)."""
    bets = []
    for e in events[:before]:
        reply = parse_trader(trader[e.event_id].text) if e.event_id in trader else None
        if reply is None or not reply.parsed or reply.side == "NONE":
            continue
        confidence = reply.p if reply.side == "YES" else 1 - reply.p
        bets.append((confidence, int((reply.side == "YES") == bool(e.outcome))))
    if not bets:
        return TrackRecord(0, None, None)
    return TrackRecord(len(bets), sum(c for c, _ in bets) / len(bets), sum(w for _, w in bets) / len(bets))


@dataclass
class Call:
    """One model reply and what the ledger needs from it."""

    role: str
    text: str
    truncated: bool
    cost_usd: float
    from_cache: bool

    @classmethod
    def of(cls, role: str, output: AgentOutput) -> "Call":
        return cls(role, output.content, output.stop_reason in TRUNCATED, output.cost_usd, output.from_cache)


async def ask(caller, req: AgentRequest, replicate: int, gate: asyncio.Semaphore) -> Call:
    async with gate:
        return Call.of(req.spec.agent_id, await caller.call(req, replicate=replicate))


def mechanical(p: float, price: float, fraction: float) -> tuple[str, float]:
    """Side and stake at `fraction` of the Kelly stake at p."""
    k = kelly_signed(p, price)
    side = "YES" if k > 0 else "NO" if k < 0 else "NONE"
    return side, fraction * abs(k)


def pool(ps: list[float], clip: float) -> float:
    """Average log-odds of the members' probabilities (each clipped to [clip, 1 - clip])."""
    return sigmoid(sum(logit(min(1 - clip, max(clip, p))) for p in ps) / len(ps))


def decisions(event: Event, calls: dict[str, Call], s: DeskSettings, structures=STRUCTURES) -> list[dict]:
    """One row per structure for one event, from that event's replies. p is the probability the
    structure acted on (NaN when its reply was unparsed)."""
    rows = []
    calls = {role: call for role, call in calls.items() if not call.truncated}  # a cut-off reply is unparsed
    trader = parse_trader(calls["trader"].text) if "trader" in calls else None
    ok = trader is not None and trader.parsed
    base = {"event_id": event.event_id, "seed": event.seed, "index": event.index, "model": s.model}

    def add(structure: str, p: float | None, side: str | None, stake: float | None, parsed: bool, **extra) -> None:
        side = side if parsed and side else "NONE"
        stake = float(stake) if parsed and stake is not None and side != "NONE" else 0.0
        rows.append({**base, "structure": structure, "parsed": parsed, "p": p if parsed else math.nan,
                     "side": side, "stake": stake,
                     "signed_stake": stake if side == "YES" else -stake if side == "NO" else 0.0, **extra})

    if "S1" in structures:
        add("S1", trader.p if trader else None, trader.side if trader else None, trader.stake if trader else None, ok,
            reason=trader.reason if trader else "")
    if "S2" in structures:
        if ok and trader.side == "NONE":
            add("S2", trader.p, "NONE", 0.0, True, reason="the trader stayed out, so there was no risk call")
        elif ok and "risk" in calls:
            stake = parse_risk(calls["risk"].text)
            add("S2", trader.p, trader.side, stake, stake is not None, reason=calls["risk"].text[:300])
        else:
            add("S2", None, None, None, False, reason="")
    if "S3" in structures:  # p clipped as in S4's pooling, so a stated 0 or 1 cannot stake the whole Kelly edge
        clipped = min(1 - s.p_clip, max(s.p_clip, trader.p)) if ok else None
        side, stake = mechanical(clipped, event.price, s.kelly_fraction) if ok else (None, None)
        add("S3", trader.p if ok else None, side, stake, ok)
    if "S4" in structures:
        ps = [p for p in [trader.p if ok else None, *(parse_member(calls[f"member{k}"].text) for k in MEMBERS
                                                     if f"member{k}" in calls)] if p is not None]
        if ps:
            pooled = pool(ps, s.p_clip)
            side, stake = mechanical(pooled, event.price, s.kelly_fraction)
            add("S4", pooled, side, stake, True, members_parsed=len(ps))
        else:
            add("S4", None, None, None, False, members_parsed=0)
    return rows
