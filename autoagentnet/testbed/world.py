"""A synthetic world with known answers, behind the fake backend: the offline tests and the power simulations run the
whole pipeline on it and check that the analysis recovers what was put in.

Generative model (plain words first; every random draw is a fixed function of named keys, so a call's outcome is the
same whether it comes from the fake vLLM server or from the vectorized `table`):
  item i         has a difficulty b_i (normal, mean by benchmark), a gold answer class, an "attractor" wrong class
                 that wrong answers favour (share pi_i of the wrong answers, the source of correlated errors), and a
                 thinking need n_i (tokens of thinking that would solve it fully; harder items need more).
  ability        a(size) = a0 + slope x log2(size / 4), the log-odds of a right answer on an item of difficulty 0
                 with thinking off.
  knowledge      e_{i,size}: what one model of the family happens to know about item i, shared by every precision and
                 budget of that size; correlated across sizes (rho_size) because the sizes share pretraining data.
  depth          g = gamma x (used / n_i)^0.7 with used = min(this sample's need, budget): thinking helps with
                 diminishing returns, and a budget below the need cuts the gain (budget forcing).
  quantization   a shift -delta_p x s(size) x (1 + kappa x max(b_i, 0)) that is larger on hard items (systematic), plus
                 noise q of spread sigma_p x s(size), s(size) = sqrt(4 / size). In the default world q is a fixed
                 function of (item, size, precision): the quantized weights are fixed, so every sample of that model
                 meets the same perturbation. With `diversify = True` q is drawn per sample instead: quantization then
                 acts like extra sampling noise, which votes can average away (the alternative T1 tests against).
  a sample       is right with probability sigmoid(L), L = a(size) + g - b_i + e_{i,size} - shift + q (+ a family
                 offset); a wrong sample gives the attractor with probability pi_i, else another wrong class. With
                 attractor_by_checkpoint each checkpoint has its own attractor on each item (wrong answers are not
                 shared across models: the misspecified world for T5, whose model pools them).
  signals        white-box: mean log-prob, entropy and answer margin are noisy functions of sigmoid(L) and of whether
                 the sample is right (so they carry some but not all of the information).
  self-check     the config re-reads its own answer: it recognises right from wrong with probability r = sigmoid(1 + L);
                 otherwise it says "yes" with probability 0.7 (it tends to approve itself).
  judge          picks among candidates by signal detection: every candidate scores d' x (1 if right) + standard
                 normal noise and the highest score wins; d' = max(0, judge_d - judge_coupling x b_i) falls with
                 difficulty when judge_coupling > 0 (the coupling T4 looks for) and is constant when it is 0.
  execution      (code items) visible tests pass with probability 0.95 for a right program and 0.3 for a wrong one.
  GPU-seconds    output tokens / a throughput per size (fake-quantized checkpoints run at BF16 speed).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .grid import Config, seed_of

MASK = np.uint64(0xFFFFFFFFFFFFFFFF)


def _key(value) -> np.ndarray:
    """A uint64 key for an int, an array of ints or a string."""
    if isinstance(value, str):
        return np.uint64(int(hashlib.sha256(value.encode()).hexdigest()[:16], 16))
    return np.asarray(value).astype(np.uint64)


def _mix(x: np.ndarray) -> np.ndarray:
    """splitmix64's finalizer: a well-mixed 64-bit hash of x."""
    with np.errstate(over="ignore"):
        x = (x ^ (x >> np.uint64(30))) * np.uint64(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> np.uint64(27))) * np.uint64(0x94D049BB133111EB)
        return x ^ (x >> np.uint64(31))


def uniform(*keys) -> np.ndarray:
    """A uniform number in (0, 1) that is a fixed function of the keys (broadcast over arrays)."""
    h = np.uint64(0x9E3779B97F4A7C15)
    with np.errstate(over="ignore"):
        for k in keys:
            h = _mix(h ^ (_key(k) + np.uint64(0x9E3779B97F4A7C15) + (h << np.uint64(6)) + (h >> np.uint64(2))))
    return ((h >> np.uint64(11)).astype(np.float64) + 0.5) / float(1 << 53)


def normal(*keys) -> np.ndarray:
    """A standard normal draw that is a fixed function of the keys (Box-Muller)."""
    return np.sqrt(-2 * np.log(uniform(*keys, "n1"))) * np.cos(2 * np.pi * uniform(*keys, "n2"))


def sigmoid(x):
    return 1 / (1 + np.exp(-x))


