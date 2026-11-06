Changed
`aggregator_factory=` now forwards merge-side `Policies` into the factory and
applies them on aggregators that expose the slots; leaving them unused raises
unless `accept_orphaned_merge_policies=True`. GEPA and SkillOpt factories honour
`acceptance` / `fusion` (#807).
