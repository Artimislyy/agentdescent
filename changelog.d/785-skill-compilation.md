Added
`agentdescent compile-skill` and `compile_skill`: turn a skill document into a
single tested function through a caller-supplied `text -> source` compiler,
behind the framework AST gate, with repeatable tests and optional
reference/case equivalence. Any gate, test or equivalence failure returns
`status: "text"` with a reason and leaves the skill document as the fallback; no
model or network call is made by the module.
