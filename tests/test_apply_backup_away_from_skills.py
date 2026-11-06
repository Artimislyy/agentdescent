"""Directory apply backups must not sit beside the skill (#758)."""

import os

from agentdescent.evolution import EvolutionResult, _file_tree_backup_path
from agentdescent.filetree import canonical, load_tree


def _result(state):
    return EvolutionResult(state=state, rendered=canonical(state), final_reward=0.0,
                           history=[], ledger_log=[])


def test_file_tree_backup_is_under_agentdescent_home(tmp_path, monkeypatch):
    home = tmp_path / "ad-home"
    monkeypatch.setenv("AGENTDESCENT_HOME", str(home))
    skills = tmp_path / "opencode" / "skill"
    dest = skills / "date-skill"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text(
        "---\nname: date-skill\n---\nReformat the date.\n", encoding="utf-8")

    plan = _result({"SKILL.md": "---\nname: date-skill\n---\nEuropean format.\n"}).write_to(
        str(dest))
    assert plan["noop"] is False and len(plan["backup"]) == 1
    bak = plan["backup"][0]
    assert bak.startswith(str(home / "backups"))
    assert bak.endswith(os.path.join("bak-0")) or bak.endswith("bak-0")
    # No sibling shadow next to the skill
    assert not (skills / "date-skill.bak-0").exists()
    assert sorted(p.name for p in skills.iterdir()) == ["date-skill"]
    assert load_tree(bak)["SKILL.md"].startswith("---\nname: date-skill")
    assert "European format" in (dest / "SKILL.md").read_text(encoding="utf-8")


def test_backup_slots_increment_without_sibling_shadow(tmp_path, monkeypatch):
    home = tmp_path / "ad-home"
    monkeypatch.setenv("AGENTDESCENT_HOME", str(home))
    dest = tmp_path / "skills" / "pdf-audit"
    dest.mkdir(parents=True)
    (dest / "SKILL.md").write_text("v0\n", encoding="utf-8")

    first = _result({"SKILL.md": "v1\n"}).write_to(str(dest))
    (dest / "SKILL.md").write_text("edited\n", encoding="utf-8")
    second = _result({"SKILL.md": "v2\n"}).write_to(str(dest))
    assert first["backup"][0].endswith("bak-0")
    assert second["backup"][0].endswith("bak-1")
    assert first["backup"][0] != second["backup"][0]
    parent = dest.parent
    assert not any(name.startswith("pdf-audit.bak-") for name in os.listdir(parent))


def test_backup_path_helper_sanitises_name(tmp_path, monkeypatch):
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "home"))
    dest = tmp_path / "host" / "weird name!"
    dest.mkdir(parents=True)
    path = _file_tree_backup_path(str(dest))
    assert "weird-name" in path
    assert path.startswith(str(tmp_path / "home" / "backups"))
