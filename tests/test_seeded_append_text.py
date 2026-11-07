"""kind=text must not wipe a multi-line seed on the first one-sentence accept (#837)."""

from __future__ import annotations

from agentdescent.evolution import SeededAppendRules, SingleSlot, Task, evolve
from agentdescent.evolvespec import EvolveSpec, compose
from agentdescent.strategies import rule_id


SEED = (
    "You are a careful assistant.\n"
    "Always cite units.\n"
    "Prefer short answers."
)


def test_seeded_append_keeps_seed_after_one_rule():
    strat = SeededAppendRules(seed=SEED)
    state = dict(strat.initial())
    diff = strat.to_diff(state, "Always show units in the answer.", "w0", 0, "a")
    assert diff is not None
    state.update({k: v for k, v in diff.ops.items() if v is not None})
    rendered = strat.render(state)
    assert "You are a careful assistant." in rendered
    assert "Always cite units." in rendered
    assert "Always show units in the answer." in rendered
    assert "# Learned rules" in rendered


def test_singleslot_still_replaces_entire_value():
    """Document the contrasting contract GEPA opts into."""
    strat = SingleSlot(initial_value=SEED)
    state = dict(strat.initial())
    diff = strat.to_diff(state, "One short rule only.", "w0", 0, "a")
    assert diff is not None
    state.update(diff.ops)
    assert strat.render(state) == "One short rule only."
    assert "careful assistant" not in strat.render(state)


def test_compose_text_uses_seeded_append():
    spec = EvolveSpec(
        kind="text",
        target=SEED,
        data={"inline": [{"prompt": f"q{i}", "gold": "a"} for i in range(8)]},
        agent="echo",
        reflect="echo",
    )
    comp = compose(spec)
    strat = comp.kwargs["strategy"]
    assert isinstance(strat, SeededAppendRules)
    assert strat.seed == SEED
    assert any("SeededAppendRules" in n for n in comp.notes)


def test_text_evolve_one_accept_keeps_seed_substance():
    tasks = [Task(id=f"t{i}", prompt=f"q{i}", meta={"gold": "a"}) for i in range(8)]

    def run(skill, task):
        # Fail until the learned rule appears in the artifact.
        return "a" if "Always show units" in skill else "wrong"

    def reward(task, output):
        return 1.0 if output == task.meta["gold"] else 0.0

    def propose(rendered, task, output, score):
        if score >= 0.999:
            return None
        return "Always show units in the answer."

    res = evolve(
        tasks, reward, run=run, propose=propose,
        strategy=SeededAppendRules(seed=SEED),
        rounds=2, n_workers=1, held_out_frac=0.25, seed=0,
    )
    assert "You are a careful assistant." in res.rendered
    assert "Always show units" in res.rendered


def test_empty_state_preserves_seed_trailing_newline():
    """apply no-op depends on empty render matching the on-disk seed (#849)."""
    seed = "original\n"
    assert SeededAppendRules(seed=seed).render({}) == seed
