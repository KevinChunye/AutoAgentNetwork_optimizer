"""How the anchor reads a math answer (autoagentnet/evidence/mathread.py; audits 74, 83, 86 and 88). Offline: synthetic
forms, the run's parsed flag, and the parse-status counts on the stored anchor replies (parse status only, never a
grade)."""

import pytest
import json
from pathlib import Path

import pandas as pd

from autoagentnet.evidence import prompts as P
from autoagentnet.evidence.mathread import abstained, condition_cut, math_read, normalize_math
from autoagentnet.evidence.panel import grade
from autoagentnet.tasks import Task, answers_match, parse_answer as math_parse

ROOT = Path(__file__).resolve().parents[1]
MATH = ROOT / "data/external/evidence/math.jsonl"


@pytest.mark.needs_external("evidence/math.jsonl")
def test_equations_are_read_as_their_right_hand_side_only_when_needed():
    # audit 83: neither the answer as written nor audit 74's form parses, one top-level "=": its right-hand side
    assert math_read("\\max_{x\\in[0,1]} g(x) = \\frac{1}{4}", "\\frac{1}{4}") == "\\frac{1}{4}"
    assert math_read("\\#\\{\\text{solutions}\\} = 12", "12") == "\\#\\{\\text{solutions}\\} = 12"  # \text first: kept
    assert math_read("x = 5", "x = 5") == "x = 5"  # the gold has "=": nothing is taken apart
    assert math_read("tuple = (1, 2)", "(1,2)") == normalize_math("tuple = (1, 2)", "(1,2)") == "(1, 2)"  # audit 74
    # audit 74's "name =" rule breaks this one (it cuts at the "=" inside \sum_{k=0}); it parses as written, and as an
    # equation the grader reads it by its right-hand side, which is how it is read (audit 84)
    eq = "\\sum_{k=0}^{n} \\binom{n}{k}^2 = \\binom{2n}{n}"
    assert len(math_parse(normalize_math(eq, "\\binom{2n}{n}"))) == 0 and math_read(eq, "\\binom{2n}{n}") == "\\binom{2n}{n}"
    assert math_read("(a, b, c) = (1, 2, 3)", "(1,2,3)") == "(1, 2, 3)"  # a parsed equation: its right-hand side
    for g in [json.loads(x)["answer"] for x in MATH.read_text().splitlines() if x]:
        assert answers_match(normalize_math(g), math_read(g, g), "math")  # every gold still reads as itself


def test_the_run_flags_math_as_parsed_the_way_the_read_reads_it():
    item = Task(id="m", prompt="p", answer="\\frac{1}{4}", grader="math", meta={})
    reply = "work\n\\boxed{\\max_{x\\in[0,1]} g(x) = \\frac{1}{4}}"
    v2 = grade("math", "base", item, reply, "end_turn", None, "v2")
    assert v2["parsed"] and v2["answer"].startswith("\\max")  # parsed as the read parses it; the answer stored raw
    assert not grade("math", "base", item, reply, "end_turn", None, "v1")["parsed"]  # v1 runs are unchanged


def parse_counts() -> pd.DataFrame:
    """Per anchor math run and source: calls parsed as written, under audit 74, and under audit 83 (truncated calls
    are unparsed at every stage); Luna on the first 25 sealed items, the ones its first chunk asked."""
    gold = {json.loads(x)["id"]: json.loads(x)["answer"] for x in MATH.read_text().splitlines() if x}
    first25 = set((ROOT / "research/v3/evidence/sealed/math_all.txt").read_text().split()[:25])
    runs = {"e51_haiku_off_math": ["haiku_nothink:base"], "e51_haiku_low_math12": ["haiku_low:base"],
            "e51_luna_math": None}
    rows = []
    for run, sources in runs.items():
        d = pd.read_csv(ROOT / "results" / run / "calls.csv", usecols=["item", "source", "reply", "truncated"])
        d = d[d["source"].isin(sources)] if sources else d[d["item"].isin(first25)]
        for item, source, reply, cut in zip(d["item"], d["source"], d["reply"], d["truncated"].astype(bool)):
            raw = P.parse_answer("math", reply if isinstance(reply, str) else "")
            ok = lambda a: a is not None and len(math_parse(a)) > 0 and not cut
            rows.append({"run": run, "source": source, "raw": ok(raw),
                         "a74": ok(None if raw is None else normalize_math(raw, gold[item])),
                         "a83": ok(None if raw is None else math_read(raw, gold[item]))})
    return pd.DataFrame(rows).groupby(["run", "source"])[["raw", "a74", "a83"]].sum()


