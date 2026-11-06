Fixed
`plan` / `evolve` / MCP start now hard-refuse a bare isolated `opencode` worker
when a gateway key (e.g. `ARK_API_KEY`) is set, instead of soft-warning and then
burning calls on OpenCode's unactivated Volcengine default. Init/`algorithms run`
warnings say filling `reflect` alone is not enough — pass `--model` / `--base-url`
(or write the Coding recipe). Wired `--model`/`--base-url` specs stay green (#790).
