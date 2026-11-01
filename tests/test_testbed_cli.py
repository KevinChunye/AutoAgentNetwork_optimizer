"""The runbook's commands that read results (pilot-report, analyze) run on shards made by the real sampler against
the fake server; estimate and serve-cmd print what the runbook expects."""

import argparse
import asyncio
import json

import pytest

import autoagentnet.testbed.__main__ as cli
from autoagentnet.providers.vllm_local import VLLMLocalClient
from autoagentnet.testbed import grid, sample
from autoagentnet.testbed.fake_server import FakeVLLM
from autoagentnet.testbed.tasks import world_tasks
from autoagentnet.testbed.world import World


@pytest.fixture
def results(tmp_path, monkeypatch):
    world = World(10, salt="cli")
    client = VLLMLocalClient(base_url="http://fake", transport=FakeVLLM(world).transport())
    configs = [grid.Config(grid.QWEN, s, p, b) for s in (2, 4) for p in ("bf16", "w4") for b in (0, 1024)]
    registry = grid.registry_for(configs, 6, "http://fake")
    for ref in registry.models:
        registry.set_client(ref, client)
    for c in configs:
        asyncio.run(sample.run_shards(c, world_tasks(world), 6, registry, tmp_path / "results" / "pilot", chunk=5))
    monkeypatch.setattr(cli, "RESULTS", tmp_path / "results")
    monkeypatch.setattr(grid, "THROUGHPUT_JSON", tmp_path / "throughput.json")
    return tmp_path


def test_pilot_report_rescales_the_stage_one_estimate(results, capsys):
    cli.cmd_pilot_report(argparse.Namespace(stage="pilot", items=363, rate=None, machine="H100"))
    out = capsys.readouterr().out
    assert "measured 4B throughput" in out and "stage-1 estimate" in out
    assert json.loads((results / "throughput.json").read_text())["scale"] > 0


def test_analyze_writes_t1_to_t4(results, capsys):
    out = results / "analysis"
    cli.cmd_analyze(argparse.Namespace(stage="pilot", judge="qwen3.5-9b:bf16:budget:4096", out=str(out), unseal=False,
                                       again=False, reason=""))
    primary = json.loads((out / "primary.json").read_text())
    assert {"t1", "t1_shared_shock", "t1_concentration", "t1_literal", "t2", "t3", "t4"} <= set(primary)
    assert (out / "t1.csv").exists() and (out / "t4.csv").exists()


def test_estimate_and_serve_cmd(capsys):
    cli.cmd_estimate(argparse.Namespace(stage="stage1", items=363, k=6, tps=["4=15000"], overhead=1.5, rate=None,
                                        machine="H200"))
    est = json.loads(capsys.readouterr().out)
    assert est["machine"] == "H200" and est["rate_usd_per_h"] == 4.5
    cli.cmd_serve_cmd(argparse.Namespace(checkpoint="qwen3.5-4b-w4-real", port=8000, max_model_len=16384, gpu_memory=0.9))
    cmd = capsys.readouterr().out
    assert "--served-model-name qwen3.5-4b-w4 " in cmd and "qwen3.5-4b-w4-real" in cmd and "--language-model-only" in cmd


def test_pilot_report_takes_the_gpu_type_from_the_pilot_ledger(tmp_path, monkeypatch):
    from autoagentnet.testbed import gpu_ledger

    ledger = tmp_path / "gpu_ledger.csv"
    ledger.write_text("date,machine,gpu_type,hours,rate_usd_per_h,usd,stage,step,note\n"
                      "d,s,H200,0.5,4.5,2.25,pilot,sample,\nd,s,CPU,0.2,0.2,0.04,pilot,grade,\nd,s,H200,0.1,4.5,0.45,pilot,x,\n")
    monkeypatch.setattr(gpu_ledger, "LEDGER", ledger)
    monkeypatch.setattr(gpu_ledger.rows, "__defaults__", (ledger,))
    assert cli.ledger_machine("pilot") == "H200" and cli.ledger_machine("stage1") is None


def test_watchdog_ignores_a_stale_step_lock(tmp_path):
    import subprocess

    lock = tmp_path / "runs/testbed/step.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text("999999 0 9999999999 dead step\n")  # a pid that is not running
    script = (cli.ROOT / "scripts/testbed_watchdog.sh").read_text()
    body = script[script.index("    if [ -f runs/testbed/step.lock ]; then"):script.index("    util=")]
    probe = f"cd {tmp_path}\nidle=0\nwhile true; do\n{body}    echo reached; break\ndone\n"
    out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True).stdout
    assert out.strip() == "reached" and not lock.exists()


def test_watchdog_ignores_a_live_lock_past_its_deadline(tmp_path):
    import os
    import subprocess

    lock = tmp_path / "runs/testbed/step.lock"
    lock.parent.mkdir(parents=True)
    lock.write_text(f"{os.getpid()} 9999999999 1 step stopped with Ctrl-C\n")  # live pid, deadline long past
    script = (cli.ROOT / "scripts/testbed_watchdog.sh").read_text()
    body = script[script.index("    if [ -f runs/testbed/step.lock ]; then"):script.index("    util=")]
    probe = f"cd {tmp_path}\nBOOT=0\nidle=0\nwhile true; do\n{body}    echo reached; break\ndone\n"
    out = subprocess.run(["bash", "-c", probe], capture_output=True, text=True).stdout
    assert out.strip() == "reached" and not lock.exists()
