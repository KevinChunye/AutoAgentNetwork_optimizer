"""GPU trace sidecar (session M1): polls the vLLM server's Prometheus endpoint every 2 s and nvidia-smi every 1 s
while a shard samples, and writes the trace next to the shard (<shard>.gpu_trace.parquet).

Plain words first.
  KV-cache usage      share of the engine's KV cache in use (vllm:kv_cache_usage_perc, a 0-1 fraction)
  running / waiting   requests in the running batch / queued (vllm:num_requests_running, vllm:num_requests_waiting)
  TTFT, per-token latency, prefill, decode, queue   the server's histograms (vllm:time_to_first_token_seconds,
                      vllm:inter_token_latency_seconds, vllm:request_{prefill,decode,queue}_time_seconds); the trace
                      keeps each one's running sum and count, so the mean over any window is delta sum / delta count
  power, memory, utilization   nvidia-smi's power.draw (W), memory.used (MiB) and utilization.gpu (%) per GPU
  energy              joules = the integral of power over the shard's window (trapezoid rule over the 1 s samples,
                      summed over GPUs): a measurement of the whole GPU, idle draw included
  per-call energy     the shard's energy shared out over its calls by each call's share of decode-token units
                      (output + 0.1 x input tokens, sample.PREFILL_WEIGHT): an apportionment, not a measurement
Metric names are vLLM 0.32.0's (research/lit/vllm_metrics_qwen35_kv.md); older names (gpu_cache_usage_perc,
time_per_output_token_seconds) are gone there, so a missing name is recorded as missing, never guessed.

Trace rows: t (seconds since the trace started), utc, source ("vllm" or "gpu"), gpu (index; None for vllm rows) and
the fields above (kv_cache_usage, running, waiting, <hist>_sum, <hist>_count, power_w, memory_mib, util_pct).
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
import time
from datetime import datetime, timezone

import httpx
import pandas as pd

GAUGES = {"kv_cache_usage": "vllm:kv_cache_usage_perc", "running": "vllm:num_requests_running",
          "waiting": "vllm:num_requests_waiting"}
COUNTERS = {"prompt_tokens": "vllm:prompt_tokens_total", "generation_tokens": "vllm:generation_tokens_total"}
HISTOGRAMS = {"ttft": "vllm:time_to_first_token_seconds", "itl": "vllm:inter_token_latency_seconds",
              "prefill": "vllm:request_prefill_time_seconds", "decode": "vllm:request_decode_time_seconds",
              "queue": "vllm:request_queue_time_seconds"}
SMI_QUERY = "index,power.draw,memory.used,utilization.gpu"
LINE_RE = re.compile(r"^([a-zA-Z_:][a-zA-Z0-9_:]*)(\{[^}]*\})?\s+(\S+)")


def parse_prometheus(text: str) -> dict[str, float]:
    """name -> value, summed over label sets (one served model, one engine: the sum is the value), for the gauges,
    counters and histogram _sum/_count series the trace keeps."""
    wanted = set(GAUGES.values()) | set(COUNTERS.values()) | {f"{h}_{s}" for h in HISTOGRAMS.values() for s in ("sum", "count")}
    out: dict[str, float] = {}
    for line in text.splitlines():
        m = LINE_RE.match(line)
        if not m or m.group(1) not in wanted:
            continue
        try:
            out[m.group(1)] = out.get(m.group(1), 0.0) + float(m.group(3))
        except ValueError:
            continue
    return out


def vllm_row(values: dict[str, float]) -> dict:
    row = {k: values.get(name) for k, name in {**GAUGES, **COUNTERS}.items()}
    for k, name in HISTOGRAMS.items():
        row[f"{k}_sum"], row[f"{k}_count"] = values.get(f"{name}_sum"), values.get(f"{name}_count")
    return row


def run_smi() -> str:
    """nvidia-smi's CSV for SMI_QUERY ("" when nvidia-smi is missing: a CPU machine records no GPU rows)."""
    smi = shutil.which("nvidia-smi")
    if not smi:
        return ""
    return subprocess.run([smi, f"--query-gpu={SMI_QUERY}", "--format=csv,noheader,nounits"], capture_output=True,
                          text=True, timeout=10).stdout


def parse_smi(text: str) -> list[dict]:
    rows = []
    for line in text.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != 4:
            continue

        def num(x):
            try:
                return float(x)
            except ValueError:  # "[N/A]"
                return None
        rows.append({"gpu": int(parts[0]), "power_w": num(parts[1]), "memory_mib": num(parts[2]), "util_pct": num(parts[3])})
    return rows


