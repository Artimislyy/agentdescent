# MCP / CLI Path A — doctor → plan → start → apply

Host agents and humans share one default loop. Everything else is advanced and
stays out of the default MCP discovery set so a host model is not flooded with
~39 equal tools (#803).

## Path A tools (default MCP listing)

| Tool / verb | Role |
|---|---|
| `doctor` | What this machine can run (CLIs, keys, installs). Call first. |
| `list_algorithms` / `describe_algorithm` | Discover Algorithm **cards** (optional; filter by `kind`). |
| `algorithm_spec` | Build + plan a starter spec for one named card (does not start). |
| `plan` | Validate the EvolveSpec and estimate cost; show the user; get a yes. |
| `start` | Detach a run; returns `run_id` immediately. |
| `status` | Poll progress (about once per round). |
| `show` | Evolved artifact + diff when done. |
| `apply` | **Destructive** — write the artifact back (after user yes). |
| `cancel` / `resume` | Stop or continue a live run. |
| `diagnose` | Why a finished run learned nothing (or stopped). |

CLI Path A verbs match: `doctor`, `init`/`algorithms run`, `plan`, `evolve`,
`status`/`watch`, `show`, `apply`, `cancel`, `resume`, `algorithms list|show`.

```
doctor  →  write a spec  →  plan (show the user)  →  start  →  status  →  show  →  ask  →  apply
```

## Advanced (opt-in)

Audit, release, platform, capability, ops, experience, tenant, meta_campaign,
governed_harness, portfolio, safety, rsi, traces_digest, and the other satellites
keep the **same names and contracts**. They are registered only when:

```bash
agentdescent mcp --advanced
# or
AGENTDESCENT_MCP_ADVANCED=1 agentdescent mcp
```

Hosts that already call advanced tools should set the flag (or env) on the MCP
server entry `install` wrote. Default Path A does not remove those tools from
the package — only from the default discovery list.

## Where this is documented for hosts

- Shared skill: `agentdescent/integrations/SKILL.md` (Path A first).
- Install / plugin page: [plugins.md](plugins.md).
- Module-level product map (evolve vs release vs platform): [main-path.md](main-path.md).
