"""The anchor's text-only item rules (scripts/seal_anchor.py). Offline."""

import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location("seal_anchor", Path(__file__).resolve().parents[1] / "scripts/seal_anchor.py")
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def test_word_sorting_rule_flags_a_changed_word_only():
    ok = ('Q: Sort the following words alphabetically: List: gazpacho ballast\nThought 1: The first letter: "gazpacho": '
          '"g" (7). "ballast": "b" (2).\nThought 2: We now have ...')
    changed = ok.replace('"ballast": "b"', '"ballest": "b"')
    assert not S.thought1_changes_word(ok) and S.thought1_changes_word(changed)
    assert not S.thought1_changes_word("Sort these: List: a b")  # no Thought 1: the sorting variant


def test_linguini_rule_and_dispatch():
    assert S.malformed_linguini("Fill the blanks (1-4):\n...") and not S.malformed_linguini("Fill in the masked element (5)")
    assert S.dropped("linguini", "Fill the blanks (1-10):") and not S.dropped("nycc", "Fill the blanks (1-10):")
