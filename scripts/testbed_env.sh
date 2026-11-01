# Shell helpers for research/v4/testbed/RUN_GPU.md. Source it from the repo root:  source scripts/testbed_env.sh
#
#   step <stage> <hours> <name> <command...>
#       1. refuses to start unless the GPU ledger's stop rule passes for <hours> more (ledger guard; return 3)
#       2. runs the command under `timeout` at 1.5 x <hours> (the protocol's 1.5x rule): a step that runs longer is
#          interrupted (return 5): stop, find out why, log it and call the auditor before going on
#       3. bills the wall-clock since the last step to <stage> (ledger tick), commits the ledger and the committed
#          results (response tables, checks, kernel.csv, sealed lists, throughput.json) and pushes the branch
#       4. with KILL_USD set (the stage's preregistered kill line in dollars), stops once the stage's ledger spend
#          passes it (return 7)
#       While it runs, runs/testbed/step.lock holds the shell's pid, the start time and the step (the idle
#       watchdog leaves a live step alone and ignores a lock whose shell has died).
#   serve <checkpoint> [serve-cmd options]  stops any running server, starts `vllm serve` for the checkpoint in the
#       background (log: runs/testbed/vllm-<checkpoint>.log) and waits until it answers
#   stop_server                             stops it
#   scripts/testbed_in_quant.sh <command>   runs a command in the quantization environment (llm-compressor)
#   start_watchdog <stage>                  (re)starts the idle watchdog, billing idle time to <stage>; run it at every
#                                           GPU boot (RUN_GPU.md)

export TB="python -m autoagentnet.testbed"
export SERVE_ENV="${SERVE_ENV:-$HOME/.venvs/aan-serve}"
export QUANT_ENV="${QUANT_ENV:-$HOME/.venvs/aan-quant}"

step () {
    local stage=$1 hours=$2 name=$3
    shift 3
    # the guard checks the most the step may cost: 1.5 x its estimate, which is also where the timeout stops it
    $TB ledger guard --stage "$stage" --hours "$(python -c "print(float('$hours') * 1.5)")" \
        || { echo "STOP: the GPU budget rule refused '$name'"; return 3; }
    local limit
    limit=$(python -c "print(max(120, int(float('$hours') * 1.5 * 3600)))")
    mkdir -p runs/testbed && echo "$$ $(date +%s) $(( $(date +%s) + limit + 180 )) $name" > runs/testbed/step.lock
    # pid, start, deadline (the timeout plus its kill grace), step
    timeout --signal=INT --kill-after=120 "$limit" "$@"
    local rc=$?
    rm -f runs/testbed/step.lock
    $TB ledger tick --stage "$stage" --step "$name" --note "exit $rc"
    git add research/v4/testbed/gpu_ledger.csv research/v4/testbed/kernel.csv research/v4/testbed/kernel_weights.log \
        research/v4/testbed/throughput.json research/v4/testbed/sealed results/testbed 2>/dev/null
    git commit -qm "testbed $stage: $name (exit $rc)" && git push -q origin HEAD
    if [ "$rc" = 124 ] || [ "$rc" = 130 ]; then
        echo "STOP: '$name' ran past 1.5 x its estimate ($limit s). Find out why, log it in research/log.md and call the auditor."
        return 5
    fi
    if [ -n "$KILL_USD" ] && python -c "from autoagentnet.testbed import gpu_ledger as g; import sys; \
sys.exit(0 if g.spent(stage='$stage') > float('$KILL_USD') else 1)"; then
        echo "STOP: stage $stage has spent more than its kill line \$$KILL_USD (1.5 x its estimate). Log it and call the auditor."
        return 7
    fi
    return $rc
}

stop_server () {
    pkill -f "vllm serve" 2>/dev/null
    for _ in $(seq 1 30); do pgrep -f "vllm serve" >/dev/null || return 0; sleep 2; done
    pkill -9 -f "vllm serve" 2>/dev/null
}

serve () {
    local checkpoint=$1
    shift
    stop_server
    mkdir -p runs/testbed
    # shellcheck disable=SC2046
    nohup $($TB serve-cmd --checkpoint "$checkpoint" "$@") > "runs/testbed/vllm-$checkpoint.log" 2>&1 &
    $TB wait-server || { tail -50 "runs/testbed/vllm-$checkpoint.log"; return 4; }
}

start_watchdog () {
    [ -n "$1" ] || { echo "usage: start_watchdog <pilot|stage1|stage2>"; return 2; }
    pkill -f testbed_watchdog.sh 2>/dev/null
    mkdir -p runs/testbed
    rm -f runs/testbed/step.lock   # no step runs at boot
    WATCHDOG_STAGE="$1" nohup scripts/testbed_watchdog.sh >> runs/testbed/watchdog.log 2>&1 &
    sleep 2
    pgrep -f testbed_watchdog.sh > /dev/null && echo "watchdog running for stage $1" \
        || { echo "WATCHDOG DID NOT START: see runs/testbed/watchdog.log"; return 6; }
}
