"""Offline tests for `examples/skill_library_evolution.py`."""

from __future__ import annotations

import os
import socket
import urllib.request

from examples.skill_library_evolution import (
    SKILL_NAMES, estimate_calls, evolve_library, library_validator,
    make_library_dir, make_rows, offline_agent, offline_reflector, to_tasks,
)
from agentdescent import load_tree
from agentdescent.skillspec import parse_skill_frontmatter


def _run(**kw):
    path = make_library_dir()
    return path, evolve_library(
        path, to_tasks(make_rows(16)), agent=offline_agent(),
        reflect_with=offline_reflector(),
        rounds=4, n_workers=2, max_concurrency=1, **kw)


def test_seed_two_valid_skills_and_library_fixes_them():
    tree = load_tree(make_library_dir())
    for name in SKILL_NAMES:
        fm = parse_skill_frontmatter(tree[f"{name}/SKILL.md"])
        assert fm and fm["name"] == name and fm["description"].strip()
    assert library_validator(tree) is None
    path, result = _run()
    assert result.error is None and result.final_reward == 1.0
    assert "COLUMN: amount" in result.state["csv-total/references/rules.md"]
    assert "FIELD: year" in result.state["date-parse/references/rules.md"]
    assert result.outcomes().get("committed", 0) >= 1
    assert load_tree(path)["csv-total/references/rules.md"].strip() == "COLUMN: id"


def test_unread_or_wrong_library_scores_zero_then_write_to_installs():
    path, tasks = make_library_dir(), to_tasks(make_rows(16))
    before = evolve_library(
        path, tasks, agent=offline_agent(), reflect_with=lambda p: "",
        rounds=1, n_workers=1, max_concurrency=1)
    assert before.final_reward == 0.0
    path2 = make_library_dir()
    for name in SKILL_NAMES:
        os.remove(os.path.join(path2, name, "references", "rules.md"))
    missing = evolve_library(
        path2, to_tasks(make_rows(12)), agent=offline_agent(),
        reflect_with=lambda p: "", rounds=1, n_workers=1, max_concurrency=1)
    assert missing.final_reward == 0.0
    path, result = _run()
    plan = result.write_to(path)
    assert plan["backup"]
    installed = load_tree(path)
    assert "COLUMN: amount" in installed["csv-total/references/rules.md"]
    assert "FIELD: year" in installed["date-parse/references/rules.md"]
    assert {p.split("/", 1)[0] for p in installed if "/" in p} >= set(SKILL_NAMES)


def test_estimate_and_dry_run(monkeypatch, capsys):
    assert estimate_calls(4, 2, 16)["agent_rollouts_upper"] > \
        estimate_calls(2, 2, 16)["agent_rollouts_upper"]
    monkeypatch.setattr(urllib.request, "urlopen",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("net")))
    monkeypatch.setattr(socket, "create_connection",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("net")))
    monkeypatch.setattr("sys.argv", ["skill_library_evolution", "--dry-run"])
    from examples.skill_library_evolution import main
    main()
    out = capsys.readouterr().out
    assert "Library tree:" in out and "csv-total/SKILL.md" in out
    assert "date-parse/SKILL.md" in out and "[dry-run]" in out
