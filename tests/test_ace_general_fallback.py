"""ACE proposals without section :: land under ## general (#842)."""

from agentdescent.algorithms.ace import ACEPlaybook


def test_bare_proposal_goes_to_general():
    pb = ACEPlaybook(seed="Seed prompt.")
    state = dict(pb.initial())
    d = pb.to_diff(state, "Always check units.", "w", 0, "a")
    assert d is not None
    entry = next(iter(d.ops.values()))
    assert entry.startswith("general :: ")
    state.update(d.ops)
    rendered = pb.render(state)
    assert "Seed prompt." in rendered
    assert "## general" in rendered or "general" in rendered


def test_section_prefix_is_honoured():
    pb = ACEPlaybook(seed="Seed.")
    d = pb.to_diff({}, "revenue :: Recognise deferred revenue carefully.", "w", 0, "a")
    assert next(iter(d.ops.values())).startswith("revenue :: ")
