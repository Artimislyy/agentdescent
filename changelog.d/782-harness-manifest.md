Added
`agentdescent harness manifest|check` and `HarnessManifest`: a file-level
component contract for harness evolution. Components name path globs, an RRSI/SHE
responsibility, editable/frozen state and per-component file/line budgets; the
manifest also has global budgets, allowed/forbidden paths and a `FileTree` kwargs
projection. `check` fails closed on frozen, forbidden, unowned or over-budget
edits; no model or network call is made.
