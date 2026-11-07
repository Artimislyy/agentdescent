# Named algorithms

*Generated from `agentdescent.algorithms`; do not edit by hand.*

These are the methods a spec (or `agentdescent init`) can ask for by
name. An algorithm contributes **defaults** — policies, `evolve()`
knobs, an `agg_config` — that the same spec can override field by field.
The default recipe for a `kind` is used when no algorithm is named, and
`plan` always echoes what was resolved.

```bash
agentdescent algorithms [--kind K] [--json]      # same as `algorithms list`
agentdescent algorithms list [--kind K] [--json]
agentdescent algorithms show NAME
agentdescent algorithms run NAME PATH [cases.jsonl] [--param k=v...] [--rounds N] [--workers N]
agentdescent init PATH --algorithm NAME --param KEY=VALUE [--rounds N] [--workers N]
```

`--rounds 1 --workers 1` turns the kind's default plan (for a text prompt,
8 rounds x 8 workers) into a quick trial without editing the spec.

Include cases the seed gets wrong: if the seed already scores
the target on held-out, the run stops at once with
`held-out reward: 1.000 -> 1.000`, nothing is learned, and
`diagnose` reports `seed-already-solved`.

These rows are Algorithm **cards** (`surface=card`) shipped in the
wheel — Path A's catalog (**cards-only contract**, #384). MethodPolicy / full ports are not listed here. A same-name [`examples/<algo>/`](https://github.com/ThinkFlowLab/agentdescent/tree/main/examples)
research port is a separate, source-only script and may use a different
propose/strategy path — see [port fidelity](port-fidelity.md). Filter with
`--kind` so hosts are not offered cards that cannot run on that artifact.

To **register one named card in a single PR**, follow
[Register a named Algorithm card](algorithm-authoring.md).
Full research ports still use the
[porting checklist](porting-checklist.md); MethodPolicy microports use
[porting-methodpolicy.md](porting-methodpolicy.md).

## `ace`

ACE's sectioned playbook: append content-addressed lessons, refuse near-duplicates, and grow-and-refine instead of gating each bullet on held-out reward.

- **Kinds:** `text`
- **Fidelity:** `mechanism_microport`
- **Surface:** `card` (Algorithm card)
- **Cost:** none (one reflection call per failed rollout, as the default recipe)
- **Research port:** `examples/ace/` — separate source-only path; Algorithm card (mechanism_microport) — not the benchmark-faithful research port at examples/ace/ (docs/port-fidelity.md). Same name, different propose/strategy path.
- **Source:** ACE: Agentic Context Engineering (Zhang et al., 2025)
- **Details:** [algo-ace.md](algo-ace.md)
- **Spec:** `"algorithm": "ace"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `title` | `str` | `# Playbook (ACE)` | rendered playbook title |
| `dedup_threshold` | `float` | `0.8` | Jaccard similarity at or above which a same-section lesson is a duplicate |

## `archive_selection`

