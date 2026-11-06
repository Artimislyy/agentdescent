Changed
The MCP server now exposes **Path A** by default (doctor → plan → start → status/show → apply, plus cancel/resume, diagnose, and algorithm list/describe/spec). Audit, release, platform, experience and the other satellites stay callable with the same names when `agentdescent mcp --advanced` or `AGENTDESCENT_MCP_ADVANCED=1` is set. Docs: `docs/mcp-path-a.md`.