@dataclass
class WorldParams:
    n_classes: int = 10
    a0: float = 0.4
    slope: float = 0.8
    gamma: float = 1.6
    sigma_b: float = 1.3
    bench_mean: dict = field(default_factory=lambda: {"bbeh": 0.8, "math": 0.3, "code": 0.5})
    sigma_e: float = 0.8
    rho_size: float = 0.6
    need_median: float = 1500.0
    need_per_b: float = 0.6
    delta: dict = field(default_factory=lambda: {"bf16": 0.0, "w8": 0.01, "w4": 0.12, "w4gptq": 0.15, "w3": 0.6,
                                                 "mxfp4": 0.1})
    sigma_q: dict = field(default_factory=lambda: {"bf16": 0.0, "w8": 0.05, "w4": 0.3, "w4gptq": 0.35, "w3": 0.6,
                                                   "mxfp4": 0.2})
    kappa: float = 0.6
    diversify: bool = False
    family_offset: dict = field(default_factory=lambda: {"qwen3.5": 0.0, "gpt-oss": 0.6})
    judge_d: float = 2.0
    attractor_by_checkpoint: bool = False
    judge_d_by_size: dict | None = None
    judge_d_by_bench: dict | None = None
    judge_coupling: float = 0.6
    tokens_per_s: dict = field(default_factory=lambda: {2: 25_000, 4: 15_000, 9: 8_000, 20: 10_000})
    answer_tokens: int = 300


CHECKPOINT_RE = re.compile(r"^(?P<family>.+)-(?P<size>[\d.]+)b-(?P<precision>\w+)$")


def parse_checkpoint(name: str) -> tuple[str, float, str]:
    m = CHECKPOINT_RE.match(name)
    if not m:
        raise ValueError(f"not a testbed checkpoint name: {name!r}")
    return m["family"], float(m["size"]), m["precision"]


