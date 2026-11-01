# Paper draft (session W1)

"Shared failure and the price of verification in multi-LLM systems", NeurIPS style, main text (8 pages) plus appendix
(19 pages in all). A draft for internal review: authors, venue and the E6 and testbed results are open. The earlier
working title ("Depth before width: ...") was withdrawn after audit W1-1: only the first effort step of a cheap model
was tested, and session E6's CD2 decides whether depth beats width beyond it.

## Build

```bash
pip install -e ".[dev]"                       # numpy, pandas, matplotlib, pyyaml
python -m analysis.atlas_extend --resume      # tables of P1-P8 (research/v4/atlas/tables/extend/); drop --resume to recompute (about an hour)
python scripts/build_numbers.py               # paper/numbers.tex, numbers_table.tex, runs_table.tex, reports/v4/story_data.json
python -m analysis.paper_figs                 # paper/figs/*.pdf
cd paper && pdflatex main && bibtex main && pdflatex main && pdflatex main
```

A TeX engine: `apt-get install texlive-latex-base texlive-latex-recommended texlive-fonts-recommended
texlive-latex-extra lmodern` (what session W1 used). `neurips_2025.sty` is the NeurIPS 2025 style file
(https://media.neurips.cc/Conferences/NeurIPS2025/Styles.zip; the 2026 file was not yet published there), loaded with
the `preprint` option.

## Rules

- **No number is typed by hand.** Every number is `\nm{key}`, defined in `numbers.tex` by `scripts/build_numbers.py`
  from a committed file. `\nmst{key}` gives the number's status (confirmatory, preregistered-descriptive, exploratory,
  post hoc; record, design, cited, pending for bookkeeping). Appendix E lists every number with its status and source.
  An unknown key prints `??key` in bold.
- **Pending pieces fill themselves.** Session E6's CD read (`research/v4/cd/read.md`) and run review
  (`research/v4/runs_review.md`) are placeholders until they are on main; rerun `scripts/build_numbers.py` after
  merging main.
- **Figures** come from committed tables through `analysis/paper_figs.py` (vector PDF).

## References

The eleven related-work papers named in the brief were checked against their arXiv pages in W1
(`research/lit/w1_related_work.md`). arXiv 2505.19433 (ACBench) is about weight compression of single models and is
not cited. The data-source and method citations (SWE-bench, MathArena, LiveBench, BBEH, Dawid-Skene, Learn-then-Test)
were not re-opened in W1.

## Status of the sections

| section | status |
|---|---|
| 1-3 Introduction, definitions, Atlas | drafted from A1-A7 and the W1 extensions P1-P8 (post hoc), revised after audit W1-1 |
| 4 Preregistered API studies | Phase 1 and the anchor drafted from the findings ledger and the anchor read; the depth claim is limited to the first effort step; CD pending (E6) |
| 5 Verification | drafted, with the judge's coverage cap; execution checks on code wait for the testbed |
| 6 Open-weight testbed | design only; no GPU run yet (T1) |
| 7 Related work | drafted from the W1 literature check |
| 8-9 Limitations, conclusion | drafted |
| Appendix A-E | preregistrations, power, audits, runs and spend, every number with its status |

## Missing before submission

- E6's CD read (CD2 decides the title and the depth claim) and run review.
- The testbed's pilot and stage 1 (T1), for section 6.
- Authors, venue and the 2026 style file.
- A re-audit of the post-W1-1 revision (W1 had one auditor call).
