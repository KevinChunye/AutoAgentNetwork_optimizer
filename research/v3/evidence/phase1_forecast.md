# Evidence plan, Phase 1, block G2b: ForecastBench (the sealed read)

Written by `python -m analysis.evidence_phase1 --block forecast`, committed before any paid call. fit: 100, sealed: 200, sealed market (sealed + extra): 100. Intervals 95%, 2000 draws, seed 0, under both cluster definitions (H10: the wider is primary). Everything here is exploratory.

## Brier and log loss

| group | forecaster | n | Brier | log loss |
|---|---|---|---|---|
| sealed, all | Haiku (per call) | 200 | 0.1377 | 0.4103 |
| sealed, all | Haiku (pooled) | 200 | 0.1370 | 0.4086 |
| sealed, all | Luna (per call) | 200 | 0.1489 | 0.4549 |
| sealed, all | Luna (pooled) | 200 | 0.1429 | 0.4301 |
| sealed, all | Sonnet (per call) | 200 | 0.1292 | 0.3891 |
| sealed, all | Sonnet (pooled) | 200 | 0.1292 | 0.3891 |
| sealed, all | Sol (per call) | 200 | 0.1282 | 0.3824 |
| sealed, all | Sol (pooled) | 200 | 0.1282 | 0.3824 |
| sealed, all | panel, pooled log-odds | 200 | 0.1328 | 0.3977 |
| sealed, all | panel, mean probability | 200 | 0.1342 | 0.4029 |
| sealed, market | Haiku (per call) | 100 | 0.0899 | 0.2865 |
| sealed, market | Haiku (pooled) | 100 | 0.0896 | 0.2855 |
| sealed, market | Luna (per call) | 100 | 0.1105 | 0.3727 |
| sealed, market | Luna (pooled) | 100 | 0.1068 | 0.3529 |
| sealed, market | Sonnet (per call) | 100 | 0.0841 | 0.2697 |
| sealed, market | Sonnet (pooled) | 100 | 0.0841 | 0.2697 |
| sealed, market | Sol (per call) | 100 | 0.0825 | 0.2700 |
| sealed, market | Sol (pooled) | 100 | 0.0825 | 0.2700 |
| sealed, market | panel, pooled log-odds | 100 | 0.0897 | 0.2894 |
| sealed, market | panel, mean probability | 100 | 0.0906 | 0.2939 |
| sealed, market | freeze price | 100 | 0.0859 | 0.2773 |
| sealed, market | panel and price combined | 100 | 0.0859 | 0.2786 |
| sealed, data-series | Haiku (per call) | 100 | 0.1854 | 0.5342 |
| sealed, data-series | Haiku (pooled) | 100 | 0.1844 | 0.5318 |
| sealed, data-series | Luna (per call) | 100 | 0.1872 | 0.5372 |
| sealed, data-series | Luna (pooled) | 100 | 0.1789 | 0.5073 |
| sealed, data-series | Sonnet (per call) | 100 | 0.1743 | 0.5086 |
| sealed, data-series | Sonnet (pooled) | 100 | 0.1743 | 0.5086 |
| sealed, data-series | Sol (per call) | 100 | 0.1739 | 0.4947 |
| sealed, data-series | Sol (pooled) | 100 | 0.1739 | 0.4947 |
| sealed, data-series | panel, pooled log-odds | 100 | 0.1760 | 0.5059 |
| sealed, data-series | panel, mean probability | 100 | 0.1778 | 0.5118 |
| 100 sealed market | Haiku (per call) | 100 | 0.0899 | 0.2865 |
| 100 sealed market | Haiku (pooled) | 100 | 0.0896 | 0.2855 |
| 100 sealed market | Luna (per call) | 100 | 0.1105 | 0.3727 |
| 100 sealed market | Luna (pooled) | 100 | 0.1068 | 0.3529 |
| 100 sealed market | Sonnet (per call) | 100 | 0.0841 | 0.2697 |
| 100 sealed market | Sonnet (pooled) | 100 | 0.0841 | 0.2697 |
| 100 sealed market | Sol (per call) | 100 | 0.0825 | 0.2700 |
| 100 sealed market | Sol (pooled) | 100 | 0.0825 | 0.2700 |
| 100 sealed market | panel, pooled log-odds | 100 | 0.0897 | 0.2894 |
| 100 sealed market | panel, mean probability | 100 | 0.0906 | 0.2939 |
| 100 sealed market | freeze price | 100 | 0.0859 | 0.2773 |
| 100 sealed market | panel and price combined | 100 | 0.0859 | 0.2786 |

## H9: panel against the market price (100 sealed market questions)

- panel minus price (Brier): +0.0037; by question -0.0040 to +0.0140 (p 0.184); by source x week -0.0041 to +0.0148 (p 0.193); primary: source x week
- combined minus price (Brier): -0.0001; by question -0.0032 to +0.0038 (p 0.512); by source x week -0.0031 to +0.0037 (p 0.535); primary: question
- panel minus price (log loss): +0.0121; by question -0.0075 to +0.0371 (p 0.115); by source x week -0.0077 to +0.0394 (p 0.128); primary: source x week

## H8: extremizing (exploratory since session E1)

Fitted a: data-series 1.46, market 1.61.
Brier gain on the 200 sealed (a = 1 minus fitted a): +0.0014; by question -0.0034 to +0.0056 (p 0.281); by source x week -0.0028 to +0.0053 (p 0.253); primary: question.

## Correlations of forecast errors

*market (100 sealed)*

| pair | r | by question | by source x week | primary |
|---|---|---|---|---|
| Haiku-Luna | 0.91 | 0.81 to 0.99 | 0.80 to 0.99 | source x week |
| Haiku-Sonnet | 0.99 | 0.99 to 1.00 | 0.99 to 1.00 | source x week |
| Haiku-Sol | 0.98 | 0.97 to 1.00 | 0.96 to 1.00 | source x week |
| Luna-Sonnet | 0.91 | 0.80 to 0.99 | 0.80 to 0.99 | source x week |
| Luna-Sol | 0.91 | 0.80 to 0.98 | 0.80 to 0.98 | source x week |
| Sonnet-Sol | 0.99 | 0.98 to 1.00 | 0.98 to 1.00 | source x week |

*data-series (100 sealed)*

| pair | r | by question | by source x week | primary |
|---|---|---|---|---|
| Haiku-Luna | 0.97 | 0.93 to 0.99 | 0.92 to 0.99 | source x week |
| Haiku-Sonnet | 0.98 | 0.95 to 1.00 | 0.94 to 1.00 | source x week |
| Haiku-Sol | 0.98 | 0.95 to 1.00 | 0.95 to 1.00 | source x week |
| Luna-Sonnet | 0.98 | 0.97 to 0.99 | 0.96 to 0.99 | source x week |
| Luna-Sol | 0.98 | 0.96 to 0.99 | 0.96 to 0.99 | source x week |
| Sonnet-Sol | 1.00 | 1.00 to 1.00 | 1.00 to 1.00 | source x week |

Repeat correlation of errors within a source (mean over call pairs; Sonnet and Sol from their second calls): Haiku 1.00 (n 200), Luna 0.95 (n 200), Sonnet 0.99 (n 100), Sol 1.00 (n 100).

## Freeze date minus each vendor's training cutoff (days)

| kind | Claude | Luna | Sol |
|---|---|---|---|
| data-series | -5 / 37 / 85 | 25 / 67 / 115 | 56 / 98 / 146 |
| market | -5 / 37 / 85 | 25 / 67 / 115 | 56 / 98 / 146 |

Each cell is min / median / max. Every resolution date is after all three cutoffs.
