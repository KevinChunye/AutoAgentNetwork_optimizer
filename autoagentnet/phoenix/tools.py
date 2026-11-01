"""Time-bounded tool processes; no model client and no generated Python execution."""
from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

from .store import atomic_json


class ToolFailure(RuntimeError):
    def __init__(self, message, cpu_s=0.0, elapsed_s=0.0):
        super().__init__(message)
        self.cpu_s = cpu_s
        self.elapsed_s = elapsed_s


def run_child(command, env, timeout_s):
    """Run one worker process and return (exit code, stdout, stderr, CPU seconds, timed out).

    CPU seconds = user + system time of THIS child only, read from os.wait4 when it is reaped. Measuring the
    difference of RUSAGE_CHILDREN around the call would also count workers that other branches of a batch
    (threads of the same process) reaped meanwhile. In a serial run both measures are the same."""
    import tempfile
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        process = subprocess.Popen(command, env=env, stdout=out, stderr=err)
        deadline, timed_out = time.monotonic() + timeout_s, False
        while True:
            pid, status, usage = os.wait4(process.pid, os.WNOHANG)
            if pid:
                break
            if time.monotonic() >= deadline:
                process.kill()
                pid, status, usage = os.wait4(process.pid, 0)
                timed_out = True
                break
            time.sleep(0.02)
        process.returncode = os.waitstatus_to_exitcode(status)  # reaped here, so Popen never waits again
        out.seek(0)
        err.seek(0)
        return (process.returncode, out.read().decode(errors="replace"), err.read().decode(errors="replace"),
                usage.ru_utime + usage.ru_stime, timed_out)


class ToolRunner:
    def __init__(self, data_path, store_path, work_dir, timeout_s=30):
        self.data_path, self.store_path = str(Path(data_path).resolve()), str(Path(store_path).resolve())
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s

    def run(self, graph, step, cpu_left=120, wall_left=30, stage_only=False):
        request = {"data": self.data_path, "store": self.store_path, "graph": graph.model_dump(),
                   "operation": step.operation, "verify": step.mode == "verify", "stage_only": stage_only,
                   "cpu_limit_s": max(1, math.ceil(cpu_left))}
        path = self.work_dir / "tool_request.json"
        atomic_json(path, request)
        env = os.environ.copy()
        for key in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "NUMEXPR_NUM_THREADS"):
            env[key] = "1"
        # Tool processes need neither model keys nor unrelated SDK credential fallbacks.
        for key in list(env):
            if key.endswith("API_KEY") or key.endswith("PROXY_KEY"):
                env.pop(key)
        start = time.monotonic()
        timeout = min(self.timeout_s, wall_left)
        if timeout <= 0 or cpu_left <= 0:
            raise ToolFailure("tool budget exhausted")
        code, stdout, stderr, cpu, timed_out = run_child(
            [sys.executable, "-m", "autoagentnet.phoenix.worker", str(path.resolve())], env, timeout)
        elapsed = time.monotonic()-start
        if timed_out:
            raise ToolFailure("tool timed out", cpu, elapsed)
        if code:
            raise ToolFailure("tool failed: "+stderr[-600:], cpu, elapsed)
        record = json.loads(stdout)
        record["cpu_s"] = cpu
        record["elapsed_s"] = elapsed
        return record
