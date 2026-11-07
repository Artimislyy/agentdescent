"""Sync and async are two contracts behind one deprecated bridge (#809)."""
from __future__ import annotations

import inspect
import warnings

import pytest

from agentdescent.async_evolve import async_evolve
from agentdescent.evolution import (
    SingleSlot,
    Task,
    _ASYNC_WIRED_POLICIES,
    _POLICY_DRIVER_SUPPORT,
    _WIRED_POLICIES,
    evolve,
)


TASKS = [Task(id=str(i), prompt="p", meta={"gold": "x"}) for i in range(8)]


def test_policy_driver_support_table_is_the_single_source():
    assert _WIRED_POLICIES == _POLICY_DRIVER_SUPPORT["evolve"]
    assert _ASYNC_WIRED_POLICIES == _POLICY_DRIVER_SUPPORT["async_evolve"]
    assert "executor" in _WIRED_POLICIES
    assert "executor" not in _ASYNC_WIRED_POLICIES
    # async is sync minus executor only — any further drift fails here.
    assert set(_WIRED_POLICIES) - set(_ASYNC_WIRED_POLICIES) == {"executor"}
    assert set(_ASYNC_WIRED_POLICIES) <= set(_WIRED_POLICIES)


def test_async_evolve_imports_the_shared_async_wired_set():
    import importlib
    # ``import agentdescent.async_evolve`` can resolve to the *function*
    # re-exported on the package; load the module object explicitly.
    mod = importlib.import_module("agentdescent.async_evolve")
    assert tuple(mod._ASYNC_WIRED_POLICIES) == tuple(_ASYNC_WIRED_POLICIES)


def test_bridge_requires_explicit_budgets_and_warns():
    with pytest.raises(ValueError, match="max_seconds"):
        evolve(TASKS, lambda t, o: 0.5, run=lambda a, t: "x",
               propose=lambda *a: None, strategy=SingleSlot(initial_value="v"),
               asynchronous=True, max_rollouts=4)
    with pytest.raises(ValueError, match="max_rollouts"):
        evolve(TASKS, lambda t, o: 0.5, run=lambda a, t: "x",
               propose=lambda *a: None, strategy=SingleSlot(initial_value="v"),
               asynchronous=True, max_seconds=2.0)
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        res = evolve(
            TASKS, lambda t, o: 0.5, run=lambda a, t: "x",
            propose=lambda *a: None, strategy=SingleSlot(initial_value="v"),
            asynchronous=True, n_workers=1, max_seconds=5.0, max_rollouts=4,
            self_verify=False,
        )
    assert res.error is None
    assert any(issubclass(w.category, FutureWarning)
               and "async_evolve" in str(w.message) for w in caught)


def test_budget_settings_work_on_both_drivers():
    from agentdescent import BudgetSettings
    bag = BudgetSettings(max_seconds=5.0, max_rollouts=4)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        sync = evolve(
            TASKS, lambda t, o: 0.5, run=lambda a, t: "x",
            propose=lambda *a: None, strategy=SingleSlot(initial_value="v"),
            budget=bag, rounds=2, n_workers=1, self_verify=False,
        )
        async_res = async_evolve(
            TASKS, lambda t, o: 0.5, run=lambda a, t: "x",
            propose=lambda *a: None, strategy=SingleSlot(initial_value="v"),
            budget=bag, n_workers=1, self_verify=False,
        )
    assert sync.error is None and async_res.error is None
    assert "max_iters" in inspect.signature(async_evolve).parameters
