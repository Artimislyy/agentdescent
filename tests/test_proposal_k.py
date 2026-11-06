"""ProposalPolicy k>1 is honoured end-to-end under evolve (#808)."""

from __future__ import annotations

from agentdescent.evolution import AppendRules, Task, evolve
from agentdescent.policies import Policies


def _tasks():
    return [Task(id=f"t{i}", prompt="q", meta={"gold": "ok", "n": i})
            for i in range(8)]


def _run(rendered, task):
    return "no"  # always fail so propose always fires


def _reward(task, output):
    return 0.0


class MultiPropose:
    k = 3
    calls = 0
    ctx_ks = []

    def propose(self, ctx):
        MultiPropose.calls += 1
        MultiPropose.ctx_ks.append(ctx.k)
        return [f"v{i}-{ctx.task.id}" for i in range(ctx.k)]


def test_multi_proposal_policy_reaches_the_aggregator(tmp_path):
    MultiPropose.calls = 0
    MultiPropose.ctx_ks = []
    ingested = []

    class CountingFactory:
        def __call__(self, ledger, verifier, audit, config, policy):
            from agentdescent.aggregator import Aggregator
            class Counting(Aggregator):
                def ingest(self, card):
                    ingested.append(card.diff.diff_id)
                    return super().ingest(card)
            return Counting(ledger, verifier, audit, config,
                            staleness_policy=policy)

    # accept_orphaned not needed: Counting subclasses Aggregator and gets slots.
    result = evolve(
        _tasks(), _reward, run=_run,
        strategy=AppendRules(),
        policies=Policies(proposal=MultiPropose(),
                          aggregator_factory=CountingFactory()),
        rounds=2, n_workers=1, max_concurrency=1,
        held_out_frac=0.5, seed=0, self_verify=False,
        repo_path=str(tmp_path / "repo"),
    )
    assert result.error is None, result.error
    assert MultiPropose.calls >= 1
    assert MultiPropose.ctx_ks[0] == 3
    # At least one rollout produced 3 cards (may be more across rounds/tasks).
    assert len(ingested) >= 3, ingested
