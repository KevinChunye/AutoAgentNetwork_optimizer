"""Sandboxed execution, verdict and choice parsing, selection efficiency and the pickers."""

import numpy as np
import pandas as pd
import pytest

from autoagentnet.testbed import checkers


def test_run_program_reads_stdin_and_reports_errors_and_timeouts():
    assert checkers.run_program("print(int(input()) * 2)", "21\n") == ("ok", "42\n")
    assert checkers.run_program("raise SystemExit(3)", "")[0] == "error"
    assert checkers.run_program("while True: pass", "", timeout_s=1)[0] == "timeout"


def test_sandbox_has_no_network_and_an_empty_environment():
    status, out = checkers.run_program(
        "import socket, os\ntry:\n    socket.create_connection(('example.com', 80), timeout=2)\n    print('net')\n"
        "except OSError:\n    print('blocked')\nprint(sorted(k for k in os.environ if 'PROXY' in k.upper()))", "")
    assert status == "ok" and out.splitlines() == ["blocked", "[]"]


def test_memory_limit_stops_a_hungry_program():
    status, _ = checkers.run_program("x = bytearray(3 * 2**30)", "", memory_mb=512)
    assert status == "error"


def test_run_tests_stdin_and_functional():
    code = "class Solution:\n    def add(self, a, b):\n        return a + b\n"
    tests = [{"input": "1\n2", "output": "3", "testtype": "functional"},
             {"input": "[1]\n[2]", "output": "[1, 2]", "testtype": "functional"}]
    assert checkers.run_tests(code, tests, "add") == [True, True]
    stdin = [{"input": "3\n", "output": "9\n", "testtype": "stdin"}, {"input": "2", "output": "5", "testtype": "stdin"}]
    assert checkers.run_tests("n=int(input())\nprint(n*n)", stdin) == [True, False]
    assert checkers.run_tests(None, stdin) == [False, False]


def test_behaviour_groups_programs_with_the_same_outputs():
    tests = [{"input": "2\n", "output": "4", "testtype": "stdin"}]
    a = checkers.behaviour("print(int(input())*2)", tests)
    b = checkers.behaviour("n=int(input())\nprint(n+n)", tests)
    c = checkers.behaviour("print(int(input())**3)", tests)
    assert a == b != c and checkers.behaviour(None, tests) == "no-code"


def test_extract_code_and_parsers():
    reply = "x\n```python\nprint(1)\n```\nmore\n```python\nprint(2)\n```\nANSWER: see code"
    assert checkers.extract_code(reply) == "print(2)\n"
    assert checkers.parse_verdict("hmm VERDICT: no ... VERDICT: Yes") == 1
    assert checkers.parse_verdict("nothing") is None
    assert checkers.parse_choice("CHOICE: 3", 4) == 2 and checkers.parse_choice("CHOICE: 9", 4) is None


def test_eta_is_zero_for_chance_and_one_for_an_oracle():
    random = np.array([0.5, 0.25, 1.0])
    oracle = np.array([1, 1, 1])
    assert checkers.eta(random, random, oracle) == 0
    assert checkers.eta(oracle, random, oracle) == 1
    assert np.isnan(checkers.eta(oracle, oracle, oracle))


def frame():
    # one system, two items, four calls; item a: calls 1 and 3 right, item b: none right
    return pd.DataFrame({"system": "s", "item": ["a"] * 4 + ["b"] * 4, "call": list(range(4)) * 2,
                         "answer": ["x", "y", "x", "y", "p", "q", "p", "q"], "correct": [0, 1, 0, 1, 0, 0, 0, 0],
                         "signal_margin": [0.1, 0.9, 0.2, 0.3, 1, 2, 3, 4],
                         "signal_exec_visible": [0, 1, 1, 1, 1, 1, 0, 0]})


def test_pickers_score_the_selected_candidate():
    t = frame()
    by_margin = checkers.pick_by_signal(t, "signal_margin").set_index("item")
    assert by_margin.loc["a", "picked"] == 1 and by_margin.loc["a", "random"] == 0.5 and by_margin.loc["b", "oracle"] == 0
    checks = pd.DataFrame({"system": "s", "item": ["a", "a", "a"], "call": [0, 1, 2], "verdict": [0, 1, 1]})
    assert checkers.pick_by_self_check(t, checks).set_index("item").loc["a", "picked"] == 1
    picks = pd.DataFrame({"system": ["s", "s"], "item": ["a", "b"], "judge": "j", "pick": [2, None]})
    judged = checkers.pick_by_judge(t, picks, "j").set_index("item")
    assert judged.loc["a", "picked"] == 0 and judged.loc["b", "picked"] == 0
    executed = checkers.pick_by_execution(t).set_index("item")
    assert executed.loc["a", "picked"] == 1  # passing classes: x (call 2) and y (calls 1, 3): y is larger
    table = checkers.eta_table({"margin": checkers.pick_by_signal(t, "signal_margin")}, pd.Series({"a": "easy", "b": "hard"}))
    overall = table[(table["tercile"] == "all") & (table["m"] == "all")]
    assert overall["eta"].item() == pytest.approx(1.0)
    assert set(table["m"]) == {"all", "0", "2"}  # item a has 2 right candidates of 4, item b none


def test_grading_a_code_reply_uses_hidden_tests_and_groups_by_behaviour():
    from autoagentnet.tasks import Task
    from autoagentnet.testbed import sample

    task = Task(id="lcb-x", prompt="square n", answer=None, meta={
        "benchmark": "code", "public_tests": [{"input": "2\n", "output": "4\n", "testtype": "stdin"}],
        "private_tests": [{"input": "3\n", "output": "9\n", "testtype": "stdin"},
                          {"input": "5\n", "output": "25\n", "testtype": "stdin"}]})
    right = sample.grade(task, "```python\nn=int(input())\nprint(n*n)\n```\nANSWER: see code")
    lucky = sample.grade(task, "```python\nn=int(input())\nprint(n+n)\n```\nANSWER: see code")  # passes 2 -> 4 only
    none = sample.grade(task, "no code here\nANSWER: 4")
    assert right["correct"] == 1.0 and right["signal_exec_visible"] == 1.0
    assert lucky["correct"] == 0.0 and lucky["signal_exec_visible"] == 1.0 and lucky["answer"] == right["answer"]
    assert none["answer"] is None and none["correct"] == 0.0
    assert sample.shown_answer("code/lcb_v6", right["answer"]) == "see code"
    assert sample.benchmark_of(task) == "code/lcb_v6"
