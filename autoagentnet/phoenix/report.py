"""Source-backed reports and replay HTML; never creates fictional effect sizes."""
from __future__ import annotations

import html
import json
from pathlib import Path

import pandas as pd

from .store import atomic_json


def replay(run_dir, destination):
    root = Path(run_dir)
    status = json.loads((root / "status.json").read_text())
    state = json.loads((root / "state.json").read_text())
    payload = {"status": status, "events": state["events"], "trajectory": state["trajectory"],
               "graph": state["graph"]}
    # Escape raw script delimiters even for adversarial text in a model-generated reason.
    data = json.dumps(payload, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    page = '''<!doctype html><html lang="zh"><meta charset="utf-8"><title>PHOENIX replay</title>
<style>body{font:16px system-ui;background:#101821;color:#e5eef5;max-width:1100px;margin:32px auto;padding:0 20px}
button,input{font:inherit}button{padding:8px 16px;background:#89e0bb;border:0;border-radius:8px}
pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#182735;padding:18px;border-radius:10px}
.cards{display:flex;gap:16px;flex-wrap:wrap}.card{background:#182735;padding:16px;border-radius:10px}
label{display:block;margin:20px 0}input{width:100%}small{color:#a9bdcc}</style>
<h1>PHOENIX · 真实日志回放</h1><p id="fixture"></p><p>Replay：此页面读取已有事件，不发起新的模型调用。</p>
<div class="cards" id="summary"></div><label>事件 <span id="counter"></span><input type="range" id="slider" min="0"></label>
<button id="prev">上一步</button> <button id="next">下一步</button><h2 id="title"></h2><pre id="event"></pre>
<h2>工作流依赖</h2><pre id="graph"></pre><small>边来自 operation 的实际 parents；建议来源使用 evidence_links，不改变计算有效性。</small>
<script id="payload" type="application/json">__DATA__</script><script>
const d=JSON.parse(document.getElementById('payload').textContent),s=document.getElementById('slider');
s.max=Math.max(0,d.events.length-1);let i=0;
document.getElementById('fixture').textContent=d.status.offline_fixture?'离线协议测试 fixture；不能作为实验效果证据。':'已记录运行；效果需结合完整配对结果解释。';
for(const [key,value] of Object.entries({状态:d.status.status,方法:d.status.policy,故障:d.status.fault,验证分数:d.status.validation_score})){
 const e=document.createElement('div');e.className='card';e.textContent=key+'：'+value;document.getElementById('summary').appendChild(e);}
function render(){s.value=i;const e=d.events[i]||{};document.getElementById('counter').textContent=(i+1)+' / '+d.events.length;
 document.getElementById('title').textContent=e.event||'没有事件';document.getElementById('event').textContent=JSON.stringify(e,null,2);}
s.oninput=()=>{i=Number(s.value);render()};document.getElementById('next').onclick=()=>{i=Math.min(d.events.length-1,i+1);render()};
document.getElementById('prev').onclick=()=>{i=Math.max(0,i-1);render()};
document.getElementById('graph').textContent=Object.entries(d.graph.operations).map(([k,v])=>k.slice(0,12)+' '+v.kind+' ← '+v.parents.map(x=>x.slice(0,12)).join(', ')).join('\\n');render();
</script></html>'''.replace("__DATA__", data)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(page)


def aggregate(manifest_path, evaluation_csv, out_dir):
    """Pair by case and budget; absence/failure is a row, never silently dropped."""
    manifest = json.loads(Path(manifest_path).read_text())
    evaluations = pd.read_csv(evaluation_csv) if evaluation_csv else pd.DataFrame()
    rows = []
    for branch in manifest["branches"]:
        status_file = Path(branch["frozen"]).with_name("status.json")
        row = {k: branch[k] for k in ("name", "case_id", "experiment", "policy", "fault", "budget")}
        row["draw"] = branch.get("draw", 0)  # replicate draw (family arms); 0 = the single draw of the main study
        if status_file.exists():
            status = json.loads(status_file.read_text())
            row.update(status=status["status"], logical_api_usd=status.get("budget", {}).get("api_spent"),
                       new_api_bill_usd=status.get("new_api_bill_usd"),
                       cpu_s=status.get("budget", {}).get("cpu_spent"),
                       validation_score=status.get("validation_score"), offline_fixture=status.get("offline_fixture"))
            if status_file.with_name("recovery_plan.json").exists():
                from .metrics import branch_metrics
                row.update(branch_metrics(status_file.parent))
        else:
            row["status"] = "not_run"
        rows.append(row)
    frame = pd.DataFrame(rows)
    if not evaluations.empty:
        if "name" not in evaluations:
            raise ValueError("evaluation table requires branch name")
        if evaluations.name.duplicated().any():
            raise ValueError("duplicate evaluation rows")
        frame = frame.merge(evaluations[["name", "test_balanced_accuracy"]], on="name", how="left", validate="one_to_one")
    target = Path(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    frame.to_csv(target / "branches.csv", index=False)
    if "test_balanced_accuracy" in frame:
        paired = frame.pivot(index=["case_id", "experiment", "fault", "budget", "draw"],
                             columns="policy", values="test_balanced_accuracy")
        for comparator in ("fixed", "llm", "static", "no_dependency", "no_cost"):
            if "full" in paired and comparator in paired:
                paired["full_minus_"+comparator] = paired["full"]-paired[comparator]
        paired.to_csv(target / "paired.csv")
        differences = [c for c in paired if c.startswith("full_minus_")]
        if differences:
            long = paired[differences].reset_index().melt(
                id_vars=["case_id", "experiment", "fault", "budget", "draw"], var_name="comparison", value_name="difference")
            long["dataset"] = long.case_id.str.split("_T").str[0]
            long["win"] = long.difference.gt(0)
            long["tie"] = long.difference.eq(0)
            long["loss"] = long.difference.lt(0)
            long.groupby(["dataset", "experiment", "fault", "budget", "comparison"], dropna=False).agg(
                n=("difference", "count"), mean=("difference", "mean"), median=("difference", "median"),
                wins=("win", "sum"), ties=("tie", "sum"), losses=("loss", "sum")).to_csv(target / "paired_descriptive.csv")
        controls = frame[frame.experiment.isin(["E1", "E2", "E3"])].pivot(
            index=["case_id", "policy", "budget"], columns="fault", values="test_balanced_accuracy")
        for fault in ("F0", "F1"):
            if "healthy" in controls and fault in controls:
                controls["quality_loss_"+fault] = controls["healthy"]-controls[fault]
        controls.to_csv(target / "fault_losses.csv")
        loss_columns = [c for c in controls if c.startswith("quality_loss_")]
        if loss_columns:
            loss_rows = controls[loss_columns].reset_index().melt(
                id_vars=["case_id", "policy", "budget"], var_name="loss_condition", value_name="quality_loss")
            loss_pairs = loss_rows.pivot(index=["case_id", "budget", "loss_condition"],
                                          columns="policy", values="quality_loss")
            if "fixed" in loss_pairs and "full" in loss_pairs:
                loss_pairs["recovery_specific_benefit"] = loss_pairs["fixed"]-loss_pairs["full"]
            loss_pairs.to_csv(target / "recovery_specific.csv")
        summary = frame.groupby(["experiment", "policy", "fault", "budget"], dropna=False).agg(
            runs=("name", "size"), scored=("test_balanced_accuracy", "count"),
            quality=("test_balanced_accuracy", "mean"), cost=("logical_api_usd", "mean"))
        summary.to_csv(target / "summary.csv")
        # Produce a standalone scientific figure, never an interactive fabricated result.
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(7, 4))
        for policy, part in frame.groupby("policy"):
            ax.scatter(part.logical_api_usd, part.test_balanced_accuracy, label=policy)
        ax.set(xlabel="Future logical API cost (USD)", ylabel="Held-out balanced accuracy")
        ax.set_title("OFFLINE FIXTURE — not experimental evidence" if frame.offline_fixture.fillna(False).any()
                     else "Recorded held-out evaluation")
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(target / "cost_quality.png", dpi=160)
        plt.close(fig)
    else:
        (target / "README.md").write_text("No held-out evaluation supplied. This is an execution-status report, not an effect estimate.\n")
    return frame
