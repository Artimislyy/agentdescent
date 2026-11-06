Fixed
`--budget` / `budget_usd` is only checked between rounds: `plan`, `evolve`, and
MCP `start` now warn when the budget is below the seed+one-round call upper
bound (so the first round alone can overshoot), and the plugin quickstart /
plugins docs match that semantics (#764).
