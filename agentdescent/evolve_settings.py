"""Typed settings bags for :func:`evolve` / :func:`async_evolve`.

:class:`~agentdescent.policies.Policies` holds replaceable *pieces*
(selection, acceptance, proposal, …). These bags hold the numeric / flag
surface that kept growing on ``evolve()`` after Policies landed (#804).

**Where a new knob goes**

* Decision / plug-in behaviour → a :class:`~agentdescent.policies.Policies`
  field (or a typed config object that field accepts).
* Spend / stop / wall-clock → :class:`BudgetSettings` (preferred) or a flat
  shortcut onto it.
* Workers / gates / data split / search extras → :class:`RuntimeSettings`.
* Hooks / meters / trajectory recording → :class:`ObservabilitySettings`.
* Do **not** add another top-level ``evolve(...)`` keyword without updating
  :data:`EVOLVE_PARAM_ALLOWLIST` and the docs — the allowlist test fails a PR
  that grows the flat surface by accident.

Flat kwargs remain shortcuts: they keep working for pip callers and for
JSON ``spec.evolve`` knobs. When a bag is passed, an explicit non-default
flat value still wins (same idea as :meth:`Policies.merged_with`).
"""

from __future__ import annotations

from dataclasses import dataclass, fields, replace
from typing import Any, Callable, Dict, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from .agents import Usage
    from .budget import CallBudget
    from .evolution import RoundInfo
    from .trajectory import TrajectoryStore


#: Public ``evolve()`` parameter names frozen as of #804. A PR that adds a
#: raw kwarg must update this set on purpose (and prefer a bag / Policies
#: field instead). ``async_evolve`` has its own surface; this freezes the
#: synchronous entry that Spec / MCP / CLI mirror.
EVOLVE_PARAM_ALLOWLIST = frozenset({
    "tasks", "reward", "agent", "run", "propose", "strategy", "parallel",
    "task_sampler", "initial_state", "blast_radius", "artifact_id", "rounds",
    "n_workers", "max_concurrency", "refresh_interval", "round_timeout",
    "target_reward", "patience", "max_worker_errors", "eval_concurrency",
    "asynchronous", "async_ratio", "resync_on_commit", "pipelined_gate",
    "gate_workers", "max_seconds", "max_rollouts", "max_calls", "max_tokens",
    "stop_on_diminishing_returns", "efficiency_floor", "call_budget",
    "self_verify", "held_out_frac", "repo_path", "checkpointing", "agg_config",
    "staleness_policy", "aggregator_factory", "oracle_budget",
    "cheap_eval_tasks", "fusion_tournament", "solved_threshold", "shuffle",
    "seed", "on_round", "on_reports", "stop_when", "verbose", "usage",
    "policies", "allocator", "record_trajectories", "trajectory_store",
    "contract", "extra_artifacts", "population_islands",
    # typed bags (#804) — preferred home for new numerics / flags
    "budget", "runtime", "observability",
})


#: The short stable contract callers should learn first. Everything else is
#: advanced (Policies, bags, or a documented flat shortcut).
EVOLVE_STABLE_SUBSET = (
    "tasks", "reward", "agent", "run", "propose", "strategy", "policies",
    "rounds", "n_workers", "max_concurrency", "max_seconds", "max_rollouts",
    "max_calls", "max_tokens", "repo_path", "budget", "runtime", "observability",
)



def _resolve(cls: type, bag: Optional[Any], flat: Dict[str, Any]) -> Any:
    base = bag if bag is not None else cls()
    overrides: Dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in flat:
            continue
        val = flat[f.name]
        default = f.default
        if bag is None:
            overrides[f.name] = val
        elif val != default:
            overrides[f.name] = val
    return replace(base, **overrides) if overrides else base


@dataclass(frozen=True)
class BudgetSettings:
    """Spend and stop bounds shared by the sync and async drivers.

    Prefer ``evolve(..., budget=BudgetSettings(...))`` (or
    ``async_evolve(..., budget=...)``) over adding another top-level kwarg.
    Flat ``max_seconds=`` / ``max_rollouts=`` / … remain shortcuts onto these
    fields. On the async path, ``max_rollouts`` is the same quantity
    ``async_evolve`` historically called ``max_iters``.
    """

    max_seconds: Optional[float] = None
    max_rollouts: Optional[int] = None
    max_calls: Optional[int] = None
    max_tokens: Optional[int] = None
    stop_on_diminishing_returns: bool = False
    efficiency_floor: float = 0.25
    call_budget: Optional["CallBudget"] = None
    target_reward: Optional[float] = None
    patience: Optional[int] = None
    oracle_budget: int = 200

    def merged_with(self, **kwargs: Any) -> "BudgetSettings":
        """This bag with any explicit keyword taking precedence."""
        return _resolve(BudgetSettings, self, kwargs)


@dataclass(frozen=True)
class RuntimeSettings:
    """How the loop runs: workers, gates, data split, search extras."""

    rounds: int = 15
    n_workers: int = 4
    max_concurrency: int = 1
    refresh_interval: int = 1
    round_timeout: Optional[float] = None
    eval_concurrency: int = 8
    max_worker_errors: int = 3
    async_ratio: int = 3
    resync_on_commit: bool = True
    pipelined_gate: bool = False
    gate_workers: int = 2
    self_verify: bool = True
    held_out_frac: float = 0.4
    checkpointing: bool = False
    cheap_eval_tasks: Optional[int] = None
    fusion_tournament: Optional[bool] = None
    solved_threshold: float = 0.999
    shuffle: bool = False
    seed: int = 0
    population_islands: int = 0

    def merged_with(self, **kwargs: Any) -> "RuntimeSettings":
        return _resolve(RuntimeSettings, self, kwargs)


@dataclass(frozen=True)
class ObservabilitySettings:
    """Hooks, meters, and durable trajectory recording."""

    on_round: Optional[Callable[["RoundInfo"], None]] = None
    on_reports: Optional[Callable[[Sequence[Any]], None]] = None
    stop_when: Optional[Callable[["RoundInfo"], bool]] = None
    verbose: bool = False
    usage: Optional["Usage"] = None
    record_trajectories: bool = False
    trajectory_store: Optional["TrajectoryStore"] = None

    def merged_with(self, **kwargs: Any) -> "ObservabilitySettings":
        return _resolve(ObservabilitySettings, self, kwargs)


def resolve_budget(budget: Optional[BudgetSettings], **flat: Any) -> BudgetSettings:
    """Fold flat budget shortcuts into a :class:`BudgetSettings`."""
    return _resolve(BudgetSettings, budget, flat)


def resolve_runtime(runtime: Optional[RuntimeSettings], **flat: Any) -> RuntimeSettings:
    """Fold flat runtime shortcuts into a :class:`RuntimeSettings`."""
    return _resolve(RuntimeSettings, runtime, flat)


def resolve_observability(
        observability: Optional[ObservabilitySettings],
        **flat: Any) -> ObservabilitySettings:
    """Fold flat observability shortcuts into a :class:`ObservabilitySettings`."""
    return _resolve(ObservabilitySettings, observability, flat)
