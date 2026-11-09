Fixed
`agentdescent github publish` now reads the repository's `default_branch` and
refuses a proposal that names it, even when the proposal's own base is another
branch. An existing proposal branch is only fast-forwarded: a rewritten history
raises one `GitHubError` and nothing is written, and no ref update is ever sent
with `force: true` (#913).
