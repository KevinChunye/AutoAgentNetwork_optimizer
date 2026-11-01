"""Write the evidence plan's panel configs (step 0.13) to configs/experiments/evidence/.

    python scripts/make_evidence_configs.py

One config per (step, task kind, vendor): runs are split by vendor. Each config covers its whole item
list; a paid run takes a slice with --task-offset/--task-limit so its worst case stays under $3.48 (the $4
run cap / 1.15). Every config carries its prereg block; the hypotheses are numbered as in the plan, with
the margins step 0.10 set (research/v3/evidence/power.md). The expected dollars per call (the stop rule
"over 1.5x the probe") are the plan's estimates until step 1.1 measures them; G1 rewrites them, committed
before the run.
"""

from __future__ import annotations

import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from analysis.pruning_cascade import STATUS as STATUS3  # noqa: E402  (one place for the Phase 3C test status)
OUT = ROOT / "configs/experiments/evidence"
DATA = "data/external/evidence"
SEALED = "research/v3/evidence/sealed"

# dollars per call, by ref and task kind: the mean of the step 1.1 probe's 10 calls per ref (e11_probe_*, session
# E4, 2026-10-22; Opus and Astra one call each). Math keeps the plan's estimates: its probe was not run (K6).
EST = {
    "haiku_nothink": {"bbeh": 0.00080, "forecast": 0.00018, "math": 0.0013},
    "luna_none": {"bbeh": 0.00017, "forecast": 0.000079, "math": 0.0013},
    "sonnet_nothink": {"bbeh": 0.0136, "forecast": 0.0040, "math": 0.026},
    "sol61_low": {"bbeh": 0.0062, "forecast": 0.0021, "math": 0.041},
    "opus_nothink": {"bbeh": 0.0228},
    "astra_low": {"bbeh": 0.0201},
}
# persona prompts write longer replies than the base prompt; a ref's guard uses the dearest persona's measured cost
# when persona calls run: Haiku from e22_persona_bbeh_anth (careful, 200 items) and e22_persona_forecast_anth (careful,
# first 50 questions; it stopped on the base-prompt guard); Luna scaled by Haiku's persona-to-base ratio (unmeasured).
PERSONA_EST = {"haiku_nothink": {"bbeh": 0.00084, "forecast": 0.00028},
               "luna_none": {"bbeh": 0.00018, "forecast": 0.00012}}
PERSONAS = ("careful", "contrarian", "quick")
SMALL = {"anthropic": "haiku_nothink", "openai": "luna_none"}
MID = {"anthropic": "sonnet_nothink", "openai": "sol61_low"}
ITEMS = {"bbeh": f"{SEALED}/bbeh_sealed.txt", "forecast": f"{SEALED}/forecast_all.txt", "math": f"{SEALED}/math_all.txt"}
SECOND = {"bbeh": f"{SEALED}/bbeh_second_call.txt", "forecast": f"{SEALED}/forecast_second_call.txt",
          "math": f"{SEALED}/math_second_call.txt"}
PHASE2 = {"bbeh": f"{SEALED}/bbeh_phase2.txt", "forecast": f"{SEALED}/forecast_sealed.txt"}
OPUS = {"bbeh": f"{SEALED}/bbeh_opus.txt", "forecast": f"{SEALED}/forecast_opus.txt"}
TOKENS = {"bbeh": 4000, "forecast": 1500, "math": 12000}


def tokens(ref: str, kind: str) -> int:
    if ref == "sol61_low":
        return 16000 if kind == "math" else 8000
    if ref in ("haiku", "luna_med"):
        return 12000 if kind == "math" else 8000
    return TOKENS[kind]


def source(ref, kind, calls=1, **extra) -> dict:
    return {"ref": ref, "calls": calls, "max_tokens": tokens(ref, kind), **extra}


