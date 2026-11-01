# Information beside n_eff (post hoc, exploratory; session E5 patch 2.3)

Written by `python -m analysis.information_posthoc` from the Phase 1 BBEH calls (300 sealed items, read at G2a). Definitions in the script's docstring. Nothing here is a test.

| set | calls | n_eff | info_nats | h_nats | dollars | info_per_dollar |
|---|---|---|---|---|---|---|
| 12-call panel | 12 | 4.1884 | 0.4332 | 0.5085 | 0.0241 | 17.9683 |
| Sol alone | 1 | 1.0000 | 0.4281 | 0.5085 | 0.0062 | 68.8762 |
| Sonnet alone | 1 | 1.0000 | 0.1743 | 0.5085 | 0.0139 | 12.5141 |
| Haiku x5 | 5 | 1.8445 | 0.0695 | 0.5085 | 0.0034 | 20.2585 |
| Haiku x5 + Luna x5 | 10 | 3.1558 | 0.0686 | 0.5085 | 0.0040 | 17.3077 |
| mixed 5 (3H+2L) | 5 | 2.6635 | 0.0566 | 0.5085 | 0.0024 | 23.6037 |
| mixed 5 (2H+3L) | 5 | 2.8309 | 0.0476 | 0.5085 | 0.0018 | 25.8871 |
| Luna x5 | 5 | 2.1890 | 0.0000 | 0.5085 | 0.0005 | 0.0000 |

Correction (audit 68, finding 6): an earlier version of this table reported Gaussian-copula numbers (up to 1.22 for the 12-call panel and 1.21 for Sol alone), which are not information about a 0/1 truth (at most ln 2 = 0.693 nats). They are replaced by the predictive bound above.
