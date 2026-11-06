Fixed
Directory `apply` backups (both `EvolutionResult.write_to` and
`apply --from`) now land under `$AGENTDESCENT_HOME/backups/` instead of a
sibling `<path>.bak-N`, so host skill scanners (OpenCode, Claude Code) no longer
load the backup and shadow the evolved skill (#758).
