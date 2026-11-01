Every paid LLM call, append-only. Tracked in git so a reclaimed cloud container cannot reset the budget.
Never edit or delete these files by hand.

- ledger.jsonl: one line per paid call (account, model, tokens, cost). `aan bill` / `aan status` read it.
- cache/: gzipped shards of every agent output, so a repeated call is free.
