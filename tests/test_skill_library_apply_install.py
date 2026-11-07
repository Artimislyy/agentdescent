"""Path A apply --install-to for skill_library (#823)."""

from __future__ import annotations

import json

import pytest

from agentdescent.cli import resolve_apply_dest
from agentdescent.evolution import EvolutionResult
from agentdescent.filetree import canonical
from agentdescent import runstore


def test_resolve_apply_dest_alias_and_conflict():
    assert resolve_apply_dest(None, "~/skills") == "~/skills"
    assert resolve_apply_dest("/a", None) == "/a"
    assert resolve_apply_dest("/a", "/a") == "/a"
    with pytest.raises(runstore.RunStoreError, match="disagree"):
        resolve_apply_dest("/a", "/b")


def test_write_to_library_leaves_unrelated_host_skills(tmp_path):
    """Evolved keys write; host extras stay (prune=False default) (#823)."""
    host = tmp_path / "claude-skills"
    (host / "unrelated").mkdir(parents=True)
    (host / "unrelated" / "SKILL.md").write_text(
        "---\nname: unrelated\ndescription: keep me\n---\n# unrelated\n")
    state = {
        "csv-total/SKILL.md": "---\nname: csv-total\ndescription: sum\n---\n# csv\n",
        "csv-total/references/rules.md": "COLUMN: amount\n",
        "date-parse/SKILL.md": "---\nname: date-parse\ndescription: year\n---\n# date\n",
    }
    result = EvolutionResult(
        state=state, rendered=canonical(state), final_reward=1.0,
        history=[], ledger_log=[])
    plan = result.write_to(str(host), backup=True, dry_run=False)
    assert not plan["noop"]
    assert (host / "csv-total" / "SKILL.md").is_file()
    assert (host / "date-parse" / "SKILL.md").is_file()
    assert (host / "unrelated" / "SKILL.md").is_file(), "must not prune unrelated"
    assert any("unrelated" in e for e in plan.get("extra", []))


def test_cli_install_to_dry_run_then_write(tmp_path, monkeypatch, capsys):
    from agentdescent.cli import main

    host = tmp_path / "skills-root"
    host.mkdir()
    (host / "keep-me").mkdir()
    (host / "keep-me" / "SKILL.md").write_text(
        "---\nname: keep-me\ndescription: stay\n---\n# keep\n")

    evolved = tmp_path / "evolved"
    for name in ("alpha", "beta"):
        d = evolved / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: evolved {name}\n---\n# {name}\n")

    monkeypatch.chdir(tmp_path)
    rc = main(["apply", "--from", str(evolved), "--install-to", str(host),
               "--dry-run"])
    assert rc == 0
    out = json.loads(capsys.readouterr().out)
    assert "written" in out or "unchanged" in out
    assert not (host / "alpha").exists()
    assert (host / "keep-me" / "SKILL.md").is_file()

    rc = main(["apply", "--from", str(evolved), "--install-to", str(host)])
    assert rc == 0
    assert (host / "alpha" / "SKILL.md").is_file()
    assert (host / "beta" / "SKILL.md").is_file()
    assert (host / "keep-me" / "SKILL.md").is_file()


def test_cli_to_and_install_to_conflict(tmp_path, monkeypatch, capsys):
    from agentdescent.cli import main
    src = tmp_path / "src"
    src.mkdir()
    (src / "a").mkdir()
    (src / "a" / "SKILL.md").write_text("---\nname: a\ndescription: x\n---\n")
    monkeypatch.chdir(tmp_path)
    rc = main(["apply", "--from", str(src), "--to", str(tmp_path / "a"),
               "--install-to", str(tmp_path / "b")])
    assert rc == 2
    assert "disagree" in capsys.readouterr().err
