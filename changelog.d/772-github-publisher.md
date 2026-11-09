Added
`agentdescent github publish|status`: publish one accepted candidate as a
proposal branch, commit, pull request and optional check run, and read a PR's
state and checks back. Publishing is a plan by default (`--apply` writes), the
token comes only from an environment variable, the base branch is never written,
and an existing proposal PR is updated rather than duplicated. The PR body
carries the run/artifact ids and evidence hash; there is no auto-approval,
auto-merge or branch-protection change.
