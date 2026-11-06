# Edit predictions — declare the effect, then falsify it

A proposal that says *what* it changes but not *what it expects* is hard to
audit: a lucky edit and a reasoned one look identical afterwards. The
prediction log closes that gap. A proposer writes its expected effect **before**
the held-out evaluation, the evaluation records the observed effect afterwards,
and the report scores the calibration.

```bash
agentdescent predictions predict --store predictions.jsonl \
  --artifact-id skill-csv --diff-id d1 \
  --delta 0.10 --confidence 0.8 \
  --tasks t7,t8 \
  --rationale "the cents rule covers both failing tasks"

agentdescent predictions observe --store predictions.jsonl \
  --prediction-id <id> --delta 0.09 --tasks t7,t8 --tolerance 0.02

agentdescent predictions report --store predictions.jsonl --json
```

## What a prediction contains

| field | meaning |
|---|---|
| `expected_delta` | expected change in held-out reward |
| `confidence` | 0..1 confidence that the prediction will hold |
| `expected_tasks` | task ids expected to flip (optional) |
| `rationale` | why the proposer expects this, for the audit trail |

The log is append-only JSONL. A prediction is written first; an observation is
appended later. A prediction with no observation stays `pending`, and the first
prediction/observation for an id wins, so appending a second row cannot rewrite
the expectation. A malformed row is skipped and counted in `skipped`; it does
not poison the rest of the report.

## How a prediction is scored

- `hit` is true when `|observed - expected| <= tolerance`; when
  `expected_tasks` is non-empty, the observed task set must also **exactly**
  match the predicted set.
- `delta_error`, `task_overlap`, `abs_error` and `brier`
  (`(confidence - hit)^2`) are stored with every observed record.
- `report` returns `predictions`, `observed`, `pending`, `skipped`, `hit_rate`,
  `mean_brier`, `mean_abs_error`, `mean_delta_error`, `task_exact_rate`,
  `falsified`, the last record and five confidence buckets with their observed
  hit rate.

`task_exact_rate` is computed only over observations that declared
`expected_tasks`; a prediction that declared no tasks is not punished for
observed flips it never claimed. High confidence with a miss is expensive in
Brier score; that is the point.
A proposer that is often overconfident should be recalibrated, down-weighted or
asked to gather more evidence before proposing.

## Where it fits

This is the **decision-observability** half of the harness loop: the trajectory
digest (`traces`) says what happened, the prediction log says what the proposer
expected, and the mismatch is the signal a reflector should read. It does not
call a model, generate a proposal or decide acceptance; the caller must record
the prediction before measuring and the observation after.

Because the file is append-only and single-writer, serialize concurrent writers
or give each run its own log and merge the reports later.