Parent sampling from an archive of every accepted candidate, tempered by novelty (DGM's rule by default) instead of always extending the head.

- **Kinds:** `text`, `skill_dir`, `skill_library`, `agent_dir`, `agent_code`, `plugin`
- **Fidelity:** `preset`
- **Surface:** `card` (Algorithm card)
- **Cost:** none
- **Source:** Darwin Gödel Machine (choose_selfimproves), ADAS archive, SICA best-agent
- **Spec:** `"algorithm": "archive_selection"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `sampling` | `str` | `sigmoid_novelty` | sigmoid_novelty: Darwin Gödel Machine's rule, sigmoid(10*(score-0.5)) / (1+times chosen); novelty: softmax over score divided by (1+times chosen); performance: softmax over score; best: always the top scorer (SICA); uniform: the ablation |
| `temperature` | `float` | `1.0` | softmax temperature for performance / novelty; must be > 0 |
| `seed` | `int` | `0` | seed of the parent draw |

## `dgm`

Darwin Gödel Machine's open-ended archive: keep every capability self-modification and sample the next parent by sigmoid(score) × 1/(1+times chosen).

- **Kinds:** `text`
- **Fidelity:** `mechanism_microport`
- **Surface:** `card` (Algorithm card)
- **Cost:** one reflection call per failed rollout; each candidate is scored on the held-out set
- **Research port:** `examples/dgm/` — separate source-only path; Algorithm card (mechanism_microport) — not the benchmark-faithful research port at examples/dgm/ (docs/port-fidelity.md). Same name, different propose/strategy path.
- **Source:** Darwin Gödel Machine (Zhang et al., 2025); see docs/algo-dgm.md
- **Details:** [algo-dgm.md](algo-dgm.md)
- **Spec:** `"algorithm": "dgm"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `seed` | `int` | `0` | seed for the parent draw |
| `archive_mode` | `str` | `keep_all` | keep_all keeps stepping stones; keep_better drops a child that does not beat its parent |
| `failure_threshold` | `float` | `0.8` | only rollouts below this reward induce a capability |

## `evoskill`

EvoSkill's two-role skill induction: Proposer analyses a failure batch, Generator writes one SKILL.md, and a bounded top-K frontier keeps the best skill libraries.

- **Kinds:** `skill_dir`, `skill_library`, `agent_dir`, `plugin`
- **Fidelity:** `mechanism_microport`
- **Surface:** `card` (Algorithm card)
- **Cost:** two model calls per induced skill; one full held-out re-eval per admitted candidate
- **Research port:** `examples/evoskill/` — separate source-only path; Algorithm card (mechanism_microport) — not the benchmark-faithful research port at examples/evoskill/ (docs/port-fidelity.md). Same name, different propose/strategy path.
- **Source:** EvoSkill: skill discovery (see docs/algo-evoskill.md)
- **Details:** [algo-evoskill.md](algo-evoskill.md)
- **Spec:** `"algorithm": "evoskill"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `max_frontier` | `int` | `5` | frontier size |
| `batch_size` | `int` | `4` | failures per induction batch |
| `eval_concurrency` | `int` | `8` | held-out re-evaluations run in parallel |

## `gepa`

GEPA's genetic reflective loop: keep a Pareto pool of candidates scored per instance and mutate a win-frequency-selected parent instead of the single best average.

- **Kinds:** `text`
- **Fidelity:** `mechanism_microport`
- **Surface:** `card` (Algorithm card)
- **Cost:** every admitted candidate is scored over the full held-out set once (the Pareto row); no extra reflection calls
- **Research port:** `examples/gepa/` — separate source-only path; Algorithm card (mechanism_microport) — not the benchmark-faithful research port at examples/gepa/ (docs/port-fidelity.md). Same name, different propose/strategy path.
- **Source:** GEPA: Reflective Prompt Evolution (Agrawal et al., 2025); arXiv:2507.19457
- **Details:** [algo-gepa.md](algo-gepa.md)
- **Spec:** `"algorithm": "gepa"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `seed` | `int` | `0` | seed for the Pareto parent draw |
| `eval_concurrency` | `int` | `8` | per-instance scorings run in parallel when a candidate enters the pool |

## `rrsi`

Regularized recursive self-improvement: an annealed edit budget, a leakage screen before measurement, and a historical-best acceptance floor.

- **Kinds:** `text`
- **Fidelity:** `mechanism_microport`
- **Surface:** `card` (Algorithm card)
- **Cost:** none (the reflection model proposes as it would anyway; the screen is deterministic and runs before any held-out sweep)
- **Source:** Google RRSI (regularized harness selection); docs/algo-rrsi.md
- **Details:** [algo-rrsi.md](algo-rrsi.md)
- **Spec:** `"algorithm": "rrsi"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `beta0` | `float` | `0.0` | large-gain cost rule: tolerance |
| `beta1` | `float` | `0.0` | large-gain cost rule: slope |
| `w_s` | `float` | `1.0` | within-band score weight |
| `w_c` | `float` | `1.0` | within-band cost weight |
| `w_n` | `float` | `0.0` | within-band novelty weight |
| `noise_band` | `float` | `0.0` | historical-best floor tolerance (score >= S* - noise_band); the paper estimates it by re-evaluating the unchanged base |
| `b_min` | `int` | `1` | smallest edit budget (independent edits per candidate) |
| `b_max` | `int` | `5` | largest edit budget, at the start of the anneal |
| `T` | `int` | `20` | rounds the edit budget anneals over |
| `stall_window` | `int` | `5` | rounds without movement of S* that count as a stall |
| `prune_window` | `int` | `5` | rounds of component yield a component must show gain over to stay |
| `max_history_chars` | `int` | `1500` | how much per-edit history fits in the reflection prompt |
| `protected` | `list[str]` | `[]` | strings that must not leak into the artifact: task ids, gold answers, names from the evolve set (never the final holdout). A candidate containing one is rejected before it is measured |
| `base_score` | `float` | `0.0` | the base artifact's evolve-set score, to seed the historical-best floor S* (0 keeps the floor at the first measurement) |

## `skillopt`

SkillOpt's skill-document training: bounded edit patches, a strict held-out gate, a rejected-edit buffer and an annealed textual learning rate.

- **Kinds:** `text`
- **Fidelity:** `mechanism_microport`
- **Surface:** `card` (Algorithm card)
- **Cost:** one analyst call per failed rollout; the strict gate scores each candidate over the full held-out set
- **Research port:** `examples/skillopt/` — separate source-only path; Algorithm card (mechanism_microport) — not the benchmark-faithful research port at examples/skillopt/ (docs/port-fidelity.md). Same name, different propose/strategy path.
- **Source:** SkillOpt: skill-document training; see docs/algo-skillopt.md
- **Details:** [algo-skillopt.md](algo-skillopt.md)
- **Spec:** `"algorithm": "skillopt"`

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `max_lr` | `int` | `4` | largest edit budget per step |
| `min_lr` | `int` | `2` | smallest edit budget per step |
| `total_steps` | `int` | `8` | steps the budget anneals over (independent of evolve rounds; past this, budget stays at min_lr) |
| `mode` | `str` | `cosine` | anneal schedule |
