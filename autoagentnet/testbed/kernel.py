"""Real-kernel benchmark (GPU node): speed, memory and energy of real quantized checkpoints.

Accuracy runs use fake-quantized BF16 checkpoints, so they cannot show what W4 or W8 kernels save. This run serves
the compressed checkpoints (vLLM's W4A16 / W8A16 kernels, W3 through its low-bit kernels if they load) and makes
300 calls per checkpoint (50 items x k = 6, thinking budget 1024) through the same sampler, while nvidia-smi is
polled every 0.5 s.

Measured, per checkpoint:
  tokens_per_s     output tokens of the 300 calls / wall-clock seconds (concurrency as in the accuracy runs)
  peak_memory_gb   the largest memory.used seen (includes vLLM's KV-cache reservation, so compare the
                   `weights_gb` that vLLM logs at load, recorded by hand in the runbook, for weight memory)
  joules_per_token energy (power.draw integrated over the run) / output tokens
"""

from __future__ import annotations

import asyncio
import csv
import subprocess
import threading
import time
from pathlib import Path

from . import sample
from .grid import Config

ROOT = Path(__file__).resolve().parents[2]
KERNEL_CSV = ROOT / "research/v4/testbed/kernel.csv"
FIELDS = ["size_b", "precision", "calls", "output_tokens", "wall_s", "tokens_per_s", "peak_memory_gb",
          "joules_per_token", "gpu"]


class SmiPoller:
    """Polls nvidia-smi in a thread: peak memory (MiB) and energy (J, trapezoid over power.draw in W)."""

    def __init__(self, every_s: float = 0.5):
        self.every_s, self.peak_mib, self.joules, self.gpu = every_s, 0.0, 0.0, ""
        self._stop = threading.Event()

    def _read(self) -> tuple[float, float, str]:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,power.draw,name", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10).stdout.strip().splitlines()[0]
        mem, power, name = [x.strip() for x in out.split(",")]
        return float(mem), float(power), name

    def _loop(self):
        last_t, last_p = time.time(), None
        while not self._stop.is_set():
            mem, power, self.gpu = self._read()
            now = time.time()
            self.peak_mib = max(self.peak_mib, mem)
            if last_p is not None:
                self.joules += (power + last_p) / 2 * (now - last_t)
            last_t, last_p = now, power
            self._stop.wait(self.every_s)

    def __enter__(self):
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self._stop.set()
        self._thread.join()


def benchmark(config: Config, tasks, registry, k: int = 6, out: Path = KERNEL_CSV) -> dict:
    """300 calls (len(tasks) x k) of a real-kernel checkpoint; appends a row to kernel.csv. No call cache, so every
    call is generated."""
    start = time.perf_counter()
    with SmiPoller() as smi:
        frame = asyncio.run(sample.sample_config(config, tasks, k, registry, cache=None))
    wall = time.perf_counter() - start
    tokens = float(frame["output_tokens"].sum())
    row = {"size_b": config.size_b, "precision": config.precision, "calls": len(frame), "output_tokens": tokens,
           "wall_s": round(wall, 2), "tokens_per_s": round(tokens / wall, 1),
           "peak_memory_gb": round(smi.peak_mib / 1024, 2), "joules_per_token": round(smi.joules / max(tokens, 1), 4),
           "gpu": smi.gpu}
    new = not Path(out).exists()
    with Path(out).open("a", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        if new:
            writer.writeheader()
        writer.writerow(row)
    return row