def config(name, kind, items, sources, prereg, expect=None, **extra) -> dict:
    refs = sorted({s["ref"] for s in sources})  # sorted: the same file on every regeneration
    usd = {r: EST[r][kind] for r in refs if kind in EST.get(r, {})}
    for r in {s["ref"] for s in sources if s.get("prompt") in PERSONAS} & set(usd):
        usd[r] = max(usd[r], PERSONA_EST[r][kind])  # audit 57: persona replies cost more than base-prompt ones
    return {"kind": "panel", "name": name, "task_kind": kind,
            "tasks": f"{DATA}/{'math_probe' if items.endswith('probe_math.txt') else kind}.jsonl", "items": items,
            "sources": sources, "max_usd": 4.0, "chunk_size": 25, "max_concurrency": 8,
            "expect": {"min_calls": 20, "max_unparsed_rate": 0.05, "max_truncation_rate": 0.05, "usd_per_call": usd,
                       "max_cost_ratio": 1.5, **(expect or {})},
            "prereg": prereg, **extra}


# Kevin's decisions of session E2 (research/log.md): which tests are confirmatory after the power re-run (power.md)
STATUS = {"H4": "expl", "H11": "expl", "H15": "expl", "H16": "expl"}  # power re-run: all under 0.70 in the base scenario
P1_FAMILY = [h for h in ("H4", "H5", "H6", "H7") if STATUS.get(h, "conf") == "conf"]
P2_FAMILY = [h for h in ("H11", "H15", "H16") if STATUS[h] == "conf"]


def tag(h: str) -> str:
    return "conf" if STATUS.get(h, "conf") == "conf" else "expl since session E2's power re-run"


PANEL = ("The Phase 1 panel per item: haiku_nothink x5 and luna_none x5 (thinking and reasoning off, equal list price), "
         "sonnet_nothink x1 and sol61_low x1 (equal list price; Sol at its lowest setting, low), each mid-size model with a "
         "second call on 100 sealed items used only for its own repeat correlation.")
HOLM = (f"Confirmatory tests use one-sided item (or question) bootstrap p-values, 2,000 draws, with Holm at 5% within the "
        f"Phase 1 family {', '.join(P1_FAMILY)} (Kevin's decision B6, then session E2's power re-run moved H4 to exploratory). Margins: H5 intercept +-0.6 log-odds and slope 0.5-1.5 "
        "(also reported at the plan's +-0.4 / 0.6-1.4); H7 non-inferiority at -8 points, accuracy only. H8 is exploratory. "
        "The BBEH block (G2a) and the ForecastBench block (G2b) are each read once, by analysis/evidence_phase1.py --block.")
STOP = ("Stop and audit if a source parses under 95% or truncates over 5% of its live calls (after 20), costs over 1.5x "
        "the probe per call, the governor projects a vendor past its cap, or (ForecastBench) over 10% of market "
        "questions lack the freeze price.")


def prereg_probe(vendor) -> dict:
    return {
        "question": (f"Step 1.1 probe ({vendor}): what does each model ref cost per call, how often does it parse and "
                     "truncate, and does thinking-off math reach the floor? 10 BBEH, 10 ForecastBench and 10 MathArena "
                     "June 2026 items, all outside the sealed lists; one call per ref; the small model also answers math "
                     "with thinking on; one flagship call finds or tests its setting."),
        "prediction": ("Costs per call within 1.5x the plan's estimates (BBEH / ForecastBench / math: Haiku 0.00071 / "
                       "0.00035 / 0.0013; Luna 0.0007 / 0.0004 / 0.0013; Sonnet 0.0144 / 0.0075 / 0.026; Sol 0.019 / "
                       "0.010 / 0.041); parse rate at least 95% and truncation at most 2% for every ref; thinking-off "
                       "math scores 2-4 of 10."),
        "kill": ("Gate G1: a ref costing over 1.5x its estimate, parsing under 95% or truncating over 2% is fixed and "
                 "re-probed before 1.3. Opus or Astra rejecting its setting: fix the ref, re-probe that one call."),
        "decision": ("The probe reads cost, parse rate and truncation only; it never reads a forecast outcome (5 of its "
                     "ForecastBench questions are sealed market questions since session E2). "
                     "Math floor rule: if thinking-off Haiku and Luna both score under 2 of 10, step 2.5 runs every panel "
                     "member with thinking on, at fewer calls within its budget. Re-run aan estimate with the probe's "
                     "costs; a vendor projecting past $27 applies its drop order (research/v3/evidence/budget.md) before "
                     "1.3. The measured costs replace usd_per_call in every later config, committed before its run."),
    }


