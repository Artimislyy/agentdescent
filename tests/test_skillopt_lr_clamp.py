"""SkillOpt LRScheduler stays at min_lr after total_steps (#840)."""

from agentdescent.algorithms.skillopt import LRScheduler


def test_cosine_does_not_climb_after_total_steps():
    sched = LRScheduler(max_lr=4, min_lr=2, total_steps=4, mode="cosine")
    budgets = [sched.step() for _ in range(12)]
    # After total_steps, every further step is min_lr (not rising again).
    assert budgets[3:] == [2] * 9
    assert budgets[0] == 4


def test_linear_clamps_too():
    sched = LRScheduler(max_lr=5, min_lr=1, total_steps=5, mode="linear")
    budgets = [sched.step() for _ in range(10)]
    assert budgets[-1] == 1
    assert all(b == 1 for b in budgets[4:])
