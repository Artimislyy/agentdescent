Fixed
`PopulationAggregator` now archives per-task held-out scores and fills
`Candidate.per_task`, so `Policies(selection=ParetoFrontier(...))` can run
GEPA-class parent selection without `aggregator_factory=` (#806).
