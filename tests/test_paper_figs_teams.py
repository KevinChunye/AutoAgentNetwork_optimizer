"""Offline test for analysis/paper_figs_teams.py: the forest-style figures draw from a numbers dict into PDF files.
Synthetic numbers; no model call and no repository data."""
from analysis import paper_figs_teams as F


def numbers():
    n = {"ah2.luna.diff": 0.107, "ah2.luna.lo": 0.071, "ah2.luna.hi": 0.142, "ah2.luna.ratio": 1.38,
         "ah2.haiku.diff": 0.037, "ah2.haiku.lo": 0.013, "ah2.haiku.hi": 0.062, "ah2.haiku.ratio": 1.17,
         "pilot.diff": 0.088, "pilot.diff.lo": -0.063, "pilot.diff.hi": 0.225, "pilot.team.usd": 0.0115,
         "pilot.sonnet.usd": 0.0144, "pilot.items": 80, "anchor.items.all": 533, "lab.items": 144,
         "lab.claude.reviewminus": 0.063, "lab.claude.reviewminus.lo": 0.021, "lab.claude.reviewminus.hi": 0.111,
         "lab.claude.review.ratio": 4.4, "lab.gpt.reviewminus": 0.014, "lab.gpt.reviewminus.lo": -0.028,
         "lab.gpt.reviewminus.hi": 0.056, "lab.gpt.review.usd": 0.0316, "lab.gpt.single.usd": 0.0055,
         "lab.mix.gpt": -0.007, "lab.mix.gpt.lo": -0.049, "lab.mix.gpt.hi": 0.035, "lab.mix.usd": 0.0227,
         "lab.gpt.vote.usd": 0.0182}
    for key, (m, lo, hi) in {"main": (0.002, -0.0031, 0.0095), "planner": (0.0067, 0.0011, 0.0148), "rule": (0.0019, 0.0004, 0.0036),
                             "claude": (0.0086, 0.0034, 0.0162), "gpt": (0.0056, 0.001, 0.0121)}.items():
        n[f"phx.{key}"], n[f"phx.{key}.lo"], n[f"phx.{key}.hi"] = m, lo, hi
    return n


def test_hero_and_phoenix_figures_are_written(tmp_path, monkeypatch):
    monkeypatch.setattr(F, "OUT", tmp_path)
    F.fig_hero(numbers())
    F.fig_phx(numbers())
    assert (tmp_path / "fig_hero.pdf").stat().st_size > 1000
    assert (tmp_path / "fig_phx.pdf").stat().st_size > 1000
