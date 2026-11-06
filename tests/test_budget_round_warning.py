"""Budget is checked between rounds; warn when seed+one round already exceeds it (#764)."""

from __future__ import annotations

import json

import pytest

from agentdescent import cli
from agentdescent.evolvespec import (
    EvolveSpec,
    budget_round_overshoot_warning,
    compose,
    estimate,
)
from agentdescent.mcp import Tools


def _spec(tmp_path, *, n_tasks=16, rounds=3, n_workers=2):
    cases = tmp_path / "cases.jsonl"
    cases.write_text(
        "".join(f'{{"prompt": "q{i}", "gold": "a{i}"}}\n' for i in range(n_tasks)),
        encoding="utf-8",
    )
    target = tmp_path / "prompt.txt"
    target.write_text("Reformat the date.\n", encoding="utf-8")
    return EvolveSpec.from_dict({
        "kind": "text",
        "target": str(target),
        "data": {"path": str(cases), "prompt": "prompt", "gold": "gold"},
        "score": "contains",
        "agent": {"ref": "echo"},
        "evolve": {"rounds": rounds, "n_workers": n_workers},
    })


def test_helper_warns_only_when_budget_below_seed_plus_one_round(tmp_path):
    spec = _spec(tmp_path)
    est = estimate(compose(spec), usd_per_call=0.01)
    first = est["seed_score_calls"] + sum(est["calls_per_round"].values())
    # Repro from #764: $0.05 with $0.01/call vs ~21-call first bound.
    warn = budget_round_overshoot_warning(est, 0.05, 0.01)
    assert warn is not None
    assert "between rounds" in warn and "overshoot" in warn
    assert f"~{first} calls" in warn
    assert budget_round_overshoot_warning(est, first * 0.01, 0.01) is None
    assert budget_round_overshoot_warning(est, None, 0.01) is None
    assert budget_round_overshoot_warning(est, 0.05, None) is None


def test_plan_includes_budget_warning(tmp_path, capsys):
    spec = _spec(tmp_path)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec.to_dict()), encoding="utf-8")
    code = cli.main(["plan", str(path), "--budget", "0.05", "--usd-per-call", "0.01"])
    assert code == 0
    payload = json.loads(capsys.readouterr().out)
    assert any("between rounds" in w and "overshoot" in w for w in payload["warnings"])
    # No budget flag: quiet even with a price.
    cli.main(["plan", str(path), "--usd-per-call", "0.01"])
    payload2 = json.loads(capsys.readouterr().out)
    assert not any("overshoot" in w for w in payload2["warnings"])


def test_evolve_prints_budget_warning_before_create(tmp_path, monkeypatch, capsys):
    spec = _spec(tmp_path)
    path = tmp_path / "spec.json"
    path.write_text(json.dumps(spec.to_dict()), encoding="utf-8")

    def boom(*_a, **_k):
        raise RuntimeError("stop-after-warn")

    monkeypatch.setattr(cli.runstore, "create", boom)
    with pytest.raises(RuntimeError, match="stop-after-warn"):
        cli.main(["evolve", str(path), "--budget", "0.05", "--usd-per-call", "0.01"])
    err = capsys.readouterr().err
    assert "warning:" in err and "between rounds" in err and "overshoot" in err


def test_mcp_plan_and_start_surface_budget_warning(tmp_path, monkeypatch):
    from agentdescent import mcp as mcp_mod
    from agentdescent import runstore

    store = str(tmp_path / "store")
    t = Tools(store)
    spec = _spec(tmp_path).to_dict()

    planned = t.plan(spec, usd_per_call=0.01, budget_usd=0.05)
    assert planned.get("ok", True)
    assert any("between rounds" in w for w in planned["warnings"])

    class _FakeRD:
        run_id = "r1"
        path = str(tmp_path / "r1")

        def update_status(self, **_kwargs):
            return None

        def status(self):
            return type("S", (), {"notes": []})()

    class _FakeSt:
        state = "running"
        pid = 1

    monkeypatch.setattr(runstore, "create", lambda *_a, **_k: _FakeRD())
    monkeypatch.setattr(runstore, "launch", lambda *_a, **_k: _FakeSt())
    monkeypatch.setattr(mcp_mod, "require_cli_on_path", lambda _spec: None)
    out = t.start(spec, budget_usd=0.05, usd_per_call=0.01)
    assert out["ok"] is True
    assert any("between rounds" in w for w in out.get("warnings", []))
