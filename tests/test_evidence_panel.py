"""The panel runner (step 0.7), offline on the fake model: rows per call, vendor split, second calls on a
subset, aggregators, estimates, stop rules and the governed path."""

import asyncio

import pandas as pd
import pytest

from autoagentnet.evidence.panel import (PanelConfig, PanelExpect, PanelSource, estimate_panel, expectation_misses,
                                         item_problems, preflight_panel, run_panel)
from autoagentnet.tasks import Task
from conftest import ROOT


def write_items(tmp_path, kind="bbeh", n=4):
    tasks = []
    for i in range(n):
        if kind == "forecast":
            meta = {"kind": "forecast", "source": "polymarket", "market": True, "freeze_value": 0.4}
            tasks.append(Task(id=f"q{i}", prompt=f"Question {i}\nMarket price at freeze: 0.40", answer=str(i % 2), meta=meta))
        else:
            tasks.append(Task(id=f"b{i}", prompt=f"Puzzle {i}", answer="yes", grader="bbeh",
                              meta={"kind": "bbeh", "task": "web of lies", "position": 140 + i}))
    (tmp_path / "tasks.jsonl").write_text("".join(t.model_dump_json() + "\n" for t in tasks))
    (tmp_path / "ids.txt").write_text("\n".join(t.id for t in tasks) + "\n")
    (tmp_path / "two.txt").write_text("".join(t.id + "\n" for t in tasks[:2]))
    return tasks


def config(tmp_path, kind="bbeh", sources=None, **extra) -> PanelConfig:
    sources = sources or [PanelSource(ref="haiku_nothink", calls=5), PanelSource(ref="sonnet_nothink", calls=1),
                          PanelSource(ref="sonnet_nothink", calls=1, first_call=1, items=str(tmp_path / "two.txt"))]
    extra = {"model_override": "fake", **extra}
    return PanelConfig(kind="panel", name="t", task_kind=kind, tasks=str(tmp_path / "tasks.jsonl"),
                       items=str(tmp_path / "ids.txt"), sources=sources,
                       out_dir=str(tmp_path / "out"), providers=str(ROOT / "configs/providers.yaml"),
                       pricing=str(ROOT / "configs/pricing.yaml"), budget=str(ROOT / "configs/budget.yaml"),
                       ledger=str(tmp_path / "ledger.jsonl"), require_ledger=False, git_checkpoint=False, **extra)


def test_dry_run_writes_one_row_per_call(tmp_path):
    write_items(tmp_path)
    rows, status = asyncio.run(run_panel(config(tmp_path, chunk_size=2)))
    assert status["state"] == "completed" and status["vendor"] == "anthropic"
    assert len(rows) == 4 * 5 + 4 + 2  # 5 Haiku and 1 Sonnet call per item, a second Sonnet call on 2 items
    sonnet = rows[rows["ref"] == "sonnet_nothink"]
    assert sorted(sonnet.loc[sonnet["call"] == 1, "item"]) == ["b0", "b1"]
    expected = {"item", "source", "ref", "model", "setting", "prompt", "call", "answer", "parsed", "correct",
                "output_tokens", "cost_usd", "seconds", "model_version", "truncated", "meta_position", "reply"}
    assert expected <= set(rows.columns)
    assert rows.loc[rows["ref"] == "haiku_nothink", "setting"].iloc[0] == '{"thinking": {"type": "disabled"}}'
    on_disk = pd.read_csv(tmp_path / "out/t/calls.csv")
    assert len(on_disk) == len(rows) and not (tmp_path / "ledger.jsonl").exists()  # a dry run spends and records nothing
    again, _ = asyncio.run(run_panel(config(tmp_path)))  # deterministic
    assert again.sort_values(["item", "source", "call"])["reply"].tolist() == rows.sort_values(["item", "source", "call"])["reply"].tolist()


def test_calls_of_one_source_are_distinct_samples(tmp_path):
    write_items(tmp_path, n=1)
    rows, _ = asyncio.run(run_panel(config(tmp_path, sources=[PanelSource(ref="haiku_nothink", calls=5)])))
    assert sorted(rows["call"]) == [0, 1, 2, 3, 4]


def test_a_run_calls_one_vendor(tmp_path):
    write_items(tmp_path)
    mixed = config(tmp_path, sources=[PanelSource(ref="haiku_nothink"), PanelSource(ref="luna_none")])
    assert any("one vendor" in p for p in item_problems(mixed))
    with pytest.raises(ValueError, match="one vendor"):
        asyncio.run(run_panel(mixed))


