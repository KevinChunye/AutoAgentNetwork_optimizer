"""Frozen prompts, reply parsers (five hand-made edge cases per task) and loaders of the evidence plan
(steps 0.5 and 0.6); offline."""

from datetime import date

import pandas as pd
import pytest
import yaml

from autoagentnet.evidence import prompts as P
from autoagentnet.evidence.loaders import bbeh_items, forecast_task, forecastbench_frame, matharena_items
from autoagentnet.tasks import answers_match
from conftest import ROOT


def test_bbeh_prompt_is_the_pilots_single_agent_prompt():
    single = yaml.safe_load((ROOT / "configs/networks/single.yaml").read_text())["stages"][0]
    assert P.BBEH_SYSTEM == single["system"] and P.BBEH_INSTRUCTION == single["instruction"]


@pytest.mark.parametrize("reply, gold, right", [
    ("Steps...\nANSWER: yes, no, yes", "yes, no, yes", True),
    ("ANSWER: (B)\nWait, re-checking.\nANSWER: (C)", "(C)", True),  # the last ANSWER line counts
    ("**ANSWER: [emma, lily]**", "emma,lily", True),  # markdown and brackets
    ("The answer is 7.", "7", False),  # no ANSWER line: unparsed
    ("46", "46", True),  # a bare answer-shaped reply is its own answer (Luna at reasoning none, probe e11)
    ("ANSWER:\n7", "7", True),  # an answer-shaped last line counts (audit 53; before, the answer had to sit on the ANSWER line)
])
def test_bbeh_parse_edge_cases(reply, gold, right):
    parsed = P.parse_answer("bbeh", reply)
    assert answers_match(gold, parsed, "bbeh") is right


@pytest.mark.parametrize("reply, parsed", [
    ("46", "46"), ("(B)", "(B)"), ("b", "b"), ("No", "no"), ("no, unknown, yes", "no, unknown, yes"), ("-3.", "-3"),
    ("<yes, no, yes>", "yes, no, yes"), ("**[no, unknown, no]**", "no, unknown, no"), ("<12>", "12"),
    ("The answer is 7.", None), ("I'm sorry, but I can't assist with that.", None), ("Working it out.\n46", "46"),
    ("Steps.\n\nyes, no, no", "yes, no, no"), ("No consistent assignment exists.", None), ("46\nI think so.", None),
    ("CONFIDENCE: 0.6", None), ("yes no", None), ("", None),
])
def test_bbeh_bare_reply_must_be_answer_shaped(reply, parsed):
    """Audit 51: only an option letter, a number or a yes / no / unknown list counts without an ANSWER line."""
    got = P.parse_answer("bbeh", reply)
    assert (got is None) if parsed is None else answers_match(parsed, got, "bbeh")


def test_a_refusal_is_unparsed_whatever_it_says():
    from autoagentnet.evidence.panel import grade
    from autoagentnet.tasks import Task

    item = Task(id="bbeh-x-1", prompt="?", answer="46", grader="bbeh")
    assert grade("bbeh", "base", item, "ANSWER: 46", stop_reason="refusal")["parsed"] is False
    assert grade("bbeh", "base", item, "ANSWER: 46", stop_reason="end_turn")["correct"] == 1.0
    assert grade("forecast", "base", item, "Probability: 0.3", stop_reason="content_filter")["prob"] is None


@pytest.mark.parametrize("reply, p", [
    ("Reasoning.\nProbability: 0.35", 0.35),
    ("Probability: 35%", 0.35),
    ("Probability: 0.2\nOn reflection...\nProbability: 0.25", 0.25),  # the last line counts
    ("**Probability:** 1.0", 0.99),  # clipped to [0.01, 0.99]
    ("I think it is likely.", None),
])
def test_forecast_parse_edge_cases(reply, p):
    got = P.parse_probability(reply)
    assert got == pytest.approx(p) if p is not None else got is None


@pytest.mark.parametrize("reply, gold, right", [
    ("so \\boxed{\\frac{1}{2}}", "0.5", True),
    ("first \\boxed{3}, then \\boxed{4}", "4", True),  # the last box counts
    ("\\boxed{\\sqrt{\\frac{3}{5}}}", "\\sqrt{3/5}", True),  # nested braces
    ("\\boxed{12", "12", False),  # an unclosed box is unparsed
    ("No box here.\nANSWER: 12", "12", True),  # the ANSWER line is the fallback
])
def test_math_parse_edge_cases(reply, gold, right):
    parsed = P.parse_answer("math", reply)
    assert (parsed is not None and answers_match(gold, parsed, "math")) is right


@pytest.mark.parametrize("reply, answer, confidence", [
    ("ANSWER: no, yes\nCONFIDENCE: 0.8", "no, yes", 0.8),
    ("ANSWER: 5\nCONFIDENCE: 80%", "5", 0.8),
    ("ANSWER: 5\nCONFIDENCE: 0", "5", 0.01),
    ("ANSWER: 5", "5", None),
    ("CONFIDENCE: 0.6", None, 0.6),
])
def test_aggregator_parse_edge_cases(reply, answer, confidence):
    assert P.parse_answer("bbeh", reply) == answer
    got = P.parse_confidence(reply)
    assert got == pytest.approx(confidence) if confidence is not None else got is None


