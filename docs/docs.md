---
description: Find the right AgentDescent guide, from a first run inside Claude Code or Codex to custom strategies, policy slots, runtime and algorithm ports.
---

# Documentation

Choose the route that matches what you want to do. Each guide links to the deeper reference when you need it.

<div class="ad-doc-paths">
  <a href="../install/"><span>01 / START</span><strong>Use it in your agent</strong><small>Install AgentDescent, connect Claude Code, Codex, OpenCode or DeepSeek Harness, and review your first change.</small><b>Open Quickstart ↗</b></a>
  <a href="../#demo"><span>02 / TRY</span><strong>See the interaction</strong><small>Walk through a sample agent conversation in the interactive demo on the homepage.</small><b>Try the demo ↗</b></a>
  <a href="../main-path/"><span>03 / MAP</span><strong>Read the supported path</strong><small>Three paths, the advanced layers, and the canonical module for each concept.</small><b>Open the main path ↗</b></a>
  <a href="../self-evolution-examples/"><span>04 / STUDY</span><strong>Browse 23 algorithm ports</strong><small>See how published methods fit different artifact types and algorithm choices.</small><b>Browse methods ↗</b></a>
</div>

## The three supported paths

| path | you have | the product surface |
|---|---|---|
| **A — evolve one artifact** | tasks, a reward, an actor | `agentdescent plan/evolve/status/show/apply` |
| **B — governed release** | paired held-out scores | `agentdescent release` + `release verify` |
| **C — continuous platform** | a run database and callbacks | `agentdescent platform` + `platform status` |

Read [the main path](main-path.md) first if you are deciding where a new
capability belongs; it is the design contract, not another module list.

## Product surfaces

| surface | verbs | guide |
|---|---|---|
| release | `release`, `release verify` | [Release a candidate](release.md) |
| traces | `traces digest/show` | [Trajectory evidence](traces.md) |
| governed harness | `governed-harness plan/run/approvals/approve/reject` | [Governed harness](governed-harness.md) |
| tenant | `tenant plan/run/report` | [Tenant cycle](tenant.md) |
| operations | `ops plan/publish/history` | [Operations console](ops.md) |
| platform | `platform init/plan/run/status` | [The RSI platform cycle](platform.md) |
| capability growth | `capability init/plan/run` | [Capability loop](capability-loop.md) |

These are product surfaces over the same `evolve()` engine, not separate
algorithms. Each returns `schema_version: 1` and fails closed under `--json`.

## Go deeper

**Understand the model.**
[Core concepts](concepts.md) · [Architecture](architecture.md) ·
[Data model](data-model.md) · [Governance](governance.md) ·
[Capability map](capabilities.md) · [Main path](main-path.md).

**Build an evolution loop.**
[The `evolve()` method](evolution.md) · [Strategies](strategies.md) ·
[Policies](policies.md) · [Policy guide](policy-guide.md) ·
[Aggregators](aggregator-factory.md) · [Directory evolution](directory-evolution.md).

**Run and operate it.**
[Parallelism](parallelism.md) · [Async](async.md) · [Execution](execution.md) ·
[Sandboxes](sandboxes.md) · [Budget](budget.md) · [Loop kernel](loop-kernel.md) ·
[Runtime](runtime.md) · [Controller](controller.md) · [Diagnose](diagnose.md) ·
[Trajectory evidence](traces.md) · [Metrics](metrics.md) · [Module audit](module-audit.md).

**Trust, release and govern.**
[Verifier](verifier.md) · [Sparse audit](audit.md) ·
[Statistical evidence](stats-eval.md) · [Trusted promotion](trusted-promotion.md) ·
[Trusted evidence](trust-evidence.md) · [Release](release.md) ·
[Approval](approval.md) · [Safety](safety.md) · [Risk policy](risk-policy.md) ·
[Decision log](decisions.md) · [Manifest](manifest.md).

**Study the methods and measurements.**
[23 self-evolution ports](self-evolution-examples.md) · [Results](results.md) ·
[Efficiency](efficiency.md) · [Runtime matrix](matrix-overview.md) ·
[Harness composition](harness-composition.md) · [Consolidation](consolidation.md) ·
[Self-improvement](self-improve.md) · [Longitudinal RSI](rsi.md).

**Reference and host integration.**
[API reference](api.md) · [Agents](agents.md) · [Plugins](plugins.md) ·
[Plugin quickstart](plugin-quickstart.md) · [Set it up and test it](testing-guide.md) ·
[Usage](usage.md).