class World:
    """A fixed draw of items (`n_items` per benchmark) under WorldParams; `salt` names the draw."""

    def __init__(self, n_items: dict | int = 60, params: WorldParams | None = None, salt: str = "world"):
        self.p = params or WorldParams()
        self.salt = salt
        counts = n_items if isinstance(n_items, dict) else {"bbeh": n_items}
        rows = []
        for bench, n in counts.items():
            rows += [{"item": f"{bench}-{j:04d}", "benchmark": bench} for j in range(n)]
        frame = pd.DataFrame(rows)
        idx = np.arange(len(frame))
        mean = frame["benchmark"].map(self.p.bench_mean).to_numpy(dtype=float)
        frame["difficulty"] = mean + self.p.sigma_b * normal(salt, "b", idx)
        frame["need"] = self.p.need_median * np.exp(self.p.need_per_b * frame["difficulty"] + 0.3 * normal(salt, "need", idx))
        K = self.p.n_classes
        frame["gold"] = (uniform(salt, "gold", idx) * K).astype(int)
        frame["attractor"] = (frame["gold"] + 1 + (uniform(salt, "attr", idx) * (K - 1)).astype(int)) % K
        frame["pi"] = 0.2 + 0.6 * uniform(salt, "pi", idx)
        self.items = frame
        self.index = {item: i for i, item in enumerate(frame["item"])}

    # ---------------------------------------------------------------- latent pieces

    def ability(self, family: str, size_b: float) -> float:
        return self.p.a0 + self.p.slope * np.log2(size_b / 4) + self.p.family_offset.get(family, 0.0)

    def knowledge(self, idx, family: str, size_b: float) -> np.ndarray:
        shared = normal(self.salt, "e-shared", family, idx)
        own = normal(self.salt, "e-own", family, int(size_b * 10), idx)
        r = self.p.rho_size
        return self.p.sigma_e * (np.sqrt(r) * shared + np.sqrt(1 - r) * own)

    def quant(self, idx, family: str, size_b: float, precision: str, seed) -> np.ndarray:
        """-shift + q for the items `idx` (and, when diversify, the sample seeds)."""
        scale = np.sqrt(4 / size_b)
        b = self.items["difficulty"].to_numpy()[idx]
        shift = self.p.delta[precision] * scale * (1 + self.p.kappa * np.maximum(b, 0))
        keys = (self.salt, "q", family, int(size_b * 10), precision, idx) + ((seed,) if self.p.diversify else ())
        return -shift + self.p.sigma_q[precision] * scale * normal(*keys)

    def need_draw(self, idx, seed) -> np.ndarray:
        """This sample's thinking need: the item's need times a lognormal factor."""
        return self.items["need"].to_numpy()[idx] * np.exp(0.3 * normal(self.salt, "need-s", idx, seed))

    def logit(self, idx, checkpoint: str, used, seed) -> np.ndarray:
        family, size, precision = parse_checkpoint(checkpoint)
        need = self.items["need"].to_numpy()[idx]
        depth = self.p.gamma * np.minimum(1.0, np.asarray(used, dtype=float) / need) ** 0.7
        b = self.items["difficulty"].to_numpy()[idx]
        return (self.ability(family, size) + depth - b + self.knowledge(idx, family, size)
                + self.quant(idx, family, size, precision, seed))

    # ---------------------------------------------------------------- one sample

    def outcome(self, idx, checkpoint: str, used, seed) -> dict:
        """Answer, correctness and signals of samples on items `idx` given the thinking tokens they used."""
        idx = np.asarray(idx)
        seed = np.asarray(seed)
        L = self.logit(idx, checkpoint, used, seed)
        p = sigmoid(L)
        right = uniform(self.salt, "draw", checkpoint, idx, seed) < p
        K = self.p.n_classes
        gold = self.items["gold"].to_numpy()[idx]
        attractor = self.items["attractor"].to_numpy()[idx]
        if self.p.attractor_by_checkpoint:  # each checkpoint has its own favourite wrong answer on each item
            attractor = (gold + 1 + (uniform(self.salt, "attr-c", checkpoint, idx) * (K - 1)).astype(int)) % K
        to_attractor = uniform(self.salt, "attract", checkpoint, idx, seed) < self.items["pi"].to_numpy()[idx]
        to_attractor = to_attractor | (K <= 2)  # with two classes the attractor is the only wrong answer
        other = (uniform(self.salt, "other", checkpoint, idx, seed) * (K - 2)).astype(int)
        low, high = np.minimum(gold, attractor), np.maximum(gold, attractor)
        other_class = other + (other >= low)  # the other-th class that is neither gold nor the attractor
        other_class = other_class + (other_class >= high)
        answer = np.where(right, gold, np.where(to_attractor, attractor, other_class))
        noise = lambda name: normal(self.salt, name, checkpoint, idx, seed)
        return {
            "logit": L, "correct": right.astype(int), "answer": answer.astype(int),
            "signal_logprob_mean": -0.45 + 0.25 * p + 0.12 * right + 0.08 * noise("s1"),
            "signal_entropy": 0.9 - 0.4 * p - 0.15 * right + 0.1 * noise("s2"),
            "signal_margin": np.logaddexp(0.0, -0.5 + 2.0 * p + 1.0 * right + 0.7 * noise("s3")),  # a gap is >= 0
        }

    def draw(self, idx, config: Config, sample) -> dict:
        """Samples `sample` (indices j) of `config` on items `idx`, thinking tokens included."""
        idx = np.asarray(idx)
        seed = np.vectorize(lambda j: seed_of(config.label, int(j)))(np.asarray(sample)) if np.size(sample) else sample
        need = self.need_draw(idx, seed)
        used = np.zeros_like(need) if config.budget == 0 else np.minimum(np.round(need), config.budget)
        out = self.outcome(idx, config.checkpoint, used, seed)
        out.update({"thinking_tokens": used.astype(int), "forced": (config.budget > 0) & (need > config.budget),
                    "seed": seed})
        return out

    # ---------------------------------------------------------------- the response table

    def table(self, configs: list[Config], k: int, items: list[str] | None = None) -> pd.DataFrame:
        """The response table every analysis reads (one row per item, config and sample), drawn directly: the same
        values the fake vLLM server produces through the executor."""
        idx_all = np.arange(len(self.items)) if items is None else np.array([self.index[i] for i in items])
        frames = []
        for config in configs:
            idx = np.repeat(idx_all, k)
            sample = np.tile(np.arange(k), len(idx_all))
            d = self.draw(idx, config, sample)
            out_tokens = d["thinking_tokens"] + self.p.answer_tokens
            frames.append(pd.DataFrame({
                "benchmark": self.items["benchmark"].to_numpy()[idx] + "/synthetic",
                "item": self.items["item"].to_numpy()[idx], "system": config.label, "family": config.family,
                "model": config.checkpoint, "size_b": float(config.size_b), "precision": config.schema_precision,
                "reasoning": config.reasoning, "scaffold": "direct", "call": sample,
                "answer": d["answer"].astype(str), "correct": d["correct"].astype(float), "cost_usd": 0.0,
                "gpu_seconds": out_tokens / self.p.tokens_per_s[int(config.size_b)], "input_tokens": 200,
                "output_tokens": out_tokens, "latency_s": 0.0,
                "signal_logprob_mean": d["signal_logprob_mean"], "signal_entropy": d["signal_entropy"],
                "signal_margin": d["signal_margin"], "signal_thinking_tokens": d["thinking_tokens"].astype(float),
                "signal_forced": d["forced"].astype(float), "source": f"world/{self.salt}", "licence": "internal"}))
        return pd.concat(frames, ignore_index=True)

    # ---------------------------------------------------------------- checkers

    def self_check(self, idx, checkpoint: str, used, seed, candidate_right) -> np.ndarray:
        """1 = the config says its own answer is right."""
        L = self.logit(np.asarray(idx), checkpoint, used, seed)
        recognise = uniform(self.salt, "sc-r", checkpoint, idx, seed) < sigmoid(1 + L)
        approve = uniform(self.salt, "sc-a", checkpoint, idx, seed) < 0.7
        return np.where(recognise, np.asarray(candidate_right, dtype=bool), approve).astype(int)

    def judge_pick(self, idx: int, judge_checkpoint: str, candidates_right: list[bool], candidate_seeds: list[int],
                   candidate_checkpoint: str | None = None) -> int:
        """Index of the candidate a judge picks (signal detection): each candidate gets a score d' x right + noise and
        the judge picks the highest. d' = max(0, judge_d - judge_coupling x b_i): with judge_coupling > 0 the judge
        tells right from wrong less well on hard items (coupling); with 0 its skill is the same everywhere, yet its
        eta still rises with the number of right candidates (more right candidates, more chances to score highest).
        With judge_d_by_size, d' depends only on the size of the model that wrote the candidates; with
        judge_d_by_bench, only on the item's benchmark (nulls for T4 in which skill varies by config or by benchmark,
        not by difficulty). Randomness is keyed by the candidates (their seeds)."""
        b = float(self.items["difficulty"].iloc[idx])
        if self.p.judge_d_by_bench:
            d = float(self.p.judge_d_by_bench[self.items["benchmark"].iloc[idx]])
        elif self.p.judge_d_by_size and candidate_checkpoint is not None:
            d = float(self.p.judge_d_by_size[int(parse_checkpoint(candidate_checkpoint)[1])])
        else:
            d = max(0.0, self.p.judge_d - self.p.judge_coupling * b)
        key = "-".join(str(int(s)) for s in candidate_seeds)
        scores = [d * float(r) + float(normal(self.salt, "judge-z", judge_checkpoint, idx, key, j))
                  for j, r in enumerate(candidates_right)]
        return int(np.argmax(scores))

    def checks(self, table: pd.DataFrame, judge: Config, self_calls=(0, 1, 2),
               candidates: dict | None = None) -> tuple[pd.DataFrame, pd.DataFrame]:
        """(self-checks, judge picks) for a World.table, as the fake server would return them through
        sample.self_checks and sample.judge. candidates: system -> number of candidates the judge reads (default 4)."""
        seeds = {(sy, j): seed_of(sy, j) for sy in table["system"].unique() for j in range(int(table["call"].max()) + 1)}
        table = table.assign(seed=[seeds[(sy, int(j))] for sy, j in zip(table["system"], table["call"])])
        sc = table[table["call"].isin(self_calls)]
        idx = sc["item"].map(self.index).to_numpy()
        frames = []
        for system in sc["system"].unique():
            m = (sc["system"] == system).to_numpy()
            verdict = self.self_check(idx[m], Config.from_label(system).checkpoint,
                                      sc["signal_thinking_tokens"].to_numpy(dtype=float)[m],
                                      sc["seed"].to_numpy()[m], sc["correct"].to_numpy(dtype=float)[m])
            frames.append(sc.loc[m, ["system", "item", "call"]].assign(verdict=verdict))
        checks = pd.concat(frames, ignore_index=True)
        rows = []
        for (system, item), part in table.groupby(["system", "item"], sort=False):
            for n in sorted({4, (candidates or {}).get(system, 4)}):
                cand = part[part["call"] < n].sort_values("call")
                pick = self.judge_pick(self.index[item], judge.checkpoint, list(cand["correct"] == 1), list(cand["seed"]),
                                       Config.from_label(system).checkpoint)
                rows.append({"system": system, "item": item, "judge": judge.label, "candidates": n, "pick": pick})
        return checks, pd.DataFrame(rows)

    def visible_pass(self, idx, seed, right) -> np.ndarray:
        return (uniform(self.salt, "exec", idx, seed) < np.where(np.asarray(right, dtype=bool), 0.95, 0.3)).astype(int)
