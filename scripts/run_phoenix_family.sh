#!/usr/bin/env bash
# One PHOENIX family arm as ONE continuous run (research/phoenix_science/prereg.md "Family arms"; Kevin, 2026-11-01:
# no separate pilot; the first slice of the real run is the gate and the rest continues on its own).
#
#   1. calibration slices g1-g3 (tasks 0, 10, 20 of every model) -> calibration gate -> s1-s6
#   2. combine the arm's tables -> research/phoenix_science/capabilities_<arm>.json
#   3. write the arm's matrix (108 branches), freeze every config, commit and push
#   4. fake dry run of the gate batch (free; results/fake_*)
#   5. gate batch (first case per dataset x 3 methods, draw 1) -> matrix gate -> rest batch (99 branches)
# Every paid batch passes `aan check` first; outputs are committed and pushed under the shared checkpoint lock after
# every batch, with results/run_progress.md regenerated. Any refusal, failure or failed gate stops the arm (no retry).
#
# Usage: scripts/run_phoenix_family.sh ARM   (claude | gpt); the calibration configs must be frozen and committed.
set -u
arm=$1
settings=configs/experiments/phoenix_science/family/settings.yaml
root=configs/experiments/phoenix_science/family/$arm
prefix=$(python -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))['arms'][sys.argv[2]]['prefix'])" "$settings" "$arm")
models=$(python -c "import sys, yaml; print(' '.join(yaml.safe_load(open(sys.argv[1]))['arms'][sys.argv[2]]['models']))" "$settings" "$arm")
table=research/phoenix_science/capabilities_$arm.json
logs=results/${prefix}_runner_logs
branch=$(git rev-parse --abbrev-ref HEAD)
lock=$(git rev-parse --git-common-dir)/aan_checkpoint.lock
mkdir -p "$logs"

say() { echo "[$(date -u +%H:%M:%S)] $prefix: $*"; }
stop() { say "STOPPED: $*"; commit "$logs" "PHOENIX $prefix: runner stopped ($1)"; exit 1; }
commit() {  # paths message
  python scripts/run_progress.py > /dev/null 2>&1
  flock "$lock" sh -c "git add $1 results/run_progress.md && { git diff --cached --quiet || git commit -q -m '$2'; } && git push -q origin '$branch'" \
    || say "commit/push failed for: $2"
}
prune_calibration() {  # finished calibration tasks are skipped on resume; their fitted models are not needed again
  python - "$prefix" $models <<'EOF'
import json, shutil, sys
from pathlib import Path
prefix, models = sys.argv[1], sys.argv[2:]
for m in models:
    run = Path(f"results/{prefix}_cal_{m}")
    if (run / "calibration_state.json").exists():
        for key in json.loads((run / "calibration_state.json").read_text())["done"]:
            shutil.rmtree(run / f"task_{key}", ignore_errors=True)
EOF
}
run_batch() {  # label config
  local free_kb
  free_kb=$(df --output=avail -k . | tail -1)
  [ "$free_kb" -lt 3000000 ] && stop "less than 3 GB of disk free before $1 (fitted models fill the session's allowance)"
  aan check "$2" > "$logs/check_$1.txt" 2>&1 || { tail -6 "$logs/check_$1.txt"; stop "aan check refused $1"; }
  say "batch $1 start"
  aan run "$2" > "$logs/run_$1.json" 2>&1
  local code=$?
  local name
  name=$(python -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))['name'])" "$2")
  local state
  state=$(python -c "import json, sys; print(json.load(open(sys.argv[1]))['status'])" "results/$name/batch_status.json" 2>/dev/null)
  say "batch $1: exit $code, status ${state:-none}"
  [ $code -eq 0 ] && [ "$state" = "completed" ] || { tail -8 "$logs/run_$1.json"; stop "batch $1 did not complete"; }
}

# 1. calibration
for label in g1 g2 g3 s1 s2 s3 s4 s5 s6; do
  run_batch "cal_$label" "$root/calibration/slices/batch_$label.yaml"
  commit "results/${prefix}_cal_* $logs" "PHOENIX $prefix calibration slice $label outputs"
  prune_calibration
  if [ "$label" = g3 ]; then
    python scripts/phoenix_family_gate.py calibration --prefix "$prefix" --models $models > "$logs/gate_calibration.json" 2>&1 \
      || { cat "$logs/gate_calibration.json"; stop "calibration gate NO-GO"; }
    commit "$logs" "PHOENIX $prefix calibration gate GO"
    say "calibration gate GO"
  fi
done
for m in $models; do
  python -c "import json, sys; s = json.load(open(sys.argv[1])); sys.exit(0 if s.get('status') == 'completed' else 1)" \
    "results/${prefix}_cal_$m/status.json" || stop "calibration of $m not completed"
done

# 2-3. table, matrix, freeze, commit
tables=""
for m in $models; do tables="$tables results/${prefix}_cal_$m/capability_table.json"; done
python -m autoagentnet.phoenix combine $tables --out "$table" > "$logs/combine.json" 2>&1 || stop "combine failed"
python -m autoagentnet.phoenix family-matrix --out "$root/matrix" --data-root data/external/phoenix_science \
  --checkpoint-root data/external/phoenix_science_checkpoints --table "$table" --settings "$settings" --arm "$arm" \
  > "$logs/matrix.json" 2>&1 || stop "matrix generation failed"
python -m autoagentnet.phoenix freeze "$root"/matrix/"${prefix}"_E1_*.yaml > "$logs/freeze.json" 2>&1 || stop "freeze failed"
python - "$root/matrix/study_manifest.json" <<'EOF' || stop "manifest status"
import json, sys
from pathlib import Path
path = Path(sys.argv[1])
manifest = json.loads(path.read_text())
manifest["status"] = "frozen"
path.write_text(json.dumps(manifest, indent=2))
EOF
commit "$root/matrix $table $logs" "PHOENIX $prefix: capability table and frozen matrix ($(python -c "import json; print(len(json.load(open('$root/matrix/study_manifest.json'))['branches']))") branches)"

# 4. fake dry run of the gate batch (free)
aan run "$root/matrix/batch_gate.yaml" --model-override fake > "$logs/dry_gate.json" 2>&1 \
  || { tail -8 "$logs/dry_gate.json"; stop "fake dry run of the gate batch failed"; }
say "fake dry run of the gate batch finished"

# 5. gate, then the rest
run_batch gate "$root/matrix/batch_gate.yaml"
commit "$logs" "PHOENIX $prefix: gate batch done"
python scripts/phoenix_family_gate.py matrix --manifest "$root/matrix/study_manifest.json" > "$logs/gate_matrix.json" 2>&1 \
  || { cat "$logs/gate_matrix.json"; stop "matrix gate NO-GO"; }
commit "$logs" "PHOENIX $prefix: matrix gate GO"
say "matrix gate GO; continuing with the rest"
run_batch rest "$root/matrix/batch_rest.yaml"
commit "$logs" "PHOENIX $prefix: all branches done"
say "arm done"
