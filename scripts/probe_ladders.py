"""Run the free checks of every v3 ladder and record the evidence (research/v3/program.md).

    python scripts/probe_ladders.py                 # all four ladders
    python scripts/probe_ladders.py --only W1 W2-B  # some of them
    python scripts/probe_ladders.py --table-only    # print the table from the saved evidence, no probing

Data ladders (W1, W2-B) probe every rung, because check 6 (the paid band check) can still fail
the chosen rung, and the next rung that passed checks 1-5 is then band-checked. Software ladders
(W3b, W4) stop at the first rung that passes. Writes research/v3/ladder_evidence.json (one record
per rung tried; item ids for the hand checks, never item text) and prints the table that
research/v3/data_sources.md shows. Set AAN_SOFTWARE_DIR to reuse clones and virtual environments.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from autoagentnet.ladder import Evidence, LadderResult, Net, evidence_table, run_ladder
from autoagentnet.ladder.core import markdown_table
from autoagentnet.ladder.rungs import CUTOFF, CUTOFF_SOURCE, w1_rungs, w2b_rungs
from autoagentnet.ladder.software import w3b_rungs, w4_rungs

ROOT = Path(__file__).resolve().parents[1]
LADDERS = {"W1": (w1_rungs, True), "W2-B": (w2b_rungs, True), "W3b": (w3b_rungs, False), "W4": (w4_rungs, False)}


def saved_results(path: Path) -> list[LadderResult]:
    """The ladder results stored in the evidence file, one per workstream, in ladder order."""
    records = json.loads(path.read_text())["rungs"]
    results = []
    for name in LADDERS:
        evidence = [Evidence(**r) for r in records if r["workstream"] == name]
        if evidence:
            results.append(LadderResult(name, evidence, next((e for e in evidence if e.chosen), None)))
    return results


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--only", nargs="*", default=list(LADDERS))
    p.add_argument("--out", default=str(ROOT / "research/v3/ladder_evidence.json"))
    p.add_argument("--table-only", action="store_true")
    args = p.parse_args()
    if args.table_only:
        print(markdown_table(evidence_table(saved_results(Path(args.out)))))
        return

    net = Net(os.environ.get("HF_TOKEN"))
    results = []
    for name in args.only:
        make, probe_all = LADDERS[name]
        result = run_ladder(make(), net, probe_all=probe_all)
        print(result.summary(), flush=True)
        results.append(result)

    records = []
    for result in results:
        for ev in result.evidence:
            record = dataclasses.asdict(ev)
            record.pop("hand_check_golds")  # golds stay out of git with the items
            records.append(record)
    out = Path(args.out)
    previous = json.loads(out.read_text())["rungs"] if out.exists() else []
    kept = [r for r in previous if r["workstream"] not in {res.workstream for res in results}]
    out.write_text(json.dumps({"probed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                               "cutoff": str(CUTOFF), "cutoff_source": CUTOFF_SOURCE,
                               "hf_token_set": bool(os.environ.get("HF_TOKEN")),
                               "rungs": kept + records}, indent=1) + "\n")
    print(markdown_table(evidence_table(results)))


if __name__ == "__main__":
    main()
