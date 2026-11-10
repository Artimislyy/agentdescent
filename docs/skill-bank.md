# Skill bank — outcome ledger, drift audit and retrieval

A self-evolving skill library fails silently when it only grows. Skills that
worked in one context linger, get retrieved everywhere, and turn into
false-positive injections; a useful skill that was never measured has no
evidence either way. `agentdescent.skill_bank` keeps the outcome ledger and the
lifecycle decision in one durable file.

```bash
agentdescent skills report --store skills.json
agentdescent skills audit  --store skills.json --min-uses 5 --min-lift 0.0
agentdescent skills audit  --store skills.json --min-uses 5 --apply
agentdescent skills search --store skills.json --query "money format" --k 5
```

## The record

```json
{
  "skill_id": "csv-cents",
  "text": "Express monetary amounts as integer cents.",
  "kind": "skill",
  "uses": 8,
  "successes": 7,
  "failures": 1,
  "status": "active",
  "tags": ["money"]
}
```

`uses = successes + failures` is enforced. A skill is `active`, `quarantined`
or `retired`; only active skills are returned by `search`.

## The audit

`baseline` is the bank-wide success rate. Each skill's `lift` is its own
success rate minus that baseline; a skill with fewer than `--min-uses`
observations is reported as `insufficient` rather than judged. A skill at or
above `--min-lift` is kept; below it is `quarantine`. Without `--apply` the
audit is a report; with `--apply` the new status is persisted. `retire` is an
explicit lifecycle action (for a skill you no longer want at all).

This is a deterministic, model-free proxy for contribution, not a causal
leave-one-out experiment. It catches the common drift (a skill that keeps losing
relative to the bank) cheaply; a stronger attribution study can replace the
`lift` rule without changing the record or the CLI.

## Retrieval

`search` builds an in-memory `ArtifactGraph` over the active skills and returns
the same IDF-overlap hits the artifact graph uses elsewhere. Quarantined and
retired skills are never retrieved, so a bad skill does not keep being injected
while its record stays available for audit.

## Boundaries

- The bank does not generate skills (EvoSkill/SkillOpt do) and does not decide
  acceptance (the merge/verification path does); it records outcomes and owns
  the active/quarantined/retired lifecycle.
- The store is a single-writer JSON snapshot written atomically, like the
  workspace registry; concurrent writers need their own lock or a real database.
- `retire` / `activate` are library calls; v1 has no CLI verb for them (the
  audit's `--apply` is the only lifecycle write).
- `baseline` counts every skill's outcomes, including quarantined and retired
  ones, so a large inactive cohort still shapes the bar.
- No model or network call is made by any verb.