def prereg_bbeh(vendor) -> dict:
    return {
        "question": (f"Step 1.3 ({vendor} half of the panel): how correlated are a price-matched two-vendor panel's errors "
                     "on 300 sealed BBEH items (75 per task), and does a frozen confidence correction hold? " + PANEL),
        "prediction": (
            f"H4 ({tag('H4')}; Kevin, session E2): the calibration gap of Haiku's 5-call plurality share minus the gap of a "
            "mixed 5-call share (Haiku calls 0-2 + Luna 0-1, and Haiku 0-1 + Luna 0-2, averaged) is above 0, paired over "
            "items; Luna's 5-call and the 12-call gaps reported. H5 (conf): the two-feature correction frozen from the 80 "
            "cached items (research/v3/evidence/cached.md: logit p = -3.5513 + 4.0495 share + 1.9921 Sonnet agrees, applied "
            "to the Haiku 5-call plurality) holds: TOST intercept within +-0.6 and slope within 0.5-1.5, task-stratified "
            "bootstrap; also reported at +-0.4 / 0.6-1.4; per-task gaps reported. H6 (conf): a two-fold cross-fitted "
            "correction of the 12-call plurality's correctness on the whole panel (shares of Haiku and of Luna agreeing "
            "with it; Sonnet agrees; Sol agrees) beats one on the Haiku share alone, Brier gain > 0. H7 (conf, accuracy "
            "leg only since session E2): the cascade 3 Haiku + 3 Luna (calls 0-2), escalating to Sonnet unless at least 4 "
            "of 6 agree with their plurality, is non-inferior to Sonnet alone at -8 points; its cost ratio is reported "
            "with a 95% interval beside the cached Haiku-only cascade (0.52), not tested. Exploratory: the frontier of "
            "accuracy vs cost for k = 3, 4, 5 of 6, Haiku-only and Luna-only 3-of-5 rules. H1 (sanity check, outside "
            "Holm): Haiku-Haiku and Luna-Luna log error odds ratios each exceed Haiku-Luna's. H2 (expl): latent r of "
            "same-vendor cross-tier pairs vs cross-vendor same-tier pairs. H3 (expl): n_eff of 5 Haiku + 5 Luna vs 10 "
            "Haiku. Phase 2 also reads these calls: " + H15 + " " + HOLM),
        "kill": STOP + " Any stop rule: stop, audit, report to Kevin.",
        "decision": ("At G2a: the vendor comparison is read from H2 and the pair table (H1 is a sanity check). H4 is "
                     "exploratory (power 0.53): an interval above 0 favours mixing vendors within the meter's cheap calls; "
                     "one that includes 0 is unresolved, and the correction carries the 'k of n' overconfidence. H5 fails "
                     "-> Phase 2 refits per task. H7 passes -> the cascade becomes the project baseline and the H13 panel, "
                     "with its measured cost ratio."),
    }


def prereg_forecast(vendor) -> dict:
    return {
        "question": (f"Step 1.4 ({vendor} half of the panel): how correlated are the panel's forecasts on 300 ForecastBench "
                     "questions (100 fit, 200 sealed; 150 market, 150 data-series), and does pooling help? Market questions "
                     "show the freeze price. " + PANEL),
        "prediction": ("All exploratory, read once in block G2b. H8: an extremizing factor a, fitted on the 100 fit questions "
                       "separately for market and data-series, lowers Brier on the 200 sealed (gain with its interval). H9: "
                       "panel vs market price vs both combined on the 100 sealed market questions (step 1.4b, which would "
                       "have added 243, was dropped by Kevin in session E3). H10 (rule): every interval is computed by question and by source x resolution week; the wider "
                       "is primary. Brier and log loss per source and per panel; market and data-series apart; every "
                       "correlation of forecast errors reported separately for market and data-series questions. Phase 2 "
                       "also reads these calls: " + H16),
        "kill": STOP,
        "decision": ("H8 and H9 shape the write-up and the design of later forecasting work (pool with an extremizing factor, "
                     "or with the market price). They do not change any Phase 2 analysis: H16's naive and corrected "
                     "probabilities are fixed in analysis/evidence_phase2.py (audit 48)."),
    }


