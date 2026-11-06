Changed
`ProposalPolicy` may return multiple strings: `evolve` / `async_evolve` ingest
each as its own evidence card, pass `ctx.k` from `policy.k`, and no longer raise
`ProposalContractError` on `len > 1`. Self-verify, when enabled, runs per
proposal (#808).
