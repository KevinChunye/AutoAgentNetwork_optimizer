#!/usr/bin/env bash
# Run one Self-or-Social config over its items in slices, as ONE continuous run (Kevin, 2026-11-01: no separate pilot;
# the first slice is the start of the real run and, if its gate passes, the rest continues on its own).
#
# - Slice sizes: each slice must pass `aan check` (its worst case fits the room the governor allows); a refused slice
#   is halved, down to 2 items; below that the runner stops and says why (only Kevin changes the budget rules).
# - Gate: if GATE_ITEMS > 0, the first slice holds exactly that many items and scripts/sos_gate.py must say GO
#   (the prereg's five go/no-go rules); otherwise the run's own stop rules (checked after every chunk) are the gate.
# - After every slice: status.json is kept as status_<config>_items_<offset>.json, results/run_progress.md is
#   regenerated, and both are committed and pushed under the shared checkpoint lock (persist.py).
# - Any stopped or failed slice stops the runner (no retries).
#
# Usage: scripts/run_sos_slices.sh CONFIG START END GATE_ITEMS EXPECTED_ITEM_USD PROJECTED_ITEMS ACCOUNT [SLICE]
#   START/END: item offsets in the config's frozen item order (END exclusive); SLICE: first try for slice size.
set -u
cfg=$1; start=$2; end=$3; gate=$4; expected=$5; projected=$6; account=$7; slice=${8:-32}
stem=$(basename "$cfg" .yaml)
name=$(python -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))['name'])" "$cfg")
items_file=$(python -c "import sys, yaml; print(yaml.safe_load(open(sys.argv[1]))['items'])" "$cfg")
out=results/$name
logs=$out/run_logs
branch=$(git rev-parse --abbrev-ref HEAD)
lock=$(git rev-parse --git-common-dir)/aan_checkpoint.lock
mkdir -p "$logs"

say() { echo "[$(date -u +%H:%M:%S)] $stem: $*"; }
commit_outputs() {
  python scripts/run_progress.py > /dev/null 2>&1
  flock "$lock" sh -c "git add '$out' results/run_progress.md && git commit -q -m '$1' && git push -q origin '$branch'" \
    || say "commit/push of outputs failed (state/ is pushed by the run itself)"
}
slice_ok() {  # status.json of the last slice says completed
  python -c "import json, sys; s = json.load(open(sys.argv[1])); sys.exit(0 if s.get('state') == 'completed' else 1)" \
    "$out/status.json"
}

offset=$start
first=1
while [ "$offset" -lt "$end" ]; do
  if [ $first = 1 ] && [ "$gate" -gt 0 ]; then
    limit=$gate
  else
    limit=$slice
  fi
  [ $((offset + limit)) -gt "$end" ] && limit=$((end - offset))
  while ! aan check "$cfg" --task-offset "$offset" --task-limit "$limit" > "$logs/${stem}_check_$offset.txt" 2>&1; do
    if [ $first = 1 ] && [ "$gate" -gt 0 ]; then
      say "STOPPED: the gate slice ($limit items from $offset) does not pass aan check"; tail -5 "$logs/${stem}_check_$offset.txt"; exit 1
    fi
    limit=$((limit / 2))
    if [ "$limit" -lt 2 ]; then
      say "STOPPED: no slice of 2+ items from $offset fits the room; tell Kevin (budget rules)"; tail -5 "$logs/${stem}_check_$offset.txt"; exit 1
    fi
  done
  say "slice items $offset-$((offset + limit - 1)) start"
  attempt=1
  while :; do
    aan run "$cfg" --task-offset "$offset" --task-limit "$limit" > "$logs/${stem}_run_$offset.json" 2>&1
    code=$?
    # A transient provider fault (server error, overload, timeout, rate limit) is not a model outcome: re-run the same
    # slice (calls already made replay from the cache at $0), at most 3 attempts. Anything else stops the run.
    transient=$(python -c "import json, sys; s = json.load(open(sys.argv[1])); r = str(s.get('reason', ''));
print(1 if s.get('state') == 'failed' and any(k in r for k in ('server_error', 'overloaded', 'Timeout', 'timed out', 'rate_limit', 'APIConnectionError', 'InternalServerError')) else 0)" "$out/status.json" 2>/dev/null)
    if [ "$transient" = 1 ] && [ $attempt -lt 3 ]; then
      say "transient provider fault at slice $offset (attempt $attempt); re-running the slice in 30 s"
      cp "$logs/${stem}_run_$offset.json" "$logs/${stem}_run_${offset}_attempt$attempt.json"
      attempt=$((attempt + 1)); sleep 30; continue
    fi
    break
  done
  cp "$out/status.json" "$out/status_${stem}_items_${offset}.json" 2>/dev/null
  if [ $code -ne 0 ] || ! slice_ok; then
    commit_outputs "$stem: slice from item $offset STOPPED"
    say "STOPPED at slice $offset (exit $code)"; tail -8 "$logs/${stem}_run_$offset.json"; exit 1
  fi
  say "slice done: $(python -c "import json; s = json.load(open('$out/status.json')); print(s.get('live_calls'), 'live calls,', '\$' + str(s.get('new_spend_usd')))")"
  if [ $first = 1 ] && [ "$gate" -gt 0 ]; then
    python scripts/sos_gate.py --results "$out" --items-file "$items_file" --offset "$offset" --limit "$limit" \
      --expected-item-usd "$expected" --projected-items "$projected" --account "$account" > "$logs/${stem}_gate.json" 2>&1
    gate_code=$?
    commit_outputs "$stem: gate slice (items $offset-$((offset + limit - 1))) and gate verdict"
    if [ $gate_code -ne 0 ]; then
      say "NO-GO at the gate (see $logs/${stem}_gate.json); the run stops"; cat "$logs/${stem}_gate.json"; exit 1
    fi
    say "gate GO; continuing"
  else
    commit_outputs "$stem: items $offset-$((offset + limit - 1))"
  fi
  first=0
  offset=$((offset + limit))
done
say "all items $start-$((end - 1)) done"
