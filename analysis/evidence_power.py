"""Step 0.10 of the evidence plan: power of each confirmatory test by simulation, before sealing.
Writes research/v3/evidence/power.md. $0: everything is simulated.

The panel model (plain words first). Each item has a latent difficulty for each source (Haiku, Luna,
Sonnet, Sol): four standard normal numbers z with a fixed correlation matrix (the "latent r" between
sources). A source's chance of answering the item right is Phi(a_s + b_s z_s); a_s and b_s are set so that
the source's accuracy p_s and repeat correlation rho_s match the inputs (for two calls of one source,
P(both right) is a bivariate normal probability). Each call is right with that chance, independently given
the chance. A wrong call gives the item's "attractor" wrong answer with probability 0.6, otherwise one of
three other wrong answers at random, so wrong answers can coincide, as on BBEH.

Inputs. Haiku: p 0.48, rho 0.48 (cached, finding 1). Sonnet: p 0.71 (cached), rho 0.50 (unmeasured; the
plan's second Sonnet call measures it). Luna and Sol are set equal to Haiku and Sonnet (price-matched).
Latent r: Haiku-Sonnet 0.15 (cached phi 0.08 / sqrt(0.48 x 0.50)); Luna-Sol the same; Haiku-Sol and
Luna-Sonnet 0.10; Haiku-Luna and Sonnet-Sol, the cross-vendor same-tier r that H1 is about, are the
scenario: 0.3, 0.6 (base) or 0.8.

Each simulated study runs the planned analysis on 300 BBEH items (or 100 fit + 200 sealed ForecastBench
questions), with 400 item-bootstrap draws for the one-sided p-value, and is repeated 300 times. Power is
the share of studies whose p-value clears the Holm threshold. Holm's threshold for a test lies between
alpha / m (the "Holm floor": the smallest p-value of a family of m tests) and alpha (the largest, all others
passed); both ends are reported, and the plan's 70% rule is applied at the floor in the base scenario. The family
size m was 6 in session E1's first pass, 4 in session E2's first pass and is 3 now (FAMILY; Phase 2: FAMILY_P2).

Usage: python -m analysis.evidence_power                 # writes research/v3/evidence/power.md (about 25 minutes)
       python -m analysis.evidence_power --sensitivity   # writes research/v3/evidence/power_sensitivity.md (audit 48)
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import brentq
from scipy.stats import multivariate_normal, norm

from autoagentnet.evidence import calibration as C
from autoagentnet.evidence import correlation as R
from autoagentnet.evidence import decisions as D
from autoagentnet.evidence.inference import p_above, tost_p

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "research/v3/evidence/power.md"
ALPHA = 0.05
FAMILY = 3  # Phase 1 Holm family after session E2's power re-run: H5, H6, H7 (accuracy leg); H4 exploratory (power 0.53)
FAMILY_P2 = 3  # Phase 2 Holm family: H11, H15, H16
H7_MARGIN = -0.08  # set by this step (plan: -0.06)
H5_INTERCEPT, H5_SLOPE = 0.6, (0.5, 1.5)  # set by this step (plan: 0.4 and 0.6-1.4)
REPS, DRAWS = 300, 400
SOURCES = ["haiku", "luna", "sonnet", "sol"]
P = {"haiku": 0.48, "luna": 0.48, "sonnet": 0.71, "sol": 0.71}
RHO = {"haiku": 0.48, "luna": 0.48, "sonnet": 0.50, "sol": 0.50}
CALLS = {"haiku": 5, "luna": 5, "sonnet": 1, "sol": 1}
USD = {"haiku": 0.00071, "luna": 0.0007, "sonnet": 0.0144, "sol": 0.019}


def chance_params(p: float, rho: float) -> tuple[float, float]:
    """(a, b) with E Phi(a + b z) = p and repeat correlation rho."""
    def rho_of(t):
        m = norm.ppf(p)
        both = multivariate_normal(mean=[0, 0], cov=[[1, t], [t, 1]]).cdf([m, m])
        return (both - p * p) / (p * (1 - p)) - rho
    t = brentq(rho_of, 1e-6, 1 - 1e-6)
    b = math.sqrt(t / (1 - t))
    return norm.ppf(p) * math.sqrt(1 + b * b), b


PARAMS = {s: chance_params(P[s], RHO[s]) for s in SOURCES}


def latent_corr(r_cross: float) -> np.ndarray:
    r = {("haiku", "luna"): r_cross, ("sonnet", "sol"): r_cross, ("haiku", "sonnet"): 0.15, ("luna", "sol"): 0.15,
         ("haiku", "sol"): 0.10, ("luna", "sonnet"): 0.10}
    M = np.eye(4)
    for (s, t), v in r.items():
        i, j = SOURCES.index(s), SOURCES.index(t)
        M[i, j] = M[j, i] = v
    return M


def simulate_panel(n: int, r_cross: float, rng, params: dict | None = None) -> dict:
    """Per source: grades (n x calls) and answers (0 = gold, 1 = attractor, 2-4 other wrong answers). `params`
    replaces a source's (a, b) to make it more or less accurate (sensitivity runs)."""
    z = rng.multivariate_normal(np.zeros(4), latent_corr(r_cross), size=n)
    params = {**PARAMS, **(params or {})}
    out = {}
    for k, s in enumerate(SOURCES):
        a, b = params[s]
        chance = norm.cdf(a + b * z[:, k])
        right = rng.random((n, CALLS[s])) < chance[:, None]
        wrong = np.where(rng.random((n, CALLS[s])) < 0.6, 1, rng.integers(2, 5, (n, CALLS[s])))
        out[s] = {"Z": right.astype(float), "A": np.where(right, 0, wrong)}
    return out


