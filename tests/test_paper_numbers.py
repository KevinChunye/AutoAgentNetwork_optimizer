"""Offline tests of the session W1 build: scripts/build_numbers.py (every number the paper and the page cite exists
and comes from a committed file) and analysis/paper_figs.py (every figure draws)."""

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_builder():
    spec = importlib.util.spec_from_file_location("build_numbers", ROOT / "scripts/build_numbers.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_display_formats():
    B = load_builder()
    assert B.fmt(0.1234, "pct", 1) == "12.3"
    assert B.fmt(-0.083, "signed", 1) == "-8.3"
    assert B.fmt(0.0733, "usd", 3) == "$0.073"
    assert B.fmt(1461.0, "int", 0) == "1,461"
    assert B.tex("$0.073") == "\\$0.073"
    assert B.grab("rho 0.430 (0.370 to 0.488)", r"rho ([\d.]+)") == 0.43
    with pytest.raises(ValueError):
        B.grab("nothing here", r"rho ([\d.]+)")


def test_put_refuses_unknown_status_and_duplicates():
    B = load_builder()
    B.NUMBERS.clear()
    B.put("x", 0.5, "post hoc", "a.csv", "pct", 1)
    with pytest.raises(ValueError):
        B.put("x", 0.5, "post hoc", "a.csv")
    with pytest.raises(ValueError):
        B.put("y", 0.5, "maybe", "a.csv")


@pytest.fixture(scope="module")
def built():
    B = load_builder()
    B.NUMBERS.clear()
    B.atlas_numbers()
    B.extension_numbers()
    B.design_numbers()
    B.phase1_numbers()
    B.anchor_numbers()
    B.cd_numbers()
    B.testbed_numbers()
    B.pilot_numbers()
    B.lab_numbers()
    B.phoenix_numbers()
    B.allocator_numbers()
    runs = B.runs_table()
    B.process_numbers(runs)
    return B, runs


def test_every_key_the_paper_and_the_page_cite_is_built(built):
    B, _ = built
    paper = set(re.findall(r"\\nm\{([^}]+)\}", (ROOT / "paper/main.tex").read_text()))
    page = set(re.findall(r'data-n="([^"]+)"', (ROOT / "reports/v4/story_template.html").read_text()))
    page |= set(re.findall(r'\["([a-z0-9.]+)", "', (ROOT / "reports/v4/story_template.html").read_text()))
    missing = sorted(k for k in paper | page if k not in B.NUMBERS and "." in k)
    assert not missing, missing


def test_spend_reconciles_and_sources_are_committed_files(built):
    B, runs = built
    assert B.NUMBERS["spend.total"]["value"] == pytest.approx(runs["spend"].sum())
    assert runs["spend"].min() >= 0
    for key, rec in B.NUMBERS.items():
        if rec["status"] == "pending":
            continue
        first = rec["source"].split(" ")[0]
        assert (ROOT / first).exists() or "*" in first, (key, first)


def test_one_item_follows_its_rule(built):
    B, _ = built
    item = B.one_item()
    assert len(item["calls"]) == 6
    assert item["judge"]["correct"] == 0 and item["sol"]["correct"] == 1
    assert item["agree"] < item["exit_rule"]


def test_figures_draw(tmp_path, monkeypatch):
    from analysis import paper_figs as P

    monkeypatch.setattr(P, "OUT", tmp_path)
    for f in P.FIGURES:
        f()
    assert len(list(tmp_path.glob("*.pdf"))) == len(P.FIGURES)
    assert P.settings("openai/o3-mini--medium", "openai/o3-mini") == ("medium", "default")


def test_half_up_rounds_ties_away_from_zero():
    B = load_builder()
    assert B.half_up(-0.0625, 1) == -0.063 and B.half_up(0.0625, 1) == 0.063 and B.half_up(0.7125, 1) == 0.713
