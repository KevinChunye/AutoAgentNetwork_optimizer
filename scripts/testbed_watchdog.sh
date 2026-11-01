#!/usr/bin/env bash
# Idle watchdog for the GPU Studio (started by start_watchdog in scripts/testbed_env.sh at every GPU boot): every
# minute, if no `step` is running (no runs/testbed/step.lock, or one whose shell has died) and the GPU has been idle (utilization 0%) for IDLE_MIN minutes, stop any vLLM server, bill
# the idle time to the ledger and try to stop the Studio (lightning_sdk, best effort). Lightning's own idle auto-sleep
# (set in the Studio settings) is the primary guard; this one covers a forgotten server between steps.
IDLE_MIN=${IDLE_MIN:-20}
: "${WATCHDOG_STAGE:?start the watchdog with start_watchdog <stage>}"
BOOT=$(( $(date +%s) - $(cut -d. -f1 /proc/uptime) ))
idle=0
while true; do
    sleep 60
    if [ -f runs/testbed/step.lock ]; then
        pid=$(cut -d' ' -f1 runs/testbed/step.lock)
        started=$(cut -d' ' -f2 runs/testbed/step.lock)
        deadline=$(cut -d' ' -f3 runs/testbed/step.lock)
        if kill -0 "$pid" 2>/dev/null && [ "${started:-0}" -ge "${BOOT:-0}" ] && [ "$(date +%s)" -le "${deadline:-0}" ]; then
            idle=0; continue
        fi
        echo "$(date -u +%FT%TZ) watchdog: stale step.lock (shell $pid gone, written before this boot, or past its" \
            "deadline, e.g. a step stopped with Ctrl-C); removed" >> runs/testbed/watchdog.log
        rm -f runs/testbed/step.lock
    fi
    util=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
    if [ "${util:-0}" -le 0 ]; then idle=$((idle + 1)); else idle=0; fi
    if [ "$idle" -ge "$IDLE_MIN" ]; then
        echo "$(date -u +%FT%TZ) watchdog: GPU idle ${IDLE_MIN} min with no step running; stopping" >> runs/testbed/watchdog.log
        pkill -f "vllm serve"
        python -m autoagentnet.testbed ledger tick --stage "$WATCHDOG_STAGE" --step "idle (watchdog)" >> runs/testbed/watchdog.log 2>&1
        python -c "from lightning_sdk import Studio; Studio().stop()" >> runs/testbed/watchdog.log 2>&1
        idle=0
    fi
done