def test_forecast_rows_carry_outcome_and_probability(tmp_path):
    write_items(tmp_path, kind="forecast")
    rows, status = asyncio.run(run_panel(config(tmp_path, kind="forecast", sources=[PanelSource(ref="luna_none", calls=2)])))
    assert status["vendor"] == "openai"
    assert set(rows["outcome"]) == {0, 1} and rows["correct"].isna().all()
    assert rows.loc[rows["parsed"], "prob"].between(0.01, 0.99).all()


def test_aggregator_reads_the_panel_without_model_names(tmp_path):
    write_items(tmp_path)
    panel, _ = asyncio.run(run_panel(config(tmp_path)))
    agg = config(tmp_path, sources=[PanelSource(ref="haiku_nothink", prompt="aggregator")],
                 panel_results=[str(tmp_path / "out/t/calls.csv")],
                 panel_sources={"haiku_nothink:base": 5, "sonnet_nothink:base": 1})
    agg = agg.model_copy(update={"name": "agg"})
    from autoagentnet.evidence.panel import panel_answers
    assert {len(a) for a in panel_answers(agg).values()} == {6}  # Sonnet's second call is not shown
    rows, _ = asyncio.run(run_panel(agg))
    assert len(rows) == 4 and rows["prob"].notna().any()
    assert item_problems(agg.model_copy(update={"panel_results": []}))  # an aggregator needs the panel


def test_estimate_covers_every_call_and_check_refuses_without_prereg(tmp_path):
    write_items(tmp_path)
    cfg = config(tmp_path, model_override=None)
    table = estimate_panel(cfg)
    assert int(table["calls"].sum()) == 26
    assert table.loc[("anthropic", "claude-sonnet-5-5"), "worst_case_usd"] > table.loc[("anthropic", "claude-haiku-5-5"), "worst_case_usd"]
    problems, _ = preflight_panel(cfg, tmp_path / "not_committed.yaml")
    assert any("prereg" in p for p in problems) and any("commit" in p for p in problems)


def test_stop_rules_per_source():
    calls = pd.DataFrame({"source": ["a:base"] * 20 + ["b:base"] * 20, "ref": ["a"] * 20 + ["b"] * 20,
                          "parsed": [True] * 18 + [False] * 2 + [True] * 20, "truncated": [False] * 40,
                          "cost_usd": [0.001] * 20 + [0.004] * 20, "from_cache": [False] * 40})
    misses = expectation_misses(calls, PanelExpect(usd_per_call={"b": 0.002}))
    assert any("a:base replies unparsed" in m for m in misses) and any("b:base costs" in m for m in misses)
    refused = calls.assign(stop_reason=["end_turn"] * 18 + ["refusal"] * 2 + ["end_turn"] * 20)
    msg = [m for m in expectation_misses(refused, PanelExpect()) if "a:base" in m][0]
    assert "2 of 20 refused" in msg and "0.0% unparsed without them" in msg  # a refusals-only stop says so (audit 54)
    assert expectation_misses(calls.assign(from_cache=True), PanelExpect()) == []  # cached calls are not judged


def test_math_abstentions_are_counted_apart_from_the_unparsed_rate():
    """Audit 88: an unparsed math answer that says the value is not known is not a format failure; the same text on
    another task kind, or an unparsed math answer that does not abstain, still counts. Made-up answers."""
    answers = ["\\text{unknown}", "\\text{open problem}", "\\text{not presently known}", "7"] + ["5"] * 16
    calls = pd.DataFrame({"source": ["a:base"] * 20, "ref": ["a"] * 20, "task_kind": ["math"] * 20, "answer": answers,
                          "parsed": [False] * 3 + [True] * 17, "truncated": [False] * 20, "cost_usd": [0.001] * 20,
                          "from_cache": [False] * 20})
    expect = PanelExpect(max_unparsed_rate=0.05)
    assert expectation_misses(calls, expect) == []  # 3 abstentions, 0 other unparsed
    shape = calls.assign(parsed=[False] * 4 + [True] * 16)  # "7" unparsed (made up): 1 of 20 counts, within 5%
    assert expectation_misses(shape, expect) == []
    two = shape.assign(parsed=[False] * 5 + [True] * 15)
    msg = expectation_misses(two, expect)[0]
    assert "10.0% of a:base replies unparsed" in msg and "3 math abstentions not counted" in msg
    assert expectation_misses(calls.assign(task_kind="bbeh"), expect)  # only math answers abstain