@pytest.mark.needs_external("evidence/math.jsonl")
def test_parse_flips_on_the_anchor_replies_are_as_audited():
    c = parse_counts()
    assert (c.loc[("e51_haiku_low_math12", "haiku_low:base")] == [245, 249, 250]).all()  # audit 74: +4; audit 83: +1
    assert (c.loc[("e51_haiku_off_math", "haiku_nothink:base")] == [259, 262, 264]).all()  # +3; +2
    assert (c.loc[("e51_luna_math", "luna_none:base")] == [45, 51, 61]).all()
    assert (c.loc[("e51_luna_math", "luna_low_ev:base")] == [52, 60, 67]).all()
    assert (c.loc[("e51_luna_math", "luna_med:base")] == [58, 65, 74]).all()
    assert (c["a83"] >= c["raw"]).all() and (c["a83"] >= c["a74"]).all()  # no call becomes unreadable


def test_an_answer_with_a_condition_attached_is_read_without_it():
    """Audit 86 (step 2b): a condition after a top-level \\quad is dropped when the rest is a value and the tail is only a
    condition; abstentions, bare bounds and hedges stay unreadable. Made-up numbers."""
    assert math_read("b_N=7\\qquad(N\\ge 3)", "7") == "7"
    assert math_read("v=7\\quad\\text{unit words}", "7") == "7"
    assert math_read("\\frac{1}{2}\\quad(n\\ge 1)", "\\frac{1}{2}") == "\\frac{1}{2}"
    for stays in ("\\text{unknown; conjectured value is } 3", "v_*\\ge 2"):
        assert len(math_parse(math_read(stays, "7"))) == 0, stays
    assert math_read("5\\quad\\text{or } 6", "7") == "5\\quad\\text{or } 6"  # a hedge is never cut to one of its values


@pytest.mark.needs_external("evidence/math.jsonl")
def test_condition_cut_flips_on_the_stored_replies_are_as_audited():
    """Audit 86: on the stored replies step 2b reads 4 more of Sol low's calls on its first 5 items (6 -> 10 of 15) and 1
    more of Luna low's (236 -> 237 of 279); nothing else changes."""
    gold = {json.loads(x)["id"]: json.loads(x)["answer"] for x in MATH.read_text().splitlines() if x}
    first5 = set((ROOT / "research/v3/evidence/sealed/math_all.txt").read_text().split()[:5])
    counts = {}
    for run, source, items in (("e51_sol_math", "sol61_low:base", first5), ("e51_luna_math", "luna_low_ev:base", None)):
        d = pd.read_csv(ROOT / "results" / run / "calls.csv", usecols=["item", "source", "reply", "truncated"])
        d = d[(d["source"] == source) & (d["item"].isin(items) if items else True)]
        n = 0
        for item, reply, cut in zip(d["item"], d["reply"], d["truncated"].astype(bool)):
            raw = P.parse_answer("math", reply if isinstance(reply, str) else "")
            n += raw is not None and not cut and len(math_parse(math_read(raw, gold[item]))) > 0
        counts[source] = (n, len(d))
    assert counts["sol61_low:base"] == (10, 15) and counts["luna_low_ev:base"] == (237, 279)


def test_an_equation_cut_inside_a_brace_and_a_condition_after_several_equals_are_read():
    """Audit 88. Rule A: audit 74's "name =" cut stops at the "=" inside \\sum_{n=0}, so step 2 also tries the answer
    normalized without that cut. Rule B: step 2b needs no "=" count, since condition_cut refuses a tail with a top-level
    "=". Made-up forms."""
    series = "\\displaystyle \\sum_{n=0}^{\\infty}a_nz^n\n=\\frac{1-z}{1-3z}"
    assert len(math_parse(normalize_math(series, "\\frac{1-z}{1-3z}"))) == 0
    assert math_read(series, "\\frac{1-z}{1-3z}") == "\\frac{1-z}{1-3z}"
    assert math_read("N=2+3=5\\qquad(k\\ge 2)", "5") == "5"
    assert condition_cut("1 \\quad x=2") is None  # a tail with "=" is never cut away
    assert math_read("N=2+3=5\\qquad(k\\ge 2)", "N = 5") != "5"  # the gold has "=": nothing is taken apart


