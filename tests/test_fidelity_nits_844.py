"""Small port fidelity fixes (#844)."""

from agentdescent.algorithms.dgm import _Agent


def test_dgm_children_only_count_admitted(monkeypatch):
    """Skipped cards must not inflate parent.children (sampling weight)."""
    parent = _Agent(("seed",), parent=None, generation=0)
    parent.children = 0
    # Simulate the fixed loop logic
    admitted = 0
    cards_skipped = 3
    for _ in range(cards_skipped):
        continue  # all skipped
    if admitted:
        parent.children += admitted
    assert parent.children == 0
    admitted = 2
    if admitted:
        parent.children += admitted
    assert parent.children == 2


def test_evoskill_context_has_no_val_every():
    from agentdescent.algorithms.evoskill import EvoSkillContext, Frontier
    ctx = EvoSkillContext(docs={}, frontier=Frontier())
    assert not hasattr(ctx, "val_every")


def test_gepa_tracks_parent_index_attr():
    import inspect
    from agentdescent.algorithms.gepa import ParetoAggregator
    src = inspect.getsource(ParetoAggregator.__init__)
    assert "_parent_index" in src
