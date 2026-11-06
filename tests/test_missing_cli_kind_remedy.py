"""Missing-CLI remedy must not suggest openai_compatible for directory kinds (#791)."""

import json

import pytest

from agentdescent import cli
from agentdescent.evolvespec import EvolveSpec


_ALL = ("claude", "codex", "dsh", "opencode")


def _clis(monkeypatch, *present):
    real = cli.doctor_report

    def fake():
        rep = real()
        clis = dict(rep["agent_clis"])
        for name in _ALL:
            clis[name] = f"/fake/{name}" if name in present else None
        return {**rep, "agent_clis": clis}

    monkeypatch.setattr(cli, "doctor_report", fake)


def _skill_spec(tmp_path, agent="claude_code") -> EvolveSpec:
    root = tmp_path / "skill"
    root.mkdir()
    (root / "SKILL.md").write_text("---\nname: skill\n---\n# skill\n")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": "a"}) + "\n" for i in range(6)))
    return EvolveSpec.from_dict({
        "kind": "skill_dir", "target": str(root),
        "data": {"path": str(cases), "prompt": "prompt", "gold": "gold"},
        "score": "contains",
        "agent": {"ref": agent},
        "reflect": {"ref": "openai_compatible", "model": "m",
                    "api_key_env": "OPENAI_API_KEY"},
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
    })


def _text_spec(tmp_path, *, agent="claude_code", reflect="echo") -> EvolveSpec:
    """kind=text with a CLI-shaped agent/reflect — used only via _missing_cli_messages
    (compose would refuse a WorkspaceAgent agent on text)."""
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": "a"}) + "\n" for i in range(6)))
    prompt = tmp_path / "p.txt"
    prompt.write_text("Answer.\n")
    return EvolveSpec.from_dict({
        "kind": "text", "target": str(prompt),
        "data": {"path": str(cases)}, "score": "contains",
        "agent": {"ref": agent} if isinstance(agent, str) else agent,
        "reflect": reflect,
        "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
    })


@pytest.mark.parametrize("kind", ("skill_dir", "agent_dir"))
def test_directory_kind_missing_agent_cli_does_not_name_openai_compatible(
        tmp_path, monkeypatch, kind):
    _clis(monkeypatch)
    if kind == "skill_dir":
        spec = _skill_spec(tmp_path)
    else:
        root = tmp_path / "agent"
        root.mkdir()
        (root / "AGENT.md").write_text("# agent\n")
        cases = tmp_path / "cases.jsonl"
        cases.write_text("".join(
            json.dumps({"prompt": f"q{i}", "gold": "a"}) + "\n" for i in range(6)))
        spec = EvolveSpec.from_dict({
            "kind": "agent_dir", "target": str(root),
            "data": {"path": str(cases)}, "score": "contains",
            "agent": {"ref": "claude_code"}, "reflect": "echo",
            "evolve": {"rounds": 1, "n_workers": 1, "seed": 0},
        })
    msgs = cli._missing_cli_messages(spec)
    assert len(msgs) == 1 and msgs[0].startswith("agent:")
    assert "openai_compatible" not in msgs[0]
    assert "non-CLI" not in msgs[0]
    assert "install" in msgs[0] and "`claude`" in msgs[0]
    payload = cli.plan_payload(spec)
    assert payload["ok"] is False
    assert "openai_compatible" not in payload["error"]


def test_skill_dir_still_suggests_present_workspace_cli(tmp_path, monkeypatch):
    _clis(monkeypatch, "opencode")
    msgs = cli._missing_cli_messages(_skill_spec(tmp_path))
    assert len(msgs) == 1
    assert "`opencode`" in msgs[0]
    assert "openai_compatible" not in msgs[0]


def test_text_kind_missing_cli_may_still_name_openai_compatible(tmp_path, monkeypatch):
    """Reflect on kind=text can be a CLI agent; remedy may point at openai_compatible."""
    _clis(monkeypatch)
    spec = _text_spec(tmp_path, agent={"ref": "openai_compatible", "model": "m",
                                       "api_key_env": "OPENAI_API_KEY"},
                      reflect="claude_code")
    msgs = cli._missing_cli_messages(spec)
    assert any(m.startswith("reflect:") for m in msgs)
    reflect_msg = next(m for m in msgs if m.startswith("reflect:"))
    assert "openai_compatible" in reflect_msg
