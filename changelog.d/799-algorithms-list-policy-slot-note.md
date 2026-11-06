Fixed
`agentdescent algorithms list --kind policy_slot` now prints the same explanation
MCP `list_algorithms` already returns (that kind evolves a policy slot and `plan`
refuses an algorithm), instead of a bare "no algorithms for kind" line. `--json`
keeps the array shape and puts the note on stderr (#799).
