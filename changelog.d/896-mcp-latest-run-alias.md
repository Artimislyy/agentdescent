Fixed
`show_payload` / `status_payload` / `apply_payload` and the MCP `show` / `status` / `apply` / `diagnose` / `cancel` / `resume` tools accept `latest` (or `last`) the same way the CLI does, so a host that asks to show the newest run no longer gets `no run 'latest'` (#896).
