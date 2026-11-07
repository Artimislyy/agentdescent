"""Typed evolve settings bags and the flat-signature freeze (#804)."""
from __future__ import annotations

import inspect
import warnings

import pytest

from agentdescent import (
    BudgetSettings,
    EVOLVE_PARAM_ALLOWLIST,
    EVOLVE_STABLE_SUBSET,
    ObservabilitySettings,
    RuntimeSettings,
    Task,
    async_evolve,
    evolve,
)
from agentdescent.evolution import SingleSlot
from agentdescent.evolve_settings import (
    resolve_budget,
    resolve_observability,
    resolve_runtime,
)


TASKS = [Task(id=str(i), prompt="p", meta={"gold": "x"}) for i in range(8)]


def _run(**kw):
    return evolve(
        TASKS, lambda t, o: 0.5,
        run=lambda a, t: "x", propose=lambda *a: None,
        strategy=SingleSlot(initial_value="v"),
        n_workers=1, rounds=2, **kw,
    )


def test_evolve_param_allowlist_matches_signature():
    """A new raw evolve() kwarg must update EVOLVE_PARAM_ALLOWLIST on purpose."""
    names = set(inspect.signature(evolve).parameters)
    assert names == set(EVOLVE_PARAM_ALLOWLIST), (
        f"evolve() signature drifted from EVOLVE_PARAM_ALLOWLIST. "
        f"added={sorted(names - EVOLVE_PARAM_ALLOWLIST)}; "
        f"removed={sorted(EVOLVE_PARAM_ALLOWLIST - names)}. "
        "Prefer a Policies field or BudgetSettings / RuntimeSettings / "
        "ObservabilitySettings (#804) instead of growing the flat surface."
    )


def test_stable_subset_is_subset_of_allowlist():
    missing = [n for n in EVOLVE_STABLE_SUBSET if n not in EVOLVE_PARAM_ALLOWLIST]
    assert missing == []


def test_budget_bag_overrides_defaults_and_flat_shortcut_wins():
    bag = BudgetSettings(max_tokens=1000, patience=2)
    folded = resolve_budget(bag, max_tokens=None, patience=None,
                            max_seconds=None, max_rollouts=None, max_calls=None,
                            stop_on_diminishing_returns=False,
                            efficiency_floor=0.25, call_budget=None,
                            target_reward=None, oracle_budget=200)
    assert folded.max_tokens == 1000 and folded.patience == 2
    folded2 = resolve_budget(bag, max_tokens=500, patience=None,
                             max_seconds=None, max_rollouts=None, max_calls=None,
                             stop_on_diminishing_returns=False,
                             efficiency_floor=0.25, call_budget=None,
                             target_reward=None, oracle_budget=200)
    assert folded2.max_tokens == 500 and folded2.patience == 2


def test_runtime_and_observability_fold():
    r = resolve_runtime(RuntimeSettings(n_workers=8, rounds=3),
                        n_workers=4, rounds=15, max_concurrency=1,
                        refresh_interval=1, round_timeout=None,
                        eval_concurrency=8, max_worker_errors=3,
                        async_ratio=3, resync_on_commit=True,
                        pipelined_gate=False, gate_workers=2,
                        self_verify=True, held_out_frac=0.4,
                        checkpointing=False, cheap_eval_tasks=None,
                        fusion_tournament=None, solved_threshold=0.999,
                        shuffle=False, seed=0, population_islands=0)
    assert r.n_workers == 8 and r.rounds == 3
    seen = []
    obs = resolve_observability(
        ObservabilitySettings(verbose=True, on_round=lambda info: seen.append(1)),
        on_round=None, on_reports=None, stop_when=None, verbose=False,
        usage=None, record_trajectories=False, trajectory_store=None,
    )
    assert obs.verbose is True and obs.on_round is not None


def test_evolve_honours_budget_and_runtime_bags():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = _run(budget=BudgetSettings(patience=1),
                   runtime=RuntimeSettings(rounds=6, n_workers=1))
    assert res.error is None
    assert res.stop_reason == "patience"
    assert len(res.history) <= 3


def test_async_evolve_honours_budget_max_rollouts():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = async_evolve(
            TASKS, lambda t, o: 0.5,
            run=lambda a, t: "x", propose=lambda *a: None,
            strategy=SingleSlot(initial_value="v"),
            budget=BudgetSettings(max_rollouts=4),
            n_workers=1, max_seconds=10.0, self_verify=False,
        )
    assert res.error is None
    assert res.stop_reason in ("max_iters", "max_rollouts")
    assert res.rollouts <= 5


def test_flat_kwargs_still_work_without_bags():
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        res = _run(patience=1)
    assert res.error is None
    assert res.stop_reason == "patience"
