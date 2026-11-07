"""show surfaces FusionStats so Path A can see merge ranking (#834)."""

from __future__ import annotations

import io
from contextlib import redirect_stdout
from dataclasses import asdict

from agentdescent import cli, demo, runstore
from agentdescent.evolution import EvolutionResult
from agentdescent.mcp import Tools
from agentdescent.policies import FusionTrial


def _trial(**kw):
    base = dict(artifact_id="a", n_candidates=2, best_single_score=0.7,
                baseline_score=0.3, fused_score=0.4, winner="single",
                ranked=True)
    base.update(kw)
    return FusionTrial(**base)


def _run_with_fusion_trials(tmp_path, monkeypatch, trials):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    spec = demo.build(str(tmp_path / "demo"))
    spec["evolve"] = dict(spec["evolve"], rounds=1, n_workers=1)
    # Force kind=text so show_payload takes the simple rendered path.
    prompt = tmp_path / "prompt.txt"
    prompt.write_text("COLUMN: id\n")
    spec["kind"] = "text"
    spec["target"] = str(prompt)
    rd = runstore.create(spec)
    result = EvolutionResult(
        state={},
        rendered="COLUMN: id\n",
        final_reward=0.4,
        history=[],
        ledger_log=[],
        initial_reward=0.3,
        fusion_trials=list(trials),
    )
    result.save(rd.result_path)
    rd.update_status(state="finished")
    return rd, result


def test_show_payload_includes_fusion_stats(tmp_path, monkeypatch):
    trials = [
        _trial(),
        _trial(fused_score=None, ranked=False, reason="trust-union",
               winner="fused"),
    ]
    rd, result = _run_with_fusion_trials(tmp_path, monkeypatch, trials)
    payload = cli.show_payload(rd.run_id)
    assert payload["fusion_stats"] == asdict(result.fusion_stats())
    assert payload["fusion_stats"]["contested"] == 1
    assert payload["fusion_stats"]["unranked"] == 1
    assert payload["fusion_stats"]["negative"] == 1
    assert payload["fusion_summary"] == result.fusion_stats().summary()


def test_mcp_show_returns_the_same_fusion_stats(tmp_path, monkeypatch):
    trials = [_trial(fused_score=0.8, best_single_score=0.5, winner="fused")]
    rd, result = _run_with_fusion_trials(tmp_path, monkeypatch, trials)
    out = Tools(None).show(rd.run_id)
    assert out["fusion_stats"] == cli.show_payload(rd.run_id)["fusion_stats"]
    assert out["fusion_summary"] == result.fusion_stats().summary()


def test_text_mode_prints_fusion_summary(tmp_path, monkeypatch):
    trials = [_trial()]
    rd, result = _run_with_fusion_trials(tmp_path, monkeypatch, trials)

    class A:
        run_id = rd.run_id
        store = None
        diff = False
        json = False

    buf = io.StringIO()
    with redirect_stdout(buf):
        assert cli.cmd_show(A()) == 0
    assert result.fusion_stats().summary() in buf.getvalue()


def test_no_trials_omits_fusion_summary_but_keeps_zero_stats(tmp_path, monkeypatch):
    rd, _ = _run_with_fusion_trials(tmp_path, monkeypatch, [])
    payload = cli.show_payload(rd.run_id)
    assert payload["fusion_stats"]["trials"] == 0
    assert "fusion_summary" not in payload