def test_personas_follow_the_shared_task_and_the_aggregator_hides_sources():
    for name in P.PERSONAS:
        text = P.instruction("bbeh", name)
        assert text.endswith(P.BBEH_INSTRUCTION) and P.PERSONAS[name] in text
    block1, block2 = P.aggregator_task("bbeh", "TASK TEXT", ["a", None, "b"], seed="item-1")
    assert block1.startswith("TASK TEXT") and "(no answer)" in block1 and "haiku" not in block1.lower()
    assert block1 == P.aggregator_task("bbeh", "TASK TEXT", ["a", None, "b"], seed="item-1")[0]  # fixed order
    assert "3 independent" in block2
    with pytest.raises(ValueError):
        P.instruction("bbeh", "pirate")


def fb_sets():
    q = {"forecast_due_date": "2026-07-05", "questions": [
        {"id": "M1", "source": "polymarket", "question": "Will X happen?", "resolution_criteria": "per site",
         "background": "bg", "freeze_datetime": "2026-06-25T00:00:00+00:00", "freeze_datetime_value": "0.3", "url": "u"},
        {"id": "AEE", "source": "yfinance", "question": "Close on {resolution_date} above {forecast_due_date}?",
         "resolution_criteria": "close", "background": "", "freeze_datetime": "2026-06-25T00:00:00+00:00",
         "freeze_datetime_value": "113.3", "url": "u"}]}
    old = {"forecast_due_date": "2026-06-21", "questions": [{**q["questions"][0], "id": "OLD"}]}
    r = {"forecast_due_date": "2026-07-05", "resolutions": [
        {"id": "M1", "source": "polymarket", "direction": None, "resolution_date": "2026-07-20", "resolved_to": 1.0, "resolved": True},
        {"id": "AEE", "source": "yfinance", "direction": None, "resolution_date": "2026-07-12", "resolved_to": 0.0, "resolved": True},
        {"id": "AEE", "source": "yfinance", "direction": None, "resolution_date": "2026-08-04", "resolved_to": 1.0, "resolved": True},
        {"id": "C", "source": "acled", "direction": [1, -1], "resolution_date": "2026-07-12", "resolved_to": 1.0, "resolved": True},
        {"id": "U", "source": "fred", "direction": None, "resolution_date": "2026-07-12", "resolved_to": 0.4, "resolved": True}]}
    r_old = {"forecast_due_date": "2026-06-21", "resolutions": [{**r["resolutions"][0], "id": "OLD"}]}
    return [q, old], [r, r_old]


def test_forecastbench_join_keeps_resolved_single_questions_due_after_the_cutoff():
    questions, resolutions = fb_sets()
    frame = forecastbench_frame(questions, resolutions)
    assert sorted(zip(frame["id"], frame["resolution_date"])) == [("AEE", "2026-07-12"), ("AEE", "2026-08-04"), ("M1", "2026-07-20")]
    m1 = frame[frame["id"] == "M1"].iloc[0]
    assert m1["market"] and m1["days_after_claude"] == -5 and m1["days_after_luna"] == 25
    task = forecast_task(m1.to_dict())
    assert task.id == "M1@2026-07-05@2026-07-20" and task.answer == "1"
    assert "Market price at freeze: 0.30" in task.prompt
    aee = forecast_task(frame[frame["id"] == "AEE"].iloc[0].to_dict())
    assert "Close on 2026-07-12 above 2026-07-05?" in aee.prompt and "Latest value at freeze: 113.3" in aee.prompt
    assert "Market price" not in aee.prompt


def test_bbeh_items_start_at_position_140_and_math_items_after_july():
    rows = [{"id": f"b{i}", "prompt": "p", "answer": "yes", "meta": {"task": "web of lies"}} for i in range(150)]
    items = bbeh_items(rows)
    assert len(items) == 10 and items[0].meta["position"] == 140 and items[0].grader == "bbeh"
    table = pd.DataFrame({"problem_idx": [1, 2, 3, 4], "problem": ["p"] * 4,
                          "answer": ["\\frac{1}{2}", "7", "x or y", "3"],
                          "source": ["2608.00001", "2606.00002", "2609.00003", "2607.1"]})
    math = matharena_items({"arxivmath-0826": table}, since=date(2026, 7, 1))
    assert [t.id for t in math] == ["arxivmath-0826-1"]  # 2: June; 3: not gradable; 4: no valid arXiv id


@pytest.mark.parametrize("reply, right", [
    ("ANSWER: B and E", 0.0), ("ANSWER: (B) or (E)", 0.0), ("ANSWER: B, E", 0.0), ("ANSWER: B/E", 0.0),
    ("ANSWER: B, C, and D are true.", 0.0), ("ANSWER: B, C, and D (so the premise is wrong)", 0.0),
    ("ANSWER: B) 5, 8 and 3 — wait", 1.0), ("ANSWER: B) 6, 3 and 4", 1.0),
    ("ANSWER: B", 1.0), ("ANSWER: (B) the square", 1.0), ("B", 1.0),
])
def test_a_hedge_naming_several_options_is_wrong(reply, right):
    """Audit 53: the letter grader compared only the first letter, so "B and E" scored right against "(B)"."""
    from autoagentnet.evidence.panel import grade
    from autoagentnet.tasks import Task

    item = Task(id="bbeh-boolean_expressions-1", prompt="?", answer="(B)", grader="bbeh")
    assert grade("bbeh", "base", item, reply, stop_reason="stop")["correct"] == right