def test_a_paid_run_refuses_under_another_budget_phase(tmp_path):
    write_items(tmp_path)
    cfg = config(tmp_path, model_override=None, phase="no_such_phase")
    problems, _ = preflight_panel(cfg, tmp_path / "x.yaml")
    assert any("active phase" in p for p in problems)
    dry = config(tmp_path, phase="no_such_phase")  # dry runs spend nothing and are not refused for the phase
    assert not any("active phase" in p for p in preflight_panel(dry, tmp_path / "x.yaml")[0])


def test_a_paid_run_refuses_until_its_required_files_are_committed(tmp_path):
    """The Phase 3C lockbox runs require research/v3/pruning/selected.json, frozen and committed first."""
    write_items(tmp_path)
    missing = str(tmp_path / "selected.json")
    cfg = config(tmp_path, model_override=None, requires=[missing, "pyproject.toml"])
    problems, _ = preflight_panel(cfg, tmp_path / "x.yaml")
    assert any(missing in p and "committed" in p for p in problems)
    assert not any("pyproject.toml" in p for p in problems)  # tracked and unchanged
    dry = config(tmp_path, requires=[missing])  # a dry run is not refused
    assert not any("committed" in p for p in preflight_panel(dry, tmp_path / "x.yaml")[0])


def test_judge_sees_distinct_candidates_and_self_check_grades_its_verdict(tmp_path):
    """Session E5 verification arms: a judge picks among the distinct earlier answers; a self-check's row says whether
    its verdict on the checked source's call 0 was right. Both record VERIFY_HASH, and TEMPLATE_HASH is unchanged."""
    from autoagentnet.evidence import prompts as P
    from autoagentnet.evidence.panel import distinct_answers, requests_for, select_items

    write_items(tmp_path)
    asyncio.run(run_panel(config(tmp_path)))
    calls = str(tmp_path / "out/t/calls.csv")
    judge = config(tmp_path, sources=[PanelSource(ref="haiku_nothink", prompt="judge")], panel_results=[calls],
                   panel_sources={"haiku_nothink:base": 5}).model_copy(update={"name": "judge"})
    jobs = requests_for(judge, select_items(judge),
                        {"haiku_nothink": "fake"})
    assert jobs and all("CANDIDATES:" in r.input.task and "Choose the candidate" in r.spec.instruction for *_, r in jobs)
    rows, _ = asyncio.run(run_panel(judge))
    assert (rows["template_hash"] == P.VERIFY_HASH).all() and rows["prob"].notna().any()
    check = config(tmp_path, sources=[PanelSource(ref="haiku_nothink", prompt="self_check", checks="haiku_nothink:base")],
                   panel_results=[calls]).model_copy(update={"name": "check"})
    rows, _ = asyncio.run(run_panel(check))
    parsed = rows[rows["parsed"]]
    assert set(parsed["answer"]) <= {"correct", "incorrect"} and len(parsed)
    agree = (parsed["answer"] == "correct") == (parsed["checked_correct"] == 1.0)
    assert (parsed["correct"] == agree.astype(float)).all()
    assert item_problems(check.model_copy(update={"sources": [PanelSource(ref="haiku_nothink", prompt="self_check")]}))
    assert distinct_answers(["(A)", "(a)", None, "B"], "bbeh") == ["(A)", "B"]
    assert P.parse_verdict("x\nVERDICT: incorrect\nCONFIDENCE: 0.2") == "incorrect"
    assert P.TEMPLATE_HASH == "918df73fdf01cefc" and P.VERIFY_HASH != P.TEMPLATE_HASH  # earlier cache keys hold


