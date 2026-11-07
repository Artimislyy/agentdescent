"""RRSI defaults make the anneal observable within a short run (#841)."""

from agentdescent.algorithms.rrsi.rrsi_policies import RRsiConfig, RRsiState


def test_default_T_matches_short_run_and_anneals():
    cfg = RRsiConfig()
    assert cfg.T == 8
    assert cfg.noise_band > 0
    assert cfg.beta0 > 0 and cfg.beta1 > 0
    state = RRsiState(config=cfg)
    b0 = state.budget()
    state.round = cfg.T - 1
    b_end = state.budget()
    assert b0 >= b_end
    assert b0 == cfg.b_max or b0 > b_end


def test_card_params_mirror_config_defaults():
    from agentdescent import algorithms
    card = algorithms.get("rrsi")
    by_name = {p.name: p.default for p in card.params}
    assert by_name["T"] == 8
    assert by_name["noise_band"] == 0.02
