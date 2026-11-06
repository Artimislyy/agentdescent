# HGM — the expand-vs-evaluate scheduler

The Huxley-Gödel Machine (arXiv:2510.21614) chooses between **expanding** a node
in the self-modification tree (propose a child) and **evaluating** a node on a
fresh task. The framework already ports HGM's expansion rule as
`selection.CladeThompson`; this page covers the missing half: the evaluation
policy and the budget split between the two actions.

```bash
agentdescent hgm next   --tree hgm-tree.json --json
agentdescent hgm report --tree hgm-tree.json --json
```

## The rule

With `n_task_evals` measurements spent, `N` nodes and `alpha` (default `0.5`):

```text
if n_task_evals ** alpha >= N - 1:
    expand a node chosen by Thompson sampling on its clade evidence
else:
    evaluate a node chosen by Thompson sampling on its own evidence,
    on a task it has not seen
```

The clade evidence is the node's own raw utility measures while it has fewer
than `n_pseudo` evaluations; once it has at least that many it collapses them to
`n_pseudo` copies of its mean, then adds every descendant's measures. This is
the upstream `get_pseudo_decendant_evals` rule. Thompson sampling
draws `Beta(1 + successes, 1 + failures)`; with `cool_down` the parameters are
multiplied by `max_task_evals ** beta / (max_task_evals - used) ** beta` so the
search narrows onto the most metaproductive clade as the budget runs out.

An expansion is eligible only when the node's own mean utility is finite and
positive, matching upstream `hgm.py::expand`. `hgm next` returns `stop` when the
budget is spent or every node has submitted every task.

## The tree JSON

```json
{
  "schema_version": 1,
  "config": {"alpha": 0.5, "beta": 0.5, "max_task_evals": 100,
             "n_pseudo_descendant_evals": 10, "eval_random_level": 0.5,
             "seed": 0},
  "total_tasks": ["t1", "t2", "t3"],
  "n_task_evals": 2,
  "nodes": [
    {"node_id": "initial", "parent_id": null, "commit_id": "abc",
     "utility_measures": [1, 0], "submitted_tasks": ["t1", "t2"]},
    {"node_id": "child-1", "parent_id": "initial", "commit_id": "def",
     "utility_measures": [1], "submitted_tasks": ["t3"]}
  ]
}
```

`hgm next` is read-only: it tells a caller what to do next. The caller records
the result (`HGM.record_expansion` / `HGM.record_evaluation`) and asks again.
This keeps the scheduler deterministic and testable; wiring it into a specific
harness loop is a separate caller concern.

## Boundaries

- This is the scheduler, not the benchmark. It does not edit agents, run
  Docker, or call a model.
- Utility measures are binary/`[0, 1]` outcomes; a non-finite or out-of-range
  value is refused.
- `CladeThompson` remains the `evolve()` selection policy; this planner is for
  a tree loop that owns both expand and evaluate actions.