def test_parser_v2_grades_bare_answers_of_any_shape_and_v1_is_unchanged():
    """Audit 69: the anchor's parser v2 accepts a short bare last line; v1 (every earlier run) does not; format
    compliance is recorded apart."""
    from autoagentnet.evidence import prompts as P

    for reply, v1, v2 in [("1,0,0", None, "1,0,0"), ("work\n\ngrape", None, "grape"), ("ABD, AB, AB", None, "ABD, AB, AB"),
                          ("x\nANSWER: (B)", "(B)", "(B)"), ("46", "46", "46"),
                          ("x\nANSWER: Yes—sufficient, but not necessary.", "Yes—sufficient, but not necessary", "Yes"),
                          ("ANSWER: (C) He heated up fish.", "(C) He heated up fish", "(C)"),
                          ("ANSWER: I hugged you (plural).", "I hugged you (plural)", "I hugged you"),
                          ("ANSWER: (H) or (A)", "(H) or (A)", "(H) or (A)")]:
        assert P.parse_answer("bbeh", reply) == v1 and P.parse_answer("bbeh", reply, "v2") == v2, reply
    long_list = "work\n" + " ".join(["word"] * 40)  # a bare answer longer than 60 characters (word sorting)
    assert P.parse_answer("bbeh", long_list) is None and P.parse_answer("bbeh", long_list, "v2") == " ".join(["word"] * 40)
    from autoagentnet.evidence.panel import grade
    gold = Task(id="g", prompt="p", answer="sweet (adj.)", grader="bbeh", meta={"task": "linguini"})
    assert grade("bbeh", "base", gold, "ANSWER: sweet (adj.)", "end_turn", None, "v2")["correct"] == 1.0  # gold stripped too
    assert grade("bbeh", "base", gold, "ANSWER: sweet", "end_turn", None, "v2")["correct"] == 1.0
    assert P.format_ok("bbeh", "x\nANSWER: 3") and not P.format_ok("bbeh", "1,0,0")
    assert P.parse_answer("math", "\\boxed{3}", "v2") == "3"


def test_stop_rules_can_count_every_slice_of_a_config(tmp_path):
    """Audit 71: with stop_over_config, a source with few calls per slice is checked over all slices so far."""
    write_items(tmp_path, n=4)
    strict = PanelExpect(min_calls=3, max_unparsed_rate=0.0, max_truncation_rate=None)
    base = config(tmp_path, sources=[PanelSource(ref="haiku_nothink", calls=1)], expect=strict, chunk_size=10)
    first, _ = asyncio.run(run_panel(base.model_copy(update={"task_offset": 0, "task_limit": 2})))
    # make the first slice's calls look unparsed on disk, then run the second slice
    on_disk = pd.read_csv(tmp_path / "out/t/calls.csv")
    on_disk["parsed"] = False
    on_disk.to_csv(tmp_path / "out/t/calls.csv", index=False)
    second = base.model_copy(update={"task_offset": 2, "task_limit": 2})
    _, alone = asyncio.run(run_panel(second))
    assert alone["state"] == "completed"  # 2 calls of this slice: under min_calls, not checked
    on_disk.to_csv(tmp_path / "out/t/calls.csv", index=False)
    _, over = asyncio.run(run_panel(second.model_copy(update={"stop_over_config": True})))
    assert over["state"] == "stopped" and "unparsed" in over["reason"]


def test_parser_v21_label_first_marks_and_parentheticals():
    """Audit 72: on a closed-label task a leading label before a comma, period or colon is the answer; curly and straight
    apostrophes are one mark; a trailing parenthetical goes before any split; hedges stay whole."""
    from autoagentnet.evidence import prompts as P
    from autoagentnet.evidence.panel import grade

    labels = ["Ambiguous", "No", "Yes"]
    assert P.strip_qualifier_v21("No, the neighbor's inaction is not sufficient", labels) == "No"
    assert P.strip_qualifier_v21("Yes. Because", labels) == "Yes" and P.strip_qualifier_v21("Not sure", labels) == "Not sure"
    assert P.strip_qualifier_v21("Yes or No", labels) == "Yes or No"
    assert P.strip_qualifier_v21("an awl (a piercing tool; maybe a needle)") == "an awl"
    gold = Task(id="g", prompt="p", answer="kas deka:ka’", grader="bbeh", meta={"task": "linguini"})
    assert grade("bbeh", "base", gold, "ANSWER: kas deka:ka'", "end_turn", None, "v2.1")["correct"] == 1.0
    assert grade("bbeh", "base", gold, "ANSWER: kas deka:ka'", "end_turn", None, "v2")["correct"] == 0.0  # v2 unchanged
    causal = Task(id="c", prompt="p", answer="No", grader="bbeh", meta={"task": "causal understanding"})
    assert grade("bbeh", "base", causal, "ANSWER: No, it is not necessary", "end_turn", None, "v2.1", labels)["correct"] == 1.0


