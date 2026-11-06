---
description: List, show, or run a named AgentDescent Algorithm card (same as algorithms list/show)
argument-hint: "[list [--kind K] | show <name> | run <name> <path> [cases.jsonl] [--param k=v...]]"
---

Use the agentdescent skill / MCP tools. `$ARGUMENTS` chooses the verb; the data
is the same as `agentdescent algorithms list` / `show` and the MCP tools
`list_algorithms` / `describe_algorithm`. Never invent a name.

These are Algorithm **cards** (wheel mechanism slices, `surface=card`). A
same-name `examples/<algo>/` research port is a separate source-only script and
may use a different propose/strategy path — never claim paper/benchmark
fidelity for a card. Prefer `list --kind <artifact kind>` so ineligible cards
are not offered.

Parse `$ARGUMENTS` (trim; empty means `list`):

- **`list`** [optional `--kind K`]: call `list_algorithms` with the artifact's
  kind when known (or `agentdescent algorithms list [--kind K] [--json]`). Show
  each name, summary, kinds, fidelity, and `surface=card`. Filter by kind so
  hosts are not offered cards that cannot run on that artifact.
- **`show <name>`**: call `describe_algorithm` (or
  `agentdescent algorithms show <name>`). Show the full card (params, defaults,
  extra cost, `research_port` / `fidelity_note` when a same-name examples/ port
  exists). Stop here unless they ask to run it.
- **`run <name> <path>`** [optional `cases.jsonl`] [optional `--param k=v`]:
  call `algorithm_spec` with the name, the absolute path, the absolute cases
  file and only the params they gave (validate with `describe_algorithm` /
  `show` first); it writes and plans the spec and returns `spec`. Run `doctor`
  first, show the resolved algorithm card (including fidelity / surface) and
  estimate, and wait for my yes before `start` with that `spec`. Same
  apply/cancel/resume rules as `/evolve`. Without MCP: `agentdescent algorithms
  run <name> <path> [cases.jsonl] [--param k=v...] [--rounds N] [--workers N]`
  (init + plan; then `evolve` after yes). For a quick trial pass
  `--rounds 1 --workers 1`.

If they only named a method with no path, `show` it and ask whether to `run`.
