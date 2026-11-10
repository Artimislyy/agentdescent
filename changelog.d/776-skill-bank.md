Added
`agentdescent skills report|audit|search`: a durable skill bank with an outcome
ledger (`uses`/`successes`/`failures`), a bank-relative lift audit that
quarantines underperforming skills (read-only unless `--apply`), active-only
retrieval through the artifact graph, and explicit retire/activate lifecycle
states. The store is an atomically written JSON snapshot; no model or network
call is made.