def test_judge_pick_reads_the_answer_line_and_maps_candidate_numbers():
    """Audit 75: a judge's pick is its ANSWER line, "Candidate k" is the k-th candidate as shown, and on math no
    \\boxed in the working overrides the ANSWER line; without an ANSWER line the usual parse applies. The judge prompt
    is unchanged (the shown order is the one judge_task prints)."""
    import hashlib

    from autoagentnet.evidence import prompts as P
    from autoagentnet.evidence.panel import grade, shown_candidates

    cands = ["Yes", "No", "Ambiguous"]
    old_order = sorted(range(3), key=lambda i: hashlib.sha256(f"seed:judge:{i}".encode()).hexdigest())
    assert P.judge_order(3, "seed") == old_order
    shown = shown_candidates(["Yes", "yes", None, "No", "Ambiguous"], "bbeh", "seed")
    block1, _ = P.judge_task("bbeh", "T", cands, "seed")
    assert block1 == "T\n\nCANDIDATES:\n" + "\n".join(f"Candidate {k}: {c}" for k, c in enumerate(shown, 1))
    assert P.judge_reply("bbeh", "w\nANSWER: Candidate 2\nCONFIDENCE: 0.6", shown) == f"ANSWER: {shown[1]}"
    assert P.judge_reply("bbeh", "ANSWER: **Candidate 3:** whatever", shown) == f"ANSWER: {shown[2]}"
    assert P.judge_reply("bbeh", "ANSWER: Candidate 7", shown) == "ANSWER: Candidate 7"  # no 7th: kept as written
    assert P.judge_reply("bbeh", "No final line", shown) == "No final line"
    assert P.parse_answer("math", P.judge_reply("math", "\\boxed{3} is wrong\nANSWER: 5", ["3", "5"])) == "5"
    # audit 76's edges: a hedge between candidates is kept (graded wrong); a bare last line naming a candidate is a
    # pick; a candidate's line breaks become spaces, so the whole candidate is the pick
    assert P.judge_reply("bbeh", "ANSWER: Candidate 1 or Candidate 2", shown) == "ANSWER: Candidate 1 or Candidate 2"
    assert P.judge_reply("bbeh", "work\n**Candidate 2**", shown) == f"ANSWER: {shown[1]}"
    assert P.judge_reply("bbeh", "work\nCandidate 2\nCONFIDENCE: 0.7", shown) == f"ANSWER: {shown[1]}"  # audit 77
    assert P.judge_reply("math", "ANSWER: Candidate 1", ["x + 1\n= 2", "3"]) == "ANSWER: x + 1 = 2"
    item = Task(id="seed", prompt="p", answer=shown[1], grader="bbeh", meta={"task": "causal understanding"})
    g = grade("bbeh", "judge", item, "w\nANSWER: Candidate 2\nCONFIDENCE: 0.6", "end_turn", None, "v2", shown=shown)
    assert g["answer"] == shown[1] and g["correct"] == 1.0 and g["prob"] == 0.6
    assert grade("bbeh", "judge", item, "w\nANSWER: Candidate 2\nCONFIDENCE: 0.6", "end_turn", None, "v2")["correct"] == 0.0


def test_boxed_labels_are_read_as_plain_lines():
    """Audit 93: under the math system prompt Sol boxes its final lines. A boxed confidence is read (forms A and B), a
    number already after the label keeps being read, a boxed ANSWER label or a pick naming a candidate inside \\text{}
    is read as the plain line, and a boxed confidence is never read as a pick. Made-up replies."""
    from autoagentnet.evidence import prompts as P

    assert P.parse_confidence("VERDICT: correct\nCONFIDENCE: \\(\\boxed{0.99}\\)") == 0.99  # form A
    assert P.parse_confidence("VERDICT: correct\n\\(\\boxed{\\text{CONFIDENCE: }0.93}\\)") == 0.93  # form B
    assert P.parse_confidence("\\boxed{\\text{CONFIDENCE: }0.95}") == 0.95
    assert P.parse_confidence("CONFIDENCE: 0.90 \\(\\boxed{2}\\)") == 0.90  # the number right after the label
    assert P.parse_confidence("CONFIDENCE: 0.7") == 0.7 and P.parse_confidence("**Confidence:** 85%") == 0.85
    assert P.parse_verdict("VERDICT: \\boxed{\\text{incorrect}}") == "incorrect"
    shown = ["17", "\\frac{1}{2}", "x+1"]
    pick = lambda text: P.parse_answer("math", P.judge_reply("math", text, shown))
    assert pick("work\nANSWER: \\(\\boxed{\\text{Candidate 2}}\\)\nCONFIDENCE: 0.8") == "\\frac{1}{2}"
    assert pick("work\n\\boxed{\\text{ANSWER: }17}\nCONFIDENCE: 0.8") == "17"
    assert pick("work\n\\boxed{\\text{ANSWER: Candidate 2}}") == "\\frac{1}{2}"
    assert pick("work\nANSWER: \\(\\boxed{17}\\)\nCONFIDENCE: 0.8") == "17"
    assert pick("work, so \\boxed{5}\nCONFIDENCE: \\(\\boxed{0.9}\\)") == "5"  # not 0.9
    assert pick("work, so \\boxed{5}\n\\(\\boxed{\\text{CONFIDENCE: }0.9}\\)") == "5"
    assert P.judge_reply("bbeh", "No final line", shown) == "No final line"


