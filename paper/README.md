# Paper

"Shared failure and the price of verification in multi-LLM systems", by Haochuan Kevin Wang and Ruijie Shi
(Massachusetts Institute of Technology). Preprint, NeurIPS style (`neurips_2025.sty`, `preprint` option).

## Build

```bash
pip install -e ".[dev]"
python scripts/build_numbers.py     # paper/numbers.tex (and the per-run and per-number tables)
python -m analysis.paper_figs       # paper/figs/*.pdf
cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main
```

A TeX engine is needed, for example `apt-get install texlive-latex-base texlive-latex-recommended
texlive-fonts-recommended texlive-latex-extra lmodern`.

## Rules

- **No number is typed by hand.** Every number is `\nm{key}`, defined in `numbers.tex` by `scripts/build_numbers.py`
  from a committed file; `\nmst{key}` gives its status (confirmatory, preregistered-descriptive, exploratory, post
  hoc). `numbers_table.tex` lists every number with its status and source, and `runs_table.tex` every run; both are
  generated and kept out of the paper.
- **Figures** come from committed tables through `analysis/paper_figs.py` (vector PDF).

## Open before submission

- The open-weight testbed's runs (section 6 is a design).
- Venue and the 2026 style file.
