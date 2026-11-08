Fixed
`agentdescent diagnose` now names the runnable next command with the resolved run id for `solved` (`show <id>`, `apply <id> --dry-run`), `cancelled` (`resume <id>`), `running` (`watch <id>`) and `partial-improvement` (`show <id> --json`), instead of prose such as "review and apply the artifact" (#898).
