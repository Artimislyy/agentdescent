"""PopulationAggregator fills Candidate.per_task so Pareto can ride Policies (#806)."""

from __future__ import annotations

import threading

import pytest

from agentdescent.evolution import SingleSlot, Task, evolve
from agentdescent.policies import Policies
from agentdescent.population import PopulationAggregator
from agentdescent.selection import ParetoFrontier


def _tasks():
    return [
        Task(id=f"t{i}", prompt=f"q{i}", meta={"gold": "ok", "n": i})
        for i in range(8)
    ]


def _run(rendered, task):
    import re
    m = re.search(r"cap:(\d+)", rendered or "")
    cap = int(m.group(1)) if m else 0
    return "ok" if task.meta["n"] <= cap else "no"


def _reward(task, output):
    return 1.0 if output == "ok" else 0.0


def _propose(rendered, task, output, reward):
    if reward >= 0.999:
        return None
    import re
    m = re.search(r"cap:(\d+)", rendered or "")
    cap = int(m.group(1)) if m else 0
    return f"cap:{cap + 1}"


class _Art:
    def __init__(self, state):
        self.state = dict(state)

    def render(self):
        return "|".join(f"{k}={v}" for k, v in sorted(self.state.items()))


class _Verifier:
    def __init__(self, held_out, table):
        self.held_out = list(held_out)
        self.table = table  # render-key -> {task_id: score}

    def eval_fn(self, artifact, tasks):
        row = self.table.get(artifact.render(), {})
        if not tasks:
            return 0.0
        return sum(float(row.get(t.id, 0.0)) for t in tasks) / len(tasks)


def _bare_agg(verifier):
    agg = PopulationAggregator.__new__(PopulationAggregator)
    agg.verifier = verifier
    agg.population_artifact = "art"
    agg._archive = []
    agg._keys = set()
    agg._archive_lock = threading.Lock()
    agg._branch_parent = {}
    agg._selections = 0
    agg._forks = []
    agg._all_forks = set()
    agg.island_count = 0
    return agg


def test_admit_stores_per_task_and_candidates_expose_it():
    held = [Task(id="a", prompt="a"), Task(id="b", prompt="b")]
    table = {
        "x=1": {"a": 1.0, "b": 0.0},
        "x=2": {"a": 0.0, "b": 1.0},
    }
    agg = _bare_agg(_Verifier(held, table))
    agg._admit(_Art({"x": "1"}), version=1)
    agg._admit(_Art({"x": "2"}), version=2)
    assert len(agg._archive) == 2
    assert agg._archive[0]["per_task"] == {"a": 1.0, "b": 0.0}
    assert agg._archive[0]["score"] == pytest.approx(0.5)
    assert agg._archive[1]["per_task"] == {"a": 0.0, "b": 1.0}
    cands = agg._candidates()
    assert cands[0].per_task == {"a": 1.0, "b": 0.0}
    assert cands[1].per_task == {"a": 0.0, "b": 1.0}


def test_checkpoint_round_trips_per_task(monkeypatch):
    held = [Task(id="a", prompt="a"), Task(id="b", prompt="b")]
    agg = _bare_agg(_Verifier(held, {"x=1": {"a": 0.25, "b": 0.75}}))
    agg._admit(_Art({"x": "1"}), version=1)

    # Avoid needing a full Aggregator parent state for this archive-only check.
    from agentdescent import aggregator as agg_mod
    monkeypatch.setattr(agg_mod.Aggregator, "checkpoint",
                        lambda self: {"posteriors": {}})
    monkeypatch.setattr(agg_mod.Aggregator, "restore",
                        lambda self, state: None)

    payload = PopulationAggregator.checkpoint(agg)
    assert payload["archive"][0]["per_task"] == {"a": 0.25, "b": 0.75}

    other = _bare_agg(_Verifier(held, {}))
    PopulationAggregator.restore(other, payload)
    assert other._archive[0]["per_task"] == {"a": 0.25, "b": 0.75}
    assert other._candidates()[0].per_task == {"a": 0.25, "b": 0.75}


def test_pre_806_checkpoint_without_per_task_restores_empty_map(monkeypatch):
    from agentdescent import aggregator as agg_mod
    monkeypatch.setattr(agg_mod.Aggregator, "restore",
                        lambda self, state: None)
    agg = _bare_agg(_Verifier([], {}))
    PopulationAggregator.restore(agg, {
        "archive": [{
            "state": {"x": "1"}, "score": 0.5, "version": 1, "selected": 0,
        }],
        "keys": [],
    })
    assert agg._archive[0]["per_task"] == {}
    assert agg._candidates()[0].per_task == {}


def test_policies_pareto_win_frequency_runs_without_factory():
    """Acceptance for #806: GEPA-class selection on the Policies path."""
    result = evolve(
        _tasks(), _reward, run=_run, propose=_propose,
        strategy=SingleSlot(initial_value="cap:0"),
        policies=Policies(selection=ParetoFrontier(mode="win_frequency", seed=0)),
        rounds=6, n_workers=2, max_concurrency=1,
        held_out_frac=0.5, seed=0, self_verify=False,
    )
    assert result.error is None, result.error
    assert result.final_reward >= 0.0
