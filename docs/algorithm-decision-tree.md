# Which path: card vs MethodPolicy vs full port vs `aggregator_factory`

Usability pillars: **call any algorithm**, **quickly implement a new one**.
This page is the map. Same name ≠ same fidelity — an Algorithm **card** such as
`"algorithm": "gepa"` is not the `examples/gepa/` research port
([port fidelity](port-fidelity.md), #384).

## Decision tree

| If you need… | Prefer… | Fidelity / surface | Example |
|---|---|---|---|
| Swap one decision rule (selection / acceptance / merge / …) on the **single-head** loop | `Policies` / SHORT_REFS / a small Algorithm **card** | `preset` or `mechanism_microport`; `surface=card` | [`archive_selection`](algorithms.md) card; [register a card](algorithm-authoring.md) |
| Paper method with custom propose/solve/reward but still a single-head Policies loop | **MethodPolicy** microport under `examples/` | `mechanism_microport` (matrix) | [porting-methodpolicy.md](porting-methodpolicy.md); e.g. Reflexion, TextGrad scripts |
| Multi-head / population / Pareto archive / keep-all search that the ledger head cannot express | `aggregator_factory=` (or a card that sets one) | Usually `mechanism_microport` on the card; paper numbers stay on the full port | GEPA / DGM / SkillOpt / EvoSkill **cards**; see [aggregator-factory.md](aggregator-factory.md) |
| Reproduce paper numbers on fixed data | Full `examples/<algo>/` **research port** | `benchmark_faithful` | `python -m examples.gepa…` from a source checkout ([porting-checklist.md](porting-checklist.md)) |

```text
need a name hosts can pick? ──yes──► Algorithm card (this package / wheel)
        │                              filter by kind; plan echoes fidelity
        │
        no (research only)
        │
        ├── single-head + custom propose/reward ──► MethodPolicy microport
        ├── population / Pareto / keep-all ───────► aggregator_factory
        └── paper numbers on fixed data ──────────► full examples/<algo>/ port
```

## Factory path: which Policies fields still apply

`aggregator_factory=` replaces the shipped merge pipeline. Merge-side
`Policies` slots the default path would wire — especially **`conflict`**,
**`fusion`**, **`acceptance`**, **`promotion`** — do **not** reach a
factory-built aggregator through the bundle unless the factory itself reads
them. Carrying them in both places is a silent drop on the evolve path today;
`plan` warns when it can see the mismatch ([#504](https://github.com/ThinkFlowLab/agentdescent/issues/504)).

Making factory aggregators compose with merge Policies (no silent drop, or a
first-class population API) is tracked as
[#807](https://github.com/ThinkFlowLab/agentdescent/issues/807). Until that
lands: pass merge rules into your aggregator's constructor, strip them from
the bundle, or omit them from the spec.

`selection` + `aggregator_factory` together are **refused** (both fill the
aggregator seat) — that is already loud.

## Worked miniatures

1. **Card (Policies only).** `"algorithm": "archive_selection"` — only parent
   sampling changes; propose / merge / acceptance stay the engine default.
2. **Card (factory).** `"algorithm": "gepa"` — Pareto pool via
   `aggregator_factory`; `plan` notes the merge/acceptance path is replaced;
   fidelity is `mechanism_microport`, not the HotpotQA
   `examples/gepa/` port.
3. **MethodPolicy.** `python -m examples.reflexion…` — custom propose/reward on
   the shared MethodPolicy runner; not in the wheel catalog.
4. **Full port.** `python -m examples.gepa.gepa_prompt_evolution` — paper data,
   paper reward, paper loop; source checkout only.

## Related

- [Register a named Algorithm card](algorithm-authoring.md)
- [Port fidelity](port-fidelity.md) · [Named algorithms](algorithms.md)
- [aggregator_factory exit](aggregator-factory.md)
- [MethodPolicy checklist](porting-methodpolicy.md) · [Porting checklist](porting-checklist.md)
- Engine follow-up: [#807](https://github.com/ThinkFlowLab/agentdescent/issues/807) (factory ⊕ merge Policies)
