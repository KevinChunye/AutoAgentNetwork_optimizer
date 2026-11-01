"""T5's factor model: predict every composition from single calls.

Terms (plain words first):
  p_ic          the probability that one sample of config c answers item i correctly.
  factor model  logit p_ic = alpha_c + beta_i + sum_r U_ir V_cr: a config's general ability alpha_c, an item's easiness
                beta_i, and r latent traits (U_i of the item, V_c of the config) that let configs differ in *which*
                items they get right (e.g. quantization hurting hard items more). Fitted by penalized maximum
                likelihood on the binomial counts (right samples out of k), with a ridge penalty
                0.5 x l2 x (|U|^2 + |V|^2) + 0.5 x l2_item x |beta|^2.
  two steps     config parameters (alpha, V) are fitted on the 70% fit items only; on the held-out items they are
                frozen and only the item parameters (beta_i, U_i) are fitted, from one probe sample per config (call
                0), with the fit items' spread of beta and U as the prior (fit_items). The compositions are scored on the other calls (1..5), so no prediction sees the samples it is
                scored against.
  wrong answers when a sample is wrong, its class is drawn from the item's wrong-answer distribution q_i, pooled over
                all configs' wrong probe samples on the item: each observed wrong class in proportion to its count; wrong
                answers seen only once ("singletons") are treated as unique (a fresh class that never ties another).
                Pooling across configs is the model's main assumption: configs share an item's attractive mistakes.
  prediction    a composition's accuracy on an item: the mean vote credit over Monte-Carlo draws from this model
                (independent draws given p_ic and q_i), with the same tie rule and cascade rule as compose.py.
  baseline      the same model and the same unique-answer mass, but the shared wrong answers spread evenly over the
                item's wrong classes seen at least twice, instead of in proportion to how often each was seen. It
                adapts to each item's answer space (audit T1-2, finding 1), so the comparison isolates what T5 is
                about: whether *which* wrong answers coincide, and how often, carries over from single calls to
                compositions.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from .compose import Samples, vote_credit


@dataclass
class FactorFit:
    systems: list[str]
    alpha: np.ndarray
    V: np.ndarray
    beta: np.ndarray | None = None
    U: np.ndarray | None = None


def _counts(s: Samples, systems: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """Y (items x configs): right samples; M: samples."""
    Y = np.stack([s.right[c].sum(axis=1) for c in systems], axis=1)
    M = np.stack([(s.cls[c] >= -1).sum(axis=1) for c in systems], axis=1).astype(float)
    return Y, M


def _nll(logit, Y, M):
    return float(np.sum(M * np.logaddexp(0, logit) - Y * logit))


def fit_configs(s: Samples, systems: list[str], rank: int = 2, l2: float = 1.0, l2_item: float = 0.1,
                iters: int = 500) -> FactorFit:
    """Fit alpha_c, V_c (and the fit items' beta_i, U_i) on the fit items."""
    Y, M = _counts(s, systems)
    n, m = Y.shape
    rng = np.random.default_rng(0)
    x0 = np.concatenate([np.zeros(m), np.zeros(n), 0.1 * rng.standard_normal(n * rank), 0.1 * rng.standard_normal(m * rank)])

    def unpack(x):
        a, b = x[:m], x[m:m + n]
        U = x[m + n:m + n + n * rank].reshape(n, rank)
        V = x[m + n + n * rank:].reshape(m, rank)
        return a, b, U, V

    def f(x):
        a, b, U, V = unpack(x)
        logit = a[None, :] + b[:, None] + U @ V.T
        p = 1 / (1 + np.exp(-logit))
        g = M * p - Y  # d nll / d logit
        value = _nll(logit, Y, M) + 0.5 * l2 * (np.sum(U ** 2) + np.sum(V ** 2)) + 0.5 * l2_item * np.sum(b ** 2)
        grad = np.concatenate([g.sum(axis=0), g.sum(axis=1) + l2_item * b, (g @ V + l2 * U).ravel(), (g.T @ U + l2 * V).ravel()])
        return value, grad

    res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": iters})
    a, b, U, V = unpack(res.x)
    return FactorFit(systems, a, V, b, U)


def fit_items(s: Samples, fit: FactorFit, iters: int = 500) -> FactorFit:
    """Freeze alpha, V; fit beta_i, U_i of the items in `s` from their samples, by maximum a posteriori with an
    empirical-Bayes prior: beta ~ N(mean, variance of the fit items' beta), U_r ~ N(0, variance of the fit items'
    U_r). With one probe sample per config an item has only one binary outcome per config, and a flat prior would
    send items every config got right (or wrong) to p = 1 (or 0)."""
    Y, M = _counts(s, fit.systems)
    n, rank = len(s.items), fit.V.shape[1]
    mu = float(np.mean(fit.beta))
    w_b = 1 / max(float(np.var(fit.beta)), 1e-3)
    w_u = 1 / np.maximum(np.var(fit.U, axis=0), 1e-3)

    def f(x):
        b, U = x[:n], x[n:].reshape(n, rank)
        logit = fit.alpha[None, :] + b[:, None] + U @ fit.V.T
        g = M / (1 + np.exp(-logit)) - Y
        value = _nll(logit, Y, M) + 0.5 * np.sum(w_u * U ** 2) + 0.5 * w_b * np.sum((b - mu) ** 2)
        return value, np.concatenate([g.sum(axis=1) + w_b * (b - mu), (g @ fit.V + w_u * U).ravel()])

    x0 = np.concatenate([np.full(n, mu), np.zeros(n * rank)])
    res = minimize(f, x0, jac=True, method="L-BFGS-B", options={"maxiter": iters})
    return FactorFit(fit.systems, fit.alpha, fit.V, res.x[:n], res.x[n:].reshape(n, rank))


def probabilities(fit: FactorFit) -> dict[str, np.ndarray]:
    logit = fit.alpha[None, :] + fit.beta[:, None] + fit.U @ fit.V.T
    p = 1 / (1 + np.exp(-logit))
    return {c: p[:, j] for j, c in enumerate(fit.systems)}


def wrong_distribution(s: Samples, systems: list[str]) -> tuple[np.ndarray, np.ndarray]:
    """(q, unique): q[i, cls] = the share of item i's wrong samples (over all configs) in class cls, counting only
    classes seen at least twice; unique[i] = the share that were singletons or unparsed (each a class of its own)."""
    width = s.class_right.shape[1]
    counts = np.zeros((len(s.items), width))
    unparsed = np.zeros(len(s.items))
    for c in systems:
        C, R = s.cls[c], s.right[c]
        wrong = R < 0.5
        unparsed += (wrong & (C < 0)).sum(axis=1)
        rows = np.repeat(np.arange(len(s.items)), C.shape[1])
        ok = (wrong & (C >= 0)).ravel()
        np.add.at(counts, (rows[ok], C.ravel()[ok]), 1)
    singles = np.where(counts == 1, 1.0, 0.0)
    total = counts.sum(axis=1) + unparsed
    q = np.where(counts >= 2, counts, 0.0) / np.maximum(total, 1)[:, None]
    unique = (singles.sum(axis=1) + unparsed) / np.maximum(total, 1)
    unique = np.where(total > 0, unique, 1.0)
    return q, unique


class Predictor:
    """Monte-Carlo predictions of composition accuracy from p_ic and q_i (or the even-spread baseline)."""

    def __init__(self, s: Samples, p: dict[str, np.ndarray], q: np.ndarray, unique: np.ndarray, draws: int = 400,
                 seed: int = 0, baseline: bool = False):
        self.s, self.p, self.draws = s, p, draws
        self.rng = np.random.default_rng(seed)
        self.width = s.class_right.shape[1]
        if baseline:  # the same unique mass, the rest spread evenly over the item's shared wrong classes
            shared = q > 0
            q = np.where(shared, (1 - unique)[:, None] / np.maximum(shared.sum(axis=1), 1)[:, None], 0.0)
        self.q, self.unique = q, unique
        gold = np.where(s.class_right.max(axis=1) > 0, s.class_right.argmax(axis=1), self.width)
        self.gold = gold  # the right class of each item (width = none seen)

    def _draw(self, system: str, n: int) -> np.ndarray:
        """Classes of n simulated samples: items x draws x n. Right -> gold class; wrong -> a class from q, or a fresh
        class id (>= width + 1, never shared) for unique wrong answers."""
        items = len(self.s.items)
        u = self.rng.random((items, self.draws, n))
        right = u < self.p[system][:, None, None]
        v = self.rng.random((items, self.draws, n))
        cum = np.cumsum(self.q, axis=1)
        fresh = self.width + 1 + np.arange(items * self.draws * n).reshape(items, self.draws, n)
        picked = (v[..., None] > cum[:, None, None, :]).sum(axis=-1)
        is_unique = v >= cum[:, -1][:, None, None]
        wrong_cls = np.where(is_unique, fresh, np.minimum(picked, self.width - 1))
        return np.where(right, self.gold[:, None, None], wrong_cls)

    def _credit(self, C: np.ndarray) -> np.ndarray:
        """items x draws vote credit for simulated classes C (items x draws x n): right iff the plurality is gold."""
        items, draws, n = C.shape
        flat = C.reshape(items * draws, n)
        out = np.zeros(items * draws)
        for j in range(n):
            same = (flat == flat[:, [j]]).sum(axis=1)
            out = np.maximum(out, same)
        top = out
        gold = np.repeat(self.gold, draws)
        gold_votes = (flat == gold[:, None]).sum(axis=1)
        n_tied = np.zeros(items * draws)
        for j in range(n):  # number of distinct classes reaching the top count
            same = (flat == flat[:, [j]]).sum(axis=1)
            first = (flat[:, :j] != flat[:, [j]]).all(axis=1)
            n_tied += (same == top) & first
        credit = np.where(gold_votes == top, 1.0 / np.maximum(n_tied, 1), 0.0)
        return credit.reshape(items, draws)

    def predict(self, comp: dict) -> np.ndarray:
        """Per item: the predicted credit of a composition (compose.compositions format)."""
        C = np.concatenate([self._draw(system, n) for system, n in comp["parts"]], axis=2)
        credit = self._credit(C)
        if comp["kind"] == "cascade":
            n = C.shape[2]
            top = np.zeros(C.shape[:2])
            for j in range(n):
                top = np.maximum(top, (C == C[:, :, [j]]).sum(axis=2))
            accept = top / n >= comp["t"] - 1e-9
            credit = np.where(accept, credit, self.p[comp["escalate"]][:, None])
        return credit.mean(axis=1)


def predict_heldout(s_fit: Samples, s_probe: Samples, systems: list[str], comps: list[dict], rank: int = 2,
                    draws: int = 400, baseline: bool = False) -> np.ndarray:
    """Predicted mean accuracy of each composition on the held-out items. Config parameters come from s_fit (the fit
    items); the held-out items' parameters and wrong-answer distributions come from s_probe (their call 0 only), so
    the predictions never see the samples the compositions are scored on (calls 1..k-1)."""
    fit = fit_items(s_probe, fit_configs(s_fit, systems, rank))
    q, unique = wrong_distribution(s_probe, systems)
    pred = Predictor(s_probe, probabilities(fit), q, unique, draws, baseline=baseline)
    return np.array([pred.predict(c).mean() for c in comps])