def test_code_kind_records_the_program_and_leaves_the_grade_to_the_read():
    """Study CD (session E6): a code reply's answer is its last ```python block, parsed when there is one, and its
    grade is None at run time (the read runs the hidden tests). The code templates are outside TEMPLATE_HASH, which
    keeps the value every earlier run recorded. Made-up replies."""
    import asyncio

    from autoagentnet.evidence import prompts as P
    from autoagentnet.evidence.panel import FakePanelClient, grade
    from autoagentnet.providers.base import Block, LLMRequest

    item = Task(id="lcb-x", prompt="Print 1.", answer=None, grader="exact", meta={})
    g = grade("code", "base", item, "Plan.\n```python\nprint(1)\n```")
    assert g["answer"] == "print(1)\n" and g["parsed"] and g["correct"] is None
    assert not grade("code", "base", item, "I think it is 1.")["parsed"]
    assert P.format_ok("code", "```python\nx=1\n```") and not P.format_ok("code", "no code")
    assert P.TEMPLATE_HASH == "918df73fdf01cefc" and len(P.CODE_HASH) == 16
    assert P.SYSTEMS["code"] == P.CODE_SYSTEM and P.instruction("code", "base") == P.CODE_INSTRUCTION
    reply = asyncio.run(FakePanelClient().complete(LLMRequest(model="fake-model", system=P.CODE_SYSTEM,
                                                              blocks=[Block(text="t")], max_tokens=10)))
    assert grade("code", "base", item, reply.text)["parsed"] or "not sure" in reply.text


def test_code_judge_sees_whole_programs_and_its_pick_is_the_program():
    """Study CD tier B: a judge over code candidates sees each program whole in its own block; its pick ("Candidate k")
    becomes that program, so the code parser reads the picked program; a hedge or no pick is no program."""
    from autoagentnet.evidence import prompts as P
    from autoagentnet.evidence.panel import grade

    programs = ["print(1)\n", "x = 2\nprint(x)\n"]
    block1, _ = P.judge_task("code", "Print a number.", programs, seed="lcb-x")
    order = P.judge_order(2, "lcb-x")
    shown = [programs[i] for i in order]
    assert "Candidate 1:\n```python\n" in block1 and shown[1].strip() in block1
    item = Task(id="lcb-x", prompt="Print a number.", answer=None, grader="exact", meta={})
    g = grade("code", "judge", item, "Reasoning.\nANSWER: Candidate 2\nCONFIDENCE: 0.7", shown=shown)
    assert g["answer"].strip() == shown[1].strip() and g["parsed"]
    assert not grade("code", "judge", item, "ANSWER: Candidate 1 or Candidate 2\nCONFIDENCE: 0.5", shown=shown)["parsed"]
    copied = f"I pick this one.\n```python\n{shown[0]}```\nCONFIDENCE: 0.6"  # audit 105: a copied program is a pick
    assert grade("code", "judge", item, copied, shown=shown)["answer"].strip() == shown[0].strip()
    assert not grade("code", "judge", item, "```python\nprint(3)\n```", shown=shown)["parsed"]  # a new program is not
    assert P.judge_reply("bbeh", "ANSWER: Candidate 1", ["(A)"]) == "ANSWER: (A)"  # other kinds unchanged
