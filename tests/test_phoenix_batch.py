"""The in-process batch runner (`kind: phoenix_batch`): offline, fake provider only."""
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
import yaml

from test_phoenix_core import InlineTool, checkpoint  # noqa: F401  (fixture)
from autoagentnet.budget import BudgetExceeded, BudgetRules, Phase
from autoagentnet.meter import CallRecord, Ledger
from autoagentnet.phoenix.batch import LockedGovernor, PhoenixBatchConfig, estimate_batch, run_batch
from autoagentnet.phoenix.run import PhoenixConfig
from autoagentnet.phoenix.tools import run_child

SETTINGS = [("fixed", "F1"), ("llm", "F1"), ("full", "F1"), ("no_cost", "F1"), ("full", "F0"), ("fixed", "F0")]


def write_batch(tmp_path, checkpoint, out, concurrency, chunk_size=None, settings=SETTINGS):
    """One fake branch config per (policy, fault), all on the same fixture checkpoint, and their batch manifest."""
    folder = tmp_path / f"configs_{out}"
    folder.mkdir()
    paths = []
    for i, (policy, fault) in enumerate(settings):
        cfg = PhoenixConfig(name=f"b{i}_{policy}_{fault}", checkpoint=str(checkpoint), policy=policy, fault=fault,
                            model_override="fake", out_dir=str(tmp_path / out), max_calls=4, max_tools=12,
                            api_budget_usd=0.2)
        path = folder / f"b{i}.yaml"
        path.write_text(yaml.safe_dump(cfg.model_dump(exclude_none=True)))
        paths.append(str(path))
    batch = PhoenixBatchConfig(name=f"batch_{out}", branches=paths, concurrency=concurrency, chunk_size=chunk_size,
                               model_override="fake", out_dir=str(tmp_path / out))
    path = tmp_path / f"batch_{out}.yaml"
    path.write_text(yaml.safe_dump(batch.model_dump(exclude_none=True)))
    return batch, path


def outcome(run_dir: Path) -> dict:
    """What a branch decided and delivered, without timings (CPU and wall time vary run to run)."""
    status = json.loads((run_dir / "status.json").read_text())
    plan = json.loads((run_dir / "recovery_plan.json").read_text())
    calls = [json.loads(line) for line in (run_dir / "calls.jsonl").read_text().splitlines() if line]
    return {"status": status["status"], "score": status["validation_score"], "incumbent": status["incumbent"],
            "order": plan["execution_order"], "reused": plan["reused_for_final_delivery"],
            "abandoned": plan["abandoned"], "models": plan["model_assignments"],
            "calls": [(c["purpose"], c["model_ref"], c["output"]["content"]) for c in calls]}


