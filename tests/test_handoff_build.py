"""Offline tests for autoagentnet/handoff/build.py: answer stripping, the cut at f, the leak flag, the wrong-trace
partner and the stratified stop-early subset. No model call."""
from autoagentnet.handoff import build as B
from autoagentnet.tasks import Task


def test_strip_answer_removes_only_the_final_answer_line():
    reply = "Step one.\nStep two says yes.\n\nANSWER: Yes"
    assert B.strip_answer(reply) == "Step one.\nStep two says yes."
    assert B.strip_answer("No answer line here.") == "No answer line here."


def test_cut_keeps_the_first_share_of_tokens_with_spacing():
    trace = "a b\nc d"
    assert B.cut(trace, 0.0) == ""
    assert B.cut(trace, 0.5) == "a b"
    assert B.cut(trace, 0.75) == "a b\nc"
    assert B.cut(trace, 1.0) == "a b\nc d"


def test_leak_flag_uses_the_task_grader_on_the_prefix_alone():
    item = Task(id="labbench-seqqa-1", prompt="Q?\nA) x\nB) y", answer="B", grader="exact", meta={})
    assert B.leaked("mcq", item, "Working... so the option is B.\nANSWER: B")
    assert not B.leaked("mcq", item, "")


def test_wrong_partner_stays_in_family_and_never_pairs_an_item_with_itself():
    ids = ["bbeh-nycc-1", "bbeh-nycc-2", "bbeh-nycc-3", "bbeh-linguini-1", "bbeh-linguini-2"]
    p = B.wrong_partner(ids)
    assert all(B.family(k) == B.family(v) and k != v for k, v in p.items())


def test_handoff_task_appends_the_prefix_and_keeps_the_key():
    item = Task(id="bbeh-nycc-1", prompt="Pick the funniest.", answer="(A)", grader="exact", meta={"task": "nycc"})
    t = B.handoff_task(item, "Caption A plays on...", "f050")
    assert t.id == "bbeh-nycc-1~f050" and t.answer == "(A)" and B.HEADER in t.prompt and t.prompt.endswith(B.HANDOFF_INSTRUCTION)
    assert B.handoff_task(item, "", "f000").prompt == item.prompt


def test_stratified_subset_spreads_over_families():
    ids = [f"bbeh-{fam}-{k}" for fam in ("a", "b", "c") for k in range(20)]
    sub = B.stratified(ids, 15)
    assert len(sub) == 15 and {B.family(i) for i in sub} == {"a", "b", "c"}


def test_mentions_flags_an_answer_named_in_prose():
    mcq = Task(id="labbench-seqqa-1", prompt="Q", answer="B", grader="exact", meta={})
    assert B.mentions("mcq", mcq, "So option B fits best")
    assert B.mentions("mcq", mcq, "The answer is (B) because")
    assert not B.mentions("mcq", mcq, "Both options look odd")
    bb = Task(id="bbeh-word_sorting-1", prompt="Q", answer="apple banana cherry", grader="exact", meta={})
    assert B.mentions("bbeh", bb, "Sorted: Apple banana cherry")
    assert not B.mentions("bbeh", Task(id="x-y-1", prompt="Q", answer="No", grader="exact", meta={}), "no idea")
