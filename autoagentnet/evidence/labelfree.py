"""Source accuracy without answer keys: a one-coin Dawid-Skene model fitted by EM (step 0.8; H17).

The model, in plain words: each item has one true answer, which is one of the answers the panel gave.
Each source s is right with probability a_s on every item, whatever the item; when wrong, it gives one
of the item's other candidate answers, each equally likely. Every call of a source is a separate draw
with the same a_s. The EM loop alternates:
  E step  for each item, the posterior probability that each candidate is the true answer, given every
          call's answer and the current accuracies (candidates start equally likely);
  M step  a_s = the expected share of the source's calls that gave the true answer.
Accuracies start at 0.7 and are kept in [0.01, 0.99]. The output also gives, per item, the posterior
probability of the plurality answer: a label-free confidence.

Answers are grouped into candidates by the task's grader (`same(a, b)`); an unparsed answer is never a
candidate and counts as wrong.

Label space (audit 68, finding 5). By default (labels=None) the true answer must be one of the item's observed
candidates and a wrong call picks one of the item's other observed candidates, so an item with two candidates makes
every wrong call look like a vote for the other one. That misranks sources even when calls are independent (on the
simulation, a medium source at 0.65 was estimated at 0.96 and a strong one at 0.75 at 0.51). With labels=L, each
item has L possible answers: a wrong call picks one of the L - 1 other labels, each with probability (1 - a_s)/(L - 1),
and the truth may be one of the L - K labels nobody gave (one pooled "unobserved" candidate with prior weight
(L - K)/L; every parsed call is wrong under it). L = K on every item reproduces the default.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def candidates(answers: list, same) -> tuple[list, list[int | None]]:
    """Distinct answers of one item and each answer's candidate index (None when unparsed)."""
    reps, index = [], []
    for a in answers:
        if not isinstance(a, str):
            index.append(None)
            continue
        home = next((k for k, r in enumerate(reps) if same(r, a)), None)
        if home is None:
            reps.append(a)
            home = len(reps) - 1
        index.append(home)
    return reps, index


def space(K: int, labels: int | None) -> tuple[int, float]:
    """(L, log prior weight of the unobserved candidate) for an item with K observed candidates."""
    L = K if labels is None else max(int(labels), K)
    return L, (np.log(L - K) if L > K else -np.inf)


