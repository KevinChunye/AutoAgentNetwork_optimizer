# Paper

"Can AI Agents Be Organized More Efficiently for Discovering Science?", by Haochuan Kevin Wang and Ruijie Shi
(Massachusetts Institute of Technology). ICML 2026 style (`icml2026.sty`, `preprint` option), two columns; the main
text ends before the references and stays within nine pages, the appendix follows them.

## Build

```bash
pip install -e ".[dev]"
python scripts/build_numbers.py     # paper/numbers.tex (and the per-run and per-number tables)
python -m analysis.paper_figs       # paper/figs: the Atlas, depth and verification figures
python -m analysis.paper_figs_teams # paper/figs: the team-study figures (drawn at their printed ICML size)
cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main
```

A TeX engine is needed, for example `apt-get install texlive-latex-base texlive-latex-recommended
texlive-fonts-recommended texlive-latex-extra lmodern`.

## Rules

- **No number is typed by hand.** Every number is `\nm{key}`, defined in `numbers.tex` by `scripts/build_numbers.py`
  from a committed file; `\nmst{key}` gives its status (confirmatory, preregistered-descriptive, exploratory, post
  hoc). `numbers_table.tex` lists every number with its status and source, and `runs_table.tex` every run; both are
  generated and kept out of the paper.
- **Figures** come from committed tables through `analysis/paper_figs.py` and `analysis/paper_figs_teams.py` (vector
  PDF), drawn at their printed size (3.3 in for a column, 6.75 in for the full width) so text is legible.

## Open before submission

- The open-weight testbed's runs (its section is a design).
- The handoff-completeness read (the runs are committed; the read and its audit are not done).
