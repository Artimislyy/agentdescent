"""Ark starter specs default to stream:true so propose does not hit 120s (#832)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentdescent import cli
from agentdescent.evolvespec import EvolveSpec, load_spec

_ARK = "https://ark.cn-beijing.volces.com/api/coding/v3"


@pytest.fixture(autouse=True)
def _no_provider_keys(monkeypatch):
    for name in ("OPENAI_API_KEY", "ARK_API_KEY", "DEEPSEEK_API_KEY",
                 "ANTHROPIC_API_KEY", "OPENAI_BASE_URL"):
        monkeypatch.delenv(name, raising=False)
    real = cli.doctor_report

    def fake():
        rep = real()
        return {**rep, "agent_clis": {**rep["agent_clis"], "opencode": "/fake/opencode"}}

    monkeypatch.setattr(cli, "doctor_report", fake)


def test_starter_model_block_sets_stream_for_ark_url():
    block = cli.starter_model_block(model="deepseek-v4-flash", base_url=_ARK,
                                    key_env="ARK_API_KEY", keys={"ARK_API_KEY": True})
    assert block["stream"] is True
    assert block["default_base_url"] == _ARK


def test_starter_model_block_skips_stream_for_non_ark():
    block = cli.starter_model_block(model="m", base_url="https://example.test/v1",
                                    key_env="MY_KEY", keys={})
    assert "stream" not in block


def test_starter_model_block_skips_stream_for_placeholder_url():
    block = cli.starter_model_block(model=None, key_env="ARK_API_KEY",
                                    keys={"ARK_API_KEY": True})
    assert block["default_base_url"] == cli.PLACEHOLDER_URL
    assert "stream" not in block


def test_algorithms_run_ark_writes_stream_true(tmp_path, monkeypatch, capsys):
    # Matches the #832 repro: skill_dir + archive_selection keeps openai_compatible
    # on reflect (gepa on text nulls reflect and puts the LLM on agent instead).
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ARK_API_KEY", "k")
    skill = tmp_path / "sk"
    skill.mkdir()
    (skill / "SKILL.md").write_text("---\nname: s\ndescription: d\n---\nbody\n")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": f"a{i}"}) + "\n" for i in range(8)))
    out = tmp_path / "out.spec.json"
    assert cli.main([
        "algorithms", "run", "archive_selection", str(skill), str(cases),
        "--model", "deepseek-v4-flash", "--base-url", _ARK,
        "--key-env", "ARK_API_KEY", "--rounds", "1", "--workers", "1",
        "--out", str(out),
    ]) == 0
    spec = json.loads(out.read_text())
    assert spec["reflect"]["stream"] is True
    assert spec["reflect"]["default_base_url"] == _ARK

def test_plan_warns_hand_edited_ark_without_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "k")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": "a"}) + "\n" for i in range(8)))
    target = tmp_path / "prompt.txt"
    target.write_text("hi\n")
    spec = EvolveSpec.from_dict({
        "kind": "text", "target": str(target),
        "data": {"path": str(cases), "prompt": "prompt", "gold": "gold"},
        "score": "contains", "agent": {"ref": "echo"},
        "reflect": {"ref": "openai_compatible", "model": "deepseek-v4-flash",
                    "api_key_env": "ARK_API_KEY", "default_base_url": _ARK},
    })
    payload = cli.plan_payload(spec)
    assert payload["ok"] is True, payload.get("error")
    warns = [w for w in payload["warnings"] if "stream" in w and "Ark" in w]
    assert warns, payload["warnings"]


def test_plan_quiet_when_ark_has_stream(tmp_path, monkeypatch):
    monkeypatch.setenv("ARK_API_KEY", "k")
    cases = tmp_path / "cases.jsonl"
    cases.write_text("".join(
        json.dumps({"prompt": f"q{i}", "gold": "a"}) + "\n" for i in range(8)))
    target = tmp_path / "prompt.txt"
    target.write_text("hi\n")
    spec = EvolveSpec.from_dict({
        "kind": "text", "target": str(target),
        "data": {"path": str(cases), "prompt": "prompt", "gold": "gold"},
        "score": "contains", "agent": {"ref": "echo"},
        "reflect": {"ref": "openai_compatible", "model": "deepseek-v4-flash",
                    "api_key_env": "ARK_API_KEY", "default_base_url": _ARK,
                    "stream": True},
    })
    payload = cli.plan_payload(spec)
    assert payload["ok"] is True, payload.get("error")
    assert not [w for w in payload["warnings"] if "stream" in w and "Ark" in w]
