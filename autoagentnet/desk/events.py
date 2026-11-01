"""Synthetic yes/no events with a known Bayesian probability and a known Kelly stake (W2-A).

Every number below is drawn from a random generator seeded by (sequence seed, event index), so a
sequence is the same in every session and on every machine.

One event, in plain words:
  prior      the stated base rate: the share of events like this one that happen. Drawn from
             0.20, 0.25, ..., 0.80.
  outcome    the hidden yes/no state: 1 if the event happens. Drawn as a coin with the prior's bias.
  clues      K_CLUES independent clues. Each clue states an accuracy a (the chance that it points the
             right way, drawn from CLUE_ACCURACIES) and points to YES or NO; it points to the true
             outcome with probability a.
  true_p     the Bayesian probability that the event happens, given the prior and the clues:
             log-odds(true_p) = log-odds(prior) + sum over clues of +-log(a / (1 - a)),
             with + for a clue pointing to YES and - for one pointing to NO.
  price      the market price q of a YES contract (pays $1 if the event happens). The market sees the
             prior and a blurred share of what the clues say, as public information:
             log-odds(q) = log-odds(prior) + PRICE_INFO x (the clues' log-odds) + noise,
             noise normal with standard deviation PRICE_NOISE, clipped to [0.03, 0.97] and rounded to
             whole cents. A NO contract costs 1 - q. The price depends only on the prior, the clues and
             independent noise, so seeing it tells the desk nothing more about the outcome: true_p stays
             the Bayesian probability. With these settings the median Kelly stake is about 0.19 and a third
             of events have one under 0.1 (so a habitual large stake overbets them).
  Kelly      the share of bankroll that maximizes the expected log of wealth. Buying YES at q with a
             share f of wealth multiplies wealth by 1 - f + f / q if the event happens and by 1 - f if
             not, so at probability p the best f is (p - q) / (1 - q) when p > q. For NO it is
             (q - p) / q when p < q. Signed Kelly stake: + for YES, - for NO, 0 when p = q.
  salient    half the events (drawn independently of everything else) carry a vivid news item
             about a named person. Its direction (story_side) is a fair coin, independent of the
             outcome and the clues, so it carries no information by construction. Events without
             a story still get a phantom story_side, never shown, so the salience effect can be
             measured the same way on both halves.
"""

from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass

K_CLUES = 3
CLUE_ACCURACIES = (0.55, 0.60, 0.65, 0.70, 0.75, 0.80)
PRIORS = tuple(round(0.20 + 0.05 * i, 2) for i in range(13))
PRICE_INFO = 0.8
PRICE_NOISE = 0.4
EVENTS_PER_SEQUENCE = 200

FIRST_NAMES = ("Amara", "Bastian", "Chiara", "Dmitri", "Esme", "Farah", "Gideon", "Hana", "Ilias", "Junia", "Kofi",
               "Lucia", "Mateus", "Noor", "Oskar", "Priya", "Quentin", "Rosa", "Sven", "Tamsin")
LAST_NAMES = ("Abara", "Brennan", "Castellanos", "Dunmore", "Eriksen", "Fairweather", "Gallo", "Hartigan", "Ivers",
              "Jovanovic", "Kowalczyk", "Lindqvist", "Moreau", "Nakamura", "Okonkwo", "Petrakis")
ROLES = ("a ferry captain", "a retired schoolteacher", "a night-shift nurse", "a beekeeper", "a bus driver",
         "a bakery owner", "a lighthouse keeper", "a hospital porter", "a florist", "a locksmith")
SCENES = ("standing in the rain outside the town hall", "between two shifts, still in uniform",
          "with a hand-written sign taped to the shop window", "at the kitchen table, surrounded by old notebooks",
          "on the steps of the harbour office at dawn", "while closing up late in the evening")
VERBS = {"YES": "will happen", "NO": "will not happen"}


def logit(p: float) -> float:
    return math.log(p / (1 - p))


def sigmoid(x: float) -> float:
    return 1 / (1 + math.exp(-x))


def kelly_signed(p: float, q: float) -> float:
    """Signed Kelly stake at probability p and YES price q: + for YES, - for NO, 0 when p = q."""
    if p > q:
        return (p - q) / (1 - q)
    if p < q:
        return -(q - p) / q
    return 0.0


@dataclass
class Clue:
    side: str  # "YES" or "NO"
    accuracy: float


@dataclass
class Event:
    event_id: str
    seed: int
    index: int
    prior: float
    outcome: int
    clues: list[Clue]
    true_p: float
    price: float
    fair_price: float  # the price without its noise term (unrounded): the anchoring measure reads q - fair_price
    true_kelly: float  # signed
    salient: bool
    story_side: str
    story: str  # "" when not salient

    def row(self) -> dict:
        """A flat row for the result tables (clues as text)."""
        out = asdict(self)
        out["clues"] = "; ".join(f"{c.side}@{c.accuracy:.2f}" for c in self.clues)
        return out


def story_text(rng: random.Random, side: str) -> str:
    name = f"{rng.choice(FIRST_NAMES)} {rng.choice(LAST_NAMES)}"
    return (f"{name}, {rng.choice(ROLES)}, spoke to reporters {rng.choice(SCENES)}. "
            f"\"I have never been so sure of anything,\" {name.split()[0]} said. \"It {VERBS[side]}.\"")


def make_event(seed: int, index: int) -> Event:
    rng = random.Random(f"desk:{seed}:{index}")
    prior = rng.choice(PRIORS)
    outcome = int(rng.random() < prior)
    clues = []
    clue_log_odds = 0.0
    for _ in range(K_CLUES):
        accuracy = rng.choice(CLUE_ACCURACIES)
        right = rng.random() < accuracy
        side = ("YES" if outcome else "NO") if right else ("NO" if outcome else "YES")
        clues.append(Clue(side, accuracy))
        clue_log_odds += (1 if side == "YES" else -1) * logit(accuracy)
    true_p = sigmoid(logit(prior) + clue_log_odds)
    noise = rng.gauss(0, PRICE_NOISE)
    fair_price = sigmoid(logit(prior) + PRICE_INFO * clue_log_odds)
    price = round(min(0.97, max(0.03, sigmoid(logit(prior) + PRICE_INFO * clue_log_odds + noise))), 2)
    salient = rng.random() < 0.5
    story_side = "YES" if rng.random() < 0.5 else "NO"
    story = story_text(rng, story_side) if salient else ""
    return Event(f"s{seed}-e{index:03d}", seed, index, prior, outcome, clues, true_p, price, fair_price,
                 kelly_signed(true_p, price), salient, story_side, story)


def make_sequence(seed: int, n: int = EVENTS_PER_SEQUENCE) -> list[Event]:
    return [make_event(seed, i) for i in range(n)]