def prereg_phase2(step, vendor, kind, what, predictions, decision) -> dict:
    return {"question": f"Step {step} ({vendor}, {kind}): {what}",
            "prediction": predictions + (
                (f" Phase 2 confirmatory family: {', '.join(P2_FAMILY)}, Holm at 5%." if P2_FAMILY else
                 " No Phase 2 test is confirmatory: H11, H15 and H16 moved to exploratory in session E2's power re-run "
                 "(research/v3/evidence/power.md, under 0.70 power in the base scenario); all are reported with intervals "
                 "and one-sided p-values.") + " The analysis runs in the next session (plan steps 2.6-2.10)."),
            "kill": STOP, "decision": decision}


H11 = (f"H11 ({tag('H11')}): another vendor buys more independence per dollar than a different prompt: the vendor arm's n_eff gain "
       "per dollar (adding Luna calls to Haiku, from Phase 1) minus the prompt arm's (adding Haiku persona calls) is above "
       "0, on the same items; reasoning and resampling arms reported, not ranked.")
# H15 and H16 are Phase 2 analyses of Phase 1's calls (audit 48: not of the persona calls)
H15 = (f"H15 ({tag('H15')}): at lambda 3, answer-escalate-abstain earns more net dollars per item with corrected than with "
       "naive confidence (cross-fitted thresholds), on these 300 items: the cheap system is the plurality of Haiku and Luna "
       "calls 0-2, escalation pays for Sonnet's call 0 (analysis/evidence_phase2.py).")
H16 = (f"H16 ({tag('H16')}): half-Kelly against the freeze price on the 100 sealed market questions grows "
       "the bankroll more with corrected (a logistic recalibration of the panel's mean log-odds fitted on the 50 fit market "
       "questions) than with naive panel probabilities (the mean of the 12).")


LOCKBOX = {"bbeh": f"{SEALED}/lockbox_bbeh.txt", "forecast": f"{SEALED}/lockbox_forecast.txt"}


def tag3(p: str) -> str:
    return "conf" if STATUS3[p] == "conf" else "expl, from the Phase 3C power simulation (research/v3/pruning/power_cascade.md)"


def n_items(path: str) -> int:
    return len([x for x in (ROOT / path).read_text().splitlines() if x])


