"""A network experiment can run a listed set of task ids (a sealed list), in the list's order; offline."""

from autoagentnet.experiment import ExperimentConfig, select_tasks
from autoagentnet.tasks import load_tasks
from conftest import ROOT


def test_items_file_picks_and_orders_tasks(tmp_path):
    tasks = load_tasks(ROOT / "data/tasks/sample.jsonl")
    ids = [tasks[2].id, tasks[0].id]
    listed = tmp_path / "items.txt"
    listed.write_text("\n".join(ids) + "\n")
    cfg = ExperimentConfig(name="x", network="configs/networks/vote6.yaml", tasks=str(ROOT / "data/tasks/sample.jsonl"),
                           items=str(listed))
    assert [t.id for t in select_tasks(cfg)] == ids
    assert [t.id for t in select_tasks(cfg.model_copy(update={"task_offset": 1}))] == ids[1:]
    plain = cfg.model_copy(update={"items": None, "task_limit": 2})
    assert [t.id for t in select_tasks(plain)] == [t.id for t in tasks[:2]]
