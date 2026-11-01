"""analysis/sos_crossfit.py, offline: a fake-model math branch table, cross-fitted by question-text hash with the
pilot left out, the prereg's decision rule, the diagnostics, and the read rule (unparsed or truncated: wrong, no vote)."""

import asyncio
import hashlib

import pandas as pd

import analysis.sos_crossfit as X
from analysis import self_or_social as A
from autoagentnet.self_or_social import run as R
from autoagentnet.self_or_social.policy import branch_table
from autoagentnet.self_or_social.protocol import grade_reply, vote_answer
from autoagentnet.tasks import Task
from test_self_or_social_run import config


def math_run(tmp_path, n=30):
    tasks = [Task(id=f"arxivmath-0826-{i}", prompt=f"Compute the value number {i}.", answer=str(i % 3), grader="math",
                  meta={"kind": "math", "set": ["arxivmath-0826", "arxivmath-0926"][i % 2]}) for i in range(n)]
    (tmp_path / "tasks.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    (tmp_path / "ids.txt").write_text("\n".join(t.id for t in tasks) + "\n")
    asyncio.run(R.run_sos(config(tmp_path, task_kind="math", full_review=True, chunk_size=30)))
    return {t.id: t for t in tasks}, A.load(str(tmp_path / "out/t/calls.csv"))


def test_question_fold_is_the_last_hex_digit_of_the_text_hash():
    for text in ("a", "b", "Compute 1.", "x" * 50):
        assert X.question_fold(text) == int(hashlib.sha256(text.encode()).hexdigest()[-1], 16) % 2
    assert X.category_of({"task": "nycc"}) == "nycc" and X.category_of({"subset": "SeqQA"}) == "SeqQA"
    assert X.category_of({"kind": "math", "set": "arxivmath-0826"}) == "arxivmath-0826" and X.category_of({}) == "all"


def test_crossfit_fits_on_the_other_fold_and_leaves_the_pilot_out(tmp_path, monkeypatch):
    tasks, calls = math_run(tmp_path)
    seen = []
    real = A.fit_frozen

    def spy(table, team, graders):
        seen.append(set(table["item"]))
        return real(table, team, graders)

    monkeypatch.setattr(A, "fit_frozen", spy)
    rule = X.report(calls, tasks, str(tmp_path / "ids.txt"), pilot=3, name="t", out=tmp_path / "rep", draws=3, boot=200)
    per_item = pd.read_csv(tmp_path / "rep/t_per_item.csv")
    evidence = list(tasks)[3:]  # the frozen order (ids.txt) without its first 3 items
    assert set(per_item["item"]) == set(evidence)  # the 3 pilot items are not evidence
    fold = {i: X.question_fold(tasks[i].prompt) for i in evidence}
    assert (per_item["fold"] == per_item["item"].map(fold)).all()
    assert len(seen) == 2 and all(seen[k].isdisjoint(set(per_item.loc[per_item["fold"] == k, "item"])) for k in (0, 1))
    assert seen[0] | seen[1] == set(evidence)
    methods = set(per_item["method"])
    assert {"vote", "all_reflect", "fixed_peer", "smartest_peer", "policy", "self_only", "forced_social",
            "random_matched", "full_review", "single_A", "single_B", "single_C"} <= methods
    assert per_item.groupby(["item", "method"]).size().max() == 1
    text = (tmp_path / "rep/t_summary.md").read_text()
    assert "## Primary decision (prereg)" in text and "DRY RUN" in text and "Herding" in text
    assert rule["verdict"] in ("policy beats all-reflect", "not resolved")
    contrasts = pd.read_csv(tmp_path / "rep/t_contrasts.csv")
    assert {"all_reflect", "vote", "full_review", "single_C"} <= set(contrasts["baseline"])
    assert set(contrasts["reading"]) <= {"policy higher", "policy lower", "not resolved"}


def per_item_frame(policy_acc, policy_cost, reflect_acc, reflect_cost, n=60):
    rows = []
    for i in range(n):
        rows.append({"item": f"i{i}", "method": "policy", "correct": float(i < policy_acc * n), "cost": policy_cost,
                     "calls": 4})
        rows.append({"item": f"i{i}", "method": "all_reflect", "correct": float(i < reflect_acc * n),
                     "cost": reflect_cost, "calls": 6})
    return pd.DataFrame(rows)


def test_decision_rule():
    assert X.decision(per_item_frame(0.5, 0.01, 0.5, 0.02))["verdict"] == "policy beats all-reflect"
    assert X.decision(per_item_frame(0.5, 0.03, 0.5, 0.02))["verdict"] == "not resolved"  # (a) fails: dearer
    worse = X.decision(per_item_frame(0.3, 0.01, 0.5, 0.02))  # 20 points worse on every draw: (b) fails
    assert worse["verdict"] == "not resolved" and worse["cheaper"] and not worse["within_margin"]
    same = X.decision(per_item_frame(0.5, 0.01, 0.5, 0.02), draws=500)
    assert same["d_acc_lo"] == 0.0 and same["n"] == 60


def test_herding_and_edges():
    acts = pd.DataFrame({"item": ["a", "a", "a", "b", "b", "c"], "receiver": ["A", "B", "C", "A", "B", "A"],
                         "action": ["consult:C", "consult:C", "stop", "consult:B", "consult:A", "reflect"]})
    acts = acts.assign(kind=acts["action"].str.split(":").str[0], sender=acts["action"].str.split(":").str[1])
    herd = X.herding(acts)
    assert herd == {"items_with_2plus_consults": 2, "herded": 1, "rate": 0.5, "items_with_any_consult": 2}
    table = pd.DataFrame({"item": ["a"] * 3, "receiver": ["A"] * 3, "action": ["stop", "reflect", "consult:C"],
                          "kind": ["stop", "reflect", "consult"], "correct": [0.0, 0.0, 1.0]})
    edge = X.edges(table, acts).set_index(["sender", "receiver"])
    assert edge.loc[("C", "A"), "corrections"] == 1 and edge.loc[("C", "A"), "policy_chose"] == 1
    assert edge.loc[("self", "A"), "corrections"] == 0 and edge.loc[("self", "A"), "policy_chose"] == 1


def test_unparsed_and_truncated_answers_are_wrong_and_cast_no_vote():
    item = Task(id="m", prompt="p", answer="2", grader="math")
    cut = grade_reply("math", item, "...\\boxed{2}", stop_reason="max_tokens")
    assert cut == {"answer": None, "parsed": False, "correct": 0.0, "prob": None}
    assert vote_answer("math", "...\\boxed{2}", "max_tokens") is None and vote_answer("math", "\\boxed{2}") == "2"
    unknown = grade_reply("math", item, "\\boxed{\\text{unknown}}")
    assert unknown["answer"] is not None and not unknown["parsed"] and unknown["correct"] == 0.0  # text kept, no vote
    assert vote_answer("math", "\\boxed{\\text{unknown}}") is None
    assert vote_answer("mcq", "ANSWER: B", "length") is None and vote_answer("bbeh", "ANSWER: x", "max_tokens") == "x"
    calls = pd.DataFrame({"item": "m", "family": None, "grader": "math", "position": [0, 1, 2],
                          "receiver": ["A", "B", "C"], "action": "initial", "cost_usd": 0.0,
                          "answer": ["\\text{unknown}", "\\text{unknown}", "3"], "parsed": [False, False, True],
                          "correct": [0.0, 0.0, 0.0]})
    table = branch_table(calls)
    assert table["answer"].isna().tolist() == [True, True, False]
    assert table.set_index("receiver")["state"].to_dict() == {"A": "none", "B": "none", "C": "split"}
