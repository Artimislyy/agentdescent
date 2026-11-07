Changed
`evolve(asynchronous=True)` is a deprecated bridge to `async_evolve`: it now
requires explicit `max_seconds` and `max_rollouts` (no silent 20s default, no
`rounds` reinterpretation) and emits `FutureWarning`. Policies wiring is one
shared `_POLICY_DRIVER_SUPPORT` table for both drivers (#809).
