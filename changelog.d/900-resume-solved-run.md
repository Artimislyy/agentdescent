Fixed
`agentdescent resume` (CLI and the MCP `resume` tool) now refuses a run that is already `done [target_reward]` and points at `show <id>` / `apply <id> --dry-run`, instead of relaunching it, spending calls again and overwriting its recorded initial reward and outcomes with the no-op rerun. Runs that stopped on a bound, were cancelled or failed still resume (#900).