def plurality(A: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Per row: the plurality answer (ties to the answer met first in column order) and its count."""
    counts = np.stack([(A == v).sum(axis=1) for v in range(5)], axis=1)
    first = np.stack([np.where((A == v).any(axis=1), (A == v).argmax(axis=1), A.shape[1]) for v in range(5)], axis=1)
    best = np.lexsort((first, -counts))  # not per row; do it per row below
    del best
    top = counts.max(axis=1)
    cand = np.where(counts == top[:, None], first, 99)
    answer = cand.argmin(axis=1)
    return answer, top


def boot_p(stat, n, rng, threshold=0.0, draws=DRAWS) -> tuple[float, float, float]:
    """(estimate, one-sided p for "above threshold", 95% half-width) from an item bootstrap."""
    idx = rng.integers(0, n, (draws, n))
    d = np.array([stat(i) for i in idx])
    return float(stat(np.arange(n))), p_above(d, threshold), float((np.percentile(d, 97.5) - np.percentile(d, 2.5)) / 2)


def study_bbeh(n: int, r_cross: float, rng) -> dict:
    sim = simulate_panel(n, r_cross, rng)
    H, L, S, O = (sim[s] for s in SOURCES)
    res = {}
    # H1: within-vendor repeat association above cross-vendor (log error odds ratio), both differences
    d_h = lambda i: R.pair_stats(H["Z"][i]).log_error_or - R.pair_stats(H["Z"][i], L["Z"][i]).log_error_or
    d_l = lambda i: R.pair_stats(L["Z"][i]).log_error_or - R.pair_stats(H["Z"][i], L["Z"][i]).log_error_or
    _, p1, _ = boot_p(d_h, n, rng)
    _, p2, _ = boot_p(d_l, n, rng)
    res["H1"] = max(p1, p2)  # both must pass: the larger p-value decides
    rho_est, _, rho_half = boot_p(lambda i: R.rho_pairwise(H["Z"][i]), n, rng)
    res["rho_halfwidth"] = rho_half
    # panel answers in call order Haiku x5, Luna x5, Sonnet, Sol
    A = np.column_stack([H["A"], L["A"], S["A"], O["A"]])
    answer, top = plurality(A)
    y = (answer == 0).astype(float)
    share = top / A.shape[1]
    # old H4 (until session E2): the 12-call share overstates accuracy; kept as a reported number
    res["gap"], res["H4_old"], _ = boot_p(lambda i: share[i].mean() - y[i].mean(), n, rng)
    # H4 since session E2 (Kevin, B5): the gap of Haiku's 5-call share minus the gap of a mixed 5-call share
    # (Haiku 0-2 + Luna 0-1 and Haiku 0-1 + Luna 0-2, averaged); paired over items, above 0
    def share_right(cols):
        a, t = plurality(cols)
        return t / cols.shape[1], (a == 0).astype(float)
    sh, yh = share_right(H["A"])
    sl, yl = share_right(L["A"])
    s1, y1 = share_right(np.column_stack([H["A"][:, :3], L["A"][:, :2]]))
    s2, y2 = share_right(np.column_stack([H["A"][:, :2], L["A"][:, :3]]))
    h4 = lambda i: (sh[i] - yh[i]).mean() - 0.5 * ((s1[i] - y1[i]).mean() + (s2[i] - y2[i]).mean())
    res["H4_diff"], res["H4"], res["H4_halfwidth"] = boot_p(h4, n, rng)
    res["gap_haiku5"], res["gap_luna5"] = (sh - yh).mean(), (sl - yl).mean()
    res["gap_mixed5"] = 0.5 * ((s1 - y1).mean() + (s2 - y2).mean())
    # H6: whole-panel correction beats a Haiku-only one, two folds, Brier gain on fixed predictions
    agree = lambda X: (X == answer[:, None]).mean(axis=1)
    whole = np.column_stack([agree(H["A"]), agree(L["A"]), agree(S["A"]), agree(O["A"])])
    folds = C.two_folds(n, seed=int(rng.integers(1 << 30)))
    one = C.cross_fit(whole[:, :1], y, folds, l2=1e-3)
    four = C.cross_fit(whole, y, folds, l2=1e-3)
    gain, res["H6"], res["brier_gain_halfwidth"] = boot_p(
        lambda i: np.mean((one[i] - y[i]) ** 2) - np.mean((four[i] - y[i]) ** 2), n, rng)
    res["brier_gain"] = gain
    # H7: cascade 3 Haiku + 3 Luna, escalate to Sonnet unless at least 4 of 6 agree; non-inferior at -6 points
    cheap = np.column_stack([H["A"][:, :3], L["A"][:, :3]])
    c_answer, c_top = plurality(cheap)
    escalate = c_top < 4
    casc = np.where(escalate, S["Z"][:, 0], (c_answer == 0).astype(float))
    diff = casc - S["Z"][:, 0]
    est, res["H7"], res["cascade_halfwidth"] = boot_p(lambda i: diff[i].mean(), n, rng, threshold=H7_MARGIN)
    _, res["H7_plan_margin"], _ = boot_p(lambda i: diff[i].mean(), n, rng, threshold=-0.06)
    res["cascade_minus_sonnet"] = est
    res["cost_ratio"] = (3 * USD["haiku"] + 3 * USD["luna"] + escalate.mean() * USD["sonnet"]) / USD["sonnet"]
    res["escalation"] = escalate.mean()
    res["H7_both_legs"] = res["H7"] if res["cost_ratio"] <= 0.70 else 1.0  # audit 47: the cost leg must hold too
    return res


CACHED = None


def cached_features() -> pd.DataFrame:
    global CACHED
    if CACHED is None:
        from analysis.evidence_cached import item_table, load
        CACHED = item_table(load())
    return CACHED


def study_h5(n: int, shift: float, rng) -> dict:
    """H5: the frozen two-feature correction on n new items drawn like the cached ones; the truth is the
    frozen model with its intercept shifted by `shift` (0 = it transfers exactly). Equivalence: intercept
    within +-0.4 and slope within 0.6-1.4 of the calibration regression; both TOSTs must pass."""
    t = cached_features()
    beta = C.fit_correction(t[["share", "sonnet_agrees"]].to_numpy(), t["correct"].to_numpy())
    rows = t.iloc[rng.integers(0, len(t), n)]
    X = rows[["share", "sonnet_agrees"]].to_numpy()
    c = C.apply_correction(beta, X)
    truth = C.sigmoid(C.logit(c) + shift)
    y = (rng.random(n) < truth).astype(float)
    idx = rng.integers(0, n, (DRAWS, n))
    fits = np.array([C.intercept_slope(c[i], y[i]) for i in idx])
    p_int = tost_p(fits[:, 0], -H5_INTERCEPT, H5_INTERCEPT)
    p_slope = tost_p(fits[:, 1], *H5_SLOPE)
    plan = max(tost_p(fits[:, 0], -0.4, 0.4), tost_p(fits[:, 1], 0.6, 1.4))
    slope_90 = (np.percentile(fits[:, 1], 95) - np.percentile(fits[:, 1], 5)) / 2
    return {"H5": max(p_int, p_slope), "H5_plan_margin": plan, "slope_halfwidth_90": slope_90,
            "intercept_sd": float(fits[:, 0].std())}


def study_h8(lam: float, rng, n_fit: int = 100, n_sealed: int = 200) -> dict:
    """H8: each of 12 forecasts is lam x (truth log-odds + shared noise + own noise); a is fitted on the fit
    questions and the Brier gain of extremizing (a against 1) is measured on the sealed ones."""
    n = n_fit + n_sealed
    x = rng.normal(-0.6, 1.6, n)
    y = (rng.random(n) < C.sigmoid(x)).astype(float)
    shared = rng.normal(0, 0.8, n)
    F = C.sigmoid(lam * (x[:, None] + shared[:, None] + rng.normal(0, 0.6, (n, 12))))
    a = C.fit_extremizing(F[:n_fit], y[:n_fit])
    base, ext = C.extremize(F[n_fit:], 1.0), C.extremize(F[n_fit:], a)
    ys = y[n_fit:]
    _, p, half = boot_p(lambda i: np.mean((base[i] - ys[i]) ** 2) - np.mean((ext[i] - ys[i]) ** 2), n_sealed, rng)
    return {"H8": p, "a": a}


# ---------------------------------------------------------------- Phase 2 (session E2, Kevin's B9)

USD_FORECAST = {"haiku": 0.00035, "luna": 0.0004}


def phase2_calls(n: int, r_cross: float, w_persona: float, rng) -> tuple[pd.DataFrame, dict]:
    """Calls shaped like calls.csv for H11's arms on n BBEH items and n ForecastBench questions.
    BBEH: Haiku's base and resample calls share Haiku's item chance; a persona call's latent difficulty correlates
    with Haiku's by w_persona (1 = the persona changes nothing); Luna's by r_cross; the reasoning arm is a Haiku
    call with latent correlation 0.9 at four times the price. ForecastBench: each call's log-odds is
    0.7 x (truth + the model's shared error + its own noise); Luna's shared error correlates with Haiku's by r_cross,
    the persona's by w_persona."""
    rows = []
    z = rng.standard_normal((n, 4))
    zh = z[:, 0]
    zl = r_cross * zh + np.sqrt(1 - r_cross ** 2) * z[:, 1]
    zp = w_persona * zh + np.sqrt(1 - w_persona ** 2) * z[:, 2]
    zr = 0.9 * zh + np.sqrt(1 - 0.81) * z[:, 3]
    a, b = PARAMS["haiku"]
    chance = {k: norm.cdf(a + b * v) for k, v in (("h", zh), ("l", zl), ("p", zp), ("r", zr))}

    def add(item, source, prompt, call, usd, correct=None, prob=None, outcome=None):
        rows.append({"item": item, "source": f"{source}:{prompt}", "prompt": prompt, "call": call, "parsed": True,
                     "correct": correct, "prob": prob, "outcome": outcome, "cost_usd": usd, "answer": "x"})

    for i in range(n):
        item = f"b{i}"
        for c in range(2):
            add(item, "haiku_nothink", "base", c, USD["haiku"], correct=float(rng.random() < chance["h"][i]))
        add(item, "luna_none", "base", 0, USD["luna"], correct=float(rng.random() < chance["l"][i]))
        add(item, "haiku", "base", 0, 4 * USD["haiku"], correct=float(rng.random() < chance["r"][i]))
        for persona in ("careful", "contrarian", "quick"):
            add(item, "haiku_nothink", persona, 0, USD["haiku"], correct=float(rng.random() < chance["p"][i]))
    x = rng.normal(-0.6, 1.6, n)
    y = (rng.random(n) < C.sigmoid(x)).astype(float)
    e = rng.normal(0, 0.8, (n, 4))
    sh = e[:, 0]
    sl = r_cross * sh + np.sqrt(1 - r_cross ** 2) * e[:, 1]
    sp = w_persona * sh + np.sqrt(1 - w_persona ** 2) * e[:, 2]
    sr = 0.9 * sh + np.sqrt(1 - 0.81) * e[:, 3]
    f = lambda shared: float(C.sigmoid(0.7 * (x[i] + shared + rng.normal(0, 0.4))))
    for i in range(n):
        item = f"q{i}"
        for c in range(2):
            add(item, "haiku_nothink", "base", c, USD_FORECAST["haiku"], prob=f(sh[i]), outcome=y[i])
        add(item, "luna_none", "base", 0, USD_FORECAST["luna"], prob=f(sl[i]), outcome=y[i])
        add(item, "haiku", "base", 0, 4 * USD_FORECAST["haiku"], prob=f(sr[i]), outcome=y[i])
        for persona in ("careful", "contrarian", "quick"):
            add(item, "haiku_nothink", persona, 0, USD_FORECAST["haiku"], prob=f(sp[i]), outcome=y[i])
    return pd.DataFrame(rows), {"bbeh": [f"b{i}" for i in range(n)], "forecast": [f"q{i}" for i in range(n)]}


def study_h11(r_cross: float, w_persona: float, rng, n: int = 200) -> dict:
    """H11 through the committed analysis code (analysis/evidence_phase2.independence)."""
    from analysis import evidence_phase2 as P2

    P2.N_BOOT, P2.SEED = DRAWS, int(rng.integers(1 << 30))
    calls, items = phase2_calls(n, r_cross, w_persona, rng)
    out = P2.independence(calls, items)
    return {"H11": out["p"], "H11_estimate": out["point"]["H11"]}


def study_h15(r_cross: float, rng, n: int = 300, lam: float = 3.0, p_luna: float | None = None) -> dict:
    """H15 through the committed analysis code (analysis/evidence_phase2.cheap_policy) on a simulated panel. p_luna
    makes Luna more or less accurate than Haiku, so the two agreeing shares carry different information."""
    from analysis import evidence_phase2 as P2

    P2.N_BOOT, P2.SEED = DRAWS, int(rng.integers(1 << 30))
    params = {"luna": chance_params(p_luna, RHO["luna"])} if p_luna is not None else None
    sim = simulate_panel(n, r_cross, rng, params)
    H, L, S = sim["haiku"], sim["luna"], sim["sonnet"]
    cheap = np.column_stack([H["A"][:, :3], L["A"][:, :3]])
    answer, top = plurality(cheap)
    t6 = pd.DataFrame({"item": range(n), "task": [k % 4 for k in range(n)], "cheap_right": (answer == 0).astype(float),
                       "share6": top / 6, "h_share6": (H["A"][:, :3] == answer[:, None]).mean(axis=1),
                       "l_share6": (L["A"][:, :3] == answer[:, None]).mean(axis=1),
                       "cheap_usd": 3 * USD["haiku"] + 3 * USD["luna"], "sonnet_usd": USD["sonnet"],
                       "sonnet_right": S["Z"][:, 0]})
    out = P2.cheap_policy(t6, lam)
    # information for Kevin, not preregistered: the same comparison with the decision-theory threshold (answer with the
    # cheap panel iff confidence >= lam / (1 + lam), else abstain), where calibration, not only ranking, matters
    y = t6["cheap_right"].to_numpy()
    folds = C.two_folds(n, seed=int(rng.integers(1 << 30)))
    corrected = C.cross_fit(t6[["h_share6", "l_share6"]].to_numpy(), y, folds, l2=1e-3)
    net = lambda c: np.where(c >= lam / (1 + lam), np.where(y == 1, 0.10, -lam * 0.10), 0.0) - t6["cheap_usd"].to_numpy()
    d = net(corrected) - net(t6["share6"].to_numpy())
    est, p_alt, _ = boot_p(lambda i: d[i].mean(), n, rng)
    return {"H15": out["p"], "H15_diff": out["diff"], "H15_alt": p_alt, "H15_alt_diff": est}


def study_h16(anchor: float, lam: float, rng, n_fit: int = 50, n_eval: int = 343) -> dict:
    """H16: half-Kelly against the freeze price on n_eval sealed market questions, the correction fitted on n_fit.
    Truth log-odds x; market price q = sigmoid(x + noise sd 0.7); each of 12 forecasts has log-odds
    anchor x logit(q) + (1 - anchor) x lam x (x + shared error + own noise). Naive = the mean of the 12
    probabilities; corrected = a logistic recalibration of their mean log-odds fitted on the fit questions."""
    n = n_fit + n_eval
    x = rng.normal(-0.6, 1.6, n)
    y = (rng.random(n) < C.sigmoid(x)).astype(float)
    q = np.clip(C.sigmoid(x + rng.normal(0, 0.7, n)), 0.01, 0.99)
    shared = rng.normal(0, 0.8, n)
    logits = anchor * C.logit(q)[:, None] + (1 - anchor) * lam * (x[:, None] + shared[:, None] + rng.normal(0, 0.5, (n, 12)))
    probs = C.sigmoid(logits)
    naive = probs.mean(axis=1)
    beta = C.fit_correction(C.logit(probs[:n_fit]).mean(axis=1), y[:n_fit], l2=1e-3)
    corrected = C.apply_correction(beta, C.logit(probs[n_fit:]).mean(axis=1))
    d = D.kelly_log_growth(corrected, q[n_fit:], y[n_fit:]) - D.kelly_log_growth(naive[n_fit:], q[n_fit:], y[n_fit:])
    est, p, half = boot_p(lambda i: d[i].mean(), n_eval, rng)
    return {"H16": p, "H16_diff": est}


def study_h16_crossfit(anchor: float, lam: float, rng, n: int = 393) -> dict:
    """H16's best case (audit 48): the recalibration cross-fitted in two folds over all n market questions instead of
    fitted on 50, so every question is scored; the forecast model is study_h16's."""
    x = rng.normal(-0.6, 1.6, n)
    y = (rng.random(n) < C.sigmoid(x)).astype(float)
    q = np.clip(C.sigmoid(x + rng.normal(0, 0.7, n)), 0.01, 0.99)
    shared = rng.normal(0, 0.8, n)
    logits = anchor * C.logit(q)[:, None] + (1 - anchor) * lam * (x[:, None] + shared[:, None] + rng.normal(0, 0.5, (n, 12)))
    probs = C.sigmoid(logits)
    folds = C.two_folds(n, seed=int(rng.integers(1 << 30)))
    corrected = C.cross_fit(C.logit(probs).mean(axis=1), y, folds, l2=1e-3)
    d = D.kelly_log_growth(corrected, q, y) - D.kelly_log_growth(probs.mean(axis=1), q, y)
    est, p, _ = boot_p(lambda i: d[i].mean(), n, rng)
    return {"H16": p, "H16_diff": est}


def sensitivity(reps: int = 150) -> pd.DataFrame:
    """Audit 48, items 2-3: how H11, H15 and H16's power moves with the assumptions their demotion rests on."""
    rng = np.random.default_rng(1)
    rows = []

    def add(test, scenario, n, ps, detail):
        rows.append({"test": test, "scenario": scenario, "n": n, "power_floor": power(ps, ALPHA / FAMILY_P2),
                     "power_alpha": power(ps, ALPHA), "detail": detail})

    for w in (0.85, 0.9, 0.95, 1.0):
        sims = pd.DataFrame([study_h11(0.6, w, rng) for _ in range(reps)])
        add("H11", f"cross-vendor r 0.6, persona r {w}", "200 + 200", sims["H11"],
            f"vendor minus prompt gain per dollar {sims['H11_estimate'].mean():+.0f}")
    for p_luna in (0.48, 0.58, 0.65):
        sims = pd.DataFrame([study_h15(0.6, rng, p_luna=p_luna) for _ in range(reps)])
        add("H15 (lambda 3)", f"cross-vendor r 0.6, Haiku accuracy 0.48, Luna {p_luna}", 300, sims["H15"],
            f"corrected minus naive {sims['H15_diff'].mean():+.4f} $/item")
    for anchor, lam in ((0.0, 1.5), (0.0, 2.0), (0.3, 1.5), (0.5, 0.6)):
        sims = pd.DataFrame([study_h16_crossfit(anchor, lam, rng) for _ in range(reps)])
        add("H16, two-fold cross-fit on all 393", f"anchor on price {anchor}, own signal x{lam}", 393, sims["H16"],
            f"corrected minus naive log growth {sims['H16_diff'].mean():+.4f}")
    table = pd.DataFrame(rows)
    lines = ["# Evidence plan: power sensitivity of the Phase 2 demotions (audit 48)", "",
             f"Written by `python -m analysis.evidence_power --sensitivity` ({reps} simulated studies per row, {DRAWS} "
             f"bootstrap draws each, seed 1). Holm floor alpha / {FAMILY_P2} = {ALPHA / FAMILY_P2:.4f}. The models are those "
             "of power.md; only the named assumption moves.", "",
             "- **H11** clears 0.70 only if a persona call is almost as correlated with the base call as a resample "
             "(persona latent r at or above about 0.95); the base scenario's 0.85 is an assumption, not a measurement.",
             "- **H15** depends on the two vendors differing: when Haiku and Luna are equally accurate, their agreeing shares "
             "rank items as the plain 6-call share does and the test has no effect to find; a more accurate Luna gives the "
             "correction something to rank by.",
             "- **H16** with its best design (cross-fitting over all 393 questions) and a panel that ignores the price and is "
             "overconfident.", "",
             "| test | scenario | items | power at Holm floor | power at alpha | detail |", "|---|---|---|---|---|---|",
             *[f"| {r.test} | {r.scenario} | {r.n} | {r.power_floor:.2f} | {r.power_alpha:.2f} | {r.detail} |"
               for r in table.itertuples()], ""]
    (ROOT / "research/v3/evidence/power_sensitivity.md").write_text("\n".join(lines))
    print("\n".join(lines))
    return table


def power(ps, level) -> float:
    return float(np.mean(np.asarray(ps) <= level))


def main(reps: int = REPS) -> pd.DataFrame:
    rng = np.random.default_rng(0)
    rows = []

    def add(test, scenario, n, ps, detail, family=FAMILY):
        rows.append({"test": test, "scenario": scenario, "n": n, "power_floor": power(ps, ALPHA / family),
                     "power_alpha": power(ps, ALPHA), "family": family, "detail": detail})

    for r_cross in (0.3, 0.6, 0.8):
        sims = pd.DataFrame([study_bbeh(300, r_cross, rng) for _ in range(reps)])
        sc = f"cross-vendor latent r {r_cross}"
        add("H4 (E2: Haiku 5 gap minus mixed 5 gap)", sc, 300, sims["H4"],
            f"difference {100 * sims['H4_diff'].mean():+.1f} pts (half-width {100 * sims['H4_halfwidth'].mean():.1f}); gaps: "
            f"Haiku5 {100 * sims['gap_haiku5'].mean():+.1f}, Luna5 {100 * sims['gap_luna5'].mean():+.1f}, mixed5 "
            f"{100 * sims['gap_mixed5'].mean():+.1f}, 12-call {100 * sims['gap'].mean():+.1f}")
        add("H6", sc, 300, sims["H6"], f"Brier gain {sims['brier_gain'].mean():+.3f}, half-width {sims['brier_gain_halfwidth'].mean():.3f}")
        add("H7 (accuracy leg, -8 pts)", sc, 300, sims["H7"],
            f"cascade - Sonnet {100 * sims['cascade_minus_sonnet'].mean():+.1f} pts, half-width {100 * sims['cascade_halfwidth'].mean():.1f}; "
            f"cost ratio {sims['cost_ratio'].mean():.2f} (reported, not tested since E2); escalation {sims['escalation'].mean():.2f}")
        add("H1 (sanity check, outside Holm)", sc, 300, sims["H1"], f"rho 95% half-width {sims['rho_halfwidth'].mean():.3f}")
        add("old H4: 12-call gap > 0 (replaced)", sc, 300, sims["H4_old"], f"12-call gap {100 * sims['gap'].mean():+.1f} pts")
        add("H7 with the 70% cost leg (dropped)", sc, 300, sims["H7_both_legs"], "for the record")
    for shift in (0.0, 0.2):
        sims = pd.DataFrame([study_h5(300, shift, rng) for _ in range(reps)])
        add("H5 (+-0.6, 0.5-1.5)", f"intercept shift {shift}", 300, sims["H5"],
            f"slope 90% half-width {sims['slope_halfwidth_90'].mean():.2f}, intercept sd {sims['intercept_sd'].mean():.2f}")
        add("H5 at the plan's bounds (reported)", f"intercept shift {shift}", 300, sims["H5_plan_margin"], "+-0.4 and 0.6-1.4")
    for lam in (0.6, 0.8):
        sims = pd.DataFrame([study_h8(lam, rng) for _ in range(reps)])
        add("H8 (exploratory)", f"forecasts shrunk x{lam}", 200, sims["H8"], f"fitted a {sims['a'].mean():.2f}")
    reps2 = max(reps // 2, 50)
    for r_cross, w in ((0.6, 0.85), (0.6, 1.0), (0.8, 0.85), (0.3, 0.7)):
        sims = pd.DataFrame([study_h11(r_cross, w, rng) for _ in range(reps2)])
        add("H11", f"cross-vendor r {r_cross}, persona r {w}", "200 + 200", sims["H11"],
            f"vendor minus prompt gain per dollar {sims['H11_estimate'].mean():+.0f}", family=FAMILY_P2)
    for r_cross in (0.3, 0.6, 0.8):
        sims = pd.DataFrame([study_h15(r_cross, rng) for _ in range(reps2)])
        add("H15 (lambda 3)", f"cross-vendor latent r {r_cross}", 300, sims["H15"],
            f"corrected minus naive {sims['H15_diff'].mean():+.4f} $/item", family=FAMILY_P2)
        add("H15 variant: threshold lambda/(1+lambda), not cross-fitted (information only)", f"cross-vendor latent r {r_cross}",
            300, sims["H15_alt"], f"corrected minus naive {sims['H15_alt_diff'].mean():+.4f} $/item", family=FAMILY_P2)
    for anchor, lam in ((0.5, 0.6), (0.3, 0.6), (0.5, 1.0), (0.3, 1.3)):
        sims = pd.DataFrame([study_h16(anchor, lam, rng) for _ in range(reps)])
        add("H16 (50 fit, 343 scored)", f"anchor on price {anchor}, own signal x{lam}", 343, sims["H16"],
            f"corrected minus naive log growth {sims['H16_diff'].mean():+.4f}", family=FAMILY_P2)
    table = pd.DataFrame(rows)
    write(table, reps)
    print(table.drop(columns="detail").to_string(index=False))
    return table


E2_DECISIONS = """## Session E2: Kevin's decisions and the re-run (before any paid call)

Kevin's decisions (session E2): H5 keeps the widened bounds; H8 exploratory; H7 = accuracy non-inferiority of the 4-of-6
cascade at -8 points, its cost ratio reported, not tested; H1 a sanity check outside Holm; H4 replaced by the paired gap
test (Haiku 5-call share minus a mixed 5-call share), confirmatory only if its power is at least 0.70 at the Holm level;
Phase 1 family H4, H5, H6, H7. The Phase 2 tests H11, H15 and H16 (H16 on all 393 market questions: 50 fit, 343 scored)
move to exploratory if under 0.70.

**First pass, family of 4 (Holm floor alpha / 4 = 0.0125), 300 studies per row** (cross-vendor latent r 0.3 / 0.6 / 0.8):
- **H4 (new):** 0.90 / **0.53** / 0.17. The mixed 5-call share is less overconfident than Haiku's: simulated
  gaps at r 0.6 are Haiku 5 +15.2 points and mixed 5 +10.2, a difference of +5.0 with a 95% half-width of 4.2 (+8.3 at
  r 0.3, +2.4 at r 0.8). **Under 0.70 in the base scenario: H4 moves to exploratory** (it is reported with its
  interval). The old 12-call H4 had power about 0.
- **H5:** 0.83 under exact transfer (0.58 if the intercept is off by 0.2); at the plan's bounds 0.23. Confirmatory.
- **H6:** 1.00 in every scenario. Confirmatory.
- **H7 (accuracy leg, -8 points):** 0.80 / **0.68** / 0.60. Kevin made H7 confirmatory (B3); it stays so. With the cost
  leg it would have been 0.00 / 0.06 / 0.28.
- **H1** (sanity check): at least 0.97 in every scenario.

**Phase 2, family of 3 (alpha / 3 = 0.0167):**
- **H11** (vendor minus prompt gain per dollar, 200 BBEH + 200 ForecastBench; 150 studies per row): **0.45** when Luna's
  latent correlation with Haiku is 0.6 and a persona's 0.85; 0.85 if personas change nothing (0.6 / 1.0); 0.68 at 0.3 /
  0.7; 0.05 at 0.8 / 0.85. Under 0.70 in the base scenario: **exploratory**.
- **H15** (answer-escalate-abstain, corrected minus naive, lambda 3): 0.00-0.01. With thresholds chosen by
  cross-fitting, any monotone recalibration of the same score gives the same policy, so H15 can only detect a better
  *ranking* of items; the Haiku and Luna agreeing shares rank items almost as the plain 6-call share does. A variant with
  the decision-theory threshold (answer iff confidence >= lambda / (1 + lambda)) is not better powered here (0.01-0.03).
  In the model the corrected policy even earns less (about -$0.005 per item): fitting the correction on half of 300
  items adds noise and no ranking. **Exploratory.**
- **H16** (half-Kelly, corrected minus naive, 343 scored): 0.01-0.03 in every scenario, and the corrected bankroll grows
  less on average (-0.002 to -0.007 log growth per question): a recalibration fitted on 50 market questions is too noisy
  to beat the plain mean when the forecasts lean on the price. **Exploratory.**
- So **Phase 2 has no confirmatory test**; H11, H15 and H16 are reported with intervals. Kevin is told.
- How these demotions move with their assumptions (audit 48: H11 with the persona correlation, H15 with unequal
  vendors, H16 with a cross-fitted fit on all 393 questions) is in research/v3/evidence/power_sensitivity.md.

**Final families:** Phase 1 = H5, H6, H7 (Holm over 3; the table below uses alpha / 3 = 0.0167); Phase 2 = none.
In the final table (alpha / 3): H5 0.84 under exact transfer; H6 1.00; H7 (accuracy leg) 0.71 in the base scenario,
0.81 at latent r 0.3 and 0.63 at 0.8; H4 would be 0.56 even at alpha / 3, so it stays exploratory.
"""


DECISIONS = """## Session E1, the first pass: what this step changed before sealing (the plan's rule: under 70% power, change counts or margins)

A first pass with the plan's settings (6 tests in the Phase 1 family, alpha / 6 = 0.0083; the table below re-runs
the plan's margins beside the new ones):
- **H1, H6:** power at least 0.96 in every scenario. Unchanged.
- **H7** (cascade non-inferior to Sonnet at -6 points): power 0.24-0.48. The cascade minus Sonnet interval at 300
  items is about +-5 points (the plan's target, +-5.5, holds), but a margin of 6 sits too close to it. **Margin set to
  -8 points**: in the final table (alpha / 5) power is 0.70 in the base scenario, 0.82 at latent r 0.3 and 0.57 at
  0.8 (an exploratory pass at -10 points gave 0.79-0.92).
  The 70% cost condition is unchanged.
- **H5** (frozen correction transfers; TOST intercept +-0.4, slope 0.6-1.4): power 0.14 even when the correction
  transfers exactly. The intercept's bootstrap sd at 300 items is about 0.15 log-odds, so +-0.4 cannot be shown at
  alpha / 6. **Bounds set to intercept +-0.6 and slope 0.5-1.5**: power 0.81 under exact transfer and 0.54 if the true
  intercept is off by 0.2 (final table, alpha / 5).
- **H8** (extremizing lowers Brier on 200 sealed questions): power 0.003-0.11 for forecasts shrunk by 0.5-0.8, and
  still 0.02-0.15 with 600 cross-fitted questions. A Brier gain from an extremizing factor near 1.2 is too small to
  detect at any count this budget allows. **H8 moves to exploratory** (reported with its interval), so the Phase 1
  Holm family is H1, H4, H5, H6, H7 (alpha / 5 = 0.01). This is outside the rule's "counts or margins", so Kevin
  confirms it at G0.
- **H4** (the 12-call panel's naive share overstates accuracy): power near 0, because in the model, calibrated to
  reproduce Haiku's cached +14-point gap from five calls, the mixed 12-call panel's share is overconfident by only
  -6 to +1.5 points. More items cannot fix a near-zero effect. H4 stays confirmatory as preregistered; the
  simulation predicts it fails, which would itself be a finding (vendor mixing removes the "k of n" overconfidence).
  A failing H4 still takes one Holm slot: the smallest p-value is tested at alpha / 5 rather than alpha / 4 (audit 47).
- **H7's cost leg** (audit 47): the rows above test accuracy only. With the plan's per-call estimates the six cheap
  calls cost 0.29 of a Sonnet call, so the cost ratio is 0.29 + the escalation rate, and the simulated escalation rate
  (fewer than 4 of 6 agreeing) is above 0.41 in every scenario: H7 as preregistered is predicted to fail on cost (row
  "H7_both_legs"). The probe's measured costs (step 1.1) and the real agreement rate decide it; options for Kevin
  before step 1.3: keep it (and report the likely failure), escalate unless 3 of 6 agree, or raise the cost bound.
- **H1** (audit 47) compares a model's repeat calls with another model, so it measures "same model" more than "same
  vendor"; its power is near 1 in every scenario. H2 (latent r, same-vendor cross-tier vs cross-vendor same-tier)
  is the informative vendor comparison. Unchanged pending Kevin.

Precision targets at 300 items: rho 95% half-width about 0.06 (target +-0.06); calibration slope 90% half-width
about 0.19 (target +-0.25); cascade minus Sonnet about +-5 points (target +-5.5); Brier gain about +-0.026 (target
+-0.02, missed slightly). The model's inputs for Luna, Sol and Sonnet's repeat correlation are assumptions until
Phase 1 measures them.
"""


def write(table: pd.DataFrame, reps: int) -> None:
    lines = ["# Evidence plan, step 0.10: power by simulation", "", E2_DECISIONS, "",
             f"Written by `python -m analysis.evidence_power` ({reps} simulated studies per Phase 1 row and per H16 row, "
             f"{max(reps // 2, 50)} per H11 and H15 row; {DRAWS} bootstrap draws each, seed 0). The model, its inputs and "
             "the Holm range are in the script's docstring. \"Holm floor\" is alpha / (family size): the threshold a test "
             f"meets if it has the smallest p-value of its family (Phase 1: {FAMILY} tests, {ALPHA / FAMILY:.4f}; Phase 2: "
             f"{FAMILY_P2}, {ALPHA / FAMILY_P2:.4f}), which is where the plan's 70% rule is applied. \"alpha\" is the most "
             "lenient Holm step.", "",
             "| test | scenario | items | power at Holm floor | power at alpha | detail |", "|---|---|---|---|---|---|",
             *[f"| {r.test} | {r.scenario} | {r.n} | {r.power_floor:.2f} | {r.power_alpha:.2f} | {r.detail} |"
               for r in table.itertuples()], "", DECISIONS]
    OUT.write_text("\n".join(lines))


if __name__ == "__main__":
    import sys

    sensitivity() if "--sensitivity" in sys.argv else main()
