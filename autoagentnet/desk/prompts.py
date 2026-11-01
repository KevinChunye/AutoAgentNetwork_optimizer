"""Prompts and reply parsing for the conviction desk (W2-A).

Rule from the pilot (research/v3/program.md, "Rules that carry over", 6): instructions carry no
concrete example values, only placeholders such as <probability>; every template's sha256 is
recorded (TEMPLATE_HASHES) so a result can be tied to the exact wording.

Roles:
  trader     states a probability, a side and a stake (S1; its probability also feeds S2 and S3,
             and it is committee member 1 in S4)
  risk       the risk manager of S2: sets the stake from the trader's probability, the price and the
             trader's track record; never sees the clues or the news item
  member k   committee members 2-6 of S4: state a probability only, each with its own way of working
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .events import Event

RULES = """You work on a prediction desk that trades yes/no events.
- A YES contract costs the market price and pays $1 if the event happens, $0 if not.
- A NO contract costs $1 minus the market price and pays $1 if the event does not happen.
- The desk stakes a fraction of its current bankroll on one side, or stays out. A stake on the losing side is lost.
- For each event you get its base rate (how often events like it happen), a few independent clues and the market price.
- Each clue points to YES or NO and states its accuracy: the chance that it points the right way.
- The base rate and the clues are the only evidence about the outcome.
- The market sets its price from the base rate and part of what the clues say, plus random noise; it knows nothing more."""

TRADER_SYSTEM = """You are the desk's trader. Decide how likely the event is, which side to buy, and how much of the
bankroll to stake.
You may work through the numbers briefly first. End your reply with exactly these four lines:
REASON: <one sentence>
PROBABILITY: <your probability that the event happens, a number from 0 to 1>
SIDE: <YES, NO or NONE>
STAKE: <fraction of the bankroll to stake, a number from 0 to 1; 0 when SIDE is NONE>"""

RISK_SYSTEM = """You are the desk's risk manager. The trader has chosen a side and stated a probability that the event
happens. You do not see the trader's evidence. You set the stake on the trader's side, using the trader's
probability, the market price and the trader's track record.
You may work through the numbers briefly first. End your reply with exactly these two lines:
REASON: <one sentence>
STAKE: <fraction of the bankroll to stake on the trader's side, a number from 0 to 1>"""

MEMBER_WAYS = {
    2: "Start from the base rate, then update for each clue in turn by how accurate it is.",
    3: "Count the clues for and against, weigh each by its accuracy, then settle on a probability.",
    4: "Work out what the market price implies, then decide how far the clues should move you from it.",
    5: "Form your estimate, then ask how you could be wrong and adjust for that.",
    6: "Treat the clues as noisy witnesses: think about how often witnesses this accurate agree by chance.",
}

MEMBER_SYSTEM = """You are a member of the desk's committee. Estimate how likely the event is; other members estimate
too, and the desk combines the estimates. Your way of working: {way}
You may work through the numbers briefly first. End your reply with exactly these two lines:
REASON: <one sentence>
PROBABILITY: <your probability that the event happens, a number from 0 to 1>"""


def member_system(k: int) -> str:
    return MEMBER_SYSTEM.format(way=MEMBER_WAYS[k])


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


TEMPLATE_HASHES = {"rules": sha(RULES), "trader": sha(TRADER_SYSTEM), "risk": sha(RISK_SYSTEM),
                   "member": sha(MEMBER_SYSTEM), **{f"member{k}_way": sha(way) for k, way in MEMBER_WAYS.items()}}


def percent(x: float) -> str:
    return f"{100 * x:.0f}%"


def event_text(event: Event) -> str:
    """What the trader and the committee see about one event. The news item, when there is one,
    sits between the clues and the price."""
    lines = [f"Event {event.event_id}.", f"Base rate: events like this happen {percent(event.prior)} of the time.",
             "Clues (independent of each other):"]
    lines += [f"{i}. Points to {c.side}. Accuracy {percent(c.accuracy)}." for i, c in enumerate(event.clues, 1)]
    if event.story:
        lines.append(f"News item: {event.story}")
    lines.append(f"Market price: YES ${event.price:.2f}, NO ${1 - event.price:.2f}.")
    return "\n".join(lines)


@dataclass
class TrackRecord:
    """The trader's record on earlier events of the same sequence where it chose a side.

    bets:        how many earlier events the trader bet on
    confidence:  mean stated probability of the chosen side
    hit_rate:    share of those bets whose side won
    """

    bets: int
    confidence: float | None
    hit_rate: float | None


def risk_text(event: Event, p: float, side: str, record: TrackRecord) -> str:
    lines = [f"Event {event.event_id}.", f"Market price: YES ${event.price:.2f}, NO ${1 - event.price:.2f}.",
             f"Trader's side: {side}.", f"Trader's probability that the event happens: {p:.2f}."]
    if record.bets == 0:
        lines.append("Track record: no earlier bets yet.")
    else:
        lines.append(f"Track record on the {record.bets} earlier bets: average confidence in the chosen side "
                     f"{percent(record.confidence)}, share of bets won {percent(record.hit_rate)}.")
    return "\n".join(lines)


NUMBER = r"([01](?:\.\d+)?|\.\d+)(?![\d.])"  # "10%" or "1.5.2" never reads as a number in [0, 1]
FIELD_RE = {
    "PROBABILITY": re.compile(rf"^\W*PROBABILITY\W*:\s*\**\s*{NUMBER}\s*(%?)", re.I | re.M),
    "STAKE": re.compile(rf"^\W*STAKE\W*:\s*\**\s*{NUMBER}\s*(%?)", re.I | re.M),
    "SIDE": re.compile(r"^\W*SIDE\W*:\s*\**\s*(YES|NO|NONE)\b", re.I | re.M),
    "REASON": re.compile(r"^\W*REASON\W*:\s*(.+)$", re.I | re.M),
}


def field(text: str, name: str) -> str | float | None:
    """One field of a reply: a number in [0, 1] (a percent sign is not allowed; such a reply is
    unparsed), a side, or the reason. The last occurrence counts, because the final lines are the
    answer and any working comes before them. None when it is missing or out of range."""
    matches = list(FIELD_RE[name].finditer(text or ""))
    if not matches:
        return None
    m = matches[-1]
    if name == "SIDE":
        return m.group(1).upper()
    if name == "REASON":
        return m.group(1).strip()
    if m.group(2):
        return None
    value = float(m.group(1))
    return value if 0 <= value <= 1 else None


@dataclass
class TraderReply:
    p: float | None
    side: str | None
    stake: float | None
    reason: str

    @property
    def parsed(self) -> bool:
        return self.p is not None and self.side is not None and self.stake is not None


def parse_trader(text: str) -> TraderReply:
    side = field(text, "SIDE")
    stake = field(text, "STAKE")
    if side == "NONE" and stake is None:
        stake = 0.0
    return TraderReply(field(text, "PROBABILITY"), side, stake, field(text, "REASON") or "")


def parse_member(text: str) -> float | None:
    return field(text, "PROBABILITY")


def parse_risk(text: str) -> float | None:
    return field(text, "STAKE")
