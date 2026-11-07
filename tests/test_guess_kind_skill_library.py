"""A directory of ≥2 ``*/SKILL.md`` is guessed as skill_library (#866)."""
from __future__ import annotations

import json
from pathlib import Path

from agentdescent import cli


def _skill(root: Path, name: str) -> None:
    d = root / name
    d.mkdir(parents=True)
    (d / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} skill.\n---\n# {name}\n",
        encoding="utf-8")


def test_library_layout_guessed_skill_library(tmp_path):
    lib = tmp_path / "skills"
    _skill(lib, "alpha")
    _skill(lib, "beta")
    assert cli.guess_kind(str(lib)) == "skill_library"


def test_root_skill_md_stays_skill_dir(tmp_path):
    lib = tmp_path / "skills"
    _skill(lib, "alpha")
    _skill(lib, "beta")
    (lib / "SKILL.md").write_text("---\nname: skills\ndescription: x\n---\n",
                                  encoding="utf-8")
    assert cli.guess_kind(str(lib)) == "skill_dir"


def test_single_child_skill_stays_skill_dir(tmp_path):
    lib = tmp_path / "skills"
    _skill(lib, "alpha")
    assert cli.guess_kind(str(lib)) == "skill_dir"


def test_agents_parent_still_agent_dir(tmp_path):
    agent = tmp_path / "agents" / "reviewer"
    _skill(agent, "alpha")
    _skill(agent, "beta")
    assert cli.guess_kind(str(agent)) == "agent_dir"


def test_init_writes_skill_library_spec(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lib = tmp_path / "skills"
    _skill(lib, "alpha")
    _skill(lib, "beta")
    assert cli.main(["init", "skills", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["kind"] == "skill_library"
    spec = json.loads(Path(out["spec"]).read_text(encoding="utf-8"))
    assert spec["kind"] == "skill_library"
    assert spec["layout"] == "skill_library"


def test_algorithms_run_evoskill_on_library(tmp_path, capsys, monkeypatch):
    monkeypatch.chdir(tmp_path)
    lib = tmp_path / "skills"
    _skill(lib, "alpha")
    _skill(lib, "beta")
    cli.main(["algorithms", "run", "evoskill", "skills", "--json"])
    capsys.readouterr()
    spec = json.loads((tmp_path / "agentdescent.evoskill.spec.json")
                      .read_text(encoding="utf-8"))
    assert spec["kind"] == "skill_library"
    assert spec["algorithm"]["name"] == "evoskill"