def test_locked_governor_never_lets_the_summed_worst_case_pass_the_run_cap():
    """Eight threads race to reserve $0.03 worst cases against a $1 run cap: accepted reservations, still held,
    never sum above $1 / 1.15, and the excess is refused."""
    rules = BudgetRules(hard_caps_usd={"openai": 1e6}, phase="p", phases={"p": Phase(total_usd=1e6, max_run_usd=1e6)})
    governor = LockedGovernor(Ledger(), rules, run_cap_usd=1.0)
    accepted, refused, start = [], [], threading.Barrier(8)

    def worker():
        start.wait()
        for _ in range(40):
            try:
                accepted.append(governor.reserve("openai", 0.03))
            except BudgetExceeded:
                refused.append(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sum(r.amount_usd for r in accepted) * 1.15 <= 1.0 + 1e-9
    assert refused and len(accepted) == int(1.0 / 1.15 / 0.03 + 1e-9)
    # Settling concurrently writes every record once and keeps the run total within the cap.
    threads = [threading.Thread(target=governor.settle, args=(r, CallRecord(
        run_id="t", purpose="t", network="t", config_id="t", task_id=str(i), stage="s", agent_id="a",
        account="openai", provider="openai", model="m", cost_usd=0.02, input_tokens=1, cache_write_tokens=0,
        cache_read_tokens=0, output_tokens=1, latency_s=0.1))) for i, r in enumerate(accepted)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(governor.ledger.records) == len(accepted) and governor.run_spent_usd * 1.15 <= 1.0 + 1e-9


def test_batch_of_four_matches_serial_execution(checkpoint, tmp_path):
    serial, serial_path = write_batch(tmp_path, checkpoint, "serial", concurrency=1)
    parallel, parallel_path = write_batch(tmp_path, checkpoint, "parallel", concurrency=4)
    a = run_batch(serial, serial_path, tool_factory=InlineTool)
    b = run_batch(parallel, parallel_path, tool_factory=InlineTool)
    assert a["status"] == b["status"] == "completed", (a, b)
    assert a["branches_reported"] == b["branches_reported"] == len(SETTINGS)
    for _, cfg in serial.branch_configs():
        assert outcome(tmp_path / "serial" / f"fake_{cfg.name}") == outcome(tmp_path / "parallel" / f"fake_{cfg.name}")
    assert json.loads((tmp_path / "parallel" / "fake_batch_parallel" / "batch_status.json").read_text())["status"] == "completed"


class SimulatedCrash(BaseException):
    """Like a killed process: not an Exception, so nothing inside the branch catches it."""


def test_a_crash_mid_batch_leaves_a_resumable_partial_status(checkpoint, tmp_path):
    batch, path = write_batch(tmp_path, checkpoint, "crash", concurrency=2, chunk_size=2,
                              settings=[("fixed", "F1"), ("full", "F1"), ("llm", "F1"), ("full", "F0")])
    crashed = []

    class CrashOnce(InlineTool):
        def run(self, graph, step, **kwargs):
            if "b2_llm" in self.data and not crashed:
                crashed.append(1)
                raise SimulatedCrash()
            return super().run(graph, step, **kwargs)

    with pytest.raises(SimulatedCrash):
        run_batch(batch, path, tool_factory=CrashOnce)
    partial = json.loads((tmp_path / "crash" / "fake_batch_crash" / "batch_status.json").read_text())
    assert partial["status"] == "partial" and partial["branches_reported"] == 2   # the first chunk finished
    state = json.loads((tmp_path / "crash" / "fake_b2_llm_F1" / "state.json").read_text())
    assert state["status"] == "running"                                          # interrupted, not failed
    resumed = run_batch(batch, path, tool_factory=CrashOnce)
    assert resumed["status"] == "completed"
    by_name = {r["name"]: r["status"] for r in resumed["branches"]}
    assert by_name["b0_fixed_F1"] == by_name["b1_full_F1"] == "skipped_finished"
    assert by_name["b2_llm_F1"] not in ("error", "skipped_finished") and by_name["b3_full_F0"] == "skipped_finished"


def test_batch_estimate_sums_branches_and_cli_gate_runs_offline(checkpoint, tmp_path):
    batch, path = write_batch(tmp_path, checkpoint, "cli", concurrency=2)
    assert estimate_batch(batch).worst_case_usd.sum() == 0   # fake models cost nothing
    env = {**os.environ, "PATH": str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]}
    for command in ("estimate", "check"):
        r = subprocess.run([sys.executable, "-m", "autoagentnet.cli", command, str(path)],
                           env=env, capture_output=True, text=True)
        assert r.returncode == 0, r.stderr + r.stdout


def test_run_child_reports_its_own_cpu_and_stops_at_the_timeout():
    burn = "import time\nt=time.process_time()\nwhile time.process_time()-t<0.3: pass\nprint('ok')"
    code, out, _, cpu, timed_out = run_child([sys.executable, "-c", burn], dict(os.environ), 30)
    assert code == 0 and out.strip() == "ok" and cpu >= 0.25 and not timed_out
    code, _, _, cpu, timed_out = run_child([sys.executable, "-c", "while True: pass"], dict(os.environ), 0.5)
    assert timed_out and code != 0 and cpu > 0.1


def test_branch_artifacts_are_linked_and_a_branch_write_leaves_the_checkpoint_intact(checkpoint, tmp_path):
    from autoagentnet.phoenix.checkpoint import branch_checkpoint
    from autoagentnet.phoenix.store import file_sha
    raw = branch_checkpoint(checkpoint, tmp_path / "branch")
    name = next(n for n in raw["inventory"] if n.endswith(".joblib"))
    source, linked = checkpoint / "artifacts" / name, tmp_path / "branch" / "artifacts" / name
    assert os.stat(source).st_ino == os.stat(linked).st_ino   # no second copy on disk
    before = file_sha(source)
    pending = linked.with_suffix(".pending")                  # the store's write: temp file, then os.replace
    pending.write_bytes(b"a branch's new payload")
    os.replace(pending, linked)
    assert file_sha(source) == before and file_sha(linked) != before
