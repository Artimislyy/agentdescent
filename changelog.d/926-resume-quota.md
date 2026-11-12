Fixed
`agentdescent resume` no longer relaunches a run whose last failure was a spent
provider quota: a `failed` run whose error starts with `QuotaExhausted` is
refused with exit 2 and the provider's own reset time in the message, plus
`--force` to retry anyway, and the status file is left untouched (#926). Only
that case is gated -- a cancelled, bounded or ordinary provider failure still
resumes. The MCP `resume` tool takes `force=true` for the same opt-out.