def dawid_skene(rows: pd.DataFrame, same, iters: int = 100, tol: float = 1e-8,
                labels: int | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """rows: one per call with columns item, source, answer. Returns (accuracy per source, per-item table of
    the label-free answer (the most probable candidate), its posterior, and the plurality answer's posterior).
    labels: the size of the label space (see the module docstring); None = the item's observed candidates."""
    sources = sorted(rows["source"].unique())
    s_index = {s: k for k, s in enumerate(sources)}
    items = []
    for item, g in rows.groupby("item", sort=True):
        reps, idx = candidates(g["answer"].tolist(), same)
        items.append((item, reps, idx, [s_index[s] for s in g["source"]]))
    acc = np.full(len(sources), 0.7)
    for _ in range(iters):
        right, total = np.zeros(len(sources)), np.zeros(len(sources))
        posts = []
        for _, reps, idx, src in items:
            K = len(reps)
            if K == 0:
                posts.append(np.array([]))
                for s in src:
                    total[s] += 1
                continue
            L, unobserved = space(K, labels)
            logp = np.append(np.zeros(K), unobserved)  # the last entry: the truth is a label nobody gave
            for c, s in zip(idx, src):
                wrong = np.log(max((1 - acc[s]) / max(L - 1, 1), 1e-12))
                if c is None:
                    logp += np.log(1 - acc[s])
                else:
                    logp[:K] += np.where(np.arange(K) == c, np.log(acc[s]), wrong)
                    logp[K] += wrong
            post = np.exp(logp - logp.max())
            post = (post / post.sum())[:K]
            posts.append(post)
            for c, s in zip(idx, src):
                total[s] += 1
                if c is not None:
                    right[s] += post[c]
        new = np.clip(right / np.maximum(total, 1), 0.01, 0.99)
        done = np.max(np.abs(new - acc)) < tol
        acc = new
        if done:
            break
    table = []
    for (item, reps, idx, _), post in zip(items, posts):
        if not reps:
            table.append({"item": item, "answer": None, "posterior": 0.0, "plurality_posterior": 0.0})
            continue
        counts = np.bincount([c for c in idx if c is not None], minlength=len(reps))
        plurality = int(np.argmax(counts))
        best = int(np.argmax(post))
        table.append({"item": item, "answer": reps[best], "posterior": float(post[best]),
                      "plurality_posterior": float(post[plurality])})
    return pd.Series(acc, index=sources, name="accuracy"), pd.DataFrame(table)


def dawid_skene_pooled(rows: pd.DataFrame, same, iters: int = 100, tol: float = 1e-8,
                       labels: int | None = None) -> tuple[pd.Series, pd.DataFrame]:
    """Dependence-aware Dawid-Skene (session E5, patch 2.4): the same one-coin model, but over sources, not calls.

    Plain words: plain Dawid-Skene treats every call as an independent witness, so five calls of one model that
    share its mistakes outvote one call of a better model five to one, and EM then rates the better model as
    unreliable (the "consensus inversion" seen on Phase 1, where Sol was estimated at 62.5% against a true 97.3%).
    Here each source's calls on an item are pooled into one soft vote: the share of its calls on each candidate
    (unparsed calls count as a vote for "none of them"). Each source then contributes one witness per item:
      E step  log P(candidate c is true) += sum over the source's vote shares v_k of v_k log P(vote k | truth c),
              with P(vote k | truth c) = a_s when k = c and (1 - a_s) / (K - 1) otherwise, and log(1 - a_s) for
              the "none" share;
      M step  a_s = the expected share of the source's votes on the true answer, averaged over items (each item
              weighs once, however many calls the source made).
    Same inputs, outputs and label-space option as `dawid_skene`."""
    sources = sorted(rows["source"].unique())
    s_index = {s: k for k, s in enumerate(sources)}
    items = []
    for item, g in rows.groupby("item", sort=True):
        reps, idx = candidates(g["answer"].tolist(), same)
        K = len(reps)
        votes = {}  # source -> (vote share per candidate, share unparsed)
        for s, frame in pd.DataFrame({"s": [s_index[s] for s in g["source"]], "c": idx}).groupby("s"):
            share = np.zeros(K)
            none = 0.0
            for c in frame["c"]:
                if c is None or (isinstance(c, float) and np.isnan(c)):
                    none += 1
                else:
                    share[int(c)] += 1
            n = len(frame)
            votes[s] = (share / n, none / n)
        items.append((item, reps, idx, votes))
    acc = np.full(len(sources), 0.7)
    for _ in range(iters):
        right, total = np.zeros(len(sources)), np.zeros(len(sources))
        posts = []
        for _, reps, _, votes in items:
            K = len(reps)
            if K == 0:
                posts.append(np.array([]))
                for s in votes:
                    total[s] += 1
                continue
            L, unobserved = space(K, labels)
            logp = np.append(np.zeros(K), unobserved)
            for s, (share, none) in votes.items():
                wrong = np.log(max((1 - acc[s]) / max(L - 1, 1), 1e-12))
                # vote share on c counts as right if c is true; the rest of the parsed share counts as wrong
                logp[:K] += share * np.log(acc[s]) + (share.sum() - share) * wrong + none * np.log(1 - acc[s])
                logp[K] += share.sum() * wrong + none * np.log(1 - acc[s])
            post = np.exp(logp - logp.max())
            post = (post / post.sum())[:K]
            posts.append(post)
            for s, (share, _) in votes.items():
                total[s] += 1
                right[s] += float(post @ share)
        new = np.clip(right / np.maximum(total, 1), 0.01, 0.99)
        done = np.max(np.abs(new - acc)) < tol
        acc = new
        if done:
            break
    table = []
    for (item, reps, idx, _), post in zip(items, posts):
        if not reps:
            table.append({"item": item, "answer": None, "posterior": 0.0, "plurality_posterior": 0.0})
            continue
        counts = np.bincount([c for c in idx if c is not None], minlength=len(reps))
        plurality = int(np.argmax(counts))
        best = int(np.argmax(post))
        table.append({"item": item, "answer": reps[best], "posterior": float(post[best]),
                      "plurality_posterior": float(post[plurality])})
    return pd.Series(acc, index=sources, name="accuracy"), pd.DataFrame(table)
