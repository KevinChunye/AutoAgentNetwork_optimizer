"""Explicit preparation/report commands; no command runs on import.

Model jobs use `aan run <config>` so they cannot bypass the preregistration gate.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(prog="python -m autoagentnet.phoenix")
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare", help="explicitly prepare data splits (not a model experiment)")
    p.add_argument("--dataset", choices=["all", "covtype", "miniboone", "higgs", "breast_cancer", "wine", "digits"],
                   default="all", help="all = the three science tables; the toy sets are for tests only")
    p.add_argument("--rows", type=int, default=None, help="one fixed stratified subsample of this many rows (seed 42)")
    p.add_argument("--out", required=True)
    p = commands.add_parser("checkpoint", help="execute trusted tools to create a real starting state")
    p.add_argument("--data", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--seed", type=int, default=101)
    p.add_argument("--template", choices=["T1", "T2"], default="T1")
    p = commands.add_parser("matrix", help="write 360 draft recovery configurations; do not execute them")
    for name in ("out", "data-root", "checkpoint-root", "table"):
        p.add_argument("--"+name, required=True)
    p.add_argument("--results-root", default="results")
    p = commands.add_parser("science-matrix", help="write the trimmed science matrix (drafts + batch manifests)")
    for name in ("out", "data-root", "checkpoint-root", "table", "settings"):
        p.add_argument("--"+name, required=True)
    p.add_argument("--results-root", default="results")
    p = commands.add_parser("science-calibration-configs", help="write one calibration config per model")
    for name in ("out", "data-root", "settings"):
        p.add_argument("--"+name, required=True)
    p = commands.add_parser("family-calibration-configs", help="write one family arm's sliced calibration configs")
    for name in ("out", "data-root", "settings", "arm"):
        p.add_argument("--"+name, required=True)
    p = commands.add_parser("family-matrix", help="write one family arm's E1 branches (gate + rest batches)")
    for name in ("out", "data-root", "checkpoint-root", "table", "settings", "arm"):
        p.add_argument("--"+name, required=True)
    p.add_argument("--results-root", default="results")
    p = commands.add_parser("calibration-configs", help="write three draft calibration configurations")
    p.add_argument("--out", required=True)
    p.add_argument("--data-root", required=True)
    p = commands.add_parser("freeze", help="record actual input hashes; commit configurations afterwards")
    p.add_argument("configs", nargs="+")
    p = commands.add_parser("combine", help="combine calibration observations without inventing missing data")
    p.add_argument("tables", nargs="+")
    p.add_argument("--out", required=True)
    p = commands.add_parser("pool", help="extract the predeclared first proposal for a selector comparison")
    p.add_argument("source_run")
    p.add_argument("--out", required=True)
    p = commands.add_parser("seal", help="require all study branches frozen before held-out evaluation")
    p.add_argument("study_manifest")
    p.add_argument("--out", required=True)
    p = commands.add_parser("evaluate", help="explicitly score a sealed study; no refitting or selection")
    p.add_argument("evaluation_manifest")
    p.add_argument("--out", required=True)
    p = commands.add_parser("replay", help="build a replay from existing events; no model calls")
    p.add_argument("run_dir")
    p.add_argument("--out", required=True)
    p = commands.add_parser("report", help="aggregate existing branch statuses and optional test scores")
    p.add_argument("study_manifest")
    p.add_argument("--evaluation-csv")
    p.add_argument("--out", required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        from .data import DATASETS, prepare_dataset
        for name in DATASETS if args.dataset == "all" else [args.dataset]:
            manifest = prepare_dataset(name, args.out, args.rows)
            print(json.dumps({"dataset": name, "search_signature": manifest["search_signature"],
                              "rows": manifest.get("subsample_rows"), "dropped_rows": manifest.get("dropped_rows")}))
    elif args.command == "checkpoint":
        from .checkpoint import create_checkpoint
        cp = create_checkpoint(args.data, args.out, args.seed, args.template)
        print(json.dumps({"dataset": cp["dataset"], "seed": cp["seed"], "template": cp["template"]}))
    elif args.command == "matrix":
        from .study import matrix
        manifest = matrix(args.out, args.data_root, args.checkpoint_root, args.table, args.results_root)
        print(json.dumps({"cases": len(manifest["cases"]), "draft_branches": len(manifest["branches"])}))
    elif args.command in ("science-matrix", "science-calibration-configs"):
        import yaml
        from .study import science_calibration_configs, science_matrix
        settings = yaml.safe_load(Path(args.settings).read_text())  # models, limits, prereg (frozen in the addendum)
        if args.command == "science-matrix":
            manifest = science_matrix(args.out, args.data_root, args.checkpoint_root, args.table, settings["models"],
                                      settings["limits"], settings["prereg"], args.results_root)
            print(json.dumps({"branches": len(manifest["branches"]), "pilot_cases": manifest["pilot_cases"],
                              "batch_manifests": manifest["batch_manifests"]}))
        else:
            print(json.dumps(science_calibration_configs(args.out, args.data_root, settings["models"],
                                                         settings["calibration_limits"], settings["calibration_prereg"])))
    elif args.command in ("family-calibration-configs", "family-matrix"):
        import yaml
        from .study import family_calibration_configs, family_matrix
        settings = yaml.safe_load(Path(args.settings).read_text())
        arm = settings["arms"][args.arm]
        if args.command == "family-calibration-configs":
            print(json.dumps(family_calibration_configs(args.out, args.data_root, arm)))
        else:
            manifest = family_matrix(args.out, args.data_root, args.checkpoint_root, args.table, arm,
                                     settings["limits"], args.results_root)
            print(json.dumps({"branches": len(manifest["branches"]), "gate_cases": manifest["gate_cases"],
                              "batch_manifests": manifest["batch_manifests"]}))
    elif args.command == "calibration-configs":
        from .study import calibration_configs
        print(json.dumps(calibration_configs(args.out, args.data_root)))
    elif args.command == "freeze":
        from .study import freeze_config
        for path in args.configs:
            print(json.dumps({"config": path, "frozen_hashes": freeze_config(path)}))
    elif args.command == "combine":
        from .calibrate import combine_tables
        table = combine_tables(args.tables, args.out)
        print(json.dumps({"observations": len(table.records), "synthetic": table.synthetic}))
    elif args.command == "pool":
        from .study import extract_proposal_pool
        print(json.dumps(extract_proposal_pool(args.source_run, args.out)))
    elif args.command == "seal":
        from .evaluate import seal_evaluation
        manifest = json.loads(Path(args.study_manifest).read_text())
        sealed = seal_evaluation(manifest["branches"], args.out)
        print(json.dumps({"sealed_branches": len(sealed["branches"])}))
    elif args.command == "evaluate":
        from .evaluate import evaluate_manifest
        frame = evaluate_manifest(args.evaluation_manifest, args.out)
        print(json.dumps({"evaluated_branches": len(frame)}))
    elif args.command == "replay":
        from .report import replay
        replay(args.run_dir, args.out)
        print(args.out)
    else:
        from .report import aggregate
        frame = aggregate(args.study_manifest, args.evaluation_csv, args.out)
        print(json.dumps({"status_rows": len(frame)}))


if __name__ == "__main__":
    main()
