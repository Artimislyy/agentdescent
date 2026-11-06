Added
`agentdescent predictions predict|observe|report`: an append-only prediction log
that pairs a proposal's expected delta, confidence and expected flipped tasks
with the later observation. Observations score hit/miss, delta error, task
overlap and Brier, and the report aggregates hit rate, calibration buckets and
falsified predictions. Predictions written before measurement stay pending until
observed; no model or network call is made.