def test_abstained_reads_the_words_inside_text_only():
    """Audit 88: form only, never the gold. Made-up answers."""
    for a in ("\\text{unknown}", "\\text{Open problem}", "\\text{not presently known}", "\\text{conjectured: } 3",
              "\\text{not established here}", "\\text{Not determined}", "\\text{cannot be computed}",
              "\\text{no closed form}", "\\text{no closed-form expression}"):
        assert abstained(a), a
    for a in ("7", "unknown", "\\frac{1}{2}\\quad\\text{(units)}", "\\text{opening}", None):
        assert not abstained(a), a  # outside \\text{}, or not an abstention


def math_census() -> pd.DataFrame:
    """Per anchor math run and source, on the base prompt: calls, calls the anchor reads (math_read; truncated calls are
    unread) and unread calls that abstain (abstained). Sol low on its first 48 sealed items, the ones asked before audit
    88 (the file grows as the run goes on)."""
    gold = {json.loads(x)["id"]: json.loads(x)["answer"] for x in MATH.read_text().splitlines() if x}
    first48 = set((ROOT / "research/v3/evidence/sealed/math_all.txt").read_text().split()[:48])
    rows = []
    for path in sorted((ROOT / "results").glob("e51_*math*/calls.csv")):
        d = pd.read_csv(path, usecols=["item", "source", "prompt", "reply", "truncated"])
        d = d[(d["prompt"] == "base") & (d["item"].isin(first48) if path.parent.name == "e51_sol_math_low" else True)]
        for item, source, reply, cut in zip(d["item"], d["source"], d["reply"], d["truncated"].astype(bool)):
            raw = P.parse_answer("math", reply if isinstance(reply, str) else "")
            read = raw is not None and not cut and len(math_parse(math_read(raw, gold[item]))) > 0
            rows.append({"run": path.parent.name, "source": source, "calls": 1, "read": read,
                         "abstained": not read and abstained(raw)})
    return pd.DataFrame(rows).groupby(["run", "source"])[["calls", "read", "abstained"]].sum()


@pytest.mark.needs_external("evidence/math.jsonl")
def test_audit88_counts_on_the_stored_replies_are_as_audited():
    """Rules A and B read 3 more of Sol low's 144 calls (100 -> 103) and change no other arm (the read counts below are
    the audit-86 counts); abstentions: Sol low 29, Luna 4, 6 and 7, Haiku off 1, Sol medium 1 (and Sol low's 3 cached
    in e51_sol_math)."""
    c = math_census()
    expected = {("e51_haiku_low_math12", "haiku_low:base"): (279, 250, 0),
                ("e51_haiku_low_math36", "haiku_low:base"): (75, 68, 0),
                ("e51_haiku_math", "haiku_low:base"): (75, 61, 0),
                ("e51_haiku_math", "haiku_nothink:base"): (75, 73, 0),
                ("e51_haiku_off_math", "haiku_nothink:base"): (279, 264, 1),
                ("e51_luna_math", "luna_low_ev:base"): (279, 237, 6),
                ("e51_luna_math", "luna_med:base"): (279, 250, 7),
                ("e51_luna_math", "luna_none:base"): (279, 217, 4),
                ("e51_sol_math", "sol61_low:base"): (15, 10, 3),
                ("e51_sol_math", "sol61_med:base"): (4, 3, 1),
                ("e51_sol_math_low", "sol61_low:base"): (144, 103, 29),
                ("e51_sonnet_math", "sonnet_low:base"): (38, 36, 0),
                ("e51_sonnet_math", "sonnet_nothink:base"): (38, 38, 0),
                ("e51_sonnet_math_t30", "sonnet_low:base"): (102, 98, 0),
                ("e51_sonnet_math_t30", "sonnet_nothink:base"): (102, 99, 0),
                ("e51_tier2_anth_math", "opus_nothink:base"): (17, 16, 0),
                ("e51_tier2_anth_math", "sonnet_high:base"): (10, 8, 0)}
    got = {key: tuple(int(v) for v in row) for key, row in zip(c.index, c[["calls", "read", "abstained"]].to_numpy())}
    for key, want in expected.items():
        assert got[key] == want, key
