"""`algorithm: evoskill` keeps each directory kind's safety rails (#604, #615 review).

evoskill brings its own strategy class (`SkillLibraryTree`); it must be built
over the `FileTree` compose resolved for the kind, not replace it.
"""

from __future__ import annotations

import pytest

from agentdescent.algorithms.evoskill import (INDEX_BEGIN, LIBRARY, SINGLE_SKILL,
                                              SkillLibraryTree)
from agentdescent.evolvespec import EvolveSpec, SpecError, compose
from agentdescent.runners import PLUGIN_FROZEN
from agentdescent.skillspec import SkillTreeValidator

ROWS = [{"prompt": f"what is {i}", "gold": f"zzz{i}"} for i in range(8)]
SKILL = "---\nname: myskill\ndescription: does a thing\n---\n# My skill\nbody\n"


def _plugin(tmp_path):
    root = tmp_path / "plug"
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name": "plug"}')
    (root / "hooks").mkdir()
    (root / "hooks" / "hooks.json").write_text("{}")
    (root / "src").mkdir()
    (root / "src" / "index.ts").write_text("export const x = 1;\n")
    return str(root)


def _skill(tmp_path):
    root = tmp_path / "myskill"
    root.mkdir()
    (root / "SKILL.md").write_text(SKILL)
    return str(root)


def _compose(kind, target, **kw):
    base = dict(kind=kind, target=target, data={"inline": ROWS},
                evolve={"rounds": 2, "n_workers": 2, "seed": 0})
    base.update(kw)
    plain = compose(EvolveSpec(**base)).kwargs["strategy"]
    evo = compose(EvolveSpec(**base, algorithm="evoskill")).kwargs["strategy"]
    return plain, evo


def test_plugin_keeps_the_host_frozen_paths_under_evoskill(tmp_path):
    plain, evo = _compose("plugin", _plugin(tmp_path), host="claude_code",
                          agent="echo", frozen=["README.md"])
    assert isinstance(evo, SkillLibraryTree) and evo.layout == LIBRARY
    assert list(evo.frozen) == list(plain.frozen) == \
        list(PLUGIN_FROZEN["claude_code"]) + ["README.md"]
    assert not evo.writable("hooks/hooks.json")
    assert not evo.writable(".claude-plugin/marketplace.json")
    # Same writability as the kind's own FileTree, path for path.
    for path in ("hooks/hooks.json", "src/permissions.ts", "README.md",
                 "skills/permission-check/SKILL.md", "skills/a/SKILL.md"):
        assert evo.writable(path) == plain.writable(path), path
    d = evo.to_diff({}, "csv totals :: sum the column", "w", 0, "a")
    assert set(d.ops) == {"skills/csv-totals/SKILL.md"}
    assert "sum the column" in d.ops["skills/csv-totals/SKILL.md"]
    assert d.ops["skills/csv-totals/SKILL.md"].startswith("---")


def test_plugin_code_is_in_the_evolved_state_under_evoskill(tmp_path):
    plain, evo = _compose("plugin", _plugin(tmp_path), host="claude_code", agent="echo")
    assert "src/index.ts" in plain.initial()
    assert evo.initial() == plain.initial()
    assert evo.max_file_bytes == plain.max_file_bytes


def test_skill_dir_keeps_the_skill_md_gate_under_evoskill(tmp_path):
    plain, evo = _compose("skill_dir", _skill(tmp_path), agent="opencode")
    assert [repr(v) for v in evo.validators] == [repr(v) for v in plain.validators] == \
        [repr(SkillTreeValidator("myskill"))]
    # A proposal that would break the root skill is never returned.
    broken = dict(evo.initial(), **{"SKILL.md": "no frontmatter"})
    assert evo.to_diff(broken, "csv totals :: sum it", "w", 0, "a") is None
    assert evo.structural_rejections["skill-no-frontmatter"] == 1


def test_skill_dir_induces_a_linked_reference_not_a_nested_skill(tmp_path):
    _, evo = _compose("skill_dir", _skill(tmp_path), agent="opencode")
    assert evo.layout == SINGLE_SKILL
    state = evo.initial()
    d = evo.to_diff(state, "csv totals :: Sum the column.\n- skip headers", "w", 0, "a")
    assert set(d.ops) == {"references/csv-totals.md", "SKILL.md"}
    assert not any(p.startswith("skills/") for p in d.ops)
    root = d.ops["SKILL.md"]
    assert root.startswith(SKILL.rstrip("\n"))          # frontmatter and body kept
    assert "- [csv-totals](references/csv-totals.md)" in root
    # A second rule rewrites the managed block in place instead of appending another.
    state = {**state, **d.ops}
    d2 = evo.to_diff(state, "header rows :: Find the header.", "w", 1, "a")
    root2 = d2.ops["SKILL.md"]
    assert root2.count(INDEX_BEGIN) == 1
    assert "references/csv-totals.md" in root2 and "references/header-rows.md" in root2
    # Editing an existing rule does not touch an unchanged index.
    state = {**state, **d2.ops}
    d3 = evo.to_diff(state, "csv totals :: Sum it twice.", "w", 2, "a")
    assert d3.ops == {"references/csv-totals.md": "Sum it twice."}


