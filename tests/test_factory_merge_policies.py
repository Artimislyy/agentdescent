"""aggregator_factory composes with merge Policies instead of dropping them (#807)."""

from __future__ import annotations

import pytest

from agentdescent.algorithms.gepa import pareto_aggregator_factory
from agentdescent.algorithms.skillopt import SkillOptContext, LRScheduler, strict_gate_factory
from agentdescent.evolution import AppendRules, SingleSlot, Task, evolve
from agentdescent.policies import AcceptDecision, Policies
from agentdescent.selection import ParetoFrontier


def _tasks(n=8):
    return [Task(id=f"t{i}", prompt=f"q{i}", meta={"gold": "ok", "n": i})
            for i in range(n)]


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


class NeverAccept:
    calls = 0

    def accept(self, ctx):
        NeverAccept.calls += 1
        return AcceptDecision(False, "below-threshold", "refused by policy")


class BlindFactory:
    """Old-style factory: five positional args, no merge slots on the result."""

    def __call__(self, ledger, verifier, audit, config, policy):
        class Bare:
            def ingest(self, card): pass
            def step(self, n_workers=1): return []
        return Bare()


def test_factory_that_ignores_merge_policies_fails_closed():
    with pytest.raises(ValueError, match="left Policies"):
        evolve(
            _tasks(), _reward, run=_run, propose=_propose,
            strategy=SingleSlot(initial_value="cap:0"),
            policies=Policies(aggregator_factory=BlindFactory(),
                              acceptance=NeverAccept()),
            rounds=2, n_workers=1, max_concurrency=1,
            held_out_frac=0.5, seed=0, self_verify=False,
        )


def test_accept_orphaned_allows_the_drop_with_a_warning():
    with pytest.warns(RuntimeWarning, match="left Policies"):
        result = evolve(
            _tasks(), _reward, run=_run, propose=_propose,
            strategy=SingleSlot(initial_value="cap:0"),
            policies=Policies(
                aggregator_factory=BlindFactory(),
                acceptance=NeverAccept(),
                accept_orphaned_merge_policies=True),
            rounds=2, n_workers=1, max_concurrency=1,
            held_out_frac=0.5, seed=0, self_verify=False,
        )
    assert result.error is None


def test_skillopt_factory_honours_policies_acceptance():
    NeverAccept.calls = 0
    ctx = SkillOptContext(
        scheduler=LRScheduler(max_lr=2, min_lr=1, total_steps=4, mode="cosine"),
        budget=2)
    factory = strict_gate_factory(ctx, artifact_id="skill")
    result = evolve(
        _tasks(), _reward, run=_run, propose=_propose,
        strategy=SingleSlot(initial_value="cap:0"),
        initial_state={"text": "cap:0"},
        artifact_id="skill",
        policies=Policies(aggregator_factory=factory, acceptance=NeverAccept()),
        rounds=3, n_workers=1, max_concurrency=1,
        held_out_frac=0.5, seed=0, self_verify=False,
    )
    assert result.error is None, result.error
    assert NeverAccept.calls > 0, "Policies(acceptance=) never reached SkillOpt"


def test_gepa_factory_honours_policies_acceptance():
    NeverAccept.calls = 0
    factory = pareto_aggregator_factory(artifact_id="prompt", seed=0)
    result = evolve(
        _tasks(), _reward, run=_run, propose=_propose,
        strategy=SingleSlot(initial_value="cap:0"),
        artifact_id="prompt",
        policies=Policies(aggregator_factory=factory, acceptance=NeverAccept()),
        rounds=4, n_workers=2, max_concurrency=1,
        held_out_frac=0.5, seed=0, self_verify=False,
    )
    assert result.error is None, result.error
    # self_verify=False leaves before_after_delta at 0, so GEPA keeps survivors
    # and must consult Policies(acceptance=) before admitting them.
    assert NeverAccept.calls > 0, "Policies(acceptance=) never reached GEPA"


def test_population_factory_path_honours_merge_policies_without_orphan():
    """Policies(selection=…) installs population_factory; Aggregator seats are
    ``*_policy``, so composition must count those as applied (#807 CI)."""
    from agentdescent.selection import Archive
    from agentdescent.fusion import KeepContradictions

    result = evolve(
        _tasks(), _reward, run=_run, propose=_propose,
        strategy=SingleSlot(initial_value="cap:0"),
        policies=Policies(selection=Archive(seed=0),
                          conflict=KeepContradictions()),
        rounds=2, n_workers=1, max_concurrency=1,
        held_out_frac=0.5, seed=0, self_verify=False,
    )
    assert result.error is None, result.error
