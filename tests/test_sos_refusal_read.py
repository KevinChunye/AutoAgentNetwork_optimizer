"""LAB-Bench prereg note 10: refusal counts and the refusal-fallback secondary read (offline, synthetic rows)."""
import sys

import pandas as pd

from conftest import ROOT

sys.path.insert(0, str(ROOT / "analysis"))
import self_or_social as S  # noqa: E402


def rows():
    base = {"item": "i1", "ref": "sonnet_low", "receiver": "B", "cost_usd": 0.01}
    return pd.DataFrame([
        {**base, "action": "initial", "stop_reason": "end_turn", "answer": "C", "parsed": True, "correct": True},
        {**base, "action": "reflect", "stop_reason": "refusal", "answer": None, "parsed": False, "correct": False},
        {**base, "action": "consult:A", "stop_reason": "end_turn", "answer": "D", "parsed": True, "correct": False},
        {**base, "receiver": "A", "ref": "haiku_low", "action": "initial", "stop_reason": "refusal", "answer": None,
         "parsed": False, "correct": False},
    ])


def test_refusal_counts_per_member_and_action():
    counts = S.refusal_counts(rows()).set_index(["receiver", "action"])
    assert counts.loc[("B", "reflect"), "refused"] == 1 and counts.loc[("B", "consult:A"), "refused"] == 0
    assert counts.loc[("A", "initial"), "share"] == 1.0


def test_refused_revision_falls_back_to_the_first_answer():
    out = S.refusal_fallback(rows())
    reflect = out[(out.receiver == "B") & (out.action == "reflect")].iloc[0]
    assert reflect["answer"] == "C" and bool(reflect["parsed"]) and bool(reflect["correct"])
    assert reflect["cost_usd"] == 0.01                                   # dollars stay as billed
    assert out[(out.action == "consult:A")].iloc[0]["answer"] == "D"     # answered revisions unchanged
    assert not bool(out[(out.receiver == "A")].iloc[0]["parsed"])        # a refused first answer stays refused


def test_text_refusals_count_and_fall_back_but_cut_calls_do_not():
    """LAB-Bench note 16 (audit SC-16): an unreadable reply the model finished itself ("I can't help with that",
    stop_reason stop or end_turn) is a text refusal; a reply cut off at the ceiling (length) is not."""
    base = {"item": "i1", "ref": "sol61_med", "receiver": "C", "cost_usd": 0.01}
    calls = pd.DataFrame([
        {**base, "action": "initial", "stop_reason": "stop", "answer": "B", "parsed": True, "correct": True},
        {**base, "action": "reflect", "stop_reason": "stop", "answer": None, "parsed": False, "correct": False},
        {**base, "action": "consult:A", "stop_reason": "length", "answer": None, "parsed": False, "correct": False},
        {**base, "action": "consult:B", "stop_reason": "content_filter", "answer": None, "parsed": False,
         "correct": False},
    ])
    counts = S.refusal_counts(calls).set_index("action")
    assert counts.loc["reflect", "text"] == 1 and counts.loc["reflect", "provider"] == 0
    assert counts.loc["consult:B", "provider"] == 1 and counts.loc["consult:A", "refused"] == 0
    out = S.refusal_fallback(calls).set_index("action")
    assert out.loc["reflect", "answer"] == "B" and out.loc["consult:B", "answer"] == "B"
    assert not bool(out.loc["consult:A", "parsed"])                      # a cut call stays wrong


def test_member_singles_cost_each_member_its_own_first_answer():
    """Audit SC-12: a member alone costs its own first answer, not the team's first-answer dollars split evenly."""
    calls = pd.DataFrame([
        {"item": "i1", "receiver": "A", "action": "initial", "cost_usd": 0.001},
        {"item": "i1", "receiver": "B", "action": "initial", "cost_usd": 0.010},
    ])
    table = pd.DataFrame([
        {"item": "i1", "family": None, "receiver": "A", "kind": "stop", "answer": "C", "correct": True, "initial_cost": 0.011},
        {"item": "i1", "family": None, "receiver": "B", "kind": "stop", "answer": "D", "correct": False, "initial_cost": 0.011},
    ])
    singles = S.member_singles(table, calls).set_index("method")
    assert singles.loc["single_A", "cost"] == 0.001 and singles.loc["single_B", "cost"] == 0.010
    assert S.SEED == 2026
