"""Agent insurance: pricing cover for losses caused by LLM agents that act on someone's behalf.

An insurer needs three things for any line of business, and this package builds each one
from agent traces rather than from claims history (there is none yet):

  frequency   how often an insured agent episode ends in a default (events.py, actuarial.py)
  severity    how many dollars a default puts at risk, and what share is lost (events.py)
  dependence  how defaults move together: the same hard task failing on every retry, one
              foundation model failing for every customer at once, and an error spreading
              through a multi-agent pipeline (actuarial.py, contagion.py, portfolio.py)

Terms used throughout:
  episode     one task an agent was asked to do for a principal (a customer conversation,
              a trader's session, a network's answer to one question). The unit of exposure.
  default     an episode whose outcome breaches the agent's mandate: a wrong final state,
              a wrong answer, or an action outside the principal's limits.
  commission  a default in which the agent changed external state (refunded, cancelled,
              booked, traded). These carry dollar exposure.
  omission    a default in which the agent failed to do what was needed but changed nothing.
  exposure    gross dollar value of the objects a defaulting episode touched (the order, the
              reservation, the trade). An upper bound on the loss, like insured value in
              property cover.
  LGD         loss given default: the share of exposure actually lost after reversals and
              recoveries. Not observable in benchmarks, so it is an underwriting assumption.
"""
