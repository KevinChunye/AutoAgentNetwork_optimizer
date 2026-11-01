"""Build the handoff-completeness item list and derived tasks from stored calls ($0; prereg:
research/handoff_completeness/prereg.md). Writes research/handoff_completeness/items.txt (+ sha256 printed) and
data/handoff/<set>_<condition>.{jsonl,txt} plus data/handoff/leaks.csv."""
import glob
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "analysis"))
from autoagentnet.handoff import build as B  # noqa: E402
from autoagentnet.tasks import load_tasks  # noqa: E402
import self_or_social as S  # noqa: E402

OUT = ROOT / "data/handoff"
dev = [l.strip() for l in open(ROOT / "research/self_or_social/sealed/dev.txt") if l.strip()]
bbeh = {t.id: t for t in load_tasks(ROOT / "data/external/bbeh_all.jsonl") if t.id in set(dev)}
c = pd.read_csv(ROOT / "results/e51_sonnet_bbeh/calls.csv", low_memory=False)
c = c[(c["ref"] == "sonnet_nothink") & (c["call"] == 0)]
bbeh_traces = c.drop_duplicates("item").set_index("item")["reply"].astype(str).to_dict()

refused = set()
for f in glob.glob(str(ROOT / "results/sos_lab_*/calls.csv")):
    x = S.load(f)
    refused |= set(x[S.refused_mask(x)]["item"])
lab_ids = [l.strip() for p in ("dev", "test") for l in open(ROOT / f"research/self_or_social_shortlist/labbench_sealed/{p}.txt") if l.strip()]
lab_ok = [i for i in lab_ids if i not in refused]
lab = {t.id: t for t in load_tasks(ROOT / "data/external/lab_bench/labbench_mcq.jsonl") if t.id in set(lab_ok)}
lab_traces = {}
for p in ("dev", "test"):
    x = pd.read_csv(ROOT / f"results/sos_lab_claude2_{p}/calls.csv")
    x = x[(x["receiver"] == "C") & (x["action"] == "initial")]
    lab_traces.update(x.set_index("item")["reply"].astype(str).to_dict())

items = sorted(bbeh) + sorted(lab)
missing = [i for i in sorted(bbeh) if i not in bbeh_traces] + [i for i in sorted(lab) if i not in lab_traces]
assert not missing, missing[:3]
ids_text = "".join(i + "\n" for i in items)
(ROOT / "research/handoff_completeness").mkdir(parents=True, exist_ok=True)
(ROOT / "research/handoff_completeness/items.txt").write_text(ids_text)
import hashlib
print("items", len(bbeh), "BBEH +", len(lab), "LAB-Bench (", len(refused & set(lab_ids)), "refused excluded ) sha256",
      hashlib.sha256(ids_text.encode()).hexdigest())
stop_ids = B.stratified(items, 60)
leaks = []
for name, tasks, traces, kind in (("bbeh", bbeh, bbeh_traces, "bbeh"), ("lab", lab, lab_traces, "mcq")):
    rows = B.build([tasks[i] for i in sorted(tasks)], traces, kind, stop_ids)
    for cond, rr in rows.items():
        sha = B.write(rr, OUT / f"{name}_{cond}.jsonl", OUT / f"{name}_{cond}.txt")
        print(name, cond, len(rr), "tasks, id sha256", sha[:16], "leaked", sum(r["leaked"] for r in rr))
        leaks += [{"set": name, "condition": cond, "item": r["item"], "f": r["f"], "leaked": r["leaked"],
                   "mentions": r.get("mentions", False)} for r in rr]
pd.DataFrame(leaks).to_csv(OUT / "leaks.csv", index=False)
(OUT / "stop_subset.txt").write_text("".join(i + "\n" for i in stop_ids))