def test_skill_dir_with_a_frozen_root_skill_md_induces_nothing(tmp_path):
    _, evo = _compose("skill_dir", _skill(tmp_path), agent="opencode", frozen=["SKILL.md"])
    assert evo.to_diff(evo.initial(), "csv totals :: sum it", "w", 0, "a") is None


def test_agent_dir_keeps_the_library_layout(tmp_path):
    (tmp_path / "AGENT.md").write_text("# agent\n")
    plain, evo = _compose("agent_dir", str(tmp_path), agent="opencode", frozen=["AGENT.md"])
    assert evo.layout == LIBRARY and list(evo.frozen) == ["AGENT.md"]
    assert evo.initial() == plain.initial()


def test_a_layout_typo_is_an_error():
    with pytest.raises(ValueError, match="layout"):
        SkillLibraryTree(layout="nested")


def test_strategy_from_is_refused_on_kind_text():
    from agentdescent import algorithms
    from agentdescent.algorithms import Algorithm, Overrides

    algorithms.register(Algorithm(
        name="_tree_only", summary="t", kinds=("text",), fidelity="mechanism_microport",
        params=(), build=lambda ctx, p: Overrides(strategy_from=lambda base: base)))
    try:
        with pytest.raises(SpecError, match="directory tree"):
            compose(EvolveSpec(kind="text", target="Be helpful.", data={"inline": ROWS},
                               agent="echo", algorithm="_tree_only"))
    finally:
        algorithms._REGISTRY.pop("_tree_only", None)


def _library(tmp_path):
    root = tmp_path / "lib"
    for name in ("alpha", "beta"):
        d = root / name
        d.mkdir(parents=True)
        (d / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: skill {name}\n---\n# {name}\n")
    return str(root)


def test_skill_library_uses_library_layout_under_evoskill(tmp_path):
    """#824/#838: kind=skill_library + evoskill → top-level <slug>/SKILL.md."""
    plain, evo = _compose("skill_library", _library(tmp_path), agent="opencode")
    assert isinstance(evo, SkillLibraryTree) and evo.layout == LIBRARY
    assert evo.library_root == ""
    d = evo.to_diff({}, "csv totals :: sum the column", "w", 0, "a")
    assert set(d.ops) == {"csv-totals/SKILL.md"}
    body = d.ops["csv-totals/SKILL.md"]
    assert body.startswith("---")
    assert "name: csv-totals" in body
    assert "sum the column" in body
    # Edit reuses the top-level path (does not fork under skills/)
    state = {**evo.initial(), **d.ops}
    d2 = evo.to_diff(state, "alpha :: updated alpha body", "w", 1, "a")
    assert "alpha/SKILL.md" in d2.ops
    assert not any(p.startswith("skills/") for p in d2.ops)
    assert d2.ops["alpha/SKILL.md"].startswith("---")
    assert "name: alpha" in d2.ops["alpha/SKILL.md"]


def test_plan_echoes_evoskill_library_layout_for_skill_library(tmp_path):
    from agentdescent.cli import plan_payload
    root = _library(tmp_path)
    spec = EvolveSpec(
        kind="skill_library", target=root, data={"inline": ROWS},
        agent="opencode", algorithm="evoskill",
        evolve={"rounds": 2, "n_workers": 2, "seed": 0})
    # compose notes include layout=LIBRARY
    from agentdescent.evolvespec import compose
    comp = compose(spec)
    assert any("layout=LIBRARY" in n for n in comp.notes)
    assert any("SINGLE_SKILL" not in n or "skill_dir" in n for n in comp.notes)
    assert isinstance(comp.kwargs["strategy"], SkillLibraryTree)
    assert comp.kwargs["strategy"].layout == LIBRARY


def test_skill_path_top_level_vs_nested():
    from agentdescent.algorithms.evoskill import LIBRARY, SKILL_ROOT, skill_name, skill_path
    assert skill_path("Csv Totals", LIBRARY, library_root="") == "csv-totals/SKILL.md"
    assert skill_path("Csv Totals", LIBRARY, library_root=SKILL_ROOT) == (
        "skills/csv-totals/SKILL.md")
    state = {"alpha/SKILL.md": "---\nname: alpha\n---\n"}
    assert skill_path("alpha", LIBRARY, library_root=SKILL_ROOT, state=state) == (
        "alpha/SKILL.md")
    assert skill_name("alpha/SKILL.md") == "alpha"
    assert skill_name("skills/beta/SKILL.md") == "beta"


def test_library_validator_rejects_missing_frontmatter_on_top_level(tmp_path):
    """Nested skills/ paths used to skip SkillLibraryValidator (#838)."""
    from agentdescent.skillspec import SkillLibraryValidator
    plain, evo = _compose("skill_library", _library(tmp_path), agent="opencode")
    assert evo.library_root == ""
    bad = {**evo.initial(), "gamma/SKILL.md": "no yaml here"}
    assert SkillLibraryValidator()(bad) is not None
