Added
`status`, `watch`, `show`, `apply`, `cancel`, `resume` and `diagnose` accept
`latest` (or `last`) in place of a run id and use the newest run in the store,
so `agentdescent show latest` works straight after a demo; an empty store
says so instead of `no run 'latest'` (#892).
