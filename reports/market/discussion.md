### What the decisions say

1. **M2: "sane" fired (MT1).** Claude traders allocate units in a double auction better than budget-constrained random traders, and close to the competitive allocation. Prices, however, do not converge to P*. Under the preregistered rule, a firm-vs-market follow-up is worth proposing to Kevin; it is not started without him. It would first need two things:
    - the rules' price example replaced by a neutral one;
    - enough sessions to detect a difference of about 7 points.
2. **M4: no exploitation found (MT3).** Sonnet's edge over Haiku in a shared market is about 5 points of competitive-equilibrium profit. That is inside the label noise measured on all-Haiku sessions, and it comes mostly from price, not from crowding Haiku out of trades. Four sessions set no design rule. No larger M4 is proposed.
3. **M3: not shown (MT2).** In all-Sonnet markets the larger model shows no efficiency penalty at this n, but 2 sessions against 4 cannot rule one out. The trade count difference is Sonnet avoiding extramarginal trades. The waiting measures are too thin to read. This neither refutes nor reproduces Struski et al.'s GPT Large result.

### What this does not show

- **Small n.** 4, 4 and 2 sessions.
    - Session-resampled intervals are too narrow at this size, so the t-intervals are shown next to them.
    - No t-interval is shown for M3 alone (n = 2).
    - Every "not shown" here is a statement at this n.
- **A possible prompt anchor.** The rules give "1.85" as the example price format. $1.85 is the most common trade price in M4 and M3, and {{value:llm_periods_below_pstar}} LLM periods price below P*, while ZI-C on the same engine prices at P*. The below-P* bias and the buyer advantage may be partly an artifact of the prompt. A rerun with a neutral example would separate the two; it is free to write and was not preregistered.
- **The R = 8 limit.** Each trader gets at most 8 turns per period, against about 13.6 in Struski's design. That favours traders who act early and may hide waiting that a longer period would expose.
- **Comparability.** The budget rule is enforced here (Struski only states it). Traders see only the last 10 prices and the earlier period means, not the full order history. So these numbers are new measurements on Claude models, not replications of Struski et al.

### Process

- **Reviews.** The plan was preregistered before any paid call. The auditor reviewed every paid run (audits 26-37) and recomputed every decision from the raw data. Three adjustments came from audits:
    - format stops checked per model;
    - a reply cut off by the token cap counts as unparsed (one Haiku reply cut at "ASK 2." had been read as $2.00 and rejected);
    - analysis fixes.
- **A restart.** The container restarted once during M2 session 14. The paid calls survived in the working tree, were committed first, and the rerun replayed them from the cache, so nothing was billed twice.
- **Spend.** Actual spend ran at about 0.2x the governor's worst case throughout.