class Sidecar:
    """Polls while running: `async with Sidecar(...) as trace: ...`, then `trace.frame()`."""

    def __init__(self, metrics_url: str, smi=run_smi, metrics_every_s: float = 2.0, smi_every_s: float = 1.0,
                 transport: httpx.AsyncBaseTransport | None = None):
        self.metrics_url = metrics_url
        self.smi = smi
        self.metrics_every_s = metrics_every_s
        self.smi_every_s = smi_every_s
        self.transport = transport
        self.rows: list[dict] = []
        self._tasks: list[asyncio.Task] = []
        self._t0 = 0.0

    def _stamp(self, source: str) -> dict:
        return {"t": time.perf_counter() - self._t0, "utc": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "source": source}

    async def poll_metrics(self) -> None:
        async with httpx.AsyncClient(transport=self.transport, timeout=5.0) as http:
            while True:
                try:
                    response = await http.get(self.metrics_url)
                    self.rows.append({**self._stamp("vllm"), "gpu": None, **vllm_row(parse_prometheus(response.text))})
                except httpx.HTTPError:
                    self.rows.append({**self._stamp("vllm"), "gpu": None})  # a missed scrape stays a gap
                await asyncio.sleep(self.metrics_every_s)

    async def poll_smi(self) -> None:
        while True:
            text = await asyncio.to_thread(self.smi)
            stamp = self._stamp("gpu")
            self.rows += [{**stamp, **r} for r in parse_smi(text)]
            await asyncio.sleep(self.smi_every_s)

    async def __aenter__(self) -> "Sidecar":
        self._t0 = time.perf_counter()
        self._tasks = [asyncio.create_task(self.poll_metrics()), asyncio.create_task(self.poll_smi())]
        await asyncio.sleep(0)
        return self

    async def __aexit__(self, *exc) -> None:
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self.end_t = time.perf_counter() - self._t0

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def energy_joules(trace: pd.DataFrame) -> float | None:
    """Integral of power over time, per GPU by the trapezoid rule over its samples, summed over GPUs; None without
    at least two power samples on some GPU."""
    if trace.empty or "power_w" not in trace:
        return None
    gpu = trace[(trace["source"] == "gpu") & trace["power_w"].notna()]
    total, any_gpu = 0.0, False
    for _, part in gpu.sort_values("t").groupby("gpu"):
        if len(part) < 2:
            continue
        t, p = part["t"].to_numpy(float), part["power_w"].to_numpy(float)
        total += float(((p[1:] + p[:-1]) / 2 * (t[1:] - t[:-1])).sum())
        any_gpu = True
    return total if any_gpu else None


def apportion_energy(weights: pd.Series, energy_j: float | None) -> pd.Series:
    """Each call's share of the shard's energy by its weight (decode-token units): an apportionment."""
    if energy_j is None or float(weights.sum()) <= 0:
        return pd.Series(None, index=weights.index, dtype="Float64")
    return energy_j * weights / float(weights.sum())


def summary(trace: pd.DataFrame) -> dict:
    """Per-shard numbers for the pilot report: KV-cache usage p95, peak memory (MiB, the largest reading of any
    one GPU), mean utilization, energy, and the server's mean TTFT and inter-token latency over the shard (delta sum
    / delta count of the histograms)."""
    vllm = trace[trace["source"] == "vllm"] if not trace.empty else trace
    gpu = trace[trace["source"] == "gpu"] if not trace.empty else trace
    out = {"kv_cache_usage_p95": None, "peak_memory_mib": None, "util_mean_pct": None, "energy_j": energy_joules(trace),
           "server_ttft_mean_s": None, "server_itl_mean_s": None}
    if not vllm.empty and "kv_cache_usage" in vllm and vllm["kv_cache_usage"].notna().any():
        out["kv_cache_usage_p95"] = float(vllm["kv_cache_usage"].astype(float).quantile(0.95))
        for key, name in (("server_ttft_mean_s", "ttft"), ("server_itl_mean_s", "itl")):
            s, c = vllm[f"{name}_sum"].astype(float).dropna(), vllm[f"{name}_count"].astype(float).dropna()
            if len(c) >= 2 and c.iloc[-1] > c.iloc[0]:
                out[key] = float((s.iloc[-1] - s.iloc[0]) / (c.iloc[-1] - c.iloc[0]))
    if not gpu.empty and "memory_mib" in gpu and gpu["memory_mib"].notna().any():
        out["peak_memory_mib"] = float(gpu["memory_mib"].max())
        out["util_mean_pct"] = float(gpu["util_pct"].astype(float).mean())
    return out


def config_timing(table: pd.DataFrame, traces: pd.DataFrame) -> pd.DataFrame:
    """Per configuration (system), for the pilot report: TTFT p50 and p95, TPOT p50 and p95 (live, streamed calls),
    KV-cache usage p95 and peak GPU memory over its shards' traces, and joules per 1,000 output tokens (the shards'
    measured energy over their output tokens; shards with a cached call have no energy_j and are left out)."""
    live = table[table["timing_source"] == "measured"] if "timing_source" in table else table.iloc[0:0]
    rows = []
    for system, part in table.groupby("system"):
        mine = live[live["system"] == system]
        row = {"system": system, "calls": len(part), "timed_calls": len(mine)}
        for col, name in (("ttft_s", "ttft"), ("tpot_s", "tpot")):
            v = pd.to_numeric(mine[col], errors="coerce").dropna() if col in mine else pd.Series(dtype=float)
            row[f"{name}_p50_s"] = float(v.quantile(0.5)) if len(v) else None
            row[f"{name}_p95_s"] = float(v.quantile(0.95)) if len(v) else None
        energy = part[part["energy_j"].notna()] if "energy_j" in part else part.iloc[0:0]
        tokens = float(energy["output_tokens"].astype(float).sum())
        row["joules_per_1k_output_tokens"] = float(energy["energy_j"].astype(float).sum()) / tokens * 1000 if tokens else None
        trace = traces[traces["system"] == system] if not traces.empty else traces
        s = summary(trace) if not trace.empty else {}
        row["kv_cache_usage_p95"] = s.get("kv_cache_usage_p95")
        row["peak_memory_mib"] = s.get("peak_memory_mib")
        rows.append(row)
    return pd.DataFrame(rows)
