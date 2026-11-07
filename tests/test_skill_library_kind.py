"""EvolveSpec kind=skill_library: KIND_ROWS, compose, init seed, dry plan (#820)."""

from __future__ import annotations

import json
import os
import sys

import pytest

from agentdescent import EvolveSpec, SpecError, compose
from agentdescent.cli import (count_library_skills, ensure_skill_library_tree,
                              main, starter_spec)
from agentdescent.evolvespec import KIND_ROWS, KINDS
from agentdescent.governance import SKILL_BLAST_RADIUS
from agentdescent.skillspec import SkillLibraryValidator, skill_names_in_library
from agentdescent.treestrategy import FileTree

_ALPHA = """\
---
name: example-alpha
description: Example library skill A. Replace with a real skill.
---
# example-alpha
body
"""

_BETA = """\
---
name: example-beta
description: Example library skill B. Replace with a real skill.
---
# example-beta
body
"""

_AGENT_SRC = (
    "import os,sys;"
    "print('ok')"
)


def _library(tmp):
    root = os.path.join(tmp, "skills-lib")
    for name, body in (("example-alpha", _ALPHA), ("example-beta", _BETA)):
        d = os.path.join(root, name)
        os.makedirs(d)
        open(os.path.join(d, "SKILL.md"), "w").write(body)
    return root


def _agent_ref():
    return {"ref": "cli_agent", "command": [sys.executable, "-c", _AGENT_SRC]}


def test_kinds_include_skill_library():
    assert "skill_library" in KINDS
    assert set(KIND_ROWS) == set(KINDS)
    row = KIND_ROWS["skill_library"]
    assert row["strategy"] == "FileTree"
    assert row["run"] == "tree_runner"
    assert row["blast_radius"] == "SKILL_BLAST_RADIUS"


def test_compose_skill_library_resolves_layout(tmp_path):
    root = _library(str(tmp_path))
    rows = [{"prompt": f"q{i}", "gold": "ok"} for i in range(8)]
    spec = EvolveSpec(
        kind="skill_library", target=root, layout="skill_library",
        data={"inline": rows}, score="exact", agent=_agent_ref(),
        reflect={"ref": "echo"},
        evolve={"rounds": 2, "n_workers": 2, "seed": 0},
        prompt_template="{prompt}",
    )
    comp = compose(spec)
    assert comp.layout == "skill_library"
    assert any("kind='skill_library'" in n and "layout='skill_library'" in n
               for n in comp.notes)
    assert isinstance(comp.kwargs["strategy"], FileTree)
    assert comp.kwargs["blast_radius"] == SKILL_BLAST_RADIUS
    assert any(isinstance(v, SkillLibraryValidator)
               for v in comp.kwargs["strategy"].validators)
    names = skill_names_in_library(comp.tree or {})
    assert set(names) == {"example-alpha", "example-beta"}


def test_compose_refuses_plain_completion_on_skill_library(tmp_path):
    root = _library(str(tmp_path))
    spec = EvolveSpec(
        kind="skill_library", target=root,
        data={"inline": [{"prompt": "q", "gold": "a"}] * 8},
        agent="echo")
    with pytest.raises(SpecError, match="WorkspaceAgent"):
        compose(spec)


def test_ensure_skill_library_seeds_two_skills(tmp_path):
    root = tmp_path / "empty-lib"
    root.mkdir()
    assert count_library_skills(str(root)) == 0
    written = ensure_skill_library_tree(str(root))
    assert len(written) == 2
    assert count_library_skills(str(root)) == 2
    assert ensure_skill_library_tree(str(root)) == []  # idempotent


def test_init_kind_skill_library_writes_spec_and_seeds(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    root = tmp_path / "my-lib"
    root.mkdir()
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(
        json.dumps({"prompt": f"q{i}", "gold": "a"}) for i in range(8)) + "\n")
    out = tmp_path / "spec.json"
    rc = main(["init", str(root), "--kind", "skill_library",
               "--data", str(cases), "--out", str(out),
               "--agent", "cli_agent"])
    # cli_agent may fail agent mismatch? It's a WorkspaceAgent - should be OK
    # but default command might be needed. init with --agent cli_agent without
    # command still writes; plan would need a command. Just check seed + kind.
    assert rc == 0
    spec = json.loads(out.read_text())
    assert spec["kind"] == "skill_library"
    assert spec["layout"] == "skill_library"
    assert count_library_skills(str(root)) >= 2
    captured = capsys.readouterr().out
    assert "seeded" in captured or "example-alpha" in captured or "SKILL.md" in captured


def test_plan_echoes_kind_and_layout(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    root = _library(str(tmp_path))
    cases = tmp_path / "cases.jsonl"
    cases.write_text("\n".join(
        json.dumps({"prompt": f"q{i}", "gold": "ok"}) for i in range(8)) + "\n")
    spec_path = tmp_path / "lib.evolve.json"
    spec = {
        "version": 1, "kind": "skill_library", "target": str(root),
        "layout": "skill_library",
        "data": {"path": str(cases), "prompt": "prompt", "gold": "gold"},
        "score": "exact",
        "agent": _agent_ref(),
        "reflect": {"ref": "echo"},
        "prompt_template": "{prompt}",
        "evolve": {"rounds": 2, "n_workers": 2},
    }
    spec_path.write_text(json.dumps(spec))
    rc = main(["plan", str(spec_path), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["kind"] == "skill_library"
    assert payload["layout"] == "skill_library"


def test_starter_spec_sets_layout():
    s = starter_spec("/tmp/x", kind="skill_library", agent="claude_code",
                     agent_explicit=True)
    assert s["kind"] == "skill_library"
    assert s["layout"] == "skill_library"
