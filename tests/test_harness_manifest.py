"""Harness component manifest: attribution, budgets and frozen safety paths."""

import json

import pytest

from agentdescent import cli
from agentdescent.harness_manifest import (
    HarnessComponent, HarnessManifest, HarnessManifestError, load_manifest,
)


def _manifest(**overrides):
    payload = {
        "schema_version": 1,
        "max_files": 4,
        "max_lines": 100,
        "forbidden_paths": ["secrets/**"],
        "components": [
            {"name": "prompt", "paths": ["prompts/**"],
             "responsibility": "system_prompt", "max_lines": 20},
            {"name": "tools", "paths": ["tools/**"],
             "responsibility": "tool_policy", "max_files": 2},
            {"name": "safety", "paths": ["safety/**"], "frozen": True,
             "responsibility": "safety_memory"},
            {"name": "tests", "paths": ["tests/**"], "frozen": True,
             "responsibility": "rule_bank"},
        ],
    }
    payload.update(overrides)
    return load_manifest(payload)


def test_component_routing_and_tree_globs():
    manifest = _manifest()
    assert manifest.component_for("prompts/system.md").name == "prompt"
    assert manifest.component_for("tools/search.py").name == "tools"
    assert manifest.component_for("safety/policy.md").name == "safety"
    assert manifest.component_for("other.txt") is None
    tree = manifest.tree_kwargs()
    assert set(tree["editable"]) == {"prompts/**", "tools/**"}
    assert set(tree["frozen"]) == {"safety/**", "tests/**"}


def test_valid_edit_passes_with_component_counts():
    manifest = _manifest()
    report = manifest.check({
        "prompts/system.md": "line 1\nline 2\n",
        "tools/search.py": "def search():\n    return []\n",
    })
    assert report["ok"] is True
    assert report["files"] == 2
    assert report["lines"] == 4
    assert {row["name"] for row in report["components"]} == {"prompt", "tools"}


def test_frozen_forbidden_unowned_and_budget_violations():
    manifest = _manifest()
    report = manifest.check({
        "safety/policy.md": "x",
        "secrets/key.txt": "x",
        "unknown.txt": "x",
        "prompts/system.md": "x\n" * 30,
        "tools/a.py": "x",
        "tools/b.py": "x",
        "tools/c.py": "x",
    })
    assert report["ok"] is False
    joined = "\n".join(report["violations"])
    assert "safety/**" in joined or "frozen" in joined
    assert "forbidden_paths" in joined
    assert "no component" in joined
    assert "max_lines" in joined
    assert "max_files" in joined


def test_allowed_paths_and_global_budget():
    manifest = _manifest(allowed_paths=["prompts/**"])
    report = manifest.check({"prompts/a.md": "x", "tools/a.py": "x"})
    assert any("allowed_paths" in row for row in report["violations"])
    with pytest.raises(HarnessManifestError):
        manifest.require_valid({"prompts/a.md": "x", "tools/a.py": "x"})


def test_manifest_validation_errors():
    with pytest.raises(HarnessManifestError):
        HarnessComponent("x", ("a/**",), editable=True, frozen=True)
    with pytest.raises(HarnessManifestError):
        HarnessComponent("x", ("../escape",))
    with pytest.raises(HarnessManifestError):
        HarnessManifest(components=[
            HarnessComponent("a", ("a/**",)),
            HarnessComponent("a", ("b/**",))])
    with pytest.raises(HarnessManifestError):
        load_manifest({"components": []})
    with pytest.raises(HarnessManifestError):
        load_manifest({"schema_version": 2,
                       "components": [{"name": "a", "paths": ["a/**"]}]})


def test_cli_manifest_and_check(tmp_path, capsys):
    spec = tmp_path / "harness.json"
    spec.write_text(json.dumps(_manifest().to_dict()), encoding="utf-8")
    changes = tmp_path / "changes.json"
    changes.write_text(json.dumps({"prompts/system.md": "hello"}), encoding="utf-8")

    assert cli.main(["harness", "manifest", "--spec", str(spec), "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert len(payload["components"]) == 4
    assert payload["tree"]["frozen"] == ["safety/**", "tests/**"]

    assert cli.main(["harness", "check", "--spec", str(spec),
                     "--changes", str(changes), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps({"safety/policy.md": "x"}), encoding="utf-8")
    assert cli.main(["harness", "check", "--spec", str(spec),
                     "--changes", str(bad), "--json"]) == 1
    assert json.loads(capsys.readouterr().out)["ok"] is False

    assert cli.main(["harness", "manifest", "--spec",
                     str(tmp_path / "missing.json"), "--json"]) == 2
    assert json.loads(capsys.readouterr().out)["ok"] is False


def test_read_only_only_manifest_does_not_reopen_paths():
    payload = {"schema_version": 1, "components": [
        {"name": "a", "paths": ["a/**"], "editable": False},
        {"name": "b", "paths": ["b/**"], "frozen": True},
    ]}
    manifest = load_manifest(payload)
    tree = manifest.tree_kwargs()
    assert tree["editable"] == ()
    assert set(tree["frozen"]) == {"a/**", "b/**"}
    assert manifest.check({"a/x": "x"})["ok"] is False
    assert manifest.check({"other.txt": "x"})["ok"] is False


def test_mixed_manifest_never_falls_back_to_catch_all():
    manifest = _manifest()
    tree = manifest.tree_kwargs()
    assert "**" not in tree["editable"]
    assert set(tree["editable"]) == {"prompts/**", "tools/**"}
