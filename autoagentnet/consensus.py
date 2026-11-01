"""Consensus among agents' answers: the cheap signal the dynamic network blocks act on.

Terms:
  answer group    agents whose final answers are equivalent under the task's grader
                  (so "1/2" and "0.5" are one group for a math task); a missing answer
                  is a group of its own and never agrees with anything
  plurality       the largest answer group (ties go to the group that appeared first)
  plurality share size of the plurality group / number of agents: 1.0 means unanimous,
                  1/n means every agent said something different
"""

from __future__ import annotations

from .tasks import Grader, answers_match


def answer_groups(answers: list[str | None], grader: Grader = "exact") -> list[list[int]]:
    """Positions of equivalent answers, grouped; each answer joins the first group whose
    first member it matches."""
    groups: list[list[int]] = []
    for i, answer in enumerate(answers):
        home = None
        if answer is not None:
            for group in groups:
                first = answers[group[0]]
                if first is not None and answers_match(first, answer, grader):
                    home = group
                    break
        if home is None:
            groups.append([i])
        else:
            home.append(i)
    return groups


def plurality(answers: list[str | None], grader: Grader = "exact") -> tuple[str | None, float]:
    """(plurality answer, plurality share). (None, 0.0) when nobody gave an answer."""
    groups = [g for g in answer_groups(answers, grader) if answers[g[0]] is not None]
    if not groups:
        return None, 0.0
    largest = max(len(g) for g in groups)
    winner = next(g for g in groups if len(g) == largest)
    return answers[winner[0]], largest / len(answers)
