"""One study manifest for the single sealed PHOENIX evaluation: the main study plus every family arm.

The prereg (research/phoenix_science/prereg.md, "Family arms") scores every branch together, once, after all are
frozen. `seal` takes one manifest, so this concatenates the branch lists of the given manifests and refuses a
duplicate branch name or a branch without its frozen and sealed_test paths. Nothing is evaluated here.

Usage: python scripts/phoenix_combined_manifest.py MANIFEST [MANIFEST ...] --out reports/phoenix_science/evaluation/combined_manifest.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

REQUIRED = ("name", "case_id", "experiment", "policy", "fault", "budget", "frozen", "sealed_test")


def combine(paths: list[str]) -> dict:
    branches, sources = [], []
    for path in paths:
        manifest = json.loads(Path(path).read_text())
        for b in manifest["branches"]:
            missing = [k for k in REQUIRED if k not in b]
            if missing:
                raise ValueError(f"{path}: branch {b.get('name')} lacks {missing}")
            branches.append({**b, "draw": b.get("draw", 0), "manifest": str(path)})
        sources.append({"manifest": str(path), "branches": len(manifest["branches"])})
    names = [b["name"] for b in branches]
    if len(names) != len(set(names)):
        raise ValueError("duplicate branch names across manifests")
    return {"schema": 1, "status": "frozen", "sources": sources, "branches": branches}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("manifests", nargs="+")
    p.add_argument("--out", required=True)
    args = p.parse_args()
    combined = combine(args.manifests)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(combined, indent=2))
    print(json.dumps(combined["sources"]))


if __name__ == "__main__":
    main()
