# Self-or-social: runbook for the paid steps

This file is for a new cloud session, or a local machine, that already has two things:
- the session owner's **own** Anthropic key, stored as the environment secret `AAN_ANTHROPIC_API_KEY`, with
  `AAN_ANTHROPIC_WORKSPACE_ID` alongside it;
- `huggingface.co` in the network allow list (data/external is rebuilt from the pinned HF revision).

Never paste a key into chat, a file or a command. The code reads it from the environment only.

Each step below lists its expected **new** spend. The first answers and the Sonnet control are reused from the E5
anchor at $0. One paid run at a time.

## 0. Setup ($0)

```bash
git fetch origin self_or_social && git checkout self_or_social && git pull origin self_or_social
pip install -e ".[dev]"
[ -n "$AAN_ANTHROPIC_API_KEY" ] && echo key set || echo KEY MISSING
python scripts/fetch_external.py          # needs huggingface.co; data/external/bbeh_all.jsonl must print "ok"
python -m pytest -q tests/test_self_or_social_*.py
aan status                                # room per account under the phase caps
```

`fetch_external.py` refuses if HF has moved past the pinned revision. If it does, stop and report: the recorded
items cannot be rebuilt that way.

## 1. Dry run and smoke (about $0.01)

```bash
aan run configs/experiments/self_or_social/sos_dev.yaml --model-override fake --task-limit 2   # free, runs/dry/
aan estimate configs/experiments/self_or_social/sos_dev.yaml --task-limit 2
aan check configs/experiments/self_or_social/sos_dev.yaml --task-limit 2
aan run configs/experiments/self_or_social/sos_dev.yaml --task-limit 2
cat results/sos_dev/status.json           # state completed, live_calls 18, new_spend_usd ~0.01
```

The smoke covers items 0-1 of the dev list, so slice 0 below reuses its 18 calls from the cache.
After the smoke, call the `auditor` subagent and paste its verdict into `research/audit_log.md`.

## 2. Calibration, dev, 200 items (about $1.2)

Choose slices with `aan estimate ... --task-offset X --task-limit N`. Keep `worst_case_x_safety` under $2, so no
pre-run audit is needed; about 35 items per slice. Then, for each slice:

```bash
aan check configs/experiments/self_or_social/sos_dev.yaml --task-offset 0 --task-limit 35
aan run   configs/experiments/self_or_social/sos_dev.yaml --task-offset 0 --task-limit 35
```

Run the slices at offsets 0, 35, 70, 105, 140 and 175 (the last one is 25 items).

After each slice:
- read `results/sos_dev/status.json`;
- the runner has already pushed `state/` after every chunk;
- call the auditor.

## 3. Freeze ($0)

```bash
python analysis/self_or_social.py freeze --dev results/sos_dev/calls.csv
git add research/self_or_social/frozen.json results/sos_dev && git commit -m "self_or_social: freeze policy on dev" && git push -u origin self_or_social
```

`sos_test.yaml` refuses to run until `frozen.json` is committed. From this point nothing is re-fitted.

## 4. Test, 240 items, branches plus full review (about $1.9)

Slices of about 27 items keep the worst case under $2. Check `aan estimate` first.

```bash
aan check configs/experiments/self_or_social/sos_test.yaml --task-offset 0 --task-limit 27
aan run   configs/experiments/self_or_social/sos_test.yaml --task-offset 0 --task-limit 27
```

Run the slices at offsets 0, 27, ..., 216 (9 slices). After each one, read `status.json` and call the auditor.

## 5. Read once, demo, report ($0)

```bash
python analysis/self_or_social.py read --test results/sos_test/calls.csv --single results/e51_sonnet_bbeh/calls.csv
python analysis/sos_demo.py --calls results/sos_test/calls.csv --summary reports/self_or_social/summary.csv
git add results/sos_test reports/self_or_social && git commit -m "self_or_social: test read" && git push -u origin self_or_social
```

Then:
- call the auditor on the read, before any conclusion;
- fill the numbers into `reports/self_or_social/PITCH.md` from `summary.md` only;
- open the PR for Kevin.

## Stop rules (from the prereg)

| Trigger | What happens |
|---|---|
| A member and phase is over 10% unparsed or truncated | The runner stops by itself |
| Cost per call is over 2x its guard | The runner stops by itself |
| The governor refuses | The runner stops by itself |
| Actual spend is over 1.5x the estimate | Stop paying and audit |

Never edit `configs/budget.yaml`, `configs/pricing.yaml` or `state/`.
