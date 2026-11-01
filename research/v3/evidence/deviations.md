# Evidence plan: deviations from the preregistered configs (session E4 onward)

Numbered, each with when it was decided relative to any outcome read. Departures in the Phase 3 pruning work are in
research/v3/pruning/deviations.md.

E1. **Cost guard for persona calls** (audit 57, finding 2). Every e22 and e31 prereg's kill says "stop and audit if a
    source costs over 1.5x the probe per call". The probe measured only the base prompt; persona replies are longer.
    After e22_persona_forecast_anth stopped on that guard (50 of 200 questions, before any Phase 2 outcome was read), a
    ref's guard in configs with persona calls became the dearest measured persona cost (Haiku: $0.00084 BBEH from
    e22_persona_bbeh_anth, $0.00028 forecast from those 50 questions; Luna scaled by Haiku's persona-to-base ratio). It
    changes no test: H11 uses measured dollars. Side effect: the config of the already completed e22_persona_bbeh_anth
    changed after its run (guard $0.0008 to $0.00084); its calls were made under $0.0008 and passed it.
E2. **Unprobed prompt kinds** (audit 57, required 2; decided before running them): for e22b's aggregator prompts,
    e22_persona_*_open and e23's adaptive-thinking Haiku and medium-reasoning Luna, the first chunk is the probe. If the
    only stop is cost, with parsing at least 95%, truncation at most 5% and cost at most 3x the base-prompt probe, the
    measured cost is committed as the guard and the run resumes without an audit; any other stop waits for an audit.
    e23's configs, which have no cost guard, run slice 0+20 first as that probe (audit 56).
E3. **Sol alone is a comparator in every Phase 2 read, and the forecast lockbox's reference** (audit 60, required 1;
    decided after the G2a and G2b reads, before any e22b, e23 or e31 call and before the Phase 2 read). Phase 1 found
    Sol at 97.3% on BBEH for 0.45x Sonnet's dollars and Sol's Brier equal to Sonnet's on ForecastBench at about half
    the dollars, so a Phase 2 decision that compares only with Haiku, the panel or Sonnet can favour a system Sol alone
    dominates. (a) `analysis/evidence_phase2.py` gains `sol_rows`: Haiku with thinking on and Luna at reasoning medium
    (2 calls each) and each aggregator (its dollars include the 12 panel calls it reads) against Sol alone, paired,
    with 95% item-bootstrap intervals and dollar ratios; the reasoning arms also against their own thinking-off model,
    on BBEH and ForecastBench (H12 was coded for Haiku on BBEH only; Luna and ForecastBench are added, exploratory).
    (b) H18's BBEH rows are reported per aggregator; the old code joined both aggregators' calls into one column,
    which would have doubled the items once both e22b runs existed (fixed before any e22b call). (c) e22b's decision
    ("the aggregator matches the statistical correction -> the simpler deployment wins") and e23's ("reasoning
    decorrelates errors -> a lever in the independence-per-dollar ranking") are read beside the Sol rows: a system
    that loses to Sol alone in accuracy or Brier at higher dollars is not deployed, whatever the within-panel result.
    (d) The forecast lockbox (e31_lockbox_forecast_*) decides against Sol alone, not Sonnet; the rule, its prereg and
    the read changed together (research/v3/pruning/deviations.md 29). The configs of e22b and e23 are unchanged.
E4. **Rule E2 covers e31_lockbox_forecast_open's Luna persona calls** (audit 63, required 2; before that run). Its Luna
    persona prompts (careful, contrarian, quick) were never probed on OpenAI; their guard is the scaled estimate of
    E1 ($0.00012). The first chunk is their probe: a cost-only stop with parsing at least 95%, truncation at most 5%
    and cost at most 3x the base-prompt probe commits the measured cost as the guard and resumes without an audit;
    any other stop waits for an audit. The run stays blind.
E5. **e23_reasoning_bbeh_anth goes past its 20-item probe only on rates and dollars** (audit 63, required 3; logged
    before any e23 call). e23 is not blind, and its outcomes are sealed until the Phase 2 read, so no accuracy is
    looked at. The other 180 items (slice 20+180) run only if, over the probe's 40 calls, at least 95% parse, at most
    5% truncate, and the mean dollars per call are at most 0.5x Sol's measured BBEH cost ($0.0059 per call, so at most
    $0.00295). Otherwise e23 stops at 20 items and is reported as a cost finding.
E6. **Defaults for the Phase 2 arms that no longer change a decision** (audit 63, required 4). Dropped unless Kevin asks
    for them: e23_reasoning_forecast_anth, e22b_aggregator_bbeh_open, e22b_aggregator_forecast_open,
    e22_persona_forecast_open, e23_reasoning_bbeh_open and e23_reasoning_forecast_open (about $1.2 OpenAI and $1.6
    worst case Anthropic). e22_persona_bbeh_open runs only if Kevin keeps the BBEH lockbox (it feeds only the BBEH
    cascade search). The Phase 2 read (`analysis/evidence_phase2.py`) skips arms whose calls do not exist.
    E5 amended (audit 64, finding 8; before any e23 call): Sol's measured BBEH cost is $0.005854 per call
    (e13_bbeh_open), so the bar is 0.5x that, $0.00293 per call, not $0.00295. E5 is checked from status.json's
    by_source dollars and call counts only; e23's calls.csv (which carries grades) is not opened. The continuation
    20+180 runs as two slices (20+90, 110+90) with an estimate recorded first.
