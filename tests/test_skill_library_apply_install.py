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


def _make_library_run(tmp_path):
    """Persist one completed offline skill_library run in an isolated store."""
    store = str(tmp_path / "runs")
    src = tmp_path / "seed-lib"
    for name in ("alpha", "beta"):
        d = src / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: seed {name}\n---\n# {name}\n")
    (src / "alpha" / "references").mkdir()
    (src / "alpha" / "references" / "rules.md").write_text("RULE: init\n")
    rd = runstore.create({
        "kind": "skill_library",
        "target": str(src),
        "data": {"inline": [{"prompt": "p", "gold": "g"}],
                 "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": {"ref": "claude_code"},
        "reflect": {"ref": "echo"},
    }, store=store)
    state = {
        "alpha/SKILL.md": "---\nname: alpha\ndescription: evolved alpha\n---\n# alpha\n",
        "alpha/references/rules.md": "RULE: evolved\n",
        "beta/SKILL.md": "---\nname: beta\ndescription: evolved beta\n---\n# beta\n",
    }
    EvolutionResult(
        state=state, rendered=canonical(state), final_reward=1.0,
        history=[], ledger_log=[]).save(rd.result_path)
    rd.update_status(state="done")
    return store, rd.run_id


_HOST_REL_CASES = (
    ("claude-code", (".claude", "skills")),
    ("claude", (".claude", "skills")),
    ("codex", (".codex", "skills")),
    ("opencode", (".config", "opencode", "skill")),
    ("open-code", (".config", "opencode", "skill")),
    ("dsh", (".dsh", "skills")),
    ("deepseek-harness", (".dsh", "skills")),
)


@pytest.mark.parametrize("host_arg,rel_parts", _HOST_REL_CASES)
def test_cli_apply_install_to_host_name_respects_home_wins(
        tmp_path, monkeypatch, capsys, host_arg, rel_parts):
    """#935: known host names/aliases map to host skills root and --home wins."""
    from agentdescent.cli import main

    store, rid = _make_library_run(tmp_path)
    fake_home = tmp_path / "fake-home"
    elsewhere = tmp_path / "elsewhere"
    monkeypatch.setenv("AGENTDESCENT_HOME", str(tmp_path / "ad-home"))
    monkeypatch.setenv("CODEX_HOME", str(elsewhere / "codex"))
    monkeypatch.setenv("DSH_HOME", str(elsewhere / "dsh"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(elsewhere / "xdg"))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(elsewhere / "claude"))

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    expected = fake_home.joinpath(*rel_parts)
    (expected / "unrelated").mkdir(parents=True)
    (expected / "unrelated" / "SKILL.md").write_text("---\nname: unrelated\n---\n")

    rc = main(["--store", store, "apply", rid, "--install-to", host_arg,
               "--home", str(fake_home), "--dry-run"])
    assert rc == 0
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["dest"] == str(expected)
    assert f"install-to {host_arg} -> {expected}" in cap.err
    assert not (work / host_arg).exists()
    assert not (expected / "alpha").exists()

    rc = main(["--store", store, "apply", rid, "--install-to", host_arg,
               "--home", str(fake_home)])
    assert rc == 0
    capsys.readouterr()
    assert (expected / "alpha" / "SKILL.md").is_file()
    assert (expected / "alpha" / "references" / "rules.md").is_file()
    assert (expected / "beta" / "SKILL.md").is_file()
    assert (expected / "unrelated" / "SKILL.md").is_file()
    assert not elsewhere.exists()


@pytest.mark.parametrize("host_arg,env_var,rel_parts", (
    ("codex", "CODEX_HOME", ("skills",)),
    ("dsh", "DSH_HOME", ("skills",)),
    ("opencode", "XDG_CONFIG_HOME", ("opencode", "skill")),
    ("claude-code", "CLAUDE_CONFIG_DIR", ("skills",)),
))
def test_resolve_apply_dest_honours_host_env_vars_without_home(
        tmp_path, monkeypatch, host_arg, env_var, rel_parts):
    """When --home is omitted, ambient host env vars apply like install/doctor."""
    monkeypatch.chdir(tmp_path)
    custom = tmp_path / "env-root"
    monkeypatch.setenv(env_var, str(custom))
    assert resolve_apply_dest(None, host_arg) == str(custom.joinpath(*rel_parts))


def test_cli_apply_install_to_local_collision_and_dot_slash_path(
        tmp_path, monkeypatch, capsys):
    """Existing cwd entry with host name stays a path + emits ambiguity note."""
    from agentdescent.cli import main

    evolved = tmp_path / "evolved"
    (evolved / "alpha").mkdir(parents=True)
    (evolved / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")

    work = tmp_path / "work"
    work.mkdir()
    local_codex = work / "codex"
    local_codex.mkdir()
    fake_home = tmp_path / "fake-home"
    monkeypatch.chdir(work)

    # Same-named dir in cwd: preserve path semantics + warn of ambiguity.
    rc = main(["apply", "--from", str(evolved), "--install-to", "codex",
               "--home", str(fake_home), "--dry-run"])
    assert rc == 0
    cap = capsys.readouterr()
    out = json.loads(cap.out)
    assert out["dest"] == str(local_codex)
    assert "./codex" in cap.err
    assert not (fake_home / ".codex" / "skills").exists()

    # Explicit ./opencode never resolves to the OpenCode host root even if absent,
    # and passing --home for a path destination notes that --home was ignored.
    rc = main(["apply", "--from", str(evolved), "--install-to", "./opencode",
               "--home", str(fake_home), "--dry-run"])
    assert rc == 0
    cap2 = capsys.readouterr()
    out2 = json.loads(cap2.out)
    assert out2["dest"] == str(work / "opencode")
    assert "--home" in cap2.err
    assert not (fake_home / ".config" / "opencode").exists()


@pytest.mark.parametrize("grok_name", ("grok-bot", "grok"))
def test_cli_apply_install_to_grok_bot_refuses_writes_and_lists_paths(
        tmp_path, monkeypatch, capsys, grok_name):
    """#935: grok-bot writes nothing, exits 2, and lists user-skill paths."""
    from agentdescent.cli import main

    store, rid = _make_library_run(tmp_path)
    fake_home = tmp_path / "fake-home"
    grok_ro = tmp_path / "grok-ro"
    monkeypatch.setenv("AGENTDESCENT_GROK_BOT_SKILLS", str(grok_ro))

    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    # 1) --from <dir>
    evolved = tmp_path / "evolved"
    for name in ("alpha", "beta"):
        d = evolved / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(f"---\nname: {name}\n---\n")

    rc = main(["apply", "--from", str(evolved), "--install-to", grok_name,
               "--home", str(fake_home)])
    assert rc == 2
    err = capsys.readouterr().err
    assert "ask Grok Bot to save" in err
    assert "user skill" in err
    assert str((evolved / "alpha" / "SKILL.md").resolve()) in err
    assert str((evolved / "beta" / "SKILL.md").resolve()) in err
    assert not (work / grok_name).exists()
    assert not grok_ro.exists()
    assert not (fake_home / "agent-data" / "workflows").exists()

    # 2) <run_id> (--dry-run too must exit 2 and write nothing)
    rc2 = main(["--store", store, "apply", rid, "--install-to", grok_name,
                "--home", str(fake_home), "--dry-run"])
    assert rc2 == 2
    err2 = capsys.readouterr().err
    assert "ask Grok Bot to save" in err2
    assert "user skill" in err2
    assert "alpha" in err2 and "beta" in err2 and "SKILL.md" in err2
    assert not (work / grok_name).exists()
    assert not grok_ro.exists()


def test_mcp_apply_matches_cli_host_resolution_and_grok_refusal(
        tmp_path, monkeypatch):
    """MCP apply(install_to=...) shares CLI host mapping and grok-bot refusal."""
    from agentdescent.mcp import Tools

    store, rid = _make_library_run(tmp_path)
    fake_home = tmp_path / "fake-home"
    work = tmp_path / "work"
    work.mkdir()
    monkeypatch.chdir(work)

    tools = Tools(store)
    expected = fake_home / ".codex" / "skills"
    plan = tools.apply(run_id=rid, install_to="codex", home=str(fake_home),
                       dry_run=True)
    assert plan["dest"] == str(expected)
    assert not (expected / "alpha").exists()

    done = tools.apply(run_id=rid, install_to="codex", home=str(fake_home))
    assert done["dest"] == str(expected)
    assert (expected / "alpha" / "SKILL.md").is_file()

    evolved = tmp_path / "evolved"
    (evolved / "alpha").mkdir(parents=True)
    (evolved / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    grok = tools.apply(source=str(evolved), install_to="grok-bot",
                       home=str(fake_home))
    assert "error" in grok
    assert "ask Grok Bot to save" in grok["error"]
    assert "user skill" in grok["error"]
    assert str((evolved / "alpha" / "SKILL.md").resolve()) in grok["error"]
    assert not (work / "grok-bot").exists()


def test_resolve_apply_dest_host_to_parity_and_empty_home_refused(
        tmp_path, monkeypatch):
    """--to agreeing with --install-to host succeeds; mismatches & empty --home fail."""
    from agentdescent.cli import main
    from agentdescent.integrations import host_skills_dir

    monkeypatch.chdir(tmp_path)
    fake_home = tmp_path / "home"
    codex_dir = fake_home / ".codex" / "skills"
    assert resolve_apply_dest(
        str(codex_dir), "codex", home=str(fake_home)) == str(codex_dir)
    with pytest.raises(runstore.RunStoreError, match="disagree"):
        resolve_apply_dest(str(tmp_path / "other"), "codex", home=str(fake_home))

    assert host_skills_dir("grok-bot", home=str(fake_home)) is None
    with pytest.raises(ValueError, match="unknown host"):
        host_skills_dir("emacs", home=str(fake_home))

    # Tilde expansion + trailing slash normpath comparison against a resolved host.
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setenv("HOME", str(fake_home))
    monkeypatch.setenv("USERPROFILE", str(fake_home))
    assert resolve_apply_dest("~/.codex/skills/", "codex") == str(codex_dir)
    with pytest.raises(runstore.RunStoreError, match="disagree"):
        resolve_apply_dest("~/.codex/other/", "codex")

    evolved = tmp_path / "evolved"
    (evolved / "alpha").mkdir(parents=True)
    (evolved / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    assert main(["apply", "--from", str(evolved), "--install-to", "codex",
                 "--home", "", "--dry-run"]) == 2


def test_cli_apply_json_error_payload(tmp_path, monkeypatch, capsys):
    """apply --json emits structured error JSON cleanly on CLI failures."""
    from agentdescent.cli import main

    evolved = tmp_path / "evolved"
    (evolved / "alpha").mkdir(parents=True)
    (evolved / "alpha" / "SKILL.md").write_text("---\nname: alpha\n---\n")
    monkeypatch.chdir(tmp_path)

    rc = main(["--json", "apply", "--from", str(evolved), "--install-to", "grok-bot"])
    assert rc == 2
    cap = capsys.readouterr()
    err_obj = json.loads(cap.out)
    assert err_obj["ok"] is False
    assert "ask Grok Bot to save" in err_obj["error"]
    assert cap.err == ""



