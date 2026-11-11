# Harness manifest — components, budgets and frozen safety paths

A harness is not one prompt. It is a system prompt, tool descriptions, tool
implementations, middleware, skills, sub-agents and memory. Rewriting that tree
as one opaque artifact makes attribution and safety impossible: an edit is not
traceable to a component, and the safety-critical files are not frozen.

`agentdescent.harness_manifest` is the file-level contract:

```bash
agentdescent harness manifest --spec harness.json
agentdescent harness check    --spec harness.json --changes changes.json
```

## The manifest

```json
{
  "schema_version": 1,
  "max_files": 10,
  "max_lines": 400,
  "allowed_paths": ["**"],
  "forbidden_paths": ["secrets/**"],
  "components": [
    {"name": "prompt", "paths": ["prompts/**"],
     "responsibility": "system_prompt", "max_lines": 80},
    {"name": "tools", "paths": ["tools/**"],
     "responsibility": "tool_policy", "max_files": 3},
    {"name": "safety", "paths": ["safety/**"], "frozen": true,
     "responsibility": "safety_memory"},
    {"name": "tests", "paths": ["tests/**"], "frozen": true,
     "responsibility": "rule_bank"}
  ]
}
```

`responsibility` mirrors the RRSI component vocabulary (`context_mgmt`,
`client_tool`, `skill`, `memory`, `subagent`) and SHE's safety decomposition:
`system_prompt`, `tool_policy`, `tool_impl`, `rule_bank`, `safety_memory`,
`skill`, `subagent`, `middleware`, `context_mgmt`, `client_tool`, `memory`,
`other`.

`frozen: true` (or `editable: false`) makes every path in the component
read-only. Overlapping globs resolve to the **first** matching component, so
order the safety components before the catch-all ones.

## What `check` validates

`--changes` is a JSON mapping `path -> content` (or a list of paths). The check
is fail-closed and reports every violation in one pass:

- path outside `allowed_paths`, or matching `forbidden_paths`;
- no component owns the path;
- the component is frozen / not editable;
- the component's `max_files` or `max_lines`;
- the manifest's global `max_files` / `max_lines`.

It exits 0 when valid, 1 for a violation and 2 for a malformed manifest or
changes file. `require_valid()` is the same rule as an exception.

## Wiring it into a tree

`manifest.tree_kwargs()` returns the `FileTree` keyword arguments:

```python
from agentdescent import FileTree, load_tree
from agentdescent.harness_manifest import load_manifest

manifest = load_manifest("harness.json")
strategy = FileTree(load_tree("my-agent"), **manifest.tree_kwargs())
```

`editable` is the union of editable component globs, `frozen` the union of
frozen **and** `editable: false` ones. There is no `**` fallback: if every
component is read-only, `editable` is empty. A path outside every component is
not editable by the loop, which is the point: a manifest that does not name a
file cannot silently authorise it. Overlapping globs resolve to the first
matching component, so put safety components before catch-alls.

## Boundaries

- This is the contract and the checker, not the runner. It does not execute the
  harness; `code_runner` / `tree_runner` still own the rollout and the test gate.
- It does not decide acceptance; the existing verifier/promotion path does.
- A single `harness.json` maps one tree. For multiple harnesses, keep one
  manifest per tree and pass the matching `tree_kwargs()`.