def prereg_lockbox(vendor, kind) -> dict:
    """Phase 3C rebuilt around cascades (session E4, Kevin's K2-K4); full text in research/v3/pruning/prereg_cascade.md."""
    family = [p for p in ("C1", "C2") if STATUS3[p] == "conf"]
    n = n_items(LOCKBOX[kind])
    lockbox_panel = ("The lockbox panel per item (both vendors' configs together): haiku_nothink x5 and luna_none x5, "
                     "sonnet_nothink x1 and sol61_low x1, and haiku_nothink x3 and luna_none x3 under the persona prompts "
                     "careful, contrarian and quick: every first round and escalation model the cascade rule selects from.")
    frozen = ("The cascade policy (first round, threshold, escalation model) and the C2 pair are frozen in "
              "research/v3/pruning/selected.json by analysis/pruning_cascade.py (the rule in its docstring and in "
              "research/v3/pruning/selection_rule.md, committed before the G2a read) from the Phase 1-2 search items, and "
              "applied to these calls without refitting. Collected blind (K4): this run may happen before selected.json "
              "exists; its calls are read only by `python -m analysis.pruning_cascade lockbox`, which refuses until "
              "selected.json is committed unchanged; nothing but status.json is opened before then, and the run "
              "writes no grade or outcome (`blind: true`): the read regrades from the task file.")
    if kind == "bbeh":
        question = (f"Step 3C ({vendor} half of the lockbox panel, BBEH): does the frozen cascade hold on {n} new sealed "
                    "BBEH items (positions 140+, in no other list)? " + lockbox_panel + " " + frozen)
        prediction = (f"C1 ({tag3('C1')}): the frozen policy minus Sonnet alone, accuracy, paired by item, is above -5 "
                      "points (non-inferiority); its dollar ratio to Sonnet is reported with a 95% interval. "
                      f"C2 ({tag3('C2')}): the frozen mixed-vendor first round's acceptance minus Haiku x5's, each at its "
                      "own frozen threshold (Learn-then-Test, alpha 0.10), is above 0. One-sided item-bootstrap p-values "
                      "(2,000 draws, stratified by task); Holm at 5% within the confirmatory family "
                      f"{', '.join(family) if family else '(empty)'}. C3 (a check): the frozen policy's accepted-wrong rate "
                      "(the share of all items accepted with a wrong answer) with its one-sided 95% upper bound "
                      "(Clopper-Pearson), flagged if the point estimate is above alpha 0.10. If nothing qualified on the "
                      "search set, C1 and C2 are void (no p-value, never a fallback); if the frozen threshold accepts "
                      "nothing, C1 is void. C1b (exploratory): the frozen policy minus its own escalation model alone, "
                      "same test. Cached expectation (80 items, 5 Haiku, accept when 3 of 5 agree): 67.5% accepted with "
                      "20.0% accepted-wrong. Power (research/v3/pruning/power_cascade.md, base scenario, Holm floor, 200 "
                      "items): C1 0.27 at a true difference of 0, C2 0.49; both under 0.70, so both are exploratory.")
        decision = ("Exploratory: no pass or fail is claimed. C1's 95% interval above -5 points -> the selected cascade "
                    "is a candidate default evidence layer for BBEH-type questions at its measured dollar ratio, to be "
                    "confirmed in November with a confirmatory design. C2's interval above 0 -> vendor mixing in the "
                    "first round stays a candidate. C3 flagged -> the Learn-then-Test guarantee did not transfer; report "
                    "it and do not use the threshold unchanged. Sonnet alone and Sol alone are reported beside the policy. "
                    "A result is never re-tested on these items.")
    else:
        question = (f"Step 3C ({vendor} half of the lockbox panel, ForecastBench): does the frozen spread cascade hold on "
                    f"{n} new data-series questions (40 per source, each question at one resolution date, 12-15 dates per source, in "
                    f"no other list)? "
                    + lockbox_panel + " " + frozen)
        prediction = ("Exploratory (K3; the reference is Sol alone since deviation 29, audit 60, logged before any lockbox "
                      "call): the frozen ForecastBench cascade (escalate when the first round's log-odds spread is above s) "
                      "minus Sol alone in Brier, with a 95% interval (the wider of the question and source x "
                      "resolution-week bootstraps, H10; deviation 31), its dollar ratio to Sol and its escalation rate; the "
                      "same against Sonnet beside it. The selection rule's tolerance is within +0.005 "
                      "Brier of Sol. The $0 replay on the 300 search questions (research/v3/pruning/frontier_forecast.md) "
                      "points to Haiku x2 + Luna x2 pooled, escalating 2% to Sol: +0.0032 Brier against Sol at 0.26x its "
                      "dollars, optimistic as the best of 12. Prediction: within +0.01 Brier of Sol at under 0.5x its "
                      "dollars.")
        decision = ("Three readings of that 95% interval of the policy minus Sol (audits 61-62): upper end at "
                    "most +0.01 Brier at under 0.5x Sol's dollars -> the cheap cross-vendor forecaster is a candidate for "
                    "Phase 4's decision track; lower end above 0 -> Sol is better and stays the forecasting baseline; "
                    "otherwise inconclusive, Sol stays the baseline, the comparison is reported as unresolved and the "
                    "forecast track ends there (no bigger lockbox). Power "
                    "(normal approximation from Phase 1's 150 data-series questions, SD of the per-question difference "
                    "0.044): 'candidate' about 0.56 if the true difference is +0.0034 (Phase 1's), 0.36 at +0.005, 0.89 "
                    "at 0; 'Sol is better' about 0.19 at +0.0034 and 0.89 at +0.01. A miss is not evidence that Sol is "
                    "better.")
    return {"question": question, "prediction": prediction,
            "kill": STOP + " No accuracy, Brier score or outcome of these calls is read before selected.json is committed "
                    "(the read refuses otherwise). Any stop rule: stop, audit, report to Kevin.",
            "decision": decision}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cfgs = []
    for vendor in ("anthropic", "openai"):
        small, mid = SMALL[vendor], MID[vendor]
        flagship = "opus_nothink" if vendor == "anthropic" else "astra_low"
        think = "haiku" if vendor == "anthropic" else "luna_med"
        v = vendor[:4] if vendor == "openai" else "anth"
        probe = prereg_probe(vendor)
        cfgs += [
            config(f"e11_probe_bbeh_{v}", "bbeh", f"{SEALED}/probe_bbeh.txt",
                   [source(small, "bbeh"), source(mid, "bbeh"),
                    source(flagship, "bbeh", items="research/v3/evidence/probe_flagship.txt")], probe),
            config(f"e11_probe_forecast_{v}", "forecast", f"{SEALED}/probe_forecast.txt",
                   [source(small, "forecast"), source(mid, "forecast")], probe),
            config(f"e11_probe_math_{v}", "math", f"{SEALED}/probe_math.txt",
                   [source(small, "math"), source(mid, "math"), source(think, "math")], probe),
        ]
        if vendor == "anthropic":  # audit 51: Opus's cost and truncation at effort low rest on one call
            cfgs.append(config("e11b_probe_opus_anth", "bbeh", f"{SEALED}/probe_bbeh.txt", [source("opus_nothink", "bbeh")], {
                "question": "Step 1.1 re-probe (audit 51): what does opus_nothink (Opus 5.5, adaptive thinking at effort low; "
                            "it cannot turn thinking off) cost per call on BBEH, and how often does it parse and truncate? "
                            "The 10 probe BBEH items, one call each (one is cached from e11_probe_bbeh_anth).",
                "prediction": "About $0.023 per call (the single probe call), parse rate at least 95%, truncation at most 2%.",
                "kill": "Gate G1 for Opus: over 1.5x $0.023 per call, under 95% parsed or over 2% truncated: fix and re-probe "
                        "before e24. A stop rule: stop, audit, report to Kevin.",
                "decision": "Reads cost, parsing and truncation only, never accuracy. The measured cost replaces Opus's "
                            "usd_per_call in e24_opus_bbeh_anth, committed before e24 runs."}))
        for kind, prereg in (("bbeh", prereg_bbeh(vendor)), ("forecast", prereg_forecast(vendor))):
            cfgs.append(config(f"e1{3 if kind == 'bbeh' else 4}_{kind}_{v}", kind, ITEMS[kind],
                               [source(small, kind, calls=5), source(mid, kind),
                                source(mid, kind, first_call=1, items=SECOND[kind])], prereg))
        panel_results = {k: [f"results/e1{3 if k == 'bbeh' else 4}_{k}_anth/calls.csv",
                             f"results/e1{3 if k == 'bbeh' else 4}_{k}_open/calls.csv"] for k in ("bbeh", "forecast")}
        panel_sources = {"haiku_nothink:base": 5, "luna_none:base": 5, "sonnet_nothink:base": 1, "sol61_low:base": 1}
        for kind in ("bbeh", "forecast"):
            cfgs.append(config(
                f"e22_persona_{kind}_{v}", kind, PHASE2[kind],
                [source(small, kind, prompt=p) for p in ("careful", "contrarian", "quick")],
                prereg_phase2("2.2", vendor, kind, f"prompt variety: {small} once under each of three persona prompts "
                              "(careful checker, contrarian, quick estimator) on the Phase 2 items (200 BBEH, 50 per task; "
                              "the 200 sealed ForecastBench questions).", H11,
                              "H11 is exploratory (power 0.45 in the base scenario): an interval above 0 favours buying "
                              "independence across vendors; an interval that includes 0 is reported as unresolved, not as "
                              "evidence for persona panels (audit 48).")))
            cfgs.append(config(
                f"e22b_aggregator_{kind}_{v}", kind, PHASE2[kind], [source(small, kind, prompt="aggregator")],
                prereg_phase2("2.2b", vendor, kind, f"an LLM aggregator: {small} reads the Phase 1 panel's 12 answers "
                              "(5 + 5 + 1 + 1, no model names, shuffled by item) and returns one answer and a confidence.",
                              "H18 (expl): the aggregator's confidence beats the naive share in Brier but not the statistical "
                              "correction; Brier differences with intervals.",
                              "The aggregator matches the statistical correction -> the simpler deployment wins."),
                panel_results=panel_results[kind], panel_sources=panel_sources))
            cfgs.append(config(
                f"e23_reasoning_{kind}_{v}", kind, PHASE2[kind], [source(think, kind, calls=2)],
                prereg_phase2("2.3", vendor, kind, f"more reasoning: {think} (thinking or reasoning at medium) twice per "
                              "item on the Phase 2 items.",
                              "H12 (expl): thinking on raises accuracy more than it lowers rho; rho and accuracy differences "
                              "(on minus off) with intervals.",
                              "Reasoning decorrelates errors -> it enters the independence-per-dollar ranking as a lever; "
                              "otherwise it is reported as an accuracy purchase only.")))
            if vendor == "anthropic" and kind == "bbeh":  # Kevin's D3 (session E3): no Opus on ForecastBench
                cfgs.append(config(
                    f"e24_opus_{kind}_anth", kind, OPUS[kind], [source("opus_nothink", kind)],
                    prereg_phase2("2.4", vendor, kind, "the flagship reference: Opus 5.5 at its least thinking, "
                                  "adaptive thinking at effort low (Opus 5.5 cannot turn thinking off: {type: disabled} "
                                  "and between_tools are rejected; labeled; in probe e11 one call wrote 805 output tokens, "
                                  "about 300 visible), once per item on 150 sealed items, after a 10-item re-probe "
                                  "(e11b_probe_opus_anth). Scheduled in October after G2a (Kevin's D5 and K5).",
                                  "H13 (expl): the H7 cascade is about as accurate as Opus at under 50% of its cost; accuracy "
                                  "difference with a 95% interval (about +-8 points) and the cost ratio.",
                                  "H11 passes and H13's interval sits above -5 points at under 50% of Opus's cost -> the "
                                  "calibrated cross-vendor cascade becomes the default evidence layer.")))
        # e25 (MathArena) deferred to Phase 4's depth track with reasoning on (Kevin's D2, session E3)
        for kind in ("bbeh", "forecast"):  # Phase 3C lockbox (session E3)
            cfgs.append(config(f"e31_lockbox_{kind}_{v}", kind, LOCKBOX[kind],
                               [source(small, kind, calls=5), source(mid, kind)]
                               + [source(small, kind, prompt=p) for p in ("careful", "contrarian", "quick")],
                               prereg_lockbox(vendor, kind), blind=True))  # no `requires`, no grades on disk (K4)
    for cfg in cfgs:
        path = OUT / f"{cfg['name']}.yaml"
        header = f"# Written by scripts/make_evidence_configs.py (evidence plan, step 0.13). Do not edit by hand.\n"
        path.write_text(header + yaml.safe_dump(cfg, sort_keys=False, width=110, allow_unicode=True))
    print(f"wrote {len(cfgs)} configs to {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
