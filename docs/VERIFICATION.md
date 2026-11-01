# Code verification — 2026-10-31

- PHOENIX: 35 offline tests passed.
- Existing upstream core: 214 selected tests passed.
- Combined check: **249 passed, 2 deselected**.
- `git diff --check` and Python compilation passed; `pip check` found no broken requirements.

The two excluded upstream tests require the original tracked `state/ledger.jsonl`:
`test_project_ledger_is_tracked_and_present` and
`test_cli_gate_refuses_an_uncommitted_market_config_without_prereg`.
The source snapshot has no historical ledger, and no replacement was invented.
This is not a claim that the entire upstream historical research/data test suite ran.

The combined check covered the four PHOENIX test files plus upstream executor, task
grading, providers, budget, market, debate and key-hygiene tests. The distributable
includes the 35 PHOENIX tests; apply the patch to the original checkout to rerun its
historical tests with its original data and ledger.

PHOENIX checks include real trusted CPU operations on synthetic arrays, artifact
lineage and corruption, shutdown/resource withdrawal, all six policies, hard budget
eligibility, ablation decision differences, model-output rejection, crash recovery
through model cache/tool receipts, isolated worker execution, split isolation,
calibration protocol on fixtures, CLI gates, sealed evaluation on fixtures, report
arithmetic, and replay HTML escaping.

No live LLM call, scientific benchmark preparation, real capability calibration,
formal 360-branch run, or scientific held-out evaluation was performed. Report tests
use explicitly labeled synthetic fixtures. Real model compatibility and empirical
recovery benefits remain unverified until separately authorized experiments.


## Separately authorized real OpenAI smoke

After the code-delivery checks above, two real OpenAI calls were authorized and completed. Luna and Sol passed JSON parsing, actual bounded pipeline execution, budget/usage accounting, and ledger/cache synchronization. Total list-price ledger cost: $0.0022938. Both runs received an independent PASS audit. See PHOENIX_SMOKE.md. This does not establish full recovery compatibility, cross-provider access, calibration quality, or recovery effectiveness. No formal study was run.
